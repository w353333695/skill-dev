"""driver 单测：locate 的 JS 生成纯函数 + mock CDP 命令序列。"""
import asyncio
import json
import types

from browser_recorder.driver import find_elements_js, locate


def test_find_elements_js_css():
    js = find_elements_js(["css:#name", "text:提交"])
    assert "deepAll" in js          # shadow 穿透函数在
    assert "#name" in js and "提交" in js
    assert "xpath" not in js.split("deepAll")[0]   # 粗验：非 xpath 分支不混淆


def test_find_elements_js_xpath_and_dom():
    js = find_elements_js(["xpath://*[@id='x']", "dom:div>a"])
    assert "document.evaluate" in js
    assert "dom" in js


class _FakeClient:
    """模拟 CDPClient.send：只回应 Runtime.evaluate，记录调用参数。

    返回结构按真实 CDP：send() 已剥掉外层 wire result，此处即
    {"result": {"type", "value"}}（Runtime.evaluate 的 RemoteObject）。
    """

    def __init__(self, value: str = "[]|0"):
        self.value = value
        self.calls: list[tuple] = []

    async def send(self, method, params=None, timeout=10.0, session_id=None):
        self.calls.append((method, params, session_id))
        return {"result": {"type": "string", "value": self.value}}


def _tabs():
    # {sid: tab}，tab 带 .tid/.sid（与 harness._TabSession 同构）
    return {"SID1": types.SimpleNamespace(tid="t0", sid="SID1")}


def test_locate_hit_parses_cdp_value():
    payload = json.dumps([
        {"rect": {"x": 10, "y": 20, "w": 100, "h": 40}, "tag": "button",
         "text": "影子按钮", "id": None, "name": None, "classes": []}
    ], ensure_ascii=False) + "|1"
    client = _FakeClient(payload)

    async def _run():
        return await locate(client, _tabs(), "t0", ["css:#name", "text:提交"])

    hit = asyncio.run(_run())
    assert hit is not None
    assert hit["tag"] == "button" and hit["text"] == "影子按钮"
    assert hit["match_count"] == 1
    method, params, sid = client.calls[0]
    assert method == "Runtime.evaluate" and sid == "SID1"   # tid→sid 定向
    assert params["awaitPromise"] is True and params["returnByValue"] is True
    assert "deepAll" in params["expression"]                 # deepQuery JS 已注入


def test_locate_miss_returns_none():
    client = _FakeClient("[]|0")

    async def _run():
        return await locate(client, _tabs(), "t0", ["css:#nope"], timeout=0.1)

    assert asyncio.run(_run()) is None
    assert len(client.calls) >= 1   # 轮询至少发过一次


# ---- 真浏览器回路（chrome 缺失时 skip）----

import pathlib
import subprocess
import tempfile
import time
import urllib.request

import pytest

from browser_recorder.cdp import CDPClient


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_devtools(port: int, tries: int = 50, interval: float = 0.2) -> bool:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                        timeout=0.5):
                return True
        except Exception:
            time.sleep(interval)
    return False


@pytest.mark.usefixtures("local_site")
def test_locate_real_browser_shadow_dom(local_site, chrome_path):
    """deepQuery 穿透 open shadow root 命中 [data-testid=shadow-btn]。

    普通 querySelector 打不进 shadow root——css: 候选命中即穿透的证明。
    dom:/text:/xpath: 三策略同页一次回路覆盖（四策略候选链全验）。
    """
    import time  # noqa: F401  # （模块级已导入，留档说明）

    async def _run():
        port = 8871
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.Popen(
                [str(chrome_path), f"--remote-debugging-port={port}",
                 f"--user-data-dir={td}", "--no-first-run", "--headless=new",
                 "--no-sandbox", f"{local_site}/index.html"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if not _wait_devtools(port):
                    pytest.fail("chrome devtools 端口未就绪")
                # page target 直连（与 harness 的 flatten 子会话不同，
                # session_id 传 None——locate 的 _sid_of 返回 None 即可）
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list") as r:
                    ws_url = next(t["webSocketDebuggerUrl"]
                                  for t in json.loads(r.read())
                                  if t.get("type") == "page")
                page = await CDPClient.connect(port, ws_url=ws_url)
                try:
                    tabs = {"fake": types.SimpleNamespace(tid="t0", sid=None)}
                    hit = await locate(page, tabs, "t0",
                                       ["css:[data-testid=shadow-btn]",
                                        "text:影子按钮"],
                                       timeout=5)
                    assert hit is not None and hit["tag"] == "button"
                    assert hit["id"] is None and hit["match_count"] == 1
                    # dom: 直译穿透（demo-widget 的 shadow 内 button）
                    hit2 = await locate(page, tabs, "t0", ["dom:demo-widget>button"],
                                        timeout=2)
                    assert hit2 is not None and hit2["tag"] == "button"
                    # text: 词首锚定（普通文档按钮）
                    hit3 = await locate(page, tabs, "t0", ["text:^点我"],
                                        timeout=2)
                    assert hit3 is not None and hit3["id"] == "btn-fetch"
                    # xpath: 原样求值（form 提交按钮）
                    hit4 = await locate(page, tabs, "t0",
                                        ["xpath://button[@type='submit']"],
                                        timeout=2)
                    assert hit4 is not None and hit4["text"] == "提交"
                    # 全 miss → None（超时路径）
                    miss = await locate(page, tabs, "t0", ["css:#no-such-thing"],
                                        timeout=0.3)
                    assert miss is None
                finally:
                    await page.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())
