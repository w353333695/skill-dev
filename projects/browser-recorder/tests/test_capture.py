# tests/test_capture.py
import logging
from browser_recorder.record import capture
from browser_recorder.record.screenshot import ScreenshotPlanner
from browser_recorder.config import DEFAULT_SCREENSHOT_POLICY


def test_is_static_by_suffix():
    assert capture.is_static("https://x.com/a.js", "script")
    assert capture.is_static("https://x.com/a.css", "stylesheet")
    assert capture.is_static("https://x.com/a.png", "image")
    assert capture.is_static("data:image/png;base64,xxx", "image")
    assert capture.is_static("blob:https://x.com/abc", "other")


def test_is_not_static_for_api():
    assert not capture.is_static("https://x.com/api/users", "xhr")
    assert not capture.is_static("https://x.com/api/list?q=1", "fetch")


def test_event_to_action_click():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    ev = {"type": "click", "target_node": {"tag": "button", "css": "#go", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}, "value": None, "ts": 1000}
    a = e2a.process(ev, url="https://x.com/p", page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0})
    assert a is not None
    assert a.type == "click"
    assert a.target.css == "#go"


def test_event_to_action_dedup_consecutive_click():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    node = {"tag": "button", "css": "#go", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    a1 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1000}, "https://x.com/p", {})
    a2 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1100}, "https://x.com/p", {})
    assert a1 is not None
    assert a2 is None  # 去重


def test_click_then_submit_coalesced():
    """点提交按钮会先 click(button) 后 submit(form)；submit 紧跟 click 时合并，
    只保留 click（bbox 是按钮），丢弃 submit。通用 DOM 行为，不耦合系统。"""
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    btn = {"tag": "button", "css": "#submit", "bbox": {"x": 10, "y": 10, "w": 40, "h": 20}}
    form = {"tag": "form", "css": "#f", "bbox": {"x": 0, "y": 0, "w": 600, "h": 400}}
    a_click = e2a.process({"type": "click", "target_node": btn, "value": None, "ts": 1000},
                          "https://x.com/p", {})
    a_submit = e2a.process({"type": "submit", "target_node": form, "value": None, "ts": 1050},
                           "https://x.com/p", {})
    assert a_click is not None and a_click.type == "click"
    assert a_click.target.bbox["w"] == 40        # 保留的是按钮（小 bbox），不是整张表单
    assert a_submit is None                        # submit 被合并丢弃


def test_submit_without_click_kept():
    """按 Enter 提交（无前置 click）→ 只剩 submit，应保留（不能误删）。"""
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    form = {"tag": "form", "css": "#f", "bbox": {"x": 0, "y": 0, "w": 600, "h": 400}}
    a = e2a.process({"type": "submit", "target_node": form, "value": None, "ts": 1000},
                    "https://x.com/p", {})
    assert a is not None and a.type == "submit"


def test_submit_after_stale_click_kept():
    """click 与 submit 间隔超过合并窗口（非同一次操作）→ submit 保留。"""
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    btn = {"tag": "button", "css": "#x", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    form = {"tag": "form", "css": "#f", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    e2a.process({"type": "click", "target_node": btn, "value": None, "ts": 1000}, "https://x.com/p", {})
    a = e2a.process({"type": "submit", "target_node": form, "value": None,
                     "ts": 1000 + capture.EventToAction.CLICK_SUBMIT_COALESCE_MS + 1},
                    "https://x.com/p", {})
    assert a is not None and a.type == "submit"


def test_event_to_action_input_aggregates():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    node = {"tag": "input", "css": "#q", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    # 连续输入字符（未失焦/未提交）应被聚合，不立即产出 Action
    r1 = e2a.process({"type": "input", "target_node": node, "value": "a", "ts": 1000}, "https://x.com/p", {})
    r2 = e2a.process({"type": "input", "target_node": node, "value": "ab", "ts": 1100}, "https://x.com/p", {})
    assert r1 is None
    assert r2 is None
    # 失焦（focusout）触发 finalize
    fin = e2a.process({"type": "input_finalize", "target_node": node, "value": "ab", "ts": 1200}, "https://x.com/p", {})
    assert fin is not None
    assert fin.type == "input"
    assert fin.value == "ab"


def test_capture_module_has_logger_not_silent_except(caplog):
    """M-5：NetworkCollector 不再静默 except Exception: pass，
    应该用 logging.getLogger 记录 debug，便于排障。"""
    assert isinstance(capture.logger, logging.Logger)
    assert capture.logger.name == "browser_recorder.record.capture"


def test_network_collector_accepts_keep_raw_bodies():
    """I-2：NetworkCollector 接受 keep_raw_bodies，开启后所有响应原始体落盘。"""
    class _FakePage:
        def on(self, *a, **kw): pass
    nc = capture.NetworkCollector(_FakePage(), lambda r: None,
                                  responses_dir=__import__("pathlib").Path("/tmp/x"),
                                  current_action_seq=lambda: None,
                                  keep_raw_bodies=True)
    assert nc.keep_raw_bodies is True
