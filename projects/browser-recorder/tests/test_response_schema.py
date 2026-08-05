# tests/test_response_schema.py
import json
from browser_recorder.response_schema import parse, _sha256


def test_parse_json_object_full_field_tree():
    body = json.dumps({"total": 42, "name": "张三", "ok": True, "nothing": None}).encode()
    ri = parse(body, "application/json")
    f = ri.schema["fields"]
    assert f["total"] == {"type": "integer", "sample": 42}
    assert f["name"] == {"type": "string", "sample": "张三"}
    assert f["ok"] == {"type": "boolean", "sample": True}
    assert f["nothing"] == {"type": "null", "sample": None}


def test_parse_json_nested_and_array():
    body = json.dumps({"list": [{"id": 1, "tags": ["a", "b"]}]}).encode()
    ri = parse(body, "application/json")
    items = ri.schema["fields"]["list"]["items"]["fields"]
    assert items["id"] == {"type": "integer", "sample": 1}
    assert items["tags"] == {"type": "array", "items": {"type": "string"}}


def test_parse_json_large_string_truncated_with_full_in_raw():
    big = "x" * 300_000
    body = json.dumps({"avatar": big}).encode()
    ri = parse(body, "application/json", inline_max=100)
    fld = ri.schema["fields"]["avatar"]
    assert fld["type"] == "string"
    assert fld["sample_truncated"].startswith("x")
    assert len(fld["sample_truncated"]) == 100
    assert fld["full_in_raw"] is True


def test_parse_json_raw_size_set():
    body = b'{"a":1}'
    ri = parse(body, "application/json")
    assert ri.raw_size == len(body)
    assert ri.raw_ref is None  # 落盘由调用方决定
    assert ri.raw_sha256 == _sha256(body)


def test_parse_form_urlencoded():
    body = b"name=zhangsan&age=30"
    ri = parse(body, "application/x-www-form-urlencoded")
    f = ri.schema["fields"]
    assert f["name"] == {"type": "string"}
    assert f["age"] == {"type": "string"}


def test_parse_binary():
    body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    ri = parse(body, "image/png")
    assert ri.schema["type"] == "binary"
    assert ri.schema["mime"] == "image/png"
    assert ri.schema["size"] == len(body)


def test_parse_html_structure_only():
    body = b"<html><body><div>hi</div></body></html>"
    ri = parse(body, "text/html")
    assert ri.schema["type"] == "html"
    assert ri.raw_sha256 == _sha256(body)


def test_parse_unknown_text_prefix():
    body = b"plain text payload " * 1000
    ri = parse(body, "text/plain")
    assert ri.schema["type"] == "text"
    assert ri.schema["prefix"].startswith("plain text")
    assert ri.schema["sha256"] == _sha256(body)


def test_parse_invalid_json_falls_back_to_text():
    body = b"{not json"
    ri = parse(body, "application/json")
    # 解析失败不丢请求，回退文本
    assert ri.schema["type"] in ("text", "error")
    assert ri.raw_sha256 == _sha256(body)
