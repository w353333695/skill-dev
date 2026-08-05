"""Markdown → HTML 转换器"""

import re
from pathlib import Path
from .base import BaseConverter, ConvertResult, register, load_template

# Mermaid 占位符前缀
_MERMAID_PLACEHOLDER = "MERMAID_BLOCK_{idx}_PLACEHOLDER"

# md 内代码块语法高亮的 Pygments 配色：浅底 friendly，协调 base.html 的浅底 pre
# （与 code_highlight.py 整文件高亮用的 monokai 深底区分场景）。
HIGHLIGHT_STYLE = "friendly"


def _codehilite_css() -> str:
    """生成 codehilite 代码高亮的 CSS（friendly 浅底，scope=.codehilite）。

    无 pygments 或失败时返回空串，调用方据此决定是否注入 <style>。
    """
    try:
        from pygments.formatters import HtmlFormatter
        return HtmlFormatter(style=HIGHLIGHT_STYLE).get_style_defs(".codehilite")
    except Exception:
        return ""


def _extract_mermaid_blocks(md_text: str) -> tuple[str, list[str]]:
    """
    从 Markdown 中提取 mermaid 代码块，替换为占位符。
    返回 (处理后的文本, mermaid代码列表)
    """
    blocks = []
    def replacer(m):
        blocks.append(m.group(1).strip())
        placeholder = _MERMAID_PLACEHOLDER.format(idx=len(blocks) - 1)
        return f"\n\n{placeholder}\n\n"
    text = re.sub(r"```mermaid\s*\n(.*?)```", replacer, md_text, flags=re.DOTALL)
    return text, blocks


def _restore_mermaid_blocks(html: str, blocks: list[str]) -> str:
    """将占位符替换为 mermaid div"""
    for i, code in enumerate(blocks):
        placeholder = _MERMAID_PLACEHOLDER.format(idx=i)
        mermaid_div = f'<div class="mermaid">\n{code}\n</div>'
        html = html.replace(f"<p>{placeholder}</p>", mermaid_div)
        html = html.replace(placeholder, mermaid_div)
    return html


def md_to_html_body(md_text: str, with_mermaid: bool = True,
                    input_path: Path | None = None,
                    highlight: bool = True) -> tuple[str, bool, str]:
    """
    将 Markdown 转为 HTML body 内容。
    返回 (html, has_mermaid, extra_css)

    Args:
        md_text: Markdown 文本
        with_mermaid: 是否处理 mermaid 代码块
        input_path: 源 md 文件路径；传入时会把相对路径的本地图片
            内嵌为 base64 data URI，避免渲染时相对路径失效
        highlight: 是否对 ```代码块``` 做语法高亮（codehilite + Pygments）。
            为 True 且文档真含代码块时，extra_css 返回高亮 CSS 供调用方注入。

    extra_css: 代码高亮 CSS（仅 highlight=True、含代码块、pygments 可用时非空）。
    """
    # 先提取 mermaid 块（必须在 markdown.markdown 之前，否则 codehilite 会误染）
    has_mermaid = "```mermaid" in md_text
    if has_mermaid and with_mermaid:
        md_text, mermaid_blocks = _extract_mermaid_blocks(md_text)
    else:
        mermaid_blocks = []

    # 将相对路径的本地图片内嵌为 base64，确保渲染/分发时图片不丢失
    if input_path is not None:
        md_text = _embed_local_images(md_text, input_path)

    extra_css = ""
    try:
        import markdown
        # extra 内含 tables/fenced_code/footnotes/def_list/attr_list/abbr；
        # 再叠 admonition(告示块)/smarty(智能标点)/toc(目录锚点)。
        extensions = ["extra", "admonition", "smarty", "toc"]
        extension_configs: dict = {}
        if highlight:
            extensions.append("codehilite")
            # 关闭乱猜语言和行号：文章内代码块按标注语言高亮、不要行号
            # （整文件高亮 code_highlight.py 走 linenos=True，场景不同）
            extension_configs["codehilite"] = {"guess_lang": False, "linenums": False}
        html = markdown.markdown(
            md_text, extensions=extensions, extension_configs=extension_configs
        )
        # 仅当确有代码块被高亮时才生成 CSS，避免无代码块文档注入空样式
        if highlight and "codehilite" in html:
            extra_css = _codehilite_css()
    except ImportError:
        html = _fallback_md_to_html(md_text)

    # 还原 mermaid 块
    if mermaid_blocks:
        html = _restore_mermaid_blocks(html, mermaid_blocks)

    return html, has_mermaid, extra_css


def _embed_local_images(md_text: str, input_path: Path) -> str:
    """把 markdown 中的本地相对路径图片替换为 base64 data URI。

    仅处理本地文件（相对/绝对路径），跳过 http(s)/data 等 URL。
    找不到的文件保持原样，便于排查。

    Args:
        md_text: Markdown 文本
        input_path: 源 md 文件路径，用于解析相对路径
    """
    import base64

    def replacer(m):
        alt = m.group(1)
        src = m.group(2).strip()
        # 跳过网络/数据 URL
        if src.startswith(("http://", "https://", "data:", "mailto:")):
            return m.group(0)
        # 解析路径
        src_path = Path(src)
        if not src_path.is_absolute():
            src_path = (input_path.parent / src_path).resolve()
        if not src_path.exists():
            return m.group(0)  # 文件不存在，保留原文本便于排查
        # 按扩展名推断 MIME
        suffix = src_path.suffix.lower().lstrip(".")
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp",
            "bmp": "image/bmp",
        }
        mime = mime_map.get(suffix, "image/png")
        if suffix == "svg":
            # SVG 用文本内嵌，避免 base64 双重编码
            data = src_path.read_text(encoding="utf-8")
            return f'![{alt}](data:{mime};utf8,{data})'
        data = base64.b64encode(src_path.read_bytes()).decode("ascii")
        return f'![{alt}](data:{mime};base64,{data})'

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replacer, md_text)


def _fallback_md_to_html(md_text: str) -> str:
    """无 markdown 库时的基础转换"""
    import html as html_lib
    lines = md_text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # 标题
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            result.append(f"<h{level}>{html_lib.escape(m.group(2))}</h{level}>")
            i += 1
            continue

        # 代码块
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(html_lib.escape(lines[i]))
                i += 1
            i += 1
            cls = f' class="language-{lang}"' if lang else ""
            result.append(f"<pre><code{cls}>{'&#10;'.join(code_lines)}</code></pre>")
            continue

        # 表格
        if "|" in line and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            rows = []
            while i < len(lines) and "|" in lines[i]:
                row_text = lines[i].strip()
                if not re.match(r"^\|[\s\-:|]+\|$", row_text):
                    cells = [c.strip() for c in row_text.strip("|").split("|")]
                    rows.append(cells)
                i += 1
            result.append("<table>")
            for r_idx, row in enumerate(rows):
                result.append("<tr>")
                tag = "th" if r_idx == 0 else "td"
                for cell in row:
                    result.append(f"<{tag}>{html_lib.escape(cell)}</{tag}>")
                result.append("</tr>")
            result.append("</table>")
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 普通段落
        escaped = html_lib.escape(line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
        escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
        result.append(f"<p>{escaped}</p>")
        i += 1

    return "\n".join(result)


def build_full_html(body: str, title: str = "Document", extra_head: str = "") -> str:
    """用模板包装 HTML body"""
    template = load_template("base.html")
    return (
        template
        .replace("{{TITLE}}", title)
        .replace("{{CONTENT}}", body)
        .replace("{{EXTRA_HEAD}}", extra_head)
    )


@register
class MdToHtml(BaseConverter):
    name = "md-html"
    source_formats = ["md", "markdown"]
    target_formats = ["html"]
    description = "Markdown 转 HTML (带样式)"
    dependencies = []

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        text = input_path.read_text(encoding="utf-8")
        title = options.get("title", input_path.stem)

        body, has_mermaid, extra_css = md_to_html_body(
            text,
            input_path=input_path,
            highlight=options.get("highlight", True),
        )

        # 高亮 CSS 与 mermaid 脚本都累加进 <head>（互不冲突）
        extra_head = ""
        if extra_css:
            extra_head += f"<style>\n{extra_css}\n</style>\n"
        if has_mermaid:
            extra_head += (
                '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>\n'
                '<script>mermaid.initialize({startOnLoad: true});</script>'
            )

        html = build_full_html(body, title, extra_head)
        output_path.write_text(html, encoding="utf-8")

        return ConvertResult(True, output_path=output_path, message="Markdown 已转为 HTML")
