"""${...} 表达式解析与求值（手写白名单，防 LLM 越界）。

严格支持 4 种合法形式：
- ``${item}``：foreach 内占位（step="item"）
- ``${<step>.<bind>}``：取某步骤 bind 的整个值
- ``${<step>.<bind>.<field>}``：bind 是 list[dict]，投影出每个 dict 的 field
- ``${join(<dotted>, '<sep>')}``：把 list 投影后用 sep 拼接成字符串

其余形式一律拒绝（双点、层级过深、``__import__`` 越界、join 缺 sep / sep 非字面量等），
抛 :class:`ExprError`，便于 LLM 根据错误修正。

设计要点：解析走严格白名单正则，**绝不**用 eval；求值只按 context 字典取值，
类型不符（如在非数组上做 field 投影）也抛 ExprError。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import re


class ExprError(Exception):
    """表达式解析或求值错误。"""


# ---------- AST 节点 ----------

@dataclass(frozen=True)
class VarRef:
    """变量引用 ``${step[.bind[.field]]}``。

    Attributes:
        step: 步骤 id（或固定 ``item``）
        bind: 步骤 output 绑定的名字；``${item}`` 形式下为 None
        field: bind 是 list[dict] 时，投影出该字段；否则 None
    """
    step: str
    bind: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class JoinCall:
    """``${join(arr_expr, sep)}``：把 list 投影后用 sep 拼成字符串。"""
    arr_expr: VarRef
    sep: str


# ---------- 解析 ----------

# 用字符类 [$] [{] [(] [)] 避开反斜杠转义（防 Write 工具误转义）。
# join(s1.fields.instanceId, ',')  形式；dotted 必须 2-3 段，sep 是单引号字面量
_DOLLAR = "[$]"
_LB = "[{]"
_RB = "[}]"
_LP = "[(]"
_RP = "[)]"
_IDENT = r"[a-zA-Z_]\w*"
_DOTTED = _IDENT + r"(?:\." + _IDENT + r"){1,2}"

_JOIN_RE = re.compile(
    "^" + _DOLLAR + _LB + r"join" + _LP + "(" + _DOTTED + r"),\s*'([^']*)'\s*" + _RP + _RB + "$"
)
# ${item} / ${step} / ${step.bind} / ${step.bind.field}  形式（最多 3 段）
_VAR_RE = re.compile(
    "^" + _DOLLAR + _LB + "(" + _IDENT + r")(?:\.(" + _IDENT + r"))?(?:\.(" + _IDENT + r"))?" + _RB + "$"
)
# 越界关键字直接拒绝
_BAD_KEYWORDS = ("import", "eval", "exec", "open", "__")


def parse(expr: str) -> VarRef | JoinCall:
    """把 ``${...}`` 字符串解析为 AST 节点；非法形式抛 :class:`ExprError`。"""
    if not isinstance(expr, str):
        raise ExprError("表达式必须是字符串：" + repr(expr))
    s = expr.strip()

    # 越界关键字直接拒绝
    if any(kw in s for kw in _BAD_KEYWORDS):
        raise ExprError("表达式含越界关键字：" + repr(expr))

    # 缺 ${...} 包裹
    if not (s.startswith("${") and s.endswith("}")):
        raise ExprError("表达式必须用 ${...} 包裹：" + repr(expr))

    # join(...) 形式
    if s.startswith("${join("):
        m = _JOIN_RE.match(s)
        if not m:
            raise ExprError(
                "join 表达式格式非法（应为 ${join(<a.b[.c]>, '<sep>')}）：" + repr(expr)
            )
        dotted, sep = m.group(1), m.group(2)
        arr = _parse_dotted(dotted)
        if arr.field is None:
            # join 的目标必须是 list[scalar]，由 dotted.a.b.field 给出
            raise ExprError(
                "join 目标必须是 <step>.<bind>.<field> 形式：" + repr(expr)
            )
        return JoinCall(arr_expr=arr, sep=sep)

    # 普通 VarRef 形式
    m = _VAR_RE.match(s)
    if not m:
        raise ExprError("表达式格式非法：" + repr(expr))
    step, bind, field = m.group(1), m.group(2), m.group(3)
    # 双点 / 层级过深已由正则排除（不允许多于 3 段）
    # 非 item 的 step 必须带 bind（${s1} 单独 step 非法）
    if step != "item" and bind is None:
        raise ExprError("非 item 引用必须带 bind：" + repr(expr))
    return VarRef(step=step, bind=bind, field=field)


def _parse_dotted(dotted: str) -> VarRef:
    """把 ``a.b[.c]`` 解析为 VarRef；段数不在 [2,3] 抛错。"""
    parts = dotted.split(".")
    if len(parts) < 2 or len(parts) > 3:
        raise ExprError("dotted 路径段数非法：" + repr(dotted))
    if any(not p for p in parts):
        raise ExprError("dotted 含空段（双点）：" + repr(dotted))
    if not all(re.fullmatch(r"[a-zA-Z_]\w*", p) for p in parts):
        raise ExprError("dotted 含非法标识符：" + repr(dotted))
    if len(parts) == 2:
        return VarRef(step=parts[0], bind=parts[1])
    return VarRef(step=parts[0], bind=parts[1], field=parts[2])


# ---------- 求值 ----------

def eval_expr(node: VarRef | JoinCall, context: dict) -> Any:
    """按 context 求值；缺 step/bind、类型不符均抛 :class:`ExprError`。"""
    if isinstance(node, JoinCall):
        arr = eval_expr(node.arr_expr, context)
        if not isinstance(arr, list):
            raise ExprError("join 目标不是数组：" + repr(node.arr_expr))
        return node.sep.join(str(x) for x in arr)

    # VarRef
    if node.step == "item":
        if "item" not in context:
            raise ExprError("上下文中不存在 item")
        return context["item"]

    if node.step not in context:
        raise ExprError("步骤不存在：" + node.step)
    cur = context[node.step]

    if node.bind is None:
        # 形如 ${step}：不常用，但允许（直接返回 step 上下文）
        return cur
    if not isinstance(cur, dict) or node.bind not in cur:
        raise ExprError(
            "步骤 " + node.step + " 下不存在 bind " + repr(node.bind)
        )
    val = cur[node.bind]

    if node.field is None:
        return val
    # 字段取值：
    #   - val 是 list[dict] → 投影出每个 dict 的该字段（原 list 语义）
    #   - val 是 dict       → 直接取该字段（嵌套字典访问，MVP-1.5 when 用）
    if isinstance(val, dict):
        if node.field not in val:
            raise ExprError(
                node.step + "." + node.bind + " 字典无字段 " + repr(node.field)
            )
        return val[node.field]
    if not isinstance(val, list):
        raise ExprError(
            node.step + "." + node.bind + " 不是数组，无法投影字段 " + node.field
        )
    out = []
    for it in val:
        if isinstance(it, dict) and node.field in it:
            out.append(it[node.field])
        else:
            raise ExprError(
                node.step + "." + node.bind + " 元素缺字段 " + repr(node.field)
            )
    return out


# ---------- when 轻量判定器（MVP-1.5）----------

import re as _re

# when 四种受批准形式（spec §4.2）。${...} 内部由 parse/eval_expr 取值。
_WHEN_EQ_NULL = _re.compile(r"^\$\{[^}]+\}\s*==\s*null$")
_WHEN_NE_NULL = _re.compile(r"^\$\{[^}]+\}\s*!=\s*null$")
_WHEN_EQ_LIT = _re.compile(r"^\$\{[^}]+\}\s*==\s*'([^']*)'$")
_WHEN_SINGLE = _re.compile(r"^\$\{[^}]+\}$")


def eval_when(when_expr: str, context: dict) -> bool:
    """求值 when 条件表达式（MVP-1.5）。

    四种受批准形式：
      - ``${bind} == null``   bind 求值为 None/键缺失 → True
      - ``${bind} != null``   bind 求值非空 → True
      - ``${bind} == 'x'``    bind 等于字面量 → True
      - ``${bind}``           单 bind 真值判定

    其余形式（``>``、``&&`` 等）抛 :class:`ValueError`，由 verify 规则 11 前置拦截。

    键缺失语义：``eval_expr`` 对不存在的 step/bind 抛 :class:`ExprError`，
    本函数将其视为 None（即 ``== null`` 为真、``!= null`` 为假、单 bind 为假、
    字面量比较按 ``None == '字面量'`` 判定）。这一语义对应 ``when`` 的典型用法——
    判断前置步骤尚未产出某 bind。

    Args:
        when_expr: when 表达式字符串
        context: 求值上下文（与 eval_expr 同构）

    Returns:
        布尔判定结果

    Raises:
        ValueError: 表达式非四种受批准形式之一
    """
    expr = when_expr.strip()
    # 抽出 ${...} 取值部分（四种形式都恰好含一个 ${...}）
    m = _re.search(r"\$\{[^}]+\}", expr)
    if m is None:
        raise ValueError("when 表达式须含 ${...} 取值：" + repr(when_expr))
    try:
        val = eval_expr(parse(m.group(0)), context)
    except ExprError:
        # 键缺失（step/bind 不存在）视为 None——when 语义即"该 bind 是否已产出"
        val = None

    if _WHEN_SINGLE.match(expr):
        return bool(val)
    if _WHEN_EQ_NULL.match(expr):
        return val is None
    if _WHEN_NE_NULL.match(expr):
        return val is not None
    lit = _WHEN_EQ_LIT.match(expr)
    if lit:
        return val == lit.group(1)
    raise ValueError(
        "when 表达式非受批准形式（仅支持 == null / != null / == '字面量' / 单 bind）："
        + repr(when_expr)
    )
