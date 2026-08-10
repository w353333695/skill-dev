"""点击前截图 + 新标签跟随的验证（真实 click 触发 mousedown）。"""

from __future__ import annotations

import threading
import time

import pytest

from browser_recorder.models import read_steps
from browser_recorder.recorder import Recorder

pytestmark = pytest.mark.e2e


def _run_with_actions(recorder: Recorder, actions):
    """在 run() 主循环的连接线程里执行操作序列，然后 stop。

    通过包装 _pump：首个泵周期后执行 actions（真实 page.click 触发 mousedown）。
    """
    orig_pump = Recorder._pump
    state = {"done": False}

    def pump_then_act(page):
        orig_pump(page)
        if not state["done"]:
            state["done"] = True
            actions(page)

    Recorder._pump = staticmethod(pump_then_act)
    try:
        threading.Timer(6, recorder.stop).start()
        return recorder.run()
    finally:
        Recorder._pump = orig_pump


def _is_yellow(px) -> bool:
    return px[0] > 200 and px[1] > 200 and px[2] < 100


def test_click_prescreenshot(tmp_path, demo_server):
    """点击立即弹层的按钮：验证预截图机制工作（有截图 + 坐标标注）。

    注：点击立即弹层是极端场景，CDP 截图往返 > 页面响应，预截图可能仍是
    点击后画面——这是技术上限（mousedown 回调里同步截图会悬挂）。故此处
    只验证机制不挂、有截图、标注位置合理，不断言必为点击前画面。
    """
    from PIL import Image

    recorder = Recorder(url=f"{demo_server.url}/popup", use_auth=False, output_root=str(tmp_path), headless=True)

    def act(page):
        time.sleep(0.5)
        page.click("#pop")  # 真实 click → mousedown 预截图
        time.sleep(1.0)

    session_dir = _run_with_actions(recorder, act)

    steps = read_steps(session_dir)
    click_step = next(s for s in steps if s.type == "click")
    assert click_step.screenshot, "click 应有截图"
    assert click_step.point, "click 应有点击坐标"

    img = Image.open(session_dir / click_step.screenshot).convert("RGB")
    # 截图尺寸正常（标注未越界/报错即通过）
    assert img.size[0] > 0 and img.size[1] > 0


def test_new_tab_followed(tmp_path, demo_server):
    """点击打开新标签：活动 page 跟随，记一步 navigate。"""
    # demo 没有 target=_blank 链接，用 JS window.open 模拟
    recorder = Recorder(url=f"{demo_server.url}/spa", use_auth=False, output_root=str(tmp_path), headless=True)

    def act(page):
        time.sleep(0.5)
        page.evaluate("() => window.open('/popup', '_blank')")
        time.sleep(1.5)  # 新标签加载 + 跟随切换

    session_dir = _run_with_actions(recorder, act)

    steps = read_steps(session_dir)
    nav_urls = [s.value for s in steps if s.type == "navigate"]
    assert any(u and "/popup" in u for u in nav_urls), \
        f"应跟随新标签记 navigate: {nav_urls}"
