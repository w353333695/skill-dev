"""writer 单测：schema 公共字段 + 硬脱敏基线。"""
import json

from browser_recorder.writer import (
    SessionWriter, mask_headers, mask_post_body, mask_url, mask_value_for_input,
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


def test_emit_masks_nav_and_session_start_url(tmp_path):
    """nav / session_start 的 URL 同样脱敏（不只 request/response）。"""
    w = SessionWriter(tmp_path)
    w.emit("nav", {"url": "https://x.io/cb?access_token=SECRET&x=1", "title": ""})
    w.emit("session_start", {"url": "https://x.io/?password=hunter2", "ts": 1.0})
    w.close()
    lines = [json.loads(l) for l in (tmp_path / "session.jsonl").read_text().splitlines()]
    assert lines[0]["url"] == "https://x.io/cb?access_token=***&x=1"
    assert lines[1]["url"] == "https://x.io/?password=***"


def test_mask_post_body_form():
    assert mask_post_body("user=alice&password=hunter2&x=1") == "user=alice&password=***&x=1"
    assert mask_post_body("passwd=abc") == "passwd=***"


def test_mask_post_body_json():
    out = json.loads(mask_post_body('{"username": "alice", "password": "hunter2"}'))
    assert out == {"username": "alice", "password": "***"}


def test_mask_post_body_other_untouched():
    assert mask_post_body("plain text no equals") == "plain text no equals"
    assert mask_post_body(None) is None
    assert mask_post_body("") == ""


def test_mask_post_body_non_dict_json_untouched():
    """合法 JSON 但非 dict（数组/字符串）→ 原样返回，不落 form 分支改写。"""
    assert mask_post_body('["password=hunter2"]') == '["password=hunter2"]'
    assert mask_post_body('"password=hunter2"') == '"password=hunter2"'


def test_emit_masks_request_post_body(tmp_path):
    w = SessionWriter(tmp_path)
    w.emit("request", {"request_id": "1", "method": "POST",
                       "url": "https://x.io/login", "headers": {},
                       "post_body": "user=a&password=b"})
    w.emit("request", {"request_id": "2", "method": "POST",
                       "url": "https://x.io/api", "headers": {},
                       "post_body": '{"password": "x"}'})
    w.close()
    lines = [json.loads(l) for l in (tmp_path / "session.jsonl").read_text().splitlines()]
    assert lines[0]["post_body"] == "user=a&password=***"
    assert json.loads(lines[1]["post_body"]) == {"password": "***"}


def test_emit_io_error_sets_fatal(tmp_path):
    """emit 落盘 IO 失败（文件已关）→ fatal 置位并上抛（IO 致命升级）。"""
    w = SessionWriter(tmp_path)
    w.emit("nav", {"url": "https://a/"})
    w._f.close()  # 模拟底层 IO 失效
    import pytest
    with pytest.raises((OSError, ValueError)):
        w.emit("nav", {"url": "https://b/"})
    assert w.fatal is True
    assert w.events == 1  # 失败那条 seq 回滚，events 语义 = 已落盘数
