#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPMN 流程布局检测器
===================

对 BPMN 2.0 XML 的「图形布局层（BPMNDI）」做可读性/合理性检查，与同目录的
`check_compliance.py`（语义合规）互补：

- 语义合规：检查流程逻辑（缺开始事件、网关直连、未连接、重名等），不依赖坐标。
- 布局检测（本脚本）：检查画布布局（节点重叠、压线、连线交叉、回流、坐标非法等），
  强依赖 BPMNDI 图形层（BPMNShape/BPMNEdge/Bounds/waypoint）。

规则来源：本脚本为通用布局检测，依据 BPMN 2.0 图形规范与流程图常见可读性约定，
非还原某一前端实现。规则来源（后台语义侧）仅作溯源：
applications_sa/itsc-union-standalone-NA/bricks/itsc-process-manage/dist/lazy-bricks/
process-design.e0d5~lazy-bricks/process-detail.e0d5.fe534c4c.js

设计要点：
- 零依赖，仅 Python 3.8+ 标准库。
- 按命名空间 URI 解析（不硬编码前缀），兼容 bpmn2:/bpmn:、dc:/omgdc:、di:/omgdi: 等任意前缀。
- 接受「XML 文件路径」或「XML 原文」或 stdin（'-'），一次性输出全部布局问题。
- 每条问题标注：规则名、等级、元素 id、元素类型、名称、XML 行号、画布坐标(x,y,w,h)、消息。
- 容差参数化（LAYOUT_CONFIG）；规模超阈值时跳过 O(n²) 规则并提示，避免大图卡顿。
- 无 BPMNDI 图形层时优雅降级：跳过布局检查并提示，退出码 0。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# 命名空间（按 URI 解析，与前缀无关）
# --------------------------------------------------------------------------- #
NS_BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
NS_BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
NS_DC = "http://www.omg.org/spec/DD/20100524/DC"
NS_DI = "http://www.omg.org/spec/DD/20100524/DI"


def _ns(uri: str, local: str) -> str:
    return f"{{{uri}}}{local}"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag and tag[0] == "{" else tag


def _type_from_local(localname: str) -> str:
    """bpmn localname -> bpmn $type，如 userTask -> bpmn:UserTask。"""
    return "bpmn:" + localname[0].upper() + localname[1:]


# FlowElement 的 localname 白名单（识别语义层元素，含嵌套子流程递归）
_FLOW_ELEMENT_LOCALNAMES = {
    "startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent",
    "boundaryEvent",
    "task", "userTask", "serviceTask", "sendTask", "receiveTask", "manualTask",
    "businessRuleTask", "scriptTask",
    "exclusiveGateway", "parallelGateway", "inclusiveGateway", "complexGateway",
    "eventBasedGateway",
    "subProcess", "callActivity", "transaction", "adHocSubProcess",
    "sequenceFlow",
}

# 命名空间 URI -> 前缀（还原 $attrs 里的 flowable:xxx 风格，仅用于可选属性展示）
_NS_PREFIX = {
    "http://flowable.org/bpmn": "flowable",
    "http://camunda.org/schema/1.0/bpmn": "camunda",
    "http://www.w3.org/2001/XMLSchema-instance": "xsi",
}


def _attr_key(raw_key: str) -> str:
    if raw_key and raw_key[0] == "{":
        ns, local = raw_key[1:].split("}", 1)
        prefix = _NS_PREFIX.get(ns)
        return f"{prefix}:{local}" if prefix else local
    return raw_key


# --------------------------------------------------------------------------- #
# 布局检测配置（容差与规模护栏，集中可调）
# --------------------------------------------------------------------------- #
LAYOUT_CONFIG = {
    # 矩形相交容差(px)：重叠量 <= 此值视为贴合，不算重叠
    "overlap_tolerance": 2,
    # 回流判定(px)：目标中心 x 小于源中心 x 超过此值，视为向左回流
    "backflow_tolerance": 30,
    # 连线交叉：节点数超过此值跳过该规则(O(n²))，0 表示不限制
    "max_elements_for_crossing": 300,
    # 节点重叠：节点数超过此值跳过该规则(O(n²))，0 表示不限制
    "max_elements_for_overlap": 500,
    # 节点压线：节点与连线段相交判定时，矩形向内缩进(px)，避免贴边误判
    "edge_rect_inset": 1,
}


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class SemanticEl:
    """语义层元素的轻量表示（仅布局检测所需字段）。"""
    id: Optional[str]
    type_: str
    name: Optional[str]
    source_ref: Optional[str]  # 仅 sequenceFlow 有
    target_ref: Optional[str]
    xml_line: int


@dataclass
class Shape:
    """BPMNShape：节点图形。"""
    diagram_id: Optional[str]   # BPMNShape 自身 id
    bpmn_element: Optional[str]  # 引用的语义元素 id
    x: float
    y: float
    w: float
    h: float
    xml_line: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0


@dataclass
class Edge:
    """BPMNEdge：连线图形。"""
    diagram_id: Optional[str]
    bpmn_element: Optional[str]  # 引用的语义 sequenceFlow id
    waypoints: List[Tuple[float, float]]
    xml_line: int

    @property
    def first_point(self) -> Optional[Tuple[float, float]]:
        return self.waypoints[0] if self.waypoints else None


class LayoutModel:
    """BPMN 布局模型：语义层 + 图形层。"""

    def __init__(self, xml_text: str):
        self.semantic_by_id: Dict[str, SemanticEl] = {}
        self.shapes: List[Shape] = []
        self.edges: List[Edge] = []
        self.shape_by_element: Dict[str, Shape] = {}   # bpmn_element -> Shape
        self.edge_by_element: Dict[str, Edge] = {}     # bpmn_element -> Edge
        self.id_lines: Dict[str, int] = {}
        self.has_diagram: bool = False
        self._parse(xml_text)

    def _parse(self, xml_text: str) -> None:
        self.id_lines = _collect_id_lines(xml_text)
        root = ET.fromstring(xml_text)

        # 1) 语义层：遍历所有 process（含子流程递归）
        for proc in root.iter(_ns(NS_BPMN, "process")):
            self._collect_semantic(proc)

        # 2) 图形层：BPMNDiagram / BPMNPlane
        for diag in root.iter(_ns(NS_BPMNDI, "BPMNDiagram")):
            self.has_diagram = True
            for plane in diag.iter(_ns(NS_BPMNDI, "BPMNPlane")):
                for child in list(plane):
                    local = _local(child.tag)
                    if local == "BPMNShape":
                        sh = self._build_shape(child)
                        if sh is not None:
                            self.shapes.append(sh)
                            if sh.bpmn_element:
                                self.shape_by_element[sh.bpmn_element] = sh
                    elif local == "BPMNEdge":
                        ed = self._build_edge(child)
                        if ed is not None:
                            self.edges.append(ed)
                            if ed.bpmn_element:
                                self.edge_by_element[ed.bpmn_element] = ed

    def _collect_semantic(self, el: ET.Element) -> None:
        for child in list(el):
            local = _local(child.tag)
            if local in _FLOW_ELEMENT_LOCALNAMES:
                sid = child.attrib.get("id")
                sem = SemanticEl(
                    id=sid,
                    type_=_type_from_local(local),
                    name=child.attrib.get("name"),
                    source_ref=child.attrib.get("sourceRef"),
                    target_ref=child.attrib.get("targetRef"),
                    xml_line=self.id_lines.get(sid, 0) if sid else 0,
                )
                if sid:
                    self.semantic_by_id[sid] = sem
                # 递归子流程
                if local in ("subProcess", "transaction", "adHocSubProcess"):
                    self._collect_semantic(child)

    def _build_shape(self, el: ET.Element) -> Optional[Shape]:
        did = el.attrib.get("id")
        bpmn_el = el.attrib.get("bpmnElement")
        bounds = el.find(_ns(NS_DC, "Bounds"))
        if bounds is None:
            return None
        try:
            x = float(bounds.attrib.get("x", "0"))
            y = float(bounds.attrib.get("y", "0"))
            w = float(bounds.attrib.get("width", "0"))
            h = float(bounds.attrib.get("height", "0"))
        except (TypeError, ValueError):
            x = y = w = h = float("nan")
        return Shape(
            diagram_id=did,
            bpmn_element=bpmn_el,
            x=x, y=y, w=w, h=h,
            xml_line=self.id_lines.get(did, 0),
        )

    def _build_edge(self, el: ET.Element) -> Optional[Edge]:
        did = el.attrib.get("id")
        bpmn_el = el.attrib.get("bpmnElement")
        pts: List[Tuple[float, float]] = []
        for wp in el.findall(_ns(NS_DI, "waypoint")):
            try:
                x = float(wp.attrib.get("x", "0"))
                yv = float(wp.attrib.get("y", "0"))
                pts.append((x, yv))
            except (TypeError, ValueError):
                continue
        return Edge(
            diagram_id=did,
            bpmn_element=bpmn_el,
            waypoints=pts,
            xml_line=self.id_lines.get(did, 0),
        )

    # ---- 查询辅助 ----
    def sem_of_shape(self, sh: Shape) -> Optional[SemanticEl]:
        return self.semantic_by_id.get(sh.bpmn_element) if sh.bpmn_element else None


def _collect_id_lines(xml_text: str) -> Dict[str, int]:
    """expat 扫描，记录每个带 id 属性元素的起始行号。"""
    id_lines: Dict[str, int] = {}
    parser = expat.ParserCreate()

    def on_start(_name, attrs):
        if "id" in attrs:
            id_lines[attrs["id"]] = parser.CurrentLineNumber

    parser.StartElementHandler = on_start
    try:
        parser.Parse(xml_text.encode("utf-8"), True)
    except expat.ExpatError:
        pass
    return id_lines


# --------------------------------------------------------------------------- #
# 几何工具
# --------------------------------------------------------------------------- #
def _is_nan(v: float) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _rects_overlap(a: Shape, b: Shape, tol: float) -> bool:
    """两个矩形相交（容差 tol：重叠量<=tol 不算）。"""
    if _is_nan(a.x) or _is_nan(b.x):
        return False
    ax1, ay1 = a.x, a.y
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx1, by1 = b.x, b.y
    bx2, by2 = b.x + b.w, b.y + b.h
    return (ax1 < bx2 - tol and ax2 > bx1 + tol
            and ay1 < by2 - tol and ay2 > by1 + tol)


def _cross(ox: float, oy: float, ax: float, ay: float, bx: float, by: float) -> float:
    """向量 OA x OB 的 z 分量。"""
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def _seg_intersect(p1, p2, p3, p4) -> bool:
    """线段 p1p2 与 p3p4 是否严格相交（不含共线相切/端点重合）。"""
    d1 = _cross(p3[0], p3[1], p4[0], p4[1], p1[0], p1[1])
    d2 = _cross(p3[0], p3[1], p4[0], p4[1], p2[0], p2[1])
    d3 = _cross(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
    d4 = _cross(p1[0], p1[1], p2[0], p2[1], p4[0], p4[1])
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _point_in_rect(px: float, py: float, sh: Shape, inset: float = 0.0) -> bool:
    """点是否在矩形内部（可向内缩进 inset）。"""
    if _is_nan(sh.x):
        return False
    return (sh.x + inset < px < sh.x + sh.w - inset
            and sh.y + inset < py < sh.y + sh.h - inset)


def _seg_rect_intersect(p1, p2, sh: Shape, inset: float) -> bool:
    """线段 p1p2 是否与矩形 sh 相交（端点落在 inset 后的内部，或与四边相交）。"""
    if _point_in_rect(p1[0], p1[1], sh, inset) or _point_in_rect(p2[0], p2[1], sh, inset):
        return True
    x1, y1 = sh.x + inset, sh.y + inset
    x2, y2 = sh.x + sh.w - inset, sh.y + sh.h - inset
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    for i in range(4):
        if _seg_intersect(p1, p2, corners[i], corners[(i + 1) % 4]):
            return True
    return False


def _polyline_segments(edge: Edge):
    """返回 [(p_i, p_{i+1}), ...]。"""
    return list(zip(edge.waypoints[:-1], edge.waypoints[1:]))


# --------------------------------------------------------------------------- #
# 问题与上报
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    rule: str
    level: str
    element_id: Optional[str]
    element_type: str
    element_name: Optional[str]
    xml_line: int
    x: Optional[float]
    y: Optional[float]
    w: Optional[float]
    h: Optional[float]
    message: str
    related_id: Optional[str] = None


def _make_issue(rule: str, level: str, model: LayoutModel,
                sem: Optional[SemanticEl], sh: Optional[Shape], ed: Optional[Edge],
                message: str, related_id: Optional[str] = None) -> Issue:
    """构造 Issue，坐标优先取 Shape；连线取首点。"""
    x = y = w = h = None
    if sh is not None and not _is_nan(sh.x):
        x, y, w, h = sh.x, sh.y, sh.w, sh.h
    elif ed is not None and ed.first_point is not None:
        x, y = ed.first_point
    return Issue(
        rule=rule, level=level,
        element_id=sem.id if sem else (sh.bpmn_element if sh else (ed.bpmn_element if ed else None)),
        element_type=sem.type_ if sem else "",
        element_name=sem.name if sem else None,
        xml_line=(sem.xml_line if sem else 0) or (sh.xml_line if sh else 0) or (ed.xml_line if ed else 0),
        x=x, y=y, w=w, h=h,
        message=message, related_id=related_id,
    )


# --------------------------------------------------------------------------- #
# 布局规则实现
# 每个函数签名: rule_xxx(model, issues, cfg, enabled_off) -> None
# --------------------------------------------------------------------------- #
def rule_invalid_bounds(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """坐标非法：width/height<=0、NaN。

    注意：x/y 为负**不算非法**。bpmn-js 画布是无限大虚拟坐标系，原点不强制在左上角，
    元素可在负坐标区域，渲染时 viewport 自动平移框入可视区，web 端显示正常。
    如需检测负坐标/超界，见 out-of-canvas（默认 off）。
    """
    for sh in model.shapes:
        if _is_nan(sh.x) or _is_nan(sh.y) or _is_nan(sh.w) or _is_nan(sh.h):
            sem = model.sem_of_shape(sh)
            issues.append(_make_issue(
                "invalid-bounds", "error", model, sem, sh, None,
                "图形坐标非法(NaN)，无法定位", sem.id if sem else sh.bpmn_element))
            continue
        bad = []
        if sh.w <= 0 or sh.h <= 0:
            bad.append(f"尺寸非正(width={sh.w}, height={sh.h})")
        if bad:
            sem = model.sem_of_shape(sh)
            issues.append(_make_issue(
                "invalid-bounds", "error", model, sem, sh, None,
                "图形坐标非法：" + "；".join(bad), sem.id if sem else sh.bpmn_element))


def rule_shape_overlap(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """节点重叠：两个 BPMNShape 矩形相交（超出容差）。"""
    max_n = cfg["max_elements_for_overlap"]
    if max_n and len(model.shapes) > max_n:
        print(f"[提示] 节点数 {len(model.shapes)} 超过 {max_n}，跳过 shape-overlap 检查",
              file=sys.stderr)
        return
    tol = cfg["overlap_tolerance"]
    n = len(model.shapes)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = model.shapes[i], model.shapes[j]
            if _rects_overlap(a, b, tol):
                sem_a = model.sem_of_shape(a)
                issues.append(_make_issue(
                    "shape-overlap", "error", model, sem_a, a, None,
                    f"与节点 {b.bpmn_element or b.diagram_id} 重叠", b.bpmn_element))


def rule_shape_on_edge(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """节点压在无关连线上：节点矩形与某条非自身相关连线折线相交。"""
    inset = cfg["edge_rect_inset"]
    # 连线 source/target 语义 id 集合
    edge_refs: List[Tuple[Edge, set]] = []
    for ed in model.edges:
        sem = model.semantic_by_id.get(ed.bpmn_element) if ed.bpmn_element else None
        refs = {sem.source_ref, sem.target_ref} if sem else set()
        refs.discard(None)
        edge_refs.append((ed, refs))
    for sh in model.shapes:
        sid = sh.bpmn_element
        for ed, refs in edge_refs:
            if sid in refs:
                continue  # 连线本身连着该节点，跳过
            for p1, p2 in _polyline_segments(ed):
                if _seg_rect_intersect(p1, p2, sh, inset):
                    sem = model.sem_of_shape(sh)
                    issues.append(_make_issue(
                        "shape-on-edge", "error", model, sem, sh, None,
                        f"节点压在连线 {ed.bpmn_element or ed.diagram_id} 上", ed.bpmn_element))
                    break  # 同一连线只报一次


def rule_orphan_shape(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """孤儿图形：BPMNShape 引用的 bpmnElement 在语义层不存在。"""
    for sh in model.shapes:
        if sh.bpmn_element and sh.bpmn_element not in model.semantic_by_id:
            issues.append(_make_issue(
                "orphan-shape", "error", model, None, sh, None,
                f"图形引用了不存在的语义元素 {sh.bpmn_element}", sh.bpmn_element))


def rule_edge_crossing(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """连线交叉：两条无公共端点的连线折线相交。"""
    max_n = cfg["max_elements_for_crossing"]
    if max_n and (len(model.edges) + len(model.shapes)) > max_n:
        print(f"[提示] 元素数超过 {max_n}，跳过 edge-crossing 检查", file=sys.stderr)
        return
    # 预取每条边的语义端点集与线段
    edge_data: List[Tuple[Edge, set, list]] = []
    for ed in model.edges:
        sem = model.semantic_by_id.get(ed.bpmn_element) if ed.bpmn_element else None
        refs = {sem.source_ref, sem.target_ref} if sem else set()
        refs.discard(None)
        edge_data.append((ed, refs, _polyline_segments(ed)))
    n = len(edge_data)
    for i in range(n):
        ed_i, refs_i, segs_i = edge_data[i]
        for j in range(i + 1, n):
            ed_j, refs_j, segs_j = edge_data[j]
            if refs_i & refs_j:
                continue  # 共用端点，相交属正常
            crossed = False
            for p1, p2 in segs_i:
                if crossed:
                    break
                for p3, p4 in segs_j:
                    if _seg_intersect(p1, p2, p3, p4):
                        crossed = True
                        break
            if crossed:
                sem = model.semantic_by_id.get(ed_i.bpmn_element) if ed_i.bpmn_element else None
                issues.append(_make_issue(
                    "edge-crossing", "warn", model, sem, None, ed_i,
                    f"与连线 {ed_j.bpmn_element or ed_j.diagram_id} 交叉", ed_j.bpmn_element))


def rule_backflow_direction(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """回流方向：连线目标节点中心 x 明显小于源节点中心 x（向左走）。"""
    tol = cfg["backflow_tolerance"]
    for ed in model.edges:
        sem = model.semantic_by_id.get(ed.bpmn_element) if ed.bpmn_element else None
        if not sem or not sem.source_ref or not sem.target_ref:
            continue
        src_sh = model.shape_by_element.get(sem.source_ref)
        tgt_sh = model.shape_by_element.get(sem.target_ref)
        if not src_sh or not tgt_sh or _is_nan(src_sh.x) or _is_nan(tgt_sh.x):
            continue
        if tgt_sh.cx < src_sh.cx - tol:
            issues.append(_make_issue(
                "backflow-direction", "warn", model, sem, None, ed,
                f"回流：目标({sem.target_ref})在源({sem.source_ref})左侧 "
                f"(源x={src_sh.cx:.0f}, 目标x={tgt_sh.cx:.0f})"))


# 可选规则（默认 off）
def rule_out_of_canvas(model: LayoutModel, issues: List[Issue], cfg, include_off: bool) -> None:
    """超出画布：可选检测负坐标或离群过远的节点（默认 off）。

    BPMN 画布无固定边界，负坐标渲染正常，故默认不检查。仅当你的部署有明确画布
    尺寸约定（如导出图片/打印版式）时才启用，在此实现具体判定。
    """
    return  # 默认 off，未实现


# --------------------------------------------------------------------------- #
# 规则注册表
# --------------------------------------------------------------------------- #
RULES: List[Tuple[str, str, Any]] = [
    ("invalid-bounds", "error", rule_invalid_bounds),
    ("shape-overlap", "error", rule_shape_overlap),
    ("shape-on-edge", "error", rule_shape_on_edge),
    ("orphan-shape", "error", rule_orphan_shape),
    ("edge-crossing", "warn", rule_edge_crossing),
    ("backflow-direction", "warn", rule_backflow_direction),
    ("out-of-canvas", "off", rule_out_of_canvas),
]


# --------------------------------------------------------------------------- #
# Linter
# --------------------------------------------------------------------------- #
class Linter:
    def __init__(self, include_off: bool = False):
        self.include_off = include_off

    def lint(self, model: LayoutModel) -> List[Issue]:
        issues: List[Issue] = []
        for name, level, fn in RULES:
            if level == "off" and not self.include_off:
                continue
            try:
                fn(model, issues, LAYOUT_CONFIG, self.include_off)
            except Exception as exc:
                issues.append(Issue(
                    rule=name, level="error",
                    element_id=None, element_type="", element_name=None,
                    xml_line=0, x=None, y=None, w=None, h=None,
                    message=f"[检测器内部错误] {type(exc).__name__}: {exc}",
                ))
        return issues


# --------------------------------------------------------------------------- #
# 输入与输出
# --------------------------------------------------------------------------- #
def read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as fh:
            return fh.read()
    return source


def _fmt_pos(it: Issue) -> str:
    if it.x is None:
        return "pos=-"
    if it.w is not None:
        return f"pos=({it.x:.0f},{it.y:.0f}) size=({it.w:.0f}×{it.h:.0f})"
    return f"pos=({it.x:.0f},{it.y:.0f})"


def format_text(issues: List[Issue]) -> str:
    if not issues:
        return "未检出任何布局问题。"
    lines = []
    for it in issues:
        tag = "ERROR" if it.level == "error" else "WARN "
        name = f"name={it.element_name}" if it.element_name else "name=-"
        line = f"line={it.xml_line}" if it.xml_line else "line=-"
        rel = f" related={it.related_id}" if it.related_id else ""
        lines.append(
            f"[{tag}] {it.rule}  id={it.element_id or '-'}  type={it.element_type or '-'}  "
            f"{name}  {line}  {_fmt_pos(it)}{rel}"
        )
        lines.append(f"        {it.message}")
    err = sum(1 for i in issues if i.level == "error")
    warn = sum(1 for i in issues if i.level == "warn")
    lines.append(f"\n共检出 {len(issues)} 个布局问题（error={err}, warn={warn}）")
    return "\n".join(lines)


def format_json(issues: List[Issue]) -> str:
    return json.dumps([asdict(i) for i in issues], ensure_ascii=False, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="BPMN 流程布局检测器（检查节点重叠/压线/连线交叉/回流/坐标非法等）",
    )
    parser.add_argument(
        "source",
        help="BPMN XML 文件路径 / XML 原文 / '-'（stdin）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出全部问题")
    parser.add_argument("--include-off", action="store_true",
                        help="同时运行默认关闭(off)的规则")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="即使存在 error 级问题也返回退出码 0")
    args = parser.parse_args(argv)

    try:
        xml_text = read_source(args.source)
    except OSError as exc:
        print(f"读取输入失败: {exc}", file=sys.stderr)
        return 2

    try:
        model = LayoutModel(xml_text)
    except ET.ParseError as exc:
        print(f"XML 解析失败: {exc}", file=sys.stderr)
        return 2

    if not model.has_diagram:
        print("未检测到图形布局信息(BPMNDiagram)，跳过布局检查。", file=sys.stderr)
        return 0

    issues = Linter(include_off=args.include_off).lint(model)

    if args.json:
        print(format_json(issues))
    else:
        print(format_text(issues))

    has_error = any(i.level == "error" for i in issues)
    if has_error and not args.no_exit_code:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
