#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPMN 流程图重排脚本 —— 无交叉布局（v2，2026-08-16 替换 Dagre 风格旧版）。

旧版（最长路径分层 + 重心排序 + 绕行通道）实测 34 节点图 18 处穿节点 + 4 处
交叉；本版把「无交叉」做成构造性保证，而非路由器去祈祷避免：

  ① 长边虚拟节点化：跨层(span>1)的边拆成虚拟链，图中所有边都变成相邻列边
     → 结构上消除「连线横穿中间列节点」。
  ② 排序以零逆序为收敛判据：相邻层间边逆序数 = 0 时，边在通道内天然有序
     （median 双向 sweep + transpose 逐对换位精化 + 固定 seed 随机重启）。
  ③ 坐标保序落位：主链锚主流道、虚拟链整链同走廊 y、其余按相邻列前驱均值
     对齐——能对齐的直线连接，不能的退化为一次直角转。
  ④ 列间通道轨道 x 分配：同 gap 竖直段各占一轨，消除共线重叠；
     出入口一律边沿中点（连线不与节点视觉脱离）。

流程语义零改动：只重写 BPMNDiagram 的 dc:Bounds / di:waypoint。

位置：platforms/demo/formats/bpmn-kit/relayout.py（ITSM 领域知识，非 skill
     通用件）。用法:
    python3 relayout.py <bpmn文件> [-o 输出.bpmn] [--svg 预览.svg] [--no-strict]
    库：sys.path.insert(0,'formats/bpmn-kit'); from relayout import relayout_xml
      （XML 串进出，供 build-process / relayout-process-diagram flow 内联调用）

纯标准库。CLI 自带几何校验，三主指标（节点重叠 / 连线穿节点 / 边-边交叉）
非零 → 退出码 1（--no-strict 降级）。
"""

import argparse
import io
import math
import os
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import deque

# ---------------------------------------------------------------- 常量与命名空间
NS = {
    # 前缀统一用 "bpmn"（而非源文件的 bpmn2）——命名空间 URI 不变，语义等价
    "bpmn":     "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi":   "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc":       "http://www.omg.org/spec/DD/20100524/DC",
    "di":       "http://www.omg.org/spec/DD/20100524/DI",
    "flowable": "http://flowable.org/bpmn",
    "camunda":  "http://camunda.org/schema/1.0/bpmn",
    "xsi":      "http://www.w3.org/2001/XMLSchema-instance",
}
for p, u in NS.items():
    ET.register_namespace(p, u)

SVG_NS = "http://www.w3.org/2000/svg"


def q(p, tag):
    return f"{{{NS[p]}}}{tag}"


# 布局常量（px）
MARGIN_X, MARGIN_Y = 60, 60
COL_GAP, ROW_GAP = 120, 40      # 列间距 / 行间距
EPS = 1e-9


def node_size(kind):
    """各节点类型的标准尺寸（bpmn.io 约定）"""
    if "Gateway" in kind:
        return 50, 50
    if "Event" in kind:
        return 36, 36
    return 100, 80              # task / callActivity / subProcess ...


def tag_name(elem):
    return elem.tag.split("}")[-1]


def load_xml(path):
    """支持 .bpmn/.xml，也支持 .md 中内嵌的 XML 片段"""
    try:
        return ET.parse(path)
    except ET.ParseError:
        with open(path, encoding="utf-8") as f:
            m = re.search(r'<\?xml.*?(</\w+:definitions>|</definitions>)',
                          f.read(), re.S)
        if not m:
            sys.exit("错误: 无法解析文件，也不是内嵌 BPMN XML 的 markdown")
        return ET.parse(io.StringIO(m.group(0)))


# ---------------------------------------------------------------- 1. 解析流程
def parse_process(proc):
    """返回 nodes: id→kind；edges: [(fid, src, dst)]；meta: fid→(name, cond)"""
    nodes, edges, meta = {}, [], {}
    for child in proc:
        kind = tag_name(child)
        if kind == "sequenceFlow":
            fid = child.get("id")
            edges.append((fid, child.get("sourceRef"), child.get("targetRef")))
            cond = child.find(q("bpmn", "conditionExpression"))
            meta[fid] = (child.get("name") or "",
                         (cond.text or "").strip() if cond is not None else "")
        elif child.get("id"):
            nodes[child.get("id")] = kind
    return nodes, edges, meta


# ---------------------------------------------------------------- 2. 图算法
def remove_cycles(nodes, edges):
    """DFS 灰边检测回边。回边不参与分层/排序/虚拟化，路由阶段走 bottom 绕行。"""
    succs = {n: [] for n in nodes}
    for _, s, t in edges:
        if s in nodes and t in nodes:
            succs[s].append(t)
    color, back = {}, set()

    def _dfs(u):
        color[u] = 1
        for v in succs[u]:
            if color.get(v, 0) == 1:
                back.add((u, v))
            elif color.get(v, 0) == 0:
                _dfs(v)
        color[u] = 2

    for n in nodes:
        if color.get(n, 0) == 0:
            _dfs(n)
    return back


def layer_longest_path(nodes, edges, back):
    """Kahn 最长路径分层：layer[v] = max(layer[pred]) + 1，只走非回边。"""
    preds = {n: [] for n in nodes}
    succs = {n: [] for n in nodes}
    for _, s, t in edges:
        if s in nodes and t in nodes and (s, t) not in back:
            preds[t].append(s)
            succs[s].append(t)
    layer = {}
    indeg = {n: len(preds[n]) for n in nodes}
    queue = deque(sorted(n for n, d in indeg.items() if d == 0))
    while queue:
        nid = queue.popleft()
        base = [layer[p] for p in preds[nid] if p in layer]
        layer[nid] = (max(base) + 1) if base else 0
        for t in succs[nid]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    # 兜底（理论到不了）：剩余按前驱已分层最大值
    for n in nodes:
        if n not in layer:
            base = [layer[p] for p in preds[n] if p in layer]
            layer[n] = (max(base) + 1) if base else 0
    return layer


def insert_virtual_nodes(nodes, edges, layer, back):
    """span>1 的边拆虚拟链。返回 layers:[[vid]], vedges:[(fid,s,t)], chain:{fid→[seq]}。

    虚拟节点 id 用 ':v:' 前缀（BPMN id 不允许冒号，天然不冲突）。
    回边不拆链（整体走 bottom 绕行）。
    """
    n_layers = max(layer.values()) + 1
    layers = [[] for _ in range(n_layers)]
    for nid, l in layer.items():
        layers[l].append(nid)
    vedges, chain = [], {}
    for fid, s, t in edges:
        if s not in layer or t not in layer:
            continue
        if (s, t) in back:
            chain[fid] = [s, t]           # 回边：不拆
            continue
        a, b = layer[s], layer[t]
        if b - a <= 1:
            vedges.append((fid, s, t))
            chain[fid] = [s, t]
            continue
        vids = [f":v:{fid}:{k}" for k in range(a + 1, b)]
        for k, vid in enumerate(vids):
            layers[a + 1 + k].append(vid)
        seq = [s] + vids + [t]
        chain[fid] = seq
        for p_, t_ in zip(seq, seq[1:]):
            vedges.append((fid, p_, t_))
    return layers, vedges, chain


def count_inversions(layers, vedges):
    """相邻层间边逆序数：pos[u1]<pos[u2] 而 pos[v1]>pos[v2] 的边对数。

    只在相邻层间计数（虚拟化后所有段都是相邻层边）。"""
    pos = _pos_of(layers)
    pairs_by_gap = _pairs_by_gap(layers, vedges)
    return sum(_gap_inversions(pairs, pos) for pairs in pairs_by_gap.values())


def _pos_of(layers):
    pos = {}
    for l, items in enumerate(layers):
        for i, v in enumerate(items):
            pos[v] = i
    return pos


def _pairs_by_gap(layers, vedges):
    """gap_l → [(s, t)]（相邻层段；非相邻层段跳过）"""
    layer_idx = {}
    for l, items in enumerate(layers):
        for v in items:
            layer_idx[v] = l
    by_gap = {}
    for fid, s, t in vedges:
        if s not in layer_idx or t not in layer_idx:
            continue
        ls = layer_idx[s]
        if layer_idx[t] != ls + 1:
            continue                       # 非相邻层段（异常），不计
        by_gap.setdefault(ls, []).append((s, t))
    return by_gap


def _gap_inversions(pairs, pos):
    vals = [(pos[s], pos[t]) for s, t in pairs]
    n = 0
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            (a1, b1), (a2, b2) = vals[i], vals[j]
            if (a1 - a2) * (b1 - b2) < 0:
                n += 1
    return n


def order_columns(layers, vedges, kind_of, sweeps=8, restarts=64, seed=42):
    """median 双向 sweep + transpose 精化，判据=总逆序数；固定 seed 随机重启。

    kind_of: vid → kind 字符串（虚拟节点返回 'virtual'）。"""
    def _type_rank(vid):
        k = kind_of(vid)
        if "startEvent" in k:
            return 0
        if "Event" in k:
            return 3
        if "Gateway" in k:
            return 2
        if k == "virtual":
            return 1.5
        return 1

    adj_down, adj_up = {}, {}
    for _, s, t in vedges:
        adj_down.setdefault(s, []).append(t)
        adj_up.setdefault(t, []).append(s)

    def _median_sweep(layers_):
        for sweep in range(sweeps):
            changed = False
            downward = (sweep % 2 == 1)
            rng = range(1, len(layers_)) if downward \
                else range(len(layers_) - 2, -1, -1)
            for k in rng:
                ref = adj_down if downward else adj_up
                pos = {v: i for l2 in layers_ for i, v in enumerate(l2)}
                def bary(v):
                    rel = sorted(pos[r] for r in ref.get(v, []) if r in pos)
                    if not rel:
                        return pos[v]
                    m = len(rel)
                    return rel[m // 2] if m % 2 else (rel[m // 2 - 1]
                                                       + rel[m // 2]) / 2
                new_order = sorted(layers_[k], key=lambda v: (bary(v),
                                                              _type_rank(v), v))
                if new_order != layers_[k]:
                    layers_[k] = new_order
                    changed = True
            if not changed:
                break
        return layers_

    def _transpose(layers_):
        """逐对换位精化。交换 layer k 内相邻两项只影响 gap k-1 与 gap k
        的逆序，用局部增量计数避免全量重算。"""
        pairs_by_gap = _pairs_by_gap(layers_, vedges)
        improved = True
        while improved:
            improved = False
            for k in range(len(layers_)):
                for i in range(len(layers_[k]) - 1):
                    pos = _pos_of(layers_)
                    affected = [pairs_by_gap.get(g, []) for g in (k - 1, k)]
                    before = sum(_gap_inversions(p, pos) for p in affected)
                    layers_[k][i], layers_[k][i + 1] = \
                        layers_[k][i + 1], layers_[k][i]
                    pos = _pos_of(layers_)
                    after = sum(_gap_inversions(p, pos) for p in affected)
                    if after < before:
                        improved = True
                    else:
                        layers_[k][i], layers_[k][i + 1] = \
                            layers_[k][i + 1], layers_[k][i]
        return layers_

    # 候选序列：类型优先级初始排列 + 若干固定 seed 洗牌排列
    init = [sorted(items, key=lambda v: (_type_rank(v), v)) for items in layers]
    rnd = random.Random(seed)
    cands = [init]
    for _ in range(restarts):
        shuffled = [list(items) for items in init]
        for items in shuffled:
            rnd.shuffle(items)
        cands.append(shuffled)

    best, best_inv = None, None
    for cand_layers in cands:
        tried = [list(items) for items in cand_layers]
        tried = _transpose(_median_sweep(tried))
        inv = count_inversions(tried, vedges)
        if best_inv is None or inv < best_inv:
            best, best_inv = tried, inv
        if best_inv == 0:
            break
    return best, best_inv


# ---------------------------------------------------------------- 3. 坐标
def _spine(nodes, edges, back):
    """主链（必经节点集）= dom(end)：所有 start→end 路径的公共节点。

    标准支配集数据流迭代：dom(entry)={entry}; dom(n)={n} ∪ ⋂dom(preds)。
    主链节点锚定主流道 y，形成从左到右的一条水平视线。"""
    start = next((n for n in nodes
                  if "startEvent" in str(nodes[n])), None)
    end = next((n for n in nodes
                if "endEvent" in str(nodes[n])), None)
    if not start or not end:
        return set()
    preds = {n: [] for n in nodes}
    for _, s, t in edges:
        if s in nodes and t in nodes and (s, t) not in back:
            preds[t].append(s)
    dom = {start: {start}}
    changed = True
    while changed:
        changed = False
        for n in nodes:
            if n == start:
                continue
            ps = preds[n]
            ready = [p for p in ps if p in dom]
            if len(ready) < len(ps):
                continue                      # 前驱未全算出，下轮再试
            new = {n} | (set.intersection(*(dom[p] for p in ready))
                        if ready else set())
            if new != dom.get(n):
                dom[n] = new
                changed = True
    return dom.get(end, {end})


# 节点在 Y 方向的占位半高（虚拟节点占小走廊位，只需彼此不共线）
def _occ_h(kind):
    return 20 if kind == "virtual" else node_size(kind)[1] / 2


def _y_gap(ka, kb):
    """相邻两项的最小 y 间距（保证不重叠、不共线）"""
    if ka == "virtual" and kb == "virtual":
        return 16                            # 同列虚拟节点错开即可
    if ka == "virtual" or kb == "virtual":
        return _occ_h(ka) + _occ_h(kb) + ROW_GAP / 2
    return _occ_h(ka) + _occ_h(kb) + ROW_GAP


def assign_coords(layers, kind_of, chain=None, edges=None, back=None,
                  gap_widths=None):
    """X: 列宽 = max 真实节点宽；Y: 保序落位（priority method）。

    「无交叉」依赖列内 y 序 == 排序序（单调），坐标只做两件事：
      1. 诉求（desired y）：
         · 主链节点 → 主流道 y=0（水平视线）
         · 虚拟节点 → 所属长边走廊 y（= 链源真实节点 y，整链水平）
         · 其余真实节点 → 已定 y 前驱的均值（直接相连者对齐）
      2. 保序推挤：主链先落位，其余按序落 desired 并向下避让，
         保证 y 严格递增且间距 ≥ _y_gap。
    能对齐的自然直线连接；不能对齐的退化为一次竖直转（Z 折）。"""
    if gap_widths is None:
        gap_widths = [COL_GAP] * max(1, len(layers) - 1)
    chain = chain or {}
    edges = edges or []
    back = back or set()

    col_widths = []
    for items in layers:
        ws = [node_size(kind_of(v))[0] for v in items if kind_of(v) != "virtual"]
        col_widths.append(max(ws) if ws else 0)
    x = MARGIN_X
    col_x = []
    for l in range(len(layers)):
        col_x.append(x)
        x += col_widths[l] + (gap_widths[l] if l < len(gap_widths) else 0)

    # 前驱表（真实边 + 虚拟链段都算邻接）
    preds = {}
    for fid, seq in chain.items():
        for a, b in zip(seq, seq[1:]):
            preds.setdefault(b, []).append(a)
    # 链 fid → 源真实节点（走廊 y 参照）
    chain_src = {fid: seq[0] for fid, seq in chain.items()
                 if len(seq) >= 2}
    virt_edge = {}
    for fid, seq in chain.items():
        for v in seq[1:-1]:
            virt_edge[v] = fid

    # 主链
    real_kinds = {}
    spine = set()
    if edges:
        for l, items in enumerate(layers):
            for v in items:
                if kind_of(v) != "virtual":
                    real_kinds[v] = kind_of(v)
        spine = _spine(real_kinds, edges, back) & set(real_kinds)

    geo = {}
    for l, items in enumerate(layers):
        # ---- 诉求 ----
        desired = {}
        for v in items:
            k = kind_of(v)
            if v in spine:
                desired[v] = 0.0
            elif k == "virtual":
                src = chain_src.get(virt_edge.get(v))
                desired[v] = geo[src][1] + geo[src][3] / 2 \
                    if src in geo else 0.0
            else:
                # 前驱均值：只取相邻列直连前驱（跨列长边走虚拟链走廊，
                # 不该把节点拉向远处）；有同层网关汇入时也计入
                ps = [p for p in preds.get(v, [])
                      if p in geo and not p.startswith(":v:")]
                if ps:
                    desired[v] = sum(geo[p][1] + geo[p][3] / 2
                                     for p in ps) / len(ps)
                else:
                    desired[v] = 0.0

        # ---- 保序落位：主链先、其余后，都按列内序 ----
        y_of = {}
        fixed_spans = []                      # 已占位区间 (lo, hi)

        def _place(v, y_want, is_spine):
            k = kind_of(v)
            occ = _occ_h(k)
            lo, hi = y_want - occ, y_want + occ
            # 向下避让已占位
            for (flo, fhi) in fixed_spans:
                if lo < fhi and flo < hi:
                    lo = fhi
                    hi = lo + 2 * occ
            y_of[v] = (lo + hi) / 2
            fixed_spans.append((lo, hi))
            return y_of[v]

        for v in [u for u in items if u in spine]:
            _place(v, desired[v], True)
        for v in items:
            if v not in y_of:
                _place(v, desired[v], False)
        # 保证严格递增（防 desired 倒挂）
        for i in range(1, len(items)):
            a, b = items[i - 1], items[i]
            need = _y_gap(kind_of(a), kind_of(b))
            if y_of[b] - y_of[a] < need:
                y_of[b] = y_of[a] + need

        # ---- 写几何 ----
        for v in items:
            k = kind_of(v)
            if k == "virtual":
                geo[v] = (col_x[l] + col_widths[l] / 2, y_of[v], 0, 0)
            else:
                w, h = node_size(k)
                geo[v] = (col_x[l] + (col_widths[l] - w) / 2,
                          y_of[v] - h / 2, w, h)

    # 整体平移：min_y → MARGIN_Y
    min_top = min(g[1] for g in geo.values() if g[3] > 0) \
        if any(g[3] > 0 for g in geo.values()) else 0
    dy = MARGIN_Y - min_top
    geo = {vid: (gx, gy + dy, gw, gh) for vid, (gx, gy, gw, gh) in geo.items()}
    return geo, col_x, col_widths


# ---------------------------------------------------------------- 4. 路由
def _center(geo, vid):
    x, y, w, h = geo[vid]
    return x + w / 2, y + h / 2


def _plan_segments(chain, back, geo, layer_of):
    """把每条真实边拆成段序列：segs[fid] = [(a, b, is_first, is_last), ...]

    回边不拆（整体绕行）。"""
    segs = {}
    for fid, seq in chain.items():
        if len(seq) < 2 or (seq[0], seq[-1]) in back:
            continue
        segs[fid] = [(a, b, k == 0, k == len(seq) - 2)
                     for k, (a, b) in enumerate(zip(seq, seq[1:]))]
    return segs


def route_edges(layers, geo, chain, edges, back, kind_of, col_x, col_widths):
    """列间通道轨道路由。

    每条真实边沿其 chain 逐段路由；每段都是相邻列边：
      - 同轨（中心 y 相同）：直线
      - 否则 Z 折：源右沿出 → 通道内轨道 x 竖转 → 目标左沿入
    轨道 x 按方向规则分配，消除同通道竖直段共线重叠。
    出入口一律走节点边沿中点（不梳状错开——错开会让连线视觉上
    与节点脱离，且零交叉论证依赖「y 序 == 列内序」的单调性）。
    回边走 bottom/top 绕行。"""
    layer_of, order_in = {}, {}
    for l, items in enumerate(layers):
        for i, v in enumerate(items):
            layer_of[v], order_in[v] = l, i

    # ---- 段收集：每段知道自己的 gap / 起止 y / 是否首末段 ----
    segs = _plan_segments(chain, back, geo, layer_of)
    gap_segs = {}                       # gap_l → [seginfo]
    for fid, seg_list in segs.items():
        for (a, b, is_first, is_last) in seg_list:
            l = layer_of[a]
            ay = geo[a][1] + geo[a][3] / 2
            by = geo[b][1] + geo[b][3] / 2
            gap_segs.setdefault(l, []).append({
                "fid": fid, "a": a, "b": b,
                "y0": ay, "y1": by,
                "turn": abs(ay - by) > EPS,
                "is_first": is_first, "is_last": is_last,
            })

    # ---- 轨道分配 ----
    track_x = {}                        # (fid, gap) → x
    for l, seg_infos in gap_segs.items():
        gap_x0 = col_x[l] + col_widths[l]
        gap_x1 = col_x[l + 1]
        turning = [s for s in seg_infos if s["turn"]]
        n = len(turning)
        if n == 0:
            continue
        TURN_MARGIN = 14
        x_lo, x_hi = gap_x0 + TURN_MARGIN, gap_x1 - TURN_MARGIN
        if x_hi <= x_lo:
            x_lo = x_hi = (gap_x0 + gap_x1) / 2
        slots = [x_lo + (x_hi - x_lo) * i / max(1, n - 1)
                 for i in range(n)] if n > 1 else [(x_lo + x_hi) / 2]
        # 方向分组排序（down: y0<y1；up: y0>y1）
        downs = sorted([s for s in turning if s["y0"] < s["y1"]],
                       key=lambda s: (s["y0"], s["y1"], s["fid"]))
        ups = sorted([s for s in turning if s["y0"] >= s["y1"]],
                     key=lambda s: (s["y0"], s["y1"], s["fid"]))
        ordered = downs + ups
        # 分配：downs 从右往左取槽，ups 从左往右取槽（在 downs 之后）
        for i, s in enumerate(ordered):
            if s in downs:
                xi = len(downs) - 1 - i
            else:
                xi = i
            track_x[(s["fid"], l)] = slots[xi]

    # ---- 生成折线 ----
    routes = {}
    back_list = [(fid, s, t) for fid, s, t in edges
                 if s in geo and t in geo and (s, t) in back]
    for fid, s, t in edges:
        if s not in geo or t not in geo:
            continue
        if (s, t) in back:
            continue                      # 回边统一在下面路由
        seg_list = segs.get(fid)
        if not seg_list:
            continue
        pts = []
        for (a, b, is_first, is_last) in seg_list:
            ay = geo[a][1] + geo[a][3] / 2
            ax = geo[a][0] + geo[a][2]
            by = geo[b][1] + geo[b][3] / 2
            bx = geo[b][0]
            l = layer_of[a]
            if abs(ay - by) < EPS:
                seg_pts = [(bx, by)]
            else:
                mx = track_x.get((fid, l),
                                 (col_x[l] + col_widths[l]
                                  + col_x[l + 1]) / 2)
                seg_pts = [(mx, ay), (mx, by), (bx, by)]
            if is_first:
                pts = [(ax, ay)] + seg_pts
            else:
                pts += seg_pts
        routes[fid] = _merge_collinear(pts)

    # ---- 回边：上/下绕行，嵌套车道 + 贪心选侧 ----
    flow_st = {fid: (s, t) for fid, s, t in edges}
    routes.update(_route_back_edges(back_list, geo, flow_st, routes))
    return routes


def _route_back_edges(back_list, geo, flow_st, fixed_routes):
    """回边绕行路由：source 顶/底边出 → 通道横行 → target 顶/底边入。

    层次布局体系中回边是「体系外」的边（排序阶段已剔除），其竖直段可能
    与虚拟链水平段相交——这是本布局器已知限制。缓解措施：
      · 同侧多条回边按深度分层车道（depth*36），互相不共线；
      · 每条回边贪心试上/下两侧，取与现存边交叉少的一侧
        （交叉计数与校验器同规则：共享端点的边对豁免）。
    剩余交叉由校验器如实报告。"""
    if not back_list:
        return {}
    min_top = min(g[1] for g in geo.values())
    max_bottom = max(g[1] + g[3] for g in geo.values())

    def _loop_pts(s, t, side, depth):
        sx, sy, sw, sh = geo[s]
        tx, ty, tw, th = geo[t]
        scx, tcx = sx + sw / 2, tx + tw / 2
        lane_y = (max_bottom + 60 + depth * 36) if side == "bottom" \
            else (min_top - 60 - depth * 36)
        if side == "bottom":
            return [(scx, sy + sh), (scx, lane_y), (tcx, lane_y),
                    (tcx, ty + th)]
        return [(scx, sy), (scx, lane_y), (tcx, lane_y), (tcx, ty)]

    def _crossings(route, my_st, others):
        n = 0
        for oid, pts in others.items():
            st = flow_st.get(oid)
            if st and set(st) & set(my_st):
                continue                  # 共享端点的边对豁免
            for p1, p2 in segments(route):
                for p3, p4 in segments(pts):
                    if seg_intersect_strict((p1, p2), (p3, p4)):
                        n += 1
        return n

    # 贪心：跨度降序逐条放置，每条试两侧取交叉少者（平手取 bottom）
    chosen, placed = {}, {}
    for fid, s, t in sorted(back_list,
                            key=lambda e: -abs(geo[e[1]][0] - geo[e[2]][0])):
        scores, trials = {}, {}
        for side in ("top", "bottom"):
            depth = sum(1 for sd in chosen.values() if sd == side)
            trials[side] = _loop_pts(s, t, side, depth)
            others = dict(fixed_routes)
            others.update(placed)
            scores[side] = _crossings(trials[side], (s, t), others)
        side = "bottom" if scores["bottom"] <= scores["top"] else "top"
        chosen[fid] = side
        placed[fid] = trials[side]
    return placed


def _merge_collinear(pts):
    """合并共线连续点；再合并同轴抖动。"""
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) < EPS and abs(p[1] - out[-1][1]) < EPS:
            continue
        out.append(p)
    # 三点共线去中点
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < EPS and abs(b[0] - c[0]) < EPS) or \
           (abs(a[1] - b[1]) < EPS and abs(b[1] - c[1]) < EPS):
            del out[i]
        else:
            i += 1
    return out


# ---------------------------------------------------------------- 5. 几何校验
def segments(pts):
    """折线拆正交段（丢弃零长度段）；非正交段按采样拆水平/垂直近似。"""
    segs = []
    for p1, p2 in zip(pts, pts[1:]):
        if abs(p1[0] - p2[0]) < EPS and abs(p1[1] - p2[1]) < EPS:
            continue
        segs.append((p1, p2))
    return segs


def _h_or_v(p1, p2):
    if abs(p1[1] - p2[1]) < EPS:
        return "h"
    if abs(p1[0] - p2[0]) < EPS:
        return "v"
    return "?"


def seg_intersect_strict(s1, s2):
    """两条正交段的严格相交（端点接触不算）。

    水平×垂直：交点在双方开区间内才 True。
    平行共线：开区间重叠 → True（重叠段，视觉上按交叉处理）。"""
    t1, t2 = _h_or_v(*s1), _h_or_v(*s2)
    p1a, p1b = s1
    p2a, p2b = s2

    def _ov(lo1, hi1, lo2, hi2):
        return max(lo1, lo2) < min(hi1, hi2) - EPS

    if t1 == "h" and t2 == "v":
        return (min(p1a[0], p1b[0]) + EPS < p2a[0] < max(p1a[0], p1b[0]) - EPS
                and min(p2a[1], p2b[1]) + EPS < p1a[1] < max(p2a[1], p2b[1]) - EPS)
    if t1 == "v" and t2 == "h":
        return (min(p1a[1], p1b[1]) + EPS < p2a[1] < max(p1a[1], p1b[1]) - EPS
                and min(p2a[0], p2b[0]) + EPS < p1a[0] < max(p2a[0], p2b[0]) - EPS)
    if t1 == t2 and t1 in ("h", "v"):
        if t1 == "h":
            if abs(p1a[1] - p2a[1]) > EPS:
                return False
            return _ov(min(p1a[0], p1b[0]), max(p1a[0], p1b[0]),
                       min(p2a[0], p2b[0]), max(p2a[0], p2b[0]))
        if abs(p1a[0] - p2a[0]) > EPS:
            return False
        return _ov(min(p1a[1], p1b[1]), max(p1a[1], p1b[1]),
                   min(p2a[1], p2b[1]), max(p2a[1], p2b[1]))
    return False


def seg_hits_rect(p1, p2, rect, pad=1.0):
    """线段是否穿过矩形内部（端点/边沿接触豁免）。"""
    x, y, w, h = rect
    L, R, T, B = x + pad, x + w - pad, y + pad, y + h - pad
    if R <= L or B <= T:
        return False
    for i in range(21):
        t = i / 20
        px = p1[0] + (p2[0] - p1[0]) * t
        py = p1[1] + (p2[1] - p1[1]) * t
        if L < px < R and T < py < B:
            return True
    return False


def edge_hits_node(pts, rect):
    return any(seg_hits_rect(p1, p2, rect) for p1, p2 in segments(pts))


def verify(nodes, edges, geo, routes):
    """三主指标几何校验。geo 只含真实节点；routes 是真实边的折线。"""
    # 1. 节点-节点重叠（开区间）
    node_overlap = []
    ids = [n for n in nodes if n in geo]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = geo[ids[i]], geo[ids[j]]
            if a[0] < b[0] + b[2] - EPS and b[0] < a[0] + a[2] - EPS \
               and a[1] < b[1] + b[3] - EPS and b[1] < a[1] + a[3] - EPS:
                node_overlap.append((ids[i], ids[j]))

    # 2. 连线-节点穿越（端点节点豁免）
    through = []
    flow_st = {fid: (s, t) for fid, s, t in edges}
    for fid, pts in routes.items():
        s, t = flow_st.get(fid, (None, None))
        for nid in ids:
            if nid in (s, t):
                continue
            if edge_hits_node(pts, geo[nid]):
                through.append((fid, nid))

    # 3. 边-边交叉（共享端点节点的边对豁免）
    ee = []
    fids = [f for f in routes if f in flow_st]
    for i in range(len(fids)):
        for j in range(i + 1, len(fids)):
            f1, f2 = fids[i], fids[j]
            s1, t1 = flow_st[f1]
            s2, t2 = flow_st[f2]
            if {s1, t1} & {s2, t2}:
                continue
            hit = False
            for p1, p2 in segments(routes[f1]):
                for p3, p4 in segments(routes[f2]):
                    if seg_intersect_strict((p1, p2), (p3, p4)):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                ee.append((f1, f2))
    return {
        "node_overlap": node_overlap,
        "edge_through_node": through,
        "edge_edge_cross": ee,
        "n_nodes": len(ids),
        "n_edges": len(routes),
    }


def _cond_text(meta, fid):
    name, cond = meta.get(fid, ("", ""))
    if name:
        return name
    if cond:
        return cond.strip().strip("${}").strip()
    return ""


def text_width(text):
    """按字符实际宽度估算：全角(CJK)≈16px，半角≈9px"""
    return sum(16 if ord(c) > 0x2E80 else 9 for c in text)


# ---------------------------------------------------------------- 6. 重写 DI
def rebuild_diagram(diagram, proc, nodes, edges, geo, routes, meta):
    plane = diagram.find(q("bpmndi", "BPMNPlane"))
    if plane is None:
        plane = ET.SubElement(diagram, q("bpmndi", "BPMNPlane"))
    plane.set("bpmnElement", proc.get("id"))
    for child in list(plane):
        plane.remove(child)

    name_of = {c.get("id"): c.get("name") for c in proc}

    # ---- 形状 ----
    for nid, kind in nodes.items():
        if nid not in geo:
            continue
        x, y, w, h = geo[nid]
        shape = ET.SubElement(plane, q("bpmndi", "BPMNShape"),
                              {"id": f"{nid}_di", "bpmnElement": nid})
        if "Gateway" in kind:
            shape.set("isMarkerVisible", "true")
        ET.SubElement(shape, q("dc", "Bounds"),
                      {"x": str(int(round(x))), "y": str(int(round(y))),
                       "width": str(int(w)), "height": str(int(h))})
        name = name_of.get(nid)
        if name and ("Event" in kind or "Gateway" in kind):
            lw = int(text_width(name)) + 16
            label = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
            ET.SubElement(label, q("dc", "Bounds"),
                          {"x": str(int(x + w / 2 - lw / 2)),
                           "y": str(int(y + h + 4)),
                           "width": str(lw), "height": "20"})

    # ---- 连线 ----
    for fid, src, dst in edges:
        if fid not in routes:
            continue
        edge = ET.SubElement(plane, q("bpmndi", "BPMNEdge"),
                             {"id": f"{fid}_di", "bpmnElement": fid})
        for px, py in routes[fid]:
            ET.SubElement(edge, q("di", "waypoint"),
                          {"x": str(int(round(px))), "y": str(int(round(py)))})
        name = name_of.get(fid)
        if name:
            lx, ly, lw, lh = _label_bounds(routes[fid], name)
            label = ET.SubElement(edge, q("bpmndi", "BPMNLabel"))
            ET.SubElement(label, q("dc", "Bounds"),
                          {"x": str(int(lx)), "y": str(int(ly)),
                           "width": str(int(lw)), "height": str(int(lh))})


def _label_bounds(pts, text):
    """分支标签：放最长横向段的【右端】、线上方。

    用户约定：有分支名称（分支1/2/3…）的流，标签贴横向段右端——
    靠近目标节点入口，读图时分支语义一目了然。"""
    lw = int(text_width(text)) + 16
    best, best_len = None, -1
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(y1 - y2) < EPS:
            length = abs(x2 - x1)
            if length > best_len:
                best_len = length
                best = (min(x1, x2), max(x1, x2), y1)
    if best is None:
        x, y = pts[0]
        return x, y - 20, lw, 20
    _, x2, y = best
    return x2 - lw - 4, y - 24, lw, 20


# ---------------------------------------------------------------- 7. SVG 渲染
SVG_STYLE = {
    "userTask":       ("#cfe4ff", "#4a7fc1"),
    "serviceTask":    ("#e8dcff", "#7a5fb5"),
    "Gateway":        ("#fff3cd", "#b8860b"),
    "inclusive":      ("#d9f2d9", "#2e8b57"),
    "startEvent":     ("#e0f0e0", "#2e8b57"),
    "endEvent":       ("#ffe0e0", "#c0392b"),
}


def _svg_el(parent, tag, **attrs):
    # SVG 属性是 CSS 风格连字符名（stroke-width 等），Python 关键字参数用
    # 下划线传入，这里统一转换
    el = ET.SubElement(parent, f"{{{SVG_NS}}}{tag}",
                       {k.replace("_", "-"): _fmt(v)
                        for k, v in attrs.items()})
    return el


def _fmt(v):
    if isinstance(v, float):
        return str(int(round(v)))
    return str(v)


def render_svg(nodes, geo, routes, meta, path, title="BPMN layout"):
    """简单预览 SVG：节点按类型着色、正交连线 + 箭头、条件标签。"""
    rects = {nid: geo[nid] for nid in nodes if nid in geo}
    all_pts = [p for pts in routes.values() for p in pts]
    xs = [r[0] for r in rects.values()] + [p[0] for p in all_pts]
    ys = [r[1] for r in rects.values()] + [p[1] for p in all_pts]
    xs += [r[0] + r[2] for r in rects.values()]
    ys += [r[1] + r[3] for r in rects.values()]
    PAD = 40
    min_x, min_y = min(xs) - PAD, min(ys) - PAD
    W = max(xs) - min(xs) + 2 * PAD
    H = max(ys) - min(ys) + 2 * PAD

    ET.register_namespace("", SVG_NS)
    root = ET.Element(f"{{{SVG_NS}}}svg", {
        "version": "1.1",
        "width": _fmt(W), "height": _fmt(H),
        "viewBox": f"{_fmt(min_x)} {_fmt(min_y)} {_fmt(W)} {_fmt(H)}",
        "font-family": "sans-serif",
    })
    _svg_el(root, "title").text = title

    defs = _svg_el(root, "defs")
    marker = _svg_el(defs, "marker", id="arrow", viewBox="0 0 10 10",
                     refX="9", refY="5", markerWidth="7", markerHeight="7",
                     orient="auto-start-reverse")
    _svg_el(marker, "path", d="M 0 1 L 9 5 L 0 9 z", fill="#555")

    _svg_el(root, "rect", x=min_x, y=min_y, width=W, height=H, fill="#fafafa")

    # ---- 连线（先画，压在节点下）----
    for fid, pts in routes.items():
        points = " ".join(f"{_fmt(px)},{_fmt(py)}" for px, py in pts)
        _svg_el(root, "polyline", points=points, fill="none", stroke="#666",
                stroke_width="1.4", marker_end="url(#arrow)")
        cond = _cond_text(meta, fid)
        if cond:
            # 分支标签：横向段右端上方（与 DI 标签同位）
            lx, ly, _, _ = _label_bounds(pts, cond)
            t = _svg_el(root, "text", x=_fmt(lx), y=_fmt(ly + 14),
                        font_size="10", fill="#8b4513")
            t.text = cond[:28] + ("…" if len(cond) > 28 else "")

    # ---- 节点 ----
    for nid, kind in nodes.items():
        if nid not in geo:
            continue
        x, y, w, h = geo[nid]
        fill, stroke = "#eee", "#888"
        if "inclusive" in kind:
            fill, stroke = SVG_STYLE["inclusive"]
        elif "Gateway" in kind:
            fill, stroke = SVG_STYLE["Gateway"]
        elif "startEvent" in kind:
            fill, stroke = SVG_STYLE["startEvent"]
        elif "endEvent" in kind:
            fill, stroke = SVG_STYLE["endEvent"]
        elif "Task" in kind or "Activity" in kind:
            fill, stroke = SVG_STYLE["userTask"]
        if "Gateway" in kind:
            cx, cy = x + w / 2, y + h / 2
            pts_str = f"{_fmt(x)},{_fmt(cy)} {_fmt(cx)},{_fmt(y)} " \
                      f"{_fmt(x + w)},{_fmt(cy)} {_fmt(cx)},{_fmt(y + h)}"
            _svg_el(root, "polygon", points=pts_str, fill=fill, stroke=stroke,
                    stroke_width="1.5")
            mark = "✕" if "exclusive" in kind.lower() else "◯"
            t = _svg_el(root, "text", x=_fmt(cx), y=_fmt(cy + 4),
                        font_size="14", text_anchor="middle", fill=stroke)
            t.text = mark
        elif "Event" in kind:
            _svg_el(root, "ellipse", cx=x + w / 2, cy=y + h / 2,
                    rx=w / 2, ry=h / 2, fill=fill, stroke=stroke,
                    stroke_width="3" if "endEvent" in kind else "1.5")
        else:
            _svg_el(root, "rect", x=x, y=y, width=w, height=h, rx=8,
                    fill=fill, stroke=stroke, stroke_width="1.5")
        name = _NODE_NAME.get(nid, "")
        if name:
            lines = [name[i:i + 10] for i in range(0, min(len(name), 20), 10)]
            ty = y + h / 2 - (len(lines) - 1) * 7 + 4
            for i, ln in enumerate(lines):
                t = _svg_el(root, "text", x=_fmt(x + w / 2), y=_fmt(ty + i * 14),
                            font_size="11", text_anchor="middle", fill="#333")
                t.text = ln

    ET.ElementTree(root).write(path, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------- 8. 主流程
_NODE_NAME = {}       # 模块级：render_svg 用（进程内多 process 时逐个刷新）


def relayout_xml(xml_str):
    """XML 字符串进出：重排 DI 后返回新 XML 字符串（流程语义零改动）。

    供 flows 在组装 bpmnXML 后、create 之前内联调用，免临时文件。
    （build-process / relayout-process-diagram flow 的库入口契约）"""
    import io as _io
    tree = ET.parse(_io.StringIO(xml_str))
    relayout_tree(tree)
    out = _io.StringIO()
    tree.write(out, encoding="unicode", xml_declaration=True)
    content = out.getvalue()
    # QName 属性值里旧前缀 bpmn2: 同步改 bpmn:（与 CLI 路径一致，URI 不变）
    return re.sub(r'("\w*)bpmn2:', r'\1bpmn:', content)


def relayout_tree(tree):
    """对 tree 中每个 process 重排 DI；返回 (report 汇总, process 数)。"""
    root = tree.getroot()
    diagram = root.find(q("bpmndi", "BPMNDiagram"))
    if diagram is None:
        diagram = ET.SubElement(root, q("bpmndi", "BPMNDiagram"))
    reports, n_proc = [], 0
    for proc in root.iter(q("bpmn", "process")):
        nodes, edges, meta = parse_process(proc)
        if not nodes:
            continue
        global _NODE_NAME
        _NODE_NAME = {c.get("id"): c.get("name") or "" for c in proc}

        back = remove_cycles(nodes, edges)
        layer = layer_longest_path(nodes, edges, back)
        layers, vedges, chain = insert_virtual_nodes(nodes, edges, layer, back)
        kind_of = lambda vid: "virtual" if vid.startswith(":v:") else nodes[vid]

        ordered, inv = order_columns(layers, vedges, kind_of)
        geo_all, col_x, col_widths = assign_coords(ordered, kind_of,
                                                   chain, edges, back)
        geo = {vid: g for vid, g in geo_all.items() if not vid.startswith(":v:")}
        routes = route_edges(ordered, geo_all, chain, edges, back, kind_of,
                             col_x, col_widths)

        rebuild_diagram(diagram, proc, nodes, edges, geo, routes, meta)
        rep = verify(nodes, edges, geo, routes)
        rep["inversions"] = inv
        rep["n_virtual"] = sum(1 for v in geo_all if v.startswith(":v:"))
        rep["n_layers"] = len(ordered)
        rep["meta"] = meta
        rep["geo_all"] = geo_all
        rep["routes"] = routes
        rep["nodes"] = nodes
        rep["geo"] = geo
        reports.append(rep)
        n_proc += 1
    return reports, n_proc


def print_report(reports, strict=True):
    bad = False
    for idx, rep in enumerate(reports):
        print(f"流程 #{idx + 1}: {rep['n_nodes']} 节点 / {rep['n_edges']} 边 | "
              f"{rep['n_layers']} 层 | 虚拟节点 {rep['n_virtual']} | "
              f"排序逆序 {rep['inversions']}")
        for key, label in (("node_overlap", "节点-节点重叠"),
                           ("edge_through_node", "连线-节点穿越"),
                           ("edge_edge_cross", "边-边交叉")):
            n = len(rep[key])
            flag = "[OK]" if n == 0 else "[!!]"
            print(f"  {label}: {n}  {flag}")
            if n:
                bad = True
                for item in rep[key][:6]:
                    print(f"      {item}")
                if n > 6:
                    print(f"      ... 共 {n} 处")
    if bad and strict:
        print("\n存在非零指标 —— 严格模式退出码 1（--no-strict 可降级为警告）")
    return 1 if (bad and strict) else 0


def main():
    ap = argparse.ArgumentParser(description="BPMN 无交叉重排程序")
    ap.add_argument("input", help="BPMN 文件（.bpmn/.xml/.md）")
    ap.add_argument("-o", "--output",
                    help="输出 .bpmn（默认 <输入名>_relayout.bpmn）")
    ap.add_argument("--svg", help="输出 .svg（默认 <输出名>.svg）")
    ap.add_argument("--no-strict", action="store_true",
                    help="校验非零时不返回退出码 1")
    args = ap.parse_args()

    tree = load_xml(args.input)
    reports, n_proc = relayout_tree(tree)
    if not n_proc:
        sys.exit("错误: 未找到 process 定义")

    out = args.output or re.sub(r"\.(md|xml|bpmn)?$", "", args.input) \
        + "_relayout.bpmn"
    svg = args.svg or re.sub(r"\.bpmn?$", "", out) + ".svg"

    _write_bpmn(tree, out)

    # SVG 用最后一个 process 的数据渲染（多 process 时可 --svg 指定多次跑）
    rep = reports[-1]
    render_svg(rep["nodes"], rep["geo"], rep["routes"], rep["meta"], svg,
               title=os.path.basename(args.input))

    code = print_report(reports, strict=not args.no_strict)
    print(f"\n已写入 {out}\n已写入 {svg}")
    sys.exit(code)


def _write_bpmn(tree, out):
    tree.write(out, encoding="unicode", xml_declaration=True)
    # xsi:type 等 QName 属性值里引用旧前缀 bpmn2:，同步改为 bpmn:
    with open(out, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'("\w*)bpmn2:', r'\1bpmn:', content)
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    main()
