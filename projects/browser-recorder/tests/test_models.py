# tests/test_models.py
from browser_recorder.models import Target, Action, RequestRecord, ResponseInfo


def test_target_roundtrip():
    t = Target(
        role_selector="button[name='提交']",
        css="button.submit",
        xpath="//button[@class='submit']",
        text="提交",
        bbox={"x": 10, "y": 20, "w": 80, "h": 30},
        tag="button",
        role="button",
        name="提交",
    )
    d = t.to_dict()
    t2 = Target.from_dict(d)
    assert t2 == t
    assert t2.bbox == {"x": 10, "y": 20, "w": 80, "h": 30}


def test_action_roundtrip_with_all_fields():
    a = Action(
        seq=3,
        ts=1719000000000,
        type="click",
        target=Target(css="a#next", bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
        value=None,
        url="https://example.com/list",
        page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 100},
        screenshot={"before": "step-0003-before.png", "after": "step-0003-after.png"},
        settled_by="network_dom_cpu",
    )
    d = a.to_dict()
    a2 = Action.from_dict(d)
    assert a2 == a
    assert a2.target.css == "a#next"


def test_action_optional_fields_none():
    a = Action(seq=1, ts=0, type="navigation", target=None, url="https://x")
    d = a.to_dict()
    a2 = Action.from_dict(d)
    assert a2.target is None
    assert a2.value is None
    assert a2.screenshot is None


def test_request_record_with_response_info():
    r = RequestRecord(
        req_id="ABC",
        ts=100,
        method="GET",
        url="https://example.com/api/x",
        headers={"Accept": "application/json"},
        post_data=None,
        status=200,
        response_headers={"Content-Type": "application/json"},
        mime="application/json",
        response=ResponseInfo(raw_size=10, schema={"type": "object"}),
        duration_ms=5,
        linked_action_seq=2,
    )
    d = r.to_dict()
    r2 = RequestRecord.from_dict(d)
    assert r2 == r
    assert r2.response.schema["type"] == "object"
    assert r2.response.raw_ref is None


def test_response_info_with_raw_ref():
    ri = ResponseInfo(raw_size=2_000_000, raw_ref="responses/ABC.bin", raw_sha256="deadbeef", schema=None)
    d = ri.to_dict()
    ri2 = ResponseInfo.from_dict(d)
    assert ri2.raw_ref == "responses/ABC.bin"
    assert ri2.schema is None
