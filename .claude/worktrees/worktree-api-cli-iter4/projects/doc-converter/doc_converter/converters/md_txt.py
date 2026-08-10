"""Markdown → 纯文本 (txt) 转换器。

复用 markdown 库把 md 解析成 HTML，再用标准库 html.parser 剥标签：
块级元素（段落/列表/标题/表格行）落为换行，避免内联标签内容黏成一坨。
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from .base import BaseConverter, ConvertResult, register
from .md_html import md_to_html_body


class _TextStripper(HTMLParser):
    """剥 HTML 标签为纯文本，块级元素和表格行落为换行。"""

    # 结束后换行的块级标签
    _BLOCK = {
        "p", "div", "section", "li", "ul", "ol", "blockquote", "pre",
        "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
        "header", "footer", "article", "dl", "dt", "dd",
    }
    _CELL = {"td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._out.append("\n")
        elif tag == "hr":
            self._out.append("\n---\n")
        elif tag == "li":
            self._out.append("\n- ")
        elif tag == "img":
            # 图片以 alt 文本替代（无 alt 则留空），保持段落可读
            alt = dict(attrs).get("alt", "")
            if alt:
                self._out.append(alt)

    def handle_endtag(self, tag):
        if tag in self._BLOCK:
            self._out.append("\n")
        elif tag in self._CELL:
            self._out.append(" | ")

    def handle_data(self, data):
        # 纯空白（HTML 源码的换行/缩进）折叠：行首位置（上一输出以 \n 结尾或为空）
        # 直接丢弃，消除段落/表格/代码块的前导空格；行中折叠为单空格，避免把表格
        # 单元格、标签间的源码换行当成内容拆散成多行。代码块内部的真实缩进保留。
        if data.strip() == "":
            if not data:
                return
            if not self._out or self._out[-1].endswith("\n"):
                return
            self._out.append(" ")
            return
        self._out.append(data)

    def text(self) -> str:
        joined = "".join(self._out)
        # 折叠 3+ 连续换行为段落间距，去掉行尾空白
        joined = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", joined)
        lines = [ln.rstrip() for ln in joined.split("\n")]
        return "\n".join(lines).strip() + "\n"


@register
class MdToText(BaseConverter):
    """Markdown → 纯文本：去标记、保留段落/列表/表格行结构。"""

    name = "md-txt"
    source_formats = ["md", "markdown"]
    target_formats = ["txt"]
    description = "Markdown 转纯文本 (去标记，保留段落结构)"
    dependencies = []

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        text = input_path.read_text(encoding="utf-8")
        html, _, _ = md_to_html_body(text, highlight=False)

        stripper = _TextStripper()
        stripper.feed(html)
        plain = stripper.text()

        if not plain.strip():
            return ConvertResult(False, message="文档为空或无文本内容")

        output_path.write_text(plain, encoding="utf-8")
        return ConvertResult(
            True, output_path=output_path, message="Markdown 已转为纯文本"
        )
