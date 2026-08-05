# browser_recorder/response_schema.py
"""响应体解析（A 方案）：按 MIME 解析成完整字段骨架，结构不丢、jsonl 轻量。

超大原始体的落盘（C 方案）由调用方根据 raw_size 决定；本模块只产 ResponseInfo。
"""
from __future__ import annotations
import hashlib
import json as _json
from typing import Any
from .models import ResponseInfo


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _type_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _sample(value: Any, *, inline_max: int) -> dict[str, Any]:
    t = _type_of(value)
    if t == "array":
        item = value[0] if value else None
        if isinstance(item, dict):
            return {"type": "array", "items": {"type": "object", "fields": {
                k: _sample(v, inline_max=inline_max) for k, v in item.items()}}}
        return {"type": "array", "items": {"type": _type_of(item)}}
    if t == "object":
        return {"type": "object", "fields": {
            k: _sample(v, inline_max=inline_max) for k, v in value.items()}}
    if t == "string" and len(value) > inline_max:
        return {"type": "string", "sample_truncated": value[:inline_max], "full_in_raw": True}
    return {"type": t, "sample": value}


def _parse_json(obj: Any, *, inline_max: int) -> dict[str, Any]:
    return _sample(obj, inline_max=inline_max)


def _parse_form(body: bytes) -> dict[str, Any]:
    from urllib.parse import parse_qs
    qs = parse_qs(body.decode("utf-8", errors="replace"))
    return {"type": "object", "fields": {k: {"type": "string"} for k in qs}}


def parse(body: bytes, mime: str, *, inline_max: int = 262_144,
         raw_threshold: int = 1_048_576) -> ResponseInfo:
    """body -> ResponseInfo。raw_ref 不在此设（调用方按 raw_size 落盘）。"""
    raw_size = len(body)
    sha = _sha256(body) if body else None
    m = (mime or "").lower()
    schema: dict[str, Any]

    if "json" in m:
        try:
            obj = _json.loads(body.decode("utf-8"))
            schema = _parse_json(obj, inline_max=inline_max)
        except Exception:
            schema = {"type": "error", "reason": "invalid_json",
                      "prefix": body[:512].decode("utf-8", errors="replace")}
    elif "x-www-form-urlencoded" in m or "multipart" in m:
        schema = _parse_form(body) if "x-www-form-urlencoded" in m else {"type": "multipart"}
    elif m.startswith("image/") or m.startswith("audio/") or m.startswith("video/") or m == "application/octet-stream":
        schema = {"type": "binary", "mime": mime, "size": raw_size}
    elif "html" in m:
        schema = {"type": "html"}
    elif "xml" in m:
        schema = {"type": "xml"}
    else:
        prefix = body[:512].decode("utf-8", errors="replace")
        schema = {"type": "text", "prefix": prefix, "sha256": sha}

    return ResponseInfo(raw_size=raw_size, raw_ref=None, raw_sha256=sha, schema=schema)
