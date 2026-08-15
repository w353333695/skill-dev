#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPMN 流程图重排脚本 —— 模仿 Mermaid(Dagre) 的排序算法，自左向右布局。

不改变流程语义（节点/连线/flowable 扩展属性全部保留），只重写
BPMNDiagram 中的坐标（dc:Bounds / di:waypoint）。

排序算法（对应 Dagre 的 LR 布局）:
  1. 分层(ranking): 最长路径分层 —— 节点列号 = max(前驱列号) + 1，自左向右
  2. 排序(ordering): 列内按前驱/后继的加权平均位置(重心法)迭代排序，减少连线交叉
  3. 坐标(placement): 每列从上到下堆叠、垂直居中对齐主干道；列间距固定
  4. 连线: 正交折线 —— 源节点右侧中心 → 列间中点 → 目标节点左侧中心

用法:
    python3 bpmn-relayout.py <bpmn文件> [-o 输出.bpmn]     # CLI：文件进出
    from bpmn_relayout import relayout_xml                 # 库：XML 字符串进出（flow 内联用）
    relayout_xml(bpmn_xml_str) -> 重排后的 bpmn_xml_str

api-orchestrator 集成（flows 调用姿势）:
  ① 设计时（生成即优化）: build-process flow 中 LLM 只产【纯语义 XML】（七要素，
     无 BPMNDI），create 前调 relayout_xml() 算出 DI —— 不手写坐标。
  ② 存量补救: process_version get 拉 BPMN → relayout → create 派生草稿（带
     baseVersionId 克隆表单绑定）→ 前端验收 → set_main。
     见 flows/relayout-process-diagram.yaml。
纯本地计算、零系统知识、零第三方依赖（标准库 only）。
"""

import argparse
import math
import re
import sys
import tempfile
from collections import deque
import os
import xml.etree.ElementTree as ET

NS = {
    # 前缀统一用 "bpmn"（而非源文件的 bpmn2）——部分建模器按字面前缀
    # 查找 <bpmn:definitions>，命名空间 URI 不变，语义等价
    "bpmn":   "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc":     "http://www.omg.org/spec/DD/20100524/DC",
    "di":     "http://www.omg.org/spec/DD/20100524/DI",
    "flowable": "http://flowable.org/bpmn",
    "camunda":  "http://camunda.org/schema/1.0/bpmn",
    "xsi":      "http://www.w3.org/2001/XMLSchema-instance",
}
for p, u in NS.items():
    ET.register_namespace(p, u)

def q(p, tag):
    return f"{{{NS[p]}}}{tag}"

# 各节点类型的标准尺寸（bpmn.io 约定）
def node_size(kind):
    if "Gateway" in kind:
        return 50, 50
    if "Event" in kind:
        return 36, 36
    return 100, 80           # task / callActivity / subProcess ...

MARGIN_X, MARGIN_Y = 60, 60
COL_GAP, ROW_GAP = 100, 40   # 列间距 / 行间距


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
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                          encoding="utf-8")
        tmp.write(m.group(0))
        tmp.close()
        tree = ET.parse(tmp.name)
        os.unlink(tmp.name)
        return tree


# ---------------------------------------------------------------- 1. 解析流程
def parse_process(proc):
    nodes, edges = {}, []      # id → kind ; (fid, src, dst)
    for child in proc:
        kind = tag_name(child)
        if kind == "sequenceFlow":
            edges.append((child.get("id"),
                          child.get("sourceRef"), child.get("targetRef")))
        elif child.get("id"):
            nodes[child.get("id")] = kind
    return nodes, edges


# ---------------------------------------------------------------- 2. 分层（ranking）
def rank_layers(nodes, edges):
    preds = {n: [] for n in nodes}
    succs = {n: [] for n in nodes}
    for _, s, t in edges:
        if s in nodes and t in nodes:
            preds[t].append(s)
            succs[s].append(t)

    # 回边检测（DFS 灰边）：构成环的边不参与分层（否则环下游全部节点被卡死，
    # Kahn 走不进、兜底字典序乱排——实测 30 节点图 28 个被误判环上、endEvent 落最左列）。
    # 回边在路由阶段由 assign_lanes 按 backward 绕行通道处理，语义不变。
    color = {}
    back = set()
    def _dfs(u):
        color[u] = 1
        for v in succs.get(u, []):
            if color.get(v, 0) == 1:
                back.add((u, v))
            elif color.get(v, 0) == 0:
                _dfs(v)
        color[u] = 2
    for n in nodes:
        if color.get(n, 0) == 0:
            _dfs(n)

    # 标准 Kahn（最长路径分层）：只走非回边
    layer = {}
    indeg = {n: len([p for p in preds[n] if (p, n) not in back]) for n in nodes}
    queue = deque(sorted(n for n, d in indeg.items() if d == 0))
    while queue:
        nid = queue.popleft()
        base = [layer[p] for p in preds[nid] if p in layer and (p, nid) not in back]
        layer[nid] = (max(base) + 1) if base else 0
        for t in succs[nid]:
            if (nid, t) in back:
                continue
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    # ⚠️不做回边目标层提升——主链节点（如 TM分析）同时是回边目标时会被推向右列，
    #   破坏主链直线（实测：TM分析 层2 被推到 4，与 TM受理 同列）。
    #   回环侧支（源节点）自然落在 目标层+1 列，与主链下游同列不同行（barycenter 排开），
    #   回边由 assign_lanes 的 backward 绕行通道画回，视觉为侧支回环——符合
    #   「侧支节点放对应节点上/下方」原则。
    # 兜底（理论到不了）：剩余按前驱已分层最大值
    for n in nodes:
        if n not in layer:
            base = [layer[p] for p in preds[n] if p in layer]
            layer[n] = (max(base) + 1) if base else 0
    return layer, preds, succs


# ---------------------------------------------------------------- 3. 列内排序（ordering）
def order_columns(nodes, edges, layer, preds, succs, sweeps=4):
    cols = {}
    for nid, l in layer.items():
        cols.setdefault(l, []).append(nid)
    for l in cols:
        cols[l].sort(key=lambda n: (0, n) if "start" in nodes[n].lower()
                     else (1, n))

    # pos[n] = 节点在所属列中的序号，供重心计算
    def refresh_pos():
        pos = {}
        for l, items in cols.items():
            for i, n in enumerate(items):
                pos[n] = i
        return pos

    for sweep in range(sweeps):
        changed = False
        # 偶数轮按前驱重心，奇数轮按后继重心（双向扫描）
        downstream = (sweep % 2 == 1)
        for l in sorted(cols):
            ref = succs if downstream else preds
            pos = refresh_pos()
            def bary(nid):
                rel = [pos[r] for r in ref[nid] if r in pos]
                return (sum(rel) / len(rel)) if rel else pos[nid]
            new_order = sorted(cols[l], key=lambda n: (bary(n), n))
            if new_order != cols[l]:
                cols[l] = new_order
                changed = True
        if not changed:
            break
    return cols


# ---------------------------------------------------------------- 4. 坐标（placement）

def longest_spine(nodes, edges, layer):
    """start→end 的关键路径（按层推进的贪心最长链）——主轴锚定集合。
    每步从当前节点后继中选【可达 end 且层最大】者，保证链贯通到终点。"""
    start = next((n for n in nodes if 'startEvent' in str(nodes[n]) or n.lower().startswith('start')), None)
    end = next((n for n in nodes if 'endEvent' in str(nodes[n]) or n.lower().startswith('event_')), None)
    if not start or not end:
        return set()
    succs = {}
    for _, s, t in edges:
        if s in nodes and t in nodes:
            succs.setdefault(s, []).append(t)
    # 可达 end 的节点集（反向 BFS）
    preds = {}
    for _, s, t in edges:
        if s in nodes and t in nodes:
            preds.setdefault(t, []).append(s)
    reach = {end}
    dq = deque([end])
    while dq:
        n = dq.popleft()
        for p in preds.get(n, []):
            if p not in reach:
                reach.add(p); dq.append(p)
    chain = [start]
    cur = start
    guard = 0
    while cur != end and guard < len(nodes) + 5:
        guard += 1
        # 过滤回边：目标是已入链节点（回环回到上游）或不在 reach 的边不算后继
        fwd = [t for t in succs.get(cur, []) if t in reach and t not in chain]
        # 回环侧支判定：该后继的全部后继都回到 cur 或已入链 → 是侧支（层最大者为主链继续）
        real = []
        for t in fwd:
            t_succ = [x for x in succs.get(t, []) if x in reach and x != t]
            if t_succ and all((x in chain) or (x == cur) for x in t_succ):
                continue          # 回环侧支（如 子流程→TM分析），跳过
            real.append(t)
        cands = real
        if not cands:
            if fwd:               # 全是回环侧支：主链沿第一个侧支前的链终止
                break
            break
        if len(cands) == 1:
            cur = cands[0]
            chain.append(cur)
            continue
        # 多分支（网关/多出边）：找汇合点——各分支【独立可达集】的交集中层最小者；
        # 分支节点本身不进主链（平级条件分支，按列排开与主轴对齐，避免「同级审批一上一下」）
        converge = None
        reach_sets = []
        for t in cands:
            seen = {t}; dq = deque([t])
            while dq:
                n = dq.popleft()
                for x in succs.get(n, []):
                    if x not in seen and x in reach:
                        seen.add(x); dq.append(x)
            reach_sets.append(seen)
        common = set.intersection(*reach_sets) if reach_sets else set()
        # 汇合点可以是某条分支上的节点（当它被其他分支也到达=必经，如 财务分支→GW软件开发分流）
        common = {t for t in common if t not in chain}
        if common:
            converge = min(common, key=lambda t: (layer.get(t, 0), t))
        if converge:
            chain.append(converge)
            cur = converge
        else:
            break
    return set(chain)


def assign_coords(nodes, cols, spine=()):
    """spine = 主链节点集（start→end 最长路径）：锚定中轴 Y，不被同列侧支挤偏。
    同列侧支节点：从主链节点上/下缘 +ROW_GAP 依次排开（符合「侧支放对应节点上下方」）。"""
    geo = {}                             # id → (x, y, w, h)
    col_widths = {l: max(node_size(nodes[n])[0] for n in items)
                  for l, items in cols.items()}

    x = MARGIN_X
    col_x = {}
    for l in sorted(cols):
        col_x[l] = x
        x += col_widths[l] + COL_GAP

    axis = MARGIN_Y
    spine = set(spine)
    for l in sorted(cols):
        items = cols[l]
        cx = col_x[l] + (col_widths[l] - 100) / 2 if col_widths[l] >= 100 else col_x[l]
        sp = [n for n in items if n in spine]
        side = [n for n in items if n not in spine]
        # 主链节点：中轴对齐（居中其高度）
        for n in sp:
            w, h = node_size(nodes[n])
            geo[n] = (col_x[l] + (col_widths[l] - w) / 2, axis - h / 2, w, h)
        # 同列无主链节点（纯分支列，如互斥网关的两条审批分支）：垂直居中——分支互相居中
        # 即贴近主轴，符合「同级审批同一水平线附近」；只有与主链同列的（回环侧支）才挂上/下
        if sp:
            top_y = min(geo[n][1] for n in sp)
            bot_y = max(geo[n][1] + geo[n][3] for n in sp)
            half = (len(side) + 1) // 2
            ups, downs = side[:half], side[half:]
        else:
            sizes_side = [node_size(nodes[n]) for n in side]
            total_h = sum(h for _, h in sizes_side) + ROW_GAP * (len(side) - 1)
            y = axis - total_h / 2
            for n, (w, h) in zip(side, sizes_side):
                geo[n] = (col_x[l] + (col_widths[l] - w) / 2, y, w, h)
                y += h + ROW_GAP
            continue
        y = top_y - ROW_GAP
        for n in reversed(ups):              # 向上：后放的更靠上
            w, h = node_size(nodes[n])
            geo[n] = (col_x[l] + (col_widths[l] - w) / 2, y - h, w, h)
            y -= h + ROW_GAP
        y = bot_y + ROW_GAP
        for n in downs:                      # 向下
            w, h = node_size(nodes[n])
            geo[n] = (col_x[l] + (col_widths[l] - w) / 2, y, w, h)
            y += h + ROW_GAP
    return geo


# ---------------------------------------------------------------- 5. 重写 DI
def col_cx(geo, nid):
    """节点中心 x，用于判断方向"""
    x, y, w, h = geo[nid]
    return x + w / 2


def edge_waypoints(geo, src, dst, lane=None):
    """正交折线。lane = (lane_y, exit_dx, entry_dx) 时经通道绕行：
    上方通道从源顶边出发、进目标顶边（连线先向上出发，不与下方连线相交）；
    下方通道从底边出、进底边。exit_dx/entry_dx 错开同节点同侧的出入口。"""
    sx, sy, sw, sh = geo[src]
    tx, ty, tw, th = geo[dst]
    scx, scy = sx + sw / 2, sy + sh / 2        # 源中心
    tcx, tcy = tx + tw / 2, ty + th / 2        # 目标中心

    if lane is None:
        if abs(scy - tcy) < 1:                  # 同行相邻列：直线
            return [(sx + sw, scy), (tx, tcy)]
        mid = (sx + sw + tx) / 2                # Z 形正交折线
        return [(sx + sw, scy), (mid, scy), (mid, tcy), (tx, tcy)]

    lane_y, exit_dx, entry_dx = lane
    if lane_y < sy:                             # 上方通道：顶边出、顶边入
        return [(scx + exit_dx, sy), (scx + exit_dx, lane_y),
                (tcx + entry_dx, lane_y), (tcx + entry_dx, ty)]
    return [(scx + exit_dx, sy + sh), (scx + exit_dx, lane_y),
            (tcx + entry_dx, lane_y), (tcx + entry_dx, ty + th)]


def seg_cross(e1, e2):
    """两条正交折线的交叉次数（水平段×垂直段）"""
    n = 0
    for p1, p2 in zip(e1, e1[1:]):
        for p3, p4 in zip(e2, e2[1:]):
            if abs(p1[1] - p2[1]) < 1e-6 and abs(p3[0] - p4[0]) < 1e-6 \
               and min(p1[0], p2[0]) < p3[0] < max(p1[0], p2[0]) \
               and min(p3[1], p4[1]) < p1[1] < max(p3[1], p4[1]):
                n += 1
            if abs(p1[0] - p2[0]) < 1e-6 and abs(p3[1] - p4[1]) < 1e-6 \
               and min(p1[1], p2[1]) < p3[1] < max(p1[1], p2[1]) \
               and min(p3[0], p4[0]) < p1[0] < max(p3[0], p4[0]):
                n += 1
    return n


def assign_lanes(nodes, edges, geo, layer):
    """给跨列(>1)或反向的边分配绕行通道。

    高度规则（按需加深，满足"同高优先"）:
      同侧（上/下）的边按 x 投影区间做嵌套深度分配 —— 短边在内、
      长边在外；区间不重叠的边共享同一高度（深度 0），
      仅重叠时才向外加深一层以示区别。

    侧向选择: 跨度降序逐条贪心 —— 每条边试上/下两侧，每次全量
              重算该侧嵌套深度（短边在内），取使该边交叉少的一侧；
              相当时按目标方向偏好（同排/偏上→上通道）。
    出入口:   同节点同侧多条边在边界上错开 ±10px。
    """
    min_top = min(y for (_, y, _, _) in geo.values())
    max_bottom = max(y + h for (_, y, _, h) in geo.values())
    base_up = min_top - 50                       # 各侧首选高度（同高）
    base_down = max_bottom + 50

    lane_edges = {}                              # fid → (src, dst, upward, lo, hi)
    for fid, src, dst in edges:
        if src not in geo or dst not in geo:
            continue
        cols_apart = abs(layer.get(dst, 0) - layer.get(src, 0))
        backward = col_cx(geo, dst) < col_cx(geo, src)
        if cols_apart > 1 or backward:
            sx, sy, sw, sh = geo[src]
            tx, ty, tw, th = geo[dst]
            upward = (ty + th / 2) <= (sy + sh / 2)   # 同排/偏上→偏好上通道
            xs = (sx + sw / 2, tx + tw / 2)           # 出/入口竖直段 x
            lane_edges[fid] = (src, dst, upward, min(xs), max(xs))

    # 静态折线（不绕行的普通边），供交叉计数
    statics = []
    for fid, src, dst in edges:
        if src in geo and dst in geo:
            ca = abs(layer.get(dst, 0) - layer.get(src, 0))
            backward = col_cx(geo, dst) < col_cx(geo, src)
            if not (ca > 1 or backward):
                statics.append(edge_waypoints(geo, src, dst, None))

    def side_depths(side_members):
        """嵌套深度: 跨度升序（短边在内），与已放置重叠时 = max+1，
        不重叠共享深度 0"""
        placed, out = [], {}
        for fid in sorted(side_members, key=lambda f: (
                lane_edges[f][4] - lane_edges[f][3], f)):
            lo, hi = lane_edges[fid][3], lane_edges[fid][4]
            overlapping = [d for (l, h, d) in placed if lo < h and l < hi]
            depth = (max(overlapping) + 1) if overlapping else 0
            placed.append((lo, hi, depth))
            out[fid] = depth
        return out

    def build_polylines(assignment):
        """assignment: fid → side；返回 fid → 折线（嵌套深度已算好）"""
        ups = [f for f, s in assignment.items() if s == "top"]
        downs = [f for f, s in assignment.items() if s == "bottom"]
        depths = {**side_depths(ups), **side_depths(downs)}
        lines = {}
        for fid, side in assignment.items():
            lane_y = (base_up - depths[fid] * 36) if side == "top" \
                else (base_down + depths[fid] * 36)
            src, dst = lane_edges[fid][0], lane_edges[fid][1]
            lines[fid] = edge_waypoints(geo, src, dst, (lane_y, 0, 0))
        return lines

    # 跨度降序贪心选侧
    assignment = {}                              # fid → side
    for fid in sorted(lane_edges, key=lambda f: -(
            lane_edges[f][4] - lane_edges[f][3])):
        prefer = "top" if lane_edges[fid][2] else "bottom"
        scores = {}
        for side in ("top", "bottom"):
            trial = dict(assignment); trial[fid] = side
            lines = build_polylines(trial)
            mine = lines[fid]
            others = [p for g, p in lines.items() if g != fid] + statics
            scores[side] = sum(seg_cross(mine, p) for p in others)
        # 交叉少者胜；相当取偏好侧
        assignment[fid] = min(
            ("top", "bottom"),
            key=lambda s: (scores[s], 0 if s == prefer else 1))

    lines = build_polylines(assignment)
    chosen = {}
    for fid, side in assignment.items():
        lane_y = lines[fid][2][1]                # 折线第3点 y = 通道高度
        chosen[fid] = (side, lane_y)

    # 出入口不做水平错开: 一律从形状中点出发/进入（网关菱形的顶点
    # 恰在中点，偏移会让起止点悬空到边界框的空白角上）。
    # 同源竖直段的重叠属于出发点相交，可接受。

    return {fid: (chosen[fid][1], 0, 0) for fid in chosen}


def text_width(text):
    """按字符实际宽度估算（偏宽松确保不换行）:
    全角(CJK/全角标点)≈16px, 半角≈9px"""
    return sum(16 if ord(c) > 0x2E80 else 9 for c in text)


def label_bounds(pts, text):
    """标签置于连线最长横向段的右端上方，宽度按实际字符宽估算（不换行）。"""
    lw = int(text_width(text)) + 16             # 两侧共留 16px 内边距
    best, best_len = None, -1
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(y1 - y2) < 1:                    # 横向段
            length = abs(x2 - x1)
            if length > best_len:
                best_len = length
                best = (min(x1, x2), max(x1, x2), y1)
    if best is None:                            # 兜底：无横段时放起点上方
        x, y = pts[0]
        return x, y - 20, lw, 20
    x1, x2, y = best
    return x2 - lw - 6, y - 26, lw, 20          # 右端上方


def rebuild_diagram(tree, proc, nodes, edges, geo, diagram, layer):
    plane = diagram.find(q("bpmndi", "BPMNPlane"))
    if plane is None:
        plane = ET.SubElement(diagram, q("bpmndi", "BPMNPlane"))
    plane.set("bpmnElement", proc.get("id"))
    for child in list(plane):
        plane.remove(child)

    # ---- 形状 ----
    for nid, kind in nodes.items():
        x, y, w, h = geo[nid]
        shape = ET.SubElement(plane, q("bpmndi", "BPMNShape"),
                              {"id": f"{nid}_di", "bpmnElement": nid})
        if "Gateway" in kind:
            shape.set("isMarkerVisible", "true")
        ET.SubElement(shape, q("dc", "Bounds"),
                      {"x": str(int(x)), "y": str(int(y)),
                       "width": str(w), "height": str(h)})
        # 事件/网关的名称标签放在形状下方
        name = None
        for child in proc:
            if child.get("id") == nid:
                name = child.get("name")
                break
        if name and ("Event" in kind or "Gateway" in kind):
            lw = int(text_width(name)) + 16
            label = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
            ET.SubElement(label, q("dc", "Bounds"),
                          {"x": str(int(x + w / 2 - lw / 2)),
                           "y": str(int(y + h + 4)),
                           "width": str(lw), "height": "20"})

    # ---- 连线 ----
    lanes = assign_lanes(nodes, edges, geo, layer)
    for fid, src, dst in edges:
        if src not in geo or dst not in geo:
            continue
        edge = ET.SubElement(plane, q("bpmndi", "BPMNEdge"),
                             {"id": f"{fid}_di", "bpmnElement": fid})
        pts = edge_waypoints(geo, src, dst, lanes.get(fid))
        for px, py in pts:
            ET.SubElement(edge, q("di", "waypoint"),
                          {"x": str(int(px)), "y": str(int(py))})
        # 有名称的流（条件分支）加边标签，置于折线中段
        name = None
        for child in proc:
            if child.get("id") == fid:
                name = child.get("name")
                break
        if name:
            lx, ly, lw, lh = label_bounds(pts, name)
            label = ET.SubElement(edge, q("bpmndi", "BPMNLabel"))
            ET.SubElement(label, q("dc", "Bounds"),
                          {"x": str(int(lx)), "y": str(int(ly)),
                           "width": str(lw), "height": str(lh)})


# ---------------------------------------------------------------- 库入口（flow 内联调用）
def relayout_xml(xml_str):
    """XML 字符串进出：重排 DI 后返回新 XML 字符串（流程语义零改动）。
    供 flows 在组装 bpmnXML 后、create 之前内联调用，免临时文件。"""
    import io
    tree = ET.parse(io.StringIO(xml_str))
    root = tree.getroot()
    diagram = root.find(q("bpmndi", "BPMNDiagram"))
    if diagram is None:
        # 无 DI（纯语义 XML）——创建空 diagram 供写入
        diagram = ET.SubElement(root, q("bpmndi", "BPMNDiagram"))
    for proc in root.iter(q("bpmn", "process")):
        nodes, edges = parse_process(proc)
        if not nodes:
            continue
        layer, preds, succs = rank_layers(nodes, edges)
        cols = order_columns(nodes, edges, layer, preds, succs)
        spine = longest_spine(nodes, edges, layer)
        geo = assign_coords(nodes, cols, spine)
        rebuild_diagram(tree, proc, nodes, edges, geo, diagram, layer)
    out = io.StringIO()
    tree.write(out, encoding="unicode", xml_declaration=True)
    content = out.getvalue()
    # QName 属性值里旧前缀 bpmn2: 同步改 bpmn:（与 CLI 路径一致）
    return re.sub(r'("\w*)bpmn2:', r'\1bpmn:', content)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="用 Mermaid(Dagre) 风格排序算法重排 BPMN 图（自左向右）")
    ap.add_argument("input", help="BPMN 文件（.bpmn/.xml/.md）")
    ap.add_argument("-o", "--output", help="输出 .bpmn（默认 <输入名>_relayout.bpmn）")
    args = ap.parse_args()

    tree = load_xml(args.input)
    root = tree.getroot()

    diagram = root.find(q("bpmndi", "BPMNDiagram"))
    if diagram is None:
        sys.exit("错误: BPMN 中没有 BPMNDiagram，无法写入布局")

    count = 0
    for proc in root.iter(q("bpmn", "process")):
        nodes, edges = parse_process(proc)
        if not nodes:
            continue
        layer, preds, succs = rank_layers(nodes, edges)
        cols = order_columns(nodes, edges, layer, preds, succs)
        spine = longest_spine(nodes, edges, layer)
        geo = assign_coords(nodes, cols, spine)
        rebuild_diagram(tree, proc, nodes, edges, geo, diagram, layer)
        count += 1
        depth = max(layer.values()) + 1
        print(f"流程 {proc.get('id')}: {len(nodes)} 节点 / {len(edges)} 连线，"
              f"共 {depth} 列（{min(layer.values())}~{max(layer.values())} 层）")

    if not count:
        sys.exit("错误: 未找到 process 定义")

    out = args.output or re.sub(r"\.(md|xml|bpmn)?$", "", args.input) \
        + "_relayout.bpmn"
    tree.write(out, encoding="unicode", xml_declaration=True)

    # xsi:type 等 QName 属性值里引用旧前缀 bpmn2:，同步改为 bpmn:
    with open(out, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'("\w*)bpmn2:', r'\1bpmn:', content)
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
