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


# ---- act：信任派发命令序列 + 降级判定（mock CDP）----

import base64

from browser_recorder.driver import act, save_evidence


class _ActFakeClient:
    """模拟 CDPClient.send：记录调用，Runtime.evaluate 按 expression 内容分支。

    返回结构按真实 CDP（CDPClient.send 已剥外层 wire envelope）：
    Runtime.evaluate → {"result": {"type", "value"}}，单层 result——brief
    示意的双层 {result: {result: ...}} 以实测单层为准（与 _FakeClient 同构）。
    expression 分支标记：deepAll=locate 深查 / scrollIntoView=派发前滚动重取
    rect / getOwnPropertyDescriptor=降级 setter / querySelector=复检读 value。
    """

    def __init__(self, check_value: str = "[]|0", fallback_value: str = "[]|0"):
        self.check_value = check_value        # 复检 evaluate 的应答（默认 miss）
        self.fallback_value = fallback_value  # 降级 JS 的应答（默认 miss）
        self.sent: list[tuple] = []

    async def send(self, method, params=None, timeout=10.0, session_id=None):
        self.sent.append((method, params, session_id))
        if method == "Runtime.evaluate":
            expr = (params or {}).get("expression", "")
            if "scrollIntoView" in expr:
                # act 派发前滚动：坐标被滚动改变（locate 旧 rect 是 10,20）
                return {"result": {"type": "string", "value": json.dumps(
                    {"x": 4, "y": 6, "w": 100, "h": 40})}}
            if "deepAll" in expr:
                payload = json.dumps([
                    {"rect": {"x": 10, "y": 20, "w": 100, "h": 40}, "tag": "button",
                     "text": "按钮", "id": "btn", "name": None, "classes": []},
                ], ensure_ascii=False) + "|1"
                return {"result": {"type": "string", "value": payload}}
            if "getOwnPropertyDescriptor" in expr:
                return {"result": {"type": "string", "value": self.fallback_value}}
            if "querySelector" in expr:
                return {"result": {"type": "string", "value": self.check_value}}
            return {"result": {"type": "string", "value": "[]|0"}}
        return {}


def test_act_click_trusted_dispatch_sequence():
    """click 信任派发：locate→滚动入视→重取 rect→三段鼠标事件。

    锁定坐标语义：鼠标事件取滚动后新 rect 的中心（4+50, 6+20），
    不是 locate 旧 rect 的中心（10+50, 20+20）——T6 审查 Minor-4。
    """
    client = _ActFakeClient()

    async def _run():
        disp = []
        r = await act(client, _tabs(), "t0",
                      {"act": "click", "loc": ["css:#btn"], "rect": None},
                      on_dispatch=disp.append)
        assert r == {"dispatch": "trusted", "check": True}
        assert disp == ["trusted"]
        methods = [m for m, _, _ in client.sent]
        # rect 缺失 → 先 locate（深查 JS），再滚动+重取，然后才是鼠标派发
        assert methods[0] == "Runtime.evaluate"
        assert "deepAll" in client.sent[0][1]["expression"]
        assert methods[1] == "Runtime.evaluate"
        assert "scrollIntoView" in client.sent[1][1]["expression"]
        types = [p.get("type") for m, p, _ in client.sent
                 if m == "Input.dispatchMouseEvent"]
        assert types == ["mouseMoved", "mousePressed", "mouseReleased"]
        for m, p, sid in client.sent:
            if m == "Input.dispatchMouseEvent":
                assert (p["x"], p["y"]) == (54, 26)   # 新 rect 中心，非旧 (60, 40)
                assert sid == "SID1"                   # tid→sid 定向派发

    asyncio.run(_run())


def test_act_input_trusted_key_events():
    """input 信任派发：聚焦点击→清空（Ctrl+A+Delete）→逐键 char。

    FakeClient 复检恒 miss（"[]|0" ≠ "hi"）→ 走 JS 降级；降级复检也 miss
    → check False、on_dispatch 报 js-fallback（降级判定语义的锁定）。
    """
    client = _ActFakeClient()

    async def _run():
        disp = []
        r = await act(client, _tabs(), "t0",
                      {"act": "input", "value": "hi", "clear": True,
                       "loc": ["css:#name"], "rect": None},
                      on_dispatch=disp.append)
        assert r == {"dispatch": "js-fallback", "check": False}
        assert disp == ["js-fallback"]
        keys = [p for m, p, _ in client.sent if m == "Input.dispatchKeyEvent"]
        assert any(k.get("text") == "h" for k in keys)
        assert any(k.get("text") == "i" for k in keys)
        # 清空先行：Delete 在首个 char 之前
        idx_del = next(i for i, (m, p, _) in enumerate(client.sent)
                       if m == "Input.dispatchKeyEvent" and p.get("key") == "Delete")
        idx_first_char = next(i for i, (m, p, _) in enumerate(client.sent)
                              if m == "Input.dispatchKeyEvent" and p.get("text") == "h")
        assert idx_del < idx_first_char
        # 降级 JS：原生 setter + input/change 合成事件（React 受控输入兼容）
        fb = [p for m, p, _ in client.sent
              if m == "Runtime.evaluate"
              and "getOwnPropertyDescriptor" in (p or {}).get("expression", "")]
        assert fb and "new Event('input', {bubbles: true})" in fb[-1]["expression"]
        assert "new Event('change', {bubbles: true})" in fb[-1]["expression"]

    asyncio.run(_run())


def test_act_input_recheck_pass_stays_trusted():
    """复检命中（value == 预期）即信任成功：不发降级 JS、on_dispatch 报 trusted。"""
    client = _ActFakeClient(check_value="hi")

    async def _run():
        disp = []
        r = await act(client, _tabs(), "t0",
                      {"act": "input", "value": "hi", "clear": True,
                       "loc": ["css:#name"], "rect": None},
                      on_dispatch=disp.append)
        assert r == {"dispatch": "trusted", "check": True}
        assert disp == ["trusted"]
        # 未派发降级 setter JS
        assert not any("getOwnPropertyDescriptor" in (p or {}).get("expression", "")
                       for m, p, _ in client.sent if m == "Runtime.evaluate")

    asyncio.run(_run())


def test_save_evidence_writes_package(tmp_path):
    """证据包三件套：screenshot.png / dom.json / context.json。"""

    class _EvClient:
        async def send(self, method, params=None, timeout=10.0, session_id=None):
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"pngdata").decode()}
            if method == "Runtime.evaluate":
                return {"result": {"type": "string", "value": "<html></html>"}}
            return {}

    async def _run():
        p = await save_evidence(tmp_path, _EvClient(), _tabs(), "t0",
                                {"n": 7, "loc": ["css:#x"], "tried": ["css:#x"],
                                 "retries": 3, "url": "http://a/", "dispatch": "trusted"})
        assert p == tmp_path / "evidence" / "fail-step7"
        ctx = json.loads((p / "context.json").read_text())
        assert ctx["n"] == 7 and ctx["retries"] == 3
        dom = json.loads((p / "dom.json").read_text())
        assert dom["html"] == "<html></html>" and dom["url"] == "http://a/"
        assert (p / "screenshot.png").read_bytes() == b"pngdata"

    asyncio.run(_run())


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


def _launch_chrome_tab(chrome_path, port: int, td: str, url: str):
    """起 headless chrome 打开指定页（真机回路共用）。"""
    return subprocess.Popen(
        [str(chrome_path), f"--remote-debugging-port={port}",
         f"--user-data-dir={td}", "--no-first-run", "--headless=new",
         "--no-sandbox", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def _connect_page(port: int) -> CDPClient:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as r:
        ws_url = next(t["webSocketDebuggerUrl"] for t in json.loads(r.read())
                      if t.get("type") == "page")
    return await CDPClient.connect(port, ws_url=ws_url)


@pytest.mark.usefixtures("local_site")
def test_locate_real_browser_visibility_layers(chrome_path):
    """可见性分层判据（T6 审查补回项的回归锁）：

    - transform 动画 mid-flight 的 0×0 rect 元素：有盒（offsetParent/
      clientRects）即可命中（headless 放宽，easyops_mvp FIND_JS L105-113 沉库）
    - hidden 祖先 / display:none 祖先 / visibility:hidden 祖先：排除
    """
    port = 8874
    page_url = ("data:text/html,"
                "<button id='tiny' style='transform:scale(0)'>小</button>"
                "<div hidden><button id='inh'>隐</button></div>"
                "<div style='display:none'><button id='ind'>藏</button></div>"
                "<div style='visibility:hidden'><button id='inv'>失</button></div>"
                "<button id='ok'>正</button>")

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            p = _launch_chrome_tab(chrome_path, port, td, page_url)
            try:
                if not _wait_devtools(port):
                    pytest.fail("chrome devtools 端口未就绪")
                page = await _connect_page(port)
                try:
                    tabs = {"s0": types.SimpleNamespace(tid="t0", sid=None)}
                    hit = await locate(page, tabs, "t0", ["css:#tiny"], timeout=5)
                    assert hit is not None, "transform 0×0 有盒元素应命中（放宽层）"
                    assert hit["rect"]["w"] == 0 and hit["rect"]["h"] == 0
                    for bad in ("#inh", "#ind", "#inv"):
                        miss = await locate(page, tabs, "t0", [f"css:{bad}"],
                                            timeout=0.3)
                        assert miss is None, f"{bad} 隐藏祖先应被排除"
                    ok = await locate(page, tabs, "t0", ["css:#ok"], timeout=2)
                    assert ok is not None and ok["rect"]["w"] > 0
                finally:
                    await page.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())


@pytest.mark.usefixtures("local_site")
def test_act_input_real_browser_controlled(local_site, chrome_path):
    """真机：信任逐键输入到 form.html 标题框，复检 value 生效。

    顺带验滚动重取：form.html 无滚动场景，此处锁定的是完整输入链路
    （聚焦→清空→逐键→复检）在真浏览器的 trusted 路径。
    """
    port = 8872

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            p = _launch_chrome_tab(chrome_path, port, td, f"{local_site}/form.html")
            try:
                if not _wait_devtools(port):
                    pytest.fail("chrome devtools 端口未就绪")
                page = await _connect_page(port)
                try:
                    tabs = {"s0": types.SimpleNamespace(tid="t0", sid=None)}
                    hit = await locate(page, tabs, "t0", ["css:[name=title]"],
                                       timeout=5)
                    assert hit, "form.html 标题框未命中"
                    disp = []
                    r = await act(page, tabs, "t0",
                                  {"act": "input", "value": "e2e标题",
                                   "loc": ["css:[name=title]",
                                           "css:[data-testid=title-input]"],
                                   "rect": hit["rect"]},
                                  on_dispatch=disp.append)
                    assert r["check"] is True
                    assert r["dispatch"] in ("trusted", "js-fallback")
                    assert disp == [r["dispatch"]]   # on_dispatch 报实际派发方式
                finally:
                    await page.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())


@pytest.mark.usefixtures("local_site")
def test_act_click_and_submit_real_browser(local_site, chrome_path):
    """真机：input 信任逐键 → click 提交按钮 → onsubmit 改 DOM → submit 动作。

    click 复检的靶：form.html 的 submitForm 是受控更新（真实 click 派发 →
    onsubmit → #result 文本变化），此处用 evaluate 读 #result 验证 click 生效。
    """
    port = 8873

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            p = _launch_chrome_tab(chrome_path, port, td, f"{local_site}/form.html")
            try:
                if not _wait_devtools(port):
                    pytest.fail("chrome devtools 端口未就绪")
                page = await _connect_page(port)
                try:
                    tabs = {"s0": types.SimpleNamespace(tid="t0", sid=None)}

                    async def eval_js(expr: str) -> str:
                        r = await page.send("Runtime.evaluate",
                                            {"expression": expr,
                                             "returnByValue": True})
                        return (r.get("result") or {}).get("value") or ""

                    # input（信任逐键）→ click 提交 → #result 反映输入值
                    disp = []
                    r = await act(page, tabs, "t0",
                                  {"act": "input", "value": "回路",
                                   "loc": ["css:[name=title]"], "rect": None},
                                  on_dispatch=disp.append)
                    assert r["check"] is True
                    r = await act(page, tabs, "t0",
                                  {"act": "click",
                                   "loc": ["css:[data-testid=submit-btn]",
                                           "text:^提交"],
                                   "rect": None},
                                  on_dispatch=disp.append)
                    assert r == {"dispatch": "trusted", "check": True}
                    await asyncio.sleep(0.3)   # onsubmit 同步改 DOM，留裕量
                    txt = await eval_js(
                        "(document.getElementById('result')||{}).textContent||''")
                    assert "已提交：回路" in txt, f"click 未触发 submitForm: {txt!r}"
                    # submit 动作：form 上下文找 button[type=submit] → click
                    r2 = await act(page, tabs, "t0",
                                   {"act": "submit", "loc": ["css:#the-form"],
                                    "rect": None},
                                   on_dispatch=disp.append)
                    assert r2 == {"dispatch": "js", "check": True}
                    assert disp == [r["dispatch"], "trusted", "js"]
                finally:
                    await page.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())
