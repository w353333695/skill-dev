"""录制编排：拉浏览器、挂三域、双截图、稳定等待、三层停止。

record() 是一次完整会话：Popen 干净 Chromium → CDP 直连 → Network/Page/Runtime 三域
→ 注入采集脚本 → 事件流落盘（writer）→ 三层停止（页面热键 / 关浏览器 / 终端 q）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from .annotator import annotate
from .cdp import CDPClient
from .writer import SessionWriter

log = logging.getLogger(__name__)

INJECT_JS = pathlib.Path(__file__).with_name("inject.js").read_text(encoding="utf-8")
SETTLE_DOM_SILENCE_MS = 500
ACTION_TYPES = ("click", "input", "submit")


class StableState:
    """网络空闲 ∧ DOM 静默 500ms 的稳定判定状态。"""

    def __init__(self):
        self.inflight = 0
        self.last_mutation_ms = time.monotonic_ns() // 1_000_000
        self._long_conn_ids: set[str] = set()  # websocket/SSE 等常驻连接不算 in-flight

    def net_open(self, request_id: str, url: str) -> None:
        if any(k in url for k in ("ws://", "wss://", "/sse", "eventsource")):
            self._long_conn_ids.add(request_id)
            return
        self.inflight += 1

    def net_close(self, request_id: str) -> None:
        if request_id in self._long_conn_ids:
            self._long_conn_ids.discard(request_id)
            return
        self.inflight = max(0, self.inflight - 1)

    def mark_mutation(self) -> None:
        self.last_mutation_ms = time.monotonic_ns() // 1_000_000


async def wait_stable(state: StableState, timeout: float) -> str:
    """两条件：inflight==0 且 距上次突变 >=500ms。返回 "stable" | "timeout"。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        now = time.monotonic_ns() // 1_000_000
        if state.inflight == 0 and now - state.last_mutation_ms >= SETTLE_DOM_SILENCE_MS:
            return "stable"
        await asyncio.sleep(0.05)
    return "timeout"


async def record(
    out_dir: pathlib.Path,
    start_url: str,
    chrome_path: pathlib.Path,
    settle_timeout: float = 30.0,
    port: int | None = None,
    headless: bool = False,
    extra_chrome_args: list[str] | None = None,
) -> dict:
    """完成一次录制到停止。返回 {"events", "out_dir", "abnormal", "stop_reason"}。

    stop_reason ∈ {"hotkey", "browser_closed", "terminal_q"}；
    abnormal 仅在 browser_closed 且退出码非 0（崩溃/被杀）时为 True。
    extra_chrome_args：追加的浏览器启动参数（容器/受限环境传 ["--no-sandbox"]）。
    """
    out_dir = pathlib.Path(out_dir)
    writer = SessionWriter(out_dir)
    state = StableState()
    stop_evt = asyncio.Event()
    action_q: asyncio.Queue = asyncio.Queue()  # 注入上报 → action_loop（双截图）
    body_tasks: set[asyncio.Task] = set()  # 在途 getResponseBody 抓取
    port = port or _free_port()

    args = [
        str(chrome_path),
        f"--remote-debugging-port={port}",
        "--user-data-dir=%s" % (out_dir / "chrome-profile"),
        "--no-first-run", "--no-default-browser-check",
        "--window-size=1280,900",
        "about:blank",
    ]
    if headless:
        args.append("--headless=new")
    args.extend(extra_chrome_args or [])
    chrome: subprocess.Popen | None = None  # Popen 失败（chrome_path 无效）也要走 finally 关 writer
    client: CDPClient | None = None
    actions: asyncio.Task | None = None
    finished = False  # 正常收尾（session_end 已 emit）标记；finally 据此补中断收尾
    try:
        chrome = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not await _wait_devtools(port):
            raise RuntimeError(
                "浏览器 devtools 端口未就绪（检查 DISPLAY/端口占用，可用 port= 换端口）")
        client = await CDPClient.connect(port)

        writer.emit("session_start", {"url": start_url, "ts": time.time(),
                                      "chrome": str(chrome_path), "pid": chrome.pid})

        # ---- 挂三域 + binding + 注入 ----
        await client.send("Network.enable")
        await client.send("Page.enable")
        await client.send("Runtime.enable")
        # binding 先注册（对当前执行上下文立即生效），再挂新文档脚本，最后手动评估当前页
        await client.send("Runtime.addBinding", {"name": "__brEvent"})
        await client.send("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT_JS})
        await client.send("Runtime.evaluate", {"expression": INJECT_JS})  # 当前页立即生效

        # ---- CDP 事件处理 ----
        def on_req(p):
            if "redirectResponse" in p:
                # 重定向跳复用同一 requestId 且无对应 responseReceived，
                # 再计 in-flight 会永久 +1 → wait_stable 必走满 timeout。
                # 只跳过记账，request 事件仍落盘（重定向 hop 不丢）。
                pass
            else:
                state.net_open(p["requestId"], p.get("request", {}).get("url", ""))
            writer.emit("request", {
                "request_id": p["requestId"], "method": p.get("request", {}).get("method"),
                "url": p.get("request", {}).get("url"), "headers": p.get("request", {}).get("headers"),
                "post_body": _post_body(p), "initiator": p.get("initiator", {}).get("type"),
            })
        client.on("Network.requestWillBeSent", on_req)

        def on_resp(p):
            state.net_close(p["requestId"])
            writer.emit("response", {
                "request_id": p["requestId"], "status": p["response"].get("status"),
                "mime": p["response"].get("mimeType"), "headers": p["response"].get("headers"),
                "size": p["response"].get("encodedDataLength"),
            })
            t = asyncio.get_running_loop().create_task(
                _fetch_body(client, writer, p["requestId"]))
            body_tasks.add(t)
            t.add_done_callback(body_tasks.discard)
        client.on("Network.responseReceived", on_resp)

        def on_loading_fail(p):
            state.net_close(p["requestId"])
        client.on("Network.loadingFailed", on_loading_fail)

        def on_nav(p):
            if p.get("frame", {}).get("parentId") is None:  # 主 frame
                writer.emit("nav", {"url": p.get("frame", {}).get("url", ""), "title": ""})
        client.on("Page.frameNavigated", on_nav)

        # ---- 注入上报（扁平 payload）----
        # 经 "*" 订阅（回调签名 (method, params) 两参）过滤出 bindingCalled；
        # 处理体全同步安全：unbounded queue 用 put_nowait，stop_evt.set 幂等。
        def on_any_event(method: str, params: dict) -> None:
            if method != "Runtime.bindingCalled" or params.get("name") != "__brEvent":
                return
            try:
                payload = json.loads(params["payload"])
            except (json.JSONDecodeError, KeyError):
                return
            t = payload.get("type")
            if t == "control_stop":
                writer.emit("control_stop", {})
                stop_evt.set()
            elif t == "dom_mutations":
                state.mark_mutation()
                writer.emit("dom_mutations", {"count": payload.get("count", 0)})
            elif t in ACTION_TYPES:
                action_q.put_nowait(payload)
        client.on("*", on_any_event)

        # ---- 动作处理协程：双截图 ----
        async def action_loop():
            while True:
                payload = await action_q.get()
                if payload is None:
                    break
                seq = writer.emit("action", {
                    "type": payload["type"],
                    "element": {"rect": payload.get("rect"),
                                "viewport": payload.get("viewport"),
                                "descriptor": payload.get("descriptor")},
                    "value": payload.get("value"), "html_type": payload.get("html_type"),
                    "before_shot": None, "after_shot": None,
                })
                # before（尽力而为，跳转竞态时标 raced）
                before_status = "ok"
                try:
                    shot = await client.send("Page.captureScreenshot", {"format": "png"})
                    _save_shot(out_dir, seq, "before", shot["data"])
                except Exception:
                    before_status = "raced"
                # after（等稳定再截）
                how = await wait_stable(state, settle_timeout)
                after_status = how
                try:
                    shot = await client.send("Page.captureScreenshot", {"format": "png"})
                    _save_shot(out_dir, seq, "after", shot["data"])
                except Exception:
                    after_status = "failed"
                # 红框标注：rect × dpr 画框 + 序号，原地覆写双截图
                vp = payload.get("viewport") or {}
                dpr = vp.get("dpr") or 1.0
                rt = (payload.get("rect") or {})
                if rt.get("w"):
                    for ph in ("before", "after"):
                        f = out_dir / "screenshots" / f"{seq:04d}-{ph}.png"
                        if f.exists():
                            annotate(f, rt, dpr=dpr, seq=seq)
                writer.emit("screenshot", {"action_seq": seq, "phase": "before",
                                           "file": f"{seq:04d}-before.png",
                                           "status": before_status})
                writer.emit("screenshot", {"action_seq": seq, "phase": "after",
                                           "file": f"{seq:04d}-after.png",
                                           "status": after_status})
                # 落盘 IO 致命（磁盘满/目录被删）：升级为停止，不再白录
                if writer.fatal:
                    stop_evt.set()

        actions = asyncio.create_task(action_loop())

        # ---- 导航 + 三层停止 ----
        await client.send("Page.navigate", {"url": start_url})
        stop_reason = "browser_closed"
        t_browser = asyncio.create_task(_wait_browser_closed(client))
        t_hotkey = asyncio.create_task(stop_evt.wait())
        t_termq = asyncio.create_task(_wait_terminal_q())
        await asyncio.wait({t_browser, t_hotkey, t_termq},
                           return_when=asyncio.FIRST_COMPLETED)
        for t in (t_browser, t_hotkey, t_termq):
            t.cancel()
        if stop_evt.is_set():
            stop_reason = "hotkey"
        elif (t_termq.done() and not t_termq.cancelled()
              and t_termq.exception() is None and t_termq.result() == "q"):
            stop_reason = "terminal_q"

        # ws 关闭可能早于进程退出，给浏览器最多 2s 收尸再判 abnormal（崩溃/被杀 → 非 0）
        abnormal = False
        if stop_reason == "browser_closed":
            try:
                await asyncio.to_thread(chrome.wait, 2)
            except subprocess.TimeoutExpired:
                pass
            abnormal = chrome.poll() not in (None, 0)

        # 落盘 IO 致命升级为停止原因（action_loop 每轮 + 停止等待完成后双检）
        io_error = None
        if writer.fatal:
            stop_reason = "io_error"
            io_error = "session.jsonl 写入失败（磁盘满/目录被删？），录制中止"

        for t in body_tasks:
            t.cancel()
        await action_q.put(None)
        actions.cancel()
        end_payload = {"abnormal": abnormal, "stop_reason": stop_reason}
        if io_error:
            end_payload["error"] = io_error
        try:
            writer.emit("session_end", end_payload)
        except (OSError, ValueError):
            # 收尾 emit 也可能撞 IO 致命（文件已关/磁盘满）。不置 finished，
            # 但把停止原因改 io_error 后走 return——CLI 侧据 io_error 字段
            # 走 ClickException 分支提示用户，胜过裸异常冒泡。
            stop_reason = "io_error"
            io_error = io_error or "session.jsonl 写入失败（磁盘满/目录被删？），录制中止"
            _copy_prompt_safe(out_dir)
            finished = True
            return {"events": writer.events, "out_dir": str(out_dir), "abnormal": abnormal,
                    "stop_reason": stop_reason, "io_error": io_error}
        _copy_prompt_safe(out_dir)
        finished = True

        return {"events": writer.events, "out_dir": str(out_dir), "abnormal": abnormal,
                "stop_reason": stop_reason, "io_error": io_error}
    finally:
        # Ctrl-C 优雅收尾：asyncio.run 收到 SIGINT 会 cancel 主协程（以
        # CancelledError 形态冒泡，except KeyboardInterrupt 在协程内不命中），
        # 故收尾统一放 finally——正常路径由 finished 标记跳过，中断/异常路径
        # 在此补 session_end(interrupt) + PROMPT.md（emit 亦 try 包住防二次异常）。
        if not finished:
            for t in body_tasks:
                t.cancel()
            if actions is not None:
                actions.cancel()
            try:
                writer.emit("session_end",
                            {"abnormal": True, "stop_reason": "interrupt"})
            except Exception:
                pass
            _copy_prompt_safe(out_dir)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        writer.close()
        if chrome is not None and chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()


def _copy_prompt_safe(out_dir: pathlib.Path) -> None:
    """_copy_prompt 的容错包装：任何异常吞掉（含 KeyboardInterrupt 场景下
    shutil 内部可能的 OSError），不让模板复制失败顶掉/掩盖原始停止路径。"""
    try:
        _copy_prompt(out_dir)
    except Exception:
        pass


def _copy_prompt(out_dir: pathlib.Path) -> bool:
    """PROMPT.md 模板随 session 落盘（供后续 Claude Code 会话生成 guide.md）。

    查找顺序：①开发态（src 布局：recorder.py 在 src/browser_recorder/ 下，
    templates/ 在 src 的上一级即项目根）②wheel 安装态（shared-data 落
    sys.prefix/browser_recorder/templates/，实测 pip/uv 安装均在此）。
    两候选全 miss 时 warning（PROMPT.md 缺失只降级文档生成，不 fatal）。
    """
    here = pathlib.Path(__file__).resolve().parent
    for tmpl in (
        here.parent.parent / "templates" / "PROMPT.md.tmpl",
        pathlib.Path(sys.prefix) / "browser_recorder" / "templates" / "PROMPT.md.tmpl",
    ):
        if tmpl.exists():
            shutil.copy(tmpl, out_dir / "PROMPT.md")
            return True
    log.warning("PROMPT.md template not found")
    return False


async def _wait_devtools(port: int, tries: int = 50, interval: float = 0.1) -> bool:
    """等 /json/list 出现 page target，~5s。"""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as r:
                for t in json.loads(r.read()):
                    if t.get("type") == "page":
                        return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def _wait_browser_closed(client: CDPClient) -> None:
    """ws reader 结束（浏览器关闭/崩溃/被杀）即返回。

    直接 await reader task 会把它变成共享 awaitable：本任务被 cancel 时取消
    会传播进 reader 本体，之后 record() 收尾的 client.close() await 已取消的
    reader 必抛 CancelledError。shield 隔离（hotkey/terminal_q 停止路径）。
    """
    await asyncio.shield(client.wait_closed())


async def _wait_terminal_q() -> str:
    """终端兜底停止：q + 回车。命中返回 "q"。

    实现方式：stdin 是 tty 时起一个 daemon 线程阻塞按行读，命中 "q" 后经
    call_soon_threadsafe 回置 asyncio.Event；stdin 非 tty（pytest 捕获/管道/重定向）
    时永久挂起——不吞管道数据、不在 DontReadFromInput 上抛 OSError，任务由外层
    cancel 收尾。
    """
    loop = asyncio.get_running_loop()
    try:
        stdin = sys.stdin
        if stdin is None or not stdin.isatty():
            await asyncio.sleep(float("inf"))
            return ""
    except (OSError, ValueError):
        await asyncio.sleep(float("inf"))
        return ""

    hit = asyncio.Event()

    def _reader() -> None:
        try:
            while True:
                line = stdin.readline()
                if not line:  # EOF
                    return
                if line.strip() == "q":
                    loop.call_soon_threadsafe(hit.set)
                    return
        except Exception:
            return

    threading.Thread(target=_reader, daemon=True, name="br-terminal-q").start()
    await hit.wait()
    return "q"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _post_body(p: dict):
    req = p.get("request", {})
    return req.get("postData")


async def _fetch_body(client: CDPClient, writer: SessionWriter, request_id: str) -> None:
    try:
        r = await client.send("Network.getResponseBody", {"requestId": request_id}, timeout=5)
        writer.emit("response_body", {
            "request_id": request_id,
            "body": r.get("body", ""),
            "body_base64": r.get("base64Encoded", False),
        })
    except Exception:
        try:
            writer.emit("response_body", {"request_id": request_id, "error": "evicted"})
        except Exception:
            pass  # writer 已关（停止收尾后），不再补写


def _save_shot(out_dir: pathlib.Path, seq: int, phase: str, b64: str) -> None:
    (out_dir / "screenshots" / f"{seq:04d}-{phase}.png").write_bytes(base64.b64decode(b64))
