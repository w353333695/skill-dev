# tests/test_export_structure.py
"""A3：build_segments 按 navigation/URL path 切段；run_export 写 structure.json。"""
import json
from pathlib import Path
from browser_recorder.models import Action, Target
from browser_recorder.export.structure import build_segments


def _act(seq, atype, url):
    return Action(seq=seq, ts=0, type=atype, url=url,
                  target=Target(css="#x", bbox={"x": 0, "y": 0, "w": 1, "h": 1}))


def test_single_page_single_segment():
    actions = [_act(1, "click", "https://x.com/a"), _act(2, "input", "https://x.com/a")]
    s = build_segments(actions, [])
    assert s["actions_total"] == 2
    assert len(s["segments"]) == 1
    assert s["segments"][0]["action_seqs"] == [1, 2]
    assert s["segments"][0]["page_url"] == "https://x.com/a"
    assert s["segments"][0]["entry_action_seq"] == 1


def test_navigation_starts_new_segment():
    actions = [
        _act(1, "click", "https://x.com/a"),
        _act(2, "navigation", "https://x.com/b"),
        _act(3, "click", "https://x.com/b"),
    ]
    s = build_segments(actions, [])
    assert len(s["segments"]) == 2
    assert s["segments"][0]["action_seqs"] == [1]
    assert s["segments"][1]["action_seqs"] == [2, 3]
    assert s["segments"][1]["entry_action_seq"] == 2


def test_url_path_change_starts_new_segment():
    # query 变化不算新页（path 相同），仅 path 变化才切。
    actions = [
        _act(1, "click", "https://x.com/list?q=1"),
        _act(2, "click", "https://x.com/list?q=2"),    # 同 path，同段
        _act(3, "click", "https://x.com/detail/1"),    # path 变，新段
    ]
    s = build_segments(actions, [])
    assert len(s["segments"]) == 2
    assert s["segments"][0]["action_seqs"] == [1, 2]
    assert s["segments"][1]["action_seqs"] == [3]


def test_linked_endpoints_dedup_per_segment():
    actions = [_act(1, "click", "https://x.com/a")]
    groups = [{"endpoint": {"method": "GET", "url_template": "/api/x", "param_path": []},
               "observations": 3, "linked_seq": [1]}]
    s = build_segments(actions, groups)
    assert s["endpoints_total"] == 1
    assert s["segments"][0]["linked_endpoints"] == [
        {"method": "GET", "url_template": "/api/x", "observations": 3}]


def test_empty_actions():
    s = build_segments([], [])
    assert s["segments"] == []
    assert s["actions_total"] == 0


def test_run_export_writes_structure_json(tmp_path: Path):
    from browser_recorder import paths
    from browser_recorder.export import runner as exp
    paths.TMP_ROOT = tmp_path / "tmp"
    sd = paths.session_dir("s1")
    sd.mkdir(parents=True, exist_ok=True)
    a = _act(1, "click", "https://x.com/a")
    (sd / "trace.jsonl").write_text(json.dumps(a.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    (sd / "requests.jsonl").write_text("", encoding="utf-8")
    (sd / "meta.json").write_text(json.dumps({"url": "https://x.com/a"}), encoding="utf-8")
    edir = exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp", fmt="md")
    data = json.loads((edir / "structure.json").read_text(encoding="utf-8"))
    assert data["actions_total"] == 1
    assert len(data["segments"]) == 1
