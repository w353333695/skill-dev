"""录制器：headed launch / CDP attach 两条接入路径，事件回调主循环。"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, docgen, inject, screenshots
from .models import SelectorSet, SessionMeta, StepEvent


class Recorder:
    """录制一次浏览器会话。

    - url 模式：launch(headless=False) 新开浏览器
    - cdp 模式：connect_over_cdp attach 已开浏览器（install 后 goto 一次强制注入）
    录制期间阻塞，stop() 或浏览器关闭结束；结束后 flush 并生成 doc.md。
    """

    def __init__(
        self,
        url: str | None = None,
        cdp: str | None = None,
        use_auth: bool = True,
        output_root: str = ".browser-recorder/sessions",
        video: bool = False,
        headless: bool = False,
        username: str | None = None,
        password: str | None = None,
        ignore_https_errors: bool = False,
    ):
        self.url = url
        self.cdp = cdp
        self.use_auth = use_auth
        self.video = video
        self.headless = headless
        self.username = username
        self.password = password
        self.ignore_https_errors = ignore_https_errors
        self.output_root = Path(output_root)

        self._stop = threading.Event()
        self._seq = 0
        self._seen_ids: set[str] = set()
        self._record_fp = None
        self.session_dir: Path | None = None
        self._context = None
        self._interrupted = False

    # ---------- 对外接口 ----------

    def run(self) -> Path:
        """阻塞录制（交互式），返回 session 目录。人操作浏览器，stop() 或关浏览器结束。"""
        self.start()
        page = self.page
        owned = self._owned

        page.on("close", lambda _: self._stop.set())
        # 关整个浏览器/最后一个标签也要退出：page.close 之外再兜 context/browser 层
        try:
            self._context.on("close", lambda _: self._stop.set())
        except Exception:
            pass
        stop_at: float | None = None
        eval_failures = 0
        try:
            while True:
                try:
                    page.evaluate("1", timeout=2000)
                    eval_failures = 0
                except Exception:
                    # 浏览器/页面已关：evaluate 立即抛 TargetClosedError。
                    # 连续失败即认定连接已断，退出（不依赖 context.pages——
                    # context 关闭后访问它可能悬挂或抛错）。
                    eval_failures += 1
                    if eval_failures >= 3:
                        break
                self.drain()
                if self._stop.is_set():
                    if stop_at is None:
                        stop_at = time.monotonic() + 2.0  # stop 后再泵 2 秒收在途事件
                    elif time.monotonic() >= stop_at:
                        break
                time.sleep(0.3)
        except KeyboardInterrupt:
            # Ctrl+C：不直接退出，照常走 finish 保证 record.jsonl flush + doc.md 生成。
            # 标记中断，finish 里跳过一次 CDP 截图（此时 driver 可能已在关闭，
            # 再发 CDP 调用会报 pipe closed / Connection closed 噪音）。
            self._interrupted = True
        return self.finish()

    def start(self) -> None:
        """装配录制环境（launch/attach + goto + 注入），返回后 self.page 可用。"""
        from playwright.sync_api import sync_playwright

        self.session_dir = self._make_session_dir()
        (self.session_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        self._record_fp = open(self.session_dir / "record.jsonl", "a", encoding="utf-8")

        self._pw = sync_playwright().start()
        p = self._pw
        if self.cdp:
            browser = p.chromium.connect_over_cdp(self.cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            owned = False
        else:
            kwargs = {"ignore_https_errors": self.ignore_https_errors}
            if self.video:
                kwargs["record_video_dir"] = str(self.session_dir / "video")
            storage_state = None
            if self.use_auth and self.url:
                from .auth import AuthManager

                self._auth = AuthManager()
                if self._auth.has_state(self.url):
                    storage_state = str(self._auth.state_path(self.url))
                if storage_state:
                    kwargs["storage_state"] = storage_state
            launch_args = ["--ignore-certificate-errors"] if self.ignore_https_errors else []
            browser = p.chromium.launch(headless=self.headless, args=launch_args)
            context = browser.new_context(**kwargs)
            owned = True

        self._browser = browser
        self._owned = owned
        # launch 模式：先建 page 再 wire，保证 __recordEvent 同步挂到已存在的 page。
        # （若先 wire 再 new_page，binding 靠 context.on("page") 异步补挂，goto 时
        #   init script 调用桥可能早于注册完成，导致事件丢失——实测 launch 模式录不到。）
        page = context.pages[0] if context.pages else context.new_page()
        self._wire_context(context)

        start_url = self.url or page.url or "about:blank"
        if self.cdp and not self.url:
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
        elif start_url != "about:blank":
            page.goto(start_url, wait_until="domcontentloaded")

        if page.url and page.url != "about:blank":
            self._write_step(StepEvent(seq=self._next_seq(), type="navigate", value=page.url, url=page.url))

        if owned and self.use_auth and self.url and getattr(self, "_auth", None):
            # SPA 站点（如 easyops）goto 后需等 JS 加载才到登录页/落地页
            page.wait_for_timeout(3000)
            self._auth.ensure_valid(context, page, self.url,
                                    username=self.username, password=self.password)
            # 自动登录可能引发二次导航，重新记录落地页
            if self.username and self.password and page.url != start_url:
                self._drain_events()  # 先收下登录过程产生的事件
                self._write_step(StepEvent(seq=self._next_seq(), type="navigate", value=page.url, url=page.url))

        self._save_meta(context, page)
        self._page = page
        self._install_targetclosed_filter(page)
        try:
            self._dpr = page.evaluate("window.devicePixelRatio || 1")
        except Exception:
            self._dpr = 1.0

    # 关闭阶段（Ctrl+C/关浏览器/连接断开）残留的 CDP future 噪音关键词
    _CLOSED_NOISE = ("TargetClosedError", "has been closed", "Connection closed",
                     "pipe closed by peer", "closed while reading from the driver")

    @staticmethod
    def _install_targetclosed_filter(page) -> None:
        """给 playwright 的 asyncio loop 装异常钩子，吞掉关闭阶段的无害 future 警告。

        Ctrl+C / 关浏览器后，事件循环里残留的 Channel.send / response.body / 泵 evaluate
        等 future 撞上已关闭的 target/driver；asyncio 在 future 被 GC 时经
        call_exception_handler 打 "Future/Task exception was never retrieved"（
        TargetClosedError / Connection closed / pipe closed by peer 等）。这些发生在
        连接已正常关闭之后，纯属噪音。钩子在 start 即挂上，覆盖整个录制+关闭期。
        """
        try:
            loop = page._impl_obj._loop
            old_handler = loop.get_exception_handler()

            def handler(loop, context):
                exc = context.get("exception")
                text = f"{exc} {context.get('message', '')}"
                if any(k in text for k in Recorder._CLOSED_NOISE):
                    return  # 静默
                if old_handler:
                    old_handler(loop, context)
                else:
                    loop.default_exception_handler(context)

            loop.set_exception_handler(handler)
        except Exception:
            pass

    @property
    def page(self):
        return self._page

    def drain(self) -> None:
        """连接线程：处理缓冲的操作事件（截图+写盘）。请求记录走 route 即时写，无需 drain。"""
        self._drain_events()

    def finish(self) -> Path:
        """收尾：最后 drain、关闭资源、生成 doc.md。

        Ctrl+C 中断时 driver 可能已在关闭，跳过 drain 里的 CDP 截图（避免
        pipe closed / Connection closed 噪音），仅做文件级收尾。
        """
        if self._interrupted:
            self._drain_events(skip_screenshot=True)
        else:
            self.drain()
        self._record_fp.close()
        self._request_logger.close()
        if self._owned:
            try:
                self._context.close()
                self._browser.close()
            except Exception:
                pass
        try:
            self._pw.stop()
        except Exception:
            pass
        docgen.generate(self.session_dir)
        return self.session_dir

    def stop(self) -> None:
        self._stop.set()

    # ---------- 内部 ----------

    def _make_session_dir(self) -> Path:
        host = "cdp"
        if self.url:
            host = re.sub(r"[^\w.-]", "_", urlparse(self.url).netloc or "page")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_root / f"{ts}_{host}"
        # 同一秒内重复时加后缀
        n = 1
        while path.exists():
            n += 1
            path = self.output_root / f"{ts}_{host}_{n}"
        return path

    def _wire_context(self, context) -> None:
        inject.install(context, self._on_event)
        from .requests_log import RequestLogger

        self._request_logger = RequestLogger(self.session_dir, lambda: self._seq)
        self._request_logger.attach_context(context)

        self._event_buffer: list[StepEvent] = []

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _write_step(self, step: StepEvent) -> None:
        self._record_fp.write(step.dumps() + "\n")
        self._record_fp.flush()

    def _on_event(self, payload: dict) -> None:
        """注入 JS 桥回调（CDP 事件线程）——只做去重/编号/纯内存 append。

        禁止在此做任何阻塞操作（queue.put / 锁竞争 / CDP 调用），
        否则 CDP attach 场景下 binding 回调会被整体饿死。
        """
        event_id = payload.get("id")
        if event_id and event_id in self._seen_ids:
            return
        if event_id:
            self._seen_ids.add(event_id)
        self._seq += 1

        self._event_buffer.append(StepEvent(
            seq=self._seq,
            type=payload.get("type", "unknown"),
            url=payload.get("url"),
            selectors=SelectorSet.from_dict(payload.get("selectors")),
            label=payload.get("label"),
            value=payload.get("value"),
            sensitive=bool(payload.get("sensitive")),
            point=payload.get("point"),
        ))

    def _drain_events(self, skip_screenshot: bool = False) -> int:
        """连接线程：从 buffer 取出事件，截图 + 写 record.jsonl。返回处理条数。

        skip_screenshot=True 用于 Ctrl+C 中断收尾（driver 可能在关闭，不再发 CDP）。
        """
        n = 0
        while self._event_buffer:
            step = self._event_buffer.pop(0)
            if step.type == "click" and not skip_screenshot:
                shot_rel = f"screenshots/step-{step.seq:03d}.png"
                page = self._current_page()
                if page and self._safe_capture(page, shot_rel, step):
                    step.screenshot = shot_rel
            self._write_step(step)
            n += 1
        return n

    def _safe_capture(self, page, shot_rel: str, step) -> bool:
        """截图，screenshot 带超时；导航/页面繁忙导致悬挂时 playwright 抛错，放弃该图。
        页面已导航时截的是新页面（对文档仍有参考），不强制跳过。"""
        try:
            png = page.screenshot(timeout=3000)
            path = self.session_dir / shot_rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(screenshots.annotate(png, step.point, step.seq, self._dpr))
            return True
        except Exception:
            return False

    def _current_page(self):
        # 截图用主页面。不用 context.pages（context 关闭后访问会悬挂），
        # 直接用 start 时缓存的 page 引用。
        return self._page

    def _save_meta(self, context, page) -> None:
        self._context = context
        auth_file = None
        if getattr(self, "_auth", None) and self.url and self._auth.has_state(self.url):
            auth_file = str(self._auth.state_path(self.url))
        SessionMeta(
            session_id=self.session_dir.name,
            url=self.url or (page.url if page else None),
            mode="cdp" if self.cdp else "launch",
            auth_file=auth_file,
            user_agent=page.evaluate("navigator.userAgent") if page else None,
            version=__version__,
        ).save(self.session_dir)
