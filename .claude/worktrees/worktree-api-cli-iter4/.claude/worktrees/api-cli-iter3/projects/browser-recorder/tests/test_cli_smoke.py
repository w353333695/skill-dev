# tests/test_cli_smoke.py
import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "browser_recorder.cli", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=120)


def test_cli_record_then_export_on_demo_site(serve_demo_site, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # record：通过 Playwright 驱动点击（auto_actions），断言 jsonl + 截图原图
    # + 每条 Action 回填了 screenshot 字段（这是录制→画标链路接通的标志）。
    from browser_recorder.record import runner as rec_runner
    session_dir = rec_runner.run_record(
        url=serve_demo_site + "/list.html",
        out_dir=tmp_path / ".browser-recorder",
        profile=None, keep_auth=False,
        screenshot_policy_path=None, video=False, name="smoke",
        headless=True,
        # 自动操作脚本：搜索（click 默认 before+after 两张截图）
        auto_actions=[("click", "#search-btn")],
    )
    assert (session_dir / "trace.jsonl").exists() or (session_dir / "requests.jsonl").exists()

    # 录制期必须产截图原图，且每条落库 Action 的 screenshot 字段非空
    trace_path = session_dir / "trace.jsonl"
    actions = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if trace_path.exists() else []
    screenshots_dir = session_dir / "screenshots"
    raw_shots = list(screenshots_dir.glob("*.png")) if screenshots_dir.exists() else []
    assert raw_shots, "录制期未产出任何截图原图（record 截图链路未接通）"
    clicked = [a for a in actions if a.get("type") == "click"]
    assert clicked, "auto_actions 的点击未被捕获成 Action"
    assert all(a.get("screenshot") for a in clicked), \
        "Action.screenshot 字段未被回填，export 侧无法定位画标原图"

    from browser_recorder.export import runner as exp_runner
    out = exp_runner.run_export(
        session=str(session_dir.name), out_dir=tmp_path / ".browser-recorder",
        name="smoke", filter_path=None, keep_raw_bodies=False,
        annotate_style="verbose", annotate_opacity=60,
        tmp_root=tmp_path / "tmp", fmt="both",
    )
    assert (out / "report.html").exists()
    assert (out / "report.md").exists()
    assert (out / "requests.json").exists()

    # export 期必须产出画标截图（半透明标注 + 序号），且报告内嵌了截图引用
    annotated = list((out / "screenshots_annotated").glob("*.png"))
    assert annotated, "export 未产出任何画标截图（画标链路未接通）"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "screenshots_annotated/" in md, "Markdown 报告未内嵌画标截图"
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "screenshots_annotated/" in html, "HTML 报告未内嵌画标截图"


def test_cli_export_help_lists_subcommands():
    r = _run(["--help"], cwd=".")
    assert r.returncode == 0
    assert "record" in r.stdout and "replay" in r.stdout and "export" in r.stdout
