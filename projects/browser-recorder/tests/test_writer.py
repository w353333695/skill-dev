"""writer 单测：schema 公共字段 + 硬脱敏基线。"""
import json

from browser_recorder.writer import (
    SessionWriter, mask_headers, mask_url, mask_value_for_input,
    SENSITIVE_HEADERS, SENSITIVE_URL_KEYS,
)


def test_emit_common_fields_and_seq(tmp_path):
    w = SessionWriter(tmp_path)
    s1 = w.emit("nav", {"url": "https://a/"})
    s2 = w.emit("action", {"type": "click"})
    w.close()
    assert s2 == s1 + 1
    lines = [json.loads(l) for l in (tmp_path / "session.jsonl").read_text().splitlines()]
    assert lines[0]["kind"] == "nav" and lines[1]["kind"] == "action"
    for ln in lines:
        assert {"t_mono", "kind", "seq"} <= set(ln)
        assert isinstance(ln["t_mono"], int) and ln["t_mono"] > 0
    assert lines[0]["t_mono"] <= lines[1]["t_mono"]  # 单调不减


def test_mask_headers_keys_only():
    h = {"Authorization": "Bearer abc", "Cookie": "sid=1", "X-Auth-Token": "t",
         "Content-Type": "application/json"}
    m = mask_headers(h)
    assert m == {"Authorization": "***", "Cookie": "***", "X-Auth-Token": "***",
                 "Content-Type": "application/json"}


def test_mask_url_params():
    u = "https://x.io/api?token=abc&password=pw&id=7"
    assert mask_url(u) == "https://x.io/api?token=***&password=***&id=7"


def test_mask_password_input():
    assert mask_value_for_input("password", "hunter2") == "***"
    assert mask_value_for_input("text", "hello") == "hello"
    assert mask_value_for_input(None, "hello") == "hello"


def test_emit_masks_request_payload(tmp_path):
    w = SessionWriter(tmp_path)
    w.emit("request", {"request_id": "9", "method": "GET",
                       "url": "https://x.io/a?token=z",
                       "headers": {"Authorization": "Bearer q", "Accept": "*/*"},
                       "post_body": None, "initiator": {}})
    w.close()
    ln = json.loads((tmp_path / "session.jsonl").read_text().splitlines()[0])
    assert ln["url"] == "https://x.io/a?token=***"
    assert ln["headers"]["Authorization"] == "***"
    assert ln["headers"]["Accept"] == "*/*"
