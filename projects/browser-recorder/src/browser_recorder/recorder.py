"""录制编排器 — 整合浏览器生命周期与事件管道."""
from __future__ import annotations
import asyncio
import json as _json
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
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
ARTIFACT_ROOT = Path("./browser-recorder")


def _domain_key(url: str) -> str:
    """从 URL 提取域名/IP 作为目录名.

    https://example.com/path   → example.com
    http://192.168.1.1:8080/a  → 192.168.1.1_8080
    """
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname or "unknown"
    if p.port and p.port not in (80, 443):
        host = f"{host}_{p.port}"
    return host


def domain_path(url: str) -> Path:
    """返回域名根目录."""
    return ARTIFACT_ROOT / _domain_key(url)


def scenario_path(url: str, name: str = "default") -> Path:
    """返回场景目录."""
    return domain_path(url) / name


# ---- index.json (全局) ----


def load_index() -> dict:
    idx = ARTIFACT_ROOT / "index.json"
    if idx.exists():
        return _json.loads(idx.read_text())
    return {"domains": {}}


def save_index(index: dict) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "index.json").write_text(
        _json.dumps(index, ensure_ascii=False, indent=2)
    )


# ---- meta.json (域名级) ----


def load_domain_meta(domain_dir: Path) -> dict:
    mp = domain_dir / "meta.json"
    if mp.exists():
        return _json.loads(mp.read_text())
    return {
        "domain": domain_dir.name,
        "first_seen": None,
        "last_recorded": None,
        "total_recordings": 0,
        "urls": [],
        "scenarios": {},
    }


def save_domain_meta(domain_dir: Path, meta: dict) -> None:
    (domain_dir / "meta.json").write_text(
        _json.dumps(meta, ensure_ascii=False, indent=2)
    )


# ---- meta.json (场景级) ----


def load_scenario_meta(scenario_dir: Path) -> dict:
    sp = scenario_dir / "meta.json"
    if sp.exists():
        return _json.loads(sp.read_text())
    return {
        "name": scenario_dir.name,
        "first_seen": None,
        "last_recorded": None,
        "total_recordings": 0,
        "sessions": [],
    }


def save_scenario_meta(scenario_dir: Path, meta: dict) -> None:
    (scenario_dir / "meta.json").write_text(
        _json.dumps(meta, ensure_ascii=False, indent=2)
    )


class Recorder:
    """录制编排器 — 按域名共享鉴权 + 按场景独立录制."""

    def __init__(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        scenario_name: str = "default",
        fallback_interval: int = 30,
        req_all: bool = False,
        req_filter: Optional[str] = None,
        keep_all: bool = False,
        max_duration: int = 0,
    ) -> None:
        self.url = url
        self.scenario_name = scenario_name
        self.keep_all = keep_all
        self.max_duration = max_duration
        self.fallback_interval = fallback_interval

        # 目录结构: <domain>/<scenario>/
        self.domain_dir = domain_path(url)
        self.scenario_dir = output_dir or scenario_path(url, scenario_name)
        self.scenario_dir.mkdir(parents=True, exist_ok=True)

        # 清除上次录制的临时截图
        self._clear_stale_screenshots()

        # 请求过滤
        self._req_filter: Optional[str] = req_filter
        if req_all:
            self._req_filter = "*"

        # 管道组件（输出到场景目录）
        self.pipeline = FilterPipeline()
        self.pipeline.add(InputMergeFilter())
        self.pipeline.add(DedupFilter())

        self.jsonl_writer = JsonlWriter(self.scenario_dir)
        self.screenshoter = Screenshoter(self.scenario_dir)
        self.network_interceptor = NetworkInterceptor(self._req_filter)

        # 鉴权状态
        self._auth_file = self.domain_dir / "auth.json"

        # 运行时状态
        self.actions: list[Action] = []
        self.step_counter = 0
        self.start_time_ms = 0.0
        self._page_map: Dict[str, Page] = {}
        self._page_counter = 0
        self._running = False
        self._fallback_task: Optional[asyncio.Task] = None

    def _clear_stale_screenshots(self) -> None:
        ss_dir = self.scenario_dir / "screenshots"
        if ss_dir.exists():
            shutil.rmtree(ss_dir)
        ss_dir.mkdir(parents=True, exist_ok=True)

    def _load_auth(self, context: BrowserContext) -> None:
        """从 auth.json 恢复鉴权状态."""
        if self._auth_file.exists():
            try:
                state = _json.loads(self._auth_file.read_text())
                context.add_cookies(state.get("cookies", []))
                # localStorage/origins 通过 storage_state 完整恢复
                # add_cookies 是简化版；完整恢复用 context.add_init_script
                # 或直接用 browser.new_context(storage_state=...)
                console.print(f"[dim]🔐 已加载鉴权: {self._auth_file}[/dim]")
            except Exception:
                pass

    async def _save_auth(self, context: BrowserContext) -> None:
        """保存鉴权状态到 auth.json."""
        try:
            state = await context.storage_state()
            self._auth_file.write_text(_json.dumps(state, ensure_ascii=False, indent=2))
            console.print(f"[dim]🔐 鉴权已保存: {self._auth_file}[/dim]")
        except Exception:
            pass

    async def run(self) -> Path:
        """启动录制."""
        self._running = True
        self.start_time_ms = time.time() * 1000

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)

            # 尝试加载已有鉴权状态
            storage_state = None
            if self._auth_file.exists():
                try:
                    storage_state = _json.loads(self._auth_file.read_text())
                    console.print("[dim]🔐 已加载鉴权状态[/dim]")
                except Exception:
                    pass

            context = await browser.new_context(
                no_viewport=True,
                storage_state=storage_state,
                ignore_https_errors=True,
            )

            page = await context.new_page()
            self._register_page(page, "main")

            # 先挂主页面，再监听后续弹窗/新标签
            await self.network_interceptor.setup(page)
            await self._setup_page(page, "main")

            # 监听后续新页面（window.open / target=_blank），不包括已创建的 main
            context.on("page", lambda p: asyncio.ensure_future(self._on_new_page(p)))
            await self._record_nav(page, self.url)

            if self.fallback_interval > 0:
                self._fallback_task = asyncio.ensure_future(
                    self._fallback_loop(page)
                )

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

            # 保存鉴权
            await self._save_auth(context)

            for p in self._page_map.values():
                await injector_flush(p)
            self.jsonl_writer.flush()

            await context.close()
            await browser.close()

        return self._finalize()

    async def _setup_page(self, page: Page, page_id: str) -> None:
        await setup_recorder_callback(page, self._on_events_batch)
        await inject(page, page_id)

        page.on("dialog", lambda d: asyncio.ensure_future(
            self._on_dialog(d, page, page_id)
        ))
        page.on("framenavigated", lambda f: asyncio.ensure_future(
            self._on_navigate(page, page_id)
        ))
        page.on("close", lambda: asyncio.ensure_future(
            self._on_page_close(page_id)
        ))

    async def _on_new_page(self, page: Page) -> None:
        self._page_counter += 1
        page_id = f"tab_{self._page_counter}"
        self._register_page(page, page_id)
        await self.network_interceptor.setup(page)
        await self._setup_page(page, page_id)

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
        try:
            batch = _json.loads(json_str)
        except _json.JSONDecodeError:
            return
        for raw in batch:
            for ev in self.pipeline.process(raw):
                await self._handle_event(ev)

    async def _handle_event(self, ev: dict) -> None:
        tag_str = ev.get("type", "")
        try:
            tag = ActionTag(tag_str)
        except ValueError:
            return

        page_id = ev.get("pageId", "main")
        page = self._page_map.get(page_id)
        if page is None:
            return

        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=ev.get("timestamp", time.time() * 1000),
            tag=tag,
            selector=ev.get("selector", ""),
            tag_name=ev.get("tagName", ""),
            text=ev.get("text"),
            url=ev.get("url", page.url),
            page_id=page_id,
            frame_id=ev.get("frameId"),
            coords=tuple(ev["coords"].values()) if ev.get("coords") else None,
            value=ev.get("value"),
        )

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
        """记录导航事件. commit 后等 2s 让 JS 跳转/渲染完成."""
        await page.goto(url, wait_until="commit", timeout=30000)
        await asyncio.sleep(2)  # 等 JS 跳转 + 首屏渲染
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
        await injector_flush(page)
        self.pipeline.flush()

    async def _on_page_close(self, page_id: str) -> None:
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
        now = datetime.now(timezone.utc).isoformat()
        duration_s = 0.0
        if self.actions:
            duration_s = (self.actions[-1].timestamp_ms - self.actions[0].timestamp_ms) / 1000

        # 产物写入场景目录
        requests = self.network_interceptor.requests
        (self.scenario_dir / "requests.json").write_text(
            _json.dumps([asdict(r) for r in requests], ensure_ascii=False, indent=2)
        )
        MarkdownReporter().generate(self.actions, requests, self.scenario_dir)
        cleanup(self.scenario_dir, keep_all=self.keep_all)

        # 更新场景 meta.json
        sc_meta = load_scenario_meta(self.scenario_dir)
        if sc_meta["first_seen"] is None:
            sc_meta["first_seen"] = now
        sc_meta["last_recorded"] = now
        sc_meta["total_recordings"] += 1
        sc_meta["sessions"].append({
            "ts": now,
            "url": self.url,
            "steps": len(self.actions),
            "duration_s": round(duration_s, 1),
        })
        if len(sc_meta["sessions"]) > 20:
            sc_meta["sessions"] = sc_meta["sessions"][-20:]
        save_scenario_meta(self.scenario_dir, sc_meta)

        # 更新域名 meta.json
        domain_meta = load_domain_meta(self.domain_dir)
        if domain_meta["first_seen"] is None:
            domain_meta["first_seen"] = now
        domain_meta["last_recorded"] = now
        domain_meta["total_recordings"] += 1
        if self.url not in domain_meta["urls"]:
            domain_meta["urls"].append(self.url)
        domain_meta["scenarios"][self.scenario_name] = {
            "last_recorded": now,
            "total_recordings": sc_meta["total_recordings"],
        }
        save_domain_meta(self.domain_dir, domain_meta)

        # 更新全局 index.json
        index = load_index()
        index["domains"][self.domain_dir.name] = {
            "last_recorded": now,
            "scenarios": list(domain_meta["scenarios"].keys()),
        }
        save_index(index)

        console.print(f"\n[bold green]✅[/bold green] 录制完成: {self.scenario_dir}")
        console.print(f"   域名: {self.domain_dir.name}  |  场景: {self.scenario_name}")
        console.print(f"   报告: {self.scenario_dir / 'record.md'}")

        return self.scenario_dir
