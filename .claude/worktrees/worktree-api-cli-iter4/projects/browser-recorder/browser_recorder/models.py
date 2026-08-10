"""数据模型：record.jsonl / requests.jsonl / meta.json 的 schema 定义与序列化。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class SelectorSet:
    """元素的多路定位候选，回放时按 best() 顺序依次尝试。"""

    testid: str | None = None
    role_name: str | None = None
    id: str | None = None
    text: str | None = None
    css: str | None = None

    def best(self) -> list[tuple[str, str]]:
        """按优先级返回 (策略名, selector) 候选，跳过空值。"""
        return [(k, v) for k, v in asdict(self).items() if v]

    @classmethod
    def from_dict(cls, d: dict | None) -> SelectorSet:
        d = d or {}
        return cls(**{k: d.get(k) for k in ("testid", "role_name", "id", "text", "css")})


@dataclass
class StepEvent:
    """record.jsonl 每行：一步操作。"""

    seq: int
    type: str  # click | input | select | key | navigate
    ts: str = field(default_factory=_utcnow_iso)
    url: str | None = None
    selectors: SelectorSet = field(default_factory=SelectorSet)
    label: str | None = None
    value: str | None = None
    param_key: str | None = None
    sensitive: bool = False
    point: dict | None = None  # {"x": int, "y": int} CSS 像素
    screenshot: str | None = None
    caused_navigation: bool = False

    def dumps(self) -> str:
        d = asdict(self)
        d["selectors"] = {k: v for k, v in d["selectors"].items() if v is not None}
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> StepEvent:
        d = dict(d)
        d["selectors"] = SelectorSet.from_dict(d.get("selectors"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class RequestEvent:
    """requests.jsonl 每行：一个 fetch/XHR 请求。"""

    seq: int
    step_seq: int  # 关联的操作步骤序号
    method: str
    url: str
    ts: str = field(default_factory=_utcnow_iso)
    resource_type: str | None = None
    status: int | None = None
    request_headers: dict = field(default_factory=dict)
    post_data: str | None = None
    response_body: str | None = None
    truncated: bool = False
    duration_ms: int | None = None

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> RequestEvent:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class SessionMeta:
    """session_dir/meta.json。"""

    session_id: str
    started_at: str = field(default_factory=_utcnow_iso)
    url: str | None = None
    mode: str | None = None  # launch | cdp
    auth_file: str | None = None
    viewport: dict | None = None
    user_agent: str | None = None
    version: str | None = None

    def save(self, session_dir: Path) -> Path:
        path = Path(session_dir) / "meta.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def read_steps(session_dir: Path) -> list[StepEvent]:
    path = Path(session_dir) / "record.jsonl"
    if not path.exists():
        return []
    return [StepEvent.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_requests(session_dir: Path) -> list[RequestEvent]:
    path = Path(session_dir) / "requests.jsonl"
    if not path.exists():
        return []
    return [RequestEvent.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
