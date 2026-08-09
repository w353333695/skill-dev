"""报告生成器 — Reporter Protocol 及 Markdown 实现."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
from .models import Action, ActionTag, RequestRecord


@runtime_checkable
class Reporter(Protocol):
    """从累积记录生成最终报告."""

    def generate(
        self,
        actions: list[Action],
        requests: list[RequestRecord],
        output_dir: Path,
    ) -> Path:
        ...


class MarkdownReporter:
    """生成 Markdown 图文报告 (record.md)."""

    def generate(
        self,
        actions: list[Action],
        requests: list[RequestRecord],
        output_dir: Path,
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "record.md"

        first_action = actions[0] if actions else None
        url = first_action.url if first_action else "unknown"
        start_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        duration_s = 0
        if actions:
            duration_s = (actions[-1].timestamp_ms - actions[0].timestamp_ms) / 1000

        lines = [
            f"# 录制报告 — {url}",
            f"> **开始**: {start_time} | **时长**: {self._fmt_duration(duration_s)} | **步骤**: {len(actions)} | **请求**: {len(requests)}",
            "",
            "---",
            "",
        ]

        # 步骤时间线
        base_ts = actions[0].timestamp_ms if actions else 0
        for action in actions:
            rel_ms = action.timestamp_ms - base_ts
            rel_str = self._fmt_timestamp(rel_ms)
            tag = f"[{action.tag.value}]"
            page = f"page:{action.page_id}"

            lines.append(f"## [Step {action.step}] {tag} {rel_str} | {page}")
            lines.append("")

            if action.tag == ActionTag.NAV:
                lines.append(f"导航到 {action.url}")
            elif action.tag == ActionTag.CLICK:
                label = action.text or action.selector
                lines.append(f"点击 `{action.selector}` \"{label}\"")
            elif action.tag == ActionTag.INPUT:
                val = action.value or ""
                if len(val) > 50:
                    val = val[:50] + "…"
                lines.append(f"输入 `{action.selector}` = \"{val}\"")
            elif action.tag == ActionTag.CHANGE:
                lines.append(f"选择 `{action.selector}` = \"{action.value or ''}\"")
            elif action.tag == ActionTag.SUBMIT:
                lines.append(f"提交表单 `{action.selector}`")
            elif action.tag == ActionTag.DIALOG:
                lines.append(f"弹窗: {action.value or action.text or ''}")
            elif action.tag == ActionTag.TAB_OPEN:
                lines.append(f"打开新标签页 #{action.page_id}: {action.url}")
            elif action.tag == ActionTag.TAB_CLOSE:
                lines.append(f"关闭标签页 #{action.page_id}")
            elif action.tag == ActionTag.SHOT:
                lines.append(f"定时截图")
            elif action.tag == ActionTag.SCROLL:
                lines.append(f"滚动页面")

            lines.append("")

            # 截图
            if action.screenshot_before:
                lines.append(f"操作前：")
                lines.append(f'<img src="{action.screenshot_before}" width="300"/>')
                lines.append("")
            if action.screenshot_after:
                label = "操作结果：" if action.screenshot_before else "截图："
                lines.append(f"{label}")
                lines.append(f'<img src="{action.screenshot_after}" width="100%"/>')
                lines.append("")

        # 网络请求
        if requests:
            lines.append("---")
            lines.append("")
            lines.append("## 网络请求记录")
            lines.append("")
            lines.append("| # | 时间 | 方法 | URL | 状态 | 耗时 |")
            lines.append("|---|------|------|-----|------|------|")
            for i, req in enumerate(requests, 1):
                rel_ms = max(0, req.timestamp_ms - base_ts)
                rel_str = self._fmt_timestamp(rel_ms)
                lines.append(
                    f"| {i} | {rel_str} | {req.method} | {req.url} "
                    f"| {req.status} | {req.duration_ms}ms |"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    @staticmethod
    def _fmt_timestamp(ms: float) -> str:
        """毫秒 → MM:SS.msc 格式."""
        total_s = ms / 1000
        minutes = int(total_s // 60)
        seconds = total_s % 60
        return f"{minutes:02d}:{seconds:06.3f}"

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """秒 → XmXs 格式."""
        if seconds < 60:
            return f"{int(seconds)}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m{s}s"
