"""Markdown → PDF 转换器

优先用系统 pandoc + xelatex 生成 PDF（免 chromium，支持中文）；
pandoc/xelatex 不可用时回退到 playwright 渲染（需 [render] extra + install-deps）。
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import BaseConverter, ConvertResult, register


def _has_pandoc_pdf() -> bool:
    """系统是否有 pandoc + xelatex（md→pdf 的轻量路径）。"""
    return bool(shutil.which("pandoc")) and bool(shutil.which("xelatex"))


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@register
class MdToPdf(BaseConverter):
    name = "md-pdf"
    source_formats = ["md", "markdown"]
    target_formats = ["pdf"]
    description = "Markdown 转 PDF (pandoc+xelatex 优先, 回退 playwright)"
    # pandoc/xelatex 是系统二进制；playwright 走 [render] extra。两者有其一即可。
    dependencies = []

    def check_dependencies(self) -> tuple[bool, list[str]]:
        if _has_pandoc_pdf() or _has_playwright():
            return True, []
        return False, ["pandoc+xelatex(系统) 或 doc-converter[render]"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        if _has_pandoc_pdf():
            return self._via_pandoc(input_path, output_path, **options)
        return self._via_playwright(input_path, output_path, **options)

    def _via_pandoc(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        """pandoc + xelatex 生成 PDF（支持中文，免 chromium）。

        pandoc 默认 latex template 引 ``\\usepackage{lmodern}``，系统 TexLive 若缺
        lmodern.sty 会编译失败；取默认 template 去掉该行（完整环境去掉亦无副作用）。
        """
        default = subprocess.run(
            ["pandoc", "-D", "latex"], capture_output=True, text=True, check=True
        ).stdout
        tmpl = default.replace(r"\usepackage{lmodern}" + "\n", "")
        with tempfile.NamedTemporaryFile(
            suffix=".tex", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(tmpl)
            tmpl_path = f.name
        try:
            cjk = options.get("cjk_font", "Noto Sans CJK SC")
            cmd = [
                "pandoc", str(input_path), "-o", str(output_path),
                "--pdf-engine=xelatex", f"--template={tmpl_path}",
                f"-VCJKmainfont={cjk}", f"-Vmainfont={cjk}",
                "-V", "geometry:margin=2cm",
            ]
            if options.get("landscape"):
                cmd += ["-V", "geometry:landscape"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                # pandoc 失败时回退 playwright（若可用），否则报错
                if _has_playwright():
                    return self._via_playwright(input_path, output_path, **options)
                return ConvertResult(
                    False, message=f"pandoc 生成 PDF 失败:\n{r.stderr.strip()[:500]}"
                )
        finally:
            Path(tmpl_path).unlink(missing_ok=True)
        return ConvertResult(
            True, output_path=output_path, message="Markdown 已转为 PDF (pandoc+xelatex)"
        )

    def _via_playwright(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        from .md_html import md_to_html_body, build_full_html
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
        return ConvertResult(
            True, output_path=output_path, message="Markdown 已转为 PDF (playwright)"
        )
