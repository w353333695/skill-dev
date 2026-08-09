"""录制编排器 — 整合浏览器生命周期与事件管道."""
from __future__ import annotations
import asyncio
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from rich.console import Console

from .models import Action, ActionTag, RequestRecord
from .injector import inject, setup_recorder_callback, flush as injector_flush
from .network import NetworkInterceptor
from .screenshoter import Screenshoter
from .filters import FilterPipeline, InputMergeFilter, DedupFilter
from .handlers import JsonlWriter
from .reporter import MarkdownReporter
from .cleaner import cleanup

console = Console()

# 产物根路径
ARTIFACT_ROOT = Path("/workspace/tmp/.browser-recorder")


class Recorder:
    """录制编排器."""

    def __init__(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        fallback_interval: int = 30,
        req_all: bool = False,
        req_filter: Optional[str] = None,
        keep_all: bool = False,
        max_duration: int = 0,
    ) -> None:
        self.url = url
        self.keep_all = keep_all
        self.max_duration = max_duration

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or (ARTIFACT_ROOT / f"record-{ts}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.fallback_interval = fallback_interval

        # 请求过滤
        self._req_filter: Optional[str] = req_filter
        if req_all:
            self._req_filter = "*"

        # 管道组件
        self.pipeline = FilterPipeline()
        self.pipeline.add(InputMergeFilter())
        self.pipeline.add(DedupFilter())

        self.jsonl_writer = JsonlWriter(self.output_dir)
        self.screenshoter = Screenshoter(self.output_dir)
        self.network_interceptor = NetworkInterceptor(self._req_filter)

        # 状态
        self.actions: list[Action] = []
        self.step_counter = 0
        self.start_time_ms = 0.0
        self._page_map: Dict[str, Page] = {}
        self._page_counter = 0
        self._running = False
        self._fallback_task: Optional[asyncio.Task] = None

    async def run(self) -> Path:
        """启动录制."""
        self._running = True
        self.start_time_ms = time.time() * 1000

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(no_viewport=True)

            # 监听新标签页
            context.on("page", lambda p: asyncio.ensure_future(self._on_new_page(p)))

            page = await context.new_page()
            self._register_page(page, "main")

            # 网络拦截
            await self.network_interceptor.setup(page)

            # 注入录制脚本 + 设置回调
            await self._setup_page(page, "main")

            # 导航到起始 URL
            await self._record_nav(page, self.url)

            # 兜底定时截图
            if self.fallback_interval > 0:
                self._fallback_task = asyncio.ensure_future(
                    self._fallback_loop(page)
                )

            # 等待录制结束
            try:
                while self._running:
                    await asyncio.sleep(0.5)
                    if self.max_duration > 0:
                        elapsed = (time.time() * 1000 - self.start_time_ms) / 1000
                        if elapsed >= self.max_duration:
                            console.print("[yellow]⏰ 达到最大录制时长[/yellow]")
                            break
            except asyncio.CancelledError:
                pass

            if self._fallback_task:
                self._fallback_task.cancel()

            # 最终 flush
            for p in self._page_map.values():
                await injector_flush(p)
            self.jsonl_writer.flush()

            await context.close()
            await browser.close()

        # 生成报告
        return self._finalize()

    async def _setup_page(self, page: Page, page_id: str) -> None:
        """为 page 注入脚本并设置回调."""
        await setup_recorder_callback(page, self._on_events_batch)
        await inject(page, page_id)

        # 弹窗处理
        page.on("dialog", lambda d: asyncio.ensure_future(
            self._on_dialog(d, page, page_id)
        ))

        # 导航 flush
        page.on("framenavigated", lambda f: asyncio.ensure_future(
            self._on_navigate(page, page_id)
        ))

        # 关闭 flush
        page.on("close", lambda: asyncio.ensure_future(
            self._on_page_close(page_id)
        ))

    async def _on_new_page(self, page: Page) -> None:
        """新标签页诞生."""
        self._page_counter += 1
        page_id = f"tab_{self._page_counter}"
        self._register_page(page, page_id)
        await self.network_interceptor.setup(page)
        await self._setup_page(page, page_id)

        # 记录 TAB_OPEN 事件
        self._create_action(
            tag=ActionTag.TAB_OPEN,
            selector=page_id,
            url=page.url,
            page_id=page_id,
            text=f"新标签页 #{page_id}",
        )

    def _register_page(self, page: Page, page_id: str) -> None:
        self._page_map[page_id] = page

    async def _on_events_batch(self, json_str: str) -> None:
        """处理 JS 推送的事件批次."""
        try:
            batch = json.loads(json_str)
        except json.JSONDecodeError:
            return

        for raw in batch:
            processed = self.pipeline.process(raw)
            for ev in processed:
                await self._handle_event(ev)

    async def _handle_event(self, ev: dict) -> None:
        """处理单个事件."""
        tag_str = ev.get("type", "")
        try:
            tag = ActionTag(tag_str)
        except ValueError:
            return

        selector = ev.get("selector", "")
        page_id = ev.get("pageId", "main")
        page = self._page_map.get(page_id)
        if page is None:
            return

        # 构建 Action
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=ev.get("timestamp", time.time() * 1000),
            tag=tag,
            selector=selector,
            tag_name=ev.get("tagName", ""),
            text=ev.get("text"),
            url=ev.get("url", page.url),
            page_id=page_id,
            frame_id=ev.get("frameId"),
            coords=tuple(ev["coords"].values()) if ev.get("coords") else None,
            value=ev.get("value"),
        )

        # 截图（仅 CLICK 类型）
        if tag == ActionTag.CLICK:
            before_path = await self.screenshoter.take_before(
                page, action.step, action.coords
            )
            action.screenshot_before = str(before_path) if before_path else None

            after_path = await self.screenshoter.take_after(page, action.step)
            action.screenshot_after = str(after_path) if after_path else None

        self.actions.append(action)
        self.jsonl_writer.write(action)

    async def _record_nav(self, page: Page, url: str) -> None:
        """记录导航事件 + 截图."""
        await page.goto(url, wait_until="domcontentloaded")
        self.step_counter += 1

        after_path = await self.screenshoter.take_nav_result(page, self.step_counter)

        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.NAV,
            selector="",
            tag_name="",
            url=url,
            page_id="main",
            screenshot_after=str(after_path) if after_path else None,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)

    async def _on_dialog(self, dialog, page: Page, page_id: str) -> None:
        """处理浏览器弹窗."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.DIALOG,
            selector="",
            tag_name=dialog.type,
            text=dialog.message,
            url=page.url,
            page_id=page_id,
            value=dialog.type,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        await dialog.accept()

    async def _on_navigate(self, page: Page, page_id: str) -> None:
        """页面导航时 flush."""
        await injector_flush(page)
        self.pipeline.flush()

    async def _on_page_close(self, page_id: str) -> None:
        """页面关闭."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.TAB_CLOSE,
            selector="",
            tag_name="",
            url="",
            page_id=page_id,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        self._page_map.pop(page_id, None)

    async def _fallback_loop(self, page: Page) -> None:
        """兜底定时截图."""
        while self._running:
            await asyncio.sleep(self.fallback_interval)
            if not self._running:
                break
            self.step_counter += 1
            path = await self.screenshoter.fallback_shot(page, self.step_counter)
            if path:
                action = Action(
                    step=self.step_counter,
                    timestamp_ms=time.time() * 1000,
                    tag=ActionTag.SHOT,
                    selector="",
                    tag_name="",
                    url=page.url,
                    page_id="main",
                    screenshot_after=str(path),
                )
                self.actions.append(action)
                self.jsonl_writer.write(action)

    def _create_action(self, **kwargs) -> Action:
        """创建 action 并递增计数器."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            **kwargs,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        return action

    def _finalize(self) -> Path:
        """生成报告 + 保存请求 + 清理."""
        # 保存 requests.json
        requests = self.network_interceptor.requests
        import json as _json
        from dataclasses import asdict

        req_path = self.output_dir / "requests.json"
        req_list = []
        for r in requests:
            d = asdict(r)
            req_list.append(d)
        req_path.write_text(_json.dumps(req_list, ensure_ascii=False, indent=2), encoding="utf-8")

        # 生成 record.md
        reporter = MarkdownReporter()
        reporter.generate(self.actions, requests, self.output_dir)

        # 清理
        cleanup(self.output_dir, keep_all=self.keep_all)

        console.print(f"\n[bold green]✅[/bold green] 录制完成: {self.output_dir}")
        console.print(f"   报告: {self.output_dir / 'record.md'}")
        console.print(f"   请求: {self.output_dir / 'requests.json'}")

        return self.output_dir
