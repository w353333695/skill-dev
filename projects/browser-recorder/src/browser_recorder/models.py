"""browser-recorder 数据模型."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict


class ActionTag(str, Enum):
    """操作事件类型."""
    CLICK = "CLICK"
    INPUT = "INPUT"
    CHANGE = "CHANGE"
    SUBMIT = "SUBMIT"
    NAV = "NAV"
    DIALOG = "DIALOG"
    TAB_OPEN = "TAB_OPEN"
    TAB_CLOSE = "TAB_CLOSE"
    SHOT = "SHOT"
    SCROLL = "SCROLL"


@dataclass
class Action:
    """单条操作记录."""
    step: int
    timestamp_ms: float
    tag: ActionTag
    selector: str
    tag_name: str
    url: str
    page_id: str
    value: Optional[str] = None
    text: Optional[str] = None
    frame_id: Optional[str] = None
    coords: Optional[tuple] = None
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None


@dataclass
class RequestRecord:
    """网络请求记录."""
    timestamp_ms: float
    method: str
    url: str
    status: int
    duration_ms: float
    resource_type: str
    req_headers: Dict[str, str] = field(default_factory=dict)
    res_headers: Dict[str, str] = field(default_factory=dict)
    req_body: Optional[str] = None
    res_body: Optional[str] = None
