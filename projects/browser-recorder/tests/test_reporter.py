"""测试 Markdown 报告生成器."""
import tempfile
from pathlib import Path
from browser_recorder.reporter import MarkdownReporter
from browser_recorder.models import Action, ActionTag, RequestRecord


def make_action(step, tag, selector="", text=None, value=None, url="https://example.com",
                page_id="main", timestamp_ms=1000.0, screenshot_before=None,
                screenshot_after=None, coords=None):
    """创建测试 Action."""
    return Action(
        step=step,
        timestamp_ms=timestamp_ms + step * 1000,
        tag=tag,
        selector=selector,
        value=value,
        tag_name="button" if tag == ActionTag.CLICK else "input",
        text=text,
        url=url,
        page_id=page_id,
        coords=coords,
        screenshot_before=screenshot_before,
        screenshot_after=screenshot_after,
    )


def test_generate_report_basic():
    """生成基本报告."""
    reporter = MarkdownReporter()
    actions = [
        make_action(1, ActionTag.NAV, url="https://example.com",
                     screenshot_after="screenshots/step_001_result.jpg"),
        make_action(2, ActionTag.CLICK, selector="#login", text="Login",
                     screenshot_before="screenshots/step_002_click.jpg",
                     screenshot_after="screenshots/step_002_result.jpg",
                     coords=(100, 200)),
        make_action(3, ActionTag.INPUT, selector="#user", value="admin"),
    ]
    requests = [
        RequestRecord(
            timestamp_ms=2000.0, method="GET", url="https://example.com/api/config",
            status=200, duration_ms=50.0, resource_type="fetch",
        ),
        RequestRecord(
            timestamp_ms=3000.0, method="POST", url="https://example.com/api/login",
            status=200, duration_ms=120.0, resource_type="xhr",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        path = reporter.generate(actions, requests, output_dir)
        assert path == output_dir / "record.md"
        assert path.exists()

        content = path.read_text()
        assert "# 录制报告" in content
        assert "example.com" in content
        assert "[NAV]" in content
        assert "[CLICK]" in content
        assert "[INPUT]" in content
        assert "#login" in content
        assert "admin" in content
        # 网络请求表
        assert "/api/config" in content
        assert "/api/login" in content


def test_generate_report_with_multi_tab():
    """多标签页报告包含 page_id."""
    reporter = MarkdownReporter()
    actions = [
        make_action(1, ActionTag.NAV, page_id="main"),
        make_action(2, ActionTag.TAB_OPEN, page_id="child_0", selector="child_0"),
        make_action(3, ActionTag.CLICK, page_id="child_0", selector="#btn"),
        make_action(4, ActionTag.TAB_CLOSE, page_id="child_0"),
        make_action(5, ActionTag.CLICK, page_id="main", selector="#done"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        path = reporter.generate(actions, [], output_dir)
        content = path.read_text()
        assert "page:main" in content
        assert "page:child_0" in content
        assert "[TAB_OPEN]" in content
        assert "[TAB_CLOSE]" in content
