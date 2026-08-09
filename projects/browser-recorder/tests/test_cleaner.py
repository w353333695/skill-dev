"""测试清理器."""
import tempfile
from pathlib import Path
from browser_recorder.cleaner import cleanup


def test_cleanup_default_removes_screenshots():
    """默认清理：删除 screenshots/ 目录."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        screenshots_dir = base / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_text("fake image")
        (base / "record.md").write_text("# report")
        (base / "requests.json").write_text("[]")

        cleanup(base, keep_all=False)

        assert not screenshots_dir.exists()
        assert (base / "record.md").exists()
        assert (base / "requests.json").exists()


def test_cleanup_keep_all_preserves_everything():
    """--keep-all：保留所有文件."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        screenshots_dir = base / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_text("fake image")
        (base / "record.md").write_text("# report")
        (base / "events.jsonl").write_text("{}")

        cleanup(base, keep_all=True)

        assert screenshots_dir.exists()
        assert (base / "record.md").exists()
        assert (base / "events.jsonl").exists()


def test_cleanup_no_screenshots_dir():
    """screenshots/ 不存在 → 不报错."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "record.md").write_text("# report")

        cleanup(base, keep_all=False)

        assert (base / "record.md").exists()
