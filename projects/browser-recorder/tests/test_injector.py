# tests/test_injector.py
from browser_recorder.record import injector


def test_inject_script_present_and_neutral():
    s = injector.INJECT_SCRIPT
    assert isinstance(s, str) and len(s) > 100
    assert "addEventListener" in s
    assert "easyops" not in s.lower()


def test_build_event_normalizes_node():
    node = {"tag": "button", "css": "button.submit", "xpath": "//button",
            "role": "button", "name": "提交", "text": "提交",
            "bbox": {"x": 1, "y": 2, "w": 3, "h": 4}}
    ev = injector.build_event(node, type="click", value=None)
    assert ev["type"] == "click"
    assert ev["target_node"]["css"] == "button.submit"
    assert ev["target_node"]["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert ev["value"] is None
    assert "ts" in ev


def test_build_event_input_carries_value():
    node = {"tag": "input", "css": "#q"}
    ev = injector.build_event(node, type="input", value="hello")
    assert ev["type"] == "input"
    assert ev["value"] == "hello"


def test_inject_script_emits_input_finalize_on_focusout_and_blur():
    """I-6：INJECT_SCRIPT 必须监听 focusout/blur 发 input_finalize，
    否则最后一段未失焦的输入会丢失。"""
    s = injector.INJECT_SCRIPT
    assert "input_finalize" in s, "INJECT_SCRIPT 未发 input_finalize 事件"
    assert "focusout" in s, "INJECT_SCRIPT 未监听 focusout"
    assert "blur" in s, "INJECT_SCRIPT 未监听 blur"
    # __br_flush 必须存在：beforeunload 时触发挂起输入的 finalize
    assert "__br_flush" in s, "INJECT_SCRIPT 未调 __br_flush"


def test_inject_script_custom_button_and_tabindex_signals():
    """A+B+C：isInteractiveSelf 识别自定义按钮标签名(-button/-link 等)、tabindex、
    capture-all 逃生开关、composedPath 穿透 shadow。"""
    s = injector.INJECT_SCRIPT
    import re
    # A：标签名模式（平台中性，不硬编码厂商前缀）
    assert re.search(r"-\(button\|link\|tab\|menuitem\|option\|switch\)", s), \
        "INJECT_SCRIPT 未按标签名模式识别自定义按钮"
    # B：tabindex 作为交互信号
    assert "hasAttribute('tabindex')" in s
    # C：capture-all 逃生开关
    assert "__br_capture_all" in s
    # shadow 穿透
    assert "composedPath" in s
