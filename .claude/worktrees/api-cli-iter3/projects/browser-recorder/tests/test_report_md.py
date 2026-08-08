# tests/test_report_md.py
from browser_recorder.models import Action, Target
from browser_recorder.export import report_md


def _action(seq, atype, css="a#x", img_after=None):
    return Action(
        seq=seq, ts=0, type=atype, url="https://example.com/p",
        target=Target(css=css, bbox={"x": 1, "y": 1, "w": 10, "h": 10}),
        screenshot={"after": img_after} if img_after else None,
    )


def test_md_has_title_and_legend():
    md = report_md.render(actions=[], request_groups=[], annotated_img_map={}, meta={"url": "https://example.com"})
    assert "# 浏览器操作报告" in md
    assert "图例" in md


def test_md_renders_step_with_screenshot():
    a = _action(1, "click", img_after="step-0001-after.png")
    md = report_md.render(actions=[a], request_groups=[], annotated_img_map={1: "step-0001-after.png"}, meta={"url": "u"})
    assert "步骤 1" in md
    assert "click" in md
    assert "screenshots_annotated/step-0001-after.png" in md


def test_md_renders_linked_requests():
    a = _action(1, "click")
    groups = [{"endpoint": {"method": "GET", "url_template": "/api/x", "param_path": []},
               "observations": 1, "merged_schema": {"type": "object", "fields": {"id": {"type": "integer"}}},
               "sample_statuses": [200], "linked_seq": [1]}]
    md = report_md.render(actions=[a], request_groups=groups, annotated_img_map={}, meta={"url": "u"})
    assert "/api/x" in md
    assert "GET" in md
