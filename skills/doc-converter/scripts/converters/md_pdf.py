"""Markdown → PDF 转换器"""

from pathlib import Path
from .base import BaseConverter, ConvertResult, register
from .md_html import md_to_html_body, build_full_html


@register
class MdToPdf(BaseConverter):
    name = "md-pdf"
    source_formats = ["md", "markdown"]
    target_formats = ["pdf"]
    description = "Markdown 转 PDF (支持 Mermaid 图表渲染)"
    dependencies = ["playwright"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        from .renderer import html_to_pdf

        text = input_path.read_text(encoding="utf-8")
        title = options.get("title", input_path.stem)

        body, has_mermaid = md_to_html_body(text, input_path=input_path)

        extra_head = ""
        if has_mermaid:
            extra_head = (
                '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>\n'
                '<script>mermaid.initialize({startOnLoad: true});</script>'
            )

        html = build_full_html(body, title, extra_head)

        wait_ms = 3000 if has_mermaid else 500
        html_to_pdf(html, output_path, wait_ms=wait_ms, **options)

        return ConvertResult(True, output_path=output_path, message="Markdown 已转为 PDF")
