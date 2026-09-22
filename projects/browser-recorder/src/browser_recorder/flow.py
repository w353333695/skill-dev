"""flow.json 执行引擎：候选链定位 → 信任派发+降级 → 等待 → 断言 → 落盘。

状态机每步：resolve_vars → tab 选择 → (open=导航) → locate 重试预算 → act
→ 后置等待 → expect 断言 → drive_step 落盘（跑即录：同时经 harness.emit_action
落统一 action 事件）。失败 → save_evidence 证据包 + drive_fail → 终止。

T7 审查遗留三项的处理（driver 不动，flow 层接住）：
1. act 内部复检/降级 JS 用裸 querySelector 不穿透 shadow——input 类动作
   check=False 时先做一次显式 deepAll 值复检（locate 同款穿透 JS 读
   el.value），值与预期相等才认为生效，不立即判失败；
2. act 的 dispatch 字段在 check=False 时不可信——失败判定只认 check 与
   expect 结果，dispatch 仅作观测落盘；
3. save_evidence 原样落盘 step dict——credential 步的 value 先替换为 ***
   再传入（_is_credential 在 resolve 前对原始模板判定，强判据）。

T9 多 tab：cur_tid 不再恒 "t0"——
- step.tabs 显式指定优先："main"=t0 / "new"=最新出现的 tab / 形如 "t1" 直给；
- step.on_new_tab="switch"：动作后 harness.tabs 出现动作前没有的新 tid
  （harness.autoAttach 已挂域）→ 后续步默认切到该 tid；
- 无 on_new_tab 声明时不动（旧 flow 行为与 T8 完全一致）。
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from .driver import act, locate, save_evidence, value_of_js

DEFAULT_RETRIES = 3
_VAR_RE = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")
_ACTS = ("open", "click", "input", "submit", "hover")

# credential 信号词（不区分大小写）——模板变量名任一命中即整值脱敏。
# BR_PW 前缀是其子集（含 "PW"），不再单列。
_CRED_RE = re.compile(r"(?i)pw|password|secret|token")

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
        if s["act"] not in _ACTS:
            raise FlowError(f"step {s['n']} ({s['desc']}) 未知 act: {s['act']!r}"
                            f"（可选：{'/'.join(_ACTS)}）")
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


def _is_credential(step: dict) -> bool:
    """脱敏强判据——必须在 resolve 前对原始 step 判定（resolve 后模板已消失）。

    判据（任一命中）：
    1. step.html_type == "password"（录制侧联动字段；schema v1 可选）；
    2. 原始模板 value 里任一 ${env.XXX} 变量名含 credential 信号词
       （pw/password/secret/token，不区分大小写）——值本身不看了（明文
       值无判据可循，变量名是唯一的稳定信号）；
    3. 原始 value 整值已是 ***（上游已脱敏的透传）。
    """
    if (step.get("html_type") or "").lower() == "password":
        return True
    raw = step.get("value")
    if isinstance(raw, str):
        if raw == MASK:
            return True
        for m in _VAR_RE.finditer(raw):
            if _CRED_RE.search(m.group(1)):
                return True
    return False


def _tab_tids(harness) -> list[str]:
    """harness.tabs 当前全部 tid（{sid: _TabSession}，_TabSession 带 .tid）。"""
    return [t.tid for t in harness.tabs.values()]


def _newest_tid(harness, known: set[str]) -> str | None:
    """known（动作前快照）之外最新出现的 tid；无新 tab 返回 None。

    tid 形如 "t0"/"t1"…（_attach_tab 按挂载序编号），数值最大即最新。
    """
    fresh = [t for t in _tab_tids(harness) if t not in known]
    if not fresh:
        return None
    def _num(t):
        try:
            return int(t[1:])
        except ValueError:
            return -1
    return max(fresh, key=_num)


def _resolve_tab(harness, spec, cur_tid) -> str:
    """step.tabs → 实际 tid。"main"=t0；"new"=当前最新 tab；"t1" 直给。

    "new" 找不到比 cur 更新的 tab 时（尚未弹出/已关闭）退 cur——元素
    「预期在最新 tab」但新 tab 未及挂载，locate 重试预算会兜住时序。
    """
    if not spec or spec == "main":
        return "t0" if any(t == "t0" for t in _tab_tids(harness)) else cur_tid
    if spec == "new":
        known = {cur_tid, "t0"}
        newest = _newest_tid(harness, known)
        return newest or cur_tid
    return spec  # 显式 tid（"t1"…）——不存在时后续 locate/send 自然失败


async def run_flow(harness, flow: dict, env=None, dry_run=False,
                   step_from=None) -> dict:
    env = dict(os.environ, **(env or {}))
    cur_tid = "t0"
    steps = flow["steps"]
    if step_from is not None:
        steps = [s for s in steps if s["n"] >= step_from]
    steps_done = 0
    for s in steps:
        # 0. tab 选择：step.tabs 显式指定优先（main/new/tid）。
        #    step_tid 钉住本步执行 tab——中途 on_new_tab 切换只改 cur_tid
        #    影响后续步，本步 action/drive_step/证据包的 target_id 不漂移
        if s.get("tabs"):
            cur_tid = _resolve_tab(harness, s["tabs"], cur_tid)
        step_tid = cur_tid
        # 1. 脱敏判定（resolve 前——模板变量名是唯一稳定信号）+ 变量解析
        cred = _is_credential(s)
        value = resolve_vars(s["value"], env) if "value" in s else None
        # 2. open 动作：导航
        if s["act"] == "open":
            await harness.navigate(value, step_tid)
            await harness.wait_stable()
            _emit_step(harness, s, "nav", None, target_id=step_tid)
            steps_done += 1
            continue
        # 3. 前置等待 + locate 重试预算
        retries = s.get("retries", DEFAULT_RETRIES)
        hit = None
        for attempt in range(retries + 1):
            await harness.wait_stable()
            hit = await locate(harness.client, harness.tabs, step_tid, s["loc"],
                               timeout=s.get("locate_timeout", 10))
            if hit:
                break
            await asyncio.sleep(0.5)
        if hit is None:
            return await _fail(harness, s, step_tid, "locate-miss", dry_run,
                               steps_done, value, cred=cred)
        if dry_run:
            _emit_step(harness, s, "dry", hit, target_id=step_tid)
            steps_done += 1
            continue
        # 4. 派发动作（含降级回调）。on_new_tab=switch：动作后对比 tabs 快照，
        #    出现新 tid（autoAttach 已挂域）→ 后续步默认切到新 tab。
        #    attach 是异步的（target 弹出 → attachedToTarget → 挂域），短窗
        #    轮询兜住时序（真机实测 attach 通常 <1s，5s 上限）
        tabs_before = set(_tab_tids(harness))
        dispatches = []
        r = await act(harness.client, harness.tabs, step_tid,
                      {"act": s["act"], "loc": s["loc"], "rect": hit["rect"],
                       "value": value, "clear": s.get("clear", True)},
                      on_dispatch=dispatches.append)
        if s.get("on_new_tab") == "switch":
            deadline = asyncio.get_running_loop().time() + 5.0
            newest = _newest_tid(harness, tabs_before)
            while newest is None and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.2)
                newest = _newest_tid(harness, tabs_before)
            if newest and newest != step_tid:
                cur_tid = newest
        # 5. 落统一 action（跑即录）+ 截图；credential 步值恒 ***（强判据，
        #    resolve 前对原始模板判定，emit_action 侧不再自判）
        await harness.emit_action({
            "type": s["act"] if s["act"] in ("click", "input", "submit") else "click",
            "source": "drive",
            "value": MASK if cred else value,
            "html_type": s.get("html_type"),
            "rect": hit["rect"], "viewport": s.get("viewport"),
            "descriptor": hit,
            "target_id": step_tid,
        })
        # 5b. 生效判定（T7-2：只认 check / expect，不认 dispatch）。
        #     input + check=False（act 内复检/降级 JS 裸 querySelector 打不进
        #     shadow 的断层）→ flow 层 deepAll 读 el.value 真值比对（T7-1）：
        #     穿透读到的值 == 预期值才算复检通过，不等则走失败协议
        ok = r.get("check")
        dispatch = dispatches[-1] if dispatches else "?"
        if not ok and s["act"] == "input":
            got = await _deep_recheck_value(harness.client, harness.tabs,
                                            step_tid, s["loc"])
            if got is not None and got == (value or ""):
                ok = True
                dispatch = f"{dispatch}+recheck" if dispatch != "?" else "recheck"
        if not ok:
            return await _fail(harness, s, step_tid, "check-fail", dry_run,
                               steps_done, value, cred=cred, dispatch=dispatch)
        # 6. 后置等待
        if s.get("wait", "settle") == "nav":
            await _wait_nav(harness, step_tid, timeout=15)
        else:
            await harness.wait_stable()
        # 7. expect 断言
        expect_result = None
        if s.get("expect"):
            expect_result = await _check_expect(harness, s["expect"], step_tid)
            if not expect_result["ok"]:
                if s.get("on_expect_fail") == "retry":
                    # 简化重试：重派动作一次（v1 不整步循环）
                    r = await act(harness.client, harness.tabs, step_tid,
                                  {"act": s["act"], "loc": s["loc"],
                                   "rect": hit["rect"], "value": value,
                                   "clear": s.get("clear", True)},
                                  on_dispatch=dispatches.append)
                    await harness.wait_stable()
                    expect_result = await _check_expect(harness, s["expect"],
                                                        step_tid)
                if not expect_result["ok"]:
                    return await _fail(harness, s, step_tid, "expect-fail",
                                       dry_run, steps_done, value, cred=cred,
                                       extra={"expect": expect_result})
        # 8. drive_step 落盘
        _emit_step(harness, s, dispatch, hit, expect=expect_result,
                   retry_used=attempt, target_id=step_tid)
        steps_done += 1
    return {"ok": True, "steps_done": steps_done, "failed_step": None,
            "exit_code": 0}


async def _deep_recheck_value(client, tabs, tid, locs) -> str | None:
    """act 复检断层后的显式 deepAll 值复检（shadow 穿透读 el.value）。

    解析 value_of_js 的返回（JSON [v, true] / [null] / [null, false]）：
    返回穿透读到的元素当前值（input/textarea 之外的元素为 ''）；候选全
    miss / evaluate 失败返回 None（与「读到空串」区分——None 表示复检
    本身不可用，交由调用方按不通过处理）。
    """
    sid = None
    for tab in tabs.values():
        if tab.tid == tid:
            sid = getattr(tab, "sid", None)
            break
    try:
        r = await client.send("Runtime.evaluate",
                              {"expression": value_of_js(locs),
                               "awaitPromise": True, "returnByValue": True},
                              session_id=sid)
    except Exception:
        return None
    raw = (r.get("result") or {}).get("value")
    if not isinstance(raw, str):
        return None
    try:
        arr = json.loads(raw)
        v = arr[0] if isinstance(arr, list) and arr else None
    except ValueError:
        return None
    return None if v is None else str(v)


def _emit_step(harness, s, dispatch, hit, expect=None, retry_used=0,
               target_id=None):
    harness.writer.emit("drive_step", {
        "n": s["n"], "desc": s["desc"], "act": s["act"],
        "dispatch": dispatch, "match_count": (hit or {}).get("match_count"),
        "retry_used": retry_used, "expect_result": expect,
        "target_id": target_id,
    })


async def _fail(harness, s, tid, reason, dry_run, steps_done, value,
                cred=False, extra=None, dispatch=None) -> dict:
    # credential 步：value 一律 ***（context.json 经 save_evidence 原样落盘，
    # drive_fail 事件同理）——cred 在 resolve 前对原始模板判定（强判据）
    v = MASK if cred else (value if "value" in s else None)
    step = {"n": s["n"], "desc": s["desc"], "loc": s.get("loc"),
            "tried": s.get("loc"), "act": s["act"],
            "retries": s.get("retries", DEFAULT_RETRIES),
            "html_type": s.get("html_type"),
            "value": v,
            "url": await _cur_url(harness, tid),
            "dispatch": dispatch or reason,
            **(extra or {})}
    ev_dir = await save_evidence(harness.out_dir, harness.client, harness.tabs,
                                 tid, step)
    harness.writer.emit("drive_fail", {
        "n": s["n"], "desc": s["desc"], "reason": reason,
        "value": MASK if cred else (value if "value" in s else None),
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
