"""会话壳：三种主循环（record/drive/probe）共用的浏览器会话基座。

从 record() 平移（纯搬运）：拉浏览器、browser-level CDP 连接、
Target.setAutoAttach flatten 模式、每个打开的 tab（page target）各成一个
子会话：Network/Page/Runtime 三域 + 注入采集脚本 → 事件流落盘（writer，带
target_id）→ 双截图（before 即拍 + after 等稳补拍）、稳定等待、flush_inputs。
模态专属的停止协调/收尾判定（三层停止、abnormal、io_error）不在这——留在
各自主循环（record 的收尾与 drive 跑完 steps 主动收尾不同）。
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

RESP_LOG_MAX = 200  # resp_log 滑动窗口上限（T8 断言用：url/status/时刻）


class StableState:
    """网络空闲 ∧ DOM 静默 500ms 的稳定判定状态（跨所有 tab 全局合计）。"""

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


class _TabSession:
    """一个 page target 的录制子会话：sessionId + 短 target_id + 事件处理注册。"""

    def __init__(self, sid: str, tid: str, url: str):
        self.sid = sid          # CDP flatten sessionId
        self.tid = tid          # 落盘短 id（"t0"/"t1"…）
        self.url = url          # 打开时的初始 URL（targetInfo.url）
        self.closed = False


class SessionHarness:
    """record/drive/probe 共用的会话壳：async with 即完整会话建立与优雅收尾。

    构造签名与 record() 一致（out_dir/start_url/chrome_path/settle_timeout/
    port/headless/extra_chrome_args/profile）。进入 = 起浏览器→挂域→注入→
    首导航完成；退出 = Browser.close 优雅链 + writer.close + interrupt 兜底。
    """

    def __init__(self, out_dir: pathlib.Path, start_url: str,
                 chrome_path: pathlib.Path, settle_timeout: float = 30.0,
                 port: int | None = None, headless: bool = False,
                 extra_chrome_args: list[str] | None = None,
                 profile: str | None = None):
        self.out_dir = pathlib.Path(out_dir)
        self.start_url = start_url
        self.chrome_path = chrome_path
        self.settle_timeout = settle_timeout
        self.port = port or _free_port()
        self.headless = headless
        self.extra_chrome_args = extra_chrome_args
        self.profile = profile

        self.writer = SessionWriter(self.out_dir)
        self.state = StableState()
        self.stop_event = asyncio.Event()
        self.hotkey_fired = False  # control_stop binding 命中（hotkey 停止路径）
        self.action_q: asyncio.Queue = asyncio.Queue()  # 注入上报 → action_loop（双截图）
        self.body_tasks: set[asyncio.Task] = set()      # 在途 getResponseBody 抓取
        self.tabs: dict[str, _TabSession] = {}          # sessionId -> tab（emit 侧查 tid）
        self.resp_log: list[dict] = []                  # 响应流水（滑动窗口，T8 断言用）
        self.chrome: subprocess.Popen | None = None  # Popen 失败（chrome_path 无效）也要能收尾关 writer
        self.client: CDPClient | None = None
        self.action_loop_task: asyncio.Task | None = None

        if profile:
            user_data = pathlib.Path.home() / ".browser-recorder" / "profiles" / profile
            user_data.mkdir(parents=True, exist_ok=True)
        else:
            user_data = self.out_dir / "chrome-profile"  # 一次性，随 session 目录走
        self.user_data = user_data

    # ---- 进入/退出 ----

    async def __aenter__(self) -> "SessionHarness":
        try:
            await self._start()
            return self
        except BaseException as e:
            # 建立期失败（Popen 无效/devtools 未就绪/autoAttach 超时）：async with
            # 语义下 __aexit__ 不会被执行（body 未进入），在此自调——否则 writer
            # 不关、chrome 进程泄漏（原 record() 的 finally 保证过这两件事）。
            await self.__aexit__(type(e), e, e.__traceback__)
            raise

    async def _start(self) -> None:
        args = [
            str(self.chrome_path),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data}",
            "--no-first-run", "--no-default-browser-check",
            "--window-size=1280,900",
            # headless 下动画/transform 进场的弹层可能停在 0×0（渲染依赖合成器），
            # 声明 reduced-motion 让组件直接落在终态；录制截图也更干净
            "--force-prefers-reduced-motion",
            "about:blank",
        ]
        if self.headless:
            args.append("--headless=new")
        args.extend(self.extra_chrome_args or [])
        self.chrome = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        if not await _wait_devtools(self.port):
            raise RuntimeError(
                "浏览器 devtools 端口未就绪（检查 DISPLAY/端口占用，可用 port= 换端口）")
        self.client = await CDPClient.connect_browser(self.port)

        self.writer.emit("session_start", {"url": self.start_url, "ts": time.time(),
                                           "chrome": str(self.chrome_path),
                                           "pid": self.chrome.pid})

        # ---- 每个 tab 子会话的域挂载 + 事件注册 ----
        self._first_tab_ready = asyncio.Event()   # 首个 tab 挂域完成（导航同步点）
        self._seen_target_ids: set[str] = set()   # 同一 target 重复 attach 去重（浏览器
        # 有时对同一 page target 发两次 attachedToTarget——autoAttach 与已有
        # session 并存时；第二次的 sessionId 事件会重复，丢弃）

        # ---- browser 级：target 生命周期 ----
        def on_attached(p):
            info = p.get("targetInfo", {})
            target_id = info.get("targetId", "")
            if target_id and target_id in self._seen_target_ids:
                return  # 同一 target 的重复 attach： sessionId 已在录，丢弃
            if target_id:
                self._seen_target_ids.add(target_id)
            if info.get("type") != "page":
                # iframe/worker 等非 page target：记录但不挂域（iframe 操作经页面
                # 注入已覆盖；worker 无 DOM）。MVP 不展开。
                self.writer.emit("note", {"text": f"non-page target attached: {info.get('type')}",
                                          "target": target_id})
                return
            attach_task = asyncio.get_running_loop().create_task(
                self._attach_tab(p["sessionId"], info))
            self.body_tasks.add(attach_task)

            def _attach_done(t: asyncio.Task) -> None:
                self.body_tasks.discard(t)
                if not t.cancelled() and t.exception() is not None:
                    log.error("attach_tab 失败: %s", t.exception(), exc_info=t.exception())
            attach_task.add_done_callback(_attach_done)
        self.client.on("Target.attachedToTarget", on_attached)

        # targetDestroyed 只给 targetId；flatten session 事件随连接摘除自然静默。
        # tab 关闭的可见性由事件断流体现，MVP 记一条 note 供 LLM 推断。
        self.client.on("Target.targetDestroyed",
                       lambda p: self.writer.emit("note", {"text": "tab closed",
                                                          "target": p.get("targetId", "")}))

        # ---- 自动附加（flatten）：已开的 tab + 用户后续新开的 tab ----
        await self.client.send("Target.setAutoAttach", {
            "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})

        # ---- 动作处理协程：before 即拍（队列不积压）+ after 异步补拍 ----
        # 旧实现：before→settle→after 串行阻塞队列——用户连续操作时截图滞后
        # 数秒（真机实测 1.3~5.3s），页面早变样，图全错位。新结构：
        #   action_loop 只做 emit + before（毫秒级），after 交给独立任务等稳再拍。
        self.action_loop_task = asyncio.create_task(self._action_loop())

        # ---- 启动 tab 导航 ----
        # autoAttach 后首个 attachedToTarget 即启动 tab；挂域完成（含
        # Network.enable 落地）再导航，否则初始请求/导航事件丢失。
        try:
            await asyncio.wait_for(self._first_tab_ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            raise RuntimeError("启动 tab 未附加（autoAttach 未生效）")
        first_sid = next(iter(self.tabs), None)  # first_tab_ready 保证非空
        await self.client.send("Page.navigate", {"url": self.start_url},
                               session_id=first_sid)

    async def __aexit__(self, exc_type, exc, tb):
        # 主循环带异常/取消退出（interrupt 路径）：先补 session_end(interrupt)
        # （emit 必须在 writer.close 前），再走优雅关闭链。
        if exc_type is not None:
            for t in self.body_tasks:
                t.cancel()
            if self.action_loop_task is not None:
                self.action_loop_task.cancel()
            try:
                self.writer.emit("session_end",
                                 {"abnormal": True, "stop_reason": "interrupt"})
            except Exception:
                pass
            _copy_prompt_safe(self.out_dir)
        # 优雅关闭：CDP Browser.close 走 Chrome 完整 shutdown——session
        # cookie（无过期时间的登录态）只在完整退出时落盘。SIGTERM 是立即
        # 死，session cookie 全丢（持久 profile 免登录失效的根因）。
        if self.client is not None:
            try:
                await self.client.send("Browser.close", timeout=5)
            except Exception:
                pass
            try:
                await self.client.close()
            except Exception:
                pass
        self.writer.close()
        if self.chrome is not None and self.chrome.poll() is None:
            # Browser.close 未及生效（连接已断/超时）时兜底 terminate → kill
            self.chrome.terminate()
            try:
                self.chrome.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.chrome.kill()

    # ---- 主循环可用的原语 ----

    def tid_of(self, sid: str) -> str:
        t = self.tabs.get(sid)
        return t.tid if t else "?"

    def tid_sid(self, tid: str) -> str | None:
        """按落盘短 id 查 CDP sessionId（drive 派发动作定向 tab 用）。"""
        t = next((t for t in self.tabs.values() if t.tid == tid), None)
        return t.sid if t else None

    async def wait_stable(self, timeout: float | None = None) -> str:
        return await wait_stable(self.state,
                                 self.settle_timeout if timeout is None else timeout)

    async def navigate(self, url: str, tid: str = "t0") -> None:
        await self.client.send("Page.navigate", {"url": url},
                               session_id=self.tid_sid(tid))

    async def emit_action(self, payload: dict) -> int:
        """动作落盘 + before 即拍 + 红框标注 + screenshot 事件（原 action_loop 内段）。

        drive 模态的机器动作直接走这里（不经 action_q）；record 模态的注入
        上报仍经 action_q 由 _action_loop 调本方法。payload 带 target_id。
        """
        tid = payload.get("target_id")
        sid = next((t.sid for t in self.tabs.values() if t.tid == tid), None)
        seq = self.writer.emit("action", {
            "type": payload["type"],
            "element": {"rect": payload.get("rect"),
                        "viewport": payload.get("viewport"),
                        "descriptor": payload.get("descriptor")},
            "value": payload.get("value"), "html_type": payload.get("html_type"),
            "target_id": tid,
            "before_shot": None, "after_shot": None,
        })
        # before：立即截（此刻页面=动作刚发生的现场）
        before_status = "ok"
        try:
            shot = await self.client.send("Page.captureScreenshot", {"format": "png"},
                                          session_id=sid)
            _save_shot(self.out_dir, seq, "before", shot["data"])
        except Exception:
            before_status = "raced"
        # 红框标注（零尺寸跳过，descriptor 文字兜底）
        vp = payload.get("viewport") or {}
        dpr = vp.get("dpr") or 1.0
        rt = (payload.get("rect") or {})
        if rt.get("w") and rt.get("h") and before_status == "ok":
            _annotate_safe(self.out_dir, seq, "before", rt, dpr)
        self.writer.emit("screenshot", {"action_seq": seq, "phase": "before",
                                        "file": f"{seq:04d}-before.png",
                                        "status": before_status, "target_id": tid})
        # after：独立任务等稳再拍——不阻塞下一个动作的 before
        self.schedule_after_shot(seq, tid, rt, dpr)
        return seq

    def schedule_after_shot(self, seq: int, tid, rt: dict, dpr: float) -> None:
        """after 异步补拍（原 after_shot 协程）：等稳再拍，不阻塞下一动作。"""
        t_after = asyncio.get_running_loop().create_task(
            self._after_shot(seq, tid, rt, dpr))
        self.body_tasks.add(t_after)
        t_after.add_done_callback(self.body_tasks.discard)

    async def flush_inputs(self) -> None:
        """冲刷各 tab 挂起中的输入聚合（Browser.close 不走页面 unload，
        未满 1.2s 聚合窗的最后一段输入会丢）。"""
        for tab in list(self.tabs.values()):
            try:
                await self.client.send("Runtime.evaluate",
                                       {"expression": "window.__brFlush && window.__brFlush()"},
                                       session_id=tab.sid)
            except Exception:
                pass  # tab 已关/导航中：beforeunload 已兜底或输入本就已落

    def copy_prompt(self) -> None:
        _copy_prompt_safe(self.out_dir)

    def mark_interrupted(self) -> None:
        """中断/异常路径的补收尾：cancel 在途任务 + session_end(interrupt) + PROMPT.md。"""
        for t in self.body_tasks:
            t.cancel()
        if self.action_loop_task is not None:
            self.action_loop_task.cancel()
        try:
            self.writer.emit("session_end",
                             {"abnormal": True, "stop_reason": "interrupt"})
        except Exception:
            pass
        _copy_prompt_safe(self.out_dir)

    # ---- 内部：从 record() 平移 ----

    async def _after_shot(self, seq: int, tid, rt, dpr: float) -> None:
        sid = next((t.sid for t in self.tabs.values() if t.tid == tid), None)
        how = await wait_stable(self.state, self.settle_timeout)
        try:
            shot = await self.client.send("Page.captureScreenshot", {"format": "png"},
                                          session_id=sid)
            _save_shot(self.out_dir, seq, "after", shot["data"])
            _annotate_safe(self.out_dir, seq, "after", rt, dpr)
            self.writer.emit("screenshot", {"action_seq": seq, "phase": "after",
                                            "file": f"{seq:04d}-after.png",
                                            "status": how, "target_id": tid})
        except Exception:
            self.writer.emit("screenshot", {"action_seq": seq, "phase": "after",
                                            "file": f"{seq:04d}-after.png",
                                            "status": "failed", "target_id": tid})

    async def _action_loop(self) -> None:
        while True:
            payload = await self.action_q.get()
            if payload is None:
                break
            await self.emit_action(payload)
            # 落盘 IO 致命（磁盘满/目录被删）：升级为停止，不再白录
            if self.writer.fatal:
                self.stop_event.set()

    async def _attach_tab(self, sid: str, target_info: dict) -> None:
        tid = f"t{len(self.tabs)}"
        tab = _TabSession(sid, tid, target_info.get("url", ""))
        self.tabs[sid] = tab
        # 放行必须最先：waitForDebuggerOnStart 冻结的 target 上，域启用类
        # 命令（Network.enable 等）会阻塞不返回——先挂域再放行 = 死锁
        # （popup 冻在 about:blank 永不加载；真机有头则表现为注入时机全乱、
        # 新 tab 有请求无动作）。放行后再挂域，代价只是新 tab 最初
        # 数百毫秒的请求可能漏录，远优于死锁。
        try:
            await self.client.send("Runtime.runIfWaitingForDebugger",
                                  session_id=sid, timeout=3)
        except Exception:
            pass  # 未冻结的 target 会报错——无害，继续挂域
        await self.client.send("Network.enable", session_id=sid)
        await self.client.send("Page.enable", session_id=sid)
        await self.client.send("Runtime.enable", session_id=sid)
        await self.client.send("Runtime.addBinding", {"name": "__brEvent"}, session_id=sid)
        await self.client.send("Page.addScriptToEvaluateOnNewDocument",
                              {"source": INJECT_JS}, session_id=sid)
        await self.client.send("Runtime.evaluate", {"expression": INJECT_JS}, session_id=sid)
        # 新 tab 若在挂域前已加载（浏览器未按 waitForDebugger 冻结），nav 事件
        # 已错过——用导航历史回填，保证事件流可见该 tab 的当前页面。
        # 首个 tab 不回填（起点 about:blank 无信息量，导航由下方 Page.navigate
        # 主动发起不丢）。
        if len(self.tabs) > 1:
            try:
                hist = await self.client.send("Page.getNavigationHistory", session_id=sid)
                idx = hist.get("currentIndex", 0)
                entries = hist.get("entries", [])
                if entries and idx < len(entries):
                    cur = entries[idx]
                    self.writer.emit("nav", {"url": cur.get("url", ""), "title": "",
                                             "target_id": tid,
                                             "recovered": True})
            except Exception:
                pass  # 导航历史回填失败不影响主流程
        if len(self.tabs) == 1:
            self._first_tab_ready.set()

        def on_req(p, _sid=sid):
            if "redirectResponse" in p:
                # 重定向跳复用同一 requestId 且无对应 responseReceived，
                # 再计 in-flight 会永久 +1 → wait_stable 必走满 timeout。
                # 只跳过记账，request 事件仍落盘（重定向 hop 不丢）。
                pass
            else:
                self.state.net_open(p["requestId"], p.get("request", {}).get("url", ""))
            self.writer.emit("request", {
                "request_id": p["requestId"], "method": p.get("request", {}).get("method"),
                "url": p.get("request", {}).get("url"),
                "headers": p.get("request", {}).get("headers"),
                "post_body": _post_body(p), "initiator": p.get("initiator", {}).get("type"),
                "target_id": self.tid_of(_sid),
            })
        self.client.on("Network.requestWillBeSent", on_req, session_id=sid)

        def on_resp(p, _sid=sid):
            self.state.net_close(p["requestId"])
            self.writer.emit("response", {
                "request_id": p["requestId"], "status": p["response"].get("status"),
                "mime": p["response"].get("mimeType"),
                "headers": p["response"].get("headers"),
                "size": p["response"].get("encodedDataLength"),
                "target_id": self.tid_of(_sid),
            })
            # 响应流水（T8 断言用）：滑动窗口，不随会话时长无界增长
            self.resp_log.append({"url": p.get("response", {}).get("url", ""),
                                  "status": p["response"].get("status"),
                                  "t": time.monotonic_ns() // 1_000_000})
            if len(self.resp_log) > RESP_LOG_MAX:
                del self.resp_log[:len(self.resp_log) - RESP_LOG_MAX]
            t = asyncio.get_running_loop().create_task(
                _fetch_body(self.client, self.writer, p["requestId"], _sid))
            self.body_tasks.add(t)
            t.add_done_callback(self.body_tasks.discard)
        self.client.on("Network.responseReceived", on_resp, session_id=sid)

        def on_loading_fail(p, _sid=sid):
            self.state.net_close(p["requestId"])
        self.client.on("Network.loadingFailed", on_loading_fail, session_id=sid)

        def _on_ws_frame(p, _sid=sid, _dir=""):
            # ws 帧不进 StableState 记账（长连接已在 net_open 排除，帧不算新请求）
            # sent/received 参数结构相同：帧数据都在 response.payloadData
            # （CDP 历史命名，sent 也是 response 字段），统一取法不分支。
            d = p.get("response", {}).get("payloadData", "")
            self.writer.emit("ws_frame", {
                "request_id": p.get("requestId"), "direction": _dir,
                "payload": d, "payload_base64": False,
                "target_id": self.tid_of(_sid),
            })
        self.client.on("Network.webSocketFrameSent",
                       lambda p, _sid=sid: _on_ws_frame(p, _sid, "sent"), session_id=sid)
        self.client.on("Network.webSocketFrameReceived",
                       lambda p, _sid=sid: _on_ws_frame(p, _sid, "received"), session_id=sid)

        def on_nav(p, _sid=sid):
            if p.get("frame", {}).get("parentId") is None:  # 主 frame
                self.writer.emit("nav", {"url": p.get("frame", {}).get("url", ""), "title": "",
                                         "target_id": self.tid_of(_sid)})
                # 补注：新 tab 的注入常错过文档创建期（autoAttach 的
                # waitForDebuggerOnStart 不被 window.open 场景遵守，页面在
                # attach_tab 挂 addScriptToEvaluateOnNewDocument 前已开始
                # 加载——attach 时 evaluate 跑在旧文档，导航后监听器全丢，
                # 症状：新 tab 只有 request/nav、无 action/dom_mutations）。
                # 每次主 frame 导航后重 evaluate（注入有 __brInstalled 哨兵，
                # 重复执行无害），双保险。
                async def _reinject():
                    await asyncio.sleep(0.3)  # 等新文档执行上下文就绪
                    try:
                        await self.client.send("Runtime.evaluate",
                                               {"expression": INJECT_JS}, session_id=_sid)
                    except Exception:
                        pass
                asyncio.get_running_loop().create_task(_reinject())
        self.client.on("Page.frameNavigated", on_nav, session_id=sid)

        def on_binding(p, _sid=sid):
            if p.get("name") != "__brEvent":
                return
            try:
                payload = json.loads(p["payload"])
            except (json.JSONDecodeError, KeyError):
                return
            payload["target_id"] = self.tid_of(_sid)  # 动作归属 tab
            t = payload.get("type")
            if t == "control_stop":
                self.writer.emit("control_stop", {"target_id": payload["target_id"]})
                self.hotkey_fired = True
                self.stop_event.set()
            elif t == "dom_mutations":
                self.state.mark_mutation()
                self.writer.emit("dom_mutations", {"count": payload.get("count", 0),
                                                   "target_id": payload["target_id"]})
            elif t in ACTION_TYPES:
                self.action_q.put_nowait(payload)
        self.client.on("Runtime.bindingCalled", on_binding, session_id=sid)


def _copy_prompt_safe(out_dir: pathlib.Path) -> None:
    """_copy_prompt 的容错包装：任何异常吞掉（含 KeyboardInterrupt 场景下
    shutil 内部可能的 OSError），不让模板复制失败顶掉/掩盖原始停止路径。"""
    try:
        _copy_prompt(out_dir)
    except Exception:
        pass


def _copy_prompt(out_dir: pathlib.Path) -> bool:
    """PROMPT.md 模板随 session 落盘（供后续 Claude Code 会话生成 guide.md）。

    查找顺序：①开发态（src 布局：harness.py 在 src/browser_recorder/ 下，
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


async def _fetch_body(client: CDPClient, writer: SessionWriter, request_id: str,
                      sid: str | None = None) -> None:
    try:
        r = await client.send("Network.getResponseBody", {"requestId": request_id},
                              timeout=5, session_id=sid)
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


def _annotate_safe(out_dir: pathlib.Path, seq: int, phase: str,
                   rt: dict, dpr: float) -> None:
    """红框标注（容错）：文件不存在/画框异常都吞掉——标注失败只降级观感，不致命。"""
    try:
        f = out_dir / "screenshots" / f"{seq:04d}-{phase}.png"
        if f.exists() and rt.get("w") and rt.get("h"):
            annotate(f, rt, dpr=dpr, seq=seq)
    except Exception:
        pass
