"""flow 引擎单测：加载校验/变量解析/执行状态机（mock harness）。

T7 审查三遗留项 + T8 修复轮的锁定：
- input + js-fallback + check=False → flow 层 deepAll 穿透读 el.value 真值
  比对：相等 → 不判失败；不等/复检不可用 → 走失败协议；
- 失败判定只认 check / expect，不认 dispatch 字段；
- 脱敏强判据 _is_credential（resolve 前对原始模板判定）：html_type=password
  / 变量名含 pw|password|secret|token（不区分大小写）/ 值===*** ——
  context.json、drive_fail、action 事件三处 value 一律 ***；
- load_flow 校验 act 枚举（open/click/input/submit/hover），未知 act 报 FlowError。
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


def test_load_flow_unknown_act_raises(tmp_path):
    """M-9：act 枚举校验——未知 act 是格式错误（exit 4 语义）。"""
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "拖", "act": "drag", "loc": ["css:#b"]}]}))
    with pytest.raises(FlowError, match="未知 act"):
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
