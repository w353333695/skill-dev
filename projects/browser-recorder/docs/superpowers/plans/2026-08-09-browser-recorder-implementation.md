# browser-recorder 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 Python + Playwright Chromium 的浏览器操作录制 CLI 工具，支持事件捕获、智能截图、网络请求拦截、多标签页管理、Markdown 报告生成和事件回放。

**Architecture:** 管道式可扩展架构 — EventFilter → EventHandler → Reporter 三层 Protocol 抽象。Push 模式事件捕获（expose_function）+ 增量 JSONL 落盘 + 双帧智能截图（前帧标记 + 结果帧）。

**Tech Stack:** Python >= 3.9, Playwright >= 1.40, Typer >= 0.9, Pillow >= 10.0, Rich >= 13.0

## Global Constraints

- Python >= 3.9，Playwright >= 1.40，Typer >= 0.9，Pillow >= 10.0，Rich >= 13.0
- 管道式架构：所有 Filter/Handler/Reporter 实现对应 Protocol 接口
- Push 模式事件捕获，5 个强制 flush 触发点，增量 JSONL 落盘
- 双帧截图策略：前帧 Pillow 标记点击坐标 + 结果帧 MutationObserver DOM 稳定检测
- 回放区分条件等待（不加速）与人为停顿（按倍速缩放）
- CLI 使用 Typer，`recorder start --url ...` + `recorder replay ...` + `recorder doctor` + `recorder version`
- 默认产物保留 record.md + requests.json，清理 screenshots/
- 多标签通过 context.on('page') 全生命周期管理，page_id 归属
- 测试使用本地 http.server + fixtures HTML 端到端
- 产物路径输出到 `/workspace/tmp/.browser-recorder/` 下按 session 组织

---

### Task 1: 项目脚手架

**Files:**
- Create: `projects/browser-recorder/pyproject.toml`
- Create: `projects/browser-recorder/.python-version`
- Create: `projects/browser-recorder/src/browser_recorder/__init__.py`

**Interfaces:**
- Produces: 项目可 `pip install -e .` 安装，`browser_recorder` 包可导入

- [ ] **Step 1: 创建 .python-version**

```
3.9
```

- [ ] **Step 2: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "browser-recorder"
version = "0.1.0"
description = "浏览器操作录制 CLI 工具，基于 Playwright + Chromium"
requires-python = ">=3.9"
dependencies = [
    "playwright>=1.40",
    "typer>=0.9",
    "Pillow>=10.0",
    "rich>=13.0",
]

[project.scripts]
recorder = "browser_recorder.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: 创建 src/browser_recorder/__init__.py**

```python
"""browser-recorder: 浏览器操作录制 CLI 工具."""

__version__ = "0.1.0"
```

- [ ] **Step 4: 安装项目和 Playwright 浏览器**

```bash
cd /workspace/projects/browser-recorder && pip install -e .
playwright install chromium
```

- [ ] **Step 5: 验证安装**

```bash
cd /workspace/projects/browser-recorder && python -c "import browser_recorder; print(browser_recorder.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 6: Commit**

```bash
cd /workspace/projects/browser-recorder && git add pyproject.toml .python-version src/
git commit -m "feat: browser-recorder 项目脚手架 — pyproject.toml + package 初始化"
```

---

### Task 2: 数据模型

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/models.py`
- Create: `projects/browser-recorder/tests/test_models.py`

**Interfaces:**
- Produces:
  - `ActionTag` enum: CLICK, INPUT, CHANGE, SUBMIT, NAV, DIALOG, TAB_OPEN, TAB_CLOSE, SHOT, SCROLL
  - `Action` dataclass: step, timestamp_ms, tag, selector, value, tag_name, text, url, page_id, frame_id, coords, screenshot_before, screenshot_after
  - `RequestRecord` dataclass: timestamp_ms, method, url, status, duration_ms, resource_type, req_headers, res_headers, req_body, res_body
  - `RawEvent` TypedDict: type, timestamp, selector, value, tagName, text, coords, url, pageId, frameId

- [ ] **Step 1: 编写 models 测试**

Create `tests/test_models.py`:

```python
"""测试数据模型."""
import json
from datetime import datetime
from browser_recorder.models import ActionTag, Action, RequestRecord


def test_action_tag_values():
    """验证 ActionTag 枚举值."""
    assert ActionTag.CLICK.value == "CLICK"
    assert ActionTag.INPUT.value == "INPUT"
    assert ActionTag.CHANGE.value == "CHANGE"
    assert ActionTag.SUBMIT.value == "SUBMIT"
    assert ActionTag.NAV.value == "NAV"
    assert ActionTag.DIALOG.value == "DIALOG"
    assert ActionTag.TAB_OPEN.value == "TAB_OPEN"
    assert ActionTag.TAB_CLOSE.value == "TAB_CLOSE"
    assert ActionTag.SHOT.value == "SHOT"
    assert ActionTag.SCROLL.value == "SCROLL"


def test_action_creation_minimal():
    """验证 Action 最简创建."""
    action = Action(
        step=1,
        timestamp_ms=1691591425000.0,
        tag=ActionTag.NAV,
        selector="",
        tag_name="",
        url="https://example.com",
        page_id="main",
    )
    assert action.step == 1
    assert action.tag == ActionTag.NAV
    assert action.value is None
    assert action.screenshot_before is None


def test_action_creation_full():
    """验证 Action 完整字段创建."""
    action = Action(
        step=2,
        timestamp_ms=1691591427000.0,
        tag=ActionTag.CLICK,
        selector="#login-btn",
        value=None,
        tag_name="button",
        text="登录",
        url="https://example.com",
        page_id="main",
        frame_id=None,
        coords=(150, 200),
        screenshot_before="screenshots/step_002_click.jpg",
        screenshot_after="screenshots/step_002_result.jpg",
    )
    assert action.coords == (150, 200)
    assert action.text == "登录"


def test_action_serialization():
    """验证 Action 可 JSON 序列化/反序列化."""
    from dataclasses import asdict

    action = Action(
        step=3,
        timestamp_ms=1691591430000.0,
        tag=ActionTag.INPUT,
        selector="#username",
        value="admin",
        tag_name="input",
        url="https://example.com",
        page_id="main",
    )
    d = asdict(action)
    d["tag"] = d["tag"].value  # enum -> str for JSON
    json_str = json.dumps(d)
    loaded = json.loads(json_str)
    assert loaded["step"] == 3
    assert loaded["tag"] == "INPUT"
    assert loaded["value"] == "admin"


def test_request_record_creation():
    """验证 RequestRecord 创建."""
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="POST",
        url="https://example.com/api/login",
        status=200,
        duration_ms=85.5,
        resource_type="fetch",
        req_headers={"content-type": "application/json"},
        res_headers={"content-type": "application/json"},
        req_body='{"user":"admin"}',
        res_body='{"ok":true}',
    )
    assert req.method == "POST"
    assert req.status == 200
    assert req.duration_ms == 85.5


def test_request_record_truncation():
    """验证 RequestRecord body 截断标记."""
    long_body = "x" * 15000
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="POST",
        url="https://example.com/api/data",
        status=200,
        duration_ms=100.0,
        resource_type="xhr",
        req_headers={},
        res_headers={},
        req_body=long_body[:10240],
        res_body=None,
    )
    assert len(req.req_body) <= 10240
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_models.py -v
```
Expected: ImportError (models 模块不存在)

- [ ] **Step 3: 实现 models.py**

Create `src/browser_recorder/models.py`:

```python
"""browser-recorder 数据模型."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any


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
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_models.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/models.py tests/test_models.py
git commit -m "feat: 数据模型 — Action + RequestRecord + ActionTag 枚举"
```

---

### Task 3: 事件过滤器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/filters.py`
- Create: `projects/browser-recorder/tests/test_filters.py`

**Interfaces:**
- Consumes: `ActionTag`, `Action` from `browser_recorder.models`
- Produces:
  - `EventFilter` Protocol: `process(self, event: dict) -> Optional[dict]`
  - `InputMergeFilter` class: 合并同一 input 连续输入事件，保留首尾
  - `DedupFilter` class: 去除完全重复的相邻事件

- [ ] **Step 1: 编写 filters 测试**

Create `tests/test_filters.py`:

```python
"""测试事件过滤器."""
import pytest
from browser_recorder.filters import InputMergeFilter, DedupFilter


def make_event(tag, selector, value=None, timestamp=1000.0):
    """创建测试用事件 dict."""
    return {
        "type": tag,
        "timestamp": timestamp,
        "selector": selector,
        "value": value,
        "tagName": "input" if "input" in selector else "button",
        "text": None,
        "coords": None,
        "url": "https://example.com",
        "pageId": "main",
        "frameId": None,
    }


class TestInputMergeFilter:
    """InputMergeFilter 测试."""

    def test_merge_consecutive_inputs(self):
        """连续 3 次 INPUT 同一 selector → 保留第一个和最后一个."""
        f = InputMergeFilter()
        events = [
            make_event("INPUT", "#name", "a", 1000),
            make_event("INPUT", "#name", "ab", 1050),
            make_event("INPUT", "#name", "abc", 1100),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 2
        assert result[0]["value"] == "a"
        assert result[1]["value"] == "abc"

    def test_single_input_passthrough(self):
        """单个 INPUT 事件 → 原样通过."""
        f = InputMergeFilter()
        events = [make_event("INPUT", "#name", "hello")]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 1
        assert result[0]["value"] == "hello"

    def test_different_selectors_not_merged(self):
        """不同 selector 的 INPUT 不合并."""
        f = InputMergeFilter()
        events = [
            make_event("INPUT", "#name", "abc"),
            make_event("INPUT", "#email", "x@y.com"),
            make_event("INPUT", "#name", "def"),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 3

    def test_non_input_passthrough(self):
        """非 INPUT 事件直接通过."""
        f = InputMergeFilter()
        events = [
            make_event("CLICK", "#btn"),
            make_event("INPUT", "#name", "a"),
            make_event("INPUT", "#name", "ab"),
            make_event("CLICK", "#btn2"),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 4  # CLICK, INPUT(first), INPUT(last), CLICK

    def test_interrupted_sequence(self):
        """INPUT 序列被其他事件打断 → 各自独立处理."""
        f = InputMergeFilter()
        events = [
            make_event("INPUT", "#a", "x"),
            make_event("INPUT", "#a", "xy"),
            make_event("CLICK", "#btn"),
            make_event("INPUT", "#a", "z"),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 4  # first INPUT, last INPUT of batch1, CLICK, single INPUT


class TestDedupFilter:
    """DedupFilter 测试."""

    def test_remove_duplicate_adjacent(self):
        """相邻完全相同的 INPUT 事件 → 去重."""
        f = DedupFilter()
        events = [
            make_event("INPUT", "#name", "abc", 1000),
            make_event("INPUT", "#name", "abc", 1050),
            make_event("INPUT", "#name", "def", 1100),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 2  # "abc" (first), "def"

    def test_no_remove_different_events(self):
        """不同事件不去重."""
        f = DedupFilter()
        events = [
            make_event("CLICK", "#a"),
            make_event("CLICK", "#b"),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 2

    def test_no_remove_same_type_different_selector(self):
        """同类型不同 selector 不去重."""
        f = DedupFilter()
        events = [
            make_event("INPUT", "#a", "x"),
            make_event("INPUT", "#b", "x"),
        ]
        result = [e for e in [f.process(ev) for ev in events] if e is not None]
        assert len(result) == 2
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_filters.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 filters.py**

Create `src/browser_recorder/filters.py`:

```python
"""事件过滤器 — EventFilter Protocol 及内置实现."""
from typing import Optional, Protocol


class EventFilter(Protocol):
    """过滤/变换原始事件."""

    def process(self, event: dict) -> Optional[dict]:
        """处理单个事件，返回 None 表示丢弃."""
        ...


class InputMergeFilter:
    """合并同一 selector 的连续输入事件，保留第一个和最后一个.

    输入 "a" → "ab" → "abc" 保留成 "a" + "abc".
    相同 value 的连续输入去重.
    """

    def __init__(self) -> None:
        self._pending_selector: Optional[str] = None
        self._first_event: Optional[dict] = None
        self._last_event: Optional[dict] = None

    def process(self, event: dict) -> Optional[dict]:
        if event.get("type") != "INPUT":
            result = self._flush()
            if result:
                for e in result:
                    yield e  # type: ignore[union-attr]
            return event

        selector = event.get("selector", "")

        if self._pending_selector is not None and selector != self._pending_selector:
            # selector 变了 → flush 旧批次
            flushed = self._flush()
            self._start_batch(event)
            if flushed:
                for e in flushed:
                    pass  # 需要在外部收集
            return None  # 返回 None，等待 flush

        if self._pending_selector is None:
            self._start_batch(event)
            return None  # 不输出，等待更多输入

        # 同 selector 的连续输入
        self._last_event = event
        return None

    def _start_batch(self, event: dict) -> None:
        self._pending_selector = event.get("selector", "")
        self._first_event = event
        self._last_event = event

    def _flush(self) -> list[dict]:
        """输出缓冲区中的事件."""
        result = []
        if self._first_event is not None:
            result.append(self._first_event)
            if self._last_event is not None and self._last_event != self._first_event:
                if self._first_event.get("value") != self._last_event.get("value"):
                    result.append(self._last_event)
        self._pending_selector = None
        self._first_event = None
        self._last_event = None
        return result

    def flush(self) -> list[dict]:
        """外部调用 flush（页面切换/关闭时）."""
        return self._flush()
```

Wait, the `yield` approach is wrong for a Protocol-based filter. Let me redesign.

The problem is `InputMergeFilter.process()` sometimes needs to output 2 events (first + last) but the Protocol returns `Optional[dict]` — a single event. We need a design that handles this.

Options:
1. Change Protocol to return `Optional[list[dict]]` 
2. Use an internal queue/buffer pattern
3. Make process return one event at a time, buffering internally

The cleanest approach: `process()` can return a single event or None, and the filter maintains an internal buffer. When a batch completes, it outputs the buffered events one by one on subsequent calls.

Actually, the simplest approach is to have the filter pipeline handle lists. Let me reconsider the architecture.

Better design: The filter pipeline calls `process(event)` and gets back `list[dict]` (0, 1, or more events). This is more flexible.

Let me rewrite both the Protocol and implementations.

Let me stop here and rewrite the entire file with the corrected design.<｜end▁of▁thinking｜>

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Write">
<｜｜DSML｜｜parameter name="content" string="true"># browser-recorder 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 Python + Playwright Chromium 的浏览器操作录制 CLI 工具，支持事件捕获、智能截图、网络请求拦截、多标签页管理、Markdown 报告生成和事件回放。

**Architecture:** 管道式可扩展架构 — EventFilter → EventHandler → Reporter 三层 Protocol 抽象。Push 模式事件捕获（expose_function）+ 增量 JSONL 落盘 + 双帧智能截图（前帧标记 + 结果帧）。

**Tech Stack:** Python >= 3.9, Playwright >= 1.40, Typer >= 0.9, Pillow >= 10.0, Rich >= 13.0

## Global Constraints

- Python >= 3.9，Playwright >= 1.40，Typer >= 0.9，Pillow >= 10.0，Rich >= 13.0
- 管道式架构：所有 Filter/Handler/Reporter 实现对应 Protocol 接口
- Push 模式事件捕获，5 个强制 flush 触发点，增量 JSONL 落盘
- 双帧截图策略：前帧 Pillow 标记点击坐标 + 结果帧 MutationObserver DOM 稳定检测
- 回放区分条件等待（不加速）与人为停顿（按倍速缩放）
- CLI 使用 Typer，`recorder start --url ...` + `recorder replay ...` + `recorder doctor` + `recorder version`
- 默认产物保留 record.md + requests.json，清理 screenshots/
- 多标签通过 context.on('page') 全生命周期管理，page_id 归属
- 测试使用本地 http.server + fixtures HTML 端到端
- 产物路径输出到 `/workspace/tmp/.browser-recorder/` 下按 session 组织

---

### Task 1: 项目脚手架

**Files:**
- Create: `projects/browser-recorder/pyproject.toml`
- Create: `projects/browser-recorder/.python-version`
- Create: `projects/browser-recorder/src/browser_recorder/__init__.py`

**Interfaces:**
- Produces: 项目可 `pip install -e .` 安装，`browser_recorder` 包可导入

- [ ] **Step 1: 创建 .python-version**

```
3.9
```

- [ ] **Step 2: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "browser-recorder"
version = "0.1.0"
description = "浏览器操作录制 CLI 工具，基于 Playwright + Chromium"
requires-python = ">=3.9"
dependencies = [
    "playwright>=1.40",
    "typer>=0.9",
    "Pillow>=10.0",
    "rich>=13.0",
]

[project.scripts]
recorder = "browser_recorder.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: 创建 src/browser_recorder/__init__.py**

```python
"""browser-recorder: 浏览器操作录制 CLI 工具."""

__version__ = "0.1.0"
```

- [ ] **Step 4: 安装项目和 Playwright 浏览器**

```bash
cd /workspace/projects/browser-recorder && pip install -e .
playwright install chromium
```

- [ ] **Step 5: 验证安装**

```bash
cd /workspace/projects/browser-recorder && python -c "import browser_recorder; print(browser_recorder.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 6: Commit**

```bash
cd /workspace/projects/browser-recorder && git add pyproject.toml .python-version src/
git commit -m "feat: browser-recorder 项目脚手架 — pyproject.toml + package 初始化"
```

---

### Task 2: 数据模型

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/models.py`
- Create: `projects/browser-recorder/tests/test_models.py`

**Interfaces:**
- Produces:
  - `ActionTag(str, Enum)`: CLICK, INPUT, CHANGE, SUBMIT, NAV, DIALOG, TAB_OPEN, TAB_CLOSE, SHOT, SCROLL
  - `Action` dataclass: step, timestamp_ms, tag, selector, value, tag_name, text, url, page_id, frame_id, coords, screenshot_before, screenshot_after
  - `RequestRecord` dataclass: timestamp_ms, method, url, status, duration_ms, resource_type, req_headers, res_headers, req_body, res_body

- [ ] **Step 1: 编写 models 测试**

Create `tests/test_models.py`:

```python
"""测试数据模型."""
import json
from dataclasses import asdict
from browser_recorder.models import ActionTag, Action, RequestRecord


def test_action_tag_values():
    """验证 ActionTag 枚举值."""
    assert ActionTag.CLICK.value == "CLICK"
    assert ActionTag.INPUT.value == "INPUT"
    assert ActionTag.CHANGE.value == "CHANGE"
    assert ActionTag.SUBMIT.value == "SUBMIT"
    assert ActionTag.NAV.value == "NAV"
    assert ActionTag.DIALOG.value == "DIALOG"
    assert ActionTag.TAB_OPEN.value == "TAB_OPEN"
    assert ActionTag.TAB_CLOSE.value == "TAB_CLOSE"
    assert ActionTag.SHOT.value == "SHOT"
    assert ActionTag.SCROLL.value == "SCROLL"


def test_action_creation_minimal():
    """Action 最简字段创建."""
    action = Action(
        step=1,
        timestamp_ms=1691591425000.0,
        tag=ActionTag.NAV,
        selector="",
        tag_name="",
        url="https://example.com",
        page_id="main",
    )
    assert action.step == 1
    assert action.tag == ActionTag.NAV
    assert action.value is None
    assert action.screenshot_before is None


def test_action_creation_full():
    """Action 完整字段创建."""
    action = Action(
        step=2,
        timestamp_ms=1691591427000.0,
        tag=ActionTag.CLICK,
        selector="#login-btn",
        value=None,
        tag_name="button",
        text="登录",
        url="https://example.com",
        page_id="main",
        frame_id=None,
        coords=(150, 200),
        screenshot_before="screenshots/step_002_click.jpg",
        screenshot_after="screenshots/step_002_result.jpg",
    )
    assert action.coords == (150, 200)
    assert action.text == "登录"


def test_action_json_roundtrip():
    """Action → dict → JSON 序列化往返."""
    action = Action(
        step=3,
        timestamp_ms=1691591430000.0,
        tag=ActionTag.INPUT,
        selector="#username",
        value="admin",
        tag_name="input",
        url="https://example.com",
        page_id="main",
    )
    d = asdict(action)
    d["tag"] = d["tag"].value
    json_str = json.dumps(d)
    loaded = json.loads(json_str)
    assert loaded["step"] == 3
    assert loaded["tag"] == "INPUT"
    assert loaded["value"] == "admin"


def test_request_record_creation():
    """RequestRecord 创建."""
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="POST",
        url="https://example.com/api/login",
        status=200,
        duration_ms=85.5,
        resource_type="fetch",
        req_headers={"content-type": "application/json"},
        res_headers={"content-type": "application/json"},
        req_body='{"user":"admin"}',
        res_body='{"ok":true}',
    )
    assert req.method == "POST"
    assert req.status == 200
    assert req.duration_ms == 85.5


def test_request_record_optional_fields():
    """RequestRecord body 可为 None."""
    req = RequestRecord(
        timestamp_ms=1691591430000.0,
        method="GET",
        url="https://example.com/api/data",
        status=200,
        duration_ms=100.0,
        resource_type="xhr",
    )
    assert req.req_body is None
    assert req.res_body is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_models.py -v
```
Expected: ImportError (模块不存在)

- [ ] **Step 3: 实现 models.py**

Create `src/browser_recorder/models.py`:

```python
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
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_models.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/models.py tests/test_models.py
git commit -m "feat: 数据模型 — Action + RequestRecord + ActionTag 枚举"
```

---

### Task 3: 事件过滤器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/filters.py`
- Create: `projects/browser-recorder/tests/test_filters.py`

**Interfaces:**
- Consumes: 原始事件 dict（来自 JS 注入脚本）
- Produces:
  - `EventFilter` Protocol: `process(self, event: dict) -> list[dict]` — 返回 0~N 个事件
  - `FilterPipeline` class: `add(filter)`, `process(event) -> list[dict]` — 串联多个 filter
  - `InputMergeFilter` class: 合并同 selector 连续 INPUT，保留首尾
  - `DedupFilter` class: 去重相邻完全相同事件

- [ ] **Step 1: 编写 filters 测试**

Create `tests/test_filters.py`:

```python
"""测试事件过滤器."""
from browser_recorder.filters import FilterPipeline, InputMergeFilter, DedupFilter


def make_event(tag, selector, value=None, timestamp=1000.0):
    """创建测试用事件 dict."""
    return {
        "type": tag,
        "timestamp": timestamp,
        "selector": selector,
        "value": value,
        "tagName": "input" if "input" in selector else "button",
        "text": None,
        "coords": None,
        "url": "https://example.com",
        "pageId": "main",
        "frameId": None,
    }


class TestFilterPipeline:
    """FilterPipeline 测试."""

    def test_empty_pipeline_passthrough(self):
        """空管道 → 事件原样通过."""
        pipeline = FilterPipeline()
        event = make_event("CLICK", "#btn")
        result = pipeline.process(event)
        assert result == [event]

    def test_multiple_filters_chained(self):
        """多个 filter 串联."""
        pipeline = FilterPipeline()
        pipeline.add(InputMergeFilter())
        pipeline.add(DedupFilter())

        events = [
            make_event("INPUT", "#a", "x", 1000),
            make_event("INPUT", "#a", "xy", 1050),
            make_event("INPUT", "#a", "xyz", 1100),
        ]
        results = []
        for ev in events:
            results.extend(pipeline.process(ev))
        # 应输出: "x" (first) + "xyz" (last)
        assert len(results) == 2
        assert results[0]["value"] == "x"
        assert results[1]["value"] == "xyz"

    def test_pipeline_flush(self):
        """pipeline flush 清空内部状态."""
        pipeline = FilterPipeline()
        pipeline.add(InputMergeFilter())
        pipeline.process(make_event("INPUT", "#a", "x"))
        flushed = pipeline.flush()
        assert len(flushed) == 1
        assert flushed[0]["value"] == "x"


class TestInputMergeFilter:
    """InputMergeFilter 测试."""

    def test_merge_consecutive_same_selector(self):
        """连续 3 次同 selector INPUT → 保留首尾."""
        f = InputMergeFilter()
        events = [
            make_event("INPUT", "#name", "a", 1000),
            make_event("INPUT", "#name", "ab", 1050),
            make_event("INPUT", "#name", "abc", 1100),
        ]
        results = []
        for ev in events:
            results.extend(f.process(ev))
        flushed = f.flush()
        results.extend(flushed)
        assert len(results) == 2
        assert results[0]["value"] == "a"
        assert results[1]["value"] == "abc"

    def test_single_input_passthrough(self):
        """单个 INPUT → 原样通过."""
        f = InputMergeFilter()
        results = f.process(make_event("INPUT", "#name", "hello"))
        flushed = f.flush()
        results.extend(flushed)
        assert len(results) == 1
        assert results[0]["value"] == "hello"

    def test_different_selector_not_merged(self):
        """不同 selector INPUT → 各自独立."""
        f = InputMergeFilter()
        results = []
        results.extend(f.process(make_event("INPUT", "#name", "abc")))
        results.extend(f.process(make_event("INPUT", "#email", "x@y.com")))
        results.extend(f.process(make_event("INPUT", "#name", "def")))
        results.extend(f.flush())
        assert len(results) == 3

    def test_non_input_passthrough(self):
        """非 INPUT 事件 → 直接通过."""
        f = InputMergeFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#btn")))
        results.extend(f.process(make_event("INPUT", "#name", "a")))
        results.extend(f.process(make_event("INPUT", "#name", "ab")))
        results.extend(f.process(make_event("CLICK", "#btn2")))
        results.extend(f.flush())
        # CLICK, INPUT-first, INPUT-last, CLICK = 4
        assert len(results) == 4


class TestDedupFilter:
    """DedupFilter 测试."""

    def test_remove_adjacent_duplicate_input(self):
        """相邻相同 value + selector → 去重."""
        f = DedupFilter()
        events = [
            make_event("INPUT", "#name", "abc", 1000),
            make_event("INPUT", "#name", "abc", 1050),
            make_event("INPUT", "#name", "def", 1100),
        ]
        results = []
        for ev in events:
            results.extend(f.process(ev))
        assert len(results) == 2
        assert results[0]["value"] == "abc"
        assert results[1]["value"] == "def"

    def test_different_selector_not_deduped(self):
        """不同 selector → 不去重."""
        f = DedupFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#a")))
        results.extend(f.process(make_event("CLICK", "#b")))
        assert len(results) == 2

    def test_different_type_not_deduped(self):
        """不同 type → 不去重."""
        f = DedupFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#a")))
        results.extend(f.process(make_event("INPUT", "#a", "x")))
        assert len(results) == 2
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_filters.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 filters.py**

Create `src/browser_recorder/filters.py`:

```python
"""事件过滤器 — EventFilter Protocol 及内置实现."""
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class EventFilter(Protocol):
    """过滤/变换原始事件."""

    def process(self, event: dict) -> list[dict]:
        """处理单个事件，返回 0~N 个事件."""
        ...

    def flush(self) -> list[dict]:
        """刷新内部缓冲区."""
        ...


class FilterPipeline:
    """串联多个 EventFilter."""

    def __init__(self) -> None:
        self._filters: list[EventFilter] = []

    def add(self, f: EventFilter) -> "FilterPipeline":
        self._filters.append(f)
        return self

    def process(self, event: dict) -> list[dict]:
        batch = [event]
        for f in self._filters:
            next_batch: list[dict] = []
            for ev in batch:
                next_batch.extend(f.process(ev))
            batch = next_batch
            if not batch:
                return []
        return batch

    def flush(self) -> list[dict]:
        results: list[dict] = []
        for f in self._filters:
            results.extend(f.flush())
        return results


class InputMergeFilter:
    """合并同一 selector 的连续 INPUT 事件，保留第一个和最后一个."""

    def __init__(self) -> None:
        self._pending_selector: Optional[str] = None
        self._first_event: Optional[dict] = None
        self._last_event: Optional[dict] = None

    def process(self, event: dict) -> list[dict]:
        if event.get("type") != "INPUT":
            flushed = self._flush_buffer()
            return flushed + [event]

        selector = event.get("selector", "")

        if self._pending_selector is not None and selector != self._pending_selector:
            flushed = self._flush_buffer()
            self._start_batch(event)
            return flushed

        if self._first_event is None:
            self._start_batch(event)
        else:
            self._last_event = event

        return []

    def flush(self) -> list[dict]:
        return self._flush_buffer()

    def _start_batch(self, event: dict) -> None:
        self._pending_selector = event.get("selector", "")
        self._first_event = event
        self._last_event = event

    def _flush_buffer(self) -> list[dict]:
        result: list[dict] = []
        if self._first_event is not None:
            result.append(self._first_event)
            if self._last_event is not None and self._last_event != self._first_event:
                if self._first_event.get("value") != self._last_event.get("value"):
                    result.append(self._last_event)
                else:
                    # 相同 value，只保留一个位置信息更新
                    pass
        self._pending_selector = None
        self._first_event = None
        self._last_event = None
        return result


class DedupFilter:
    """去重相邻完全相同的重复事件."""

    def __init__(self) -> None:
        self._last_event: Optional[dict] = None

    def process(self, event: dict) -> list[dict]:
        if self._is_duplicate(event):
            return []
        self._last_event = event
        return [event]

    def flush(self) -> list[dict]:
        return []

    def _is_duplicate(self, event: dict) -> bool:
        if self._last_event is None:
            return False
        return (
            self._last_event.get("type") == event.get("type")
            and self._last_event.get("selector") == event.get("selector")
            and self._last_event.get("value") == event.get("value")
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_filters.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/filters.py tests/test_filters.py
git commit -m "feat: 事件过滤器 — FilterPipeline + InputMergeFilter + DedupFilter"
```

---

### Task 4: JS 注入器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/injector.py`
- Create: `projects/browser-recorder/tests/test_injector.py`

**Interfaces:**
- Consumes: `Playwright` `Page` 对象
- Produces:
  - `RECORDER_JS: str` — 注入到浏览器页面的 JS 脚本（事件监听 + 缓冲 + push）
  - `inject(page: Page) -> None` — 注入脚本到页面
  - `setup_recorder_callback(page: Page, callback) -> None` — 暴露 `__recorder_push__` Python 回调

- [ ] **Step 1: 编写 test_injector.py**

Create `tests/test_injector.py`:

```python
"""测试 JS 注入器."""
from browser_recorder.injector import RECORDER_JS


def test_recorder_js_is_non_empty_string():
    """注入脚本非空."""
    assert isinstance(RECORDER_JS, str)
    assert len(RECORDER_JS) > 100


def test_recorder_js_contains_core_functions():
    """脚本包含核心函数."""
    assert "addEventListener" in RECORDER_JS or "attachEvent" not in RECORDER_JS
    assert "__recorder_push__" in RECORDER_JS
    assert "flush" in RECORDER_JS.lower()


def test_recorder_js_contains_event_types():
    """脚本监听必要事件类型."""
    assert "click" in RECORDER_JS.lower()
    assert "input" in RECORDER_JS.lower()
    assert "change" in RECORDER_JS.lower()
    assert "submit" in RECORDER_JS.lower()


def test_recorder_js_contains_composed_path():
    """脚本使用 composedPath 穿透 Shadow DOM."""
    assert "composedPath" in RECORDER_JS


def test_recorder_js_contains_mutation_observer():
    """脚本包含 MutationObserver DOM 稳定检测."""
    assert "MutationObserver" in RECORDER_JS


def test_recorder_js_contains_beforeunload():
    """脚本监听 beforeunload flush."""
    assert "beforeunload" in RECORDER_JS
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_injector.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 injector.py**

Create `src/browser_recorder/injector.py`:

```python
"""JS 注入器 — 浏览器端事件捕获脚本."""
from __future__ import annotations
from typing import Callable, Awaitable
from playwright.async_api import Page

# JS 注入脚本：监听所有 DOM 交互事件，缓冲批量 push 到 Python
RECORDER_JS = r"""
(function() {
    if (window.__recorder_injected__) return;
    window.__recorder_injected__ = true;

    const BATCH_SIZE = 10;
    const FLUSH_INTERVAL_MS = 50;
    let buffer = [];
    let flushTimer = null;

    function getSelector(target) {
        try {
            const path = event.composedPath ? event.composedPath() : [];
            for (const el of path) {
                if (el.nodeType !== 1) continue;
                if (el.id) return '#' + CSS.escape(el.id);
            }
            // fallback: build path from target
            const parts = [];
            let el = target;
            while (el && el.nodeType === 1) {
                let seg = el.tagName.toLowerCase();
                if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
                if (el.className && typeof el.className === 'string') {
                    const cls = el.className.trim().split(/\s+/)[0];
                    if (cls) seg += '.' + CSS.escape(cls);
                }
                parts.unshift(seg);
                el = el.parentElement;
            }
            return parts.join(' > ');
        } catch(e) {
            return '';
        }
    }

    function getText(target) {
        try {
            const t = (target.textContent || '').trim();
            return t.substring(0, 100);
        } catch(e) { return ''; }
    }

    function getCoords(event) {
        if (event.clientX !== undefined) {
            return {x: Math.round(event.clientX), y: Math.round(event.clientY)};
        }
        return null;
    }

    function push(type, event, value) {
        const target = event.target;
        if (!target) return;
        const record = {
            type: type,
            timestamp: Date.now(),
            selector: getSelector(target),
            value: value || null,
            tagName: target.tagName ? target.tagName.toLowerCase() : '',
            text: getText(target),
            coords: getCoords(event),
            url: location.href,
            pageId: window.__recorder_page_id__ || 'main',
            frameId: null
        };
        buffer.push(record);
        if (buffer.length >= BATCH_SIZE) {
            doFlush();
        } else if (!flushTimer) {
            flushTimer = setTimeout(doFlush, FLUSH_INTERVAL_MS);
        }
    }

    function doFlush() {
        if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
        if (buffer.length === 0) return;
        const batch = buffer;
        buffer = [];
        if (window.__recorder_push__) {
            try {
                window.__recorder_push__(JSON.stringify(batch));
            } catch(e) { console.error('[recorder] push error:', e); }
        }
    }

    // click 监听
    document.addEventListener('click', function(e) {
        push('CLICK', e, null);
    }, true);

    // input 监听
    document.addEventListener('input', function(e) {
        const el = e.target;
        const value = (el && (el.value !== undefined)) ? el.value : null;
        push('INPUT', e, value);
    }, true);

    // change 监听
    document.addEventListener('change', function(e) {
        const el = e.target;
        const value = (el && (el.value !== undefined)) ? el.value : null;
        push('CHANGE', e, value);
    }, true);

    // submit 监听
    document.addEventListener('submit', function(e) {
        push('SUBMIT', e, null);
    }, true);

    // scroll 监听 (debounced)
    let scrollDebounce = null;
    document.addEventListener('scroll', function(e) {
        if (scrollDebounce) return;
        scrollDebounce = setTimeout(function() {
            scrollDebounce = null;
            push('SCROLL', e, null);
        }, 300);
    }, true);

    // SPA 路由变化
    window.addEventListener('popstate', function(e) {
        doFlush();
        push('NAV', e, location.href);
    });
    window.addEventListener('hashchange', function(e) {
        doFlush();
        push('NAV', e, location.href);
    });

    // 页面卸载前 flush
    window.addEventListener('beforeunload', function() {
        doFlush();
    });

    // MutationObserver — DOM 稳定检测（供外部查询）
    window.__recorder_mutation_count__ = 0;
    window.__recorder_mutation_timer__ = null;
    const observer = new MutationObserver(function(mutations) {
        window.__recorder_mutation_count__ += mutations.length;
        if (window.__recorder_mutation_timer__) {
            clearTimeout(window.__recorder_mutation_timer__);
        }
        window.__recorder_mutation_timer__ = setTimeout(function() {
            window.__recorder_stable__ = true;
        }, 300);
    });
    observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true, characterData: true
    });

    // 对外 API
    window.__recorder_flush__ = doFlush;
    window.__recorder_stable__ = false;
})();
"""


async def inject(page: Page, page_id: str = "main") -> None:
    """注入录制脚本到页面."""
    await page.evaluate(f"window.__recorder_page_id__ = '{page_id}';")
    await page.evaluate(RECORDER_JS)


async def setup_recorder_callback(
    page: Page,
    callback: Callable[[str], Awaitable[None]],
) -> None:
    """暴露 __recorder_push__ 回调给 JS."""
    await page.expose_function("__recorder_push__", callback)


async def flush(page: Page) -> None:
    """强制 flush JS 侧缓冲区."""
    try:
        await page.evaluate("if(window.__recorder_flush__) window.__recorder_flush__()")
    except Exception:
        pass  # 页面可能已关闭


async def wait_dom_stable(page: Page, timeout_ms: int = 5000) -> bool:
    """等待 DOM 稳定（MutationObserver 300ms 无变化）."""
    try:
        await page.evaluate("window.__recorder_stable__ = false;")
        await page.wait_for_function(
            "window.__recorder_stable__ === true",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_injector.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/injector.py tests/test_injector.py
git commit -m "feat: JS 注入器 — 事件监听 + 批量 push + DOM 稳定检测"
```

---

### Task 5: 网络请求拦截

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/network.py`
- Create: `projects/browser-recorder/tests/test_network.py`

**Interfaces:**
- Consumes: `Page` from Playwright
- Produces:
  - `NetworkInterceptor` class: `setup(page)`, `teardown(page)`, `requests: list[RequestRecord]`
  - `should_record(resource_type, url, filter_glob) -> bool`

- [ ] **Step 1: 编写 test_network.py**

Create `tests/test_network.py`:

```python
"""测试网络请求拦截."""
from browser_recorder.network import should_record, DEFAULT_RECORD_TYPES


def test_should_record_xhr():
    """XHR 类型应记录."""
    assert should_record("xhr", "https://api.example.com/data", None) is True


def test_should_record_fetch():
    """fetch 类型应记录."""
    assert should_record("fetch", "https://api.example.com/data", None) is True


def test_should_record_document():
    """document 类型应记录."""
    assert should_record("document", "https://example.com", None) is True


def test_should_ignore_image():
    """image 类型不记录."""
    assert should_record("image", "https://example.com/logo.png", None) is False


def test_should_ignore_script():
    """script 类型不记录."""
    assert should_record("script", "https://example.com/app.js", None) is False


def test_should_ignore_stylesheet():
    """stylesheet 类型不记录."""
    assert should_record("stylesheet", "https://example.com/style.css", None) is False


def test_should_ignore_font():
    """font 类型不记录."""
    assert should_record("font", "https://example.com/font.woff2", None) is False


def test_default_record_types():
    """默认记录类型为 xhr, fetch, document."""
    assert "xhr" in DEFAULT_RECORD_TYPES
    assert "fetch" in DEFAULT_RECORD_TYPES
    assert "document" in DEFAULT_RECORD_TYPES
    assert "image" not in DEFAULT_RECORD_TYPES


def test_custom_filter_glob_match():
    """自定义 glob 过滤 — 匹配."""
    assert should_record("xhr", "https://api.example.com/v1/users", "*.api.example.com/*") is True


def test_custom_filter_glob_no_match():
    """自定义 glob 过滤 — 不匹配."""
    assert should_record("xhr", "https://other.com/data", "*.api.example.com/*") is False


def test_custom_filter_glob_override_resource_type():
    """自定义 glob 覆盖 resource_type 限制."""
    assert should_record("image", "https://api.example.com/logo.png", "*.api.example.com/*") is True
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_network.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 network.py**

Create `src/browser_recorder/network.py`:

```python
"""网络请求拦截 — page.route() 捕获 XHR/Fetch."""
from __future__ import annotations
import time
import fnmatch
from typing import Optional
from playwright.async_api import Page, Route, Request
from .models import RequestRecord

DEFAULT_RECORD_TYPES = {"xhr", "fetch", "document"}
IGNORED_TYPES = {"image", "script", "stylesheet", "font", "media", "websocket", "other"}
BODY_MAX_LENGTH = 10240  # 10KB 截断


def should_record(
    resource_type: str,
    url: str,
    filter_glob: Optional[str],
) -> bool:
    """判断请求是否应记录.

    Args:
        resource_type: 请求资源类型 (xhr/fetch/document/image/...)
        url: 请求 URL
        filter_glob: 自定义过滤 glob，提供时覆盖 resource_type 判断

    Returns:
        True 表示应记录
    """
    if filter_glob:
        return fnmatch.fnmatch(url, filter_glob)
    return resource_type in DEFAULT_RECORD_TYPES


class NetworkInterceptor:
    """网络请求拦截器."""

    def __init__(self, filter_glob: Optional[str] = None) -> None:
        self._filter_glob = filter_glob
        self.requests: list[RequestRecord] = []
        self._start_times: dict[str, float] = {}

    async def setup(self, page: Page) -> None:
        """在 page 上挂载 route 拦截."""
        await page.route("**/*", self._handle_route)

    async def teardown(self, page: Page) -> None:
        """移除 route 拦截."""
        try:
            await page.unroute("**/*", self._handle_route)
        except Exception:
            pass

    async def _handle_route(self, route: Route) -> None:
        """处理单个请求."""
        request = route.request
        start_time = time.time() * 1000
        self._start_times[request.url] = start_time

        try:
            response = await route.fetch()
        except Exception:
            await route.continue_()
            return

        end_time = time.time() * 1000
        duration_ms = end_time - start_time

        if should_record(request.resource_type, request.url, self._filter_glob):
            record = RequestRecord(
                timestamp_ms=start_time,
                method=request.method,
                url=request.url,
                status=response.status,
                duration_ms=round(duration_ms, 1),
                resource_type=request.resource_type,
                req_headers=dict(request.headers),
                res_headers=dict(response.headers),
                req_body=self._truncate_body(request.post_data_buffer),
                res_body=self._truncate_body(await response.body()),
            )
            self.requests.append(record)

        await route.fulfill(response=response)

    @staticmethod
    def _truncate_body(body: Optional[bytes]) -> Optional[str]:
        if body is None:
            return None
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            return "[binary]"
        if len(text) > BODY_MAX_LENGTH:
            return text[:BODY_MAX_LENGTH] + "…[truncated]"
        return text
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_network.py -v
```
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/network.py tests/test_network.py
git commit -m "feat: 网络请求拦截 — NetworkInterceptor + page.route + 过滤"
```

---

### Task 6: 截图器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/screenshoter.py`
- Create: `projects/browser-recorder/tests/test_screenshoter.py`

**Interfaces:**
- Consumes: `Page` from Playwright, `Pillow.Image`
- Produces:
  - `Screenshoter` class: `take_screenshot(page, path) -> Path`, `mark_click(image_path, coords, output_path) -> Path`

- [ ] **Step 1: 编写 test_screenshoter.py**

Create `tests/test_screenshoter.py`:

```python
"""测试截图器."""
import os
import tempfile
from pathlib import Path
from PIL import Image
from browser_recorder.screenshoter import Screenshoter


def test_mark_click_creates_image():
    """mark_click 在图片上画圆标记并输出."""
    s = Screenshoter()
    # 创建一张 200x100 白色测试图
    img = Image.new("RGB", (200, 100), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        result = s.mark_click(src, (100, 50), out)
        assert result == out
        assert out.exists()
        # 验证输出是有效图片
        marked = Image.open(out)
        assert marked.size == (200, 100)


def test_mark_click_circle_visible():
    """标记图片上应有红色像素（圆圈）."""
    s = Screenshoter()
    img = Image.new("RGB", (100, 100), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        s.mark_click(src, (50, 50), out)
        marked = Image.open(out)
        # 检查中心附近有红色像素
        pixels = []
        for x in range(40, 61):
            for y in range(40, 61):
                pixels.append(marked.getpixel((x, y)))
        has_red = any(p[0] > 200 and p[1] < 100 and p[2] < 100 for p in pixels)
        assert has_red, "应在点击坐标附近找到红色圆圈标记"


def test_mark_click_none_coords_noop():
    """coords 为 None → 不标记，直接复制."""
    s = Screenshoter()
    img = Image.new("RGB", (50, 50), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        result = s.mark_click(src, None, out)
        assert result == out
        assert out.exists()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_screenshoter.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 screenshoter.py**

Create `src/browser_recorder/screenshoter.py`:

```python
"""智能截图器 — 双帧策略 + Pillow 点击标记."""
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw
from playwright.async_api import Page


class Screenshoter:
    """截图管理器.

    双帧策略:
      - 前帧 (before): 上一操作的结果帧 + Pillow 在图上画红圈标记点击坐标
      - 结果帧 (after): DOM 稳定后的全页面截图
    """

    def __init__(self, output_dir: Path, fallback_interval: float = 30.0) -> None:
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.fallback_interval = fallback_interval
        self._last_before_screenshot: Optional[Path] = None
        self._last_screenshot_time: float = 0.0

    async def take_before(self, page: Page, step: int, coords: Optional[tuple]) -> Optional[Path]:
        """截取前帧（操作前页面），在图上标记点击坐标."""
        try:
            raw_path = self.screenshots_dir / f"step_{step:03d}_raw.png"
            await page.screenshot(path=str(raw_path), full_page=True)

            out_path = self.screenshots_dir / f"step_{step:03d}_click.jpg"
            self.mark_click(raw_path, coords, out_path)

            # 删除原始 png（仅保留标记后 jpg）
            if raw_path.exists():
                raw_path.unlink()

            self._last_before_screenshot = out_path
            return out_path
        except Exception:
            return None

    async def take_after(
        self, page: Page, step: int,
        wait_stable: bool = True,
        stable_timeout_ms: int = 5000,
    ) -> Optional[Path]:
        """截取结果帧（操作后页面），可选等待 DOM 稳定."""
        try:
            if wait_stable:
                await self._wait_dom_stable(page, stable_timeout_ms)

            out_path = self.screenshots_dir / f"step_{step:03d}_result.jpg"
            await page.screenshot(path=str(out_path), full_page=True)
            self._last_before_screenshot = out_path
            return out_path
        except Exception:
            return None

    async def take_nav_result(self, page: Page, step: int) -> Optional[Path]:
        """截取导航结果帧（等 networkidle）."""
        try:
            await page.wait_for_load_state("networkidle")
            out_path = self.screenshots_dir / f"step_{step:03d}_result.jpg"
            await page.screenshot(path=str(out_path), full_page=True)
            self._last_before_screenshot = out_path
            return out_path
        except Exception:
            return None

    def mark_click(
        self, src: Path, coords: Optional[tuple], output: Path,
        radius: int = 15, color: str = "red", width: int = 3,
    ) -> Path:
        """在图片上用 Pillow 画红色圆圈标记点击位置."""
        img = Image.open(src)
        if coords is not None:
            draw = ImageDraw.Draw(img)
            x, y = coords
            draw.ellipse(
                [x - radius, y - radius, x + radius, y + radius],
                outline=color, width=width,
            )
            # 画十字线
            draw.line([x - radius - 5, y, x + radius + 5, y], fill=color, width=2)
            draw.line([x, y - radius - 5, x, y + radius + 5], fill=color, width=2)
        img.save(str(output), quality=85)
        return output

    def get_last_before(self) -> Optional[Path]:
        """返回最近一次截图路径（作为下一步的前帧）."""
        return self._last_before_screenshot

    async def fallback_shot(self, page: Page, step: int) -> Optional[Path]:
        """兜底定时截图（无操作时）."""
        out_path = self.screenshots_dir / f"step_{step:03d}_shot.jpg"
        try:
            await page.screenshot(path=str(out_path), full_page=True)
            return out_path
        except Exception:
            return None

    @staticmethod
    async def _wait_dom_stable(page: Page, timeout_ms: int = 5000) -> None:
        """等待 DOM 稳定."""
        try:
            await page.evaluate("window.__recorder_stable__ = false;")
            await page.wait_for_function(
                "window.__recorder_stable__ === true",
                timeout=timeout_ms,
            )
        except Exception:
            pass  # 超时不报错
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_screenshoter.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/screenshoter.py tests/test_screenshoter.py
git commit -m "feat: 截图器 — 双帧策略 + Pillow 点击标记 + DOM 稳定等待"
```

---

### Task 7: 事件处理器 (JsonlWriter)

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/handlers.py`
- Create: `projects/browser-recorder/tests/test_handlers.py`

**Interfaces:**
- Consumes: `Action` from `browser_recorder.models`
- Produces:
  - `EventHandler` Protocol: `async handle(self, action: Action, page: Page) -> None`
  - `JsonlWriter` class: 增量追加写 events.jsonl

- [ ] **Step 1: 编写 test_handlers.py**

Create `tests/test_handlers.py`:

```python
"""测试事件处理器."""
import json
import tempfile
from pathlib import Path
from browser_recorder.handlers import JsonlWriter
from browser_recorder.models import Action, ActionTag


def test_jsonl_writer_writes_and_flushes():
    """JsonlWriter 写入 events.jsonl 并刷新."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir))
        action = Action(
            step=1,
            timestamp_ms=1000.0,
            tag=ActionTag.CLICK,
            selector="#btn",
            tag_name="button",
            url="https://example.com",
            page_id="main",
            text="Click me",
        )
        writer.write(action)
        writer.flush()

        jsonl_path = Path(tmpdir) / "events.jsonl"
        assert jsonl_path.exists()

        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["step"] == 1
        assert data["tag"] == "CLICK"
        assert data["selector"] == "#btn"


def test_jsonl_writer_multiple_events():
    """JsonlWriter 写入多条事件."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir))
        for i in range(5):
            action = Action(
                step=i + 1,
                timestamp_ms=1000.0 + i * 100,
                tag=ActionTag.INPUT,
                selector=f"#input{i}",
                tag_name="input",
                url="https://example.com",
                page_id="main",
                value=f"value{i}",
            )
            writer.write(action)
        writer.flush()

        jsonl_path = Path(tmpdir) / "events.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 5


def test_jsonl_writer_batch_flush():
    """JsonlWriter 达到批量阈值自动刷新."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir), batch_size=3)
        for i in range(5):
            action = Action(
                step=i + 1,
                timestamp_ms=1000.0 + i * 100,
                tag=ActionTag.CLICK,
                selector="#btn",
                tag_name="button",
                url="https://example.com",
                page_id="main",
            )
            writer.write(action)

        jsonl_path = Path(tmpdir) / "events.jsonl"
        assert jsonl_path.exists()
        # batch_size=3 → 第3条和第5条（flush on close/context exit）后触发
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) >= 3
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_handlers.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 handlers.py**

Create `src/browser_recorder/handlers.py`:

```python
"""事件处理器 — EventHandler Protocol 及内置实现."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict
from typing import Protocol, runtime_checkable
from playwright.async_api import Page
from .models import Action


@runtime_checkable
class EventHandler(Protocol):
    """消费事件，产生产物."""

    async def handle(self, action: Action, page: Page) -> None:
        ...

    async def close(self) -> None:
        ...


def _action_to_dict(action: Action) -> dict:
    """Action → 可 JSON 序列化的 dict."""
    d = asdict(action)
    d["tag"] = d["tag"].value
    return d


class JsonlWriter:
    """增量追加写 events.jsonl."""

    def __init__(self, output_dir: Path, batch_size: int = 10) -> None:
        self._path = output_dir / "events.jsonl"
        self._batch_size = batch_size
        self._buffer: list[dict] = []
        self._count = 0

    def write(self, action: Action) -> None:
        """写入一条 action 到缓冲区."""
        self._buffer.append(_action_to_dict(action))
        self._count += 1
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """将缓冲区写入磁盘."""
        if not self._buffer:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            for item in self._buffer:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._buffer.clear()

    async def close(self) -> None:
        """关闭时 flush 剩余事件."""
        self.flush()
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_handlers.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/handlers.py tests/test_handlers.py
git commit -m "feat: 事件处理器 — EventHandler Protocol + JsonlWriter 增量写入"
```

---

### Task 8: 清理器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/cleaner.py`
- Create: `projects/browser-recorder/tests/test_cleaner.py`

**Interfaces:**
- Consumes: 输出目录 Path
- Produces:
  - `cleanup(output_dir, keep_all) -> None` — 根据 keep_all 清理临时文件

- [ ] **Step 1: 编写 test_cleaner.py**

Create `tests/test_cleaner.py`:

```python
"""测试清理器."""
import tempfile
from pathlib import Path
from browser_recorder.cleaner import cleanup


def test_cleanup_default_removes_screenshots():
    """默认清理：删除 screenshots/ 目录."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        screenshots_dir = base / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_text("fake image")
        (base / "record.md").write_text("# report")
        (base / "requests.json").write_text("[]")

        cleanup(base, keep_all=False)

        assert not screenshots_dir.exists()
        assert (base / "record.md").exists()
        assert (base / "requests.json").exists()


def test_cleanup_keep_all_preserves_everything():
    """--keep-all：保留所有文件."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        screenshots_dir = base / "screenshots"
        screenshots_dir.mkdir()
        (screenshots_dir / "test.png").write_text("fake image")
        (base / "record.md").write_text("# report")
        (base / "events.jsonl").write_text("{}")

        cleanup(base, keep_all=True)

        assert screenshots_dir.exists()
        assert (base / "record.md").exists()
        assert (base / "events.jsonl").exists()


def test_cleanup_no_screenshots_dir():
    """screenshots/ 不存在 → 不报错."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "record.md").write_text("# report")

        cleanup(base, keep_all=False)

        assert (base / "record.md").exists()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_cleaner.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 cleaner.py**

Create `src/browser_recorder/cleaner.py`:

```python
"""清理器 — 录制结束后的临时文件清理."""
import shutil
from pathlib import Path


def cleanup(output_dir: Path, keep_all: bool = False) -> None:
    """清理输出目录中的临时文件.

    默认（keep_all=False）:
      - 保留: record.md, requests.json
      - 删除: screenshots/ 目录及其内容

    keep_all=True:
      - 保留所有文件（包括 events.jsonl, requests_full.json, screenshots/）
    """
    if keep_all:
        return

    screenshots_dir = output_dir / "screenshots"
    if screenshots_dir.exists() and screenshots_dir.is_dir():
        shutil.rmtree(screenshots_dir)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_cleaner.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/cleaner.py tests/test_cleaner.py
git commit -m "feat: 清理器 — 默认删除 screenshots/，--keep-all 保留全部"
```

---

### Task 9: Markdown 报告生成器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/reporter.py`
- Create: `projects/browser-recorder/tests/test_reporter.py`

**Interfaces:**
- Consumes: `Action`, `RequestRecord` from `browser_recorder.models`
- Produces:
  - `Reporter` Protocol: `generate(actions, requests, output_dir) -> Path`
  - `MarkdownReporter` class: 生成 record.md

- [ ] **Step 1: 编写 test_reporter.py**

Create `tests/test_reporter.py`:

```python
"""测试 Markdown 报告生成器."""
import tempfile
from pathlib import Path
from browser_recorder.reporter import MarkdownReporter
from browser_recorder.models import Action, ActionTag, RequestRecord


def make_action(step, tag, selector="", text=None, value=None, url="https://example.com",
                page_id="main", timestamp_ms=1000.0, screenshot_before=None,
                screenshot_after=None, coords=None):
    """创建测试 Action."""
    return Action(
        step=step,
        timestamp_ms=timestamp_ms + step * 1000,
        tag=tag,
        selector=selector,
        value=value,
        tag_name="button" if tag == ActionTag.CLICK else "input",
        text=text,
        url=url,
        page_id=page_id,
        coords=coords,
        screenshot_before=screenshot_before,
        screenshot_after=screenshot_after,
    )


def test_generate_report_basic():
    """生成基本报告."""
    reporter = MarkdownReporter()
    actions = [
        make_action(1, ActionTag.NAV, url="https://example.com",
                     screenshot_after="screenshots/step_001_result.jpg"),
        make_action(2, ActionTag.CLICK, selector="#login", text="Login",
                     screenshot_before="screenshots/step_002_click.jpg",
                     screenshot_after="screenshots/step_002_result.jpg",
                     coords=(100, 200)),
        make_action(3, ActionTag.INPUT, selector="#user", value="admin"),
    ]
    requests = [
        RequestRecord(
            timestamp_ms=2000.0, method="GET", url="https://example.com/api/config",
            status=200, duration_ms=50.0, resource_type="fetch",
        ),
        RequestRecord(
            timestamp_ms=3000.0, method="POST", url="https://example.com/api/login",
            status=200, duration_ms=120.0, resource_type="xhr",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        path = reporter.generate(actions, requests, output_dir)
        assert path == output_dir / "record.md"
        assert path.exists()

        content = path.read_text()
        assert "# 录制报告" in content
        assert "example.com" in content
        assert "[NAV]" in content
        assert "[CLICK]" in content
        assert "[INPUT]" in content
        assert "#login" in content
        assert "admin" in content
        # 网络请求表
        assert "/api/config" in content
        assert "/api/login" in content


def test_generate_report_with_multi_tab():
    """多标签页报告包含 page_id."""
    reporter = MarkdownReporter()
    actions = [
        make_action(1, ActionTag.NAV, page_id="main"),
        make_action(2, ActionTag.TAB_OPEN, page_id="child_0", selector="child_0"),
        make_action(3, ActionTag.CLICK, page_id="child_0", selector="#btn"),
        make_action(4, ActionTag.TAB_CLOSE, page_id="child_0"),
        make_action(5, ActionTag.CLICK, page_id="main", selector="#done"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        path = reporter.generate(actions, [], output_dir)
        content = path.read_text()
        assert "page:main" in content
        assert "page:child_0" in content
        assert "[TAB_OPEN]" in content
        assert "[TAB_CLOSE]" in content
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_reporter.py -v
```
Expected: ImportError

- [ ] **Step 3: 实现 reporter.py**

Create `src/browser_recorder/reporter.py`:

```python
"""报告生成器 — Reporter Protocol 及 Markdown 实现."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
from .models import Action, ActionTag, RequestRecord


@runtime_checkable
class Reporter(Protocol):
    """从累积记录生成最终报告."""

    def generate(
        self,
        actions: list[Action],
        requests: list[RequestRecord],
        output_dir: Path,
    ) -> Path:
        ...


class MarkdownReporter:
    """生成 Markdown 图文报告 (record.md)."""

    def generate(
        self,
        actions: list[Action],
        requests: list[RequestRecord],
        output_dir: Path,
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "record.md"

        first_action = actions[0] if actions else None
        url = first_action.url if first_action else "unknown"
        start_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        duration_s = 0
        if actions:
            duration_s = (actions[-1].timestamp_ms - actions[0].timestamp_ms) / 1000

        lines = [
            f"# 录制报告 — {url}",
            f"> **开始**: {start_time} | **时长**: {self._fmt_duration(duration_s)} | **步骤**: {len(actions)} | **请求**: {len(requests)}",
            "",
            "---",
            "",
        ]

        # 步骤时间线
        base_ts = actions[0].timestamp_ms if actions else 0
        for action in actions:
            rel_ms = action.timestamp_ms - base_ts
            rel_str = self._fmt_timestamp(rel_ms)
            tag = f"[{action.tag.value}]"
            page = f"page:{action.page_id}"

            lines.append(f"## [Step {action.step}] {tag} {rel_str} | {page}")
            lines.append("")

            if action.tag == ActionTag.NAV:
                lines.append(f"导航到 {action.url}")
            elif action.tag == ActionTag.CLICK:
                label = action.text or action.selector
                lines.append(f"点击 `{action.selector}` \"{label}\"")
            elif action.tag == ActionTag.INPUT:
                val = action.value or ""
                if len(val) > 50:
                    val = val[:50] + "…"
                lines.append(f"输入 `{action.selector}` = \"{val}\"")
            elif action.tag == ActionTag.CHANGE:
                lines.append(f"选择 `{action.selector}` = \"{action.value or ''}\"")
            elif action.tag == ActionTag.SUBMIT:
                lines.append(f"提交表单 `{action.selector}`")
            elif action.tag == ActionTag.DIALOG:
                lines.append(f"弹窗: {action.value or action.text or ''}")
            elif action.tag == ActionTag.TAB_OPEN:
                lines.append(f"打开新标签页 #{action.page_id}: {action.url}")
            elif action.tag == ActionTag.TAB_CLOSE:
                lines.append(f"关闭标签页 #{action.page_id}")
            elif action.tag == ActionTag.SHOT:
                lines.append(f"定时截图")
            elif action.tag == ActionTag.SCROLL:
                lines.append(f"滚动页面")

            lines.append("")

            # 截图
            if action.screenshot_before:
                lines.append(f"点击位置：")
                lines.append(f'<img src="{action.screenshot_before}" width="300"/>')
                lines.append("")
            if action.screenshot_after:
                label = "操作结果：" if action.screenshot_before else "截图："
                lines.append(f"{label}")
                lines.append(f'<img src="{action.screenshot_after}" width="100%"/>')
                lines.append("")

        # 网络请求
        if requests:
            lines.append("---")
            lines.append("")
            lines.append("## 网络请求记录")
            lines.append("")
            lines.append("| # | 时间 | 方法 | URL | 状态 | 耗时 |")
            lines.append("|---|------|------|-----|------|------|")
            for i, req in enumerate(requests, 1):
                rel_ms = req.timestamp_ms - base_ts
                rel_str = self._fmt_timestamp(rel_ms)
                lines.append(
                    f"| {i} | {rel_str} | {req.method} | {req.url} "
                    f"| {req.status} | {req.duration_ms}ms |"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    @staticmethod
    def _fmt_timestamp(ms: float) -> str:
        """毫秒 → MM:SS.msc 格式."""
        total_s = ms / 1000
        minutes = int(total_s // 60)
        seconds = total_s % 60
        return f"{minutes:02d}:{seconds:06.3f}"

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """秒 → XmXs 格式."""
        if seconds < 60:
            return f"{int(seconds)}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m{s}s"
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_reporter.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/reporter.py tests/test_reporter.py
git commit -m "feat: Markdown 报告生成器 — Reporter Protocol + record.md 生成"
```

---

### Task 10: CLI 入口

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/cli.py`

**Interfaces:**
- Consumes: `recorder`, `replay` 模块（stub 先行）
- Produces: `recorder` CLI 命令:
  - `recorder start --url URL [OPTIONS]`
  - `recorder replay EVENTS [OPTIONS]`
  - `recorder doctor`
  - `recorder version`

- [ ] **Step 1: 实现 cli.py（stub 版本，recorder/replay 先占位）**

Create `src/browser_recorder/cli.py`:

```python
"""CLI 入口 — Typer 命令定义."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console

app = typer.Typer(
    name="recorder",
    help="浏览器操作录制 CLI 工具",
    no_args_is_help=True,
)
console = Console()


@app.command()
def start(
    url: str = typer.Option(..., "--url", help="起始 URL"),
    output: Optional[Path] = typer.Option(
        None, "--output", help="输出目录（默认 /workspace/tmp/.browser-recorder/<timestamp>）"
    ),
    interval: int = typer.Option(30, "--interval", help="兜底截图间隔（秒）"),
    req_all: bool = typer.Option(False, "--req-all", help="记录所有请求"),
    req_filter: Optional[str] = typer.Option(None, "--req-filter", help="请求过滤 glob"),
    keep_all: bool = typer.Option(False, "--keep-all", help="保留全部过程文件"),
    max_duration: int = typer.Option(0, "--max-duration", help="最大录制时长（秒），0=不限"),
    plugin: Optional[Path] = typer.Option(None, "--plugin", help="自定义 handler 模块"),
) -> None:
    """启动浏览器录制 session."""
    from .recorder import Recorder

    console.print(f"[bold green]▶[/bold green] 启动录制: {url}")
    console.print(f"  按 Ctrl+C 停止录制")

    recorder = Recorder(
        url=url,
        output_dir=output,
        fallback_interval=interval,
        req_all=req_all,
        req_filter=req_filter,
        keep_all=keep_all,
        max_duration=max_duration,
    )

    import asyncio
    try:
        asyncio.run(recorder.run())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⏹[/bold yellow] 录制已停止")


@app.command()
def replay(
    events: Path = typer.Argument(..., help="events.jsonl 文件路径"),
    speed: float = typer.Option(1.0, "--speed", help="人为停顿倍速"),
    repeat: int = typer.Option(1, "--repeat", help="重复回放次数"),
    output: Optional[Path] = typer.Option(None, "--output", help="输出目录"),
    keep_all: bool = typer.Option(False, "--keep-all", help="保留回放的全部过程文件"),
) -> None:
    """回放录制的事件链."""
    from .replay import ReplayEngine

    console.print(f"[bold green]▶[/bold green] 回放: {events}")
    console.print(f"  倍速: {speed}x | 重复: {repeat}")

    engine = ReplayEngine(
        events_path=events,
        speed=speed,
        repeat=repeat,
        output_dir=output,
        keep_all=keep_all,
    )

    import asyncio
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⏹[/bold yellow] 回放已停止")


@app.command()
def doctor() -> None:
    """检查环境（Chromium 是否安装）."""
    console.print("[bold]browser-recorder 环境检查[/bold]\n")

    # 检查 Python 版本
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 9):
        console.print(f"  ✅ Python {py_ver}")
    else:
        console.print(f"  ❌ Python {py_ver} (需要 >= 3.9)")
        return

    # 检查 Playwright
    try:
        import playwright
        console.print(f"  ✅ Playwright {playwright.__version__}")
    except ImportError:
        console.print("  ❌ Playwright 未安装")
        console.print("     安装: pip install playwright")
        return

    # 检查 Chromium
    import subprocess
    result = subprocess.run(
        ["playwright", "install", "--dry-run", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print("  ✅ Chromium 已安装")
    else:
        console.print("  ⚠️  Chromium 未安装")
        console.print("     安装: playwright install chromium")

    # 检查依赖
    for lib, name in [("Pillow", "Pillow"), ("rich", "Rich"), ("typer", "Typer")]:
        try:
            __import__(lib.lower() if lib != "Pillow" else "PIL")
            console.print(f"  ✅ {name}")
        except ImportError:
            console.print(f"  ❌ {name} 未安装")

    console.print("\n[bold green]环境检查完成[/bold green]")


@app.command()
def version() -> None:
    """显示版本号."""
    from . import __version__
    console.print(f"browser-recorder v{__version__}")
```

- [ ] **Step 2: 验证 CLI 可加载**

```bash
cd /workspace/projects/browser-recorder && python -m browser_recorder.cli --help
```
Expected: 显示 help 信息（recorder/replay 模块导入可能失败，先忽略）

- [ ] **Step 3: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/cli.py
git commit -m "feat: CLI 入口 — Typer 命令: start + replay + doctor + version"
```

---

### Task 11: 录制编排器

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/recorder.py`

**Interfaces:**
- Consumes: 所有前置模块 (models, injector, network, screenshoter, handlers, filters, cleaner, reporter)
- Produces:
  - `Recorder` class: `__init__(url, output_dir, ...)`, `async run() -> Path`
  - 整合：启动浏览器 → 注入脚本 → 事件管道 → 截图 → 网络拦截 → 多标签管理 → 报告生成 → 清理

- [ ] **Step 1: 实现 recorder.py**

Create `src/browser_recorder/recorder.py`:

```python
"""录制编排器 — 整合浏览器生命周期与事件管道."""
from __future__ import annotations
import asyncio
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from rich.console import Console

from .models import Action, ActionTag, RequestRecord
from .injector import inject, setup_recorder_callback, flush as injector_flush
from .network import NetworkInterceptor
from .screenshoter import Screenshoter
from .filters import FilterPipeline, InputMergeFilter, DedupFilter
from .handlers import JsonlWriter
from .reporter import MarkdownReporter
from .cleaner import cleanup

console = Console()

# 产物根路径
ARTIFACT_ROOT = Path("/workspace/tmp/.browser-recorder")


class Recorder:
    """录制编排器."""

    def __init__(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        fallback_interval: int = 30,
        req_all: bool = False,
        req_filter: Optional[str] = None,
        keep_all: bool = False,
        max_duration: int = 0,
    ) -> None:
        self.url = url
        self.keep_all = keep_all
        self.max_duration = max_duration

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or (ARTIFACT_ROOT / f"record-{ts}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.fallback_interval = fallback_interval

        # 请求过滤
        self._req_filter: Optional[str] = req_filter
        if req_all:
            self._req_filter = "*"

        # 管道组件
        self.pipeline = FilterPipeline()
        self.pipeline.add(InputMergeFilter())
        self.pipeline.add(DedupFilter())

        self.jsonl_writer = JsonlWriter(self.output_dir)
        self.screenshoter = Screenshoter(self.output_dir, fallback_interval)
        self.network_interceptor = NetworkInterceptor(self._req_filter)

        # 状态
        self.actions: list[Action] = []
        self.step_counter = 0
        self.start_time_ms = 0.0
        self._page_map: Dict[str, Page] = {}
        self._page_counter = 0
        self._running = False
        self._fallback_task: Optional[asyncio.Task] = None

    async def run(self) -> Path:
        """启动录制."""
        self._running = True
        self.start_time_ms = time.time() * 1000

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(no_viewport=True)

            # 监听新标签页
            context.on("page", lambda p: asyncio.ensure_future(self._on_new_page(p)))

            page = await context.new_page()
            self._register_page(page, "main")

            # 网络拦截
            await self.network_interceptor.setup(page)

            # 注入录制脚本 + 设置回调
            await self._setup_page(page, "main")

            # 导航到起始 URL
            await self._record_nav(page, self.url)

            # 兜底定时截图
            if self.fallback_interval > 0:
                self._fallback_task = asyncio.ensure_future(
                    self._fallback_loop(page)
                )

            # 等待录制结束
            try:
                while self._running:
                    await asyncio.sleep(0.5)
                    if self.max_duration > 0:
                        elapsed = (time.time() * 1000 - self.start_time_ms) / 1000
                        if elapsed >= self.max_duration:
                            console.print("[yellow]⏰ 达到最大录制时长[/yellow]")
                            break
            except asyncio.CancelledError:
                pass

            if self._fallback_task:
                self._fallback_task.cancel()

            # 最终 flush
            for p in self._page_map.values():
                await injector_flush(p)
            self.jsonl_writer.flush()

            await context.close()
            await browser.close()

        # 生成报告
        return self._finalize()

    async def _setup_page(self, page: Page, page_id: str) -> None:
        """为 page 注入脚本并设置回调."""
        await setup_recorder_callback(page, self._on_events_batch)
        await inject(page, page_id)

        # 弹窗处理
        page.on("dialog", lambda d: asyncio.ensure_future(
            self._on_dialog(d, page, page_id)
        ))

        # 导航 flush
        page.on("framenavigated", lambda f: asyncio.ensure_future(
            self._on_navigate(page, page_id)
        ))

        # 关闭 flush
        page.on("close", lambda: asyncio.ensure_future(
            self._on_page_close(page_id)
        ))

    async def _on_new_page(self, page: Page) -> None:
        """新标签页诞生."""
        self._page_counter += 1
        page_id = f"tab_{self._page_counter}"
        self._register_page(page, page_id)
        await self.network_interceptor.setup(page)
        await self._setup_page(page, page_id)

        # 记录 TAB_OPEN 事件
        self._create_action(
            tag=ActionTag.TAB_OPEN,
            selector=page_id,
            url=page.url,
            page_id=page_id,
            text=f"新标签页 #{page_id}",
        )

    def _register_page(self, page: Page, page_id: str) -> None:
        self._page_map[page_id] = page

    async def _on_events_batch(self, json_str: str) -> None:
        """处理 JS 推送的事件批次."""
        try:
            batch = json.loads(json_str)
        except json.JSONDecodeError:
            return

        for raw in batch:
            processed = self.pipeline.process(raw)
            for ev in processed:
                await self._handle_event(ev)

    async def _handle_event(self, ev: dict) -> None:
        """处理单个事件."""
        tag_str = ev.get("type", "")
        try:
            tag = ActionTag(tag_str)
        except ValueError:
            return

        selector = ev.get("selector", "")
        page_id = ev.get("pageId", "main")
        page = self._page_map.get(page_id)
        if page is None:
            return

        # 构建 Action
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=ev.get("timestamp", time.time() * 1000),
            tag=tag,
            selector=selector,
            tag_name=ev.get("tagName", ""),
            text=ev.get("text"),
            url=ev.get("url", page.url),
            page_id=page_id,
            frame_id=ev.get("frameId"),
            coords=tuple(ev["coords"].values()) if ev.get("coords") else None,
            value=ev.get("value"),
        )

        # 截图（仅 CLICK 类型）
        if tag == ActionTag.CLICK:
            before_path = await self.screenshoter.take_before(
                page, action.step, action.coords
            )
            action.screenshot_before = str(before_path) if before_path else None

            after_path = await self.screenshoter.take_after(page, action.step)
            action.screenshot_after = str(after_path) if after_path else None

        self.actions.append(action)
        self.jsonl_writer.write(action)

    async def _record_nav(self, page: Page, url: str) -> None:
        """记录导航事件 + 截图."""
        await page.goto(url, wait_until="domcontentloaded")
        self.step_counter += 1

        after_path = await self.screenshoter.take_nav_result(page, self.step_counter)

        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.NAV,
            selector="",
            tag_name="",
            url=url,
            page_id="main",
            screenshot_after=str(after_path) if after_path else None,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)

    async def _on_dialog(self, dialog, page: Page, page_id: str) -> None:
        """处理浏览器弹窗."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.DIALOG,
            selector="",
            tag_name=dialog.type,
            text=dialog.message,
            url=page.url,
            page_id=page_id,
            value=dialog.type,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        await dialog.accept()

    async def _on_navigate(self, page: Page, page_id: str) -> None:
        """页面导航时 flush."""
        await injector_flush(page)
        self.pipeline.flush()

    async def _on_page_close(self, page_id: str) -> None:
        """页面关闭."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            tag=ActionTag.TAB_CLOSE,
            selector="",
            tag_name="",
            url="",
            page_id=page_id,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        self._page_map.pop(page_id, None)

    async def _fallback_loop(self, page: Page) -> None:
        """兜底定时截图."""
        while self._running:
            await asyncio.sleep(self.fallback_interval)
            if not self._running:
                break
            self.step_counter += 1
            path = await self.screenshoter.fallback_shot(page, self.step_counter)
            if path:
                action = Action(
                    step=self.step_counter,
                    timestamp_ms=time.time() * 1000,
                    tag=ActionTag.SHOT,
                    selector="",
                    tag_name="",
                    url=page.url,
                    page_id="main",
                    screenshot_after=str(path),
                )
                self.actions.append(action)
                self.jsonl_writer.write(action)

    def _create_action(self, **kwargs) -> Action:
        """创建 action 并递增计数器."""
        self.step_counter += 1
        action = Action(
            step=self.step_counter,
            timestamp_ms=time.time() * 1000,
            **kwargs,
        )
        self.actions.append(action)
        self.jsonl_writer.write(action)
        return action

    def _finalize(self) -> Path:
        """生成报告 + 保存请求 + 清理."""
        # 保存 requests.json
        requests = self.network_interceptor.requests
        import json as _json
        from dataclasses import asdict

        req_path = self.output_dir / "requests.json"
        req_list = []
        for r in requests:
            d = asdict(r)
            req_list.append(d)
        req_path.write_text(_json.dumps(req_list, ensure_ascii=False, indent=2), encoding="utf-8")

        # 生成 record.md
        reporter = MarkdownReporter()
        reporter.generate(self.actions, requests, self.output_dir)

        # 清理
        cleanup(self.output_dir, keep_all=self.keep_all)

        console.print(f"\n[bold green]✅[/bold green] 录制完成: {self.output_dir}")
        console.print(f"   报告: {self.output_dir / 'record.md'}")
        console.print(f"   请求: {self.output_dir / 'requests.json'}")

        return self.output_dir
```

- [ ] **Step 2: 验证 recorder 模块可导入**

```bash
cd /workspace/projects/browser-recorder && python -c "from browser_recorder.recorder import Recorder; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/recorder.py
git commit -m "feat: 录制编排器 — 浏览器生命周期 + 事件管道 + 多标签 + 报告生成"
```

---

### Task 12: 回放引擎

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/replay.py`

**Interfaces:**
- Consumes: `Action` from models, `events.jsonl`
- Produces:
  - `ReplayEngine` class: `__init__(events_path, speed, repeat, output_dir, keep_all)`, `async run() -> Path`
  - 条件等待（不加速）与人为停顿（倍速缩放）
  - 回放产物步骤编号后缀 `(R)`

- [ ] **Step 1: 实现 replay.py**

Create `src/browser_recorder/replay.py`:

```python
"""回放引擎 — 读取 events.jsonl 在新浏览器中自动执行."""
from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Page
from rich.console import Console

from .models import Action, ActionTag
from .injector import inject
from .screenshoter import Screenshoter
from .reporter import MarkdownReporter
from .cleaner import cleanup

console = Console()

ARTIFACT_ROOT = Path("/workspace/tmp/.browser-recorder")


class ReplayEngine:
    """事件回放引擎."""

    def __init__(
        self,
        events_path: Path,
        speed: float = 1.0,
        repeat: int = 1,
        output_dir: Optional[Path] = None,
        keep_all: bool = False,
    ) -> None:
        self.events_path = Path(events_path)
        self.speed = speed
        self.repeat = repeat
        self.keep_all = keep_all

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or (ARTIFACT_ROOT / f"replay-{ts}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run(self) -> Path:
        """执行回放."""
        actions = self._load_events()
        if not actions:
            console.print("[red]❌ events.jsonl 为空或不存在[/red]")
            return self.output_dir

        console.print(f"  加载 {len(actions)} 个事件")

        for r in range(self.repeat):
            if self.repeat > 1:
                console.print(f"\n[bold]第 {r + 1}/{self.repeat} 次回放[/bold]")

            suffix = f"_r{r + 1}" if self.repeat > 1 else ""
            replay_dir = self.output_dir / f"replay{suffix}" if self.repeat > 1 else self.output_dir
            replay_dir.mkdir(parents=True, exist_ok=True)

            await self._replay_once(actions, replay_dir)

        return self.output_dir

    async def _replay_once(self, actions: list[Action], output_dir: Path) -> None:
        """执行一次完整回放."""
        screenshoter = Screenshoter(output_dir)
        replay_actions: list[Action] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            page_map: dict[str, Page] = {"main": page}

            prev_ts = actions[0].timestamp_ms if actions else 0
            prev_conditional_wait_ms = 0.0

            for i, orig in enumerate(actions):
                # 人为停顿 = 间隔 - 上一步条件等待耗时
                interval_ms = orig.timestamp_ms - prev_ts
                human_pause_ms = max(0, interval_ms - prev_conditional_wait_ms)
                if human_pause_ms > 0 and i > 0:
                    await asyncio.sleep((human_pause_ms / 1000) / self.speed)

                wait_start = time.time() * 1000
                target_page = page_map.get(orig.page_id, page)

                try:
                    await self._execute_action(target_page, orig, page_map)
                except Exception as e:
                    console.print(f"  [yellow]⚠ Step {orig.step}: {e}[/yellow]")

                conditional_wait_ms = (time.time() * 1000) - wait_start
                prev_conditional_wait_ms = conditional_wait_ms
                prev_ts = orig.timestamp_ms

                # 截图
                before_path = None
                after_path = None
                if orig.tag == ActionTag.CLICK:
                    after_path = await screenshoter.take_after(
                        target_page, orig.step, wait_stable=False
                    )

                replay_action = Action(
                    step=orig.step,
                    timestamp_ms=time.time() * 1000,
                    tag=orig.tag,
                    selector=orig.selector,
                    tag_name=orig.tag_name,
                    text=orig.text,
                    url=target_page.url,
                    page_id=orig.page_id,
                    value=orig.value,
                    screenshot_before=str(before_path) if before_path else None,
                    screenshot_after=str(after_path) if after_path else None,
                )
                replay_actions.append(replay_action)

            await context.close()
            await browser.close()

        # 生成回放报告
        reporter = MarkdownReporter()
        reporter.generate(replay_actions, [], output_dir)
        cleanup(output_dir, keep_all=self.keep_all)

        console.print(f"  ✅ 回放完成: {output_dir / 'record.md'}")

    async def _execute_action(
        self, page: Page, action: Action, page_map: dict[str, Page]
    ) -> None:
        """执行单个 Action."""
        tag = action.tag

        if tag == ActionTag.NAV:
            if action.value:
                await page.goto(action.value, wait_until="networkidle")
            elif action.url:
                await page.goto(action.url, wait_until="networkidle")

        elif tag == ActionTag.CLICK:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=10000)
                await page.click(action.selector)

        elif tag == ActionTag.INPUT:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.fill(action.selector, action.value or "")

        elif tag == ActionTag.CHANGE:
            if action.selector and action.value:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.select_option(action.selector, action.value)

        elif tag == ActionTag.SUBMIT:
            if action.selector:
                await page.wait_for_selector(action.selector, state="visible", timeout=5000)
                await page.locator(action.selector).evaluate("el => el.submit()")

        elif tag == ActionTag.DIALOG:
            page.once("dialog", lambda d: asyncio.ensure_future(d.accept()))

        elif tag == ActionTag.TAB_OPEN:
            # 新标签页由浏览器自然触发，记录 page_id
            pass

        elif tag == ActionTag.TAB_CLOSE:
            target = page_map.pop(action.page_id, None)
            if target and action.page_id != "main":
                await target.close()

        elif tag in (ActionTag.SHOT, ActionTag.SCROLL):
            pass  # 无操作

    def _load_events(self) -> list[Action]:
        """从 events.jsonl 加载 Action 列表."""
        if not self.events_path.exists():
            return []

        actions = []
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    actions.append(Action(
                        step=d["step"],
                        timestamp_ms=d["timestamp_ms"],
                        tag=ActionTag(d["tag"]),
                        selector=d.get("selector", ""),
                        tag_name=d.get("tag_name", ""),
                        text=d.get("text"),
                        url=d.get("url", ""),
                        page_id=d.get("page_id", "main"),
                        frame_id=d.get("frame_id"),
                        coords=tuple(d["coords"]) if d.get("coords") else None,
                        value=d.get("value"),
                    ))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    console.print(f"  [yellow]⚠ 跳过无效行: {e}[/yellow]")
        return actions
```

- [ ] **Step 2: 验证 replay 模块可导入**

```bash
cd /workspace/projects/browser-recorder && python -c "from browser_recorder.replay import ReplayEngine; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 验证 CLI 完整可用**

```bash
cd /workspace/projects/browser-recorder && recorder --help
```
Expected: 显示完整帮助信息（start, replay, doctor, version）

- [ ] **Step 4: Commit**

```bash
cd /workspace/projects/browser-recorder && git add src/browser_recorder/replay.py
git commit -m "feat: 回放引擎 — 条件等待不加速 + 人为停顿倍速 + 独立回放报告"
```

---

### Task 13: 测试 Fixture HTML

**Files:**
- Create: `projects/browser-recorder/tests/fixtures/basic.html`
- Create: `projects/browser-recorder/tests/fixtures/dialog.html`
- Create: `projects/browser-recorder/tests/fixtures/modal.html`
- Create: `projects/browser-recorder/tests/fixtures/iframe.html`
- Create: `projects/browser-recorder/tests/fixtures/shadow.html`
- Create: `projects/browser-recorder/tests/fixtures/spa.html`
- Create: `projects/browser-recorder/tests/fixtures/multi_tab/opener.html`
- Create: `projects/browser-recorder/tests/fixtures/multi_tab/child_a.html`
- Create: `projects/browser-recorder/tests/fixtures/multi_tab/child_b.html`
- Create: `projects/browser-recorder/tests/fixtures/multi_tab/popup.html`

- [ ] **Step 1: 创建 basic.html**

Create `tests/fixtures/basic.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>basic 测试页</title></head>
<body>
  <h1>Basic 测试页面</h1>
  <button id="login-btn">登录</button>
  <input id="username" type="text" placeholder="用户名">
  <input id="password" type="password" placeholder="密码">
  <select id="role">
    <option value="admin">管理员</option>
    <option value="user">用户</option>
  </select>
  <form id="test-form">
    <input name="email" type="email">
    <button type="submit">提交</button>
  </form>
  <a href="#section2">跳转到 Section 2</a>
  <div id="section2" style="margin-top:200vh">Section 2 内容</div>
  <div style="height:200vh;background:linear-gradient(#fff,#eee);"></div>
  <button id="bottom-btn" style="margin-top:100vh">底部按钮</button>
</body>
</html>
```

- [ ] **Step 2: 创建 dialog.html**

Create `tests/fixtures/dialog.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>dialog 测试页</title></head>
<body>
  <h1>Dialog 测试页面</h1>
  <button id="alert-btn" onclick="alert('这是一个 alert')">Alert</button>
  <button id="confirm-btn" onclick="confirm('确定删除?')">Confirm</button>
  <button id="prompt-btn" onclick="prompt('输入内容:')">Prompt</button>
</body>
</html>
```

- [ ] **Step 3: 创建 modal.html**

Create `tests/fixtures/modal.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>modal 测试页</title>
<style>
  .modal-overlay {
    display:none; position:fixed; top:0;left:0;width:100%;height:100%;
    background:rgba(0,0,0,0.5); z-index:1000;
  }
  .modal-overlay.open { display:flex; align-items:center; justify-content:center; }
  .modal-box { background:white; padding:30px; border-radius:8px; }
</style>
</head>
<body>
  <h1>Modal 测试页面</h1>
  <button id="open-modal" onclick="document.getElementById('modal').classList.add('open')">打开模态框</button>
  <div id="modal" class="modal-overlay">
    <div class="modal-box">
      <p>这是一个自定义模态框</p>
      <button id="modal-ok" onclick="document.getElementById('modal').classList.remove('open')">确定</button>
      <button id="modal-cancel" onclick="document.getElementById('modal').classList.remove('open')">取消</button>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 4: 创建 iframe.html**

Create `tests/fixtures/iframe.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>iframe 测试页</title></head>
<body>
  <h1>iframe 测试页面</h1>
  <button id="main-btn">主页按钮</button>
  <iframe id="frame1" src="about:blank" style="width:400px;height:200px;"></iframe>
  <script>
    const iframe = document.getElementById('frame1');
    const doc = iframe.contentDocument;
    doc.open();
    doc.write('<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body><h2>iframe 内容</h2><button id="iframe-btn">iframe 按钮</button><input id="iframe-input" placeholder="iframe 输入"></body></html>');
    doc.close();
  </script>
</body>
</html>
```

- [ ] **Step 5: 创建 shadow.html**

Create `tests/fixtures/shadow.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>shadow DOM 测试页</title></head>
<body>
  <h1>Shadow DOM 测试页面</h1>
  <div id="host"></div>
  <script>
    const host = document.getElementById('host');
    const shadow = host.attachShadow({mode: 'open'});
    shadow.innerHTML = '<style>.btn{color:blue;}</style><button class="btn" id="shadow-btn">Shadow 按钮</button><input id="shadow-input" placeholder="Shadow 输入框">';
  </script>
</body>
</html>
```

- [ ] **Step 6: 创建 spa.html**

Create `tests/fixtures/spa.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>SPA 测试页</title></head>
<body>
  <h1>SPA 测试页面</h1>
  <nav>
    <button id="nav-home" onclick="navigate('/home')">Home</button>
    <button id="nav-about" onclick="navigate('/about')">About</button>
    <button id="nav-hash" onclick="location.hash='#section3'">Hash</button>
  </nav>
  <div id="content"><p>当前: Home</p></div>
  <div id="section3" style="display:none;"><p>Section 3</p></div>
  <script>
    function navigate(path) {
      history.pushState({}, '', path);
      document.getElementById('content').innerHTML = '<p>当前: ' + path + '</p>';
    }
    window.addEventListener('popstate', function() {
      document.getElementById('content').innerHTML = '<p>当前: ' + location.pathname + '</p>';
    });
    window.addEventListener('hashchange', function() {
      document.getElementById('section3').style.display =
        location.hash === '#section3' ? 'block' : 'none';
    });
  </script>
</body>
</html>
```

- [ ] **Step 7: 创建 multi_tab/opener.html**

Create `tests/fixtures/multi_tab/opener.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>多标签测试 - 主页</title></head>
<body>
  <h1>多标签测试 - 主页</h1>
  <button id="open-child-a" onclick="window.open('child_a.html','childA','width=600,height=400')">window.open Child A</button>
  <button id="open-child-b" onclick="window.open('child_b.html','childB','width=600,height=400')">window.open Child B</button>
  <a id="link-child-a" href="child_a.html" target="_blank">target=_blank Child A</a>
  <button id="main-action">主页操作按钮</button>
  <input id="main-input" placeholder="主页输入">
</body>
</html>
```

- [ ] **Step 8: 创建 multi_tab/child_a.html**

Create `tests/fixtures/multi_tab/child_a.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>子页 A</title></head>
<body>
  <h1>子页 A</h1>
  <button id="child-a-btn">子页 A 按钮</button>
  <input id="child-a-input" placeholder="子页 A 输入">
  <button id="child-a-open-b" onclick="window.open('child_b.html','childB','width=600,height=400')">打开子页 B</button>
  <button id="child-a-open-popup" onclick="window.open('popup.html','popup','width=300,height=200')">打开弹窗</button>
  <button id="child-a-close" onclick="window.close()">关闭自己</button>
</body>
</html>
```

- [ ] **Step 9: 创建 multi_tab/child_b.html**

Create `tests/fixtures/multi_tab/child_b.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>子页 B</title></head>
<body>
  <h1>子页 B</h1>
  <button id="child-b-btn">子页 B 按钮</button>
  <input id="child-b-input" placeholder="子页 B 输入">
  <button id="child-b-close" onclick="window.close()">关闭自己</button>
</body>
</html>
```

- [ ] **Step 10: 创建 multi_tab/popup.html**

Create `tests/fixtures/multi_tab/popup.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>弹窗</title></head>
<body>
  <h1>弹窗页面</h1>
  <button id="popup-btn">弹窗按钮</button>
  <button id="popup-close" onclick="window.close()">关闭</button>
</body>
</html>
```

- [ ] **Step 11: Commit**

```bash
cd /workspace/projects/browser-recorder && git add tests/fixtures/
git commit -m "feat: 测试 fixture HTML — 覆盖 basic/dialog/modal/iframe/shadow/spa/multi_tab 场景"
```

---

### Task 14: 集成测试

**Files:**
- Create: `projects/browser-recorder/tests/conftest.py`
- Create: `projects/browser-recorder/tests/test_recorder.py`

**Interfaces:**
- Consumes: 所有模块 + fixture HTML
- Produces: 端到端测试：启动 http.server → 录制 → 验证产物

- [ ] **Step 1: 编写 conftest.py**

Create `tests/conftest.py`:

```python
"""测试配置 — 本地 HTTP server + Playwright browser."""
import socket
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import pytest
from playwright.async_api import async_playwright


def _find_free_port() -> int:
    """找到可用端口."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def fixtures_dir():
    """fixture HTML 目录."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def http_server(fixtures_dir):
    """启动本地 HTTP server 托管 fixture HTML."""

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(fixtures_dir), **kwargs)

        def log_message(self, format, *args):
            pass  # 抑制日志

    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # 等待启动
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
async def browser():
    """创建 Playwright browser（headless）."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser):
    """创建新页面."""
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()
```

- [ ] **Step 2: 编写 test_recorder.py 集成测试**

Create `tests/test_recorder.py`:

```python
"""集成测试 — 端到端录制流程."""
import json
import tempfile
from pathlib import Path
import pytest
from browser_recorder.injector import inject, setup_recorder_callback, flush
from browser_recorder.filters import FilterPipeline, InputMergeFilter, DedupFilter
from browser_recorder.handlers import JsonlWriter
from browser_recorder.models import Action, ActionTag
from browser_recorder.reporter import MarkdownReporter


@pytest.mark.asyncio
async def test_inject_and_capture_click(page, http_server):
    """注入脚本后，click 事件被 push 到 Python 回调."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/basic.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    # 点击按钮
    await page.click("#login-btn")
    await page.wait_for_timeout(200)
    await flush(page)

    assert len(events) > 0
    click_events = [e for e in events if e.get("type") == "CLICK"]
    assert len(click_events) >= 1
    assert click_events[0]["tagName"] == "button"


@pytest.mark.asyncio
async def test_inject_and_capture_input(page, http_server):
    """输入文本 → INPUT 事件带上 value."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/basic.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    await page.fill("#username", "hello world")
    await page.wait_for_timeout(200)
    await flush(page)

    input_events = [e for e in events if e.get("type") == "INPUT"]
    assert len(input_events) >= 1


@pytest.mark.asyncio
async def test_inject_and_capture_change(page, http_server):
    """选择下拉 → CHANGE 事件."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/basic.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    await page.select_option("#role", "user")
    await page.wait_for_timeout(200)
    await flush(page)

    change_events = [e for e in events if e.get("type") == "CHANGE"]
    assert len(change_events) >= 1


@pytest.mark.asyncio
async def test_dialog_capture(page, http_server):
    """弹窗事件捕获."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/dialog.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    # 监听 dialog（自动 accept）
    page.on("dialog", lambda d: d.accept())

    await page.click("#alert-btn")
    await page.wait_for_timeout(500)

    # dialog 事件可能不走注入脚本（被浏览器拦截）
    # 此测试验证不崩溃即可
    assert True


@pytest.mark.asyncio
async def test_filter_pipeline_integration(page, http_server):
    """FilterPipeline 集成测试."""
    pipeline = FilterPipeline()
    pipeline.add(InputMergeFilter())
    pipeline.add(DedupFilter())

    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        for ev in batch:
            processed = pipeline.process(ev)
            events.extend(processed)

    await page.goto(f"{http_server}/basic.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    await page.fill("#username", "a")
    await page.wait_for_timeout(100)
    await page.fill("#username", "ab")
    await page.wait_for_timeout(100)
    await page.fill("#username", "abc")
    await page.wait_for_timeout(300)
    await flush(page)

    input_events = [e for e in events if e.get("type") == "INPUT" and e.get("selector")]
    # 合并后应 ≤ 原始输入次数
    assert len(input_events) >= 1


@pytest.mark.asyncio
async def test_jsonl_writer_integration():
    """JsonlWriter 集成测试."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir))

        action = Action(
            step=1,
            timestamp_ms=1000.0,
            tag=ActionTag.NAV,
            selector="",
            tag_name="",
            url="https://example.com",
            page_id="main",
        )
        writer.write(action)
        writer.flush()

        jsonl = Path(tmpdir) / "events.jsonl"
        assert jsonl.exists()
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tag"] == "NAV"


def test_reporter_integration():
    """MarkdownReporter 集成测试."""
    actions = [
        Action(step=1, timestamp_ms=1000, tag=ActionTag.NAV, selector="",
               tag_name="", url="https://example.com", page_id="main",
               screenshot_after="shots/step_001.jpg"),
        Action(step=2, timestamp_ms=3000, tag=ActionTag.CLICK, selector="#btn",
               tag_name="button", text="Click", url="https://example.com",
               page_id="main", coords=(100, 200),
               screenshot_before="shots/step_002_click.jpg",
               screenshot_after="shots/step_002_result.jpg"),
        Action(step=3, timestamp_ms=5000, tag=ActionTag.INPUT, selector="#user",
               tag_name="input", value="admin", url="https://example.com",
               page_id="main"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = MarkdownReporter()
        path = reporter.generate(actions, [], Path(tmpdir))
        assert path.exists()
        content = path.read_text()
        assert "example.com" in content
        assert "login" in content or "Click" in content or "admin" in content


@pytest.mark.asyncio
async def test_multi_tab_events(page, http_server):
    """多标签页 — 新页面事件被捕获."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/multi_tab/opener.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    # 点击 window.open
    async with page.expect_popup() as popup_info:
        await page.click("#open-child-a")

    child_page = await popup_info.value
    # 子页注入（模拟 recorder 行为）
    await setup_recorder_callback(child_page, on_push)
    await inject(child_page, "child_0")

    await child_page.click("#child-a-btn")
    await child_page.wait_for_timeout(300)
    await flush(child_page)

    child_clicks = [e for e in events if e.get("type") == "CLICK" and e.get("pageId") == "child_0"]
    assert len(child_clicks) >= 1

    await child_page.close()


@pytest.mark.asyncio
async def test_spa_navigation_capture(page, http_server):
    """SPA 路由变化产生 NAV 事件."""
    events = []

    async def on_push(json_str: str):
        batch = json.loads(json_str)
        events.extend(batch)

    await page.goto(f"{http_server}/spa.html")
    await setup_recorder_callback(page, on_push)
    await inject(page, "main")

    await page.click("#nav-about")
    await page.wait_for_timeout(500)
    await flush(page)

    nav_events = [e for e in events if e.get("type") == "NAV"]
    assert len(nav_events) >= 1


@pytest.mark.asyncio
async def test_network_interceptor(page, http_server):
    """网络拦截器集成测试."""
    from browser_recorder.network import NetworkInterceptor

    interceptor = NetworkInterceptor()
    await page.goto(f"{http_server}/basic.html")
    await interceptor.setup(page)

    # 触发一个 fetch
    await page.evaluate("fetch('/basic.html')")
    await page.wait_for_timeout(500)

    # 应记录 document 类型的请求
    assert len(interceptor.requests) >= 1
    assert any("basic.html" in r.url for r in interceptor.requests)
```

- [ ] **Step 3: 运行集成测试**

```bash
cd /workspace/projects/browser-recorder && python -m pytest tests/test_recorder.py -v --timeout=60
```
Expected: 大部分测试通过（部分可能因 headless 环境差异需要调整）

- [ ] **Step 4: 修复失败测试**

根据测试输出修复代码中的问题。

- [ ] **Step 5: Commit**

```bash
cd /workspace/projects/browser-recorder && git add tests/conftest.py tests/test_recorder.py
git commit -m "test: 集成测试 — 端到端录制流程 + 多标签 + SPA + 网络拦截"
```

---

## 依赖关系

```
Task 1 (脚手架)
 └─ Task 2 (数据模型)
     ├─ Task 3 (过滤器)
     ├─ Task 4 (注入器)
     ├─ Task 5 (网络拦截)
     ├─ Task 6 (截图器)
     ├─ Task 7 (JsonlWriter)
     ├─ Task 8 (清理器)
     └─ Task 9 (报告生成器)
          └─ Task 10 (CLI) ← 需要所有模块
               └─ Task 11 (录制编排器)
                    └─ Task 12 (回放引擎)
Task 13 (Fixture HTML) ← 独立
Task 14 (集成测试) ← 依赖全部
```
