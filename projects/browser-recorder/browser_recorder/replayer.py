"""回放器：读 record.jsonl 重放操作，selector 多路 fallback + 智能等待。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .models import StepEvent, read_steps


class Replayer:
    """headless 回放指定 session。

    - resolve(): 按 SelectorSet 优先级探测（存在且可见）
    - 每步：wait_for(visible) → 执行 → networkidle（超时可容忍）
    - params: record.jsonl 里 input step 的 param_key 对应值覆盖（--param key=value）
    """

    def __init__(
        self,
        session_dir: str | Path,
        params: dict | None = None,
        on_fail: str = "stop",
        video: bool = False,
        timeout_ms: int = 15000,
        ignore_https_errors: bool = False,
    ):
        self.session_dir = Path(session_dir)
        self.params = params or {}
        self.on_fail = on_fail
        self.video = video
        self.timeout_ms = timeout_ms
        self.ignore_https_errors = ignore_https_errors

        self.replay_dir = self.session_dir / "replay"
        self.replay_dir.mkdir(exist_ok=True)
        (self.replay_dir / "screenshots").mkdir(exist_ok=True)

    def run(self) -> dict:
        from playwright.sync_api import sync_playwright

        steps = read_steps(self.session_dir)
        results = []
        start_url = self._start_url(steps)

        with sync_playwright() as p:
            launch_args = ["--ignore-certificate-errors"] if self.ignore_https_errors else []
            browser = p.chromium.launch(headless=True, args=launch_args)
            ctx_kwargs = {"ignore_https_errors": self.ignore_https_errors}
            if self.video:
                ctx_kwargs["record_video_dir"] = str(self.replay_dir / "video")
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()

            if start_url:
                page.goto(start_url, wait_until="domcontentloaded")
                self._wait_network(page)

            for step in steps:
                result = self._replay_step(page, step)
                results.append(result)
                if result["status"] == "failed" and self.on_fail == "stop":
                    break

            final_url = page.url
            context.close()
            browser.close()

        failed = [r for r in results if r["status"] == "failed"]
        report = {
            "total": len(steps),
            "executed": len(results),
            "passed": sum(1 for r in results if r["status"] == "passed"),
            "failed": len(failed),
            "skipped": len(steps) - len(results),
            "final_url": final_url,
            "steps": results,
        }
        report_path = self.replay_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    # ---------- 内部 ----------

    def _start_url(self, steps: list[StepEvent]) -> str | None:
        for step in steps:
            if step.type == "navigate" and step.value:
                return step.value
        return steps[0].url if steps else None

    def _resolve(self, page, step: StepEvent):
        """按优先级探测 selector，返回 (策略名, locator) 或 (None, None)。"""
        for strategy, selector in step.selectors.best():
            try:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    return strategy, loc.first
            except Exception:
                continue
        return None, None

    def _replay_step(self, page, step: StepEvent) -> dict:
        result = {"seq": step.seq, "type": step.type, "status": "passed",
                  "selector_used": None, "duration_ms": 0, "error": None}
        start = time.monotonic()
        try:
            if step.type == "navigate":
                if step.value:
                    page.goto(step.value, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    self._wait_network(page)
            else:
                strategy, loc = self._resolve(page, step)
                if loc is None:
                    raise RuntimeError(f"所有 selector 候选均未命中: {step.selectors.best()}")
                result["selector_used"] = strategy
                loc.wait_for(state="visible", timeout=self.timeout_ms)

                if step.type == "click":
                    loc.click(timeout=self.timeout_ms)
                elif step.type == "input":
                    value = self.params.get(step.param_key, step.value) if step.param_key else step.value
                    loc.fill(value or "", timeout=self.timeout_ms)
                elif step.type == "select":
                    loc.select_option(value=step.value, timeout=self.timeout_ms)
                elif step.type == "key":
                    loc.press(step.value or "Enter", timeout=self.timeout_ms)
                self._wait_network(page)

            page.screenshot(path=str(self.replay_dir / "screenshots" / f"step-{step.seq:03d}.png"))
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)[:500]
            try:
                page.screenshot(path=str(self.replay_dir / "screenshots" / f"step-{step.seq:03d}-fail.png"))
            except Exception:
                pass
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result

    def _wait_network(self, page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 10000))
        except Exception:
            try:
                page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
