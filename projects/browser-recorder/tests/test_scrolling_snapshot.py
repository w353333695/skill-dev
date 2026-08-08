# tests/test_scrolling_snapshot.py
"""scrolling-snapshot：后台定时截图入环形缓冲，click emit 时取【点击前】最近帧，
解决"录制被动监听、_on_event 在 JS handler 后、抓不到点击前画面"的问题。

纯函数 _pick_pre_click_snapshot 的选择逻辑在此单测；后台 loop + _capture_for_action
的集成由 cli_smoke 覆盖。
"""
from browser_recorder.record.runner import _pick_pre_click_snapshot


def test_returns_latest_frame_before_emit():
    buf = [(100, b"a"), (200, b"b"), (300, b"c")]
    assert _pick_pre_click_snapshot(buf, emit_ts=250) == b"b"


def test_returns_none_if_all_frames_after_emit():
    buf = [(300, b"c"), (400, b"d")]
    assert _pick_pre_click_snapshot(buf, emit_ts=250) is None


def test_returns_none_for_empty_buffer():
    assert _pick_pre_click_snapshot([], emit_ts=250) is None


def test_frame_at_exact_emit_ts_excluded():
    """emit 时刻的帧可能已含点击副作用，不算'点击前'。"""
    buf = [(200, b"b"), (250, b"c")]
    assert _pick_pre_click_snapshot(buf, emit_ts=250) == b"b"


def test_picks_closest_before_when_gap_large():
    buf = [(100, b"a"), (500, b"e")]
    assert _pick_pre_click_snapshot(buf, emit_ts=400) == b"a"
