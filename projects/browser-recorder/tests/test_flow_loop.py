"""T8 回路冒烟：run_flow 在真 chrome + fixture 页跑完整状态机（open→input→
click→expect dom/net 双通道 + password 脱敏落盘 + 失败步证据包）。

与单测（monkeypatch locate/act）互补：这条不 patch 任何 driver 函数，
locate/act/_check_expect 全走真浏览器。harness 侧仅 FakeShell 提供
navigate/wait_stable/emit_action 的轻量替身（完整 SessionHarness 回路是
T9 CLI 冒烟的职责，避免本测试重复拉整套注入管线）。
"""
import asyncio
import json
import pathlib
import subprocess
import tempfile
import urllib.request

import pytest

from browser_recorder.cdp import CDPClient
from browser_recorder.flow import run_flow
from browser_recorder.writer import SessionWriter

pytestmark = pytest.mark.usefixtures("local_site")

_SITE = pathlib.Path(__file__).parent / "fixtures" / "site"


class _Tab:
    def __init__(self, tid, sid):
        self.tid, self.sid = tid, sid


class FakeShell:
    """run_flow 依赖面的会话壳（client/tabs/tid_sid/navigate/wait_stable/
    emit_action/out_dir/resp_log），不拉浏览器管线。"""

    def __init__(self, tmp, client):
        self.out_dir = tmp
        self.client = client
        self.tabs = {"s0": _Tab("t0", "s0")}
        self.writer = SessionWriter(tmp)
        self.resp_log = []
        self.actions = []
        self.emitted = []
        _orig = self.writer.emit

        def wrapped(kind, payload):
            self.emitted.append((kind, dict(payload)))
            return _orig(kind, payload)
        self.writer.emit = wrapped

    async def wait_stable(self, timeout=None):
        await asyncio.sleep(0.1)
        return "stable"

    async def navigate(self, url, tid="t0"):
        await self.client.send("Page.navigate", {"url": url},
                               session_id=self.tid_sid(tid))

    async def emit_action(self, payload):
        self.actions.append(dict(payload))
        return self.writer.emit("action", {
            "type": payload.get("type"), "source": payload.get("source"),
            "value": payload.get("value"), "html_type": payload.get("html_type"),
            "target_id": payload.get("target_id"),
        })

    def tid_sid(self, tid):
        return None          # page target 直连：命令不带 sessionId

    def close(self):
        self.writer.close()


def _wait_devtools(port, tries=50, interval=0.2):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                        timeout=0.5):
                return True
        except Exception:
            import time
            time.sleep(interval)
    return False


def test_run_flow_real_browser_fixture(local_site, chrome_path, tmp_path):
    port = 8875

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.Popen(
                [str(chrome_path), f"--remote-debugging-port={port}",
                 f"--user-data-dir={td}", "--no-first-run", "--headless=new",
                 "--no-sandbox", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if not _wait_devtools(port):
                    pytest.fail("chrome devtools 端口未就绪")
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list") as r:
                    ws_url = next(t["webSocketDebuggerUrl"]
                                  for t in json.loads(r.read())
                                  if t.get("type") == "page")
                client = await CDPClient.connect(port, ws_url=ws_url)
                try:
                    # page target 直连：无 flatten 子会话，tabs 替身 sid="s0"
                    # 但真发命令要 session_id=None——改用空映射约定：
                    # FakeShell.tabs 指向 sid=None 的 page 直连
                    h = FakeShell(tmp_path, client)
                    h.tabs = {"s0": _Tab("t0", None)}
                    flow = {"name": "smoke", "steps": [
                        {"n": 1, "desc": "打开表单", "act": "open",
                         "value": f"{local_site}/form.html"},
                        {"n": 2, "desc": "标题", "act": "input",
                         "loc": ["css:[name=title]"], "value": "回路"},
                        {"n": 3, "desc": "密钥", "act": "input",
                         "loc": ["css:[name=secret]"], "value": "s3cret",
                         "html_type": "password"},
                        {"n": 4, "desc": "提交", "act": "click",
                         "loc": ["css:[data-testid=submit-btn]"],
                         "expect": {"dom_contains": "已提交：回路"}},
                        {"n": 5, "desc": "断网靶", "act": "click",
                         "loc": ["css:#result"],
                         "expect": {"response_contains": {"url": "/api/echo",
                                                          "status": 200}}},
                    ]}
                    r = await run_flow(h, flow)
                    # n5 expect：click #result 不再触发 fetch（form 只在 submit
                    # 时 fetch 一次）→ resp_log 无新 /api/echo → expect-fail。
                    # 这正好覆盖失败协议：drive_fail + 证据包 + exit 3。
                    assert r == {"ok": False, "steps_done": 4, "failed_step": 5,
                                 "exit_code": 3}
                    # password 步：action 落盘值 ***（html_type 联动脱敏）
                    lines = [json.loads(l)
                             for l in (tmp_path / "session.jsonl").read_text()
                             .splitlines()]
                    pw = [l for l in lines if l["kind"] == "action"
                          and l.get("value") is not None][1]
                    assert pw["value"] == "***" and pw["html_type"] == "password"
                    # drive_step 前四步齐：nav + input×2 + click；expect dom 通道过
                    steps = [l for l in lines if l["kind"] == "drive_step"]
                    assert [s["n"] for s in steps] == [1, 2, 3, 4]
                    assert steps[3]["expect_result"]["channel"] == "dom"
                    assert steps[3]["expect_result"]["ok"] is True
                    fails = [l for l in lines if l["kind"] == "drive_fail"]
                    assert len(fails) == 1 and fails[0]["n"] == 5 \
                        and fails[0]["reason"] == "expect-fail"
                    ev = pathlib.Path(fails[0]["evidence"])
                    assert (ev / "context.json").exists()
                    assert (ev / "dom.json").exists()
                    # 证据包 step dict 不含明文密码（n3 才是 password 步，
                    # n5 无 value；此处锁定 save_evidence 调用约定本身）
                    h.close()
                finally:
                    await client.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())
