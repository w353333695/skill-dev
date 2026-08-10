"""models 序列化 round-trip 测试。"""

import json

from browser_recorder.models import RequestEvent, SelectorSet, SessionMeta, StepEvent


def test_selector_set_best_order():
    s = SelectorSet(testid='[data-testid="ok"]', id="#btn", css="form > button")
    assert s.best() == [
        ("testid", '[data-testid="ok"]'),
        ("id", "#btn"),
        ("css", "form > button"),
    ]


def test_selector_set_from_dict_ignores_unknown():
    s = SelectorSet.from_dict({"testid": "x", "xpath": "/html", "unknown": 1})
    assert s.testid == "x"
    assert s.css is None


def test_step_event_round_trip():
    step = StepEvent(
        seq=3,
        type="input",
        selectors=SelectorSet(id="#user", css="form > input"),
        label="用户名",
        value="alice",
        sensitive=False,
    )
    line = step.dumps()
    d = json.loads(line)
    assert d["selectors"] == {"id": "#user", "css": "form > input"}  # 空值已剔除
    back = StepEvent.from_dict(d)
    assert back == step


def test_step_event_from_dict_tolerates_extra_fields():
    d = {"seq": 1, "type": "click", "future_field": "x"}
    step = StepEvent.from_dict(d)
    assert step.seq == 1
    assert step.selectors.css is None


def test_request_event_round_trip():
    req = RequestEvent(seq=1, step_seq=2, method="POST", url="http://x/api", status=200, post_data='{"a":1}')
    back = RequestEvent.from_dict(json.loads(req.dumps()))
    assert back == req


def test_session_meta_save(tmp_path):
    meta = SessionMeta(session_id="s1", url="http://x", mode="cdp")
    path = meta.save(tmp_path)
    loaded = json.loads(path.read_text())
    assert loaded["session_id"] == "s1"
    assert loaded["mode"] == "cdp"
