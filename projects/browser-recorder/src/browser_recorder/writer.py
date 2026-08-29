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


def mask_post_body(body):
    """post_body 脱敏：敏感键的值打码为 ***。

    三种形态：
    - JSON（json.loads 得通且是 dict）：顶层敏感键的值打码；
    - form（"a=b&c=d" 形态，含 application/x-www-form-urlencoded）：逐参数按键名打码；
    - 其他（multipart/二进制/普通文本）：原样返回，不猜。

    敏感判定与 mask_url 同款子串逻辑（SENSITIVE_URL_KEYS，键小写化后子串匹配）。
    """
    if body is None or not isinstance(body, str) or not body.strip():
        return body
    # JSON：parse 得通且顶层是 dict 才处理（数组/标量 JSON 结构不明，原样）
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        obj = None
    if isinstance(obj, dict):
        for k in list(obj):
            if any(s in k.lower() for s in SENSITIVE_URL_KEYS):
                obj[k] = "***"
        return json.dumps(obj, ensure_ascii=False)
    # form：形如 a=b&c=d（每个 chunk 都含 = 才认定，避免误伤普通文本）
    chunks = body.strip().split("&")
    if chunks and all("=" in c for c in chunks):
        parts = []
        for c in chunks:
            k, sep, v = c.partition("=")
            if any(s in k.strip().lower() for s in SENSITIVE_URL_KEYS):
                c = k + sep + "***"
            parts.append(c)
        return "&".join(parts)
    return body


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
        self.fatal = False  # IO 致命标记：emit 落盘抛 OSError 时置位（录制层据此停止）

    @property
    def events(self) -> int:
        """已落盘事件数（= 最新 seq）。"""
        return self._seq

    def emit(self, kind: str, payload: dict) -> int:
        self._seq += 1
        rec = {"t_mono": time.monotonic_ns() // 1_000_000, "kind": kind, "seq": self._seq}
        if kind == "request":
            payload = dict(payload)
            payload["url"] = mask_url(payload.get("url", ""))
            payload["headers"] = mask_headers(payload.get("headers") or {})
            if payload.get("post_body") is not None:
                payload["post_body"] = mask_post_body(payload["post_body"])
        if kind == "response":
            payload = dict(payload)
            payload["url"] = mask_url(payload.get("url", ""))
            payload["headers"] = mask_headers(payload.get("headers") or {})
        if kind == "action":
            payload = dict(payload)
            if "value" in payload and payload.get("html_type") is not None:
                payload["value"] = mask_value_for_input(
                    payload.get("html_type"), payload.get("value", ""))
        if kind in ("nav", "session_start"):
            payload = dict(payload)
            payload["url"] = mask_url(payload.get("url", ""))
        rec.update(payload)
        try:
            self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._f.flush()
        except (OSError, ValueError):
            # IO 错误升级为致命：磁盘满/目录被删/文件已关等，录制继续只会在
            # 每条事件上重复失败。置位 fatal 供录制层检查（_dispatch 仍会吞掉
            # 本异常，防止单条事件处理搞死整个事件泵）。
            # ValueError：对已 close 的文件写/flush 在 CPython 抛 ValueError。
            self.fatal = True
            self._seq -= 1
            raise
        return self._seq

    def close(self) -> None:
        self._f.close()
