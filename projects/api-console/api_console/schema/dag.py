"""DAG 数据模型 + JSONPath 子集（手写，严格白名单）。

- DAG/Step/StepOutput/StepAssert dataclass：spec 第 7 章契约。
- :func:`extract_jsonpath` 只支持 ``$.xxx.yyy`` 与 ``[n]`` 索引，**不支持** ``[*]``
  （抛 KeyError 引导用 outputs 锚点 + 表达式投影，避免 LLM 滥用通配）。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import re


# ---------- dataclass ----------

@dataclass
class StepOutput:
    """步骤输出绑定。

    Attributes:
        bind: 上下文中的变量名（后续步骤可 ``${step.bind}`` 引用）
        anchor: 卡片 outputs 中的锚点名（spec 5.1）
    """
    bind: str
    anchor: str


@dataclass
class StepAssert:
    """步骤断言（失败则终止 DAG，回传错误给 LLM）。"""
    condition: str
    message: str


@dataclass
class Step:
    """DAG 中的一步。

    Attributes:
        id: 步骤唯一 id（其他步骤 depends/表达式引用）
        card: 卡片名（registry 内）
        params: 参数字典；值可以是字面量或 ``${...}`` 表达式
        depends: 依赖的 step id 列表
        foreach: ``${...}`` 表达式；提供则对结果数组逐项执行（``${item}`` 取当前元素）
        output: 输出绑定；None 表示不绑定（如纯写操作）
        asserts: 断言列表（求值失败抛 ExecutionError）
        when: MVP-1.5：条件为真才执行（空串=无条件）；为假跳过该步
    """
    id: str
    card: str
    params: dict = field(default_factory=dict)
    depends: list = field(default_factory=list)
    foreach: str | None = None
    output: StepOutput | None = None
    asserts: list = field(default_factory=list)
    when: str = ""  # MVP-1.5：条件为真才执行（空串=无条件）；为假跳过该步

    @classmethod
    def from_dict(cls, sd: dict) -> "Step":
        """从字典（LLM 生成的 yaml 中的单步）构造 Step。

        Args:
            sd: 单步字典，含 id/card/params/depends/foreach/output/assert/when

        Returns:
            构造好的 :class:`Step`
        """
        out_d = sd.get("output")
        output = None
        if out_d:
            output = StepOutput(
                bind=out_d["bind"],
                anchor=out_d.get("from") or out_d.get("anchor"),
            )
        # assert 在 yaml 中是 dict（condition -> message），转成 list[StepAssert]
        asserts = []
        raw_assert = sd.get("assert")
        if isinstance(raw_assert, dict):
            for cond, msg in raw_assert.items():
                asserts.append(StepAssert(condition=cond, message=msg))
        elif isinstance(raw_assert, list):
            for a in raw_assert:
                if isinstance(a, dict):
                    for cond, msg in a.items():
                        asserts.append(StepAssert(condition=cond, message=msg))
                elif isinstance(a, StepAssert):
                    asserts.append(a)
        return cls(
            id=sd["id"], card=sd["card"],
            params=sd.get("params", {}) or {},
            depends=sd.get("depends", []) or [],
            foreach=sd.get("foreach"),
            output=output,
            asserts=asserts,
            when=sd.get("when", ""),
        )


@dataclass
class DAG:
    """编排图：steps 拓扑序 + result 表达式。"""
    goal: str
    steps: list
    result: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "DAG":
        """从字典（LLM 生成的 yaml）构造。字段对齐 spec 7.1。"""
        steps = [Step.from_dict(sd) for sd in d.get("steps", [])]
        return cls(
            goal=d.get("goal", ""),
            steps=steps,
            result=d.get("result", ""),
        )

    def step_map(self) -> dict:
        """id -> Step。"""
        return {s.id: s for s in self.steps}


# ---------- JSONPath 子集 ----------

# 严格白名单：$.ident.ident[0].ident...；遇到 [*] 抛 KeyError
# 用 [$] [.] 规避反斜杠转义。
_SEG = re.compile(r"[$]\.?" + "|" + r"\.[a-zA-Z_]\w*" + "|" + r"\[\d+\]" + "|" + r"\[\*\]")


def extract_jsonpath(path: str, data: Any) -> Any:
    """极简 JSONPath：只支持 ``$.a.b[0].c``，不支持 ``[*]``。

    Args:
        path: JSONPath 字符串，必须 ``$.`` 开头
        data: 待取值的数据

    Raises:
        KeyError: 路径非法、缺失段、或含 ``[*]``（引导用 outputs 锚点 + DAG 投影）
    """
    if not isinstance(path, str) or not path.startswith("$."):
        raise KeyError("jsonpath 必须 $. 开头：" + repr(path))

    # [*] 不支持：引导用锚点
    if "[*]" in path:
        raise KeyError(
            "jsonpath 子集不支持 [*]，请改用 outputs 锚点 + ${step.bind.field} 投影：" + repr(path)
        )

    # 逐段切分。token 形如 .ident 或 [n]
    # 用 [$] [.] [[] 规避反斜杠转义
    token_re = re.compile(r"\.[a-zA-Z_]\w*" + "|" + r"\[\d+\]" + "|" + r"\[\*\]")
    # 第一段允许 ident 直接跟在 $. 后（即 $.ident 或 $[n]）
    first_re = re.compile(r"[a-zA-Z_]\w*" + "|" + r"\[\d+\]")

    cur = data
    # 去掉 "$." 前缀，剩下 .a.b[0].c 或 a.b（兼容 $[0] 形式略）
    rest = path[2:]
    pos = 0
    n = len(rest)
    if rest == "":
        return cur

    # 首段（紧跟 $. 后）
    m = first_re.match(rest, pos)
    if not m:
        # 第一个字符是 . 也允许（$.xxx 与 $xxx 等价）
        if rest[pos] != ".":
            raise KeyError("jsonpath 非法前缀：" + repr(path))
    else:
        key = m.group(0)
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError("jsonpath 缺失段 " + key + "：" + repr(path))
        cur = cur[key]
        pos = m.end()

    while pos < n:
        c = rest[pos]
        if c == ".":
            m = token_re.match(rest, pos)
            if not m or not m.group(0).startswith("."):
                raise KeyError("jsonpath 段非法 @ " + str(pos) + "：" + repr(path))
            key = m.group(0)[1:]  # 去掉前导 .
            if not isinstance(cur, dict) or key not in cur:
                raise KeyError("jsonpath 缺失段 " + key + "：" + repr(path))
            cur = cur[key]
            pos = m.end()
        elif c == "[":
            j = rest.find("]", pos)
            if j == -1:
                raise KeyError("jsonpath 下标未闭合：" + repr(path))
            inner = rest[pos + 1:j]
            if not inner.isdigit():
                raise KeyError("jsonpath 仅支持数字下标：" + repr(path))
            idx = int(inner)
            if not isinstance(cur, list) or idx >= len(cur):
                raise KeyError("jsonpath 下标越界或非数组：" + repr(path))
            cur = cur[idx]
            pos = j + 1
        else:
            raise KeyError("jsonpath 非法字符 " + repr(c) + "：" + repr(path))

    return cur
