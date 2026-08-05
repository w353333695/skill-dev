"""
PDF → Word 转换器。

使用 pdf2docx 库直接将 PDF 转换为 Word 文档，
尽量保留原始排版、表格和样式。
"""

from pathlib import Path

from .base import BaseConverter, ConvertResult, register


@register
class PdfToDocxConverter(BaseConverter):
    """PDF 转 Word 文档"""

    name = "pdf-docx"
    source_formats = ["pdf"]
    target_formats = ["docx"]
    description = "PDF 转 Word 文档 (保留排版和表格)"
    dependencies = ["pdf2docx"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        """
        将 PDF 转换为 Word 文档。

        Args:
            input_path: PDF 文件路径
            output_path: 输出 .docx 文件路径
            **options:
                start: 起始页码 (从0开始，默认0)
                end: 结束页码 (默认None即全部)

        Returns:
            ConvertResult
        """
        try:
            from pdf2docx import Converter
        except ImportError:
            return ConvertResult(
                success=False,
                message="缺少依赖 pdf2docx，请运行: uv pip install pdf2docx",
            )

        start = options.get("start", 0)
        end = options.get("end", None)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cv = Converter(str(input_path))
            cv.convert(str(output_path), start=start, end=end)
            cv.close()
        except Exception as e:
            return ConvertResult(success=False, message=f"转换失败: {e}")

        return ConvertResult(
            success=True,
            output_path=output_path,
            message="PDF 已转为 Word 文档",
        )
