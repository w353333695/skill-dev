"""HTML → PDF 转换器"""

from pathlib import Path
from .base import BaseConverter, ConvertResult, register


@register
class HtmlToPdf(BaseConverter):
    name = "html-pdf"
    source_formats = ["html", "htm"]
    target_formats = ["pdf"]
    description = "HTML 转 PDF"
    dependencies = ["playwright"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        from .renderer import html_to_pdf

        html_content = input_path.read_text(encoding="utf-8")
        html_to_pdf(html_content, output_path, **options)
        return ConvertResult(True, output_path=output_path, message="HTML 已转为 PDF")
