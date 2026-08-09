"""回放引擎 — 读取 events.jsonl 在新浏览器中自动执行."""
from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Page
from rich.console import Console

from .models import Action, ActionTag
from .injector import inject
from .screenshoter import Screenshoter
from .reporter import MarkdownReporter
from .cleaner import cleanup

console = Console()

ARTIFACT_ROOT = Path("./browser-recorder")


class ReplayEngine:
    """事件回放引擎."""

    def __init__(
        self,
        events_path: Path,
        speed: float = 1.0,
        repeat: int = 1,
        output_dir: Optional[Path] = None,
        keep_all: bool = False,
    ) -> None:
        self.events_path = Path(events_path)
        self.speed = speed
        self.repeat = repeat
        self.keep_all = keep_all

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or (ARTIFACT_ROOT / f"replay-{ts}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run(self) -> Path:
        """执行回放."""
        actions = self._load_events()
        if not actions:
            console.print("[red]❌ events.jsonl 为空或不存在[/red]")
            return self.output_dir

        console.print(f"  加载 {len(actions)} 个事件")

        for r in range(self.repeat):
            if self.repeat > 1:
                console.print(f"\n[bold]第 {r + 1}/{self.repeat} 次回放[/bold]")

            suffix = f"_r{r + 1}" if self.repeat > 1 else ""
            replay_dir = self.output_dir / f"replay{suffix}" if self.repeat > 1 else self.output_dir
            replay_dir.mkdir(parents=True, exist_ok=True)

            await self._replay_once(actions, replay_dir)

        return self.output_dir

    async def _replay_once(self, actions: list[Action], output_dir: Path) -> None:
        """执行一次完整回放."""
        screenshoter = Screenshoter(output_dir)
        replay_actions: list[Action] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            page_map: dict[str, Page] = {"main": page}

            prev_ts = actions[0].timestamp_ms if actions else 0
            prev_conditional_wait_ms = 0.0

            for i, orig in enumerate(actions):
                # 人为停顿 = 间隔 - 上一步条件等待耗时
                interval_ms = orig.timestamp_ms - prev_ts
                human_pause_ms = max(0, interval_ms - prev_conditional_wait_ms)
                if human_pause_ms > 0 and i > 0:
                    await asyncio.sleep((human_pause_ms / 1000) / self.speed)

                wait_start = time.time() * 1000
                target_page = page_map.get(orig.page_id, page)

                try:
                    await self._execute_action(target_page, orig, page_map)
                except Exception as e:
                    console.print(f"  [yellow]⚠ Step {orig.step}: {e}[/yellow]")

                conditional_wait_ms = (time.time() * 1000) - wait_start
                prev_conditional_wait_ms = conditional_wait_ms
                prev_ts = orig.timestamp_ms

                # 截图
                before_path = None
                after_path = None
                if orig.tag == ActionTag.CLICK:
                    after_path = await screenshoter.take_after(
                        target_page, orig.step, wait_stable=False
                    )

                replay_action = Action(
                    step=orig.step,
                    timestamp_ms=time.time() * 1000,
                    tag=orig.tag,
                    selector=orig.selector,
                    tag_name=orig.tag_name,
                    text=orig.text,
                    url=target_page.url,
                    page_id=orig.page_id,
                    value=orig.value,
                    screenshot_before=str(before_path) if before_path else None,
                    screenshot_after=str(after_path) if after_path else None,
                )
                replay_actions.append(replay_action)

            await context.close()
            await browser.close()

        # 生成回放报告
        reporter = MarkdownReporter()
        reporter.generate(replay_actions, [], output_dir)
        cleanup(output_dir, keep_all=self.keep_all)

        console.print(f"  ✅ 回放完成: {output_dir / 'record.md'}")

    async def _execute_action(
        self, page: Page, action: Action, page_map: dict[str, Page]
    ) -> None:
        """执行单个 Action."""
        tag = action.tag

        if tag == ActionTag.NAV:
            if action.value:
                await page.goto(action.value, wait_until="networkidle")
            elif action.url:
                await page.goto(action.url, wait_until="networkidle")

        elif tag == ActionTag.CLICK:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=10000)
                await page.click(action.selector)

        elif tag == ActionTag.INPUT:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.fill(action.selector, action.value or "")

        elif tag == ActionTag.CHANGE:
            if action.selector and action.value:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.select_option(action.selector, action.value)

        elif tag == ActionTag.SUBMIT:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.locator(action.selector).evaluate("el => el.submit()")

        elif tag == ActionTag.DIALOG:
            page.once("dialog", lambda d: asyncio.ensure_future(d.accept()))

        elif tag == ActionTag.TAB_OPEN:
            # 新标签页由浏览器自然触发，记录 page_id
            pass

        elif tag == ActionTag.TAB_CLOSE:
            target = page_map.pop(action.page_id, None)
            if target and action.page_id != "main":
                await target.close()

        elif tag in (ActionTag.SHOT, ActionTag.SCROLL):
            pass  # 无操作

    def _load_events(self) -> list[Action]:
        """从 events.jsonl 加载 Action 列表."""
        if not self.events_path.exists():
            return []

        actions = []
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    actions.append(Action(
                        step=d["step"],
                        timestamp_ms=d["timestamp_ms"],
                        tag=ActionTag(d["tag"]),
                        selector=d.get("selector", ""),
                        tag_name=d.get("tag_name", ""),
                        url=d.get("url", ""),
                        page_id=d.get("page_id", "main"),
                        value=d.get("value"),
                        text=d.get("text"),
                        frame_id=d.get("frame_id"),
                        coords=tuple(d["coords"]) if d.get("coords") else None,
                    ))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    console.print(f"  [yellow]⚠ 跳过无效行: {e}[/yellow]")
        return actions
