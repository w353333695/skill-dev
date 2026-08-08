# tests/test_export_dedupe.py
"""export 读 trace 后去双录：同名 session 二次录制会 append 旧 trace，导致同一
screenshot.after 被多段 action 引用 → marks_by_file 在一张图上画多个序号/框。

去重策略：同一 screenshot.after 保留【最后】一条 action——因为二次录制的截图会
覆盖同名文件，故最后一条 action 与当前截图匹配。
"""
from browser_recorder.models import Action, Target
from browser_recorder.export.runner import dedupe_double_recorded_actions


def _a(seq, type_, shot, ts=0, bbox=None):
    return Action(
        seq=seq, ts=ts, type=type_, url="u",
        target=Target(css="#x", bbox=bbox or {"x": 1, "y": 1, "w": 2, "h": 2}),
        screenshot={"after": shot} if shot else None,
    )


def test_dedupe_keeps_last_action_per_screenshot():
    """双录：同 screenshot.after 两条 action，只保留最后一条。"""
    actions = [
        _a(4, "click", "step-0004-after.png", ts=100),
        _a(4, "input", "step-0004-after.png", ts=200),
    ]
    out = dedupe_double_recorded_actions(actions)
    assert len(out) == 1
    assert out[0].type == "input"   # 保留最后（与覆盖后的截图匹配）
    assert out[0].ts == 200


def test_dedupe_keeps_distinct_screenshots():
    """正常：不同 action 不同 screenshot，全部保留。"""
    actions = [
        _a(1, "click", "step-0001-after.png"),
        _a(2, "input", "step-0002-after.png"),
    ]
    out = dedupe_double_recorded_actions(actions)
    assert len(out) == 2


def test_dedupe_preserves_first_seen_order_with_last_value():
    """去重后顺序按首次出现位置，但值取最后一次。"""
    actions = [
        _a(1, "click", "step-0001-after.png", ts=10),
        _a(2, "input", "step-0002-after.png", ts=20),
        _a(1, "click", "step-0001-after.png", ts=30),   # 双录第一帧
        _a(2, "input", "step-0002-after.png", ts=40),   # 双录第二帧
    ]
    out = dedupe_double_recorded_actions(actions)
    assert len(out) == 2
    assert out[0].screenshot["after"] == "step-0001-after.png"
    assert out[0].ts == 30   # 最后
    assert out[1].screenshot["after"] == "step-0002-after.png"
    assert out[1].ts == 40


def test_dedupe_action_without_screenshot_kept_by_seq():
    """无截图的 action（如 navigation）按 seq 去重，保留最后。"""
    actions = [
        _a(7, "navigation", None, ts=10),
        _a(7, "navigation", None, ts=20),
    ]
    out = dedupe_double_recorded_actions(actions)
    assert len(out) == 1
    assert out[0].ts == 20


def test_filter_empty_input_removes_blank_keeps_real():
    """空/纯空白 input 被过滤；click 和有内容的 input 保留。"""
    from browser_recorder.export.runner import filter_empty_input

    def mk(seq, t, val=None):
        return Action(seq=seq, ts=0, type=t, url="u", value=val,
                      target=Target(css="#a", bbox={"x": 1, "y": 1, "w": 2, "h": 2}),
                      screenshot={"after": f"s{seq}.png"})

    out = filter_empty_input([
        mk(1, "click"),
        mk(2, "input", ""),        # 空 → 过滤
        mk(3, "input", "abc"),     # 有内容 → 保留
        mk(4, "input", None),      # None → 过滤
        mk(5, "input", "   "),     # 纯空白 → 过滤
    ])
    assert [a.seq for a in out] == [1, 3]


def test_export_clears_stale_annotated_on_reexport(tmp_path):
    """重 export 清空旧标注图，避免已过滤/去重 action 的标注图残留
    （用户报 step-0010 被过滤但旧标注图仍在）。"""
    import json as _json
    from browser_recorder.export import runner as exp
    from browser_recorder import paths

    saved = paths.TMP_ROOT
    paths.TMP_ROOT = tmp_path / "tmp"
    try:
        sd = paths.session_dir("s1")
        sd.mkdir(parents=True)
        a = Action(seq=1, ts=0, type="click", url="u",
                   target=Target(css="#g", bbox={"x": 1, "y": 1, "w": 2, "h": 2}),
                   screenshot={"after": "step-0001-after.png"})
        (sd / "trace.jsonl").write_text(_json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
        (sd / "requests.jsonl").write_text("")
        (sd / "meta.json").write_text(_json.dumps({"url": "u"}))
        out_root = tmp_path / "out" / ".browser-recorder"
        ann = out_root / "exports" / "s1" / "screenshots_annotated"
        ann.mkdir(parents=True)
        (ann / "step-9999-after.png").write_bytes(b"STALE")   # 模拟上次 export 的残留标注图
        exp.run_export(session="s1", out_dir=out_root, name="s1", filter_path=None,
                       keep_raw_bodies=False, annotate_style="verbose",
                       annotate_opacity=60, tmp_root=tmp_path / "tmp")
        assert not (ann / "step-9999-after.png").exists(), "重 export 应清空旧标注图"
    finally:
        paths.TMP_ROOT = saved
