"""markdown YAML frontmatter 解析/重写工具。

close 缺口时要回写知识文件的 completeness/gaps/last_verified，需可靠解析
`---` 包围的 frontmatter 并保留正文。本模块只做 frontmatter ↔ body 的拆合，
不关心字段语义。无 frontmatter 的文件按空 dict + 全文 body 处理。
"""
from __future__ import annotations
from pathlib import Path
import yaml


def parse(text: str) -> tuple[dict, str]:
    """拆分 frontmatter 与正文。无 frontmatter 返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    # 找第二个 --- 作为 frontmatter 结束
    rest = text[3:]
    # 跳过首个换行
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    fm_text = rest[:end]
    body = rest[end + 4:]  # 跳过 "\n---"
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    fm = yaml.safe_load(fm_text) or {}
    return fm, body


def dump(fm: dict, body: str) -> str:
    """重组为 frontmatter + 正文。"""
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n{body}"


def load_file(path: Path) -> tuple[dict, str]:
    return parse(Path(path).read_text(encoding="utf-8"))


def write_file(path: Path, fm: dict, body: str) -> None:
    Path(path).write_text(dump(fm, body), encoding="utf-8")
