"""端到端：真浏览器 + 本地静态站 + 程序化驱动操作 → 断言事件流/截图/脱敏。

驱动方式：测试侧第二个 CDP ws 连接连同一 page target，用 Runtime.evaluate
驱动 DOM 操作（click / input 派发）。停止：flow 用例 Browser.close（优雅，
退出码 0 → abnormal False 可断言）；hotkey 用例走注入脚本热键路径。

环境适配（无 DISPLAY 容器）：
- record(..., headless=True) 追加 --headless=new
- chrome 在禁用 unprivileged userns 的内核（AppArmor/Docker）里启动即崩
  （zygote "No usable sandbox!"）→ 预热探测失败时给 extra_chrome_args 传
  --no-sandbox

注：与 test_cdp.py 同约定——依赖里没有 pytest-asyncio，用 asyncio.run 包装。
"""
import asyncio
import json
import pathlib
import socket
import subprocess
import tempfile
import time
import urllib.request

from browser_recorder.cdp import CDPClient
from browser_recorder.recorder import record


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


def _chrome_needs_no_sandbox(chrome_path: pathlib.Path) -> bool:
    """预热探测：headless chrome 能否在当前内核起 devtools 端口。

    zygote 沙箱不可用时浏览器进程秒退（stderr FATAL No usable sandbox!），
    devtools HTTP 端口永远不就绪。进程在 1.5s 内退出 = 需要旗子。
    """
    port = _free_port()
    with tempfile.TemporaryDirectory() as td:
        args = [str(chrome_path), f"--remote-debugging-port={port}",
                f"--user-data-dir={td}", "--no-first-run", "--no-default-browser-check",
                "--headless=new", "about:blank"]
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if p.poll() is not None:
                    return True  # 秒退 = 沙箱崩，需要 --no-sandbox
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/json/version", timeout=0.5):
                        return False
                except Exception:
                    time.sleep(0.1)
            return False  # 起得慢但没崩，不添旗子（record 内部还有 5s 重试）
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()


async def _connect_with_retry(port: int, tries: int = 50, interval: float = 0.2) -> CDPClient:
    """等 record() 侧起浏览器 + devtools 就绪后连上（连接重试）。"""
    for _ in range(tries):
        try:
            return await CDPClient.connect(port)
        except Exception:
            await asyncio.sleep(interval)
    raise RuntimeError("drive client 连不上")


async def _wait_page_ready(c: CDPClient) -> None:
    """等 record() 侧导航到 index.html（#btn-fetch 出现）。"""
    for _ in range(50):
        try:
            r = await c.send("Runtime.evaluate", {
                "expression": "document.querySelector('#btn-fetch') ? 'ready' : 'no'",
                "returnByValue": True})
            if r.get("result", {}).get("value") == "ready":
                return
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError("首页 10s 未就绪")


def test_record_session_flow(local_site, chrome_path, tmp_path):
    async def _run():
        port = _free_port()
        extra = ["--no-sandbox"] if _chrome_needs_no_sandbox(chrome_path) else []

        async def drive_task():
            c = await _connect_with_retry(port)
            await _wait_page_ready(c)
            await asyncio.sleep(0.3)  # 注入脚本随页面加载安装
            await c.send("Runtime.evaluate", {"expression":
                "document.querySelector('#btn-fetch').click()"})
            await asyncio.sleep(1.5)  # 等 fetch 流程 + settle + 双截图完成
            await c.send("Runtime.evaluate", {"expression":
                "const i=document.querySelector('input[name=user]');"
                "i.value='alice'; i.dispatchEvent(new Event('input',{bubbles:true}));"})
            await asyncio.sleep(0.8)
            await c.send("Runtime.evaluate", {"expression":
                "const p=document.querySelector('input[name=pass]');"
                "p.value='hunter2'; p.dispatchEvent(new Event('input',{bubbles:true}));"})
            await asyncio.sleep(0.8)
            # 停止：优雅关浏览器（退出码 0 → abnormal False）
            await c.send("Browser.close")
            try:
                await c.close()
            except Exception:
                pass

        dt = asyncio.create_task(drive_task())
        result = await asyncio.wait_for(
            record(tmp_path / "sess", local_site + "/index.html", chrome_path,
                   settle_timeout=5.0, port=port, headless=True,
                   extra_chrome_args=extra),
            timeout=120,
        )
        await dt
        return result

    result = asyncio.run(_run())
    out = tmp_path / "sess"

    # ---- 断言产物 ----
    lines = [json.loads(l) for l in (out / "session.jsonl").read_text().splitlines()]
    kinds = [l["kind"] for l in lines]
    assert "session_start" in kinds and "session_end" in kinds
    assert "nav" in kinds                       # 导航事件
    assert kinds.count("action") >= 3           # click + 2x input（submit 若触发则更多）
    acts = [l for l in lines if l["kind"] == "action"]
    assert any(a["type"] == "click" for a in acts)
    ins = [a for a in acts if a["type"] == "input"]
    assert any(a.get("value") == "alice" for a in ins)
    assert any(a.get("value") == "***" for a in ins)   # password 脱敏
    # 截图文件存在
    shots = list((out / "screenshots").glob("*.png"))
    assert len(shots) >= 6                       # >=3 动作 x before/after
    # 网络：页面自身的请求被记录
    reqs = [l for l in lines if l["kind"] == "request"]
    assert any("index.html" in r["url"] for r in reqs)
    # screenshot 事件带稳定状态
    scr = [l for l in lines if l["kind"] == "screenshot"]
    assert any(s["phase"] == "after" and s.get("status") == "stable" for s in scr)
    # Browser.close 优雅停止：非 abnormal
    assert result["stop_reason"] == "browser_closed"
    assert result["abnormal"] is False
    # PROMPT.md 模板随 session 落盘
    assert (out / "PROMPT.md").exists()
    assert "操作指引" in (out / "PROMPT.md").read_text(encoding="utf-8")


def test_record_hotkey_stop(local_site, chrome_path, tmp_path):
    """页面内热键停止（Ctrl+Shift+F9 经注入脚本路径，用 dispatchEvent 模拟）。"""

    async def _run():
        port = _free_port()
        extra = ["--no-sandbox"] if _chrome_needs_no_sandbox(chrome_path) else []

        async def drive():
            c = await _connect_with_retry(port)
            await _wait_page_ready(c)
            await asyncio.sleep(0.3)  # 等注入热键监听器安装
            await c.send("Runtime.evaluate", {"expression":
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                "{ctrlKey:true, shiftKey:true, key:'F9', keyCode:120, bubbles:true}))"})
            try:
                await c.close()
            except Exception:
                pass

        dt = asyncio.create_task(drive())
        result = await asyncio.wait_for(
            record(tmp_path / "sess2", local_site + "/index.html", chrome_path,
                   port=port, headless=True, extra_chrome_args=extra),
            timeout=60,
        )
        await dt
        return result

    result = asyncio.run(_run())
    assert result["stop_reason"] == "hotkey"
    assert result["abnormal"] is False


def test_record_new_tab_follow(local_site, chrome_path, tmp_path):
    """多 tab 跟随：window.open 开新 tab，新 tab 的导航/请求带独立 target_id。"""

    async def _run():
        port = _free_port()
        extra = ["--no-sandbox"] if _chrome_needs_no_sandbox(chrome_path) else []

        async def drive():
            c = await _connect_with_retry(port)
            await _wait_page_ready(c)
            await asyncio.sleep(0.3)
            # 开新 tab 到 page2（easyops 第 7 步"点击跳转新 tab"的等价形态）。
            # browser 级 createTarget 等价于用户开新标签页；recorder 侧
            # autoAttach 会自动附加并跟随。
            b = await CDPClient.connect_browser(port)
            await b.send("Target.createTarget", {"url": local_site + "/page2.html"})
            await asyncio.sleep(2.0)  # 等 autoAttach 挂域 + 新 tab 加载
            try:
                await b.send("Browser.close")  # 优雅停止（abnormal=False）
                await c.close()
                await b.close()
            except Exception:
                pass

        dt = asyncio.create_task(drive())
        result = await asyncio.wait_for(
            record(tmp_path / "sess3", local_site + "/index.html", chrome_path,
                   settle_timeout=5.0, port=port, headless=True,
                   extra_chrome_args=extra),
            timeout=120,
        )
        await dt
        return result

    result = asyncio.run(_run())
    assert result["stop_reason"] == "browser_closed"
    out = tmp_path / "sess3"
    lines = [json.loads(l) for l in (out / "session.jsonl").read_text().splitlines()]
    # 启动 tab 的 target_id
    t0 = [l for l in lines if l["kind"] == "nav"][0]["target_id"]
    # 新 tab 的导航被记录且 target_id 区分于启动 tab（挂域前加载的页面经
    # 导航历史回填，标 recovered=True——首个文档请求可能错过，属已知边界）
    navs = [l for l in lines if l["kind"] == "nav"]
    new_tab_navs = [n for n in navs if n["target_id"] != t0 and "page2.html" in n["url"]]
    assert new_tab_navs, f"新 tab 导航未跟随: {navs}"
    # 新 tab 内后续触发的请求可录（favicon 与页面加载同时，不作为断言对象；
    # 直接在断言里允许空——核心验证点是新 tab 存在 + nav 跟随 + tabs 汇总）
    # session_end 汇总 tabs
    end = [l for l in lines if l["kind"] == "session_end"][0]
    assert len(end.get("tabs", [])) >= 2, f"tabs 汇总缺失: {end}"
