# browser_recorder/selectors.py
"""多维度选择器：从 DOM 节点信息构造 Target、计算去重指纹、回退定位。

回退定位 locate() 依赖 Playwright page，集成测试覆盖；本模块单测聚焦纯函数。
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from .models import Target

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


def build_target_from_dom(node_info: dict[str, Any]) -> Target:
    """注入钩子回传的 DOM 节点字典 → Target。"""
    return Target(
        role_selector=node_info.get("role_selector"),
        css=node_info.get("css"),
        xpath=node_info.get("xpath"),
        text=node_info.get("text"),
        bbox=node_info.get("bbox"),
        tag=node_info.get("tag"),
        role=node_info.get("role"),
        name=node_info.get("name"),
    )


def target_fingerprint(target: Target) -> str:
    """去重指纹：优先 css，回退 xpath，再回退 tag+text（无选择器时附 bbox 兜底）。

    有 css/xpath 时**忽略 bbox**（位置变化不代表新元素，见 test_stable_across_bbox_change）。
    无 css/xpath 时（如旧录制只有 bbox），bbox 是唯一身份信号：附上位置，避免不同位置的
    null-selector 点击被误并成一个。
    """
    if target.css:
        return f"css:{target.css}"
    if target.xpath:
        return f"xpath:{target.xpath}"
    base = f"tag:{target.tag or ''}|text:{target.text or ''}"
    if target.bbox:
        b = target.bbox
        base += f"|bbox:{b.get('x')},{b.get('y')},{b.get('w')},{b.get('h')}"
    return base


async def locate(page: "Page", target: Target) -> "Locator | None":
    """按 role→css→xpath 优先级回退定位。全失败返回 None。"""
    candidates: list[str] = []
    if target.role_selector:
        candidates.append(target.role_selector)
    if target.css:
        candidates.append(target.css)
    if target.xpath:
        candidates.append(target.xpath)
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="visible", timeout=1000)
            return loc
        except Exception:
            continue
    # 坐标兜底不在此返回伪定位器；executor 用 page.mouse.click(x,y) 处理
    return None
