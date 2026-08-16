#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPMN 流程设计合规检测器
=======================

本脚本是前端 `data/sources/frontend/ITSM/itsc-form-management/process-detail.e0d5.e200490e.js`（2.9MB
lazy chunk = bricks/itsc-process-manage 1.84.9 的流程设计 lazy-bricks，2026-08-16 归档；同源于后台
`applications_sa/itsc-union-standalone-NA/.../process-detail.e0d5.fe534c4c.js`）中内嵌的
bpmn-js-bpmnlint（https://github.com/bpmn-io/bpmn-js-bpmnlint）27 条规则的
等价 Python 实现，用于离线对 BPMN 2.0 XML（flowable/camunda 扩展兼容）做
流程设计合规检查。

设计要点：
- 零依赖，仅使用 Python 标准库（xml.etree.ElementTree + xml.parsers.expat）。
- 接受「XML 文件路径」或「XML 原文」作为输入，一次性输出全部问题。
- 每条问题标注：规则名、等级(error/warn)、元素 id、元素类型($type)、
  元素名称(name)、XML 源码行号、消息。
- 默认按源码 oD 配置启用 error/warn 规则，off 规则默认跳过（可用 --include-off 开启）。

与源码的两处差异（修正明显笔误，详见 spec 文档「与源码差异」一节）：
- `gateway-cannot-be-directly-connected` / `flow-conditional-error` /
  `form-flow` 中原码写作 `"bpmn:ParallelGatewa"`（漏 y），本实现修正为
  `bpmn:ParallelGateway`，使并行网关能被正确检查。

额外补充（bpmnlint 27 条之外，2026-08-04 主机申请流程实战）：
- `diagram-required`（error）：缺 `<bpmndi:BPMNDiagram>` 时报错——bpmn-js 渲染流程图
  依赖 BPMNShape/BPMNEdge 图形坐标，缺失时设计器报 "no diagram to display"。
  注意这是图形层要求，与流程逻辑（发起工单）无关。
- `diagram-element-missing`（warn）：BPMNDiagram 存在但为空（无 Shape/Edge）时提示。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 命名空间
# --------------------------------------------------------------------------- #
NS_BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
NS_FLOWABLE = "http://flowable.org/bpmn"
NS_CAMUNDA = "http://camunda.org/schema/1.0/bpmn"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

# 命名空间 -> 前缀（用于还原 $attrs 里的 `flowable:xxx` 风格 key）
_NS_PREFIX = {
    NS_FLOWABLE: "flowable",
    NS_CAMUNDA: "camunda",
    NS_XSI: "xsi",
}

# --------------------------------------------------------------------------- #
# BPMN 类型继承关系（用于等价于 bpmn-moddle 的 $instanceOf）
# 每个具体类型映射到其自身 + 所有祖先类型（含抽象基类）。
# --------------------------------------------------------------------------- #
_BASE = {"bpmn:BaseElement", "bpmn:FlowElement"}
_FLOWNODE = {"bpmn:FlowNode"} | _BASE
_ACTIVITY = {"bpmn:Activity"} | _FLOWNODE
_TASK = {"bpmn:Task"} | _ACTIVITY
_EVENT = {"bpmn:Event"} | _FLOWNODE
_GATEWAY = {"bpmn:Gateway"} | _FLOWNODE
_CONTAINER = {"bpmn:FlowElementsContainer"}

_SUPERTYPES: Dict[str, set] = {
    # 容器
    "bpmn:Process": {"bpmn:Process"} | _CONTAINER | _BASE,
    "bpmn:SubProcess": {"bpmn:SubProcess"} | _ACTIVITY | _CONTAINER,
    # Task 族
    "bpmn:Task": _TASK,
    "bpmn:UserTask": {"bpmn:UserTask"} | _TASK,
    "bpmn:ServiceTask": {"bpmn:ServiceTask"} | _TASK,
    "bpmn:SendTask": {"bpmn:SendTask"} | _TASK,
    "bpmn:ReceiveTask": {"bpmn:ReceiveTask"} | _TASK,
    "bpmn:ManualTask": {"bpmn:ManualTask"} | _TASK,
    "bpmn:BusinessRuleTask": {"bpmn:BusinessRuleTask"} | _TASK,
    "bpmn:ScriptTask": {"bpmn:ScriptTask"} | _TASK,
    # Activity 其它
    "bpmn:CallActivity": {"bpmn:CallActivity"} | _ACTIVITY,
    # 事件
    "bpmn:StartEvent": {"bpmn:StartEvent", "bpmn:CatchEvent"} | _EVENT,
    "bpmn:EndEvent": {"bpmn:EndEvent", "bpmn:ThrowEvent"} | _EVENT,
    "bpmn:IntermediateCatchEvent": {"bpmn:IntermediateCatchEvent", "bpmn:CatchEvent"} | _EVENT,
    "bpmn:IntermediateThrowEvent": {"bpmn:IntermediateThrowEvent", "bpmn:ThrowEvent"} | _EVENT,
    "bpmn:BoundaryEvent": {"bpmn:BoundaryEvent", "bpmn:CatchEvent"} | _EVENT,
    # 网关
    "bpmn:ExclusiveGateway": {"bpmn:ExclusiveGateway"} | _GATEWAY,
    "bpmn:ParallelGateway": {"bpmn:ParallelGateway"} | _GATEWAY,
    "bpmn:InclusiveGateway": {"bpmn:InclusiveGateway"} | _GATEWAY,
    "bpmn:ComplexGateway": {"bpmn:ComplexGateway"} | _GATEWAY,
    "bpmn:EventBasedGateway": {"bpmn:EventBasedGateway"} | _GATEWAY,
    # 连线
    "bpmn:SequenceFlow": {"bpmn:SequenceFlow"} | _BASE,
    "bpmn:MessageFlow": {"bpmn:MessageFlow"} | _BASE,
}

# FlowElement 的 localname 白名单（用于识别 Process/SubProcess 的 flowElements 子节点）
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


def _qname_local(tag: str) -> str:
    """从 ET 的 tag（`{ns}local` 或 `local`）取 localname。"""
    if tag and tag[0] == "{":
        return tag.split("}", 1)[1]
    return tag


def _type_from_local(local: str) -> str:
    """localname -> bpmn $type，如 userTask -> bpmn:UserTask。"""
    return "bpmn:" + local[0].upper() + local[1:]


def _attr_key(raw_key: str) -> str:
    """ET 属性 key（`{ns}local` 或 `local`）-> `prefix:local` 或 `local`。"""
    if raw_key and raw_key[0] == "{":
        ns, local = raw_key[1:].split("}", 1)
        prefix = _NS_PREFIX.get(ns)
        return f"{prefix}:{local}" if prefix else local
    return raw_key


# --------------------------------------------------------------------------- #
# 业务对象（模拟 bpmn-moddle 的 business object）
# --------------------------------------------------------------------------- #
class BO:
    """BPMN 元素的内存模型，字段命名与 JS 源码一致以便逐行对照。"""

    def __init__(self, bpmn_type: str, raw_attrs: Dict[str, str], xml_line: int):
        self.type_: str = bpmn_type  # noqa: valid-name（保留与 JS 一致的写法）
        # 标量属性
        self.id: Optional[str] = raw_attrs.get("id")
        self.name: Optional[str] = raw_attrs.get("name")
        self.calledElement: Optional[str] = raw_attrs.get("calledElement")
        self.triggeredByEvent: bool = raw_attrs.get("triggeredByEvent") == "true"
        # 待 resolve 的引用 id
        self._default_id: Optional[str] = raw_attrs.get("default")
        self._source_id: Optional[str] = raw_attrs.get("sourceRef")
        self._target_id: Optional[str] = raw_attrs.get("targetRef")
        # 扩展属性：flowable:xxx / camunda:xxx ...
        self.attrs_: Dict[str, str] = {}
        for k, v in raw_attrs.items():
            if k in ("id", "name", "default", "sourceRef", "targetRef",
                     "calledElement", "triggeredByEvent"):
                continue
            mapped = _attr_key(k)
            if mapped not in ("xmlns", ):
                self.attrs_[mapped] = v
        # 关系字段（resolve 后填充）
        self.flowElements: List["BO"] = []
        self.incoming: List["BO"] = []   # 节点：入向 SequenceFlow 对象
        self.outgoing: List["BO"] = []   # 节点：出向 SequenceFlow 对象
        self.sourceRef: Optional["BO"] = None   # SequenceFlow：源节点
        self.targetRef: Optional["BO"] = None   # SequenceFlow：目标节点
        self.default: Optional["BO"] = None     # 网关：默认流
        self.conditionExpression: Optional["BO"] = None  # SequenceFlow：条件
        self.eventDefinitions: List["BO"] = []
        self.xml_line: int = xml_line

    # 等价于 bpmn-moddle 的 $instanceOf
    def is_a(self, t: str) -> bool:
        return t in _SUPERTYPES.get(self.type_, {self.type_})

    def is_any(self, types: List[str]) -> bool:
        return any(self.is_a(t) for t in types)


# --------------------------------------------------------------------------- #
# 模型解析
# --------------------------------------------------------------------------- #
class BpmnModel:
    """解析 BPMN XML，构建 BO 树并解析引用。"""

    def __init__(self, xml_text: str):
        self.processes: List[BO] = []
        self.by_id: Dict[str, BO] = {}
        self._id_lines: Dict[str, int] = {}
        # DI（图形坐标）存在性：bpmn-js 渲染流程图必需，缺了页面报 "no diagram to display"
        self.has_diagram: bool = False
        self.di_shape_count: int = 0
        self.di_edge_count: int = 0
        self._parse(xml_text)

    # ---- 解析入口 ----
    def _parse(self, xml_text: str) -> None:
        # 1) 用 expat 单独扫描一遍，记录每个带 id 元素的源码行号
        self._id_lines = _collect_id_lines(xml_text)
        # 2) ET 解析树
        root = ET.fromstring(xml_text)
        # root 通常是 <definitions>
        for child in list(root):
            local = _qname_local(child.tag)
            if local == "process":
                bo = self._build_bo(child)
                if bo:
                    self.processes.append(bo)
            elif local == "BPMNDiagram":
                self.has_diagram = True
                self.di_shape_count = _count_by_local(child, "BPMNShape")
                self.di_edge_count = _count_by_local(child, "BPMNEdge")
        # 3) 解析引用（sourceRef/targetRef/default）
        self._resolve_refs()

    def _build_bo(self, el: ET.Element) -> Optional[BO]:
        local = _qname_local(el.tag)
        if local not in _FLOW_ELEMENT_LOCALNAMES and local != "process":
            return None
        bpmn_type = _type_from_local(local)
        # ET attrib 的 key 仍是 `{ns}local` 形式
        raw_attrs = {k: v for k, v in el.attrib.items()}
        line = self._id_lines.get(raw_attrs.get("id"), 0)
        bo = BO(bpmn_type, raw_attrs, line)

        if bo.id:
            self.by_id[bo.id] = bo

        # 递归子元素
        for child in list(el):
            clocal = _qname_local(child.tag)
            if clocal == "conditionExpression":
                cbo = BO("bpmn:ConditionExpression", dict(child.attrib), 0)
                cbo.body = (child.text or "").strip()
                bo.conditionExpression = cbo
            elif clocal.endswith("EventDefinition"):
                cbo = BO("bpmn:" + clocal, dict(child.attrib), 0)
                bo.eventDefinitions.append(cbo)
            elif clocal in _FLOW_ELEMENT_LOCALNAMES:
                cbo = self._build_bo(child)
                if cbo is not None:
                    bo.flowElements.append(cbo)
        return bo

    def _resolve_refs(self) -> None:
        # 遍历所有 BO，连接 SequenceFlow 与节点
        for bo in self._iter_all():
            if bo.type_ == "bpmn:SequenceFlow":
                bo.sourceRef = self.by_id.get(bo._source_id) if bo._source_id else None
                bo.targetRef = self.by_id.get(bo._target_id) if bo._target_id else None
                if bo.sourceRef is not None:
                    bo.sourceRef.outgoing.append(bo)
                if bo.targetRef is not None:
                    bo.targetRef.incoming.append(bo)
            if bo._default_id:
                bo.default = self.by_id.get(bo._default_id)

    def _iter_all(self) -> List[BO]:
        """深度优先遍历所有 BO（容器先于其子元素）。"""
        acc: List[BO] = []

        def walk(bo: BO) -> None:
            acc.append(bo)
            for fe in bo.flowElements:
                if fe.is_a("bpmn:SubProcess"):
                    walk(fe)
                else:
                    acc.append(fe)

        for p in self.processes:
            walk(p)
        return acc

    def all_elements(self) -> List[BO]:
        return self._iter_all()


def _count_by_local(el: ET.Element, localname: str) -> int:
    """统计元素树中指定 localname 的子孙节点数（用于 DI 的 BPMNShape/BPMNEdge 计数）。"""
    count = 0
    if _qname_local(el.tag) == localname:
        count += 1
    for child in list(el):
        count += _count_by_local(child, localname)
    return count


def _collect_id_lines(xml_text: str) -> Dict[str, int]:
    """用 expat 扫描，记录每个带 id 属性的元素的起始行号。"""
    id_lines: Dict[str, int] = {}
    parser = expat.ParserCreate()
    parser.StartElementHandler = lambda name, attrs: (
        id_lines.update({attrs["id"]: parser.CurrentLineNumber})
        if "id" in attrs else None
    )
    try:
        parser.Parse(xml_text.encode("utf-8"), True)
    except expat.ExpatError:
        # 行号定位是增强项，解析失败时退化为 0（不影响规则检查）
        pass
    return id_lines


# --------------------------------------------------------------------------- #
# 表达式变量名提取（等价于源码 nD：基于 math.js 的 AST SymbolNode 提取）
# --------------------------------------------------------------------------- #
_EXPR_RESERVED = {"and", "or", "not", "true", "false", "null", "undefined",
                   "True", "False", "None", "in", "is"}


def extract_expr_vars(expr: str) -> List[str]:
    """从 ${...} 表达式中提取变量名（SymbolNode），近似 nD 的行为。"""
    if not expr:
        return []
    # 去掉 ${...} 包裹
    expr = re.sub(r"\$\{([^}]*)\}", r"\1", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    result: List[str] = []
    for m in re.finditer(r"[A-Za-z_]\w*", expr):
        tok = m.group(0)
        if tok in _EXPR_RESERVED:
            continue
        # 排除函数名（标识符紧跟 '('）
        rest = expr[m.end():].lstrip()
        if rest.startswith("("):
            continue
        if tok not in result:
            result.append(tok)
    return result


# --------------------------------------------------------------------------- #
# 问题与上报器
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    rule: str
    level: str
    element_id: Optional[str]
    element_type: str
    element_name: Optional[str]
    xml_line: int
    message: str


class Reporter:
    """单元素 + 单规则的问题收集器，等价于 JS 规则里的 `t`。"""

    def __init__(self, element: BO, rule: str, level: str,
                 issues: List[Issue], by_id: Dict[str, BO]):
        self._element = element
        self._rule = rule
        self._level = level
        self._issues = issues
        self._by_id = by_id

    def report(self, target_id: Optional[str], message: str) -> None:
        """上报问题。

        target_id 可与当前被检查元素不同（如容器规则上报子元素、
        或网关规则上报相连 SequenceFlow 的 id）。位置信息（类型/名称/行号）
        优先取 target_id 对应的真实元素；解析不到时退化为当前元素。
        """
        target = self._by_id.get(target_id) if target_id else None
        if target is None:
            target = self._element
        self._issues.append(Issue(
            rule=self._rule,
            level=self._level,
            element_id=target_id,
            element_type=target.type_,
            element_name=target.name,
            xml_line=target.xml_line,
            message=message,
        ))


# --------------------------------------------------------------------------- #
# 规则实现
# 每个函数签名: rule_xxx(e: BO, t: Reporter, ctx: "Linter") -> None
# 与源码 rD["bpmnlint/<name>"] = function(){ return { check: function(e, t){...} } } 一一对应。
# --------------------------------------------------------------------------- #
def _has_cond(flow: BO) -> bool:
    return flow.conditionExpression is not None


def rule_conditional_flows(e: BO, t: Reporter, ctx) -> None:
    # if (e.default || e.outgoing.find(LN)) { 出口>1 时，无条件且非默认的流报错 }
    has_default_or_cond = e.default is not None or any(_has_cond(f) for f in e.outgoing)
    if not has_default_or_cond:
        return
    outs = e.outgoing or []
    if len(outs) <= 1:
        return
    for f in outs:
        if not _has_cond(f) and e.default is not f:
            t.report(f.id, "序列流缺少条件")


def rule_end_event_required(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:Process", "bpmn:SubProcess"]):
        has_end = any(fe.is_a("bpmn:EndEvent") for fe in (e.flowElements or []))
        if not has_end:
            label = "Sub process" if e.is_a("bpmn:SubProcess") else "Process"
            t.report(e.id, label + " is missing end event")


def rule_event_sub_process_typed_start_event(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:SubProcess") and e.triggeredByEvent:
        for fe in (e.flowElements or []):
            if not fe.is_a("bpmn:StartEvent"):
                continue
            if len(fe.eventDefinitions) == 0:
                t.report(fe.id, "开始事件缺少事件定义")


def rule_no_complex_gateway(e: BO, t: Reporter, ctx) -> None:
    # 等价 disallowNodeType("bpmn:ComplexGateway")
    if e.is_a("bpmn:ComplexGateway"):
        t.report(e.id, "Element has disallowed type <bpmn:ComplexGateway>")


def rule_no_disconnected(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:Task", "bpmn:Gateway", "bpmn:SubProcess",
                 "bpmn:Event", "bpmn:CallActivity"]) and not e.triggeredByEvent:
        n = e.incoming or []
        r = e.outgoing or []
        if e.is_a("bpmn:StartEvent") and not r:
            t.report(e.id, "进程有未连接的元素")
        if e.is_a("bpmn:EndEvent") and not n:
            t.report(e.id, "进程有未连接的元素")
        if not e.is_any(["bpmn:StartEvent", "bpmn:EndEvent"]):
            if not (n and r):
                t.report(e.id, "进程有未连接的元素")


def rule_no_duplicate_sequence_flows(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:SequenceFlow"):
        body = e.conditionExpression.body if e.conditionExpression else ""
        src = e.sourceRef.id if e.sourceRef else e.id
        dst = e.targetRef.id if e.targetRef else e.id
        key = f"{src}#{dst}#{body}"
        if key in ctx.dup_seen:
            t.report(e.id, "有重复的序列流,请检查连线")
            if src and src not in ctx.dup_out:
                t.report(src, "有重复的传出序列流,请检查连线")
                ctx.dup_out[src] = True
            if dst and dst not in ctx.dup_in:
                t.report(dst, "有重复的传入序列流,请检查连线")
                ctx.dup_in[dst] = True
        else:
            ctx.dup_seen[key] = e


def rule_no_gateway_join_fork(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:Gateway"):
        n = e.incoming or []
        r = e.outgoing or []
        if len(n) > 1 and len(r) > 1:
            t.report(e.id, "网关不能同时合并和分叉")




def rule_branch_gateway_only(e: BO, t: Reporter, ctx) -> None:
    """分支只能出现在网关上（2026-08-15 新增，用户需求）：
    出边 > 1 的节点（分支点）必须是 Gateway——userTask/callActivity/Event 多出边
    = 隐式分裂，EasyOps 设计规范要求分支统一由网关表达（含人工按钮分支：
    节点后应插 exclusiveGateway 再分叉，否则引擎行为/前端展示不可控）。
    比 off 状态的 no-implicit-split 更严：不看条件与 default，出边数即判。"""
    if e.is_any(["bpmn:Task", "bpmn:Event", "bpmn:CallActivity", "bpmn:SubProcess"]):
        outs = e.outgoing or []
        if len(outs) > 1:
            labels = ", ".join(f.name or f.id for f in outs)
            t.report(e.id,
                     "节点存在 {} 条出边（分支点必须在网关上）：{}。"
                     "应在节点后插入排他网关再分叉".format(len(outs), labels[:60]))




def rule_no_implicit_split(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:Task", "bpmn:Event"]):
        outs = [f for f in (e.outgoing or [])
                if not _has_cond(f) and e.default is not f]
        if len(outs) > 1:
            t.report(e.id, "流程隐式分裂（分支点应在网关上）")


def rule_no_inclusive_gateway(e: BO, t: Reporter, ctx) -> None:
    # 等价 disallowNodeType("bpmn:InclusiveGateway")
    if e.is_a("bpmn:InclusiveGateway"):
        t.report(e.id, "Element has disallowed type <bpmn:InclusiveGateway>")


def rule_single_blank_start_event(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:FlowElementsContainer"):
        blanks = [fe for fe in (e.flowElements or [])
                  if fe.is_a("bpmn:StartEvent") and len(fe.eventDefinitions) == 0]
        if len(blanks) > 1:
            label = "子流程" if e.is_a("bpmn:SubProcess") else "流程"
            t.report(e.id, label + "有多个开始事件")


def rule_single_event_definition(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:Event") and len(e.eventDefinitions) > 1:
        t.report(e.id, "事件有多个事件定义")


def rule_start_event_required(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:Process", "bpmn:SubProcess"]):
        has_start = any(fe.is_a("bpmn:StartEvent") for fe in (e.flowElements or []))
        if not has_start:
            label = "Sub process" if e.is_a("bpmn:SubProcess") else "Process"
            t.report(e.id, label + " is missing start event")


def rule_sub_process_blank_start_event(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:SubProcess") and not e.triggeredByEvent:
        for fe in (e.flowElements or []):
            if not fe.is_a("bpmn:StartEvent"):
                continue
            if len(fe.eventDefinitions) > 0:
                t.report(fe.id, "子流程开始事件必须为空事件")


def rule_superfluous_gateway(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:Gateway"):
        n = e.incoming or []
        r = e.outgoing or []
        if len(n) == 1 and len(r) == 1:
            t.report(e.id, "网关多余（只有一个入口和一个出口）")


def rule_inclusive_gateway_appear_in_pairs(e: BO, t: Reporter, ctx) -> None:
    n = e.flowElements or []
    if n:
        r = [fe for fe in n if fe.is_a("bpmn:InclusiveGateway")]
        if len(r) % 2 != 0:
            t.report(r[-1].id, "网关一般要成对出现")


def rule_parallel_gateway_appear_in_pairs(e: BO, t: Reporter, ctx) -> None:
    n = e.flowElements or []
    if n:
        r = [fe for fe in n if fe.is_a("bpmn:ParallelGateway")]
        if len(r) % 2 != 0:
            t.report(r[-1].id, "网关一般要成对出现")


# 注意：源码此处为 "bpmn:ParallelGatewa"（笔误），已修正。
_GW_TYPES_DIRECT = ["bpmn:InclusiveGateway", "bpmn:ExclusiveGateway", "bpmn:ParallelGateway"]


def rule_gateway_cannot_be_directly_connected(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(_GW_TYPES_DIRECT):
        ins = e.incoming or []
        outs = e.outgoing or []
        a = any(f.sourceRef and f.sourceRef.type_ in _GW_TYPES_DIRECT for f in ins)
        o = any(f.targetRef and f.targetRef.type_ in _GW_TYPES_DIRECT for f in outs)
        if a or o:
            t.report(e.id, "网关不能直接连接")


def rule_gateway_cannot_be_directly_connected_to_end(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:InclusiveGateway", "bpmn:ExclusiveGateway"]):
        ins = e.incoming or []
        outs = e.outgoing or []
        i = any(f.sourceRef and f.sourceRef.type_ == "bpmn:StartEvent" for f in ins)
        a = any(f.targetRef and f.targetRef.type_ == "bpmn:EndEvent" for f in outs)
        if i or a:
            t.report(e.id, "网关不能直接连" + ("开始" if i else "结束"))


# 注意：源码此处为 "bpmn:ParallelGatewa"（笔误），已修正。
_GW_TYPES_COND = ["bpmn:InclusiveGateway", "bpmn:ExclusiveGateway", "bpmn:ParallelGateway"]


def rule_form_decision_vars_consistent(e: BO, t: Reporter, ctx) -> None:
    """表单决定流转的变量一致性（2026-08-15 新增，用户需求）：
    R1(error) 网关任一出边表达式引用的每个变量，必须存在于【紧邻上游节点】的
       flowable:formExpressionName 声明的变量名集合中——否则运行时变量无值，
      流转判断失败/走错分支。
    R2(warn)  上游决策节点声明的变量若在该网关全部出边表达式中均未出现——冗余声明，
       提示清理（不阻断）。
    说明：上游节点未声明任何变量（isFormDecision!=1）但出边表达式引用了变量时，
    同样按 R1 报错（变量来源不明）。"""
    if not e.is_any(["bpmn:ExclusiveGateway", "bpmn:InclusiveGateway", "bpmn:ParallelGateway"]):
        return
    ins = e.incoming or []
    outs = e.outgoing or []
    if not outs:
        return
    # 表达式变量全集（网关全部出边）
    expr_vars: List[str] = []
    for f in outs:
        if f.conditionExpression and f.conditionExpression.body:
            expr_vars.extend(extract_expr_vars(f.conditionExpression.body))
    expr_vars = list(dict.fromkeys(expr_vars))   # 去重保序
    if not expr_vars:
        return
    # 每条入边分别校验（多入边网关：任一上游没声明该变量即报——运行时走哪条入边不可预知）
    for f in ins:
        src = f.sourceRef
        if src is None:
            continue
        fen = src.attrs_.get("flowable:formExpressionName") or ""
        declared = [x.split(":")[0].strip() for x in fen.split(";")
                    if ":" in x and x.split(":")[0].strip()]
        # R1：表达式变量 ⊄ 声明集
        missing = [v for v in expr_vars if v not in declared]
        if missing:
            t.report(f.id,
                     "序列流表达式变量 {} 未在上游节点 [{}] 的 formExpressionName 变量（{}）中声明"
                     .format(", ".join(missing), src.name or src.id,
                             ", ".join(declared) if declared else "未声明"))
        # R2：声明未用（仅提示）
        if declared:
            unused = [v for v in declared if v not in expr_vars]
            if unused:
                t.report(f.id,
                         "上游节点声明变量 {} 在网关出边表达式中未使用（冗余声明）"
                         .format(", ".join(unused)))


def rule_flow_conditional_error(e: BO, t: Reporter, ctx) -> None:
    if not e.is_any(_GW_TYPES_COND):
        return
    n = e.incoming or []
    r = e.outgoing or []
    # 出口 > 1：每条出口流必须有 ${...} 包裹的条件
    if len(r) > 1:
        for f in r:
            body = f.conditionExpression.body if f.conditionExpression else None
            if body:
                if not re.match(r"^\$\{.*\}$", body):
                    t.report(f.id, "表达式需要用${}包裹")
            else:
                t.report(f.id, "序列流缺少条件")
    # 入口上游若是「表单决定流向」节点，校验表单变量与出口表达式变量一致
    for f in n:
        src = f.sourceRef
        if src is None:
            continue
        if src.attrs_.get("flowable:isFormDecision") == "1":
            fen = src.attrs_.get("flowable:formExpressionName")
            o = fen.split(";") if fen else None
            s = [x.split(":")[0] for x in o] if o else None  # 变量名
            l = [x.split(":")[1] for x in o] if o else None  # 表单字段
            if not (s and l and s[0] and l[0]):
                t.report(f.id, "使用了表单决定流转但未配置变量名和表单字段")
            for out_f in r:
                a: List[str] = []
                if out_f.conditionExpression and out_f.conditionExpression.body:
                    a = extract_expr_vars(out_f.conditionExpression.body)
                if not (a and all(v in (s or []) for v in a)):
                    t.report(f.id, "表单决定流转里的变量名与序列流上的表达式变量名不一致")


def rule_inclusive_gateway(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:InclusiveGateway"):
        n = e.incoming or []
        if len(n) > 1:
            return
        for f in n:
            src = f.sourceRef
            if not (src and src.attrs_.get("flowable:isFormDecision") == "1"):
                t.report(f.id, "包容分支网关前的节点必须要设置“表单决定流转”")


def rule_form_flow(e: BO, t: Reporter, ctx) -> None:
    """网关前节点非表单决定流转时表达式符号必须用 ==。
    源码布尔（2026-08-16 用 node 直接执行源码表达式定案）：
      不报 当且仅当 body 含 '=='（n_syms 范围符号判定的取反只影响 && 前段，
      只要 body 缺 '==' —— 无论空/纯标识符/含 >、>= 等 —— 一律 report）。
    实测矩阵：null/''/'abc'/'${x>1}'/'${x>=1}' 全报；'${x==1}' 不报。
    旧实现 NOT(a AND b AND c) 恰好等价本语义——无行为差异，仅精化注释与中文消息。"""
    n_syms = [">=", "<=", ">", "<", "!=", "!=="]
    if not e.is_any(_GW_TYPES_COND):
        return
    r = e.incoming or []
    outs = e.outgoing or []
    if len(r) > 1:
        return
    for f in r:
        src = f.sourceRef
        if src and src.attrs_.get("flowable:isFormDecision") == "1":
            continue
        for out_f in outs:
            body = out_f.conditionExpression.body if out_f.conditionExpression else None
            ok = body is not None and "==" in body and not any(op in body for op in n_syms if op != "!=" and op != "!==")
            if not ok:
                t.report(out_f.id, "网关前节点是非表单决定流转的表达式符号必须要用==")


def rule_auto_pass(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:UserTask"):
        r = e.attrs_.get("flowable:strategy")
        i = e.attrs_.get("flowable:isFormDecision") == "1"
        if r and "emptyAssign" not in r and not i:
            for f in (e.outgoing or []):
                if f.targetRef and f.targetRef.type_ in ["bpmn:InclusiveGateway", "bpmn:ExclusiveGateway"]:
                    t.report(f.sourceRef.id if f.sourceRef else e.id,
                             "用户任务的策略为『xx跳过』且非表单决定流转时，后面不能接 包容/排它网关")


def rule_sub_process_start(e: BO, t: Reporter, ctx) -> None:
    if e.is_a("bpmn:CallActivity"):
        r = e.incoming or []
        outs = e.outgoing or []
        for f in r:
            if f.sourceRef and f.sourceRef.type_ == "bpmn:StartEvent":
                t.report(f.id, "开始节点不能直接连接子流程")
        for f in outs:
            if f.targetRef and f.targetRef.type_ in ["bpmn:InclusiveGateway", "bpmn:ExclusiveGateway"]:
                t.report(f.id, "子流程后面不能接 包容/排它网关")


def rule_sub_process_quote(e: BO, t: Reporter, ctx) -> None:
    if e.is_any(["bpmn:ParallelGateway", "bpmn:InclusiveGateway"]):
        outs = e.outgoing or []
        call_flows = [f for f in outs if f.targetRef and f.targetRef.type_ == "bpmn:CallActivity"]
        if len(call_flows) > 1:
            s = call_flows[0].targetRef
            l = call_flows[-1].targetRef
            if s and l and s.calledElement and l.calledElement and s.calledElement == l.calledElement:
                t.report(s.id, "包容/并行网关后面的子流程，不能引用同一个子流程")
                t.report(l.id, "包容/并行网关后面的子流程，不能引用同一个子流程")


def _find_dup_group(items: List[BO], key: str) -> List[BO]:
    """按 key 分组，返回第一组长度>1 的全部元素（等价源码 name-required 内的分组函数）。"""
    groups: Dict[Any, List[BO]] = {}
    order: List[Any] = []
    for it in items:
        k = getattr(it, key, None)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(it)
    for k in order:
        if len(groups[k]) > 1:
            return groups[k]
    return []


def rule_name_required(e: BO, t: Reporter, ctx) -> None:
    n = e.flowElements or []
    if not n:
        return
    candidates = [fe for fe in n if fe.is_any(["bpmn:UserTask", "bpmn:CallActivity"])]
    dup = _find_dup_group(candidates, "name")
    if dup:
        for it in dup:
            t.report(it.id, "节点名称不能重复")
    for it in candidates:
        if it.name and len(it.name) > 20:
            t.report(it.id, "节点名称不能超过20个字符")
        if not (it.name and it.name.strip()):
            t.report(it.id, "节点名称不能为空")


def rule_flow_elements_length(e: BO, t: Reporter, ctx) -> None:
    n = e.flowElements or []
    if n and not any(fe.is_a("bpmn:UserTask") for fe in n):
        t.report(e.id, "进程缺少用户任务")


def rule_is_empty_element(e: BO, t: Reporter, ctx) -> None:
    # 严格类型相等：仅裸 <task> 报错，UserTask 等子类型不报
    if e.type_ == "bpmn:Task":
        t.report(e.id, "节点类型错误")


def rule_diagram_required(e: BO, t: Reporter, ctx) -> None:
    """BPMN 图形坐标（DI）存在性检查。

    bpmn-js 渲染流程图依赖 `<bpmndi:BPMNDiagram>` 中的 BPMNShape（节点坐标）
    与 BPMNEdge（连线坐标）；缺失时流程设计器报 "no diagram to display"。
    注意：这是**图形层**要求，与流程逻辑合规（发起工单）无关——
    逻辑不依赖 DI 也能流转，但页面无法渲染流程图。
    """
    if not e.is_a("bpmn:Process"):
        return
    m = getattr(ctx, "model", None)
    if m is None or m.has_diagram:
        return
    t.report(e.id, "BPMN XML 缺少 <bpmndi:BPMNDiagram> 图形坐标（BPMNShape/BPMNEdge），流程设计器将报 \"no diagram to display\"")


def rule_diagram_element_missing(e: BO, t: Reporter, ctx) -> None:
    """DI 存在但节点/连线坐标数量明显不足（如全空 Diagram）时提示。"""
    if not e.is_a("bpmn:Process"):
        return
    m = getattr(ctx, "model", None)
    if m is None or not m.has_diagram:
        return
    # 统计流程内逻辑节点/连线数量
    node_count = sum(1 for fe in (e.flowElements or [])
                     if fe.is_any(["bpmn:FlowNode"]))
    flow_count = sum(1 for fe in (e.flowElements or [])
                     if fe.is_a("bpmn:SequenceFlow"))
    if m.di_shape_count == 0 and m.di_edge_count == 0:
        t.report(e.id, "BPMNDiagram 存在但为空（无 BPMNShape/BPMNEdge），流程图仍无法渲染")


# --------------------------------------------------------------------------- #
# 规则注册表：(规则名, 等级, check 函数)
# 等级与源码 oD 配置完全一致。
# --------------------------------------------------------------------------- #
RULES: List[tuple] = [
    ("conditional-flows", "off", rule_conditional_flows),
    ("end-event-required", "error", rule_end_event_required),
    ("event-sub-process-typed-start-event", "off", rule_event_sub_process_typed_start_event),
    ("no-complex-gateway", "error", rule_no_complex_gateway),
    ("no-disconnected", "error", rule_no_disconnected),
    ("no-duplicate-sequence-flows", "error", rule_no_duplicate_sequence_flows),
    ("no-gateway-join-fork", "off", rule_no_gateway_join_fork),
    ("branch-gateway-only", "error", rule_branch_gateway_only),
    ("no-implicit-split", "off", rule_no_implicit_split),
    ("no-inclusive-gateway", "off", rule_no_inclusive_gateway),
    ("single-blank-start-event", "error", rule_single_blank_start_event),
    ("single-event-definition", "off", rule_single_event_definition),
    ("start-event-required", "error", rule_start_event_required),
    ("sub-process-blank-start-event", "off", rule_sub_process_blank_start_event),
    ("superfluous-gateway", "off", rule_superfluous_gateway),
    ("inclusive-gateway-appear-in-pairs", "warn", rule_inclusive_gateway_appear_in_pairs),
    ("parallel-gateway-appear-in-pairs", "warn", rule_parallel_gateway_appear_in_pairs),
    ("gateway-cannot-be-directly-connected", "error", rule_gateway_cannot_be_directly_connected),
    ("gateway-cannot-be-directly-connected-to-end", "warn", rule_gateway_cannot_be_directly_connected_to_end),
    # 业务扩展规则 flow-conditional-error / form-flow 已按要求永久关闭：
    # 两者对 flowable 表单表达式/网关符号的判定较激进，在现有流程中误报较多，默认不再检查。
    ("form-decision-vars-consistent", "error", rule_form_decision_vars_consistent),
    ("flow-conditional-error", "off", rule_flow_conditional_error),
    ("inclusive-gateway", "error", rule_inclusive_gateway),
    ("form-flow", "off", rule_form_flow),
    ("auto-pass", "warn", rule_auto_pass),
    ("sub-process-start", "error", rule_sub_process_start),
    ("sub-process-quote", "error", rule_sub_process_quote),
    ("name-required", "error", rule_name_required),
    ("flow-elements-length", "error", rule_flow_elements_length),
    ("is-empty-element", "error", rule_is_empty_element),
    # DI（图形坐标）存在性：缺了流程设计器报 "no diagram to display"（2026-08-04 主机申请流程实战补充）
    ("diagram-required", "error", rule_diagram_required),
    ("diagram-element-missing", "warn", rule_diagram_element_missing),
]


# --------------------------------------------------------------------------- #
# Linter
# --------------------------------------------------------------------------- #
class Linter:
    """规则调度器，持有跨元素状态（如 no-duplicate-sequence-flows 的去重表）。"""

    def __init__(self, include_off: bool = False):
        self.include_off = include_off
        # no-duplicate-sequence-flows 跨元素共享状态
        self.dup_seen: Dict[str, BO] = {}
        self.dup_out: Dict[str, bool] = {}
        self.dup_in: Dict[str, bool] = {}
        self.model: Optional[BpmnModel] = None  # DI 规则经 ctx 访问

    def lint(self, model: BpmnModel) -> List[Issue]:
        issues: List[Issue] = []
        self.model = model  # 供 DI 规则经 ctx 访问
        for e in model.all_elements():
            for name, level, fn in RULES:
                if level == "off" and not self.include_off:
                    continue
                rep = Reporter(e, name, level, issues, model.by_id)
                try:
                    fn(e, rep, self)
                except Exception as exc:  # 单条规则异常不中断整体检查
                    issues.append(Issue(
                        rule=name, level="error",
                        element_id=e.id, element_type=e.type_,
                        element_name=e.name, xml_line=e.xml_line,
                        message=f"[检测器内部错误] {type(exc).__name__}: {exc}",
                    ))
        return issues


# --------------------------------------------------------------------------- #
# 输入读取与输出
# --------------------------------------------------------------------------- #
def read_source(source: str) -> str:
    """source 为 '-' 时读 stdin；为已存在文件路径时读文件；否则按 XML 原文处理。"""
    if source == "-":
        return sys.stdin.read()
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as fh:
            return fh.read()
    # 非文件路径，当作 XML 原文
    return source


def format_text(issues: List[Issue]) -> str:
    if not issues:
        return "未检出任何流程设计问题。"
    lines = []
    for it in issues:
        tag = "ERROR" if it.level == "error" else "WARN "
        name = f"name={it.element_name}" if it.element_name else "name=-"
        line = f"line={it.xml_line}" if it.xml_line else "line=-"
        lines.append(
            f"[{tag}] {it.rule}  id={it.element_id or '-'}  type={it.element_type}  {name}  {line}"
        )
        lines.append(f"        {it.message}")
    err = sum(1 for i in issues if i.level == "error")
    warn = sum(1 for i in issues if i.level == "warn")
    lines.append(f"\n共检出 {len(issues)} 个问题（error={err}, warn={warn}）")
    return "\n".join(lines)


def format_json(issues: List[Issue]) -> str:
    return json.dumps([asdict(i) for i in issues], ensure_ascii=False, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="BPMN 流程设计合规检测器（基于 bpmn-js-bpmnlint 27 条规则的等价实现）",
    )
    parser.add_argument(
        "source",
        help="BPMN XML 文件路径，或直接 XML 原文（若非已存在文件则按原文解析）；"
             "传入 '-' 可从 stdin 读取",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出全部问题")
    parser.add_argument("--include-off", action="store_true",
                        help="同时运行默认关闭(off)的规则（按其等级报告）")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="即使存在 error 级问题也返回退出码 0")
    args = parser.parse_args(argv)

    try:
        xml_text = read_source(args.source)
    except OSError as exc:
        print(f"读取输入失败: {exc}", file=sys.stderr)
        return 2

    try:
        model = BpmnModel(xml_text)
    except ET.ParseError as exc:
        print(f"XML 解析失败: {exc}", file=sys.stderr)
        return 2

    if not model.processes:
        print("未在 XML 中找到 <process> 元素，无法检测。", file=sys.stderr)
        return 2

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
