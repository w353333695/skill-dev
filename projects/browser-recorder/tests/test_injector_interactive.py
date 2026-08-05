# tests/test_injector_interactive.py
"""注入钩子点击捕获：A(自定义按钮标签名) + B(tabindex) + C(--capture-all-clicks 逃生)。

用真实浏览器跑 INJECT_SCRIPT，验证：
- `eo-button` 这类「零信号自定义按钮」(无 role/tabindex/cursor) 现在能被记（A: 标签名 -button）；
- 带 `tabindex` 的非按钮自定义元素能被记（B）；
- 纯 `<div>` 点空白默认不记（噪音过滤仍生效）；
- 开 `__br_capture_all` 后点空白也记（C 逃生）。
"""
import tempfile
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from browser_recorder.browser import launch, new_context
from browser_recorder.record.injector import INJECT_SCRIPT


HTML = """
<html><body>
  <eo-button id="eobtn" style="display:inline-block;padding:8px;">启用</eo-button>
  <my-widget id="tabbed" tabindex="0" style="display:inline-block;padding:8px;">widget</my-widget>
  <div id="blank" style="padding:8px;">空白区</div>
  <button id="nativebtn">原生</button>
</body></html>
"""


async def _collect_clicks(click_selectors, html=HTML, capture_all=False):
    """注入钩子到 HTML（file:// goto，会触发 init script），点若干选择器，返回 click 列表。"""
    d = Path(tempfile.mkdtemp()) / "t.html"
    d.write_text(html, encoding="utf-8")
    async with async_playwright() as pw:
        b = await launch(pw, headless=True)
        ctx = await new_context(b)
        page = await ctx.new_page()
        captured = []
        await page.expose_function("__br_emit", lambda ev: captured.append(ev))
        await page.expose_function("__br_flush", lambda: None)
        await page.expose_function("__br_stop", lambda: None)
        await ctx.add_init_script(INJECT_SCRIPT)
        if capture_all:
            await ctx.add_init_script("window.__br_capture_all = true;")
        await page.goto(f"file://{d}", wait_until="domcontentloaded")
        await page.wait_for_timeout(150)
        for sel in click_selectors:
            await page.locator(sel).first.click(timeout=3000)
            await page.wait_for_timeout(80)
        await b.close()
        return [ev.get("target_node") or {} for ev in captured if ev.get("type") == "click"]


@pytest.mark.asyncio
async def test_custom_button_tag_captured():
    """A: eo-button（零信号自定义按钮）能被记。"""
    clicks = await _collect_clicks(["#eobtn"])
    assert len(clicks) == 1
    assert clicks[0].get("tag") == "eo-button"


@pytest.mark.asyncio
async def test_tabindex_widget_captured():
    """B: 带 tabindex 的非按钮自定义元素能被记。"""
    clicks = await _collect_clicks(["#tabbed"])
    assert len(clicks) == 1


@pytest.mark.asyncio
async def test_blank_div_not_captured_by_default():
    """噪音过滤仍生效：点纯 div 默认不记。"""
    clicks = await _collect_clicks(["#blank"])
    assert clicks == []


@pytest.mark.asyncio
async def test_native_button_still_captured():
    """原生 button 不回归。"""
    clicks = await _collect_clicks(["#nativebtn"])
    assert len(clicks) == 1
    assert clicks[0].get("tag") == "button"


@pytest.mark.asyncio
async def test_capture_all_records_blank():
    """C: 开 --capture-all-clicks 后点空白也记（逃生）。"""
    clicks = await _collect_clicks(["#blank"], capture_all=True)
    assert len(clicks) == 1
