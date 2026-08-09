"""测试 JS 注入器."""
from browser_recorder.injector import RECORDER_JS


def test_recorder_js_is_non_empty_string():
    """注入脚本非空."""
    assert isinstance(RECORDER_JS, str)
    assert len(RECORDER_JS) > 100


def test_recorder_js_contains_core_functions():
    """脚本包含核心函数."""
    assert "addEventListener" in RECORDER_JS or "attachEvent" not in RECORDER_JS
    assert "__recorder_push__" in RECORDER_JS
    assert "flush" in RECORDER_JS.lower()


def test_recorder_js_contains_event_types():
    """脚本监听必要事件类型."""
    assert "click" in RECORDER_JS.lower()
    assert "input" in RECORDER_JS.lower()
    assert "change" in RECORDER_JS.lower()
    assert "submit" in RECORDER_JS.lower()


def test_recorder_js_contains_composed_path():
    """脚本使用 composedPath 穿透 Shadow DOM."""
    assert "composedPath" in RECORDER_JS


def test_recorder_js_contains_mutation_observer():
    """脚本包含 MutationObserver DOM 稳定检测."""
    assert "MutationObserver" in RECORDER_JS


def test_recorder_js_contains_beforeunload():
    """脚本监听 beforeunload flush."""
    assert "beforeunload" in RECORDER_JS
