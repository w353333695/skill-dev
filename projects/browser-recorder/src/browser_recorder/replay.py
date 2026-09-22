"""replay：session.jsonl → flow.json 转换器（按稳定性排序的候选链推导）。

候选链（稳定性降序）：稳定 id > 测试锚点 data-* > name/aria-label > 文本 >
语义 class；dom_path 不进候选链——它是唯一原料时判 fragile（默认剔除并进
报告，keep_fragile=True 保留在 steps 并附 fragile:true）。

open 步合成：drive 的 open 步与真人录制的起点导航都只落 nav 事件（无
action），转换时从「首个动作前同 tab 的最后一次主 frame 导航」合成 open
步——否则重放 flow 缺起点导航，首步 locate 落在 about:blank 上必 miss。

credential 闭环（对接 flow._is_credential）：password 值（录制侧已脱敏为
***，或 html_type=password）→ ${env.BR_PW_<n>} 占位 + needs_credential:true
——BR_PW 变量名含 "pw" 信号词，flow 层脱敏判据可识别；重放时明文经
--var 注入，不落盘。
"""
from __future__ import annotations

import json
import re

# 数字后缀 = 自动生成 id（rc_select_20 / dynamicForm_0_name）。语义 id
# （name/btn-ok）不含 "_数字" 段。注意不能锚尾（r"_\d+$"）——
# dynamicForm_0_name 的数字段在中段，锚尾会漏判成稳定。
_AUTO_ID_RE = re.compile(r"_\d+")
# css-in-js 生成器指纹：框架前缀词，或「纯字母数字 ≥6 且含数字」（1q2w3e
# 型）。不含数字的语义词（submit/button/primary）不误杀。前缀按词边界
# 匹配——class 以 marker 开头才算：子串包含会把 desc-header/disc-list/
# misc-info 这类含 "sc-" 子串的语义 class 误杀。
_HASH_CLASS_RE = re.compile(r"[a-z0-9]{6,}", re.I)
_CLASS_MARKERS = ("css-", "emotion", "styled", "sc-", "jss", "mui-")
# 纯符号/数字文本不作为文本候选（无区分度）。Python3 \w 默认含 CJK，
# 中文文本是 word 字符不会被跳过。
_TEXT_SKIP = re.compile(r"^[\s\d\W]*$")
# 与 flow.load_flow 的 act 枚举一致——session 侧未知动作类型兜底为 click
_ACTS = ("open", "click", "input", "submit", "hover")


def is_stable_id(id_str: str | None) -> bool:
    """纯数字后缀的自动生成 id（rc_select_20 型）判不稳定。"""
    if not id_str:
        return False
    return not _AUTO_ID_RE.search(id_str)


def _attr_sel(key: str, value) -> str:
    """属性选择器片段；值非标识符形态（含空格/引号/CJK 外符号）转 CSS 字符串。"""
    v = str(value)
    if re.fullmatch(r"[\w-]+", v):
        return f"[{key}={v}]"
    return f"[{key}={json.dumps(v, ensure_ascii=False)}]"


def _stable_classes(classes) -> list[str]:
    """剔除生成器指纹 class，保留全部语义 class（class 链是末位候选，
    全保留提高兜底定位精度；截断会丢语义 class——Task 10 审查 I-1）。"""
    out = []
    for c in classes or []:
        cs = str(c)
        if any(cs.lower().startswith(m) for m in _CLASS_MARKERS):
            continue
        if _HASH_CLASS_RE.fullmatch(cs) and any(ch.isdigit() for ch in cs):
            continue
        out.append(cs)
    return out


def _candidates(desc: dict, is_click_like: bool) -> list[str]:
    """候选链（稳定性降序）：id > 测试锚点 > name/aria > 文本 > 语义class。

    name 对输入类动作优先于文本（表单语义）；点击类动作文本优先、name 垫后
    （同名 radio/按钮组的 name 无区分度）。dom_path 兜底不在此——由调用方
    按 fragile 语义单独处理。desc 缺新字段（旧 session）时全部安全缺省。
    """
    locs: list[str] = []
    raw_id = desc.get("id")
    # id 含选择器元字符（. / : 等）时 css:# 转义复杂，直接放弃 id 候选
    if raw_id and is_stable_id(raw_id) and re.fullmatch(r"[\w-]+", raw_id):
        locs.append(f"css:#{raw_id}")
    for k, v in (desc.get("data_attrs") or {}).items():
        locs.append("css:" + _attr_sel(k, v))
    if desc.get("name") and not is_click_like:
        locs.append("css:" + _attr_sel("name", desc["name"]))
    if desc.get("aria_label"):
        locs.append("css:" + _attr_sel("aria-label", desc["aria_label"]))
    text = str(desc.get("text") or "").strip()
    if text and not _TEXT_SKIP.match(text):
        locs.append(f"text:{text}")
    if is_click_like and desc.get("name"):
        locs.append("css:" + _attr_sel("name", desc["name"]))
    sc = _stable_classes(desc.get("classes"))
    if sc:
        locs.append("css:" + str(desc.get("tag") or "*")
                    + "".join("." + c for c in sc))
    return locs


def _dedup(seq: list[str]) -> list[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _trim_action(a: dict, desc: dict) -> dict:
    """removed 条目里的动作摘要（报告用，不塞整包事件）。"""
    return {"seq": a.get("seq"), "type": a.get("type"),
            "text": str(desc.get("text") or "")[:40]}


def session_to_flow(lines: list[dict], name: str | None = None,
                    keep_fragile: bool = False) -> tuple[dict, list[dict]]:
    """action 事件流 → (flow, removed)。

    removed = 被剔除的步 [{n, reason, action}]；keep_fragile=True 时
    dom-path-only 步保留在 steps（loc 就是 dom: 候选，附 fragile:true），
    但仍进 removed 供报告列出。只读 kind=="action" 的事件（drive_step /
    nav / request 等忽略）；drive 产生的 action 带 source:"drive"，与人工
    录制同等转换（不区分 source）。n 为全序步号（含被剔除的步，剔除后
    steps 的 n 不再连续——load_flow 不要求连续，报告可对回原 seq）。
    """
    events = [l for l in lines if isinstance(l, dict)]
    actions = sorted((l for l in events if l.get("kind") == "action"),
                     key=lambda l: (l.get("t_mono", 0), l.get("seq", 0)))
    navs = [l for l in events if l.get("kind") == "nav"]
    steps: list[dict] = []
    removed: list[dict] = []
    new_tab_tids: set[str] = set()

    # ---- open 步合成（见模块 docstring）----
    if actions:
        tid0 = actions[0].get("target_id") or "t0"
        pre = [nv for nv in navs
               if (nv.get("target_id") or "t0") == tid0
               and nv.get("t_mono", 0) < actions[0].get("t_mono", 0)
               and nv.get("url") and nv["url"] != "about:blank"]
        if pre:
            url = max(pre, key=lambda nv: nv.get("t_mono", 0))["url"]
            steps.append({"n": 1, "desc": f"打开 {url}"[:60], "act": "open",
                          "value": url,
                          "tabs": "main" if tid0 == "t0" else tid0})

    n = len(steps)  # open 合成时为 1，否则 0——动作步号顺延
    for i, a in enumerate(actions):
        n += 1
        desc = ((a.get("element") or {}).get("descriptor")) or {}
        act = a.get("type") if a.get("type") in _ACTS else "click"
        is_click_like = act in ("click", "submit")
        locs = _dedup(_candidates(desc, is_click_like))
        fragile = False
        if not locs:
            if desc.get("dom_path"):
                locs = [f"dom:{desc['dom_path']}"]
                fragile = True
            else:
                removed.append({"n": n, "reason": "no-descriptor",
                                "action": _trim_action(a, desc)})
                continue
        step = {"n": n, "desc": str(desc.get("text") or act)[:30] or act,
                "act": act, "loc": locs}
        v = a.get("value")
        if v is not None or act == "input":  # input 步必须有 value（schema）
            if (a.get("html_type") or "").lower() == "password" or v == "***":
                step["value"] = f"${{env.BR_PW_{n}}}"
                step["needs_credential"] = True
            else:
                step["value"] = "" if v is None else v
            if a.get("html_type"):
                step["html_type"] = a["html_type"]
        tid = a.get("target_id") or "t0"
        if tid != "t0" and tid not in new_tab_tids:
            # 首个落在新 tab 的动作：给上一步（开 tab 的动作）挂 on_new_tab
            new_tab_tids.add(tid)
            if steps:
                steps[-1]["on_new_tab"] = "switch"
        step["tabs"] = tid if tid != "t0" else "main"
        # wait 推导：本动作与下一动作之间有同 tab 的 nav → 本步 wait:nav
        next_t = (actions[i + 1].get("t_mono", float("inf"))
                  if i + 1 < len(actions) else float("inf"))
        if any((nv.get("target_id") or "t0") == tid
               and a.get("t_mono", 0) < nv.get("t_mono", 0) < next_t
               for nv in navs):
            step["wait"] = "nav"
        if fragile:
            step["fragile"] = True
            removed.append({"n": n, "reason": "dom-path-only",
                            "action": _trim_action(a, desc)})
            if keep_fragile:
                steps.append(step)
            continue
        steps.append(step)

    flow = {"name": name or "replayed-flow",
            "meta": {"generated_by": "replay", "actions": len(actions),
                     "removed": len(removed), "keep_fragile": keep_fragile},
            "steps": steps}
    return flow, removed
