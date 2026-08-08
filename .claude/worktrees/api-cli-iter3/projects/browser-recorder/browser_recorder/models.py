# browser_recorder/models.py
"""数据模型：所有模块共享的单一数据来源。

通过 to_dict / from_dict 实现 jsonl 序列化。字段命名与 spec §5.1 / §6.1 对齐。
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Target:
    """元素定位包：多维度选择器 + bbox + 语义信息。"""
    role_selector: str | None = None
    css: str | None = None
    xpath: str | None = None
    text: str | None = None
    bbox: dict[str, float] | None = None  # {x, y, w, h}
    tag: str | None = None
    role: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Target":
        return cls(**d)


@dataclass
class Action:
    """trace.jsonl 中的一条动作。"""
    seq: int
    ts: int
    type: str
    url: str
    target: Target | None = None
    value: str | None = None
    page_info: dict[str, Any] | None = None
    screenshot: dict[str, str] | None = None  # {"before": ..., "after": ...}
    settled_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "url": self.url,
            "target": self.target.to_dict() if self.target else None,
            "value": self.value,
            "page_info": self.page_info,
            "screenshot": self.screenshot,
            "settled_by": self.settled_by,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        target = Target.from_dict(d["target"]) if d.get("target") else None
        return cls(
            seq=d["seq"], ts=d["ts"], type=d["type"], url=d["url"],
            target=target, value=d.get("value"),
            page_info=d.get("page_info"), screenshot=d.get("screenshot"),
            settled_by=d.get("settled_by"),
        )


@dataclass
class ResponseInfo:
    """响应体：字段骨架(A) + 原始落盘引用(C)。"""
    raw_size: int = 0
    raw_ref: str | None = None
    raw_sha256: str | None = None
    schema: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResponseInfo":
        return cls(**d)


@dataclass
class RequestRecord:
    """requests.jsonl 中的一条网络请求。"""
    req_id: str
    ts: int
    method: str
    url: str
    headers: dict[str, str]
    status: int
    response_headers: dict[str, str]
    mime: str
    post_data: str | None = None
    response: ResponseInfo | None = None
    duration_ms: int | None = None
    linked_action_seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id, "ts": self.ts, "method": self.method,
            "url": self.url, "headers": self.headers, "post_data": self.post_data,
            "status": self.status, "response_headers": self.response_headers,
            "mime": self.mime,
            "response": self.response.to_dict() if self.response else None,
            "duration_ms": self.duration_ms, "linked_action_seq": self.linked_action_seq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RequestRecord":
        resp = ResponseInfo.from_dict(d["response"]) if d.get("response") else None
        return cls(
            req_id=d["req_id"], ts=d["ts"], method=d["method"], url=d["url"],
            headers=d["headers"], post_data=d.get("post_data"),
            status=d["status"], response_headers=d["response_headers"],
            mime=d["mime"], response=resp,
            duration_ms=d.get("duration_ms"),
            linked_action_seq=d.get("linked_action_seq"),
        )
