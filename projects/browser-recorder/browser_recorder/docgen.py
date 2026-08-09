"""doc.md 生成：record.jsonl + screenshots/ → 图文操作手册。"""

from __future__ import annotations

from pathlib import Path

from .models import StepEvent, read_steps


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

    path = session_dir / "doc.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
