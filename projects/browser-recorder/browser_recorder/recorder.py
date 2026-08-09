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

    # ---------- 对外接口 ----------

    def run(self) -> Path:
        """阻塞录制（交互式），返回 session 目录。人操作浏览器，stop() 或关浏览器结束。"""
        self.start()
        page = self.page
        owned = self._owned

        page.on("close", lambda _: self._stop.set())
        stop_at: float | None = None
        while True:
            try:
                page.evaluate("1", timeout=2000)
            except Exception:
                pass
            self.drain()
            if owned and not self._context.pages:
                break
            if self._stop.is_set():
                if stop_at is None:
                    stop_at = time.monotonic() + 2.0  # stop 后再泵 2 秒收在途事件
                elif time.monotonic() >= stop_at:
                    break
            time.sleep(0.3)
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
        self._wire_context(context)

        page = context.pages[0] if context.pages else context.new_page()
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
        try:
            self._dpr = page.evaluate("window.devicePixelRatio || 1")
        except Exception:
            self._dpr = 1.0

    @property
    def page(self):
        return self._page

    def drain(self) -> None:
        """连接线程：处理缓冲的操作事件（截图+写盘）。请求记录走 route 即时写，无需 drain。"""
        self._drain_events()

    def finish(self) -> Path:
        """收尾：最后 drain、关闭资源、生成 doc.md。"""
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

    def _drain_events(self) -> int:
        """连接线程：从 buffer 取出事件，截图 + 写 record.jsonl。返回处理条数。"""
        n = 0
        while self._event_buffer:
            step = self._event_buffer.pop(0)
            if step.type == "click":
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
        # 截图用最近活跃 page；多 tab 场景取最后一个
        try:
            pages = self._context.pages
            return pages[-1] if pages else None
        except Exception:
            return None

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
