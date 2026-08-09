"""doc.md 生成：record.jsonl + requests.jsonl + screenshots/ → 图文操作手册 + 请求附录。"""

from __future__ import annotations

from pathlib import Path

from .models import StepEvent, read_requests, read_steps


def describe(step: StepEvent) -> str:
    """一步操作的人类可读描述。"""
    label = step.label or "页面元素"
    if step.type == "click":
        return f"点击【{label}】"
    if step.type == "input":
        value = "***" if step.sensitive else f"`{step.value}`"
        return f"在【{label}】输入 {value}"
    if step.type == "select":
        return f"在【{label}】选择 `{step.value}`"
    if step.type == "key":
        return f"按 {step.value} 键"
    if step.type == "navigate":
        return f"打开 {step.value}"
    return f"{step.type}【{label}】"


def _requests_appendix(session_dir: Path) -> list[str]:
    """关键请求附录：写操作（POST/PUT/DELETE/PATCH）或非 2xx 的请求列成表。"""
    requests = read_requests(session_dir)
    interesting = [
        r for r in requests
        if r.method in ("POST", "PUT", "DELETE", "PATCH") or (r.status and r.status >= 400)
    ]
    if not interesting:
        return []
    lines = ["## 附：关键请求", "", "| 步骤 | 方法 | 路径 | 状态 |", "|---|---|---|---|"]
    for r in interesting:
        path = r.url.split("://", 1)[-1].split("/", 1)
        path = "/" + path[1] if len(path) > 1 else r.url
        if len(path) > 60:
            path = path[:57] + "..."
        lines.append(f"| {r.step_seq} | {r.method} | `{path}` | {r.status or '-'} |")
    lines.append("")
    lines.append("> 完整请求记录见 `requests.jsonl`（含请求体/响应体）。")
    return lines


def generate(session_dir: Path, title: str | None = None) -> Path:
    session_dir = Path(session_dir)
    steps = read_steps(session_dir)
    title = title or f"操作手册 - {session_dir.name}"

    lines = [f"# {title}", ""]
    for step in steps:
        lines.append(f"## 步骤 {step.seq}：{describe(step)}")
        lines.append("")
        if step.screenshot:
            lines.append(f"![步骤{step.seq}]({step.screenshot})")
            lines.append("")

    lines += _requests_appendix(session_dir)

    path = session_dir / "doc.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
