"""代码 → 语法高亮 HTML/PNG 转换器"""

import re
from pathlib import Path
from .base import BaseConverter, ConvertResult, register

# 源格式 → 语言映射
LANG_MAP = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "rb": "ruby", "rs": "rust", "go": "go", "java": "java",
    "sh": "bash", "bash": "bash", "zsh": "bash",
    "yml": "yaml", "yaml": "yaml", "json": "json",
    "sql": "sql", "html": "html", "css": "css",
    "cpp": "cpp", "c": "c", "h": "c", "hpp": "cpp",
    "xml": "xml",
}

# md 由专用转换器处理 (md-html, md-pdf, mermaid-image)，不在此注册
_CODE_FORMATS = list(set(LANG_MAP.keys()) | {"txt", "text", "code"})

def highlight_code(code: str, language: str = "text") -> str:
    """生成语法高亮 HTML"""
    try:
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name, TextLexer
        from pygments.formatters import HtmlFormatter

        try:
            lexer = get_lexer_by_name(language)
        except Exception:
            lexer = TextLexer()

        formatter = HtmlFormatter(
            style="monokai",
            full=False,
            linenos=True,
            cssclass="highlight",
        )
        css = formatter.get_style_defs(".highlight")
        body = highlight(code, lexer, formatter)
        return css, body
    except ImportError:
        # fallback: 纯 pre 标签
        import html
        css = "pre { background: #272822; color: #f8f8f2; padding: 16px; border-radius: 6px; overflow-x: auto; }"
        body = f"<pre><code>{html.escape(code)}</code></pre>"
        return css, body


@register
class CodeToHtml(BaseConverter):
    name = "code-html"
    source_formats = _CODE_FORMATS
    target_formats = ["html"]
    description = "代码文件 → 语法高亮 HTML"
    dependencies = []  # pygments 可选，有 fallback

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        code = input_path.read_text(encoding="utf-8")
        lang = options.get("language") or LANG_MAP.get(input_path.suffix.lstrip("."), "text")

        css, body = highlight_code(code, lang)

        template = Path(__file__).parent.parent / "templates" / "base.html"
        if template.exists():
            html = template.read_text(encoding="utf-8")
        else:
            html = "<html><head><title>{{TITLE}}</title>{{EXTRA_HEAD}}</head><body>{{CONTENT}}</body></html>"

        html = (
            html
            .replace("{{TITLE}}", f"{input_path.name} - Syntax Highlight")
            .replace("{{EXTRA_HEAD}}", f"<style>{css}</style>")
            .replace("{{CONTENT}}", body)
        )

        output_path.write_text(html, encoding="utf-8")
        return ConvertResult(True, output_path=output_path, message=f"代码已高亮为 HTML ({lang})")


@register
class CodeToImage(BaseConverter):
    name = "code-image"
    source_formats = _CODE_FORMATS
    target_formats = ["png", "jpeg", "jpg"]
    description = "代码文件 → 语法高亮图片"
    dependencies = ["playwright"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        from .renderer import html_to_image

        code = input_path.read_text(encoding="utf-8")
        lang = options.get("language") or LANG_MAP.get(input_path.suffix.lstrip("."), "text")

        css, body = highlight_code(code, lang)

        html = f"""<!DOCTYPE html><html><head>
        <meta charset="UTF-8">
        <style>
            body {{ margin: 0; padding: 20px; background: #272822; }}
            {css}
        </style>
        </head><body>{body}</body></html>"""

        html_to_image(html, output_path, selector=".highlight, pre", **options)
        return ConvertResult(True, output_path=output_path, message=f"代码已高亮为图片 ({lang})")
