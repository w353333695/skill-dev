# tests/test_selectors.py
from browser_recorder.selectors import build_target_from_dom, target_fingerprint
from browser_recorder.models import Target


def test_build_target_from_dom_full():
    node = {
        "tag": "button",
        "role": "button",
        "name": "提交",
        "text": "提交",
        "css": "button.submit",
        "xpath": "//button[@class='submit']",
        "role_selector": "button[name='提交']",
        "bbox": {"x": 10, "y": 20, "w": 80, "h": 30},
    }
    t = build_target_from_dom(node)
    assert t.tag == "button"
    assert t.role == "button"
    assert t.name == "提交"
    assert t.css == "button.submit"
    assert t.bbox == {"x": 10, "y": 20, "w": 80, "h": 30}
    assert t.role_selector == "button[name='提交']"


def test_build_target_from_dom_partial():
    node = {"tag": "a", "css": "a#next", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    t = build_target_from_dom(node)
    assert t.css == "a#next"
    assert t.role is None
    assert t.xpath is None


def test_target_fingerprint_stable_across_bbox_change():
    """指纹应忽略 bbox（位置变不代表是不同元素）。"""
    t1 = Target(css="a#next", text="下一页", bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    t2 = Target(css="a#next", text="下一页", bbox={"x": 5, "y": 5, "w": 1, "h": 1})
    assert target_fingerprint(t1) == target_fingerprint(t2)


def test_target_fingerprint_differs_by_css():
    t1 = Target(css="a#next")
    t2 = Target(css="a#prev")
    assert target_fingerprint(t1) != target_fingerprint(t2)


def test_target_fingerprint_falls_back_to_xpath_then_text():
    t1 = Target(xpath="//div[@id='x']")
    t2 = Target(xpath="//div[@id='x']")
    assert target_fingerprint(t1) == target_fingerprint(t2)
    # 无 css/xpath 时用 tag+text
    t3 = Target(tag="button", text="ok")
    t4 = Target(tag="button", text="ok")
    assert target_fingerprint(t3) == target_fingerprint(t4)
