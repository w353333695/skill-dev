#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyOps 流程表单设计合规检测器
================================

对一份 EasyOps 流程表单 JSON（顶层为「容器数组」，容器内 `propertys`
为控件数组）做**设计期 schema 静态合规检查**，一次性输出全部问题，并
标注每个问题的：

- `rule`：规则名
- `level`：等级（`error` / `warn`）
- `path`：违规元素在 JSON 中的定位路径（如 `[0].propertys[3]`）
- `element_id`：违规元素的 `key` / `modelField`（若存在）
- `element_type`：元素类型（容器 type / 控件 type）
- `element_name`：元素标题（容器 `name` / 控件 `label`）
- `message`：问题描述

规则来源：前端 bundle `tmp/index.9c69d18d.js`（表单设计器 i18n 文案常量
+ 运行时代码），并用真实样本 `./sample.json` 校准字段路径。本文只做
「设计期 schema 校验」（对标流程设计合规检测），不做用户填写值的运行期
校验（必填命中、正则匹配是运行期的事）。

设计要点：
- 零依赖，仅使用 Python 3.8+ 标准库。
- 接受「JSON 文件路径」「JSON 原文」「-」(stdin) 三态输入。
- 默认启用 error/warn 全部规则；off 规则默认跳过（可用 --include-off 开启）。
- 文案与源码 i18n 常量保持一致（如「控件字段id {{value}} 不能重复」）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# 已知类型清单（来源：bundle WIDGET_*_NAME / CONTAINER_*_NAME 枚举）
# --------------------------------------------------------------------------- #
CONTAINER_TYPES = {
    "row", "table", "tabs", "inspection_checklist",
    "cmdb_instance_operate_container",
    "business_table",                       # CMDB 数据写入容器
    "business_cmdb_instance_change_table",  # CMDB 实例变更容器
}

CONTROL_TYPES = {
    # 输入
    "INPUT", "TEXTAREA", "NUMBERINPUT", "ARRATINPUT", "RICHTEXT",
    # 选择
    "SELECT", "MULTIPLESELECT", "RADIO", "CHECKBOX", "CASCADER",
    "MODALSELECT", "SWITCH", "SLIDER",
    # 日期时间
    "COMMONDATE", "DATE", "TIME", "DATERANGE", "TIMERANGE",
    # 人员组织
    "USER_SELECTOR", "USER_GROUP_SELECTOR", "DEPARTMENT_SELECTOR",
    # 附件
    "UPLOAD", "LARGEFILE_UPLOAD",
    # CMDB
    "CMDBINSTANCESELECT", "CMDBCASCADER", "CMDB_WRITE_STRUCTS",
    # 其它
    "DATAINHERIT", "TIPS", "IFRAME", "LINK", "BUTTON",
}

# 需要模型 objectId 的 CMDB 容器
CMDB_OPERATE_CONTAINER = "cmdb_instance_operate_container"

# id 命名规则：只允许字母、数字、@、_，且不能纯数字
# 来源：bundle CONTAINER_ID_NOT_VALID / FIELD_ID_NOT_VALID
#   "不能为纯数字,不能包含@_外的特殊字符"
_ID_VALID_RE = re.compile(r"^[A-Za-z0-9@_]+$")
_ID_NUMERIC_RE = re.compile(r"^[0-9]+$")

# 标题长度上限（来源：CONTROL_TITLE_LENGTH_EXCEEDS_20 / CONTAINER_TITLE_LENGTH_EXCEEDS_20）
TITLE_MAX_LEN = 20


def _is_blank(s: Any) -> bool:
    """字符串为 None 或纯空白。"""
    return not (isinstance(s, str) and s.strip())


def _id_invalid(idval: Any) -> bool:
    """id 不合法：含非法字符 或 纯数字 或 空。"""
    if not isinstance(idval, str) or not idval:
        return True
    if not _ID_VALID_RE.match(idval):
        return True
    if _ID_NUMERIC_RE.match(idval):
        return True
    return False


# --------------------------------------------------------------------------- #
# 问题与上报器
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    rule: str
    level: str
    path: str
    element_id: Optional[str]
    element_type: str
    element_name: Optional[str]
    message: str


class Reporter:
    """单元素 + 单规则的问题收集器。"""

    def __init__(self, path: str, element: dict, rule: str, level: str,
                 issues: List[Issue]):
        self._path = path
        self._element = element
        self._rule = rule
        self._level = level
        self._issues = issues

    def report(self, message: str, *,
               element_id: Optional[str] = ...,       # 默认取元素 key
               element_type: Optional[str] = ...,     # 默认取元素 type
               element_name: Optional[str] = ...,     # 默认取元素 name/label
               path: Optional[str] = None) -> None:
        self._issues.append(Issue(
            rule=self._rule,
            level=self._level,
            path=path or self._path,
            element_id=self._element.get("key") if element_id is ... else element_id,
            element_type=self._element.get("type") if element_type is ... else element_type,
            element_name=(self._element.get("name") or self._element.get("label"))
            if element_name is ... else element_name,
            message=message,
        ))


# --------------------------------------------------------------------------- #
# 规则实现
# 每个函数签名: rule_xxx(node: dict, t: Reporter, ctx: "Linter") -> None
# node 可能是容器（顶层元素）或控件（propertys 元素）。
# --------------------------------------------------------------------------- #
def rule_unknown_container_type(node: dict, t: Reporter, ctx) -> None:
    """顶层（容器位）元素的 type 不在已知 7 种内。按结构位置判定，不依赖 type 合法性。"""
    if ctx.current_role != "container":
        return
    typ = node.get("type")
    if typ not in CONTAINER_TYPES:
        t.report(f"未知的容器类型 {typ!r}，已知：{sorted(CONTAINER_TYPES)}")


def rule_unknown_control_type(node: dict, t: Reporter, ctx) -> None:
    """控件位元素的 type 不在已知 30 种内。"""
    if ctx.current_role != "control":
        return
    typ = node.get("type")
    if typ not in CONTROL_TYPES:
        t.report(f"未知的控件类型 {typ!r}，已知 {len(CONTROL_TYPES)} 种")


def rule_container_type_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node) and not node.get("type"):
        t.report("容器类型不能为空")  # CONTAINER_TYPE_CANNOT_BE_EMPTY


def rule_container_id_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node) and not node.get("key"):
        t.report("容器id不能为空")  # CONTAINER_ID_CANNOT_BE_EMPTY


def rule_control_id_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        if not node.get("key") or not node.get("modelField"):
            t.report("控件字段id不能为空")  # CONTROL_FIELD_ID_CANNOT_BE_EMPTY


def _rule_id_invalid(node: dict, t: Reporter, ctx, label: str, field: str) -> None:
    val = node.get(field)
    if val and _id_invalid(val):
        t.report(f"{label} {val!r} 不合法：不能为纯数字，不能包含 @ _ 外的特殊字符",
                 element_id=val)  # CONTAINER_ID_NOT_VALID / FIELD_ID_NOT_VALID


def rule_container_id_invalid(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node):
        _rule_id_invalid(node, t, ctx, "容器id", "key")


def rule_control_id_invalid(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        _rule_id_invalid(node, t, ctx, "控件字段id", "modelField")


def rule_control_title_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        label = node.get("label")
        if _is_blank(label):
            t.report("控件标题不能为空")  # CONTROL_TITLE_CANNOT_BE_EMPTY
        elif label != label.strip():
            t.report("控件标题不能为空格")  # CONTROL_TITLE_CANNOT_BE_SPACES


def rule_control_title_length(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        label = node.get("label")
        if isinstance(label, str) and len(label) > TITLE_MAX_LEN:
            t.report(f"控件标题长度不能超过 {TITLE_MAX_LEN} 个字符（当前 {len(label)}）")
            # CONTROL_TITLE_LENGTH_EXCEEDS_20


def rule_container_title_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node):
        name = node.get("name")
        if _is_blank(name):
            t.report("容器标题不能为空")  # CONTAINER_TITLE_CANNOT_BE_EMPTY
        elif name != name.strip():
            t.report("容器标题不能为空格")  # CONTAINER_TITLE_CANNOT_BE_SPACES


def rule_container_title_length(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node):
        name = node.get("name")
        if isinstance(name, str) and len(name) > TITLE_MAX_LEN:
            t.report(f"容器标题长度不能超过 {TITLE_MAX_LEN} 个字符（当前 {len(name)}）")
            # CONTAINER_TITLE_LENGTH_EXCEEDS_20


def rule_belong_disconnected(node: dict, t: Reporter, ctx) -> None:
    """控件 belongToSection 指向不存在的容器 key。"""
    if ctx.is_control(node):
        belong = node.get("belongToSection")
        if belong and belong not in ctx.container_keys:
            t.report(f"控件 belongToSection={belong!r} 指向不存在的容器")  # 引用悬空


def rule_belong_missing(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node) and not node.get("belongToSection"):
        t.report("控件缺少 belongToSection，无法归属到任何容器")


def rule_pattern_enabled_but_empty(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        o = node.get("options") or {}
        if o.get("isEnablePattern") is True and not o.get("pattern"):
            t.report("启用了正则校验(isEnablePattern=true)但未填写 pattern")


def rule_pattern_hint_missing(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        o = node.get("options") or {}
        if o.get("isEnablePattern") is True and not (o.get("patternErrorHint") or "").strip():
            t.report("启用了正则校验但未填写 patternErrorHint（正则错误提示）")


def rule_pattern_without_flag(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_control(node):
        o = node.get("options") or {}
        if (o.get("pattern") or "").strip() and not o.get("isEnablePattern") is True:
            t.report("填写了 pattern 但未启用 isEnablePattern，正则可能不生效")


def rule_select_candidate_field(node: dict, t: Reporter, ctx) -> None:
    """选择类控件候选字段名校验。

    前端 itsc-ticket-center 控件渲染器(Me)对候选直接 .map 无兜底：
      SELECT/MULTIPLESELECT/CHECKBOX → options.extraProps.items
      RADIO/CASCADER                  → options.extraProps.options
    字段名错位或缺失会触发 'Cannot read properties of undefined (reading map)'。
    """
    if not ctx.is_control(node):
        return
    ctype = node.get("type")
    ITEMS_TYPES = {"SELECT", "MULTIPLESELECT", "CHECKBOX"}
    OPTIONS_TYPES = {"RADIO", "CASCADER"}
    if ctype not in ITEMS_TYPES and ctype not in OPTIONS_TYPES:
        return
    o = node.get("options") or {}
    ep = o.get("extraProps") or {}
    if ctype in ITEMS_TYPES:
        if "options" in ep and "items" not in ep:
            t.report(f"{ctype} 候选错放在 extraProps.options（应为 extraProps.items），前端 items.map 会崩")
        elif "items" not in ep or not isinstance(ep.get("items"), list):
            t.report(f"{ctype} 缺少 extraProps.items（候选数组），前端 items.map 无兜底会崩")
    else:  # RADIO / CASCADER
        if "items" in ep and "options" not in ep:
            t.report(f"{ctype} 候选错放在 extraProps.items（应为 extraProps.options），前端 options.map 会崩")
        elif "options" not in ep or not isinstance(ep.get("options"), list):
            t.report(f"{ctype} 缺少 extraProps.options（候选数组），前端 options.map 无兜底会崩")


def rule_container_layout_required(node: dict, t: Reporter, ctx) -> None:
    """容器顶层 layout 必填：前端按 layout[1] 对容器排序（无兜底）。"""
    if ctx.is_control(node):
        return
    if node.get("layout") is None:
        t.report("容器缺少顶层 layout（[x,y,w,h]），前端按 layout[1] 排序无兜底会崩")


def rule_control_layout_required(node: dict, t: Reporter, ctx) -> None:
    """控件 options.layout 必填：前端按 layout[2]/[3] 算宽高（无兜底）。"""
    if not ctx.is_control(node):
        return
    o = node.get("options") or {}
    if o.get("layout") is None:
        t.report("控件缺少 options.layout（[x,y,w,h]），前端按 layout[2]/[3] 算宽高无兜底会崩")


def _is_valid_layout(L: Any) -> bool:
    return isinstance(L, list) and len(L) == 4 and all(
        isinstance(x, (int, float)) for x in L)


def rule_layout_malformed(node: dict, t: Reporter, ctx) -> None:
    # 控件 layout 在 options.layout；容器 layout 在 node.layout
    if ctx.is_control(node):
        L = (node.get("options") or {}).get("layout")
    else:
        L = node.get("layout")
    if L is not None and not _is_valid_layout(L):
        t.report(f"layout 格式非法，应为 [x,y,w,h] 四个数字，实际为 {L!r}")


def rule_layout_width_exceed(node: dict, t: Reporter, ctx) -> None:
    """控件 layout[2](w) 超过所在容器的 columns（默认 12）。"""
    if not ctx.is_control(node):
        return
    o = node.get("options") or {}
    L = o.get("layout")
    belong = node.get("belongToSection")
    container = ctx.container_by_key.get(belong)
    if not (isinstance(L, list) and len(L) == 4 and container):
        return
    w = L[2]
    columns = ((container.get("layoutConfig") or {}).get("columns")) or 12
    if isinstance(w, (int, float)) and w > columns:
        t.report(f"控件布局宽度 {w} 超过容器分栏数 {columns}")


def rule_cmdb_operate_no_model(node: dict, t: Reporter, ctx) -> None:
    """CMDB 实例操作容器未配置模型 ID。"""
    if ctx.is_container(node) and node.get("type") == CMDB_OPERATE_CONTAINER:
        ep = node.get("extraProps") or {}
        model = ep.get("cmdbInstanceChangeModel") or {}
        if not (model.get("objectId") or "").strip():
            name = node.get("name") or "-"
            t.report(f"容器标题为 【{name}】 的 CMDB 实例操作容器未配置模型ID")
            # CMDB_OPERATE_CONTAINER_NO_MODEL_ID


def rule_cmdb_operate_no_show_fields(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node) and node.get("type") == CMDB_OPERATE_CONTAINER:
        ep = node.get("extraProps") or {}
        model = ep.get("cmdbInstanceChangeModel") or {}
        modify = model.get("cmdbModifyFields") or {}
        has = (modify.get("attrIds") or modify.get("relationAttrIds"))
        if not has:
            name = node.get("name") or "-"
            t.report(f"容器标题为 【{name}】 的 CMDB 实例操作容器未配置展示字段")
            # CMDB_OPERATE_CONTAINER_NO_SHOW_FIELDS


def rule_modelfield_key_mismatch(node: dict, t: Reporter, ctx) -> None:
    key = node.get("key")
    mf = node.get("modelField")
    if key and mf and key != mf:
        t.report(f"modelField={mf!r} 与 key={key!r} 不一致，二者应相等")


def rule_condition_boolean(node: dict, t: Reporter, ctx) -> None:
    if ctx.is_container(node):
        cond = node.get("condition")
        if cond is not None and not isinstance(cond, bool):
            t.report(f"容器 condition 应为布尔值，实际为 {type(cond).__name__}({cond!r})")


# 跨元素去重规则（需要 ctx 维护全表状态），单独在 Linter 里实现：
#   field-id-duplicate / container-id-duplicate


# --------------------------------------------------------------------------- #
# 规则注册表：(规则名, 等级, check 函数)
# --------------------------------------------------------------------------- #
RULES: List[Tuple[str, str, Any]] = [
    # 结构
    ("unknown-container-type", "error", rule_unknown_container_type),
    ("unknown-control-type", "error", rule_unknown_control_type),
    ("container-type-empty", "error", rule_container_type_empty),
    # 标识 - 空
    ("container-id-empty", "error", rule_container_id_empty),
    ("control-id-empty", "error", rule_control_id_empty),
    # 标识 - 合法性
    ("container-id-invalid", "error", rule_container_id_invalid),
    ("control-id-invalid", "error", rule_control_id_invalid),
    # 标题
    ("control-title-empty", "error", rule_control_title_empty),
    ("control-title-length", "error", rule_control_title_length),
    ("container-title-empty", "error", rule_container_title_empty),
    ("container-title-length", "error", rule_container_title_length),
    # 引用
    ("belong-disconnected", "error", rule_belong_disconnected),
    ("belong-missing", "warn", rule_belong_missing),
    # 正则
    ("pattern-enabled-but-empty", "error", rule_pattern_enabled_but_empty),
    ("pattern-hint-missing", "warn", rule_pattern_hint_missing),
    ("pattern-without-flag", "warn", rule_pattern_without_flag),
    # 选择类候选字段名（前端无兜底崩点）
    ("select-candidate-field", "error", rule_select_candidate_field),
    # 布局
    ("container-layout-required", "error", rule_container_layout_required),
    ("control-layout-required", "error", rule_control_layout_required),
    ("layout-malformed", "error", rule_layout_malformed),
    ("layout-width-exceed", "warn", rule_layout_width_exceed),
    # CMDB
    ("cmdb-operate-no-model", "error", rule_cmdb_operate_no_model),
    ("cmdb-operate-no-show-fields", "warn", rule_cmdb_operate_no_show_fields),
    # 一致性
    ("modelfield-key-mismatch", "warn", rule_modelfield_key_mismatch),
    ("condition-boolean", "warn", rule_condition_boolean),
    # 去重（占位，实际在 Linter.lint 里跨元素执行）
    ("container-id-duplicate", "error", None),
    ("field-id-duplicate", "error", None),
]


# --------------------------------------------------------------------------- #
# Linter
# --------------------------------------------------------------------------- #
class Linter:
    """规则调度器，持有跨元素状态（容器索引、去重表）。"""

    def __init__(self, include_off: bool = False):
        self.include_off = include_off
        self.container_keys: set = set()
        self.container_by_key: Dict[str, dict] = {}
        self.current_role: str = ""   # 当前节点的结构位置角色：container / control

    # ---- 节点角色判定（基于结构位置，不依赖 type 合法性）----
    def is_container(self, node: Any) -> bool:
        return self.current_role == "container"

    def is_control(self, node: Any) -> bool:
        return self.current_role == "control"

    # ---- 收集所有节点 + 路径 + 角色 ----
    def _walk(self, data: list) -> List[Tuple[dict, str, str]]:
        """返回 (node, path, role) 列表；role 由结构位置决定：
        顶层数组元素为 container，propertys 内元素为 control。"""
        nodes: List[Tuple[dict, str, str]] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            cpath = f"[{i}]"
            nodes.append((item, cpath, "container"))
            for j, prop in enumerate(item.get("propertys") or []):
                if isinstance(prop, dict):
                    nodes.append((prop, f"{cpath}.propertys[{j}]", "control"))
        return nodes

    def lint(self, data: list) -> List[Issue]:
        issues: List[Issue] = []

        # 预扫描：顶层元素一律视为容器位，按 key 建索引（供 belong/layout-width 查询）
        for item in data:
            if isinstance(item, dict):
                k = item.get("key")
                if k is not None:
                    self.container_keys.add(k)
                    self.container_by_key[k] = item

        nodes = self._walk(data)

        # 1) 逐节点、逐规则
        for node, path, role in nodes:
            self.current_role = role
            for name, level, fn in RULES:
                if fn is None:
                    continue  # 去重规则单独处理
                if level == "off" and not self.include_off:
                    continue
                rep = Reporter(path, node, name, level, issues)
                try:
                    fn(node, rep, self)
                except Exception as exc:  # 单条规则异常不中断整体检查
                    issues.append(Issue(
                        rule=name, level="error", path=path,
                        element_id=node.get("key"),
                        element_type=node.get("type"),
                        element_name=node.get("name") or node.get("label"),
                        message=f"[检测器内部错误] {type(exc).__name__}: {exc}",
                    ))

        # 2) 跨元素去重：容器 key（顶层元素）
        self._check_dup(data, key_field="key", scope="container",
                        rule="container-id-duplicate",
                        msg_tmpl="容器id {value!r} 不能重复",
                        path_tmpl="[{i}]", issues=issues)
        # 3) 跨元素去重：控件 modelField（全表）
        self._check_dup_controls(data, issues)

        return issues

    def _check_dup(self, data: list, *, key_field: str, scope: str,
                   rule: str, msg_tmpl: str, path_tmpl: str,
                   issues: List[Issue]) -> None:
        level = self._level_of(rule)
        if level == "off" and not self.include_off:
            return
        groups: Dict[str, List[Tuple[int, dict]]] = {}
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            # scope=="container"：顶层元素全部参与（不按 type 过滤，因 type 可能非法）
            val = item.get(key_field)
            if val is None:
                continue
            groups.setdefault(val, []).append((i, item))
        for val, hits in groups.items():
            if len(hits) > 1:
                for i, item in hits:
                    rep = Reporter(path_tmpl.format(i=i), item, rule, level, issues)
                    rep.report(msg_tmpl.format(value=val))

    def _check_dup_controls(self, data: list, issues: List[Issue]) -> None:
        rule = "field-id-duplicate"
        level = self._level_of(rule)
        if level == "off" and not self.include_off:
            return
        groups: Dict[str, List[Tuple[str, dict]]] = {}
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            for j, prop in enumerate(item.get("propertys") or []):
                if not isinstance(prop, dict):
                    continue
                val = prop.get("modelField")
                if val is None:
                    continue
                groups.setdefault(val, []).append((f"[{i}].propertys[{j}]", prop))
        for val, hits in groups.items():
            if len(hits) > 1:
                for path, prop in hits:
                    rep = Reporter(path, prop, rule, level, issues)
                    rep.report(f"控件字段id {val!r} 不能重复",
                               element_id=val)  # FIELD_ID_DUPLICATE

    def _level_of(self, rule: str) -> str:
        for name, level, _ in RULES:
            if name == rule:
                return level
        return "error"


# --------------------------------------------------------------------------- #
# 输入读取与输出
# --------------------------------------------------------------------------- #
def read_source(source: str) -> str:
    """source 为 '-' 时读 stdin；为已存在文件路径时读文件；否则按 JSON 原文处理。"""
    if source == "-":
        return sys.stdin.read()
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as fh:
            return fh.read()
    return source


def format_text(issues: List[Issue]) -> str:
    if not issues:
        return "未检出任何表单设计问题。"
    lines = []
    for it in issues:
        tag = "ERROR" if it.level == "error" else "WARN "
        eid = f"id={it.element_id}" if it.element_id else "id=-"
        etype = f"type={it.element_type}" if it.element_type else "type=-"
        name = f"name={it.element_name}" if it.element_name else "name=-"
        lines.append(
            f"[{tag}] {it.rule}  path={it.path}  {eid}  {etype}  {name}"
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
        description="EasyOps 流程表单设计合规检测器（设计期 schema 静态校验）",
    )
    parser.add_argument(
        "source",
        help="表单 JSON 文件路径，或直接 JSON 原文（若非已存在文件则按原文解析）；"
             "传入 '-' 可从 stdin 读取",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出全部问题")
    parser.add_argument("--include-off", action="store_true",
                        help="同时运行默认关闭(off)的规则（按其等级报告）")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="即使存在 error 级问题也返回退出码 0")
    args = parser.parse_args(argv)

    try:
        raw = read_source(args.source)
    except OSError as exc:
        print(f"读取输入失败: {exc}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"JSON 解析失败: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, list):
        print("表单顶层应为数组（容器数组），无法检测。", file=sys.stderr)
        return 2
    if not data:
        # 顶层为空数组：container-required
        issues = [Issue(rule="container-required", level="error", path="[]",
                        element_id=None, element_type=None, element_name=None,
                        message="表单至少需要 1 个容器（顶层容器数组为空）")]
    else:
        issues = Linter(include_off=args.include_off).lint(data)

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
