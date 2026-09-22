"""flow 引擎单测：加载校验/变量解析/执行状态机（mock harness）。

T7 审查三遗留项 + T8 修复轮的锁定：
- input + js-fallback + check=False → flow 层 deepAll 穿透读 el.value 真值
  比对：相等 → 不判失败；不等/复检不可用 → 走失败协议；
- 失败判定只认 check / expect，不认 dispatch 字段；
- 脱敏强判据 _is_credential（resolve 前对原始模板判定）：html_type=password
  / 变量名含 pw|password|secret|token（不区分大小写）/ 值===*** ——
  context.json、drive_fail、action 事件三处 value 一律 ***；
- load_flow 校验 act 枚举（open/click/input/submit/hover），未知 act 报 FlowError。

T9 增补：多 tab 状态机（tabs/on_new_tab）+ CLI 冒烟（exit 0/4、跑即录产物、
真机新 tab 切换）。
"""
import asyncio
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

from browser_recorder.flow import FlowError, load_flow, resolve_vars

_PROJ_ROOT = pathlib.Path(__file__).parent.parent


def test_load_flow_valid(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "开", "act": "open", "value": "http://a/"},
        {"n": 2, "desc": "点名", "act": "click", "loc": ["css:#b"]},
        {"n": 3, "desc": "输入", "act": "input", "loc": ["css:#i"], "value": "x"},
    ]}))
    flow = load_flow(f)
    assert flow["name"] == "t" and len(flow["steps"]) == 3


def test_load_flow_missing_loc_raises(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "点", "act": "click"}]}))     # 无 loc
    with pytest.raises(FlowError, match="loc"):
        load_flow(f)


def test_load_flow_input_requires_value(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"]}]}))
    with pytest.raises(FlowError, match="value"):
        load_flow(f)


def test_load_flow_unknown_act_raises(tmp_path):
    """M-9：act 枚举校验——未知 act 是格式错误（exit 4 语义）。"""
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "拖", "act": "drag", "loc": ["css:#b"]}]}))
    with pytest.raises(FlowError, match="未知 act"):
        load_flow(f)


def test_load_flow_unknown_wait_raises(tmp_path):
    """终审 Minor-2：wait 枚举校验（settle/none/nav）——未知值是格式错误。"""
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"],
         "wait": "fast"}]}))
    with pytest.raises(FlowError, match="未知 wait"):
        load_flow(f)


def test_resolve_vars():
    assert resolve_vars("用户-${env.USER}", {"USER": "alice"}) == "用户-alice"
    with pytest.raises(FlowError, match="BR_PW"):
        resolve_vars("${env.BR_PW_1}", {})


def test_is_credential_criteria():
    """脱敏强判据（resolve 前对原始模板判定）——信号词不区分大小写。"""
    from browser_recorder.flow import _is_credential
    assert _is_credential({"value": "${env.BR_PW_1}"})                     # pw
    assert _is_credential({"value": "${env.BR_EASYOPS_PW}"})               # 无 html_type 也脱敏
    assert _is_credential({"value": "${env.BR_EASYOPS_PW}"})
    assert _is_credential({"value": "x${env.API_TOKEN}y"})                 # token + 拼接模板
    assert _is_credential({"value": "${env.LOGIN_SECRET}"})                # secret
    assert _is_credential({"value": "${env.my_password}"})                 # 小写
    assert _is_credential({"value": "s3cret", "html_type": "password"})    # html_type 联动
    assert _is_credential({"value": "***"})                                # 上游已脱敏透传
    assert not _is_credential({"value": "${env.BR_USER}"})                 # 普通变量
    assert not _is_credential({"value": "s3cret"})                         # 裸明文无从判起
    assert not _is_credential({"html_type": "text", "value": "x"})


# ---- mock-harness 状态机（monkeypatch flow_mod.locate / flow_mod.act）----

from browser_recorder.flow import run_flow  # noqa: E402
import browser_recorder.flow as flow_mod  # noqa: E402


class FakeHarness:
    """run_flow 依赖面的最小假体：writer 落盘 + emit 收据 + tabs/tid_sid。"""

    def __init__(self, tmp: pathlib.Path):
        self.out_dir = tmp
        self.tabs = {"s0": type("T", (), {"tid": "t0", "sid": "s0"})()}
        self.client = None
        from browser_recorder.writer import SessionWriter
        self.writer = SessionWriter(tmp)
        self.resp_log = []
        self.emitted = []          # (kind, payload) 收据（emit 前截获）
        self.actions = []          # emit_action 收据
        _orig = self.writer.emit

        def wrapped(kind, payload):
            self.emitted.append((kind, dict(payload)))
            return _orig(kind, payload)
        self.writer.emit = wrapped

    async def wait_stable(self, timeout=None):
        return "stable"

    async def navigate(self, url, tid="t0"):
        self.nav_url = url

    async def emit_action(self, payload):
        self.actions.append(dict(payload))
        return self.writer.emit("action", payload)

    def tid_sid(self, tid):
        return "s0"

    def close(self):
        self.writer.close()


def _patch(monkeypatch, locate_fn=None, act_fn=None):
    if locate_fn is not None:
        monkeypatch.setattr(flow_mod, "locate", locate_fn)
    if act_fn is not None:
        monkeypatch.setattr(flow_mod, "act", act_fn)


HIT = {"rect": {"x": 1, "y": 1, "w": 10, "h": 10}, "tag": "button",
       "text": "b", "id": "btn", "name": None, "classes": [], "match_count": 1}


def test_run_flow_happy_path_and_failure(monkeypatch):
    """两步全过 → ok；第二步 locate miss → fail + drive_fail 落盘 + 证据包。

    重试预算：locate 被调 1（成功步）+ 4（失败步 retries=3 → 4 次）= 5。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    h = FakeHarness(tmp)
    calls = {"n": 0}

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        calls["n"] += 1
        return dict(HIT) if calls["n"] == 1 else None

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"]},
            {"n": 2, "desc": "点2", "act": "click", "loc": ["css:#miss"]},
        ]}
        r = await run_flow(h, flow)
        assert r == {"ok": False, "steps_done": 1, "failed_step": 2, "exit_code": 3}
        kinds = [k for k, _ in h.emitted]
        assert "drive_fail" in kinds
        assert calls["n"] == 5
        # 成功步落了 drive_step + action（跑即录）
        assert kinds.count("drive_step") == 1
        step_payload = next(p for k, p in h.emitted if k == "drive_step")
        assert step_payload["n"] == 1 and step_payload["dispatch"] == "trusted"
        assert len(h.actions) == 1 and h.actions[0]["source"] == "drive"
        # 失败证据包落盘（context.json 无条件写）
        ev = next(p for k, p in h.emitted if k == "drive_fail")["evidence"]
        assert json.loads((pathlib.Path(ev) / "context.json").read_text())["n"] == 2
        h.close()

    asyncio.run(_run())


def test_run_flow_js_fallback_deep_recheck_recovers(monkeypatch):
    """T7 遗留 1 / I-3：input + act 复检 miss（js-fallback, check=False）→
    flow 层 deepAll 穿透读 el.value 真值比对：相等 → 不判失败，dispatch 记
    js-fallback+recheck；不等 → 走既有失败协议。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    rechecks = {"n": 0}

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": False}

    async def fake_recheck(client, tabs, tid, locs):
        rechecks["n"] += 1
        return "e2e"          # deepAll 穿透读到 el.value == 预期值

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        monkeypatch.setattr(flow_mod, "_deep_recheck_value", fake_recheck)
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"],
             "value": "e2e"},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is True and r["exit_code"] == 0
        assert rechecks["n"] == 1
        step = next(p for k, p in h.emitted if k == "drive_step")
        assert step["dispatch"] == "js-fallback+recheck"
        h.close()

    asyncio.run(_run())


def test_run_flow_deep_recheck_value_mismatch_fails(monkeypatch):
    """I-3 反向：check=False 且穿透读值 != 预期（输入没进框/复检不可用）→
    check-fail 终止——「元素在」不再足以翻盘。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": False}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        # 值不等 → 失败
        monkeypatch.setattr(flow_mod, "_deep_recheck_value",
                            lambda *a, **k: _ret(""))
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"],
             "value": "e2e"},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is False and r["failed_step"] == 1 \
            and r["exit_code"] == 3
        assert next(p for k, p in h.emitted
                    if k == "drive_fail")["reason"] == "check-fail"
        h.close()

        # 复检不可用（None：候选 miss / evaluate 失败）→ 同样失败
        monkeypatch.setattr(flow_mod, "_deep_recheck_value",
                            lambda *a, **k: _ret(None))
        h2 = FakeHarness(tmp)
        r2 = await run_flow(h2, flow)
        assert r2["ok"] is False and r2["failed_step"] == 1
        h2.close()

    async def _ret(v):
        return v

    asyncio.run(_run())


def test_run_flow_dispatch_not_trusted_but_check_true_ok(monkeypatch):
    """T7 遗留 2：dispatch 字段不可信——check=True 即成功（哪怕 dispatch="js-fallback"）。

    反向：check=False 且 deep 复检也不吻合（非 input 或复检 miss）→ 失败。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"],
             "value": "x"},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is True, "check=True 时 dispatch=js-fallback 不应判失败"
        h.close()

        # 反向：click check=False → 失败（click 无 deep 复检豁免）
        async def bad_act(client, tabs, tid, a, on_dispatch=None):
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": False}
        _patch(monkeypatch, act_fn=bad_act)
        h2 = FakeHarness(tmp)
        click_flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"]},
        ]}
        r2 = await run_flow(h2, click_flow)
        assert r2["ok"] is False and r2["failed_step"] == 1
        assert next(p for k, p in h2.emitted if k == "drive_fail")["reason"] == "check-fail"
        h2.close()

    asyncio.run(_run())


def test_run_flow_password_masked_in_evidence(monkeypatch):
    """T7 遗留 3 / C-1：credential 步失败时 context.json 与 drive_fail 的
    value 均 ***。判据是 resolve 前的原始模板（html_type / 变量名信号词 /
    值===***）——本例变量名 BR_PW_1 命中，html_type 只是第二判据。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": False}   # 触发失败路径

    _patch(monkeypatch, fake_locate, fake_act)
    saved = {}

    async def fake_ev(out_dir, client, tabs, tid, step):
        saved.update(step)
        return pathlib.Path(out_dir) / "evidence" / "fail-step1"

    async def fake_recheck(client, tabs, tid, locs):
        return None      # deep 复检不可用 → 走失败路径（save_evidence 脱敏靶）

    async def _run():
        monkeypatch.setattr(flow_mod, "save_evidence", fake_ev)
        monkeypatch.setattr(flow_mod, "_deep_recheck_value", fake_recheck)
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "密码", "act": "input", "loc": ["css:#pw"],
             "value": "${env.BR_PW_1}", "html_type": "password"},
        ]}
        r = await run_flow(h, flow, env={"BR_PW_1": "s3cret"})
        assert r["ok"] is False
        # save_evidence 收到的 step：值已脱敏（变量名 BR_PW 开头 + html_type 双判据）
        assert saved["value"] == "***"
        # 落盘的 action 事件同样 ***
        act = [json.loads(l) for l in (tmp / "session.jsonl").read_text().splitlines()
               if json.loads(l)["kind"] == "action"][0]
        assert act["value"] == "***"
        # drive_fail 事件同样 ***（C-1：不只 context.json）
        fail = next(p for k, p in h.emitted if k == "drive_fail")
        assert fail["value"] == "***"
        h.close()

    asyncio.run(_run())


def test_run_flow_credential_var_without_html_type_masked(monkeypatch):
    """I-2：变量名含信号词但无 html_type（${env.BR_EASYOPS_PW}）→
    action / drive_fail / context.json 三处 value 一律 ***（明文零落盘）。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": False}

    _patch(monkeypatch, fake_locate, fake_act)
    saved = {}

    async def fake_ev(out_dir, client, tabs, tid, step):
        saved.update(step)
        return pathlib.Path(out_dir) / "evidence" / "fail-step1"

    async def fake_recheck(client, tabs, tid, locs):
        return None

    async def _run():
        monkeypatch.setattr(flow_mod, "save_evidence", fake_ev)
        monkeypatch.setattr(flow_mod, "_deep_recheck_value", fake_recheck)
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "运维密码", "act": "input", "loc": ["css:#pw"],
             "value": "${env.BR_EASYOPS_PW}"},      # 无 html_type，纯变量名判据
        ]}
        r = await run_flow(h, flow, env={"BR_EASYOPS_PW": "topsecret"})
        assert r["ok"] is False
        assert saved["value"] == "***"                    # context.json
        assert next(p for k, p in h.emitted               # drive_fail
                    if k == "drive_fail")["value"] == "***"
        act = [json.loads(l) for l in (tmp / "session.jsonl").read_text().splitlines()
               if json.loads(l)["kind"] == "action"][0]   # action 事件
        assert act["value"] == "***"
        assert act.get("html_type") is None               # 未伪造 html_type
        # 成功路径同判据：check=True 的 credential 步，action 值也是 ***
        h.close()
        h2 = FakeHarness(tmp)

        async def ok_act(client, tabs, tid, a, on_dispatch=None):
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}
        _patch(monkeypatch, act_fn=ok_act)
        r2 = await run_flow(h2, flow, env={"BR_EASYOPS_PW": "topsecret"})
        assert r2["ok"] is True
        ok_act_evt = [json.loads(l)
                      for l in (tmp / "session.jsonl").read_text().splitlines()
                      if json.loads(l)["kind"] == "action"][-1]
        assert ok_act_evt["value"] == "***"
        h2.close()

    asyncio.run(_run())


def test_run_flow_open_dry_run_and_expect(monkeypatch):
    """open 导航、dry-run（只 locate 不 act）、expect 双通道。

    I-1 后网络通道按 arm_t 时间窗过滤——新响应必须在动作派发后到达
    （fake_act 内追加模拟 Network.responseReceived），布防前的旧响应
    不再算命中。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    import time as _time

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        h.resp_log.append({"url": "http://a/api/gateway/x", "status": 200, "t": 1})
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "开", "act": "open", "value": "http://a/"},
            {"n": 2, "desc": "点", "act": "click", "loc": ["css:#b"],
             "expect": {"response_contains": {"url": "/api/gateway/", "status": 200}}},
        ]}
        r = await run_flow(h, flow, dry_run=True)
        assert r["ok"] is True
        assert h.nav_url == "http://a/"
        assert h.actions == [], "dry-run 不派发动作"
        dry = [p for k, p in h.emitted if k == "drive_step"]
        assert dry[0]["dispatch"] == "nav"      # open 步
        assert dry[1]["dispatch"] == "dry"      # dry-run 步
        assert dry[1]["expect_result"] is None  # dry-run 不跑 expect
        h.close()

        # 非 dry-run：动作派发后同 URL 响应到达（arm_t 之后）→ expect 命中
        h2 = FakeHarness(tmp)

        async def act_then_resp(client, tabs, tid, a, on_dispatch=None):
            h2.resp_log.append({"url": "http://a/api/gateway/x", "status": 200,
                                "t": _time.monotonic_ns() // 1_000_000})
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}
        _patch(monkeypatch, act_fn=act_then_resp)
        r2 = await run_flow(h2, flow)
        assert r2["ok"] is True
        stp = [p for k, p in h2.emitted if k == "drive_step"][-1]
        assert stp["expect_result"]["ok"] is True and stp["expect_result"]["channel"] == "net"
        h2.close()

        h3 = FakeHarness(tmp)      # resp_log 空 → expect miss
        _patch(monkeypatch, act_fn=fake_act)
        r3 = await run_flow(h3, flow)
        assert r3["ok"] is False and r3["failed_step"] == 2
        assert next(p for k, p in h3.emitted if k == "drive_fail")["reason"] == "expect-fail"
        h3.close()

    asyncio.run(_run())


def test_expect_response_time_window_filters_stale(monkeypatch):
    """终审 I-1：resp_log 是跨全流程的 200 条滑动窗口——同 URL 的旧响应
    （几十步前，t 很小）不再假阳性命中；只有本步动作 arm 之后的响应算数。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    import time as _time

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    flow = {"name": "t", "steps": [
        {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"],
         "expect": {"response_contains": {"url": "/api/gateway/", "status": 200}}},
    ]}

    async def _run():
        # 只有旧响应（布防前几十步的同 URL 响应）→ miss
        _patch(monkeypatch, fake_locate, fake_act)
        h = FakeHarness(tmp)
        h.resp_log.append({"url": "http://a/api/gateway/old", "status": 200,
                           "t": 1})
        r = await run_flow(h, flow)
        assert r["ok"] is False and r["failed_step"] == 1
        assert next(p for k, p in h.emitted
                    if k == "drive_fail")["reason"] == "expect-fail"
        h.close()

        # 旧响应 + 新响应（act 后到达）并存 → 只有新的算命中 → ok
        h2 = FakeHarness(tmp)

        async def act_then_resp(client, tabs, tid, a, on_dispatch=None):
            h2.resp_log.append({"url": "http://a/api/gateway/new",
                                "status": 200,
                                "t": _time.monotonic_ns() // 1_000_000})
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}
        _patch(monkeypatch, act_fn=act_then_resp)
        h2.resp_log.append({"url": "http://a/api/gateway/old", "status": 200,
                            "t": 1})            # 旧响应：布防前，不算
        r2 = await run_flow(h2, flow)
        assert r2["ok"] is True, "布防后到达的响应应命中（旧响应被时间窗滤掉）"
        stp = [p for k, p in h2.emitted if k == "drive_step"][-1]
        assert stp["expect_result"]["ok"] is True
        h2.close()

    asyncio.run(_run())


def test_run_flow_step_from_skips_earlier(monkeypatch):
    """step_from=2 只执行 n>=2 的步。"""
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点1", "act": "click", "loc": ["css:#a"]},
            {"n": 2, "desc": "点2", "act": "click", "loc": ["css:#b"]},
        ]}
        r = await run_flow(h, flow, step_from=2)
        assert r["ok"] is True
        ns = [p["n"] for k, p in h.emitted if k == "drive_step"]
        assert ns == [2]
        h.close()

    asyncio.run(_run())


def test_run_flow_step_from_prepends_open(monkeypatch):
    """终审 I-2：step_from 把 n=1 的 open 滤掉后自动补回——harness 起点
    about:blank，无起点导航后续步必 miss。过滤结果已含 open 时不重复补。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        # 首步 open 被 step_from=3 滤掉 → 补回，执行的 steps[0] 是 open
        h = FakeHarness(tmp)
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "打开", "act": "open", "value": "http://a/form"},
            {"n": 2, "desc": "点2", "act": "click", "loc": ["css:#a"]},
            {"n": 3, "desc": "点3", "act": "click", "loc": ["css:#b"]},
            {"n": 4, "desc": "点4", "act": "click", "loc": ["css:#c"]},
        ]}
        r = await run_flow(h, flow, step_from=3)
        assert r["ok"] is True
        ns = [p["n"] for k, p in h.emitted if k == "drive_step"]
        assert ns == [1, 3, 4], "补回的 open（n=1）打头，再接 n>=3 的步"
        assert h.nav_url == "http://a/form"
        h.close()

        # 过滤结果已含 open（n=2 是中途导航）→ 不重复补
        h2 = FakeHarness(tmp)
        flow2 = {"name": "t", "steps": [
            {"n": 1, "desc": "打开", "act": "open", "value": "http://a/"},
            {"n": 2, "desc": "站内跳转", "act": "open", "value": "http://a/p2"},
            {"n": 3, "desc": "点3", "act": "click", "loc": ["css:#b"]},
            {"n": 4, "desc": "点4", "act": "click", "loc": ["css:#c"]},
        ]}
        r2 = await run_flow(h2, flow2, step_from=2)
        assert r2["ok"] is True
        ns2 = [p["n"] for k, p in h2.emitted if k == "drive_step"]
        assert ns2 == [2, 3, 4], "已含 open 时不再补回更早的 n=1"
        h2.close()

    asyncio.run(_run())


def test_run_flow_wait_none_skips_post_wait(monkeypatch):
    """终审 Minor-2：wait:"none" 跳过后置等待——wait_stable 调用数只剩
    locate 重试循环里那次前置（1 次）；缺省 settle 是前置+后置（2 次）。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        def make_h(wait_val):
            h = FakeHarness(tmp)
            h.flow_doc = {"name": "t", "steps": [
                {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"],
                 **({"wait": wait_val} if wait_val is not None else {})}]}
            calls = {"n": 0}
            real = h.wait_stable

            async def spy(timeout=None):
                calls["n"] += 1
                return await real(timeout)
            h.wait_stable = spy
            return h, calls

        h_none, c_none = make_h("none")
        r1 = await run_flow(h_none, h_none.flow_doc)
        assert r1["ok"] is True
        assert c_none["n"] == 1, "wait:none 只剩 locate 前置那次 wait_stable"
        h_none.close()

        h_settle, c_settle = make_h(None)     # 缺省 settle
        r2 = await run_flow(h_settle, h_settle.flow_doc)
        assert r2["ok"] is True
        assert c_settle["n"] == 2, "缺省 settle = 前置 + 后置两次"
        h_settle.close()

    asyncio.run(_run())


# ---- T9-fix: 热键停止（I-1）----


def test_run_flow_stop_event_short_circuits(monkeypatch):
    """I-1：stop_event 预置（模态热键已触发）→ run_flow 立即返回失败，
    不执行任何 locate/act——drive 模态下热键也能停止步循环。

    failed_step=当前步 n、reason=hotkey-stop、exit_code=3（复用 _fail 证据包路径）。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    located = []

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        located.append(tid)
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        located.append(("act", tid))
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        # FakeHarness 无 stop_event——I-1 给 run_flow 加的依赖面，补上
        h.stop_event = asyncio.Event()
        h.stop_event.set()          # 热键先于循环触发
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"]},
        ]}
        r = await run_flow(h, flow)
        assert r == {"ok": False, "steps_done": 0, "failed_step": 1,
                     "exit_code": 3}
        assert located == [], "stop_event 已置位时不应执行任何 locate"
        fail = next(p for k, p in h.emitted if k == "drive_fail")
        assert fail["reason"] == "hotkey-stop"
        assert fail["n"] == 1
        h.close()

    asyncio.run(_run())


def test_run_flow_stop_event_after_first_step(monkeypatch):
    """I-1 续：第 1 步完成后热键触发 → 第 2 步开头短路（不在步中途拦截），
    steps_done 计入已完成的第 1 步。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    seen = []

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        seen.append("locate")
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        seen.append("act")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        h.stop_event = asyncio.Event()
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点1", "act": "click", "loc": ["css:#a"]},
            {"n": 2, "desc": "点2", "act": "click", "loc": ["css:#b"]},
        ]}
        real_wait = h.wait_stable

        async def wait_stable_spy(timeout=None):
            # 第 1 步的 drive_step 落盘后、第 2 步进入前触发热键
            if seen.count("act") >= 1 and not h.stop_event.is_set():
                h.stop_event.set()
            return await real_wait(timeout)
        h.wait_stable = wait_stable_spy
        r = await run_flow(h, flow)
        assert r["ok"] is False and r["steps_done"] == 1 \
            and r["failed_step"] == 2 and r["exit_code"] == 3
        assert seen.count("act") == 1, "第 2 步不应派发动作"
        assert next(p for k, p in h.emitted
                    if k == "drive_fail")["reason"] == "hotkey-stop"
        h.close()

    asyncio.run(_run())


# ---- T9: 多 tab 状态机（tabs/on_new_tab 消费）----


class _Tab:
    def __init__(self, tid, sid):
        self.tid, self.sid = tid, sid


def test_run_flow_on_new_tab_switches_target(monkeypatch):
    """on_new_tab=switch：动作后 harness.tabs 出现新 tid（动作前没有的）→
    后续步自动切到新 tid；locate/act 收到的 tid 与 drive_step.target_id 同步。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    holder = {}
    seen_tids = []

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        seen_tids.append(("locate", tid))
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        seen_tids.append(("act", tid))
        if on_dispatch:
            on_dispatch("trusted")
        if a.get("loc") == ["css:#open-newtab"]:
            # 动作效果：新 page target 被 harness.autoAttach 挂上 → tabs 多 t1
            holder["h"].tabs["s1"] = _Tab("t1", "s1")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        holder["h"] = h
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点开新tab", "act": "click",
             "loc": ["css:#open-newtab"], "on_new_tab": "switch"},
            {"n": 2, "desc": "新tab里点名", "act": "click", "loc": ["css:#b"]},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is True
        # n1：locate/act 都在 t0；n2 的 locate 已在 t1
        assert seen_tids[:2] == [("locate", "t0"), ("act", "t0")]
        assert ("locate", "t1") in seen_tids[2:], seen_tids
        steps = [p for k, p in h.emitted if k == "drive_step"]
        assert [s["target_id"] for s in steps] == ["t0", "t1"]
        h.close()

    asyncio.run(_run())


def test_run_flow_tabs_explicit_and_main(monkeypatch):
    """step.tabs 显式指定优先：tabs="new" = 本步元素预期在最新出现的 tab；
    tabs="t0"/"main" 显式回主 tab——自动切换不覆盖显式声明。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    holder = {}

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("trusted")
        if a.get("loc") == ["css:#open-newtab"]:
            holder["h"].tabs["s1"] = _Tab("t1", "s1")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        holder["h"] = h
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点开新tab", "act": "click",
             "loc": ["css:#open-newtab"], "on_new_tab": "switch"},
            {"n": 2, "desc": "新tab里", "act": "click", "loc": ["css:#b"],
             "tabs": "new"},
            {"n": 3, "desc": "回主tab", "act": "click", "loc": ["css:#c"],
             "tabs": "main"},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is True
        steps = [p for k, p in h.emitted if k == "drive_step"]
        assert [s["target_id"] for s in steps] == ["t0", "t1", "t0"]
        h.close()

    asyncio.run(_run())


def test_run_flow_no_auto_switch_without_flag(monkeypatch):
    """无 on_new_tab=switch：动作后出现新 tab 也不切（默认 stay）——
    旧 flow（无 tabs 字段）行为与 T8 完全一致（cur_tid 恒 t0）。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    holder = {}
    seen = []

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        seen.append(("locate", tid))
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        seen.append(("act", tid))
        if on_dispatch:
            on_dispatch("trusted")
        if a.get("loc") == ["css:#open-newtab"]:
            holder["h"].tabs["s1"] = _Tab("t1", "s1")
        return {"dispatch": "trusted", "check": True}

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        h = FakeHarness(tmp)
        holder["h"] = h
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点开新tab", "act": "click", "loc": ["css:#open-newtab"]},
            {"n": 2, "desc": "仍在原tab", "act": "click", "loc": ["css:#b"]},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is True
        assert all(tid == "t0" for _, tid in seen), seen
        h.close()

    asyncio.run(_run())


# ---- T9: CLI 冒烟（真 chrome 子进程）----


def _drive_cmd(flow_path, out, extra=()):
    return [sys.executable, "-m", "browser_recorder.cli", "drive", str(flow_path),
            "--out", str(out), "--headless", "--no-sandbox", *extra]


def test_cli_drive_fixture_e2e_and_exit4(local_site, chrome_path, tmp_path):
    """CLI 冒烟一：完整 drive（非 dry-run）在 fixture 页跑通——exit 0 +
    session 产物含 drive_step/action/screenshot 配对；格式错误 flow → exit 4。
    """
    flow = tmp_path / "smoke.json"
    flow.write_text(json.dumps({"name": "smoke", "steps": [
        {"n": 1, "desc": "打开表单", "act": "open", "value": local_site + "/form.html"},
        {"n": 2, "desc": "标题", "act": "input", "loc": ["css:[name=title]"],
         "value": "冒烟"},
        {"n": 3, "desc": "提交", "act": "click", "loc": ["css:[data-testid=submit-btn]"],
         "expect": {"dom_contains": "已提交：冒烟"}},
    ]}, ensure_ascii=False))
    out = tmp_path / "sessions"
    r = subprocess.run(_drive_cmd(flow, out), capture_output=True, text=True,
                       timeout=180, cwd=_PROJ_ROOT)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    sd = sorted(out.glob("*/session.jsonl"))
    assert sd, "session 未落盘"
    lines = [json.loads(l) for l in sd[-1].read_text().splitlines()]
    kinds = [l["kind"] for l in lines]
    assert "drive_step" in kinds and "action" in kinds
    # 跑即录产物与真人录制同构：session_end + PROMPT.md + before/after 配对
    assert kinds[-1] == "session_end"
    assert (sd[-1].parent / "PROMPT.md").exists()
    # 截图配对：每个 action seq 应有 before（after 可能仍在途，收尾前已 flush）
    acts = [l for l in lines if l["kind"] == "action"]
    shots = [l for l in lines if l["kind"] == "screenshot"]
    before_seqs = {s["action_seq"] for s in shots if s["phase"] == "before"}
    after_seqs = {s["action_seq"] for s in shots if s["phase"] == "after"}
    assert {a["seq"] for a in acts} <= before_seqs
    assert {a["seq"] for a in acts} <= after_seqs
    # action 带 source=drive（跑即录）
    assert all(a.get("source") == "drive" for a in acts)

    # exit 4：格式错误（未知 act）——不是 ClickException 的 exit 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "bad", "steps": [
        {"n": 1, "desc": "拖", "act": "drag", "loc": ["css:#x"]}]}))
    r4 = subprocess.run(_drive_cmd(bad, tmp_path / "o4"), capture_output=True,
                        text=True, timeout=60, cwd=_PROJ_ROOT)
    assert r4.returncode == 4, f"exit={r4.returncode} stderr={r4.stderr}"

    # exit 4：run 期 resolve_vars 的 FlowError（变量未定义）同样转 4
    undef = tmp_path / "undef.json"
    undef.write_text(json.dumps({"name": "u", "steps": [
        {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"],
         "value": "${env.NO_SUCH_VAR}"}]}))
    ru = subprocess.run(_drive_cmd(undef, tmp_path / "ou"), capture_output=True,
                        text=True, timeout=120, cwd=_PROJ_ROOT)
    assert ru.returncode == 4, f"exit={ru.returncode} stderr={ru.stderr}"
    # 终审 Minor-4：run 期 FlowError 的 session_end stop_reason=invalid
    # （与步失败的 drive_fail 区分——格式问题不是驱动失败）
    su = sorted((tmp_path / "ou").glob("*/session.jsonl"))[-1]
    ends = [json.loads(l) for l in su.read_text().splitlines()
            if json.loads(l)["kind"] == "session_end"]
    assert ends and ends[-1]["stop_reason"] == "invalid"
    assert ends[-1]["abnormal"] is True


def test_cli_drive_new_tab_on_fixture(local_site, chrome_path, tmp_path):
    """CLI 冒烟二：真机多 tab——点 newtab-link（target=_blank）→ 后续步在
    新 tab 操作（shadow 按钮命中即证明切过去了）。
    """
    flow = tmp_path / "newtab.json"
    flow.write_text(json.dumps({"name": "newtab", "steps": [
        {"n": 1, "desc": "打开表单", "act": "open", "value": local_site + "/form.html"},
        {"n": 2, "desc": "点新tab链接", "act": "click",
         "loc": ["css:[data-testid=newtab-link]"], "on_new_tab": "switch"},
        {"n": 3, "desc": "新tab点影子按钮", "act": "click",
         "loc": ["css:[data-testid=shadow-btn]"], "tabs": "new"},
        {"n": 4, "desc": "新tab提交", "act": "click", "loc": ["css:#login button"]},
    ]}, ensure_ascii=False))
    out = tmp_path / "sessions"
    r = subprocess.run(_drive_cmd(flow, out), capture_output=True, text=True,
                       timeout=180, cwd=_PROJ_ROOT)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    sd = sorted(out.glob("*/session.jsonl"))
    lines = [json.loads(l) for l in sd[-1].read_text().splitlines()]
    steps = [l for l in lines if l["kind"] == "drive_step"]
    assert [s["target_id"] for s in steps] == ["t0", "t0", "t1", "t1"]


def test_cli_drive_no_record_cleans_tmp(local_site, chrome_path, tmp_path):
    """I-2：--no-record 的临时 session 目录用后即删——含登录态的
    session.jsonl/chrome-profile 不留在 /tmp。--out 仍指向正常录制根目录
    （验证不误删正常目录：no_record 分支根本不用 --out）。
    """
    flow = tmp_path / "smoke.json"
    flow.write_text(json.dumps({"name": "smoke", "steps": [
        {"n": 1, "desc": "打开表单", "act": "open", "value": local_site + "/form.html"},
        {"n": 2, "desc": "标题", "act": "input", "loc": ["css:[name=title]"],
         "value": "无痕"},
        {"n": 3, "desc": "提交", "act": "click", "loc": ["css:[data-testid=submit-btn]"],
         "expect": {"dom_contains": "已提交：无痕"}},
    ]}, ensure_ascii=False))
    out = tmp_path / "sessions"
    before = set(pathlib.Path(tempfile.gettempdir()).glob("br-drive-*"))
    r = subprocess.run(_drive_cmd(flow, out, extra=("--no-record",)),
                       capture_output=True, text=True, timeout=180, cwd=_PROJ_ROOT)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    after = set(pathlib.Path(tempfile.gettempdir()).glob("br-drive-*"))
    leaked = {d for d in after - before if d.is_dir() and any(d.iterdir())}
    assert not leaked, f"--no-record 临时目录泄漏: {leaked}"
    # 正常录制根目录不受影响（no_record 不落 sessions/）
    assert not list(out.glob("*/session.jsonl"))


def test_cli_drive_no_record_failure_path_cleans_tmp(local_site, chrome_path,
                                                     tmp_path):
    """I-2 异常路径：步失败（exit 3）时临时目录同样被 finally 清掉。"""
    flow = tmp_path / "fail.json"
    flow.write_text(json.dumps({"name": "fail", "steps": [
        {"n": 1, "desc": "打开表单", "act": "open", "value": local_site + "/form.html"},
        {"n": 2, "desc": "点不存在的", "act": "click", "loc": ["css:#no-such-thing"],
         "retries": 0, "locate_timeout": 1},
    ]}, ensure_ascii=False))
    out = tmp_path / "sessions"
    before = set(pathlib.Path(tempfile.gettempdir()).glob("br-drive-*"))
    r = subprocess.run(_drive_cmd(flow, out, extra=("--no-record",)),
                       capture_output=True, text=True, timeout=120, cwd=_PROJ_ROOT)
    assert r.returncode == 3, f"exit={r.returncode} stderr={r.stderr}"
    after = set(pathlib.Path(tempfile.gettempdir()).glob("br-drive-*"))
    leaked = {d for d in after - before if d.is_dir() and any(d.iterdir())}
    assert not leaked, f"失败路径临时目录泄漏: {leaked}"


# ---- 终审 I-4：run 期浏览器侧异常 → exit 3（不冒裸 traceback）----


def test_cli_drive_crash_maps_to_exit3(tmp_path, monkeypatch):
    """run 期 CDP 异常（浏览器被关/崩溃 → run_flow 抛 RuntimeError）→
    CLI 收尾后 exit 3 + stderr「运行中断」，不冒裸 traceback（exit 1）。

    cli 结构取可行者：in-process CliRunner + monkeypatch flow.run_flow /
    harness.SessionHarness（drive_cmd 内调用点 import，替身生效），
    不拉真浏览器。
    """
    from click.testing import CliRunner
    import browser_recorder.cli as cli_mod
    import browser_recorder.flow as flow_mod
    import browser_recorder.harness as harness_mod

    flow = tmp_path / "crash.json"
    flow.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"]}]}))

    class _W:
        @staticmethod
        def emit(kind, payload):
            return 0

    class FakeHarness:
        def __init__(self, *a, **k):
            self.body_tasks = set()
            self.tabs = {}
            self.writer = _W()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def flush_inputs(self):
            pass

        def copy_prompt(self):
            pass

    async def boom(*a, **k):
        raise RuntimeError("browser went away (connection reset)")

    monkeypatch.setattr(cli_mod, "DEFAULT_CHROME", flow)   # exists() → True
    monkeypatch.setattr(harness_mod, "SessionHarness", FakeHarness)
    monkeypatch.setattr(flow_mod, "run_flow", boom)

    runner = CliRunner()
    r = runner.invoke(cli_mod.drive_cmd,
                      [str(flow), "--out", str(tmp_path / "o")])
    assert r.exit_code == 3, f"exit={r.exit_code} output={r.output}"
    assert "运行中断" in r.output and "browser went away" in r.output
    # 唯一异常是受控 SystemExit(3)——不是未捕获的 RuntimeError 裸 traceback
    assert type(r.exception) is SystemExit and r.exception.code == 3
