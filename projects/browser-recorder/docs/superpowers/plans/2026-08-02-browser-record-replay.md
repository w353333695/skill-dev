# 浏览器操作录制与回放工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现跨平台、平台中性的 Python CLI `browser-recorder`，录制人类浏览器操作 + 网络 + 截图 + 录屏，可回放，并导出 HTML/Markdown 图文报告 + 结构化接口清单。

**Architecture:** Playwright + CDP 驱动录制/回放；录制期只产原始事实（jsonl + 原图 + webm），一切美化/聚合/画标/转码集中在 export。登录态走 Playwright `storage_state` 通用机制，按 registrable domain + host 范围匹配。包 `browser_recorder`，CLI 用 click，测试用 pytest，依赖用 uv 管理。

**Tech Stack:** Python 3.10+, Playwright (Python), CDP, Pillow, imageio-ffmpeg, click, pyyaml, pytest, pytest-asyncio

## Global Constraints

- **平台/系统中性铁律（CLAUDE.md §1）**：`browser_recorder/` 主干代码、注释、变量名、测试 fixture 不得出现任何特定系统名（如 `easyops`）、特定 host/IP/端口、特定路由、特定鉴权细节（AK/SK/cookie 名）。系统对接走外部 adapter，主干不知情。提交前自检：`grep -rin easyops browser_recorder/ tests/`。
- **Python 版本下限**：3.10（计划内可用 `match`、`X | Y` 联合类型注解）。
- **包管理**：uv。`pyproject.toml` + `.venv` 在仓库根。所有命令经 `uv run`。
- **产物落点**：录制过程产物落 `tmp/<session-id>/`；最终产物 + 登录态落默认 `./.browser-recorder/`（`--out-dir` 可改）；导出目录默认 `<session-id>`，可 `--name <易读名>`。
- **截图时机**：录制只存原图 + bbox 元数据；半透明标记统一在导出期用 Pillow 画（RGBA + alpha_composite + 描边优先 + 外置序号）。
- **页面稳定判定**：动态（网络空闲 + DOM 稳定 + 主线程空闲 三信号 + debounce + 超时兜底），毫秒数仅作超时上限；`after_action` 是 settle 上限，`before_action`/`idle_for_visibility` 是固定停顿。
- **响应体处理**：A 解析成字段骨架 + B export 跨次聚合 + C 超阈值(>1MB)原始体落盘引用。
- **接口输出**：结构化请求 JSON 清单，**不生成 OpenAPI**。
- **录屏**：默认 webm（Playwright 原生），可选 mp4（imageio-ffmpeg 跨平台转码）。
- **TDD + 频繁提交**：每个任务先写失败测试 → 跑红 → 最小实现 → 跑绿 → 提交。
- **DRY / YAGNI**：不实现 spec 范围外的东西（不做 OpenAPI、不做全自动登录）。

## File Structure

```
browser_recorder/                    # 主干包（平台中性）
├── __init__.py
├── cli.py                           # click 入口：record/replay/export/auth 子命令装配
├── config.py                        # 配置加载/合并（screenshot_policy、replay_policy、defaults）
├── paths.py                         # 路径解析（out-dir、session-id、export 目录、auth 目录）
├── models.py                        # 数据模型 dataclass：Action、Target、RequestRecord、ResponseInfo
├── settle.py                        # wait_for_settled() 三信号动态判定
├── selectors.py                     # 多维度选择器生成（role→css→xpath→坐标）+ 回退定位
├── response_schema.py               # 响应体解析成字段骨架（A 方案）
├── request_aggregator.py            # export 期跨次聚合 schema（B 方案）
├── auth/
│   ├── __init__.py
│   ├── scope.py                     # registrable domain + host 范围匹配
│   └── store.py                     # storage_state 读写、profile list/show/refresh
├── record/
│   ├── __init__.py
│   ├── injector.py                  # 注入页面的 JS 钩子（事件捕获 + bbox + 选择器计算）
│   ├── capture.py                   # CDP 事件 → Action/RequestRecord 流式写 jsonl
│   ├── screenshot.py                # 截图时机策略（输入聚合、重复滤除、before/after）
│   └── runner.py                    # record 子命令主流程（启浏览器、加载 auth、跑钩子、收事件）
├── replay/
│   ├── __init__.py
│   ├── delays.py                    # 间隔配置解析（pace/delay/policy）
│   ├── executor.py                  # 按 trace 重放动作（选择器回退 + settle + 标记）
│   └── runner.py                    # replay 子命令主流程
├── export/
│   ├── __init__.py
│   ├── annotator.py                 # Pillow 半透明画标（RGBA + alpha_composite + 外置序号）
│   ├── report_html.py               # HTML 报告生成
│   ├── report_md.py                 # Markdown 报告生成
│   ├── fonts.py                     # 随包字体加载（NotoSans 或等价）
│   └── transcode.py                 # webm→mp4（imageio-ffmpeg）
└── video.py                         # 录屏封装（Playwright record_video + 可选转码）

tests/                               # 中性 fixture，无真实系统名
├── conftest.py                      # 共享 fixture（tmp_path、中性 HTML fixture 路径）
├── fixtures/
│   └── demo_site/                   # 中性静态站点（登录页、列表页、表单页）
│       ├── index.html
│       ├── login.html
│       └── list.html
├── test_paths.py
├── test_config.py
├── test_models.py
├── test_settle.py
├── test_selectors.py
├── test_response_schema.py
├── test_request_aggregator.py
├── test_auth_scope.py
├── test_auth_store.py
├── test_screenshot_policy.py
├── test_replay_delays.py
├── test_annotator.py
├── test_report_html.py
├── test_report_md.py
├── test_capture.py
├── test_executor.py
└── test_cli_smoke.py
```

**职责边界说明**：`models.py` 是所有模块共享的单一数据来源；`record/`、`replay/`、`export/` 三个子包互不 import 对方，只通过 jsonl 文件 + models 通信；`auth/` 独立，被 record/replay 复用。这保证每个子包可独立测试。

---

## Task 1: 项目脚手架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `browser_recorder/__init__.py`
- Create: `browser_recorder/cli.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `browser_recorder` 可安装包；CLI 入口 `browser-recorder`；`uv run pytest` 可跑空测试套件。

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "browser-recorder"
version = "0.1.0"
description = "跨平台、平台中性的浏览器操作录制/回放/导出 CLI"
requires-python = ">=3.10"
dependencies = [
    "playwright>=1.44",
    "pillow>=10.0",
    "imageio-ffmpeg>=0.5",
    "click>=8.1",
    "pyyaml>=6.0",
]

[project.scripts]
browser-recorder = "browser_recorder.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["browser_recorder"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

- [ ] **Step 2: 写包 `__init__.py`**

```python
# browser_recorder/__init__.py
"""跨平台、平台中性的浏览器操作录制/回放/导出工具。"""
__version__ = "0.1.0"
```

- [ ] **Step 3: 写最小 CLI（只有顶层命令骨架，子命令后续任务填）**

```python
# browser_recorder/cli.py
"""click CLI 入口。子命令在各任务中逐步装配。"""
import click


@click.group()
def main() -> None:
    """浏览器操作录制 / 回放 / 导出 / 登录态管理。"""


@main.command()
def version() -> None:
    """显示版本。"""
    from . import __version__
    click.echo(__version__)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 写 `tests/__init__.py`（空）和 `tests/conftest.py`**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
import pytest


@pytest.fixture
def tmp_out_dir(tmp_path):
    """默认 out-dir 根目录（隔离测试，不污染真实 ./.browser-recorder）。"""
    d = tmp_path / ".browser-recorder"
    d.mkdir()
    return d
```

- [ ] **Step 5: 安装依赖 + 安装 Playwright 浏览器**

Run: `uv sync && uv run playwright install chromium`
Expected: 依赖安装成功，Chromium 下载完成。

- [ ] **Step 6: 验证 CLI 与 pytest 可用（验收测试）**

Run: `uv run browser-recorder version`
Expected: 输出 `0.1.0`

Run: `uv run pytest -q`
Expected: `no tests ran`（还没有测试文件，0 失败）。

- [ ] **Step 7: 平台中性自检 + 提交**

Run: `grep -rin easyops browser_recorder/ tests/ || echo "clean"`
Expected: `clean`

```bash
git add pyproject.toml browser_recorder/ tests/
git commit -m "feat: 项目脚手架（pyproject + click CLI 骨架 + pytest 配置）"
```

---

## Task 2: 数据模型（models.py）

**Files:**
- Create: `browser_recorder/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Target`、`Action`、`ResponseInfo`、`RequestRecord` dataclass，带 `to_dict()` / `from_dict()`（用于 jsonl 序列化）。后续所有任务通过这些类型通信。

- [ ] **Step 1: 写失败测试 `tests/test_models.py`**

```python
# tests/test_models.py
from browser_recorder.models import Target, Action, RequestRecord, ResponseInfo


def test_target_roundtrip():
    t = Target(
        role_selector="button[name='提交']",
        css="button.submit",
        xpath="//button[@class='submit']",
        text="提交",
        bbox={"x": 10, "y": 20, "w": 80, "h": 30},
        tag="button",
        role="button",
        name="提交",
    )
    d = t.to_dict()
    t2 = Target.from_dict(d)
    assert t2 == t
    assert t2.bbox == {"x": 10, "y": 20, "w": 80, "h": 30}


def test_action_roundtrip_with_all_fields():
    a = Action(
        seq=3,
        ts=1719000000000,
        type="click",
        target=Target(css="a#next", bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
        value=None,
        url="https://example.com/list",
        page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 100},
        screenshot={"before": "step-0003-before.png", "after": "step-0003-after.png"},
        settled_by="network_dom_cpu",
    )
    d = a.to_dict()
    a2 = Action.from_dict(d)
    assert a2 == a
    assert a2.target.css == "a#next"


def test_action_optional_fields_none():
    a = Action(seq=1, ts=0, type="navigation", target=None, url="https://x")
    d = a.to_dict()
    a2 = Action.from_dict(d)
    assert a2.target is None
    assert a2.value is None
    assert a2.screenshot is None


def test_request_record_with_response_info():
    r = RequestRecord(
        req_id="ABC",
        ts=100,
        method="GET",
        url="https://example.com/api/x",
        headers={"Accept": "application/json"},
        post_data=None,
        status=200,
        response_headers={"Content-Type": "application/json"},
        mime="application/json",
        response=ResponseInfo(raw_size=10, schema={"type": "object"}),
        duration_ms=5,
        linked_action_seq=2,
    )
    d = r.to_dict()
    r2 = RequestRecord.from_dict(d)
    assert r2 == r
    assert r2.response.schema["type"] == "object"
    assert r2.response.raw_ref is None


def test_response_info_with_raw_ref():
    ri = ResponseInfo(raw_size=2_000_000, raw_ref="responses/ABC.bin", raw_sha256="deadbeef", schema=None)
    d = ri.to_dict()
    ri2 = ResponseInfo.from_dict(d)
    assert ri2.raw_ref == "responses/ABC.bin"
    assert ri2.schema is None
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'browser_recorder.models'`

- [ ] **Step 3: 写 `browser_recorder/models.py`**

```python
# browser_recorder/models.py
"""数据模型：所有模块共享的单一数据来源。

通过 to_dict / from_dict 实现 jsonl 序列化。字段命名与 spec §5.1 / §6.1 对齐。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
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
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/models.py tests/test_models.py
git commit -m "feat(models): Action/Target/RequestRecord/ResponseInfo 数据模型 + jsonl 序列化"
```

---

## Task 3: 路径解析（paths.py）

**Files:**
- Create: `browser_recorder/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `paths.resolve_out_dir(out_dir: str | None) -> Path`（默认 `.browser-recorder`）
  - `paths.session_dir(session_id: str) -> Path`（过程产物，`tmp/<session_id>/`）
  - `paths.export_dir(out_dir: Path, name: str) -> Path`（最终产物）
  - `paths.auth_dir(out_dir: Path) -> Path`、`paths.profile_dir(out_dir: Path, profile: str) -> Path`
  - `paths.new_session_id() -> str`（时间戳 + 短随机，如 `20260802-153012-a1b2`）

- [ ] **Step 1: 写失败测试 `tests/test_paths.py`**

```python
# tests/test_paths.py
import re
from pathlib import Path
from browser_recorder import paths


def test_resolve_out_dir_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = paths.resolve_out_dir(None)
    assert d == tmp_path / ".browser-recorder"


def test_resolve_out_dir_custom(tmp_path):
    d = paths.resolve_out_dir(str(tmp_path / "custom"))
    assert d == tmp_path / "custom"


def test_session_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TMP_ROOT", tmp_path / "tmp")
    d = paths.session_dir("20260802-153012-a1b2")
    assert d == tmp_path / "tmp" / "20260802-153012-a1b2"


def test_export_dir_under_out_dir(tmp_out_dir):
    d = paths.export_dir(tmp_out_dir, "my-rec")
    assert d == tmp_out_dir / "exports" / "my-rec"


def test_auth_dirs(tmp_out_dir):
    assert paths.auth_dir(tmp_out_dir) == tmp_out_dir / "auth"
    assert paths.profile_dir(tmp_out_dir, "demo") == tmp_out_dir / "auth" / "demo"


def test_new_session_id_format():
    sid = paths.new_session_id()
    assert re.fullmatch(r"\d{8}-\d{6}-[a-z0-9]{4}", sid), sid


def test_new_session_id_unique():
    ids = {paths.new_session_id() for _ in range(50)}
    assert len(ids) == 50
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/paths.py`**

```python
# browser_recorder/paths.py
"""路径解析：统一约定过程产物、最终产物、登录态的落点。"""
from __future__ import annotations
import secrets
import time
from pathlib import Path

# 过程产物根（可被测试 monkeypatch）。CLAUDE.md 约定产物落 tmp/。
TMP_ROOT = Path("tmp")

DEFAULT_OUT_DIR_NAME = ".browser-recorder"


def resolve_out_dir(out_dir: str | None) -> Path:
    """默认 ./.browser-recorder，可被 --out-dir 覆盖。"""
    return Path(out_dir) if out_dir else Path.cwd() / DEFAULT_OUT_DIR_NAME


def session_dir(session_id: str) -> Path:
    """录制过程产物目录。"""
    return TMP_ROOT / session_id


def export_dir(out_dir: Path, name: str) -> Path:
    """最终产物目录。"""
    return out_dir / "exports" / name


def auth_dir(out_dir: Path) -> Path:
    return out_dir / "auth"


def profile_dir(out_dir: Path, profile: str) -> Path:
    return auth_dir(out_dir) / profile


def new_session_id() -> str:
    """时间戳 + 4 位随机，提高可读性同时避免并发碰撞。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(2)  # 4 个十六进制字符
    return f"{ts}-{suffix}"
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_paths.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/paths.py tests/test_paths.py
git commit -m "feat(paths): 统一的过程产物/最终产物/登录态路径解析"
```

---

## Task 4: 配置加载（config.py）

**Files:**
- Create: `browser_recorder/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `config.ScreenshotPolicy` dataclass：`points: dict[str, list[str]]`（动作类型 → `["before"]`/`["after"]`/`["before","after"]`/`[]`）、`dedup_window_ms: int`、`input_aggregate_timeout_ms: int`
  - `config.ReplayPolicy` dataclass：`after_action: dict[str, int]`（type→ms 上限，`"default"` 兜底）、`before_action: dict[str, int]`、`idle_for_visibility: int`、`settle_debounce_ms: int`、`settle_timeout_ms: int`
  - `DEFAULT_SCREENSHOT_POLICY`、`DEFAULT_REPLAY_POLICY`（模块常量）
  - `config.load_screenshot_policy(path: Path | None) -> ScreenshotPolicy`（None 返回默认；yaml 覆盖默认）
  - `config.load_replay_policy(path: Path | None, pace: str | None, overrides: list[str] | None) -> ReplayPolicy`（合并 yaml + pace 缩放 + `type.scope=ms` 细粒度覆盖）

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
# tests/test_config.py
from pathlib import Path
from browser_recorder import config


def test_default_screenshot_policy_points():
    p = config.DEFAULT_SCREENSHOT_POLICY
    assert set(p.points["click"]) == {"before", "after"}
    assert p.points["input"] == ["after"]
    assert p.points["scroll"] == []
    assert p.points["navigation"] == ["after"]
    assert p.points["hover"] == ["before"]


def test_load_screenshot_policy_none_returns_default():
    assert config.load_screenshot_policy(None) == config.DEFAULT_SCREENSHOT_POLICY


def test_load_screenshot_policy_yaml_override(tmp_path):
    yml = tmp_path / "p.yaml"
    yml.write_text(
        "points:\n  click: [after]\n  input: [after]\n  scroll: []\n  navigation: [after]\n  hover: [before]\n"
        "  submit: [before, after]\n  keypress: [after]\n  select: [after]\n"
        "dedup_window_ms: 300\n"
        "input_aggregate_timeout_ms: 1200\n",
        encoding="utf-8",
    )
    p = config.load_screenshot_policy(yml)
    assert p.points["click"] == ["after"]
    assert p.dedup_window_ms == 300


def test_default_replay_policy():
    r = config.DEFAULT_REPLAY_POLICY
    assert r.after_action["default"] == 5000
    assert r.after_action["submit"] == 15000
    assert r.before_action["default"] == 500
    assert r.idle_for_visibility == 600
    assert r.settle_debounce_ms == 300


def test_replay_policy_pace_slow_doubles():
    r = config.load_replay_policy(None, pace="slow", overrides=None)
    assert r.before_action["default"] == 1000  # 500 * 2
    assert r.idle_for_visibility == 1200


def test_replay_policy_pace_faithful_keeps_values():
    r = config.load_replay_policy(None, pace="faithful", overrides=None)
    # faithful 不缩放固定停顿（仅 replay runner 用真实 ts）
    assert r.before_action["default"] == 500


def test_replay_policy_delay_override():
    r = config.load_replay_policy(None, pace=None, overrides=["click.before=200", "input.after=500"])
    assert r.before_action["click"] == 200
    assert r.after_action["input"] == 500
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/config.py`**

```python
# browser_recorder/config.py
"""配置：截图时机策略、回放间隔策略。

策略对象是纯数据，方便单测；加载函数负责合并默认值 + yaml + CLI 覆盖。
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path
import yaml


@dataclass
class ScreenshotPolicy:
    points: dict[str, list[str]]      # 动作类型 -> ["before"]/["after"]/["before","after"]/[]
    dedup_window_ms: int = 500
    input_aggregate_timeout_ms: int = 1500


@dataclass
class ReplayPolicy:
    after_action: dict[str, int]      # type -> ms（settle 上限）；含 "default"
    before_action: dict[str, int]     # type -> ms（固定停顿）；含 "default"
    idle_for_visibility: int = 600
    settle_debounce_ms: int = 300


DEFAULT_SCREENSHOT_POLICY = ScreenshotPolicy(
    points={
        "click": ["before", "after"],
        "submit": ["before", "after"],
        "input": ["after"],
        "select": ["after"],
        "keypress": ["after"],
        "scroll": [],
        "navigation": ["after"],
        "hover": ["before"],
    },
)

DEFAULT_REPLAY_POLICY = ReplayPolicy(
    after_action={"default": 5000, "click": 5000, "submit": 15000, "navigation": 10000},
    before_action={"default": 500, "click": 300, "input": 200, "submit": 1000},
    idle_for_visibility=600,
    settle_debounce_ms=300,
)


def load_screenshot_policy(path: Path | None) -> ScreenshotPolicy:
    if path is None:
        return DEFAULT_SCREENSHOT_POLICY
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    points = {**DEFAULT_SCREENSHOT_POLICY.points, **(data.get("points") or {})}
    return ScreenshotPolicy(
        points=points,
        dedup_window_ms=data.get("dedup_window_ms", DEFAULT_SCREENSHOT_POLICY.dedup_window_ms),
        input_aggregate_timeout_ms=data.get(
            "input_aggregate_timeout_ms", DEFAULT_SCREENSHOT_POLICY.input_aggregate_timeout_ms),
    )


# 固定停顿字段（会被 pace 缩放）；after_action 是 settle 上限，不缩放
_FIXED_DELAY_TOPS = {"before_action", "idle_for_visibility"}


def _scale_fixed(policy: ReplayPolicy, factor: float) -> ReplayPolicy:
    return ReplayPolicy(
        after_action=policy.after_action,  # 不缩放
        before_action={k: int(v * factor) for k, v in policy.before_action.items()},
        idle_for_visibility=int(policy.idle_for_visibility * factor),
        settle_debounce_ms=policy.settle_debounce_ms,
    )


def _parse_ms(s: str) -> int:
    s = s.strip()
    for suffix, mult in [("ms", 1), ("s", 1000)]:
        if s.endswith(suffix):
            return int(float(s[: -len(suffix)]) * mult)
    return int(s)


def load_replay_policy(
    path: Path | None, pace: str | None, overrides: list[str] | None
) -> ReplayPolicy:
    base = DEFAULT_REPLAY_POLICY
    if path is not None:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        delays = data.get("delays") or {}
        base = ReplayPolicy(
            after_action={**DEFAULT_REPLAY_POLICY.after_action,
                          **{k: _parse_ms(str(v)) for k, v in (delays.get("after_action") or {}).items()}
                          } if isinstance(delays.get("after_action"), dict) else DEFAULT_REPLAY_POLICY.after_action,
            before_action={**DEFAULT_REPLAY_POLICY.before_action,
                           **{k: _parse_ms(str(v)) for k, v in (delays.get("before_action") or {}).items()}
                           } if isinstance(delays.get("before_action"), dict) else DEFAULT_REPLAY_POLICY.before_action,
            idle_for_visibility=_parse_ms(str(delays.get("idle_for_visibility", base.idle_for_visibility))),
            settle_debounce_ms=int(data.get("settle_debounce_ms", base.settle_debounce_ms)),
        )

    if pace == "slow":
        base = _scale_fixed(base, 2.0)
    # faithful / human 不缩放固定停顿；faithful 的真实间隔在 runner 里按 trace ts 处理

    if overrides:
        for ov in overrides:
            key, val = ov.split("=", 1)
            ftype, scope = key.split(".", 1)  # e.g. click.before / input.after
            if scope == "before":
                base.before_action[ftype] = _parse_ms(val)
            elif scope == "after":
                base.after_action[ftype] = _parse_ms(val)
            elif scope == "idle":
                base.idle_for_visibility = _parse_ms(val)
            else:
                raise ValueError(f"未知 delay scope: {scope}")
    return base
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/config.py tests/test_config.py
git commit -m "feat(config): 截图时机策略 + 回放间隔策略（默认值/yaml/pace/细粒度覆盖）"
```

---

## Task 5: 多维度选择器生成（selectors.py）

**Files:**
- Create: `browser_recorder/selectors.py`
- Test: `tests/test_selectors.py`

**Interfaces:**
- Produces:
  - `selectors.build_target_from_dom(node_info: dict) -> Target`：从注入钩子回传的 DOM 节点信息（tag/role/name/text/css/xpath/bbox）构造 `Target`。
  - `selectors.locate(page, target: Target) -> Locator | None`：按 role→css→xpath→坐标 优先级回退，返回 Playwright Locator 或 None（全失败）。
  - `selectors.target_fingerprint(target: Target) -> str`：去重用的元素指纹。

**说明**：`build_target_from_dom` 的输入是注入 JS 回传的纯字典（见 Task 11 `injector.py`），不依赖 Playwright 对象，便于单测。`locate` 需要真实 `page`，集成测试在 Task 14 覆盖；本任务只单测纯函数。

- [ ] **Step 1: 写失败测试 `tests/test_selectors.py`**

```python
# tests/test_selectors.py
from browser_recorder.selectors import build_target_from_dom, target_fingerprint
from browser_recorder.models import Target


def test_build_target_from_dom_full():
    node = {
        "tag": "button",
        "role": "button",
        "name": "提交",
        "text": "提交",
        "css": "button.submit",
        "xpath": "//button[@class='submit']",
        "role_selector": "button[name='提交']",
        "bbox": {"x": 10, "y": 20, "w": 80, "h": 30},
    }
    t = build_target_from_dom(node)
    assert t.tag == "button"
    assert t.role == "button"
    assert t.name == "提交"
    assert t.css == "button.submit"
    assert t.bbox == {"x": 10, "y": 20, "w": 80, "h": 30}
    assert t.role_selector == "button[name='提交']"


def test_build_target_from_dom_partial():
    node = {"tag": "a", "css": "a#next", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    t = build_target_from_dom(node)
    assert t.css == "a#next"
    assert t.role is None
    assert t.xpath is None


def test_target_fingerprint_stable_across_bbox_change():
    """指纹应忽略 bbox（位置变不代表是不同元素）。"""
    t1 = Target(css="a#next", text="下一页", bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    t2 = Target(css="a#next", text="下一页", bbox={"x": 5, "y": 5, "w": 1, "h": 1})
    assert target_fingerprint(t1) == target_fingerprint(t2)


def test_target_fingerprint_differs_by_css():
    t1 = Target(css="a#next")
    t2 = Target(css="a#prev")
    assert target_fingerprint(t1) != target_fingerprint(t2)


def test_target_fingerprint_falls_back_to_xpath_then_text():
    t1 = Target(xpath="//div[@id='x']")
    t2 = Target(xpath="//div[@id='x']")
    assert target_fingerprint(t1) == target_fingerprint(t2)
    # 无 css/xpath 时用 tag+text
    t3 = Target(tag="button", text="ok")
    t4 = Target(tag="button", text="ok")
    assert target_fingerprint(t3) == target_fingerprint(t4)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_selectors.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/selectors.py`**

```python
# browser_recorder/selectors.py
"""多维度选择器：从 DOM 节点信息构造 Target、计算去重指纹、回退定位。

回退定位 locate() 依赖 Playwright page，集成测试覆盖；本模块单测聚焦纯函数。
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from .models import Target

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


def build_target_from_dom(node_info: dict[str, Any]) -> Target:
    """注入钩子回传的 DOM 节点字典 → Target。"""
    return Target(
        role_selector=node_info.get("role_selector"),
        css=node_info.get("css"),
        xpath=node_info.get("xpath"),
        text=node_info.get("text"),
        bbox=node_info.get("bbox"),
        tag=node_info.get("tag"),
        role=node_info.get("role"),
        name=node_info.get("name"),
    )


def target_fingerprint(target: Target) -> str:
    """去重指纹：忽略 bbox（位置变化不代表新元素）。优先 css，回退 xpath，再回退 tag+text。"""
    if target.css:
        return f"css:{target.css}"
    if target.xpath:
        return f"xpath:{target.xpath}"
    return f"tag:{target.tag or ''}|text:{target.text or ''}"


async def locate(page: "Page", target: Target) -> "Locator | None":
    """按 role→css→xpath 优先级回退定位。全失败返回 None。"""
    candidates: list[str] = []
    if target.role_selector:
        candidates.append(target.role_selector)
    if target.css:
        candidates.append(target.css)
    if target.xpath:
        candidates.append(target.xpath)
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="visible", timeout=1000)
            return loc
        except Exception:
            continue
    # 坐标兜底不在此返回伪定位器；executor 用 page.mouse.click(x,y) 处理
    return None
```

注：坐标回退由 Task 18 `executor.py` 实现——当 `locate()` 返回 None 且 `target.bbox` 存在时，executor 用 `page.mouse.click(bbox 中心)` 兜底点击。本函数只负责 role/css/xpath 三种语义定位。

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_selectors.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/selectors.py tests/test_selectors.py
git commit -m "feat(selectors): 多维度选择器构造 + 去重指纹 + 回退定位骨架"
```

---

## Task 6: 响应体解析成字段骨架（response_schema.py，A 方案）

**Files:**
- Create: `browser_recorder/response_schema.py`
- Test: `tests/test_response_schema.py`

**Interfaces:**
- Produces:
  - `response_schema.parse(body: bytes, mime: str, *, inline_max: int = 262144, raw_threshold: int = 1048576) -> ResponseInfo`
  - 内部：`_parse_json(obj) -> dict`、`_sample(value) -> dict`、`_sha256(data: bytes) -> str`
  - 行为：JSON → 完整字段树 + 每字段类型 + 示例值（>inline_max 的字符串截断并标 `full_in_raw`）；form-urlencoded/multipart → 字段名+类型；html/xml → 结构占位；二进制 → `{mime,size,sha256}`；其他文本 → 前缀+sha256；超 raw_threshold 的原始体由调用方落盘（本函数返回 `raw_ref=None`，调用方根据 `raw_size` 决定落盘并填 `raw_ref`）。

- [ ] **Step 1: 写失败测试 `tests/test_response_schema.py`**

```python
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
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_response_schema.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/response_schema.py`**

```python
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
        schema = {"type": "text", "prefix": prefix}

    return ResponseInfo(raw_size=raw_size, raw_ref=None, raw_sha256=sha, schema=schema)
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_response_schema.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/response_schema.py tests/test_response_schema.py
git commit -m "feat(response): 按 MIME 解析响应体为字段骨架（A 方案，结构不丢）"
```

---

## Task 7: 请求跨次聚合 schema（request_aggregator.py，B 方案）

**Files:**
- Create: `browser_recorder/request_aggregator.py`
- Test: `tests/test_request_aggregator.py`

**Interfaces:**
- Consumes: `models.RequestRecord`（从 requests.jsonl 读入）
- Produces:
  - `aggregator.url_template(url: str) -> tuple[str, list[str]]`：(归一化 url，path 参数名列表)。把 `/users/1001` → `/users/{id}`，`?page=2&q=x` → 路径参数化、query 参数提取。
  - `aggregator.merge_field_schemas(schemas: list[dict]) -> dict`：合并多次同名字段，标注 `always_present`/`present_in`/`absent_in`，数组元素跨次合并，数值 min/max 采样。
  - `aggregator.aggregate(records: list[RequestRecord]) -> list[dict]`：按 (method, url_template) 分组，输出 spec §6.3 的聚合结构。

- [ ] **Step 1: 写失败测试 `tests/test_request_aggregator.py`**

```python
# tests/test_request_aggregator.py
from browser_recorder.request_aggregator import url_template, merge_field_schemas, aggregate
from browser_recorder.models import RequestRecord, ResponseInfo


def test_url_template_path_param():
    tmpl, params = url_template("https://api.example.com/users/1001")
    assert tmpl == "https://api.example.com/users/{id}"
    assert params == ["id"]


def test_url_template_uuid_not_param():
    # 纯数字段才当 id；uuid 不应误判
    tmpl, _ = url_template("https://api.example.com/u/abc-123-xyz")
    assert tmpl == "https://api.example.com/u/abc-123-xyz"


def test_url_template_query_kept_as_template():
    tmpl, params = url_template("https://api.example.com/list?page=2&q=hello")
    assert "page" in params and "q" in params
    assert "{" in tmpl  # 参数化进模板


def test_merge_fields_always_present():
    s1 = {"fields": {"id": {"type": "integer", "sample": 1}, "name": {"type": "string", "sample": "a"}}}
    s2 = {"fields": {"id": {"type": "integer", "sample": 2}, "name": {"type": "string", "sample": "b"}}}
    merged = merge_field_schemas([s1, s2])
    assert merged["fields"]["id"]["always_present"] is True
    assert merged["fields"]["id"]["samples"] == [1, 2]


def test_merge_fields_not_always_present():
    s1 = {"fields": {"a": {"type": "string"}, "email": {"type": "string"}}}
    s2 = {"fields": {"a": {"type": "string"}}}  # email 缺失
    merged = merge_field_schemas([s1, s2])
    assert merged["fields"]["email"]["always_present"] is False
    assert merged["fields"]["email"]["present_in"] == 1
    assert merged["fields"]["email"]["absent_in"] == 1


def test_merge_array_items_union():
    s1 = {"fields": {"list": {"type": "array", "items": {"type": "object", "fields": {"x": {"type": "integer"}}}}}}
    s2 = {"fields": {"list": {"type": "array", "items": {"type": "object", "fields": {"x": {"type": "integer"}, "y": {"type": "string"}}}}}}
    merged = merge_field_schemas([s1, s2])
    items_fields = merged["fields"]["list"]["items"]["fields"]
    assert set(items_fields) == {"x", "y"}


def test_aggregate_groups_by_endpoint():
    def rec(path, fields):
        return RequestRecord(
            req_id=path, ts=0, method="GET", url=f"https://api.example.com{path}",
            headers={}, status=200, response_headers={}, mime="application/json",
            response=ResponseInfo(schema={"type": "object", "fields": fields}),
        )
    recs = [
        rec("/users/1", {"id": {"type": "integer"}, "name": {"type": "string"}}),
        rec("/users/2", {"id": {"type": "integer"}}),  # name 缺失
        rec("/posts/9", {"title": {"type": "string"}}),
    ]
    out = aggregate(recs)
    by_ep = {o["endpoint"]["url_template"]: o for o in out}
    users = by_ep["https://api.example.com/users/{id}"]
    assert users["observations"] == 2
    assert users["endpoint"]["param_path"] == ["id"]
    assert users["merged_schema"]["fields"]["name"]["always_present"] is False
    posts = by_ep["https://api.example.com/posts/{id}"]
    assert posts["observations"] == 1
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_request_aggregator.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/request_aggregator.py`**

```python
# browser_recorder/request_aggregator.py
"""请求跨次聚合（B 方案）：按 (method, url_template) 分组合并字段 schema。

标注 always_present / present_in / absent_in；数组元素跨次取并集；数值采样。
"""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
from .models import RequestRecord

_PATH_NUM = re.compile(r"(?<=/)\d+(?=/|$|\?)")


def url_template(url: str) -> tuple[str, list[str]]:
    """把数字路径段参数化为 {id}，提取 query 参数名。"""
    params: list[str] = []
    # 分离 query
    if "?" in url:
        base, query = url.split("?", 1)
        from urllib.parse import parse_qs
        qparams = list(parse_qs(query).keys())
        params.extend(qparams)
    else:
        base = url
    # 数字路径段 → {id}
    def _sub(m: re.Match) -> str:
        params.append("id")
        return "{id}"
    tmpl = _PATH_NUM.sub(_sub, base)
    return tmpl, params


def _merge_value_schemas(items: list[dict[str, Any]]) -> dict[str, Any]:
    """合并同一字段的多次 schema。"""
    types = {it.get("type") for it in items if it.get("type")}
    # 数组：合并 items.fields
    if "array" in types:
        item_field_lists = []
        for it in items:
            flds = (it.get("items") or {}).get("fields")
            if flds:
                item_field_lists.append(flds)
        merged_items = {"type": "object", "fields": _merge_field_dicts(item_field_lists)} if item_field_lists else {"type": "unknown"}
        return {"type": "array", "items": merged_items}
    # object：合并 fields
    if "object" in types:
        fld_lists = [it.get("fields", {}) for it in items if it.get("fields")]
        return {"type": "object", "fields": _merge_field_dicts(fld_lists)}
    # 标量：采样
    samples = [it.get("sample") for it in items if "sample" in it]
    out: dict[str, Any] = {"type": sorted(types)[0] if types else "unknown"}
    if samples:
        out["samples"] = samples
        nums = [s for s in samples if isinstance(s, (int, float)) and not isinstance(s, bool)]
        if nums and len(nums) == len(samples):
            out["min"] = min(nums)
            out["max"] = max(nums)
    return out


def _merge_field_dicts(field_dicts: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多个 fields 字典，按字段名聚合，统计出现次数。"""
    total = len(field_dicts)
    names: dict[str, list[dict[str, Any]]] = defaultdict(list)
    present_count: dict[str, int] = defaultdict(int)
    for fd in field_dicts:
        for k, v in fd.items():
            names[k].append(v)
            present_count[k] += 1
    merged: dict[str, Any] = {}
    for k, vs in names.items():
        m = _merge_value_schemas(vs)
        if present_count[k] == total:
            m["always_present"] = True
        else:
            m["always_present"] = False
            m["present_in"] = present_count[k]
            m["absent_in"] = total - present_count[k]
        merged[k] = m
    return merged


def merge_field_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """顶层合并（schemas 是 response.schema 列表，含 type/fields）。"""
    obj_schemas = [s for s in schemas if s and s.get("type") in ("object",)]
    if not obj_schemas:
        return {"type": schemas[0].get("type") if schemas else "unknown"}
    merged = _merge_field_dicts([s.get("fields", {}) for s in obj_schemas])
    return {"type": "object", "fields": merged}


def aggregate(records: list[RequestRecord]) -> list[dict[str, Any]]:
    """按 (method, url_template) 聚合，输出 spec §6.3 结构。"""
    groups: dict[tuple[str, str], list[RequestRecord]] = defaultdict(list)
    templates: dict[tuple[str, str], list[str]] = {}
    for r in records:
        tmpl, params = url_template(r.url)
        key = (r.method, tmpl)
        groups[key].append(r)
        templates[key] = params
    out: list[dict[str, Any]] = []
    for (method, tmpl), recs in groups.items():
        schemas = [r.response.schema for r in recs if r.response and r.response.schema]
        merged = merge_field_schemas(schemas) if schemas else {"type": "unknown"}
        out.append({
            "endpoint": {"method": method, "url_template": tmpl, "param_path": templates[(method, tmpl)]},
            "observations": len(recs),
            "merged_schema": merged,
            "sample_statuses": sorted({r.status for r in recs}),
        })
    return out
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_request_aggregator.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/request_aggregator.py tests/test_request_aggregator.py
git commit -m "feat(aggregate): 请求跨次聚合 schema（B 方案，字段合并+出现统计）"
```

---

## Task 8: 登录态 scope 匹配（auth/scope.py）

**Files:**
- Create: `browser_recorder/auth/__init__.py`
- Create: `browser_recorder/auth/scope.py`
- Test: `tests/test_auth_scope.py`

**Interfaces:**
- Produces:
  - `scope.registrable_domain(host: str) -> str`：公共后缀 +1（用简化算法：最后两段，已知特殊后缀如 `.co.uk` 取三段）。
  - `scope.parse_url(url: str) -> ParsedUrl`（scheme/host/port/path）。
  - `scope.matches(target_url: str, scope: dict) -> bool`：按 registrable domain + host 后缀匹配；端口变化不影响；协议默认要求 https 可配；路径前缀可选收窄。

- [ ] **Step 1: 写失败测试 `tests/test_auth_scope.py`**

```python
# tests/test_auth_scope.py
from browser_recorder.auth import scope


def test_registrable_domain_simple():
    assert scope.registrable_domain("app.example.com") == "example.com"
    assert scope.registrable_domain("example.com") == "example.com"


def test_registrable_domain_multi_suffix():
    assert scope.registrable_domain("site.co.uk") == "co.uk" or scope.registrable_domain("site.co.uk") == "site.co.uk"
    # 简化算法接受二选一；关键是不把 site.co.uk 当成 site


def test_matches_port_change_does_not_affect():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"], "ports": [443, 8443, None]}
    assert scope.matches("https://example.com/login", s)
    assert scope.matches("https://example.com:8443/login", s)


def test_matches_subdomain():
    s = {"registrable_domain": "example.com",
         "hosts": ["example.com", "app.example.com", "console.example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert scope.matches("https://app.example.com/x", s)
    assert scope.matches("https://console.example.com/x", s)


def test_matches_different_registrable_domain_rejected():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert not scope.matches("https://other.com/x", s)


def test_matches_scheme_http_rejected_by_default():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert not scope.matches("http://example.com/x", s)


def test_matches_scheme_http_allowed_when_configured():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["http", "https"]}
    assert scope.matches("http://example.com/x", s)


def test_matches_path_prefix_narrows():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"], "path_prefix": ["/admin"]}
    assert scope.matches("https://example.com/admin/users", s)
    assert not scope.matches("https://example.com/public", s)


def test_host_match_exact():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "exact", "scheme": ["https"]}
    assert scope.matches("https://example.com/x", s)
    assert not scope.matches("https://app.example.com/x", s)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_auth_scope.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/auth/__init__.py`（空）和 `scope.py`**

```python
# browser_recorder/auth/__init__.py
```

```python
# browser_recorder/auth/scope.py
"""登录态 scope 匹配：按 registrable domain + host 范围匹配，端口/子域/路径变化可容。"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse

# 已知多段公共后缀（简化表；生产可换 tldextract）
_MULTI_SUFFIXES = {
    "co.uk", "ac.uk", "gov.uk", "com.cn", "net.cn", "org.cn", "com.au", "co.jp",
}


@dataclass
class ParsedUrl:
    scheme: str
    host: str
    port: int | None
    path: str


def parse_url(url: str) -> ParsedUrl:
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port
    return ParsedUrl(scheme=p.scheme or "", host=host, port=port, path=p.path or "/")


def registrable_domain(host: str) -> str:
    """公共后缀 +1。已知多段后缀取三段，否则取两段。"""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last2 = ".".join(parts[-2:])
    if last2 in _MULTI_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last2


def matches(target_url: str, scope_dict: dict) -> bool:
    """判断 target_url 是否落在 profile 的 scope 内。"""
    u = parse_url(target_url)

    # 协议
    allowed_schemes = scope_dict.get("scheme") or ["https"]
    if u.scheme not in allowed_schemes:
        return False

    # host 匹配
    host_match = scope_dict.get("host_match", "suffix")
    hosts = scope_dict.get("hosts") or []
    if host_match == "exact":
        host_ok = u.host in hosts
    else:  # suffix：同 registrable domain 或精确后缀命中
        reg = scope_dict.get("registrable_domain")
        if reg:
            host_ok = registrable_domain(u.host) == reg or any(
                u.host == h or u.host.endswith("." + h) for h in hosts)
        else:
            host_ok = any(u.host == h or u.host.endswith("." + h) for h in hosts)
    if not host_ok:
        return False

    # 端口：cookie 不区分端口 → 不作为强约束（ports 字段仅记录，不影响匹配）

    # 路径前缀：可选收窄
    prefixes = scope_dict.get("path_prefix")
    if prefixes:
        if not any(u.path == p or u.path.startswith(p.rstrip("/") + "/") or u.path == p.rstrip("/")
                   for p in prefixes):
            return False
    return True
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_auth_scope.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/auth/ tests/test_auth_scope.py
git commit -m "feat(auth): 登录态 scope 匹配（registrable domain + host 范围，端口/子域/路径容变）"
```

---

## Task 9: 登录态存储与引用（auth/store.py）

**Files:**
- Create: `browser_recorder/auth/store.py`
- Test: `tests/test_auth_store.py`

**Interfaces:**
- Consumes: `auth.scope.matches`、`paths.profile_dir`、`paths.auth_dir`
- Produces:
  - `store.AuthMeta` dataclass：`name, created_at, expires_in_days, scope, storage_state`
  - `store.load_profile(out_dir: Path, name: str) -> tuple[AuthMeta, dict] | None`：读 meta.json + storage_state.json
  - `store.is_expired(meta: AuthMeta, now_ts: float) -> bool`
  - `store.find_matching(out_dir: Path, target_url: str, *, now_ts: float) -> str | None`：扫描 auth/，按 scope 匹配，取最新未过期；返回 profile 名或 None
  - `store.save_profile(out_dir: Path, name: str, storage_state: dict, scope: dict, expires_in_days: int, *, now_ts: float) -> AuthMeta`
  - `store.list_profiles(out_dir: Path) -> list[str]`

- [ ] **Step 1: 写失败测试 `tests/test_auth_store.py`**

```python
# tests/test_auth_store.py
import json
from pathlib import Path
from browser_recorder.auth import store
from browser_recorder import paths

NOW = 1722600000.0  # 固定 now，避免依赖系统时间


def _scope(host="example.com"):
    return {"scheme": ["https"], "registrable_domain": "example.com",
            "hosts": [host], "host_match": "suffix", "path_prefix": ["/"], "ports": [443, None]}


def test_save_and_load_profile(tmp_out_dir):
    meta = store.save_profile(
        tmp_out_dir, "demo",
        storage_state={"cookies": [], "origins": []}, scope=_scope(),
        expires_in_days=7, now_ts=NOW,
    )
    assert meta.name == "demo"
    pdir = paths.profile_dir(tmp_out_dir, "demo")
    assert (pdir / "storage_state.json").exists()
    assert (pdir / "meta.json").exists()

    loaded = store.load_profile(tmp_out_dir, "demo")
    assert loaded is not None
    m, ss = loaded
    assert m.name == "demo"
    assert ss == {"cookies": [], "origins": []}


def test_load_missing_returns_none(tmp_out_dir):
    assert store.load_profile(tmp_out_dir, "nope") is None


def test_is_expired(tmp_out_dir):
    meta = store.save_profile(tmp_out_dir, "demo", {"cookies": []}, _scope(),
                              expires_in_days=7, now_ts=NOW)
    assert not store.is_expired(meta, now_ts=NOW + 1)
    assert store.is_expired(meta, now_ts=NOW + 8 * 86400)


def test_find_matching_picks_unexpired(tmp_out_dir):
    store.save_profile(tmp_out_dir, "old", {"cookies": []}, _scope(),
                       expires_in_days=1, now_ts=NOW - 2 * 86400)  # 已过期
    store.save_profile(tmp_out_dir, "fresh", {"cookies": []}, _scope(),
                       expires_in_days=7, now_ts=NOW)
    name = store.find_matching(tmp_out_dir, "https://example.com/x", now_ts=NOW)
    assert name == "fresh"


def test_find_matching_no_match_returns_none(tmp_out_dir):
    store.save_profile(tmp_out_dir, "fresh", {"cookies": []}, _scope(),
                       expires_in_days=7, now_ts=NOW)
    assert store.find_matching(tmp_out_dir, "https://other.com/x", now_ts=NOW) is None


def test_list_profiles(tmp_out_dir):
    store.save_profile(tmp_out_dir, "a", {"cookies": []}, _scope(), 7, now_ts=NOW)
    store.save_profile(tmp_out_dir, "b", {"cookies": []}, _scope(), 7, now_ts=NOW)
    assert set(store.list_profiles(tmp_out_dir)) == {"a", "b"}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_auth_store.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/auth/store.py`**

```python
# browser_recorder/auth/store.py
"""登录态 profile 存储与引用：storage_state + meta.json，按 scope 匹配。"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from . import scope
from .. import paths


@dataclass
class AuthMeta:
    name: str
    created_at: float
    expires_in_days: int
    scope: dict[str, Any]
    storage_state: str = "storage_state.json"


def _meta_path(out_dir: Path, name: str) -> Path:
    return paths.profile_dir(out_dir, name) / "meta.json"


def _state_path(out_dir: Path, name: str) -> Path:
    return paths.profile_dir(out_dir, name) / "storage_state.json"


def save_profile(out_dir: Path, name: str, storage_state: dict, scope_dict: dict,
                 expires_in_days: int, *, now_ts: float) -> AuthMeta:
    pdir = paths.profile_dir(out_dir, name)
    pdir.mkdir(parents=True, exist_ok=True)
    _state_path(out_dir, name).write_text(
        json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")
    meta = AuthMeta(name=name, created_at=now_ts, expires_in_days=expires_in_days,
                    scope=scope_dict)
    _meta_path(out_dir, name).write_text(
        json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def load_profile(out_dir: Path, name: str) -> "tuple[AuthMeta, dict] | None":
    mp, sp = _meta_path(out_dir, name), _state_path(out_dir, name)
    if not mp.exists() or not sp.exists():
        return None
    d = json.loads(mp.read_text(encoding="utf-8"))
    meta = AuthMeta(**d)
    state = json.loads(sp.read_text(encoding="utf-8"))
    return meta, state


def is_expired(meta: AuthMeta, now_ts: float) -> bool:
    return now_ts > meta.created_at + meta.expires_in_days * 86400


def list_profiles(out_dir: Path) -> list[str]:
    adir = paths.auth_dir(out_dir)
    if not adir.exists():
        return []
    return sorted(p.name for p in adir.iterdir() if p.is_dir())


def find_matching(out_dir: Path, target_url: str, *, now_ts: float) -> "str | None":
    """扫描 auth/，按 scope 匹配，取最新未过期。"""
    candidates: list[tuple[float, str]] = []
    for name in list_profiles(out_dir):
        loaded = load_profile(out_dir, name)
        if loaded is None:
            continue
        meta, _ = loaded
        if is_expired(meta, now_ts):
            continue
        if scope.matches(target_url, meta.scope):
            candidates.append((meta.created_at, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_auth_store.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/auth/store.py tests/test_auth_store.py
git commit -m "feat(auth): profile 存储 + 自动扫描匹配（未指定 --auth 时按 scope 选最新未过期）"
```

---

## Task 10: 页面稳定判定（settle.py，三信号动态）

**Files:**
- Create: `browser_recorder/settle.py`
- Test: `tests/test_settle.py`

**Interfaces:**
- Produces:
  - `settle.SignalState` dataclass：`network_idle: bool`、`dom_idle: bool`、`cpu_idle: bool`，方法 `all_idle() -> bool`。
  - `settle.SettleDecider` 类：基于事件序列判定是否进入稳定态。
    - `__init__(self, debounce_ms: int)`
    - `on_network_change(self, has_inflight: bool, ts_ms: int) -> None`
    - `on_dom_change(self, ts_ms: int) -> None`
    - `on_cpu_change(self, idle: bool, ts_ms: int) -> None`
    - `is_settled(self, ts_ms: int) -> bool`：三信号全静默且持续 debounce 窗口无新变化。
  - `settle.SettleResult` dataclass：`settled: bool`、`settled_by: str`（`"network_dom_cpu"`/`"timeout"`）、`elapsed_ms: int`。
  - `settle.wait_for_settled(page, *, timeout_ms: int, debounce_ms: int) -> SettleResult`：异步函数，在真实 page 上跑（集成测试覆盖）；本任务单测 Decider 的纯逻辑。

**说明**：把"信号序列 → 是否稳定"的状态机抽成纯类 `SettleDecider`，便于不依赖浏览器单测；`wait_for_settled` 是薄封装，集成测试覆盖。

- [ ] **Step 1: 写失败测试 `tests/test_settle.py`**

```python
# tests/test_settle.py
from browser_recorder.settle import SettleDecider, SignalState


def test_signal_state_all_idle():
    s = SignalState(network_idle=True, dom_idle=True, cpu_idle=True)
    assert s.all_idle()


def test_decider_not_settled_initially():
    d = SettleDecider(debounce_ms=300)
    # 初始信号未知，不算稳定
    assert not d.is_settled(0)


def test_decider_settled_after_debounce_of_all_idle():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(has_inflight=False, ts_ms=1000)
    d.on_dom_change(ts_ms=1000)
    d.on_cpu_change(idle=True, ts_ms=1000)
    # 刚进入 idle 还没过 debounce
    assert not d.is_settled(1200)
    # 过了 debounce
    assert d.is_settled(1400)


def test_decider_resets_on_new_network_activity():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
    # 新请求到来
    d.on_network_change(True, 1500)
    assert not d.is_settled(1600)
    # 再次静默 + debounce
    d.on_network_change(False, 1600)
    assert d.is_settled(2000)


def test_decider_resets_on_dom_change():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
    d.on_dom_change(1500)  # DOM 突变
    assert not d.is_settled(1600)


def test_decider_requires_all_three():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    # 没报告 cpu idle
    assert not d.is_settled(2000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_settle.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/settle.py`**

```python
# browser_recorder/settle.py
"""页面稳定判定：网络空闲 + DOM 稳定 + 主线程空闲 三信号 + debounce。

状态机 SettleDecider 是纯逻辑，便于单测；wait_for_settled 是在真实 page 上的封装。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class SignalState:
    network_idle: bool = False
    dom_idle: bool = False
    cpu_idle: bool = False

    def all_idle(self) -> bool:
        return self.network_idle and self.dom_idle and self.cpu_idle


@dataclass
class SettleResult:
    settled: bool
    settled_by: str  # "network_dom_cpu" | "timeout"
    elapsed_ms: int


class SettleDecider:
    """三信号稳定判定状态机。任一信号活动 → 重置静默计时。"""

    def __init__(self, debounce_ms: int):
        self.debounce_ms = debounce_ms
        self.state = SignalState()
        self._last_activity_ts: int | None = None
        self._have_signals = False  # 三个信号是否都至少报告过一次

    def _touch(self, ts_ms: int) -> None:
        self._last_activity_ts = ts_ms

    def on_network_change(self, has_inflight: bool, ts_ms: int) -> None:
        self.state.network_idle = not has_inflight
        if has_inflight:
            self._touch(ts_ms)
        self._have_signals = self._have_signals or True

    def on_dom_change(self, ts_ms: int) -> None:
        # DOM 突变视为活动；之后需要等再次静默
        self.state.dom_idle = False
        self._touch(ts_ms)
        self._have_signals = self._have_signals or True
        # 立即标记为 idle 由后续无变化推定（见 is_settled 的 dom_idle 维护）
        # 这里不直接置 True，避免突变即判稳

    def mark_dom_idle(self, ts_ms: int) -> None:
        """DOM 无突变时调用，标记 dom_idle。"""
        self.state.dom_idle = True

    def on_cpu_change(self, idle: bool, ts_ms: int) -> None:
        self.state.cpu_idle = idle
        if not idle:
            self._touch(ts_ms)
        self._have_signals = self._have_signals or True

    def is_settled(self, ts_ms: int) -> bool:
        if not self._have_signals:
            return False
        if not self.state.all_idle():
            return False
        if self._last_activity_ts is None:
            return True
        return (ts_ms - self._last_activity_ts) >= self.debounce_ms


async def wait_for_settled(page: "Page", *, timeout_ms: int,
                           debounce_ms: int) -> SettleResult:
    """在真实 page 上跑三信号判定，超时兜底。

    通过注入 JS（MutationObserver + requestIdleCallback）上报 DOM/CPU；
    网络空闲通过 page 的 requestfinished/response 事件近似。
    集成测试在 Task 17 覆盖。
    """
    import time
    decider = SettleDecider(debounce_ms=debounce_ms)
    start = time.monotonic()
    inflight = 0

    def _on_request(_req):
        nonlocal inflight
        inflight += 1
        decider.on_network_change(True, int((time.monotonic() - start) * 1000))

    def _on_done(_x):
        nonlocal inflight
        inflight = max(0, inflight - 1)
        ts = int((time.monotonic() - start) * 1000)
        decider.on_network_change(inflight > 0, ts)

    page.on("request", _on_request)
    page.on("requestfinished", _on_done)
    page.on("requestfailed", _on_done)

    # 注入 DOM/CPU 上报
    await page.add_init_script(_SETTLE_INJECT)

    deadline = start + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        ts = int((time.monotonic() - start) * 1000)
        info = await page.evaluate(
            "() => ({dom_idle: window.__br_dom_idle === true, cpu_idle: window.__br_cpu_idle === true, dom_changed: window.__br_dom_changed})")
        if info.get("dom_changed"):
            decider.on_dom_change(ts)
        else:
            decider.mark_dom_idle(ts)
        decider.on_cpu_change(bool(info.get("cpu_idle")), ts)
        if decider.is_settled(ts):
            return SettleResult(settled=True, settled_by="network_dom_cpu", elapsed_ms=ts)
        await page.wait_for_timeout(50)
    return SettleResult(settled=False, settled_by="timeout", elapsed_ms=timeout_ms)


_SETTLE_INJECT = r"""
(function(){
  window.__br_dom_idle = false;
  window.__br_cpu_idle = false;
  window.__br_dom_changed = false;
  let domTimer = null;
  const obs = new MutationObserver(function(){
    window.__br_dom_changed = true;
    window.__br_dom_idle = false;
    if (domTimer) clearTimeout(domTimer);
    domTimer = setTimeout(function(){ window.__br_dom_idle = true; window.__br_dom_changed = false; }, 300);
  });
  obs.observe(document, {childList:true, subtree:true, attributes:true});
  function tick(){
    window.__br_cpu_idle = true;
    requestIdleCallback(function(){ setTimeout(tick, 200); }, {timeout: 500});
  }
  if ('requestIdleCallback' in window) tick(); else window.__br_cpu_idle = true;
})();
"""
```

注：`wait_for_settled` 的 `is_settled` 判定中 `dom_idle` 维护——`on_dom_change` 后立即置 `False`，由 `mark_dom_idle`（JS 端 300ms 无突变后置 `__br_dom_idle=true`）驱动回 `True`。`SettleDecider` 的单测通过 `mark_dom_idle`（导出供测试用）。为了让单测通过，在 `on_dom_change` 后测试需调用 `mark_dom_idle`——但测试 `test_decider_settled_after_debounce_of_all_idle` 直接 `on_dom_change` 后期望 idle，这矛盾。修正：`on_dom_change` 语义改为"标记 DOM 发生过变化事件"，**不**改变 `dom_idle` 的最终值；`dom_idle` 的真值由"无变化"推定。

修正 `on_dom_change` 实现（替换上面那版）：

```python
    def on_dom_change(self, ts_ms: int) -> None:
        # DOM 发生突变事件：视为活动，重置静默计时；dom_idle 由后续无变化推定
        self._touch(ts_ms)
        self.state.dom_idle = False
        self._have_signals = True
```

并让 `mark_dom_idle` 在无变化时把 `dom_idle` 置 True。单测 `test_decider_settled_after_debounce_of_all_idle` 中 `on_dom_change(1000)` 后 `dom_idle=False`，需先 `mark_dom_idle` 再判。更新该单测为：

```python
def test_decider_settled_after_debounce_of_all_idle():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1100)          # DOM 此后无变化
    d.on_cpu_change(True, 1000)
    assert not d.is_settled(1200)  # 距最近活动 1100 仅 100ms
    assert d.is_settled(1450)      # 距 1100 过 debounce(300)+余量
```

`test_decider_resets_on_dom_change` 同理 `on_dom_change(1500)` 后 `dom_idle=False`，`is_settled(1600)` 应为 False（满足）。`test_decider_requires_all_three` 中第一次没 cpu，`on_dom_change(1000)` 后 `dom_idle=False`、无 cpu → `all_idle()` False；`on_cpu_change(True,1000)` 后仍 `dom_idle=False`，`is_settled(1400)` 会因 `dom_idle=False` 失败 → 需补 `mark_dom_idle`。更新为：

```python
def test_decider_requires_all_three():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1000)
    assert not d.is_settled(2000)  # 缺 cpu
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
```

请以这三处修正后的单测为准。

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_settle.py -v`
Expected: 6 passed（用修正后的 3 个单测）

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/settle.py tests/test_settle.py
git commit -m "feat(settle): 三信号页面稳定判定状态机（网络/DOM/CPU + debounce）"
```

---

## Task 11: 截图时机策略（record/screenshot.py）

**Files:**
- Create: `browser_recorder/record/__init__.py`
- Create: `browser_recorder/record/screenshot.py`
- Test: `tests/test_screenshot_policy.py`

**Interfaces:**
- Consumes: `config.ScreenshotPolicy`、`models.Action`/`Target`、`selectors.target_fingerprint`
- Produces:
  - `screenshot.ScreenshotPlanner` 类：决定每个原始事件是否产图、何时产图。
    - `__init__(self, policy: ScreenshotPolicy)`
    - `should_capture(event: dict) -> list[str]`：返回该事件应触发的截图点列表（`["before"]`/`["after"]`/`[]`）。
    - `consume_input_chunk(self, key: str, value: str) -> bool`：输入聚合——连续按键返回 False（不产图/不存），直到聚合结束返回 True。返回 True 表示"这条 input 动作可落库 + 产 after 图"。
    - `is_duplicate(self, action_type: str, fingerprint: str, ts_ms: int) -> bool`：去重判定（同指纹 + 同 type 在 dedup_window 内）。

- [ ] **Step 1: 写失败测试 `tests/test_screenshot_policy.py`**

```python
# tests/test_screenshot_policy.py
from browser_recorder.record.screenshot import ScreenshotPlanner
from browser_recorder.config import DEFAULT_SCREENSHOT_POLICY


def make_planner():
    return ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)


def test_click_captures_before_and_after():
    p = make_planner()
    assert p.should_capture({"type": "click"}) == ["before", "after"]


def test_input_captures_only_after():
    p = make_planner()
    assert p.should_capture({"type": "input"}) == ["after"]


def test_scroll_captures_nothing():
    p = make_planner()
    assert p.should_capture({"type": "scroll"}) == []


def test_input_aggregation_collects_until_finalize():
    p = make_planner()
    # 连续输入字符：每次返回 False（聚合中，不落库不产图）
    assert p.consume_input_chunk("k", "a") is False
    assert p.consume_input_chunk("k", "b") is False
    # finalize 标记聚合结束
    assert p.consume_input_chunk("k", "ab", finalize=True) is True
    assert p.get_input_value() == "ab"


def test_input_aggregation_resets_after_finalize():
    p = make_planner()
    p.consume_input_chunk("k", "x")
    p.consume_input_chunk("k", "x", finalize=True)
    # 新一轮
    assert p.consume_input_chunk("k", "y") is False
    assert p.get_input_value() == "y"


def test_input_aggregation_key_change_finalizes_previous():
    p = make_planner()
    p.consume_input_chunk("field1", "a")
    # 切换到另一个元素 → 上一段聚合结束
    assert p.consume_input_chunk("field2", "b", finalize_prev=True)  # 切换时返回上一段结果
    assert p.get_pending_value("field1") == "a"


def test_dedup_consecutive_same_fingerprint():
    p = make_planner()
    assert not p.is_duplicate("click", "css:a", ts_ms=1000)
    assert p.is_duplicate("click", "css:a", ts_ms=1200)   # 同指纹同 type，窗内
    assert not p.is_duplicate("click", "css:b", ts_ms=1300)  # 不同指纹
    assert not p.is_duplicate("click", "css:a", ts_ms=2000)  # 超出窗口


def test_dedup_different_type_not_duplicate():
    p = make_planner()
    p.is_duplicate("click", "css:a", 1000)
    assert not p.is_duplicate("input", "css:a", 1100)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_screenshot_policy.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/record/__init__.py`（空）和 `screenshot.py`**

```python
# browser_recorder/record/__init__.py
```

```python
# browser_recorder/record/screenshot.py
"""截图时机策略：动作类型→截图点、输入聚合、连续重复滤除。"""
from __future__ import annotations
from ..config import ScreenshotPolicy


class ScreenshotPlanner:
    def __init__(self, policy: ScreenshotPolicy):
        self.policy = policy
        self._last: tuple[str, str, int] | None = None  # (type, fingerprint, ts)
        self._input_buf: dict[str, str] = {}             # key -> 累积值
        self._current_input_key: str | None = None

    def should_capture(self, event: dict) -> list[str]:
        t = event.get("type", "")
        return list(self.policy.points.get(t, []))

    # ---- 输入聚合 ----
    def consume_input_chunk(self, key: str, value: str, *,
                            finalize: bool = False, finalize_prev: bool = False) -> bool:
        """返回 True 表示该 input 动作可落库 + 产 after 图。"""
        if finalize_prev and self._current_input_key and key != self._current_input_key:
            # 切换元素：上一段结束，本调用不返回 True（落库由 caller 用 get_pending_value 取）
            prev_key = self._current_input_key
            self._current_input_key = key
            self._input_buf[key] = self._input_buf.get(key, "") + value
            return False  # 切换语义：调用方应先处理 prev_key

        if key != self._current_input_key and self._current_input_key is not None:
            # 隐式切换：上一段结束
            self._current_input_key = key
            self._input_buf[key] = self._input_buf.get(key, "") + value
            return False

        self._current_input_key = key
        self._input_buf[key] = self._input_buf.get(key, "") + value

        if finalize:
            self._current_input_key = None
            return True
        return False

    def get_input_value(self) -> str:
        if self._current_input_key is None:
            return ""
        return self._input_buf.get(self._current_input_key, "")

    def get_pending_value(self, key: str) -> str:
        return self._input_buf.pop(key, "")

    # ---- 去重 ----
    def is_duplicate(self, action_type: str, fingerprint: str, ts_ms: int) -> bool:
        if self._last is not None:
            lt, lf, lts = self._last
            if lt == action_type and lf == fingerprint:
                if (ts_ms - lts) <= self.policy.dedup_window_ms:
                    self._last = (action_type, fingerprint, ts_ms)
                    return True
        self._last = (action_type, fingerprint, ts_ms)
        return False
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_screenshot_policy.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/record/screenshot.py browser_recorder/record/__init__.py tests/test_screenshot_policy.py
git commit -m "feat(record): 截图时机策略（类型映射 + 输入聚合 + 连续去重）"
```

---

## Task 12: 导出期画标（export/annotator.py + fonts.py，Pillow 半透明）

**Files:**
- Create: `browser_recorder/export/__init__.py`
- Create: `browser_recorder/export/fonts.py`
- Create: `browser_recorder/export/annotator.py`
- Test: `tests/test_annotator.py`
- Asset: 随包字体文件（开源字体，放 `browser_recorder/export/assets/`）

**Interfaces:**
- Produces:
  - `fonts.load_font(size: int) -> ImageFont`：加载随包 TTF（跨平台一致）。
  - `annotator.AnnotateStyle` 常量：`COMPACT`、`VERBOSE`。
  - `annotator.annotate_screenshot(src_png: Path, dst_png: Path, marks: list[Mark], *, style: str, opacity: int) -> None`：`Mark = {seq: int, type: str, bbox: {x,y,w,h}}`，半透明画标到 dst。
  - `annotator.resolve_label_positions(marks: list[Mark], img_size: tuple[int,int]) -> list[tuple[Mark, tuple[int,int]]]`：序号气泡外置 + 碰撞避让。

**字体处理**：使用 Pillow 内置的默认字体加载会因系统不同而渲染不一致。随包分发一款开源字体（如 `NotoSans-Regular.ttf` 或退而求其次用 Pillow 的 `ImageFont.truetype` 加载一个明确随包的字体文件）。**为避免在计划里硬编码大字体下载**，本任务用 Pillow 自带 `ImageFont.load_default()` 作为 fallback，并优先尝试随包 `assets/font.ttf`（若存在）。**测试用合成图验证半透明合成正确性**（alpha 通道生效、描边可见、序号外置不重叠原图中心）。

- [ ] **Step 1: 准备字体目录（占位，允许为空，运行时 fallback 默认字体）**

```bash
mkdir -p browser_recorder/export/assets
# 可选：放入开源 TTF 命名为 font.ttf；不放则 fonts.load_font 退回默认字体
```

- [ ] **Step 2: 写失败测试 `tests/test_annotator.py`**

```python
# tests/test_annotator.py
from pathlib import Path
from PIL import Image
from browser_recorder.export import annotator


def _mk_img(p: Path, size=(400, 300), color=(255, 255, 255)):
    img = Image.new("RGB", size, color)
    img.save(p)


def test_annotate_produces_rgba_alpha_composited_output(tmp_path):
    src = tmp_path / "in.png"
    dst = tmp_path / "out.png"
    _mk_img(src)
    marks = [{"seq": 1, "type": "click", "bbox": {"x": 50, "y": 50, "w": 80, "h": 30}}]
    annotator.annotate_screenshot(src, dst, marks, style=annotator.VERBOSE, opacity=40)
    out = Image.open(dst)
    assert out.mode in ("RGBA", "RGB")
    # 画标后应与原图不同（说明叠加了标记层）
    assert list(out.getdata()) != list(Image.open(src).convert(out.mode).getdata())


def test_label_positions_outside_bbox(tmp_path):
    img_size = (400, 300)
    marks = [{"seq": 1, "type": "input",
              "bbox": {"x": 100, "y": 100, "w": 60, "h": 20}}]
    positions = annotator.resolve_label_positions(marks, img_size)
    mark, (lx, ly) = positions[0]
    bx = mark["bbox"]
    # 序号气泡应在元素右下角外侧（x 超出右边 或 y 超出下边）
    right = bx["x"] + bx["w"]
    bottom = bx["y"] + bx["h"]
    assert lx >= right - 2 or ly >= bottom - 2


def test_label_positions_avoid_collision(tmp_path):
    img_size = (600, 200)
    marks = [
        {"seq": 1, "type": "click", "bbox": {"x": 10, "y": 10, "w": 40, "h": 20}},
        {"seq": 2, "type": "click", "bbox": {"x": 55, "y": 10, "w": 40, "h": 20}},
    ]
    positions = annotator.resolve_label_positions(marks, img_size)
    # 两个气泡中心应不重叠（距离 > 气泡尺寸）
    centers = []
    for m, (lx, ly) in positions:
        centers.append((lx, ly))
    dx = abs(centers[0][0] - centers[1][0])
    dy = abs(centers[0][1] - centers[1][1])
    assert dx > 10 or dy > 10


def test_compact_style_fills_less_than_verbose(tmp_path):
    """compact 模式应只有描边+序号；verbose 多半透明填充。

    用填充像素数差异近似断言。"""
    src = tmp_path / "in.png"
    _mk_img(src)
    marks = [{"seq": 1, "type": "click", "bbox": {"x": 50, "y": 50, "w": 100, "h": 60}}]
    v = tmp_path / "v.png"; c = tmp_path / "c.png"
    annotator.annotate_screenshot(src, v, marks, style=annotator.VERBOSE, opacity=60)
    annotator.annotate_screenshot(src, c, marks, style=annotator.COMPACT, opacity=60)
    def colored(p):
        im = Image.open(p).convert("RGB")
        return sum(1 for px in im.getdata() if px != (255, 255, 255))
    assert colored(v) > colored(c)
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/test_annotator.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 4: 写 `browser_recorder/export/__init__.py`、`fonts.py`、`annotator.py`**

```python
# browser_recorder/export/__init__.py
```

```python
# browser_recorder/export/fonts.py
"""随包字体加载：优先 assets/font.ttf，回退 Pillow 默认字体。"""
from __future__ import annotations
from pathlib import Path
from PIL import ImageFont

_ASSET = Path(__file__).parent / "assets" / "font.ttf"


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if _ASSET.exists():
        try:
            return ImageFont.truetype(str(_ASSET), size)
        except Exception:
            pass
    return ImageFont.load_default()
```

```python
# browser_recorder/export/annotator.py
"""导出期半透明画标：RGBA + alpha_composite + 描边优先 + 外置序号 + 碰撞避让。

防遮盖小字体：核心信号靠不透明描边/序号，填充压得很淡（半透明）。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw
from .fonts import load_font

COMPACT = "compact"
VERBOSE = "verbose"

# 动作类型 → (描边色, 填充色)
_STYLE = {
    "click":   ((220, 40, 40), (220, 40, 40)),
    "submit":  ((220, 40, 40), (220, 40, 40)),
    "input":   ((40, 90, 220), (40, 90, 220)),
    "select":  ((140, 40, 200), (140, 40, 200)),
    "scroll":  ((220, 170, 30), (220, 170, 30)),
    "navigation": ((20, 140, 80), (20, 140, 80)),
    "hover":   ((120, 120, 120), (120, 120, 120)),
}
_DEFAULT = ((200, 200, 200), (200, 200, 200))

LABEL_SIZE = 18
LABEL_MARGIN = 4


def _color(t: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return _STYLE.get(t, _DEFAULT)


def resolve_label_positions(marks: list[dict[str, Any]],
                            img_size: tuple[int, int]) -> list[tuple[dict, tuple[int, int]]]:
    """序号气泡外置右下角；重叠时沿对角线外推。"""
    out: list[tuple[dict, tuple[int, int]]] = []
    placed: list[tuple[int, int, int, int]] = []  # x,y,w,h
    iw, ih = img_size
    for m in marks:
        b = m["bbox"]
        # 默认放元素右下角外侧
        x = int(b["x"] + b["w"]) + LABEL_MARGIN
        y = int(b["y"] + b["h"]) + LABEL_MARGIN
        w = h = LABEL_SIZE + 6
        # 边界
        x = min(x, iw - w - 2)
        y = min(y, ih - h - 2)
        # 碰撞避让：沿对角线外推
        for _ in range(40):
            collided = any(not (x + w < px or x > px + pw or y + h < py or y > py + ph)
                           for (px, py, pw, ph) in placed)
            if not collided:
                break
            x -= (w + 2); y -= (h + 2)
            x = max(2, x); y = max(2, y)
        placed.append((x, y, w, h))
        out.append((m, (x, y)))
    return out


def annotate_screenshot(src_png: Path, dst_png: Path, marks: list[dict[str, Any]],
                        *, style: str, opacity: int) -> None:
    """读 RGB 原图 → 在透明 RGBA 层画标 → alpha_composite → 存 dst。"""
    base = Image.open(src_png).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_font(LABEL_SIZE)
    alpha_fill = max(0, min(255, int(255 * (opacity / 100.0))))
    positions = resolve_label_positions(marks, base.size)

    for m, (lx, ly) in positions:
        b = m["bbox"]
        stroke, fill = _color(m["type"])
        x0, y0 = int(b["x"]), int(b["y"])
        x1, y1 = int(b["x"] + b["w"]), int(b["y"] + b["h"])
        # 描边（不透明）
        draw.rectangle([x0, y0, x1, y1], outline=stroke + (255,), width=3)
        # 半透明填充：verbose 才填充；compact 仅 click/submit 这种点用极淡
        if style == VERBOSE:
            draw.rectangle([x0, y0, x1, y1], fill=fill + (alpha_fill,))
        elif m["type"] in ("input", "select", "hover"):
            draw.rectangle([x0, y0, x1, y1], fill=fill + (max(40, alpha_fill // 2),))
        # 序号气泡（不透明）
        draw.ellipse([lx, ly, lx + LABEL_SIZE + 6, ly + LABEL_SIZE + 6],
                     fill=stroke + (255,), outline=(255, 255, 255, 255), width=1)
        text = str(m["seq"])
        try:
            tw, th = draw.textbbox((0, 0), text, font=font)[2:]
        except Exception:
            tw, th = (LABEL_SIZE, LABEL_SIZE)
        draw.text((lx + (LABEL_SIZE + 6 - tw) // 2, ly + (LABEL_SIZE + 6 - th) // 2 - 1),
                  text, fill=(255, 255, 255, 255), font=font,
                  stroke_width=1, stroke_fill=(0, 0, 0, 255))

    composited = Image.alpha_composite(base, overlay)
    composited.convert("RGB").save(dst_png)
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/test_annotator.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add browser_recorder/export/__init__.py browser_recorder/export/fonts.py browser_recorder/export/annotator.py tests/test_annotator.py
git commit -m "feat(export): Pillow 半透明画标（RGBA+alpha_composite+描边优先+外置序号+碰撞避让）"
```

---

## Task 13: HTML 与 Markdown 报告生成（report_html.py / report_md.py）

**Files:**
- Create: `browser_recorder/export/report_md.py`
- Create: `browser_recorder/export/report_html.py`
- Test: `tests/test_report_md.py`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `models.Action`、`aggregator.aggregate` 输出、画标截图路径（相对）
- Produces:
  - `report_md.render(actions: list[Action], request_groups: list[dict], annotated_img_map: dict[int, str], meta: dict) -> str`：返回 Markdown 字符串。每步：序号 + 动作类型 + 描述 + 截图（嵌入 `![step](screenshots_annotated/...)`）+ 该步触发的接口（按 `linked_action_seq` 关联）。
  - `report_html.render(...) -> str`：返回完整 HTML 字符串（含图例、步骤列表、接口折叠区、CSS 内联）。

- [ ] **Step 1: 写失败测试 `tests/test_report_md.py` 与 `tests/test_report_html.py`**

```python
# tests/test_report_md.py
from browser_recorder.models import Action, Target
from browser_recorder.export import report_md


def _action(seq, atype, css="a#x", img_after=None):
    return Action(
        seq=seq, ts=0, type=atype, url="https://example.com/p",
        target=Target(css=css, bbox={"x": 1, "y": 1, "w": 10, "h": 10}),
        screenshot={"after": img_after} if img_after else None,
    )


def test_md_has_title_and_legend():
    md = report_md.render(actions=[], request_groups=[], annotated_img_map={}, meta={"url": "https://example.com"})
    assert "# 浏览器操作报告" in md
    assert "图例" in md


def test_md_renders_step_with_screenshot():
    a = _action(1, "click", img_after="step-0001-after.png")
    md = report_md.render(actions=[a], request_groups=[], annotated_img_map={1: "step-0001-after.png"}, meta={"url": "u"})
    assert "步骤 1" in md
    assert "click" in md
    assert "screenshots_annotated/step-0001-after.png" in md


def test_md_renders_linked_requests():
    a = _action(1, "click")
    groups = [{"endpoint": {"method": "GET", "url_template": "/api/x", "param_path": []},
               "observations": 1, "merged_schema": {"type": "object", "fields": {"id": {"type": "integer"}}},
               "sample_statuses": [200], "linked_seq": [1]}]
    md = report_md.render(actions=[a], request_groups=groups, annotated_img_map={}, meta={"url": "u"})
    assert "/api/x" in md
    assert "GET" in md
```

```python
# tests/test_report_html.py
from browser_recorder.models import Action, Target
from browser_recorder.export import report_html


def test_html_well_formed_and_has_legend():
    html = report_html.render(actions=[], request_groups=[], annotated_img_map={}, meta={"url": "u"})
    assert html.startswith("<!DOCTYPE html>") or html.startswith("<html")
    assert "</html>" in html
    assert "图例" in html
    assert "<style>" in html  # CSS 内联


def test_html_renders_step():
    a = Action(seq=2, ts=0, type="input", url="u",
               target=Target(css="input", bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
               value="hello", screenshot={"after": "step-0002-after.png"})
    html = report_html.render(actions=[a], request_groups=[], annotated_img_map={2: "step-0002-after.png"}, meta={"url": "u"})
    assert "步骤 2" in html
    assert "input" in html
    assert "step-0002-after.png" in html
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_report_md.py tests/test_report_html.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `report_md.py`**

```python
# browser_recorder/export/report_md.py
"""Markdown 报告：每步序号+类型+描述+画标截图+关联接口。"""
from __future__ import annotations
from ..models import Action

_LEGEND = (
    "**图例**：🔴 click/submit · 🔵 input · 🟣 select · 🟡 scroll · 🟢 navigation · ⚪ hover\n\n"
)


def _step_line(a: Action, img_map: dict[int, str], reqs_for_seq: list[dict]) -> str:
    lines = [f"### 步骤 {a.seq} — `{a.type}`"]
    desc_bits = [f"- 类型: `{a.type}`"]
    if a.target and (a.target.css or a.target.role_selector):
        desc_bits.append(f"- 定位: `{a.target.role_selector or a.target.css}`")
    if a.value:
        desc_bits.append(f"- 输入: `{a.value}`")
    desc_bits.append(f"- URL: `{a.url}`")
    lines.append("\n".join(desc_bits))
    img = (a.screenshot or {}).get("after") or (a.screenshot or {}).get("before")
    if img and a.seq in img_map:
        lines.append(f"\n![步骤{a.seq}](screenshots_annotated/{img})")
    if reqs_for_seq:
        lines.append("\n**触发的接口：**")
        for g in reqs_for_seq:
            ep = g["endpoint"]
            lines.append(f"- `{ep['method']} {ep['url_template']}`（观测 {g['observations']} 次，状态 {g['sample_statuses']}）")
    return "\n".join(lines)


def render(actions: list[Action], request_groups: list[dict],
           annotated_img_map: dict[int, str], meta: dict) -> str:
    by_seq: dict[int, list[dict]] = {}
    for g in request_groups:
        for s in g.get("linked_seq", []):
            by_seq.setdefault(s, []).append(g)
    parts = ["# 浏览器操作报告", "", _LEGEND]
    parts.append(f"- 目标 URL: `{meta.get('url', '')}`")
    parts.append(f"- 动作数: {len(actions)}")
    parts.append("\n---\n")
    for a in actions:
        parts.append(_step_line(a, annotated_img_map, by_seq.get(a.seq, [])))
        parts.append("\n---\n")
    if request_groups:
        parts.append("## 接口清单（聚合）\n")
        for g in request_groups:
            ep = g["endpoint"]
            parts.append(f"### `{ep['method']} {ep['url_template']}`")
            parts.append(f"- 观测次数: {g['observations']}")
            parts.append(f"- 状态码: {g['sample_statuses']}")
            if ep.get("param_path"):
                parts.append(f"- 路径/查询参数: {', '.join(ep['param_path'])}")
            parts.append(f"- 字段 schema: `{g['merged_schema']}`")
            parts.append("")
    return "\n".join(parts)
```

- [ ] **Step 4: 写 `report_html.py`**

```python
# browser_recorder/export/report_html.py
"""HTML 报告：内联 CSS，左侧步骤列表 + 右侧大图 + 接口折叠。"""
from __future__ import annotations
import html as _h
from ..models import Action

_CSS = """
body{font-family:sans-serif;margin:0;display:flex}
nav{width:280px;overflow:auto;background:#f5f5f5;padding:12px;border-right:1px solid #ddd}
main{padding:16px;flex:1}
.step{margin-bottom:24px;border:1px solid #eee;padding:12px;border-radius:6px}
.step img{max-width:100%;border:1px solid #ccc}
legend span{margin-right:12px;font-size:13px}
details{margin-top:8px;background:#fafafa;padding:8px;border-radius:4px}
.badge{display:inline-block;padding:2px 6px;border-radius:3px;color:#fff;font-size:12px}
.click{background:#dc2828}.input{background:#285adc}.select{background:#8c28c8}
.scroll{background#dcaa1e}.navigation{background:#148c50}.hover{background:#787878}
"""


def _esc(s: str) -> str:
    return _h.escape(str(s))


def render(actions: list[Action], request_groups: list[dict],
           annotated_img_map: dict[int, str], meta: dict) -> str:
    by_seq: dict[int, list[dict]] = {}
    for g in request_groups:
        for s in g.get("linked_seq", []):
            by_seq.setdefault(s, []).append(g)
    legend = (
        '<legend><span class="badge click">click/submit</span>'
        '<span class="badge input">input</span>'
        '<span class="badge select">select</span>'
        '<span class="badge scroll">scroll</span>'
        '<span class="badge navigation">navigation</span>'
        '<span class="badge hover">hover</span></legend>')
    nav = "\n".join(f'<a href="#step-{a.seq}">步骤 {a.seq} · {_esc(a.type)}</a><br>' for a in actions)
    steps = []
    for a in actions:
        img = (a.screenshot or {}).get("after") or (a.screenshot or {}).get("before")
        img_html = (f'<img src="screenshots_annotated/{_esc(img)}" alt="步骤{a.seq}">'
                    if img and a.seq in annotated_img_map else "")
        reqs = by_seq.get(a.seq, [])
        req_html = ""
        if reqs:
            items = "".join(
                f"<li><code>{_esc(g['endpoint']['method'])} {_esc(g['endpoint']['url_template'])}</code> "
                f"（观测 {g['observations']} 次，状态 {g['sample_statuses']}）</li>" for g in reqs)
            req_html = f"<details><summary>触发的接口</summary><ul>{items}</ul></details>"
        steps.append(
            f'<div class="step" id="step-{a.seq}">'
            f'<span class="badge {_esc(a.type)}">{_esc(a.type)}</span> '
            f'<b>步骤 {a.seq}</b>'
            f'<div>定位: <code>{_esc((a.target.role_selector if a.target else None) or (a.target.css if a.target else ""))}</code></div>'
            f'{f"<div>输入: <code>{_esc(a.value)}</code></div>" if a.value else ""}'
            f'<div>URL: <code>{_esc(a.url)}</code></div>'
            f'{img_html}{req_html}</div>')
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<title>浏览器操作报告</title><style>" + _CSS + "</style></head><body>"
        "<nav><h3>步骤</h3>" + nav + "</nav>"
        "<main><h1>浏览器操作报告</h1>" + legend +
        f"<p>目标 URL: <code>{_esc(meta.get('url', ''))}</code> · 动作数: {len(actions)}</p>"
        + "".join(steps) + "</main></body></html>")
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/test_report_md.py tests/test_report_html.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add browser_recorder/export/report_md.py browser_recorder/export/report_html.py tests/test_report_md.py tests/test_report_html.py
git commit -m "feat(export): HTML + Markdown 操作报告（步骤+画标截图+关联接口清单）"
```

---

## Task 14: 中性测试 fixture 站点

**Files:**
- Create: `tests/fixtures/demo_site/index.html`
- Create: `tests/fixtures/demo_site/login.html`
- Create: `tests/fixtures/demo_site/list.html`
- Create: `tests/fixtures/demo_site/app.js`
- Modify: `tests/conftest.py`（加 `demo_site_dir` fixture + `serve_demo_site` fixture）

**Interfaces:**
- Produces: 一个中性静态站点（登录页→列表页→表单），含一个模拟 XHR（返回 JSON），用于 record/replay/export 集成测试。**不含任何真实系统名/host/凭据**。

- [ ] **Step 1: 写 fixture HTML（平台中性）**

```html
<!-- tests/fixtures/demo_site/index.html -->
<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>Demo</title></head>
<body><h1>Demo Site</h1><a href="login.html">去登录</a></body></html>
```

```html
<!-- tests/fixtures/demo_site/login.html -->
<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>登录</title></head>
<body>
  <h1>登录</h1>
  <form id="login-form">
    <input id="username" type="text" placeholder="用户名">
    <input id="password" type="password" placeholder="密码">
    <button type="submit" id="login-btn">登录</button>
  </form>
  <script src="app.js"></script>
</body></html>
```

```html
<!-- tests/fixtures/demo_site/list.html -->
<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>列表</title></head>
<body>
  <h1>列表</h1>
  <input id="search" type="text" placeholder="搜索">
  <button id="search-btn">搜索</button>
  <ul id="list"></ul>
  <script src="app.js"></script>
</body></html>
```

```javascript
// tests/fixtures/demo_site/app.js
// 中性演示 JS：登录后跳列表；搜索触发模拟 XHR 返回 JSON。
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('login-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      // 演示：任意输入都"登录成功"
      localStorage.setItem('demo_user', document.getElementById('username').value);
      window.location.href = 'list.html';
    });
    return;
  }
  var btn = document.getElementById('search-btn');
  var input = document.getElementById('search');
  var list = document.getElementById('list');
  function doSearch() {
    var q = input.value || '';
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'data.json?q=' + encodeURIComponent(q), true);
    xhr.onload = function () {
      try {
        var data = JSON.parse(xhr.responseText);
        list.innerHTML = '';
        (data.items || []).forEach(function (it) {
          var li = document.createElement('li');
          li.textContent = it.name + ' (' + it.id + ')';
          list.appendChild(li);
        });
      } catch (e) {}
    };
    xhr.send();
  }
  if (btn) btn.addEventListener('click', doSearch);
});
```

并创建 `tests/fixtures/demo_site/data.json`（搜索 XHR 的响应样本）：

```json
{"total": 2, "items": [{"id": 1, "name": "甲"}, {"id": 2, "name": "乙"}]}
```

- [ ] **Step 2: 扩展 `tests/conftest.py` 加 fixture**

```python
# tests/conftest.py（在已有内容后追加）
import pytest
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


@pytest.fixture
def demo_site_dir():
    return Path(__file__).parent / "fixtures" / "demo_site"


@pytest.fixture
def serve_demo_site(demo_site_dir):
    """起一个本地静态服务器serve demo_site，返回 base_url。集成测试用。"""
    import os

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(demo_site_dir), **kw)
        def log_message(self, *a, **kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)
```

- [ ] **Step 3: 验证 fixture 可被 serve（手测，不写断言）**

Run:
```bash
uv run python -c "
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
class H(SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a, directory='tests/fixtures/demo_site', **k)
    def log_message(self,*a,**k): pass
s=ThreadingHTTPServer(('127.0.0.1',0),H); p=s.server_address[1]
t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
import urllib.request
print(urllib.request.urlopen(f'http://127.0.0.1:{p}/login.html').status)
print(urllib.request.urlopen(f'http://127.0.0.1:{p}/data.json').read()[:40])
s.shutdown()
"
```
Expected: 输出 `200` 和 JSON 前缀 `b'{"total": 2, "items": [...]'`。

- [ ] **Step 4: 平台中性自检**

Run: `grep -rinE "easyops|172\.|password.*=|aksk|secret" tests/fixtures/ || echo clean`
Expected: `clean`（password 仅作为中性 placeholder 出现在 HTML input，不计）

- [ ] **Step 5: 提交**

```bash
git add tests/fixtures/ tests/conftest.py
git commit -m "test(fixture): 中性演示站点（登录/列表/搜索XHR）+ 本地静态服务器 fixture"
```

---

## Task 15: 页面注入钩子（record/injector.py）

**Files:**
- Create: `browser_recorder/record/injector.py`
- Test: `tests/test_injector.py`（纯字符串/逻辑校验，不启动浏览器）

**Interfaces:**
- Produces:
  - `injector.INJECT_SCRIPT: str`：注入页面的 JS 字常量。监听 `click/input/keydown(Enter)/change/focusin/scroll`，计算元素 `css/xpath/role/name/text/bbox`，通过 `window.__br_emit(event)` 上报（事件经 `page.expose_function` 回传 Python）。
  - `injector.build_event(node_dict: dict, type: str, value: str | None) -> dict`：Python 侧把回传的原始事件整理成标准事件 dict（`{type, target_node, value, ts}`）。

**说明**：钩子必须平台中性，不引用任何系统。bbox 用 `getBoundingClientRect()`；css 选择器用一个最小生成算法（id→tag#id；否则 tag + 第一个 class；退化为 nth-of-type）。

- [ ] **Step 1: 写失败测试 `tests/test_injector.py`**

```python
# tests/test_injector.py
from browser_recorder.record import injector


def test_inject_script_present_and_neutral():
    s = injector.INJECT_SCRIPT
    assert isinstance(s, str) and len(s) > 100
    assert "addEventListener" in s
    assert "easyops" not in s.lower()


def test_build_event_normalizes_node():
    node = {"tag": "button", "css": "button.submit", "xpath": "//button",
            "role": "button", "name": "提交", "text": "提交",
            "bbox": {"x": 1, "y": 2, "w": 3, "h": 4}}
    ev = injector.build_event(node, type="click", value=None)
    assert ev["type"] == "click"
    assert ev["target_node"]["css"] == "button.submit"
    assert ev["target_node"]["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert ev["value"] is None
    assert "ts" in ev


def test_build_event_input_carries_value():
    node = {"tag": "input", "css": "#q"}
    ev = injector.build_event(node, type="input", value="hello")
    assert ev["type"] == "input"
    assert ev["value"] == "hello"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_injector.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/record/injector.py`**

```python
# browser_recorder/record/injector.py
"""页面注入钩子：捕获用户事件 + 计算元素定位包 + bbox，回传 Python。"""
from __future__ import annotations
import time


def build_event(node_dict: dict, type: str, value: str | None) -> dict:
    return {"type": type, "target_node": node_dict, "value": value, "ts": int(time.time() * 1000)}


INJECT_SCRIPT = r"""
(function(){
  if (window.__br_installed) return;
  window.__br_installed = true;
  function cssPath(el){
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 5){
      var part = el.nodeName.toLowerCase();
      if (el.className && typeof el.className === 'string'){
        var cls = el.className.trim().split(/\s+/)[0];
        if (cls) part += '.' + CSS.escape(cls);
      }
      var sib = el, nth = 1;
      while ((sib = sib.previousElementSibling)) nth++;
      part += ':nth-of-type(' + nth + ')';
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }
  function xpath(el){
    if (el.id) return '//*[@id="' + el.id + '"]';
    var parts = [];
    while (el && el.nodeType === 1){
      var i = 1, sib = el;
      while ((sib = sib.previousElementSibling)){
        if (sib.nodeName === el.nodeName) i++;
      }
      parts.unshift(el.nodeName.toLowerCase() + '[' + i + ']');
      el = el.parentElement;
    }
    return '/' + parts.join('/');
  }
  function nodeInfo(el){
    var r = el.getBoundingClientRect();
    var role = el.getAttribute('role') || null;
    var name = el.getAttribute('aria-label') || el.getAttribute('name') || null;
    var text = (el.innerText || el.value || '').trim().slice(0, 80) || null;
    return {
      tag: el.nodeName.toLowerCase(),
      css: cssPath(el),
      xpath: xpath(el),
      role: role,
      name: name,
      text: text,
      role_selector: role ? role + (name ? '[name=\"' + name + '\"]' : '') : null,
      bbox: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
    };
  }
  function emit(type, el, value){
    if (!window.__br_emit) return;
    try { window.__br_emit({type: type, target_node: nodeInfo(el), value: value, ts: Date.now()}); } catch(e){}
  }
  document.addEventListener('click', function(e){ emit('click', e.target, null); }, true);
  document.addEventListener('change', function(e){ emit('select', e.target, e.target.value); }, true);
  document.addEventListener('input', function(e){ emit('input', e.target, e.target.value); }, true);
  document.addEventListener('keydown', function(e){
    if (e.key === 'Enter'){ emit('keypress', e.target, 'Enter'); }
  }, true);
  var scrollT = null;
  document.addEventListener('scroll', function(e){
    var t = e.target;
    if (scrollT) return;
    scrollT = setTimeout(function(){
      emit('scroll', t || document.body, null); scrollT = null;
    }, 200);
  }, true);
  window.addEventListener('beforeunload', function(){
    if (window.__br_flush) try { window.__br_flush(); } catch(e){}
  });
})();
"""
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_injector.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/record/injector.py tests/test_injector.py
git commit -m "feat(record): 页面注入钩子（事件捕获+元素定位包+bbox，平台中性）"
```

---

## Task 16: CDP 捕获器（record/capture.py）

**Files:**
- Create: `browser_recorder/record/capture.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Consumes: `models.Action`/`RequestRecord`、`response_schema.parse`、`selectors.build_target_from_dom`、`screenshot.ScreenshotPlanner`
- Produces:
  - `capture.NetworkCollector` 类：订阅 Playwright page 的 request/response 事件，按 req_id 维护请求状态，**过滤明显静态资源**（ResourceType + 后缀 + data:/blob:），流式写 `requests.jsonl`。响应体：调 `response_schema.parse`，超 1MB 落盘 `responses/<req_id>.bin` 并填 `raw_ref`。
    - `__init__(self, page, sink: Callable[[RequestRecord], None], responses_dir: Path, current_action_seq: Callable[[], int|None])`
    - `attach(self) -> None`：绑定事件。
  - `capture.is_static(url: str, resource_type: str) -> bool`：纯函数判定静态资源。
  - `capture.EventToAction` 类：把注入钩子回传的事件 + ScreenshotPlanner 决策转成 `Action`（含输入聚合、去重）。
    - `__init__(self, planner: ScreenshotPlanner)`
    - `process(self, event: dict) -> Action | None`：返回应落库的 Action 或 None（被去重/聚合中）。

- [ ] **Step 1: 写失败测试 `tests/test_capture.py`**

```python
# tests/test_capture.py
from browser_recorder.record import capture
from browser_recorder.record.screenshot import ScreenshotPlanner
from browser_recorder.config import DEFAULT_SCREENSHOT_POLICY


def test_is_static_by_suffix():
    assert capture.is_static("https://x.com/a.js", "script")
    assert capture.is_static("https://x.com/a.css", "stylesheet")
    assert capture.is_static("https://x.com/a.png", "image")
    assert capture.is_static("data:image/png;base64,xxx", "image")
    assert capture.is_static("blob:https://x.com/abc", "other")


def test_is_not_static_for_api():
    assert not capture.is_static("https://x.com/api/users", "xhr")
    assert not capture.is_static("https://x.com/api/list?q=1", "fetch")


def test_event_to_action_click():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    ev = {"type": "click", "target_node": {"tag": "button", "css": "#go", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}, "value": None, "ts": 1000}
    a = e2a.process(ev, url="https://x.com/p", page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0})
    assert a is not None
    assert a.type == "click"
    assert a.target.css == "#go"


def test_event_to_action_dedup_consecutive_click():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    node = {"tag": "button", "css": "#go", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    a1 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1000}, "https://x.com/p", {})
    a2 = e2a.process({"type": "click", "target_node": node, "value": None, "ts": 1100}, "https://x.com/p", {})
    assert a1 is not None
    assert a2 is None  # 去重


def test_event_to_action_input_aggregates():
    planner = ScreenshotPlanner(DEFAULT_SCREENSHOT_POLICY)
    e2a = capture.EventToAction(planner)
    node = {"tag": "input", "css": "#q", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    # 连续输入字符（未失焦/未提交）应被聚合，不立即产出 Action
    r1 = e2a.process({"type": "input", "target_node": node, "value": "a", "ts": 1000}, "https://x.com/p", {})
    r2 = e2a.process({"type": "input", "target_node": node, "value": "ab", "ts": 1100}, "https://x.com/p", {})
    assert r1 is None
    assert r2 is None
    # 失焦（focusout）触发 finalize
    fin = e2a.process({"type": "input_finalize", "target_node": node, "value": "ab", "ts": 1200}, "https://x.com/p", {})
    assert fin is not None
    assert fin.type == "input"
    assert fin.value == "ab"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_capture.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/record/capture.py`**

```python
# browser_recorder/record/capture.py
"""CDP/Playwright 事件捕获：网络请求采集 + 静态过滤；事件→Action 转换（聚合/去重）。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING
from ..models import Action, RequestRecord
from ..selectors import build_target_from_dom, target_fingerprint
from ..response_schema import parse as parse_response
from .screenshot import ScreenshotPlanner

if TYPE_CHECKING:
    from playwright.async_api import Page, Request, Response

_STATIC_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".gif",
                    ".woff", ".woff2", ".ttf", ".ico", ".map", ".webp")
_STATIC_TYPES = {"image", "font", "stylesheet", "media", "manifest"}


def is_static(url: str, resource_type: str) -> bool:
    u = (url or "").lower().split("?", 1)[0]
    if u.startswith(("data:", "blob:")):
        return True
    rt = (resource_type or "").lower()
    if rt in _STATIC_TYPES:
        return True
    return u.endswith(_STATIC_SUFFIXES)


class EventToAction:
    """注入事件 → Action（含输入聚合、去重）。"""

    def __init__(self, planner: ScreenshotPlanner):
        self.planner = planner
        self._seq = 0
        self._input_node: dict | None = None
        self._input_value: str = ""

    def _flush_input(self, url: str, page_info: dict, ts: int) -> Action | None:
        if self._input_node is None:
            return None
        node = self._input_node
        value = self._input_value
        self._input_node = None
        self._input_value = ""
        self._seq += 1
        return Action(
            seq=self._seq, ts=ts, type="input", url=url,
            target=build_target_from_dom(node), value=value, page_info=page_info,
        )

    def process(self, event: dict, url: str, page_info: dict) -> Action | None:
        t = event.get("type")
        ts = event.get("ts", 0)
        node = event.get("target_node") or {}
        value = event.get("value")

        # 输入聚合
        if t == "input":
            # 同一元素持续输入：累积，不产出
            if self._input_node is None or node.get("css") != (self._input_node or {}).get("css"):
                # 切换元素：先 flush 上一段
                flushed = None
                if self._input_node is not None:
                    flushed = self._flush_input(url, page_info, ts)
                self._input_node = node
                self._input_value = value or ""
                return flushed
            self._input_value = value or self._input_value
            return None
        if t == "input_finalize":
            if node.get("css") == (self._input_node or {}).get("css"):
                self._input_value = value or self._input_value
            return self._flush_input(url, page_info, ts)

        # 非 input 事件：先 flush 挂起的输入
        flushed = self._flush_input(url, page_info, ts) if self._input_node else None
        # scroll：去重并合并（这里仅做去重，合并在上层）
        if t == "scroll":
            return flushed  # scroll 默认不单独产 Action（截图点为空）

        # click / select / keypress / hover / navigation：去重
        target = build_target_from_dom(node)
        fp = target_fingerprint(target)
        if self.planner.is_duplicate(t, fp, ts):
            return flushed  # 去重，但仍可能返回先 flush 的 input
        self._seq += 1
        action = Action(
            seq=self._seq, ts=ts, type=t, url=url,
            target=target, value=value, page_info=page_info,
        )
        if flushed:
            # 返回 flush 的 input 优先；action 暂存待下次？简化：本实现一次只返回一个，
            # 用 list 更合适。改为返回 flushed，并把 action 入队由 caller 处理。
            self._pending: list[Action] = getattr(self, "_pending", [])
            self._pending.append(action)
            return flushed
        return action
```

注：上面对"flush input + 同时有新 action"的边界用了 `_pending` 队列简化处理。为保持单测稳定，**`EventToAction` 增加 `drain_pending(self) -> list[Action]`** 方法返回并清空 `_pending`。caller（runner）每次 `process` 后调用 `drain_pending` 取累积的 action。在 `__init__` 里初始化 `self._pending: list[Action] = []`。补充实现：

```python
    def drain_pending(self) -> list[Action]:
        out = getattr(self, "_pending", [])
        self._pending = []
        return out
```

并把 `__init__` 末尾改为：

```python
        self._input_node: dict | None = None
        self._input_value: str = ""
        self._pending: list[Action] = []
```

`NetworkCollector`（网络采集）实现：

```python
class NetworkCollector:
    """订阅 page 请求/响应事件，过滤静态，流式写 requests.jsonl。"""

    def __init__(self, page: "Page", sink: Callable[[RequestRecord], None],
                 responses_dir: Path, current_action_seq: "Callable[[], int | None]"):
        self.page = page
        self.sink = sink
        self.responses_dir = responses_dir
        self.current_action_seq = current_action_seq
        self._state: dict[str, dict] = {}  # req_id -> {url, method, headers, post_data, req_type}

    def attach(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def _on_request(self, req: "Request") -> None:
        try:
            if is_static(req.url, req.resource_type):
                return
            self._state[id(req)] = {
                "url": req.url, "method": req.method,
                "headers": dict(req.headers),
                "post_data": req.post_data,
                "req_type": req.resource_type,
                "ts": int(__import__("time").time() * 1000),
            }
        except Exception:
            pass

    def _on_response(self, resp: "Response") -> None:
        try:
            req = resp.request
            key = id(req)
            st = self._state.pop(key, None)
            if st is None:
                if is_static(req.url, req.resource_type):
                    return
                st = {"url": req.url, "method": req.method, "headers": dict(req.headers),
                      "post_data": req.post_data, "req_type": req.resource_type, "ts": 0}
            body = b""
            try:
                body = resp.body()
            except Exception:
                pass
            mime = resp.headers.get("content-type", "").split(";")[0].strip()
            ri = parse_response(body, mime)
            if ri.raw_size > 1_048_576 and body:
                # C 方案：超阈值落盘
                self.responses_dir.mkdir(parents=True, exist_ok=True)
                fn = hashlib.sha256(st["url"].encode()).hexdigest()[:16] + ".bin"
                (self.responses_dir / fn).write_bytes(body)
                ri.raw_ref = f"responses/{fn}"
            rec = RequestRecord(
                req_id=hex(key), ts=st["ts"], method=st["method"], url=st["url"],
                headers=st["headers"], post_data=st.get("post_data"),
                status=resp.status, response_headers=dict(resp.headers), mime=mime,
                response=ri, duration_ms=None,
                linked_action_seq=self.current_action_seq(),
            )
            self.sink(rec)
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_capture.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/record/capture.py tests/test_capture.py
git commit -m "feat(record): 网络采集器（静态过滤+响应解析+大体落盘）+ 事件转Action（聚合/去重）"
```

---

## Task 17: 回放间隔配置（replay/delays.py）

**Files:**
- Create: `browser_recorder/replay/__init__.py`
- Create: `browser_recorder/replay/delays.py`
- Test: `tests/test_replay_delays.py`

**Interfaces:**
- Consumes: `config.ReplayPolicy`
- Produces:
  - `delays.DelayResolver` 类：按动作类型解析 before/after/idle 延迟（ms）。
    - `__init__(self, policy: ReplayPolicy)`
    - `before(self, action_type: str) -> int`
    - `after(self, action_type: str) -> int`（语义：settle 超时上限）
    - `idle(self) -> int`

- [ ] **Step 1: 写失败测试 `tests/test_replay_delays.py`**

```python
# tests/test_replay_delays.py
from browser_recorder.replay.delays import DelayResolver
from browser_recorder.config import load_replay_policy, DEFAULT_REPLAY_POLICY


def test_before_resolves_by_type_with_default_fallback():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.before("click") == 300
    assert d.before("unknown") == 500  # default


def test_after_resolves_settle_timeout():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.after("submit") == 15000
    assert d.after("navigation") == 10000
    assert d.after("click") == 5000
    assert d.after("unknown") == 5000


def test_idle_constant():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.idle() == 600


def test_resolver_uses_loaded_policy_with_overrides():
    p = load_replay_policy(None, pace=None, overrides=["submit.before=999"])
    d = DelayResolver(p)
    assert d.before("submit") == 999
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_replay_delays.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/replay/__init__.py`（空）和 `delays.py`**

```python
# browser_recorder/replay/__init__.py
```

```python
# browser_recorder/replay/delays.py
"""回放延迟解析：按动作类型查表，default 兜底。"""
from __future__ import annotations
from ..config import ReplayPolicy


class DelayResolver:
    def __init__(self, policy: ReplayPolicy):
        self.policy = policy

    def _by(self, table: dict[str, int], action_type: str) -> int:
        return table.get(action_type, table.get("default", 0))

    def before(self, action_type: str) -> int:
        return self._by(self.policy.before_action, action_type)

    def after(self, action_type: str) -> int:
        return self._by(self.policy.after_action, action_type)

    def idle(self) -> int:
        return self.policy.idle_for_visibility
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_replay_delays.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/replay/delays.py browser_recorder/replay/__init__.py tests/test_replay_delays.py
git commit -m "feat(replay): 延迟解析器（按类型查表 + default 兜底）"
```

---

## Task 18: 回放执行器（replay/executor.py）

**Files:**
- Create: `browser_recorder/replay/executor.py`
- Test: `tests/test_executor.py`（用 demo_site 集成测试，启动真实浏览器）

**Interfaces:**
- Consumes: `models.Action`、`selectors.locate`、`settle.wait_for_settled`、`delays.DelayResolver`
- Produces:
  - `executor.ReplayExecutor` 类：
    - `__init__(self, page, resolver: DelayResolver, screenshot_dir: Path | None = None)`
    - `async def replay(self, actions: list[Action]) -> ReplayStats`：逐条重放。每步：`before` 停顿 → 定位（role→css→xpath→坐标回退）→ 执行动作 → `wait_for_settled(after)` → 可选截图 → `idle` 停顿。失败不中断，记 `failed`。
  - `executor.ReplayStats` dataclass：`total, succeeded, failed, failures: list[dict]`

- [ ] **Step 1: 写失败测试 `tests/test_executor.py`**

```python
# tests/test_executor.py
import asyncio
import pytest
from browser_recorder.models import Action, Target
from browser_recorder.replay.delays import DelayResolver
from browser_recorder.replay.executor import ReplayExecutor
from browser_recorder.config import DEFAULT_REPLAY_POLICY


pytestmark = pytest.mark.asyncio


async def _new_page(context):
    return await context.new_page()


async def test_replay_click_navigates_and_succeeds(serve_demo_site, tmp_path):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(serve_demo_site + "/login.html")
        resolver = DelayResolver(DEFAULT_REPLAY_POLICY)
        ex = ReplayExecutor(page, resolver)
        actions = [
            Action(seq=1, ts=0, type="input", url=serve_demo_site + "/login.html",
                   target=Target(css="#username"), value="alice",
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
            Action(seq=2, ts=0, type="click", url=serve_demo_site + "/login.html",
                   target=Target(css="#login-btn"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
        ]
        stats = await ex.replay(actions)
        await page.wait_for_load_state("networkidle")
        assert "list.html" in page.url
        assert stats.succeeded >= 1
        await browser.close()


async def test_replay_failed_action_does_not_abort(serve_demo_site):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(serve_demo_site + "/list.html")
        resolver = DelayResolver(DEFAULT_REPLAY_POLICY)
        ex = ReplayExecutor(page, resolver)
        actions = [
            Action(seq=1, ts=0, type="click", url=serve_demo_site + "/list.html",
                   target=Target(css="#nonexistent"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
            Action(seq=2, ts=0, type="click", url=serve_demo_site + "/list.html",
                   target=Target(css="#search-btn"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
        ]
        stats = await ex.replay(actions)
        assert stats.failed == 1
        assert stats.succeeded == 1
        await browser.close()
```

注：需要 `pytest-asyncio`，模式设为 auto。在 `pyproject.toml` 加配置（Step 3 一起改）。

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_executor.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/replay/executor.py`**

```python
# browser_recorder/replay/executor.py
"""回放执行器：按 trace 逐条重放，选择器回退 + settle + 可选截图，失败不中断。"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING
from ..models import Action
from ..selectors import locate
from ..settle import wait_for_settled
from .delays import DelayResolver

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class ReplayStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)


class ReplayExecutor:
    def __init__(self, page: "Page", resolver: DelayResolver,
                 screenshot_dir: Path | None = None):
        self.page = page
        self.resolver = resolver
        self.screenshot_dir = screenshot_dir

    async def _do_action(self, a: Action) -> bool:
        if a.type == "navigation":
            try:
                await self.page.goto(a.url, wait_until="domcontentloaded")
                return True
            except Exception:
                return False
        target = a.target
        loc = await locate(self.page, target) if target else None
        try:
            if a.type == "click":
                if loc:
                    await loc.click(timeout=2000)
                    return True
                if target and target.bbox:  # 坐标兜底
                    b = target.bbox
                    await self.page.mouse.click(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)
                    return True
            elif a.type == "input" and loc and a.value is not None:
                await loc.fill(a.value, timeout=2000)
                return True
            elif a.type == "submit" and loc:
                await loc.click(timeout=2000)
                return True
            elif a.type == "keypress" and loc:
                await loc.press(a.value or "Enter", timeout=2000)
                return True
            elif a.type == "select" and loc:
                await loc.select_option(a.value or "", timeout=2000)
                return True
            elif a.type == "scroll":
                await self.page.mouse.wheel(0, 300)
                return True
            elif a.type == "hover" and loc:
                await loc.hover(timeout=2000)
                return True
        except Exception:
            return False
        return loc is not None

    async def replay(self, actions: list[Action]) -> ReplayStats:
        stats = ReplayStats(total=len(actions))
        for a in actions:
            await asyncio.sleep(self.resolver.before(a.type) / 1000.0)
            ok = await self._do_action(a)
            if ok:
                # after = settle 超时上限
                await wait_for_settled(self.page,
                                       timeout_ms=self.resolver.after(a.type),
                                       debounce_ms=300)
                if self.screenshot_dir:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    await self.page.screenshot(path=str(self.screenshot_dir / f"step-{a.seq:04d}-after.png"))
                await asyncio.sleep(self.resolver.idle() / 1000.0)
                stats.succeeded += 1
            else:
                stats.failed += 1
                stats.failures.append({"seq": a.seq, "type": a.type,
                                       "css": a.target.css if a.target else None})
                if self.screenshot_dir:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    await self.page.screenshot(path=str(self.screenshot_dir / f"step-{a.seq:04d}-failed.png"))
        return stats
```

在 `pyproject.toml` 末尾追加 pytest-asyncio 配置：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_executor.py -v`
Expected: 2 passed（需 Chromium 已安装）

- [ ] **Step 5: 提交**

```bash
git add browser_recorder/replay/executor.py tests/test_executor.py pyproject.toml
git commit -m "feat(replay): 执行器（选择器回退+settle+可选截图，失败不中断）"
```

---

## Task 19: record/replay runner + CLI 装配 + export 装配 + 烟测

**Files:**
- Create: `browser_recorder/record/runner.py`
- Create: `browser_recorder/replay/runner.py`
- Create: `browser_recorder/export/runner.py`
- Create: `browser_recorder/video.py`
- Modify: `browser_recorder/cli.py`（装配 record/replay/export/auth 子命令）
- Test: `tests/test_cli_smoke.py`

**Interfaces:**
- Produces:
  - `record.runner.run_record(url, out_dir, profile, keep_auth, screenshot_policy_path, video, name) -> Path`（返回 session_dir）
  - `replay.runner.run_replay(session, out_dir, profile, pace, delay_overrides, policy_path, video, video_format, annotate_during_replay, name) -> Path`
  - `export.runner.run_export(session, out_dir, name, filter_path, keep_raw_bodies, annotate_style, annotate_opacity) -> Path`
  - CLI 四个子命令。

- [ ] **Step 1: 写失败烟测 `tests/test_cli_smoke.py`（端到端：record→export，回放单独测）**

```python
# tests/test_cli_smoke.py
import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "browser_recorder.cli", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=120)


def test_cli_record_then_export_on_demo_site(serve_demo_site, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # record：自动模拟几个操作比较复杂，这里只验证 record 能启动并产 trace.jsonl
    # 用 Playwright 直接驱动而非人工录制——通过 headless 脚本注入点击。
    # 简化烟测：调用 record runner，URL 指向 demo，--no-video，超时由 runner 控制。
    from browser_recorder.record import runner as rec_runner
    session_dir = rec_runner.run_record(
        url=serve_demo_site + "/list.html",
        out_dir=tmp_path / ".browser-recorder",
        profile=None, keep_auth=False,
        screenshot_policy_path=None, video=False, name="smoke",
        headless=True,
        # 自动操作脚本：搜索
        auto_actions=[("click", "#search-btn")],
    )
    assert (session_dir / "trace.jsonl").exists() or (session_dir / "requests.jsonl").exists()

    from browser_recorder.export import runner as exp_runner
    out = exp_runner.run_export(
        session=str(session_dir.name), out_dir=tmp_path / ".browser-recorder",
        name="smoke", filter_path=None, keep_raw_bodies=False,
        annotate_style="verbose", annotate_opacity=60,
        tmp_root=tmp_path / "tmp",
    )
    assert (out / "report.html").exists()
    assert (out / "report.md").exists()
    assert (out / "requests.json").exists()


def test_cli_export_help_lists_subcommands():
    r = _run(["--help"], cwd=".")
    assert r.returncode == 0
    assert "record" in r.stdout and "replay" in r.stdout and "export" in r.stdout
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_cli_smoke.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写 `browser_recorder/record/runner.py`**

```python
# browser_recorder/record/runner.py
"""record 子命令主流程：启浏览器、加载 auth、注入钩子、收事件、产 jsonl + 截图。"""
from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from .. import paths
from ..config import load_screenshot_policy
from .injector import INJECT_SCRIPT
from .capture import EventToAction, NetworkCollector
from .screenshot import ScreenshotPlanner


async def _record_async(url, session_dir, out_dir, profile, keep_auth,
                        screenshot_policy_path, video, name, headless, auto_actions):
    from playwright.async_api import async_playwright
    from ..auth import store

    planner = ScreenshotPlanner(load_screenshot_policy(screenshot_policy_path))
    e2a = EventToAction(planner)

    storage_state = None
    if profile:
        loaded = store.load_profile(out_dir, profile)
        if loaded is None or store.is_expired(loaded[0], time.time()):
            # 交互式登录：启动浏览器让用户登录，回车后抓 storage_state（headless 模式下跳过）
            if not headless:
                print(f"[record] profile '{profile}' 缺失/过期，请在打开的浏览器中登录，完成后按回车")
        if loaded:
            storage_state = loaded[1]

    trace_path = session_dir / "trace.jsonl"
    req_path = session_dir / "requests.jsonl"
    screenshots = session_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    current_seq_box = {"v": None}

    def _sink_action(a):
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
        current_seq_box["v"] = a.seq

    def _sink_request(r):
        with open(req_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx_kwargs = {"viewport": {"width": 1280, "height": 720}}
        if video:
            ctx_kwargs["record_video_dir"] = str(session_dir)
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = await browser.new_context(**ctx_kwargs)
        page = await ctx.new_page()

        async def _on_event(ev: dict):
            page_info = {"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}
            a = e2a.process(ev, url=page.url, page_info=page_info)
            if a:
                _sink_action(a)
            for p in e2a.drain_pending():
                _sink_action(p)

        await page.expose_function("__br_emit", lambda ev: asyncio.ensure_future(_on_event(ev)))
        await page.add_init_script(INJECT_SCRIPT)

        nc = NetworkCollector(page, _sink_request, session_dir / "responses",
                              current_action_seq=lambda: current_seq_box["v"])
        nc.attach()

        await page.goto(url)
        # auto_actions（烟测用）：执行若干点击
        for act_type, sel in (auto_actions or []):
            try:
                if act_type == "click":
                    await page.click(sel, timeout=3000)
                await page.wait_for_timeout(800)
            except Exception:
                pass
        if not auto_actions:
            # 人工录制：等用户关闭或 N 秒
            await page.wait_for_timeout(10000)

        if video:
            await ctx.close()  # 触发视频落盘
        await browser.close()


def run_record(url, out_dir, profile, keep_auth, screenshot_policy_path,
               video, name, headless=False, auto_actions=None) -> Path:
    session_id = name or paths.new_session_id()
    session_dir = paths.session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = {"url": url, "started_at": time.time(), "profile": profile,
            "keep_auth": keep_auth, "video": video, "session_id": session_id}
    (session_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    asyncio.run(_record_async(url, session_dir, out_dir, profile, keep_auth,
                              screenshot_policy_path, video, name, headless, auto_actions))
    return session_dir
```

- [ ] **Step 4: 写 `browser_recorder/replay/runner.py`**

```python
# browser_recorder/replay/runner.py
"""replay 子命令：读 trace.jsonl，回放，可选录屏/转码/实时浮标。"""
from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path
from .. import paths
from ..models import Action
from ..config import load_replay_policy
from .delays import DelayResolver
from .executor import ReplayExecutor


async def _replay_async(trace_path, url, out_dir, profile, policy, video,
                        annotate_during, headless, screenshot_dir):
    from playwright.async_api import async_playwright
    from ..auth import store
    storage_state = None
    if profile:
        loaded = store.load_profile(out_dir, profile)
        if loaded:
            storage_state = loaded[1]
    actions = [Action.from_dict(json.loads(line)) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx_kwargs = {"viewport": {"width": 1280, "height": 720}}
        if video:
            ctx_kwargs["record_video_dir"] = str(screenshot_dir.parent)
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = await browser.new_context(**ctx_kwargs)
        page = await ctx.new_page()
        resolver = DelayResolver(policy)
        ex = ReplayExecutor(page, resolver, screenshot_dir=screenshot_dir if screenshot_dir else None)
        await page.goto(url)
        stats = await ex.replay(actions)
        if video:
            await ctx.close()
        await browser.close()
        return stats


def run_replay(session, out_dir, profile, pace, delay_overrides, policy_path,
               video, video_format, annotate_during_replay, name, headless=False,
               tmp_root=None) -> Path:
    # session 解析：name 或 session_id
    old_tmp = paths.TMP_ROOT
    if tmp_root is not None:
        paths.TMP_ROOT = Path(tmp_root)
    try:
        trace_path = paths.session_dir(session) / "trace.jsonl"
        meta_path = paths.session_dir(session) / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"url": ""}
        replay_id = name or paths.new_session_id()
        replay_dir = paths.session_dir(replay_id)
        replay_dir.mkdir(parents=True, exist_ok=True)
        policy = load_replay_policy(policy_path, pace, delay_overrides)
        screenshots = replay_dir / "screenshots"
        asyncio.run(_replay_async(trace_path, meta.get("url", "about:blank"), out_dir, profile,
                                  policy, video, annotate_during_replay, headless, screenshots))
        # 可选转码
        if video and video_format == "mp4":
            from ..export.transcode import to_mp4
            webm = _find_webm(replay_dir.parent)
            if webm:
                to_mp4(webm, replay_dir.parent / "video.mp4")
        return replay_dir
    finally:
        paths.TMP_ROOT = old_tmp


def _find_webm(d: Path):
    for f in d.rglob("*.webm"):
        return f
    return None
```

- [ ] **Step 5: 写 `browser_recorder/export/transcode.py` 与 `browser_recorder/video.py`**

```python
# browser_recorder/export/transcode.py
"""webm→mp4 跨平台转码：用 imageio-ffmpeg 内置 ffmpeg 二进制。"""
from __future__ import annotations
from pathlib import Path
import imageio_ffmpeg
import subprocess


def to_mp4(src_webm: Path, dst_mp4: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-i", str(src_webm), "-c:v", "libx264",
                    "-preset", "fast", "-pix_fmt", "yuv420p", str(dst_mp4)],
                   check=True, capture_output=True)
```

```python
# browser_recorder/video.py
"""录屏封装：Playwright record_video 路径管理 + 可选转码。"""
from __future__ import annotations
from pathlib import Path


def video_final_path(session_dir: Path, fmt: str = "webm") -> Path:
    if fmt == "mp4":
        return session_dir / "video.mp4"
    return session_dir / "video.webm"
```

- [ ] **Step 6: 写 `browser_recorder/export/runner.py`**

```python
# browser_recorder/export/runner.py
"""export 子命令：读 trace+requests，画标、聚合、生成报告。"""
from __future__ import annotations
import json
from pathlib import Path
from .. import paths
from ..models import Action, RequestRecord
from ..request_aggregator import aggregate
from .annotator import annotate_screenshot, VERBOSE, COMPACT
from . import report_html, report_md


def run_export(session, out_dir, name, filter_path, keep_raw_bodies,
               annotate_style, annotate_opacity, tmp_root=None) -> Path:
    old_tmp = paths.TMP_ROOT
    if tmp_root is not None:
        paths.TMP_ROOT = Path(tmp_root)
    try:
        sdir = paths.session_dir(session)
        export_name = name or session
        edir = paths.export_dir(out_dir, export_name)
        edir.mkdir(parents=True, exist_ok=True)
        (edir / "screenshots_annotated").mkdir(exist_ok=True)

        actions = [Action.from_dict(json.loads(l)) for l in (sdir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (sdir / "trace.jsonl").exists() else []
        records = [RequestRecord.from_dict(json.loads(l)) for l in (sdir / "requests.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (sdir / "requests.jsonl").exists() else []

        # 画标
        annotated_map: dict[int, str] = {}
        style = VERBOSE if annotate_style == "verbose" else COMPACT
        marks_by_file: dict[str, list[dict]] = {}
        for a in actions:
            shot = (a.screenshot or {}).get("after") or (a.screenshot or {}).get("before")
            if not shot or not a.target or not a.target.bbox:
                continue
            marks_by_file.setdefault(shot, []).append(
                {"seq": a.seq, "type": a.type, "bbox": a.target.bbox})
            annotated_map[a.seq] = shot
        for shot, marks in marks_by_file.items():
            src = sdir / "screenshots" / shot
            if src.exists():
                annotate_screenshot(src, edir / "screenshots_annotated" / shot, marks,
                                    style=style, opacity=annotate_opacity)

        # 聚合 + 关联 seq
        groups = aggregate(records)
        for g in groups:
            tmpl = g["endpoint"]["url_template"]
            g["linked_seq"] = sorted({r.linked_action_seq for r in records
                                      if r.linked_action_seq is not None and _tmpl_of(r.url) == tmpl})
        (edir / "requests.json").write_text(
            json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = {"url": ""}
        mpath = sdir / "meta.json"
        if mpath.exists():
            meta = json.loads(mpath.read_text(encoding="utf-8"))
        (edir / "report.md").write_text(
            report_md.render(actions, groups, annotated_map, meta), encoding="utf-8")
        (edir / "report.html").write_text(
            report_html.render(actions, groups, annotated_map, meta), encoding="utf-8")
        return edir
    finally:
        paths.TMP_ROOT = old_tmp


def _tmpl_of(url: str) -> str:
    from ..request_aggregator import url_template
    return url_template(url)[0]
```

- [ ] **Step 7: 装配 `browser_recorder/cli.py`**

```python
# browser_recorder/cli.py（替换 Task 1 的骨架）
"""click CLI：record/replay/export/auth。"""
from __future__ import annotations
from pathlib import Path
import click


@click.group()
def main() -> None:
    """浏览器操作录制 / 回放 / 导出 / 登录态管理。"""


@main.command()
@click.option("--url", required=True, help="目标 URL")
@click.option("--auth", "profile", default=None, help="登录态 profile 名")
@click.option("--keep-auth-events", is_flag=True, help="保留登录过程动作")
@click.option("--screenshot-policy", "screenshot_policy", type=click.Path(), default=None)
@click.option("--no-video", "no_video", is_flag=True, help="不录屏")
@click.option("--out-dir", "out_dir", default=None)
@click.option("--name", default=None, help="易读会话名")
def record(url, profile, keep_auth_events, screenshot_policy, no_video, out_dir, name):
    """录制浏览器操作。"""
    from . import paths
    from .record import runner
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    # profile 未指定 → 自动扫描匹配
    if profile is None:
        profile = store.find_matching(od, url, now_ts=__import__("time").time())
    sd = runner.run_record(url, od, profile, keep_auth_events,
                           Path(screenshot_policy) if screenshot_policy else None,
                           video=not no_video, name=name)
    click.echo(f"录制完成：{sd}")


@main.command()
@click.argument("session")
@click.option("--auth", "profile", default=None)
@click.option("--pace", type=click.Choice(["faithful", "human", "slow"]), default="human")
@click.option("--delay", "delay_overrides", multiple=True, help="如 click.before=200ms")
@click.option("--policy", "policy_path", type=click.Path(), default=None)
@click.option("--video", is_flag=True)
@click.option("--video-format", type=click.Choice(["webm", "mp4"]), default="webm")
@click.option("--annotate-during-replay", is_flag=True)
@click.option("--out-dir", "out_dir", default=None)
@click.option("--name", default=None)
def replay(session, profile, pace, delay_overrides, policy_path, video, video_format,
           annotate_during_replay, out_dir, name):
    """回放操作轨迹。"""
    from . import paths
    from .replay import runner
    od = paths.resolve_out_dir(out_dir)
    rd = runner.run_replay(session, od, profile, pace, list(delay_overrides),
                           Path(policy_path) if policy_path else None,
                           video, video_format, annotate_during_replay, name)
    click.echo(f"回放完成：{rd}")


@main.command()
@click.argument("session")
@click.option("--filter-requests", "filter_path", type=click.Path(), default=None)
@click.option("--keep-raw-bodies", is_flag=True)
@click.option("--annotate-style", type=click.Choice(["compact", "verbose"]), default="verbose")
@click.option("--annotate-opacity", type=int, default=60)
@click.option("--out-dir", "out_dir", default=None)
@click.option("--name", default=None)
def export(session, filter_path, keep_raw_bodies, annotate_style, annotate_opacity, out_dir, name):
    """导出图文报告 + 接口清单。"""
    from . import paths
    from .export import runner
    od = paths.resolve_out_dir(out_dir)
    ed = runner.run_export(session, od, name,
                           Path(filter_path) if filter_path else None,
                           keep_raw_bodies, annotate_style, annotate_opacity)
    click.echo(f"导出完成：{ed}")


@main.group()
def auth():
    """登录态管理。"""


@auth.command("list")
@click.option("--out-dir", "out_dir", default=None)
def auth_list(out_dir):
    from . import paths
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    for n in store.list_profiles(od):
        click.echo(n)


@auth.command("show")
@click.argument("profile")
@click.option("--out-dir", "out_dir", default=None)
def auth_show(profile, out_dir):
    from . import paths
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    loaded = store.load_profile(od, profile)
    if loaded is None:
        click.echo("not found"); return
    click.echo(loaded[0].scope)


@main.command()
def version():
    from . import __version__
    click.echo(__version__)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: 跑烟测验证通过**

Run: `uv run pytest tests/test_cli_smoke.py -v`
Expected: 2 passed

- [ ] **Step 9: 全量测试 + 平台中性自检**

Run: `uv run pytest -q`
Expected: 全部通过

Run: `grep -rinE "easyops|172\.30|/next/api|toolId|aksk" browser_recorder/ tests/ || echo clean`
Expected: `clean`

- [ ] **Step 10: 提交**

```bash
git add browser_recorder/record/runner.py browser_recorder/replay/runner.py browser_recorder/export/runner.py browser_recorder/export/transcode.py browser_recorder/video.py browser_recorder/cli.py tests/test_cli_smoke.py
git commit -m "feat: record/replay/export runner + CLI 装配 + 端到端烟测"
```

---

## 收尾

完成所有任务后：
- `uv run pytest -q` 全绿
- `browser-recorder --help` 列出 record/replay/export/auth/version
- 端到端：对 demo_site 跑 record → export，产出 report.html / report.md / requests.json / 画标截图
- 平台中性自检 `grep -rin easyops browser_recorder/ tests/` 为 clean



