"""path 归一化 + gateway 剥离 + 三级优先级（纯函数）。

spec 3.3：后端契约 colon style（:param）与前端 openapi brace style（{param}）
必须先归一化才能对齐。align_path 实现三级优先级：
后端契约 > gateway 剥离 > 前端原样。

注意：本模块所有正则刻意避开反斜杠字面量（用字符类替代 ``\\w``、用 ``re.escape``
处理字面量、用 lambda 避免 ``\\1`` 反向引用），规避 Write 工具翻倍反斜杠的坑。
"""
from __future__ import annotations
import re
from typing import Optional
from api_console.schema.contracts import BackendContract

# colon 参数识别：以 [a-zA-Z0-9_] 字符类替代 \w，规避反斜杠
_PARAM_IDENT = "([a-zA-Z_][a-zA-Z0-9_]*)"
_COLON_RE = re.compile(":" + _PARAM_IDENT)

# gateway 占位符 {service}：按字面量匹配的单段服务名（不含 /）
_SVC_PLACEHOLDER = "{service}"
_SVC_PATTERN = "([^/]+)"
_TAIL_GROUP = "(/.*)?$"


def normalize_path(raw: str) -> str:
    """把 colon style（:param）归一化为 brace style（{param}）。

    Args:
        raw: 原始路径，可能含 colon 参数 ``:name``。

    Returns:
        归一化后的路径，colon 参数被包进花括号。已是 brace style 的不变。
    """
    # 用 lambda 取 group(1)，避免 r"{\1}" 反向引用里出现反斜杠
    return _COLON_RE.sub(lambda m: "{" + m.group(1) + "}", raw)


def make_operation_key(service: str, method: str, normalized_uri: str) -> str:
    """构造 ``service|method|normalized_uri`` 三元组对齐键。"""
    return f"{service}|{method}|{normalized_uri}"


def strip_gateway(gateway_path: str, rules: dict) -> Optional[str]:
    """按 gateway-rules 依次剥离前缀。

    Args:
        gateway_path: 前端 openapi 里的完整 gateway 路径（如
            ``/next/api/gateway/logic.flowable_service/api/...``）。
        rules: gateway-rules.yaml 反序列化结果，含 ``strip_prefix`` 与
            ``service_map``。``strip_prefix`` 中可含 ``{service}`` 占位符，
            表示该段匹配单段服务名。

    Returns:
        剥离成功返回后端真实路径；若 rules 中所有前缀都没匹配（剥后路径与原值
        相同），返回 None。
    """
    p = gateway_path
    for prefix in rules.get("strip_prefix", []):
        if _SVC_PLACEHOLDER in prefix:
            # 把 prefix 拆成 {service} 前后两段字面量，分别 re.escape，
            # 中间用 ([^/]+) 匹配服务名，尾部 (.*)? 兜后端路径
            head, tail_literal = prefix.split(_SVC_PLACEHOLDER)
            pattern = (
                "^"
                + re.escape(head)
                + _SVC_PATTERN
                + re.escape(tail_literal)
                + _TAIL_GROUP
            )
            m = re.match(pattern, p)
            if m:
                p = m.group(2) or "/"
        else:
            if p.startswith(prefix):
                p = p[len(prefix):]
                if not p.startswith("/"):
                    p = "/" + p
    return p if p != gateway_path else None


# 已知 path 参数占位符的值形态（强先验，用于「具体值 vs 占位符」对齐）。
# 录制路径里 path 参数位置常是具体业务值（如 SOME_MODEL@VENDOR），后端契约同位置
# 是 {objectId} 占位符；仅靠「双边占位符才通配」会漏配。故对已知占位符名校验形态：
# 具体值符合该形态才通配（让 SOME_MODEL@VENDOR 配进 {objectId}），否则不通配
# （排除字面段误配，如 search_collect 不配进 {objectId}）。未登记形态的占位符名
# （如 {toolId}）只与占位符匹配，不通配具体值，避免错配字面段造成多义误命中。
_PARAM_SHAPE = {
    # objectId：CMDB 模型对象 ID，仅大写字母/下划线/@（如 SOME_MODEL@VENDOR、USER）
    "objectId": "^[A-Z_@]+$",
    # instanceId：实例 ID，13 位十六进制小写
    "instanceId": "^[0-9a-f]{13}$",
}
_PARAM_SHAPE_RE = {name: re.compile(pat) for name, pat in _PARAM_SHAPE.items()}


def _is_placeholder(seg: str) -> bool:
    """段是否为 ``{name}`` 占位符。"""
    return seg.startswith("{") and seg.endswith("}")


def _seg_value_matches(ph_name: str, concrete: str) -> bool:
    """占位符 ``{ph_name}`` 与对端具体值 ``concrete`` 是否通配。

    仅当占位符为已登记形态（objectId/instanceId）且具体值符合该形态时通配——
    这让「具体业务值 vs 已知占位符」（如 ``SOME_MODEL@VENDOR`` vs ``{objectId}``）
    能对齐，同时排除字面段误配（如 ``search_collect`` 不配进 ``{objectId}``）。

    未登记形态的占位符（如 ``{toolId}``）**不通配**具体值——占位符只与占位符
    匹配，避免 ``{toolId}`` 错配进字面段 ``batch``/``execution`` 造成多义误命中。
    """
    pat = _PARAM_SHAPE_RE.get(ph_name)
    if pat is None:
        return False  # 未知形态 → 不通配具体值（占位符只对占位符）
    return bool(pat.match(concrete))


def _paths_match_by_segment(a: str, b: str) -> bool:
    """逐段比对两条归一化路径。

    段匹配规则（任一满足即该段匹配）：
        1. 字面相等；
        2. 双方同为 ``{..}`` 占位符 → 按位置通配（不看参数名）；
        3. 一边占位符、一边具体值 → 仅已知形态占位符（objectId/instanceId）
           在具体值符合该形态时通配（让具体业务值对齐到占位符）；其余情况
           （未知占位符名，或形态不符）不通配，避免占位符错配字面段。

    colon style 在此处调用前已被 :func:`normalize_path` 归一化为 brace style。

    Args:
        a: 归一化后的路径 A。
        b: 归一化后的路径 B。

    Returns:
        段数相同且每段满足上述规则时返回 True；否则 False。
    """
    segs_a = a.split("/")
    segs_b = b.split("/")
    if len(segs_a) != len(segs_b):
        return False
    for sa, sb in zip(segs_a, segs_b):
        if sa == sb:
            continue
        a_ph, b_ph = _is_placeholder(sa), _is_placeholder(sb)
        if a_ph and b_ph:
            continue  # 双占位符：按位置通配，不看参数名
        if a_ph or b_ph:
            # 一边占位符一边具体值：按占位符名校验具体值形态
            ph_name = (sa[1:-1] if a_ph else sb[1:-1])
            concrete = sb if a_ph else sa
            if _seg_value_matches(ph_name, concrete):
                continue
            return False
        return False
    return True


def align_path(frontend_gateway_path: str, service: str, method: str,
               contracts: list[BackendContract], rules: dict
               ) -> tuple[str, str, str, str]:
    """三级优先级对齐前端 gateway_path 到后端真实 path。

    优先级：
        1A. **backend_contract（high）**：在 contracts 中按 service+method 找候选，
            再按 gateway 剥离后路径或后缀匹配命中后端契约 path。
        1B. **method+path 兜底（high）**：service 失配（如 RPC 名与 logic.* 不一致）
            时，仅按 method+path 唯一命中即可救回，matched_service 回填契约真实 service。
            多义（命中 ≥2）不猜，落入优先级 2。
        2. **gateway_strip（medium）**：没有匹配契约但 gateway 前缀可剥离。
        3. **frontend_raw（low）**：以上都失败，归一化后原样返回。

    Args:
        frontend_gateway_path: 前端 openapi 中的 gateway 路径。
        service: 目标后端 serviceName（可能为 RPC 名，与契约 logic.* 不一致）。
        method: HTTP 方法（大写）。
        contracts: 后端契约列表。
        rules: gateway-rules（含 ``strip_prefix``/``service_map``）。

    Returns:
        ``(path, path_source, path_confidence, matched_service)`` 四元组。source
        取值 ``backend_contract | gateway_strip | frontend_raw``；matched_service
        命中后端契约时为该契约的 service（logic.*），未命中为 ``""``。
    """
    norm = normalize_path(frontend_gateway_path)
    stripped = strip_gateway(frontend_gateway_path, rules)  # 提循环外，算一次
    norm_stripped = normalize_path(stripped) if stripped else None

    # 优先级 1A：service+method+path 精确（service 已对）
    for c in contracts:
        if c.service == service and c.method == method:
            if norm_stripped and _paths_match_by_segment(norm_stripped,
                                                          normalize_path(c.path)):
                return c.path, "backend_contract", "high", c.service
            if frontend_gateway_path.endswith(c.path):
                return c.path, "backend_contract", "high", c.service

    # 优先级 1B（兜底）：method+path 唯一命中（service 失配时救回）
    mp_hits = [c for c in contracts
               if c.method == method
               and _paths_match_by_segment(norm_stripped or norm,
                                            normalize_path(c.path))]
    if len(mp_hits) == 1:
        return mp_hits[0].path, "backend_contract", "high", mp_hits[0].service
    # mp_hits >= 2 多义：不猜，落入优先级 2（matched_service 留空）

    # 优先级 2：gateway 剥离
    if stripped:
        return normalize_path(stripped), "gateway_strip", "medium", ""

    # 优先级 3：前端原样（已归一化）
    return norm, "frontend_raw", "low", ""
