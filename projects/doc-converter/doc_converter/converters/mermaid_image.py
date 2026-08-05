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
