# tests/test_report_html.py
from browser_recorder.models import Action, Target
from browser_recorder.export import report_html


def test_html_well_formed_and_has_legend():
    html = report_html.render(actions=[], request_groups=[], annotated_img_map={}, meta={"url": "u"})
    assert html.startswith("<!DOCTYPE html>") or html.startswith("<html")
    assert "</html>" in html
    assert "图例" in html
    assert "<style>" in html  # CSS 内联


def test_html_renders_step():
    a = Action(seq=2, ts=0, type="input", url="u",
               target=Target(css="input", bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
               value="hello", screenshot={"after": "step-0002-after.png"})
    html = report_html.render(actions=[a], request_groups=[], annotated_img_map={2: "step-0002-after.png"}, meta={"url": "u"})
    assert "步骤 2" in html
    assert "input" in html
    assert "step-0002-after.png" in html
