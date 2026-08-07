# tests/test_export_format.py
"""A1：export 默认产物 Markdown；--format html/both 控制是否额外产 html。"""
import json
from pathlib import Path
from browser_recorder.models import Action, Target
from browser_recorder.export import runner as exp


def _seed_session(tmp_root: Path, name: str = "s1") -> Path:
    """在 tmp_root 下造一个最小 session（trace+requests+meta），返回 session_dir。"""
    from browser_recorder import paths
    paths.TMP_ROOT = tmp_root
    sd = paths.session_dir(name)
    sd.mkdir(parents=True, exist_ok=True)
    a = Action(seq=1, ts=0, type="click", url="https://x.com/p",
               target=Target(css="#go", bbox={"x": 1, "y": 1, "w": 10, "h": 10}))
    (sd / "trace.jsonl").write_text(json.dumps(a.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    (sd / "requests.jsonl").write_text("", encoding="utf-8")
    (sd / "meta.json").write_text(json.dumps({"url": "https://x.com/p"}), encoding="utf-8")
    return sd


def _export(tmp_path, fmt):
    sd = _seed_session(tmp_path / "tmp")
    return exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp", fmt=fmt)


def test_default_format_is_md_only(tmp_path: Path):
    edir = _export(tmp_path, fmt="md")
    assert (edir / "report.md").exists()
    assert not (edir / "report.html").exists(), "默认不应再产 html"


def test_format_html_only(tmp_path: Path):
    edir = _export(tmp_path, fmt="html")
    assert (edir / "report.html").exists()
    assert not (edir / "report.md").exists()


def test_format_both(tmp_path: Path):
    edir = _export(tmp_path, fmt="both")
    assert (edir / "report.md").exists()
    assert (edir / "report.html").exists()


def test_default_fmt_when_not_passed(tmp_path: Path):
    """不传 fmt → 默认 md（旧行为同时产两文件，须回归为只产 md）。"""
    sd = _seed_session(tmp_path / "tmp")
    edir = exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp")
    assert (edir / "report.md").exists()
    assert not (edir / "report.html").exists()
