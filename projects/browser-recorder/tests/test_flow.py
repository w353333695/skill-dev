"""flow 引擎单测：加载校验/变量解析/执行状态机（mock harness）。

T7 审查三遗留项的锁定：
- input + js-fallback + check=False → flow 层 deepAll 显式复检命中 → 不判失败；
- 失败判定只认 check / expect，不认 dispatch 字段；
- save_evidence 的 step dict（context.json）password 值先替换为 ***。
"""
import asyncio
import json
import pathlib
import tempfile

import pytest

from browser_recorder.flow import FlowError, load_flow, resolve_vars


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


def test_resolve_vars():
    assert resolve_vars("用户-${env.USER}", {"USER": "alice"}) == "用户-alice"
    with pytest.raises(FlowError, match="BR_PW"):
        resolve_vars("${env.BR_PW_1}", {})


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
    """T7 遗留 1：input + act 复检 miss（js-fallback, check=False）→ flow 层
    deepAll 显式复检命中且 tag/text 吻合 → 不判失败，dispatch 记 js-fallback+recheck。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    h = FakeHarness(tmp)
    rechecks = {"n": 0}

    async def fake_locate(client, tabs, tid, locs, timeout=10):
        return dict(HIT)

    async def fake_act(client, tabs, tid, a, on_dispatch=None):
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": False}

    async def fake_recheck(client, tabs, tid, locs, timeout=10):
        rechecks["n"] += 1
        return {**HIT, "value": "e2e"}          # deepAll 复检：元素在且值已生效

    _patch(monkeypatch, fake_locate, fake_act)

    async def _run():
        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"],
             "value": "e2e"},
        ]}
        monkeypatch.setattr(flow_mod, "_deep_recheck", fake_recheck)
        r = await run_flow(h, flow)
        assert r["ok"] is True and r["exit_code"] == 0
        assert rechecks["n"] == 1
        step = next(p for k, p in h.emitted if k == "drive_step")
        assert step["dispatch"] == "js-fallback+recheck"
        h.close()

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
    """T7 遗留 3：失败步 save_evidence 的 step dict 里 password 值 → ***。

    三判据：html_type=password / 值===*** / 变量名 BR_PW 开头（resolve 前）。
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

    async def fake_recheck(client, tabs, tid, locs, timeout=10):
        return None      # deep 复检也 miss → 走失败路径（save_evidence 脱敏靶）

    async def _run():
        monkeypatch.setattr(flow_mod, "save_evidence", fake_ev)
        monkeypatch.setattr(flow_mod, "_deep_recheck", fake_recheck)
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
        h.close()

    asyncio.run(_run())


def test_run_flow_open_dry_run_and_expect(monkeypatch):
    """open 导航、dry-run（只 locate 不 act）、expect 双通道。"""
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

        # 非 dry-run：expect 命中 → expect_result.ok=True；miss → drive_fail
        h2 = FakeHarness(tmp)
        h2.resp_log.append({"url": "http://a/api/gateway/x", "status": 200, "t": 2})
        r2 = await run_flow(h2, flow)
        assert r2["ok"] is True
        stp = [p for k, p in h2.emitted if k == "drive_step"][-1]
        assert stp["expect_result"]["ok"] is True and stp["expect_result"]["channel"] == "net"
        h2.close()

        h3 = FakeHarness(tmp)      # resp_log 空 → expect miss
        r3 = await run_flow(h3, flow)
        assert r3["ok"] is False and r3["failed_step"] == 2
        assert next(p for k, p in h3.emitted if k == "drive_fail")["reason"] == "expect-fail"
        h3.close()

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
