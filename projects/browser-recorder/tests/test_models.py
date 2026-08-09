"""测试数据模型."""
import json
from dataclasses import asdict
from browser_recorder.models import ActionTag, Action, RequestRecord


def test_action_tag_values():
    """验证 ActionTag 枚举值."""
    assert ActionTag.CLICK.value == "CLICK"
    assert ActionTag.INPUT.value == "INPUT"
    assert ActionTag.CHANGE.value == "CHANGE"
    assert ActionTag.SUBMIT.value == "SUBMIT"
    assert ActionTag.NAV.value == "NAV"
    assert ActionTag.DIALOG.value == "DIALOG"
    assert ActionTag.TAB_OPEN.value == "TAB_OPEN"
    assert ActionTag.TAB_CLOSE.value == "TAB_CLOSE"
    assert ActionTag.SHOT.value == "SHOT"
    assert ActionTag.SCROLL.value == "SCROLL"


def test_action_creation_minimal():
    """Action 最简字段创建."""
    action = Action(
        step=1,
        timestamp_ms=1691591425000.0,
        tag=ActionTag.NAV,
        selector="",
        tag_name="",
        url="https://example.com",
        page_id="main",
    )
    assert action.step == 1
    assert action.tag == ActionTag.NAV
    assert action.value is None
    assert action.screenshot_before is None


def test_action_creation_full():
    """Action 完整字段创建."""
    action = Action(
        step=2,
        timestamp_ms=1691591427000.0,
        tag=ActionTag.CLICK,
        selector="#login-btn",
        value=None,
        tag_name="button",
        text="登录",
        url="https://example.com",
        page_id="main",
        frame_id=None,
        coords=(150, 200),
        screenshot_before="screenshots/step_002_click.jpg",
        screenshot_after="screenshots/step_002_result.jpg",
    )
    assert action.coords == (150, 200)
    assert action.text == "登录"


def test_action_json_roundtrip():
    """Action → dict → JSON 序列化往返."""
    action = Action(
        step=3,
        timestamp_ms=1691591430000.0,
        tag=ActionTag.INPUT,
        selector="#username",
        value="admin",
        tag_name="input",
        url="https://example.com",
        page_id="main",
    )
    d = asdict(action)
    d["tag"] = d["tag"].value
    json_str = json.dumps(d)
    loaded = json.loads(json_str)
    assert loaded["step"] == 3
    assert loaded["tag"] == "INPUT"
    assert loaded["value"] == "admin"


def test_request_record_creation():
    """RequestRecord 创建."""
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="POST",
        url="https://example.com/api/login",
        status=200,
        duration_ms=85.5,
        resource_type="fetch",
        req_headers={"content-type": "application/json"},
        res_headers={"content-type": "application/json"},
        req_body='{"user":"admin"}',
        res_body='{"ok":true}',
    )
    assert req.method == "POST"
    assert req.status == 200
    assert req.duration_ms == 85.5


def test_request_record_optional_fields():
    """RequestRecord body 可为 None."""
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="GET",
        url="https://example.com/api/data",
        status=200,
        duration_ms=100.0,
        resource_type="xhr",
    )
    assert req.req_body is None
    assert req.res_body is None
