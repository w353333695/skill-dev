# tests/test_screenshot_policy.py
from browser_recorder.record.screenshot import ScreenshotPlanner
from browser_recorder.config import DEFAULT_SCREENSHOT_POLICY


def make_planner():
    return ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)


def test_click_captures_before_and_after():
    # click 截 before+after：before 抢在导航/异步渲染前（点击瞬间上下文），
    # after 等加载完。
    p = make_planner()
    assert p.should_capture({"type": "click"}) == ["before", "after"]


def test_input_captures_only_after():
    p = make_planner()
    assert p.should_capture({"type": "input"}) == ["after"]


def test_scroll_captures_nothing():
    p = make_planner()
    assert p.should_capture({"type": "scroll"}) == []


def test_input_aggregation_collects_until_finalize():
    p = make_planner()
    # 连续输入字符：每次返回 False（聚合中，不落库不产图）
    assert p.consume_input_chunk("k", "a") is False
    assert p.consume_input_chunk("k", "b") is False
    # finalize 标记聚合结束
    assert p.consume_input_chunk("k", "ab", finalize=True) is True
    assert p.get_input_value() == "ab"


def test_input_aggregation_resets_after_finalize():
    p = make_planner()
    p.consume_input_chunk("k", "x")
    p.consume_input_chunk("k", "x", finalize=True)
    # 新一轮
    assert p.consume_input_chunk("k", "y") is False
    assert p.get_input_value() == "y"


def test_input_aggregation_key_change_finalizes_previous():
    p = make_planner()
    p.consume_input_chunk("field1", "a")
    # 切换到另一个元素 → 上一段聚合结束
    assert p.consume_input_chunk("field2", "b", finalize_prev=True)  # 切换时返回上一段结果
    assert p.get_pending_value("field1") == "a"


def test_dedup_consecutive_same_fingerprint():
    p = make_planner()
    assert not p.is_duplicate("click", "css:a", ts_ms=1000)
    assert p.is_duplicate("click", "css:a", ts_ms=1200)   # 同指纹同 type，窗内
    assert not p.is_duplicate("click", "css:b", ts_ms=1300)  # 不同指纹
    assert not p.is_duplicate("click", "css:a", ts_ms=2000)  # 超出窗口


def test_dedup_different_type_not_duplicate():
    p = make_planner()
    p.is_duplicate("click", "css:a", 1000)
    assert not p.is_duplicate("input", "css:a", 1100)
