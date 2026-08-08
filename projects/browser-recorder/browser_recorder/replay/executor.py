# browser_recorder/replay/executor.py
"""回放执行器：按 trace 逐条重放，选择器回退 + settle + 可选截图，失败不中断。"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING
from ..models import Action
from ..selectors import locate
from ..settle import wait_for_settled
from .delays import DelayResolver

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class ReplayStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)


class ReplayExecutor:
    def __init__(self, page: "Page", resolver: DelayResolver,
                 screenshot_dir: Path | None = None, mark: bool = False):
        self.page = page
        self.resolver = resolver
        self.screenshot_dir = screenshot_dir
        self.mark = mark   # 录视频时在每个动作【前】闪现内联标记（真 lead）

    async def _do_action(self, a: Action) -> bool:
        if a.type == "navigation":
            try:
                await self.page.goto(a.url, wait_until="domcontentloaded")
                return True
            except Exception:
                return False
        target = a.target
        loc = await locate(self.page, target) if target else None
        try:
            if a.type == "click":
                if loc:
                    await loc.click(timeout=2000)
                    return True
                if target and target.bbox:  # 坐标兜底
                    b = target.bbox
                    await self.page.mouse.click(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)
                    return True
            elif a.type == "input" and loc and a.value is not None:
                await loc.fill(a.value, timeout=2000)
                return True
            elif a.type == "submit" and loc:
                await loc.click(timeout=2000)
                return True
            elif a.type == "keypress" and loc:
                await loc.press(a.value or "Enter", timeout=2000)
                return True
            elif a.type == "select" and loc:
                await loc.select_option(a.value or "", timeout=2000)
                return True
            elif a.type == "scroll":
                await self.page.mouse.wheel(0, 300)
                return True
            elif a.type == "hover" and loc:
                await loc.hover(timeout=2000)
                return True
        except Exception:
            return False
        return loc is not None

    async def replay(self, actions: list[Action]) -> ReplayStats:
        stats = ReplayStats(total=len(actions))
        for a in actions:
            await asyncio.sleep(self.resolver.before(a.type) / 1000.0)
            ok = await self._do_action(a)
            if ok:
                # after = settle 超时上限
                await wait_for_settled(self.page,
                                       timeout_ms=self.resolver.after(a.type),
                                       debounce_ms=300)
                if self.screenshot_dir:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    await self.page.screenshot(path=str(self.screenshot_dir / f"step-{a.seq:04d}-after.png"))
                await asyncio.sleep(self.resolver.idle() / 1000.0)
                stats.succeeded += 1
            else:
                stats.failed += 1
                stats.failures.append({"seq": a.seq, "type": a.type,
                                       "css": a.target.css if a.target else None})
                if self.screenshot_dir:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    await self.page.screenshot(path=str(self.screenshot_dir / f"step-{a.seq:04d}-failed.png"))
        return stats
