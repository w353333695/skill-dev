"""Markdown → JSON 结构化提取转换器。

复用 markdown 库把 md 解析成 HTML，再用标准库 html.parser 抽取结构化元素：
大纲（标题层级树）/ 链接 / 图片；代码块则从原 md 正则提取（跳过 mermaid）。

通过 ``--extract`` 选择提取内容（默认 outline），让原本是 dead option 的
``extract=code`` 真正落地。
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from .base import BaseConverter, ConvertResult, register
from .md_html import md_to_html_body

# fenced 代码块：```lang\n ... ```（MULTILINE 让 ^/`` 锚定行首）
_CODE_BLOCK_RE = re.compile(r"^```([^\n`]*)\n(.*?)```", re.MULTILINE | re.DOTALL)

_EXTRACTORS = ("outline", "links", "images", "code")


class _StructParser(HTMLParser):
    """一次遍历 HTML，收集标题 / 链接 / 图片。

    - headings: [(level, text)] 平铺，后续按 level 建树
    - links:    [{text, href}]
    - images:   [{alt, src}]
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, str]] = []
        self.links: list[dict] = []
        self.images: list[dict] = []
        self._h_level: int | None = None
        self._h_text: str = ""
        self._a_href: str | None = None
        self._a_text: str = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._h_level = int(tag[1])
            self._h_text = ""
        elif tag == "a":
            self._a_href = dict(attrs).get("href")
            self._a_text = ""
        elif tag == "img":
            d = dict(attrs)
            self.images.append({"alt": d.get("alt", ""), "src": d.get("src", "")})

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._h_level is not None:
            self.headings.append((self._h_level, self._h_text.strip()))
            self._h_level = None
            self._h_text = ""
        elif tag == "a" and self._a_href is not None:
            self.links.append({"text": self._a_text.strip(), "href": self._a_href})
            self._a_href = None
            self._a_text = ""

    def handle_data(self, data):
        if self._h_level is not None:
            self._h_text += data
        if self._a_href is not None:
            self._a_text += data


def _build_outline_tree(headings: list[tuple[int, str]]) -> list[dict]:
    """把平铺的 [(level, text)] 按 level 建成嵌套树。"""
    root = {"level": 0, "children": []}
    stack = [root]
    for level, text in headings:
        node = {"level": level, "text": text, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)
    return root["children"]


def _extract_code_blocks(md_text: str) -> list[dict]:
    """从原 md 提取所有 fenced 代码块，跳过 mermaid（它有专门提取器）。"""
    blocks = []
    for m in _CODE_BLOCK_RE.finditer(md_text):
        lang = m.group(1).strip()
        if lang == "mermaid":
            continue
        blocks.append({"lang": lang, "code": m.group(2).rstrip("\n")})
    return blocks


def extract_struct(md_text: str, kind: str) -> list:
    """提取指定类型的结构化数据。kind ∈ outline/links/images/code。"""
    if kind == "code":
        return _extract_code_blocks(md_text)
    # outline/links/images 走 HTML 解析：不高亮、不抽 mermaid 占位符
    html, _, _ = md_to_html_body(md_text, with_mermaid=False, highlight=False)
    parser = _StructParser()
    parser.feed(html)
    if kind == "outline":
        return _build_outline_tree(parser.headings)
    if kind == "links":
        return parser.links
    if kind == "images":
        return parser.images
    return []


_LABELS = {
    "outline": "标题大纲",
    "links": "链接",
    "images": "图片",
    "code": "代码块",
}


@register
class MdToJson(BaseConverter):
    """Markdown → JSON：提取大纲/链接/图片/代码块为结构化 JSON。"""

    name = "md-json"
    source_formats = ["md", "markdown"]
    target_formats = ["json"]
    description = "Markdown 转 JSON (提取大纲/链接/图片/代码块)"
    dependencies = []

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        text = input_path.read_text(encoding="utf-8")
        kind = options.get("extract") or "outline"
        if kind not in _EXTRACTORS:
            return ConvertResult(
                False,
                message=f"不支持的提取模式 '{kind}'，可选: {'/'.join(_EXTRACTORS)}",
            )

        items = extract_struct(text, kind)
        if not items:
            return ConvertResult(False, message=f"未找到{_LABELS[kind]}")

        payload = {"extract": kind, "count": len(items), "items": items}
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return ConvertResult(
            True,
            output_path=output_path,
            message=f"已提取 {len(items)} 个{_LABELS[kind]}为 JSON",
            metadata={"extract": kind, "count": len(items)},
        )
