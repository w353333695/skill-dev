"""
Playwright 渲染工具模块。

多个转换器共用的浏览器渲染逻辑，避免重复代码。
提供: HTML→PDF, HTML→截图(PNG) 两个核心能力。
"""

import tempfile
from pathlib import Path


def _ensure_playwright():
    """确保 playwright 可用"""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        raise ImportError(
            "需要安装 playwright: pip install playwright && playwright install chromium"
        )


def html_to_pdf(html_content: str, output_path: Path, **options) -> Path:
    """
    将 HTML 内容渲染为 PDF。

    Args:
        html_content: 完整 HTML 字符串
        output_path: PDF 输出路径
        options:
            width: 页面宽度 (如 "210mm")
            height: 页面高度 (如 "297mm")
            margin: 页边距 dict (top, bottom, left, right)
            landscape: 横向 (默认 False)
            scale: 缩放比例 (默认 1)
    """
    _ensure_playwright()
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html_content)
        tmp_html = f.name

    pdf_options = {
        "path": str(output_path),
        "format": "A4",
        "print_background": True,
        "margin": options.get("margin", {
            "top": "15mm", "bottom": "15mm",
            "left": "15mm", "right": "15mm",
        }),
    }
    if options.get("landscape"):
        pdf_options["landscape"] = True
    if options.get("scale"):
        pdf_options["scale"] = options["scale"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{tmp_html}")
        page.wait_for_load_state("load")
        # 等待可能的异步渲染 (如 Mermaid)
        wait_ms = options.get("wait_ms", 1000)
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        page.pdf(**pdf_options)
        browser.close()

    Path(tmp_html).unlink(missing_ok=True)
    return output_path


def html_to_image(html_content: str, output_path: Path, **options) -> Path:
    """
    将 HTML 内容渲染为图片 (PNG/JPEG)。

    Args:
        html_content: 完整 HTML 字符串
        output_path: 图片输出路径
        options:
            selector: CSS 选择器，截取特定元素 (默认 "body")
            width: 视口宽度 (默认 1200)
            height: 视口高度 (默认 800)
            device_scale_factor: 设备像素比 (默认 2, 高清)
            wait_ms: 渲染等待时间 (默认 2000)
    """
    _ensure_playwright()
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html_content)
        tmp_html = f.name

    selector = options.get("selector", "body")
    width = options.get("width", 1200)
    height = options.get("height", 800)
    scale = options.get("device_scale_factor", 2)
    wait_ms = options.get("wait_ms", 2000)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
        )
        page.goto(f"file://{tmp_html}")
        page.wait_for_load_state("load")
        if wait_ms:
            page.wait_for_timeout(wait_ms)

        element = page.query_selector(selector)
        target = element if element else page
        target.screenshot(path=str(output_path))
        browser.close()

    Path(tmp_html).unlink(missing_ok=True)
    return output_path
