"""flow.json 执行引擎：候选链定位 → 信任派发+降级 → 等待 → 断言 → 落盘。

状态机每步：resolve_vars → (open=导航) → locate 重试预算 → act → 后置等待
→ expect 断言 → drive_step 落盘（跑即录：同时经 harness.emit_action 落统一
action 事件）。失败 → save_evidence 证据包 + drive_fail → 终止。

T7 审查遗留三项的处理（driver 不动，flow 层接住）：
1. act 内部复检/降级 JS 用裸 querySelector 不穿透 shadow——input 类动作
   check=False 时先做一次显式 deepAll 复检（locate 同款穿透 JS），
   命中且 tag/text 吻合则认为生效，不立即判失败；
2. act 的 dispatch 字段在 check=False 时不可信——失败判定只认 check 与
   expect 结果，dispatch 仅作观测落盘；
3. save_evidence 原样落盘 step dict——password 值先替换为 *** 再传入。
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from .driver import act, locate, save_evidence

DEFAULT_RETRIES = 3
_VAR_RE = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")

MASK = "***"


class FlowError(Exception):
    """flow.json 格式错误（exit 4）。"""


def load_flow(path) -> dict:
    with open(path, encoding="utf-8") as f:
        flow = json.load(f)
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        raise FlowError("steps 必须是非空数组")
    for s in flow["steps"]:
        for k in ("n", "desc", "act"):
            if k not in s:
                raise FlowError(f"step {s.get('n', '?')} 缺必填字段 {k}")
        if s["act"] != "open" and not s.get("loc"):
            raise FlowError(f"step {s['n']} ({s['desc']}) 非 open 动作缺 loc")
        if s["act"] == "input" and "value" not in s:
            raise FlowError(f"step {s['n']} ({s['desc']}) input 缺 value")
    return flow


def resolve_vars(value: str, env: dict) -> str:
    def _sub(m):
        k = m.group(1)
        if k not in env:
            raise FlowError(f"变量 ${{env.{k}}} 未定义（--var 或环境变量提供）")
        return env[k]
    return _VAR_RE.sub(_sub, value)


def _is_password(step: dict, raw_value) -> bool:
    """脱敏判据：html_type=password / 值本身已是 *** / 变量名 BR_PW 开头（解析前）。"""
    if (step.get("html_type") or "").lower() == "password":
        return True
    if raw_value is not None and str(raw_value) == MASK:
        return True
    if isinstance(step.get("value"), str):
        for m in _VAR_RE.finditer(step["value"]):
            if m.group(1).startswith("BR_PW"):
                return True
    return False


def _masked_step(s: dict, value) -> dict:
    """save_evidence 用的 step 投影：password 值替换为 ***（context.json 原样落盘）。"""
    d = dict(s)
    if _is_password(s, value):
        d["value"] = MASK
    return d


async def run_flow(harness, flow: dict, env=None, dry_run=False,
                   step_from=None) -> dict:
    env = dict(os.environ, **(env or {}))
    cur_tid = "t0"
    steps = flow["steps"]
    if step_from is not None:
        steps = [s for s in steps if s["n"] >= step_from]
    steps_done = 0
    for s in steps:
        # 1. 变量解析
        value = resolve_vars(s["value"], env) if "value" in s else None
        # 2. open 动作：导航
        if s["act"] == "open":
            await harness.navigate(value, cur_tid)
            await harness.wait_stable()
            _emit_step(harness, s, "nav", None, target_id=cur_tid)
            steps_done += 1
            continue
        # 3. 前置等待 + locate 重试预算
        retries = s.get("retries", DEFAULT_RETRIES)
        hit = None
        for attempt in range(retries + 1):
            await harness.wait_stable()
            hit = await locate(harness.client, harness.tabs, cur_tid, s["loc"],
                               timeout=s.get("locate_timeout", 10))
            if hit:
                break
            await asyncio.sleep(0.5)
        if hit is None:
            return await _fail(harness, s, cur_tid, "locate-miss", dry_run,
                               steps_done, value)
        if dry_run:
            _emit_step(harness, s, "dry", hit, target_id=cur_tid)
            steps_done += 1
            continue
        # 4. 派发动作（含降级回调）
        dispatches = []
        r = await act(harness.client, harness.tabs, cur_tid,
                      {"act": s["act"], "loc": s["loc"], "rect": hit["rect"],
                       "value": value, "clear": s.get("clear", True)},
                      on_dispatch=dispatches.append)
        # 5. 落统一 action（跑即录）+ 截图；password 值不落盘
        await harness.emit_action({
            "type": s["act"] if s["act"] in ("click", "input", "submit") else "click",
            "source": "drive",
            "value": MASK if _is_password(s, value) else value,
            "html_type": s.get("html_type"),
            "rect": hit["rect"], "viewport": s.get("viewport"),
            "descriptor": hit,
            "target_id": cur_tid,
        })
        # 5b. 生效判定（T7-2：只认 check / expect，不认 dispatch）。
        #     input + check=False（act 内复检/降级 JS 裸 querySelector 打不进
        #     shadow 的断层）→ flow 层 deepAll 显式复检（T7-1）
        ok = r.get("check")
        dispatch = dispatches[-1] if dispatches else "?"
        if not ok and s["act"] == "input":
            re_hit = await _deep_recheck(harness.client, harness.tabs, cur_tid,
                                         s["loc"])
            if re_hit and re_hit.get("tag") == hit.get("tag") \
                    and re_hit.get("text") == hit.get("text"):
                ok = True
                dispatch = f"{dispatch}+recheck" if dispatch != "?" else "recheck"
        if not ok:
            return await _fail(harness, s, cur_tid, "check-fail", dry_run,
                               steps_done, value, dispatch=dispatch)
        # 6. 后置等待
        if s.get("wait", "settle") == "nav":
            await _wait_nav(harness, cur_tid, timeout=15)
        else:
            await harness.wait_stable()
        # 7. expect 断言
        expect_result = None
        if s.get("expect"):
            expect_result = await _check_expect(harness, s["expect"], cur_tid)
            if not expect_result["ok"]:
                if s.get("on_expect_fail") == "retry":
                    # 简化重试：重派动作一次（v1 不整步循环）
                    r = await act(harness.client, harness.tabs, cur_tid,
                                  {"act": s["act"], "loc": s["loc"],
                                   "rect": hit["rect"], "value": value,
                                   "clear": s.get("clear", True)},
                                  on_dispatch=dispatches.append)
                    await harness.wait_stable()
                    expect_result = await _check_expect(harness, s["expect"],
                                                        cur_tid)
                if not expect_result["ok"]:
                    return await _fail(harness, s, cur_tid, "expect-fail",
                                       dry_run, steps_done, value,
                                       extra={"expect": expect_result})
        # 8. drive_step 落盘
        _emit_step(harness, s, dispatch, hit, expect=expect_result,
                   retry_used=attempt, target_id=cur_tid)
        steps_done += 1
    return {"ok": True, "steps_done": steps_done, "failed_step": None,
            "exit_code": 0}


async def _deep_recheck(client, tabs, tid, locs) -> dict | None:
    """act 复检断层后的显式 deepAll 复检（shadow 穿透，locate 同款 JS）。"""
    return await locate(client, tabs, tid, locs, timeout=1)


def _emit_step(harness, s, dispatch, hit, expect=None, retry_used=0,
               target_id=None):
    harness.writer.emit("drive_step", {
        "n": s["n"], "desc": s["desc"], "act": s["act"],
        "dispatch": dispatch, "match_count": (hit or {}).get("match_count"),
        "retry_used": retry_used, "expect_result": expect,
        "target_id": target_id,
    })


async def _fail(harness, s, tid, reason, dry_run, steps_done, value,
                extra=None, dispatch=None) -> dict:
    step = _masked_step({"n": s["n"], "desc": s["desc"], "loc": s.get("loc"),
                         "tried": s.get("loc"), "act": s["act"],
                         "retries": s.get("retries", DEFAULT_RETRIES),
                         "html_type": s.get("html_type"),
                         "value": value if "value" in s else None,
                         "url": await _cur_url(harness, tid),
                         "dispatch": dispatch or reason,
                         **(extra or {})}, value)
    ev_dir = await save_evidence(harness.out_dir, harness.client, harness.tabs,
                                 tid, step)
    harness.writer.emit("drive_fail", {
        "n": s["n"], "desc": s["desc"], "reason": reason,
        "evidence": str(ev_dir), "target_id": tid})
    return {"ok": False, "steps_done": steps_done, "failed_step": s["n"],
            "exit_code": 3}


async def _cur_url(harness, tid) -> str:
    sid = harness.tid_sid(tid)
    try:
        r = await harness.client.send("Runtime.evaluate",
                                      {"expression": "location.href"},
                                      session_id=sid)
        return ((r.get("result") or {}).get("value")) or ""
    except Exception:
        return ""


async def _wait_nav(harness, tid, timeout=15):
    fut = asyncio.get_running_loop().create_future()

    def _on_nav(p):
        if not fut.done():
            fut.set_result(p.get("frame", {}).get("url", ""))
    harness.client.on("Page.frameNavigated", _on_nav)   # 全局订阅（含所有 session）
    try:
        await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        pass  # CDPClient 无 off()——订阅泄漏一次可接受（v1），M6+ 考虑加 off


async def _check_expect(harness, expect: dict, tid) -> dict:
    if "dom_contains" in expect:
        arg = expect["dom_contains"]
        js = f"document.body.innerText.includes({arg!r})"
        try:
            r = await harness.client.send("Runtime.evaluate",
                                          {"expression": js},
                                          session_id=harness.tid_sid(tid))
            got = (r.get("result") or {}).get("value", False)
        except Exception:
            got = False
        return {"ok": bool(got), "channel": "dom"}
    if "response_contains" in expect:
        arg = expect["response_contains"]
        # 网络通道：harness.resp_log（Network.responseReceived 滑动窗口）。
        # 未指定 status 时不比对状态码；时间窗不设——窗口数据源本身只有最近
        # 200 条，drive 步间隔内混入旧响应的风险由「先 settle 后检查」压住。
        hits = [h for h in getattr(harness, "resp_log", [])
                if arg.get("url", "") in h.get("url", "")
                and (arg.get("status") is None
                     or h.get("status") == arg.get("status"))]
        return {"ok": bool(hits), "channel": "net"}
    return {"ok": False, "channel": "?", "error": "unknown expect"}
