"""Mermaid → PNG/SVG 转换器"""

import json
import re
import tempfile
from pathlib import Path
from .base import BaseConverter, ConvertResult, register


def _build_mermaid_html(code: str, theme: str = "default") -> str:
    """构建 Mermaid 渲染 HTML，使用 mermaid.render() API 确保完整渲染"""
    code_json = json.dumps(code.strip())
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  body {{ margin: 0; padding: 40px; background: #fff; }}
  #container {{ display: inline-block; }}
</style>
</head><body>
<div id="container"></div>
<script>
  mermaid.initialize({{
    startOnLoad: false,
    theme: "{theme}",
    securityLevel: "loose",
    flowchart: {{ useMaxWidth: false }},
    sequence: {{ useMaxWidth: false }},
    gantt: {{ useMaxWidth: false }}
  }});
  async function render() {{
    const code = {code_json};
    const {{ svg }} = await mermaid.render("diagram", code);
    document.getElementById("container").innerHTML = svg;
  }}
  render();
</script>
</body></html>"""


def extract_mermaid_blocks(text: str) -> list[str]:
    """从 Markdown 中提取所有 mermaid 代码块"""
    pattern = r"```mermaid\s*\n(.*?)```"
    return re.findall(pattern, text, re.DOTALL)


def render_mermaid_to_image(code: str, output_path: Path, theme: str = "default", **options) -> Path:
    """将单个 mermaid 代码渲染为高清图片，返回输出路径"""
    from .renderer import html_to_image
    html = _build_mermaid_html(code, theme)
    # 默认高清参数
    options.setdefault("width", 3200)
    options.setdefault("device_scale_factor", 4)
    options.setdefault("wait_ms", 5000)
    options.setdefault("selector", "#container svg")
    html_to_image(html, output_path, **options)
    return output_path


def render_mermaid_blocks(blocks: list[str], out_dir, theme: str = "default", **options) -> list[Path]:
    """批量渲染 mermaid 代码块为 PNG，返回图片路径列表。

    单块渲染复用 render_mermaid_to_image；供 md-docx / md-pdf 等"预先光栅化
    mermaid 再嵌入"的路径共用（区别于 md-html 的浏览器内客户端渲染）。
    playwright 缺失时由底层抛 ImportError，由调用方决定是否降级。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for i, code in enumerate(blocks):
        img = out_dir / f"mermaid_{i}.png"
        render_mermaid_to_image(code, img, theme, **options)
        images.append(img)
    return images


def inline_mermaid_as_images(md_text: str, out_dir, theme: str = "default", **options) -> tuple[str, list[Path]]:
    """提取 md 中 mermaid 块 → 逐块渲染 PNG → 占位符替换为图片引用。

    供 pandoc/typst 等"非浏览器渲染"路径使用：mermaid 先光栅化再以 ![]() 嵌入，
    pandoc 转 typst 后由 typst image 内联。返回 (处理后的 md, 成功渲染的图片路径列表)。

    逐块容错：单块渲染失败（如某 mermaid 类型/语法不受支持、CDN 超时）时，该块
    还原为 ```mermaid 代码块，不影响其他块继续嵌入，避免"一坏全坏"。
    """
    from pathlib import Path
    from .md_html import _extract_mermaid_blocks, _MERMAID_PLACEHOLDER
    text, blocks = _extract_mermaid_blocks(md_text)
    if not blocks:
        return md_text, []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for i, code in enumerate(blocks):
        placeholder = _MERMAID_PLACEHOLDER.format(idx=i)
        try:
            img = out_dir / f"mermaid_{i}.png"
            render_mermaid_to_image(code, img, theme, **options)
            images.append(img)
            text = text.replace(placeholder, f"![mermaid 图 {i + 1}]({img.name})")
        except Exception:
            # 该块渲染失败 → 还原为代码块，不阻断其余块
            text = text.replace(placeholder, f"```mermaid\n{code}\n```")
    return text, images


@register
class MermaidToImage(BaseConverter):
    name = "mermaid-image"
    source_formats = ["mermaid", "mmd", "md"]
    target_formats = ["png", "svg", "jpeg", "jpg"]
    description = "Mermaid 图表转图片 (PNG/SVG/JPEG)"
    dependencies = ["playwright"]

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        text = input_path.read_text(encoding="utf-8")
        theme = options.get("theme", "default")

        # 提取模式: 从 MD 中提取 mermaid 块
        if options.get("extract") == "mermaid" or input_path.suffix in (".md", ".markdown"):
            blocks = extract_mermaid_blocks(text)
            if not blocks:
                return ConvertResult(False, message="未找到 mermaid 代码块")
            if len(blocks) > 1:
                results = []
                for i, block in enumerate(blocks):
                    out = output_path.with_stem(f"{output_path.stem}_{i+1}")
                    render_mermaid_to_image(block, out, theme, **options)
                    results.append(str(out))
                return ConvertResult(
                    True, output_path=output_path.parent,
                    message=f"已生成 {len(results)} 张图片: {', '.join(results)}"
                )
            code = blocks[0]
        else:
            code = text

        render_mermaid_to_image(code, output_path, theme, **options)
        return ConvertResult(True, output_path=output_path, message="Mermaid 图表已转为图片")
