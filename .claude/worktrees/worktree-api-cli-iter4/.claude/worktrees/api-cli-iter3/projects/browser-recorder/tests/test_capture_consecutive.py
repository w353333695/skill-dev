# tests/test_capture_consecutive.py
"""Bug 3：连续点击同一位置（哪怕间隔数秒）应被过滤；中间有其它动作则保留。"""
from browser_recorder.record import capture
from browser_recorder.record.screenshot import ScreenshotPlanner
from browser_recorder.config import DEFAULT_SCREENSHOT_POLICY


def _planner():
    return ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)


def _node(css="#dup", bbox=None):
    return {"tag": "button", "css": css,
            "bbox": bbox or {"x": 10, "y": 10, "w": 20, "h": 20}}


def test_consecutive_same_position_click_dropped_even_seconds_apart():
    """同位置连点，间隔远超 500ms 去重窗，仍应丢弃第二次。"""
    e2a = capture.EventToAction(_planner())
    node = _node()
    a1 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1000}, "u", {})
    a2 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 5000}, "u", {})  # 4s 后
    assert a1 is not None and a1.type == "click"
    assert a2 is None, "连续同位置点击（间隔数秒）应被过滤"


def test_same_position_click_kept_when_other_action_between():
    """两次同位置点击之间夹了其它动作（输入）→ 不算连续，第二次保留。"""
    e2a = capture.EventToAction(_planner())
    node = _node()
    a1 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1000}, "u", {})
    # 在两次点击之间输入（打断「连续」）
    e2a.process({"type": "input", "target_node": {"tag": "input", "css": "#q",
                  "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}, "value": "x", "ts": 2000}, "u", {})
    e2a.process({"type": "input_finalize", "target_node": {"tag": "input", "css": "#q"},
                 "value": "x", "ts": 2100}, "u", {})
    a3 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 5000}, "u", {})
    assert a1 is not None
    assert a3 is not None, "中间有其它动作后，同位置点击应保留"


def test_different_position_clicks_all_kept():
    """不同元素/不同位置的连续点击都保留。"""
    e2a = capture.EventToAction(_planner())
    a1 = e2a.process({"type": "click", "target_node": _node(css="#a", bbox={"x": 10, "y": 10, "w": 20, "h": 20}),
                      "value": None, "ts": 1000}, "u", {})
    a2 = e2a.process({"type": "click", "target_node": _node(css="#b", bbox={"x": 500, "y": 500, "w": 20, "h": 20}),
                      "value": None, "ts": 1100}, "u", {})
    assert a1 is not None and a2 is not None


def test_same_position_via_fingerprint_when_bbox_drifts():
    """bbox 有轻微漂移但选择器指纹相同（同元素）→ 视为同位置过滤。"""
    e2a = capture.EventToAction(_planner())
    a1 = e2a.process({"type": "click", "target_node": _node(css="#dup", bbox={"x": 10, "y": 10, "w": 20, "h": 20}),
                      "value": None, "ts": 1000}, "u", {})
    a2 = e2a.process({"type": "click", "target_node": _node(css="#dup", bbox={"x": 11, "y": 10, "w": 20, "h": 20}),
                      "value": None, "ts": 5000}, "u", {})
    assert a1 is not None
    assert a2 is None


def test_null_selector_different_position_kept():
    """选择器缺失（旧数据 null css）+ 不同 bbox → 不应误并为同位置。"""
    e2a = capture.EventToAction(_planner())
    n1 = {"tag": None, "css": None, "bbox": {"x": 10, "y": 10, "w": 20, "h": 20}}
    n2 = {"tag": None, "css": None, "bbox": {"x": 400, "y": 300, "w": 20, "h": 20}}
    a1 = e2a.process({"type": "click", "target_node": n1, "value": None, "ts": 1000}, "u", {})
    a2 = e2a.process({"type": "click", "target_node": n2, "value": None, "ts": 1100}, "u", {})
    assert a1 is not None and a2 is not None, "null 选择器 + 不同位置不应被过滤"
