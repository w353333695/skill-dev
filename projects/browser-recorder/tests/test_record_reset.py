# tests/test_record_reset.py
"""录制期同名 session 复用：必须清空旧产物，否则 trace.jsonl/requests.jsonl 以
append 模式叠加 → 双录污染（同名截图被多段 action 引用 → export 一图画多个序号）。

Bug 现场：session "easyops" 录了两次（间隔 6 分钟），第二次的 trace append 到
第一次后面；meta.json 是覆盖写故只显示第二次时间，掩盖了双录。
"""
from pathlib import Path
from browser_recorder.record import runner


def test_clear_stale_artifacts_removes_old_trace_requests_screenshots(tmp_path: Path):
    """复用同名 session 时，旧 trace/requests/screenshots/responses 必须被清空。"""
    sd = tmp_path / "easyops"
    sd.mkdir()
    (sd / "trace.jsonl").write_text("OLD_TRACE\n", encoding="utf-8")
    (sd / "requests.jsonl").write_text("OLD_REQ\n", encoding="utf-8")
    (sd / "screenshots").mkdir()
    (sd / "screenshots" / "step-0001-after.png").write_bytes(b"OLD_PNG")
    (sd / "responses").mkdir()
    (sd / "responses" / "abc.bin").write_bytes(b"OLD_BODY")
    (sd / "meta.json").write_text("{}", encoding="utf-8")  # meta 由 run_record 覆盖写

    runner.clear_stale_artifacts(sd)

    assert not (sd / "trace.jsonl").exists(), "旧 trace.jsonl 必须清除（append 会叠加）"
    assert not (sd / "requests.jsonl").exists(), "旧 requests.jsonl 必须清除"
    assert not (sd / "screenshots").exists(), "旧 screenshots 必须清除（同名截图会错配）"
    assert not (sd / "responses").exists(), "旧 responses 必须清除"


def test_clear_stale_artifacts_safe_on_fresh_dir(tmp_path: Path):
    """全新 session 目录（无旧产物）调用不应抛错。"""
    sd = tmp_path / "fresh"
    sd.mkdir()
    runner.clear_stale_artifacts(sd)
    assert sd.exists()


def test_clear_stale_artifacts_partial_old_files(tmp_path: Path):
    """只有部分旧文件（如仅 trace.jsonl）也应正常清除，不因缺失项报错。"""
    sd = tmp_path / "partial"
    sd.mkdir()
    (sd / "trace.jsonl").write_text("OLD", encoding="utf-8")
    # 故意不建 screenshots/responses
    runner.clear_stale_artifacts(sd)
    assert not (sd / "trace.jsonl").exists()
