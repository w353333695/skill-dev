"""事件归一化 + session.jsonl append-only 落盘 + 硬脱敏基线。

脱敏不可配置（spec §3.1）：敏感 header 只记键名、password 值恒 ***、URL 敏感参数值打码。
body 不截断。
"""
from __future__ import annotations

import json
import pathlib
import time

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-auth-token", "token"}
SENSITIVE_URL_KEYS = ("token", "password", "secret", "passwd", "access_token")


def mask_url(url: str) -> str:
    """URL 中敏感 query 参数值替换为 ***。

    直接在原始 query 串上打码（split & / partition =），不经历 parse_qsl+urlencode
    round-trip：一来 urlencode 会把 *** 编成 %2A%2A%2A，二来非敏感参数保持原样
    （已编码值不被二次改写）。
    """
    from urllib.parse import urlsplit, urlunsplit
    sp = urlsplit(url)
    if not sp.query:
        return url
    parts = []
    for chunk in sp.query.split("&"):
        k, sep, v = chunk.partition("=")
        if k and any(s in k.lower() for s in SENSITIVE_URL_KEYS):
            chunk = k + sep + "***"
        parts.append(chunk)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "&".join(parts), sp.fragment))


def mask_headers(headers: dict) -> dict:
    """敏感 header 值替换为 ***（保留键名）。键大小写不敏感。"""
    return {k: ("***" if k.lower() in SENSITIVE_HEADERS else v) for k, v in (headers or {}).items()}


def mask_value_for_input(html_type: str | None, value: str) -> str:
    """password 型 input 值恒 ***。"""
    return "***" if (html_type or "").lower() == "password" else value


class SessionWriter:
    """append-only jsonl writer。emit 立即写+flush（崩溃不丢已录事件）。"""

    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "screenshots").mkdir(exist_ok=True)
        self._f = open(self.out_dir / "session.jsonl", "a", encoding="utf-8")
        self._seq = 0

    def emit(self, kind: str, payload: dict) -> int:
        self._seq += 1
        rec = {"t_mono": time.monotonic_ns() // 1_000_000, "kind": kind, "seq": self._seq}
        if kind == "request":
            payload = dict(payload)
            payload["url"] = mask_url(payload.get("url", ""))
            payload["headers"] = mask_headers(payload.get("headers") or {})
        if kind == "response":
            payload = dict(payload)
            payload["url"] = mask_url(payload.get("url", ""))
            payload["headers"] = mask_headers(payload.get("headers") or {})
        if kind == "action":
            payload = dict(payload)
            if "value" in payload and payload.get("html_type") is not None:
                payload["value"] = mask_value_for_input(
                    payload.get("html_type"), payload.get("value", ""))
        rec.update(payload)
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._f.flush()
        return self._seq

    def close(self) -> None:
        self._f.close()
