# browser-recorder 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 裸 CDP 直连的浏览器操作录制器——录制真人操作+网络请求为单时钟事件流 session.jsonl，配双截图与 Claude Code 文档生成模板。

**Architecture:** CLI（click）拉起 headed Chromium 并直连其调试端口（websockets 库，无 Playwright）；三组 CDP 域（Network/Page/Runtime）事件归一化为 `{t_mono, kind, ...}` append-only 写 jsonl；注入脚本（Runtime.addBinding + addScriptToEvaluateOnNewDocument）采集 DOM 动作与 MutationObserver 突变；动作后双截图（before 立即 + after 等稳定：网络空闲∧DOM 静默 500ms，30s 兜底）；停止三层（页面内 Ctrl+Shift+F9 / 关窗 / 终端 q）。文档生成引擎外置：PROMPT.md 模板随 session 落盘，由 Claude Code 会话执行。

**Tech Stack:** Python ≥3.11（uv + hatchling，flat layout）；`websockets>=15,<16`（CDP 传输）；`click>=8.1`（CLI）；`pillow`（截图标注）；pytest。

**Spec:** `projects/browser-recorder/docs/2026-08-29-browser-recorder-design.md`

## Global Constraints

- Python 钉 `>=3.11,<3.13`（sdist 编译规避，对齐 doc-converter 惯例）
- 禁止引入 Playwright/Puppeteer——CDP 协议裸操作（spec §1 选型）
- 硬脱敏写死 `writer.py`，**不可配置**（spec §3.1）：敏感 header 只记键名；`type=password` 值恒 `***`；URL `token/password/secret/` 参数值替换 `***`
- request/response body **不截断**、全量落盘（spec §3.1）
- `t_mono` 为进程单调时钟毫秒（`time.monotonic_ns() // 1_000_000`），全流唯一排序键
- 模块文件目标 ≤~200 行（spec §2.2）
- 浏览器二进制复用 `~/.cache/ms-playwright/chromium-1208/chrome-linux/chrome`（环境已装，通过 `BR_CHROME` 环境变量可覆盖；不在打包依赖里带浏览器）
- 每个 task 结束必须 commit（工作区有 javis 自动提交，改完立即手动 commit 才干净）
- 项目文档路径：`projects/browser-recorder/docs/`（用户偏好）

## File Structure

```
projects/browser-recorder/
├── pyproject.toml              # Task 1
├── README.md                   # Task 1（骨架）→ Task 11（完整）
├── src/browser_recorder/
│   ├── __init__.py             # Task 1
│   ├── cdp.py                  # Task 2  ws 连接/命令收发/事件订阅
│   ├── writer.py               # Task 3  事件归一化+jsonl+脱敏（纯函数可测）
│   ├── inject.js               # Task 5  页面注入：动作采集+突变观察+停止热键
│   ├── annotator.py            # Task 8  截图红框标注（Pillow）
│   ├── recorder.py             # Task 6  录制编排：三域挂载/稳定等待/生命周期
│   └── cli.py                  # Task 9  record/export 子命令
├── templates/PROMPT.md.tmpl    # Task 10
└── tests/
    ├── conftest.py             # Task 4  静态站 fixture（http.server + 真浏览器）
    ├── test_writer.py          # Task 3
    ├── test_inject.py          # Task 4（注入逻辑以 node 等价物单测）
    ├── test_recorder.py        # Task 7  端到端录制断言
    └── test_annotator.py       # Task 8
```

依赖顺序：Task 1（骨架）→ 2（cdp）→ 3（writer）→ 4（测试基建）→ 5（inject.js）→ 6（recorder）→ 7（e2e）→ 8（annotator）→ 9（cli）→ 10（PROMPT 模板+会话落盘）→ 11（README+收尾验证）。

---

### Task 1: 项目骨架（pyproject + 包结构）

**Files:**
- Create: `projects/browser-recorder/pyproject.toml`
- Create: `projects/browser-recorder/src/browser_recorder/__init__.py`
- Create: `projects/browser-recorder/README.md`
- Create: `projects/browser-recorder/.gitignore`

**Interfaces:**
- Produces: 包名 `browser_recorder`（import 路径），CLI 入口 `browser-recorder = "browser_recorder.cli:main"`（Task 9 实现该函数）

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "browser-recorder"
version = "0.1.0"
description = "浏览器操作录制 CLI：裸 CDP 直连，真人操作+网络请求 → session.jsonl + 双截图 + 文档生成模板"
requires-python = ">=3.11,<3.13"
dependencies = [
    "websockets>=15,<16",
    "click>=8.1,<8.2",
    "pillow>=10,<12",
]

[project.scripts]
browser-recorder = "browser_recorder.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/browser_recorder"]

[tool.hatch.build.targets.wheel.shared-data]
"templates" = "browser_recorder/templates"

[dependency-groups]
dev = ["pytest>=8.0"]
```

注意：`inject.js` 通过 `include_package_data` 不方便（非包内 data），Task 5 起把 `inject.js` 放 `src/browser_recorder/inject.js`，hatchling 默认会打包包目录内所有文件——确认 wheel 构建时包含（Step 4 验证）。

- [ ] **Step 2: 写包骨架与 README**

`src/browser_recorder/__init__.py`:

```python
__version__ = "0.1.0"
```

`README.md`（骨架版，Task 11 补完整）:

```markdown
# browser-recorder

浏览器操作录制 CLI：真人操作 + 网络请求 → `session.jsonl`（单时钟事件流）+ 双截图 + `PROMPT.md`（Claude Code 文档生成模板）。

设计文档：`docs/2026-08-29-browser-recorder-design.md`（开发中，详见实现计划）
```

`.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
sessions/
dist/
.pytest_cache/
```

- [ ] **Step 3: 安装并验证 import**

```bash
cd /workspace/projects/browser-recorder && uv sync && uv run python -c "import browser_recorder; print(browser_recorder.__version__)"
```

Expected: `0.1.0`

- [ ] **Step 4: 验证 wheel 含 inject.js 位（占位文件先建）**

```bash
touch src/browser_recorder/inject.js && uv build && unzip -l dist/*.whl | grep -E "inject|templates"
```

Expected: whl 内可见 `browser_recorder/inject.js`（templates 此时还没有，Task 10 后再验）。

- [ ] **Step 5: Commit**

```bash
git add projects/browser-recorder
git commit -m "feat(browser-recorder): 项目骨架——pyproject/包结构/README"
```

---

### Task 2: cdp.py——ws 连接与事件泵

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/cdp.py`
- Test: `projects/browser-recorder/tests/test_cdp.py`

**Interfaces:**
- Produces:
  - `class CDPClient`：`await CDPClient.connect(port: int, host: str = "127.0.0.1") -> CDPClient`
  - `await client.send(method: str, params: dict | None = None, timeout: float = 10.0) -> dict`（返回 `result` 对象；CDP 报错抛 `CDPError(code, message)`）
  - `client.on(event: str, callback)`——callback 为同步函数，收 `params: dict`；支持通配 `"*"`
  - `await client.wait_closed()`——连接关闭（浏览器退出）后返回
  - `client.closed: bool` 属性
  - `class CDPError(Exception)`，属性 `code: int, message: str`

**设计说明：** 单 ws 连接多域复用（`Target.attachToTarget` 不用，flat session 直连 page target 的 ws）。Chromium 启动参数 `--remote-debugging-port` 后，从 `http://host:port/json/version` 拿 `webSocketDebuggerUrl`。注意 page-level ws 是 `/json/version` 返回的 browser-level ws 不能收 Network 事件，必须用 `/json/list` 里 `type == "page"` 的 `webSocketDebuggerUrl`。

- [ ] **Step 1: 写失败测试（离线协议模拟）**

`tests/test_cdp.py`——用 `websockets.serve` 起本地 mock CDP 端点，验证收发逻辑，不碰真浏览器：

```python
"""cdp.py 单测：mock ws 端点模拟 CDP 协议收发。"""
import asyncio
import json

import pytest
import websockets

from browser_recorder.cdp import CDPClient, CDPError


async def _mock_cdp(ws):
    """模拟 page target ws：回命令结果 + 主动推一个事件。"""
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("id") is not None:
            if msg["method"] == "Runtime.evaluate":
                await ws.send(json.dumps(
                    {"id": msg["id"], "result": {"result": {"type": "string", "value": "ok"}}}))
            else:
                await ws.send(json.dumps(
                    {"id": msg["id"], "error": {"code": -32000, "message": "not found"}}))
        await ws.send(json.dumps(
            {"method": "Network.requestWillBeSent", "params": {"requestId": "1", "url": "x"}}))


@pytest.mark.asyncio
async def test_send_returns_result():
    async with websockets.serve(_mock_cdp, "127.0.0.1", 8765):
        client = await CDPClient.connect(8765, ws_url="ws://127.0.0.1:8765")
        r = await client.send("Runtime.evaluate", {"expression": "1"})
        assert r["result"]["value"] == "ok"
        await client.close()


@pytest.mark.asyncio
async def test_send_error_raises_cdperror():
    async with websockets.serve(_mock_cdp, "127.0.0.1", 8766):
        client = await CDPClient.connect(8766, ws_url="ws://127.0.0.1:8766")
        with pytest.raises(CDPError) as ei:
            await client.send("Nope.nothing")
        assert ei.value.code == -32000
        await client.close()


@pytest.mark.asyncio
async def test_on_event_dispatch():
    got = []
    async with websockets.serve(_mock_cdp, "127.0.0.1", 8767):
        client = await CDPClient.connect(8767, ws_url="ws://127.0.0.1:8767")
        client.on("Network.requestWillBeSent", lambda p: got.append(p["url"]))
        await client.send("Runtime.evaluate", {"expression": "1"})  # 触发 mock 推事件
        await asyncio.sleep(0.1)
        assert got == ["x"]
        await client.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /workspace/projects/browser-recorder && uv run pytest tests/test_cdp.py -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'browser_recorder.cdp'`（或 import 错）

- [ ] **Step 3: 实现 cdp.py**

```python
"""裸 CDP 客户端：单 ws 连接，命令收发 + 事件订阅。

用法：
    client = await CDPClient.connect(port)          # 真浏览器
    client = await CDPClient.connect(0, ws_url=...)  # 测试直连 ws
    client.on("Network.*", cb)                       # cb(params: dict) 同步
    r = await client.send("Page.navigate", {"url": ...})
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import urllib.request

import websockets

log = logging.getLogger(__name__)


class CDPError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"CDP error {code}: {message}")
        self.code = code
        self.message = message


class CDPClient:
    def __init__(self, ws):
        self._ws = ws
        self._id = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list] = []  # 占位，下一行真正初始化
        self._handlers = {}
        self._reader: asyncio.Task | None = None
        self.closed = False

    # ---- 连接 ----
    @classmethod
    async def connect(cls, port: int, host: str = "127.0.0.1", ws_url: str | None = None):
        if ws_url is None:
            ws_url = cls._page_ws_url(host, port)
        ws = await websockets.connect(ws_url, max_size=256 * 1024 * 1024)
        self = cls(ws)
        self._reader = asyncio.create_task(self._pump())
        return self

    @staticmethod
    def _page_ws_url(host: str, port: int) -> str:
        with urllib.request.urlopen(f"http://{host}:{port}/json/list", timeout=5) as r:
            targets = json.loads(r.read())
        for t in targets:
            if t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
        raise CDPError(-1, f"no page target on {host}:{port}")

    # ---- 事件 ----
    def on(self, event: str, callback) -> None:
        self._handlers.setdefault(event, []).append(callback)

    def _dispatch(self, method: str, params: dict) -> None:
        for cb in self._handlers.get(method, []):
            try:
                cb(params)
            except Exception:
                log.exception("handler error on %s", method)
        for cb in self._handlers.get("*", []):
            try:
                cb(method, params)
            except Exception:
                log.exception("handler error on *")

    async def _pump(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(
                                CDPError(msg["error"]["code"], msg["error"].get("message", "")))
                        else:
                            fut.set_result(msg.get("result", {}))
                else:
                    self._dispatch(msg.get("method", ""), msg.get("params", {}))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.closed = True
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()

    # ---- 命令 ----
    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        mid = next(self._id)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout)

    async def wait_closed(self) -> None:
        if self._reader:
            await self._reader

    async def close(self) -> None:
        await self._ws.close()
        if self._reader:
            await self._reader
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_cdp.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add projects/browser-recorder/src projects/browser-recorder/tests
git commit -m "feat(browser-recorder): cdp.py——ws 连接/命令收发/事件订阅"
```

---

### Task 3: writer.py——事件归一化+jsonl 落盘+硬脱敏

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/writer.py`
- Test: `projects/browser-recorder/tests/test_writer.py`

**Interfaces:**
- Produces:
  - `class SessionWriter(out_dir: pathlib.Path)`：`.emit(kind: str, payload: dict) -> int`（返回 seq）；`.close()`（flush+关闭）；`.out_dir` 属性
  - `mask_url(url: str) -> str`、`mask_headers(headers: dict) -> dict`、`mask_value_for_input(html_type: str | None, value: str) -> str`——模块级纯函数（脱敏基线）
  - 常量 `SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-auth-token", "token"}`、`SENSITIVE_URL_KEYS = ("token", "password", "secret", "passwd", "access_token")`

- [ ] **Step 1: 写失败测试**

`tests/test_writer.py`:

```python
"""writer 单测：schema 公共字段 + 硬脱敏基线。"""
import json

from browser_recorder.writer import (
    SessionWriter, mask_headers, mask_url, mask_value_for_input,
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: FAIL `ImportError: cannot import name 'SessionWriter'`

- [ ] **Step 3: 实现 writer.py**

```python
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
    """URL 中敏感 query 参数值替换为 ***。"""
    from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
    sp = urlsplit(url)
    pairs = []
    for k, v in parse_qsl(sp.query, keep_blank_values=True):
        pairs.append((k, "***" if any(s in k.lower() for s in SENSITIVE_URL_KEYS) else v))
    return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(pairs), sp.fragment))


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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add projects/browser-recorder/src projects/browser-recorder/tests
git commit -m "feat(browser-recorder): writer.py——事件归一化/jsonl/硬脱敏"
```

---

### Task 4: 测试基建——本地静态站 fixture

**Files:**
- Create: `projects/browser-recorder/tests/conftest.py`
- Create: `projects/browser-recorder/tests/fixtures/site/index.html`
- Create: `projects/browser-recorder/tests/fixtures/site/page2.html`
- Create: `projects/browser-recorder/tests/test_inject.py`

**Interfaces:**
- Produces:
  - pytest fixture `local_site`——起 `http.server` 于随机端口 serve `tests/fixtures/site/`，yield `base_url: str`
  - pytest fixture `chrome_env`——返回含 `BR_CHROME`（指向 playwright chromium）的 env 副本；浏览器不可用时 `pytest.skip`
  - 注入逻辑的**行为等价 node 测试**（不测浏览器，测 `inject.js` 同构逻辑）——见 Step 1 说明

**说明：** `/json/list` 有个坑——返回是数组但 Chromium 有时带 list header；`urllib` 直接 `json.loads(r.read())` 即可。fixture 站点准备两个页面：index 有表单+按钮+延迟交互，page2 是跳转目标。

- [ ] **Step 1: 写 fixture 站点**

`tests/fixtures/site/index.html`:

```html
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>录制测试首页</title>
<style>body{font:16px sans-serif;padding:24px}.card{padding:16px;border:1px solid #ccc;margin:8px 0}</style>
</head>
<body>
<h1>首页</h1>
<div class="card" id="box">状态：初始</div>
<button id="btn-fetch" onclick="fetchThenUpdate()">点我发请求</button>
<form id="login" action="/page2.html">
  <input name="user" type="text" placeholder="用户名">
  <input name="pass" type="password" placeholder="密码">
  <button type="submit">提交</button>
</form>
<script>
async function fetchThenUpdate() {
  document.getElementById('box').textContent = '状态：请求中';
  await new Promise(r => setTimeout(r, 300));
  const ul = document.createElement('ul');
  ul.innerHTML = '<li>条目A</li><li>条目B</li>';
  document.body.appendChild(ul);          // 触发 DOM 突变
  document.getElementById('box').textContent = '状态：完成';
}
</script>
</body>
</html>
```

`tests/fixtures/site/page2.html`:

```html
<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>第二页</title></head>
<body><h1>第二页</h1><p>表单提交后的落点。</p></body></html>
```

- [ ] **Step 2: 写 conftest.py**

```python
"""共享 fixture：本地静态站 + 真浏览器可用性探测。"""
import http.server
import os
import pathlib
import socket
import threading

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "site"
DEFAULT_CHROME = (pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def local_site():
    """http.server serve fixtures/site，返回 base_url。"""
    port = _free_port()
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a, **k: None  # 静音
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


@pytest.fixture
def chrome_path() -> pathlib.Path:
    p = pathlib.Path(os.environ.get("BR_CHROME", str(DEFAULT_CHROME)))
    if not p.exists():
        pytest.skip(f"chrome not found: {p}")
    return p
```

- [ ] **Step 3: 写 inject 行为等价单测**

注入脚本核心逻辑（选择器生成/文本截断/rect 提取）抽成可在 node 里跑的纯函数——`inject.js` 文件头以 CommonJS 导出这些纯函数、浏览器注入时用 `typeof module` 判断（CDP 注入的是文件内容字符串，无 module 环境，走 IIFE 分支）。

`tests/test_inject.py`（node 可用则跑，否则 skip）:

```python
"""inject.js 纯函数逻辑的 node 等价单测。"""
import pathlib
import shutil
import subprocess

import pytest

INJECT = pathlib.Path(__file__).parent.parent / "src" / "browser_recorder" / "inject.js"
node = shutil.which("node")


@pytest.mark.skipif(node is None or not INJECT.exists(), reason="node/inject.js 未就绪")
def test_descriptor_helpers():
    script = """
const m = require('%s');
// best_selector：有 id 用 #id；否则 tag.classes；文本截断 40
console.log(JSON.stringify([
  m.best_selector({tag:'button', id:'btn', classes:['a','b'], dom_path:'html>body>button'}),
  m.trunc_text('x'.repeat(80)),
]));
""" % INJECT
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert out.returncode == 0, out.stderr
    import json
    sel, text = json.loads(out.stdout.strip())
    assert sel == "#btn"
    assert len(text) == 40
```

- [ ] **Step 4: Task 5 前先跑（此刻 skip 合法）**

```bash
uv run pytest tests/ -v
```

Expected: `test_inject.py` SKIP（inject.js 只有空文件），其余 pass。

- [ ] **Step 5: Commit**

```bash
git add projects/browser-recorder/tests
git commit -m "test(browser-recorder): 本地静态站 fixture + inject node 等价测试基建"
```

---

### Task 5: inject.js——页面注入脚本

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/inject.js`（覆盖 Task 1 的空文件）
- Test: `projects/browser-recorder/tests/test_inject.py`（Task 4 已写，本任务让它转绿）

**Interfaces:**
- Consumes: Task 6 中 `Runtime.addBinding("__brEvent")` 先于本脚本注入执行（binding 必须先存在，`addScriptToEvaluateOnNewDocument` 的脚本才能引用）
- Produces:
  - 文件头 CommonJS 导出：`best_selector(desc)`、`trunc_text(s)`（node 测试消费）
  - 浏览器分支：捕获 `click`/`input`/`submit`（capture 阶段，document 级），序列化 `{type, element:{rect, viewport, descriptor}, value, html_type, frame_id 无需}` 调 `__brEvent(json)`
  - MutationObserver：150ms 聚合，突变静默窗口供稳定判定（`__brMutations(count)`）
  - 停止热键 `Ctrl+Shift+F9`（capture，覆盖所有 frame 注入实例）：`__brEvent('{"type":"control_stop"}')`

- [ ] **Step 1: 让失败测试先明确（Task 4 的 test_descriptor_helpers 现在应跑且 FAIL）**

```bash
uv run pytest tests/test_inject.py -v
```

Expected: FAIL（inject.js 空文件，require 后 `m.best_selector` undefined → returncode!=0）

- [ ] **Step 2: 实现 inject.js**

```javascript
/* browser-recorder 页面注入脚本。
 * 两种形态：
 *  - node（require）：导出纯函数（best_selector/trunc_text）供单测
 *  - 浏览器（CDP 注入字符串）：IIFE，监听动作/突变/停止热键，经 __brEvent 上报
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { factory().install(root); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function trunc_text(s) {
    s = (s || "").replace(/\s+/g, " ").trim();
    return s.length > 40 ? s.slice(0, 40) + "…" : s;
  }

  function best_selector(desc) {
    if (desc.id) return "#" + desc.id;
    var parts = [desc.tag];
    if (desc.classes && desc.classes.length) parts.push("." + desc.classes.join("."));
    return parts.join("");
  }

  function describe(el) {
    var r = el.getBoundingClientRect();
    var dd = el.ownerDocument.documentElement;
    return {
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      viewport: {
        w: innerWidth, h: innerHeight,
        scrollX: scrollX, scrollY: scrollY,
        dpr: devicePixelRatio || 1,
      },
      descriptor: {
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        classes: Array.prototype.slice.call(el.classList || []),
        text: trunc_text(el.textContent || el.value || el.getAttribute("aria-label") || ""),
        dom_path: (function () {
          var p = [], cur = el;
          while (cur && cur.nodeType === 1 && p.length < 12) {
            p.unshift(cur.tagName.toLowerCase() +
              (cur.id ? "#" + cur.id : ""));
            cur = cur.parentElement;
          }
          return p.join(">");
        })(),
        best_selector: null, // 下方填
      },
    };
  }

  function api() {
    var ev = describe(document.activeElement || document.body);
    return ev;
  }

  function install(win) {
    var B = win.__brEvent;
    if (!B || win.__brInstalled) return;
    win.__brInstalled = true;

    function report(type, el, extra) {
      try {
        var payload = describe(el);
        payload.type = type;
        if (extra) for (var k in extra) payload[k] = extra[k];
        payload.descriptor.best_selector =
          best_selector(payload.descriptor) === "" ? "" :
          (payload.descriptor.id ? "#" + payload.descriptor.id :
           payload.descriptor.tag +
           (payload.descriptor.classes.length ? "." + payload.descriptor.classes.join(".") : ""));
        B(JSON.stringify(payload));
      } catch (e) { /* 上报失败不扰动页面 */ }
    }

    // 动作：capture 阶段，document 级
    ["click", "submit"].forEach(function (t) {
      win.document.addEventListener(t, function (e) {
        var el = t === "submit" ? e.target : (e.target.closest("a,button,input,select,textarea,[onclick]") || e.target);
        report(t, el, {});
      }, true);
    });
    win.document.addEventListener("input", function (e) {
      var el = e.target;
      report("input", el, {
        value: el.type === "password" ? "***" : String(el.value || "").slice(0, 200),
        html_type: el.type || "text",
      });
    }, true);

    // 停止热键：Ctrl+Shift+F9
    win.document.addEventListener("keydown", function (e) {
      if (e.ctrlKey && e.shiftKey && (e.key === "F9" || e.keyCode === 120)) {
        e.preventDefault(); e.stopPropagation();
        B(JSON.stringify({ type: "control_stop" }));
      }
    }, true);

    // DOM 突变聚合：150ms 窗口
    var pending = 0, timer = null, last = 0;
    new MutationObserver(function (muts) {
      pending += muts.length;
      clearTimeout(timer);
      timer = setTimeout(function () {
        last = Date.now();
        try { B(JSON.stringify({ type: "dom_mutations", count: pending })); } catch (e) {}
        pending = 0;
      }, 150);
    }).observe(win.document.documentElement, {
      subtree: true, childList: true, attributes: true, characterData: true,
    });
  }

  return { best_selector: best_selector, trunc_text: trunc_text, install: install, _describeForTest: describe };
});
```

- [ ] **Step 3: 跑 node 等价测试转绿**

```bash
uv run pytest tests/test_inject.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add projects/browser-recorder/src/browser_recorder/inject.js projects/browser-recorder/tests/test_inject.py
git commit -m "feat(browser-recorder): inject.js——动作采集/突变聚合/停止热键"
```

---

### Task 6: recorder.py——录制编排核心

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/recorder.py`
- Test: （本任务只做冒烟编译级验证，e2e 断言在 Task 7）

**Interfaces:**
- Consumes: `CDPClient`（Task 2）、`SessionWriter`（Task 3）、`inject.js`（Task 5）
- Produces:
  - `async def record(out_dir: pathlib.Path, start_url: str, chrome_path: pathlib.Path, settle_timeout: float = 30.0, port: int | None = None) -> dict`——完成一次录制到停止，返回 `{"events": n, "out_dir": str, "abnormal": bool}`
  - `async def wait_stable(state: "StableState", timeout: float) -> str`——返回 `"stable" | "timeout"`（供 after 截图等待；`StableState` 由 recorder 内部维护网络 in-flight 计数与最后突变时间）

- [ ] **Step 1: 实现 recorder.py**

```python
"""录制编排：拉浏览器、挂三域、双截图、稳定等待、三层停止。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import pathlib
import subprocess
import time

from .cdp import CDPClient
from .writer import SessionWriter

log = logging.getLogger(__name__)

INJECT_JS = pathlib.Path(__file__).with_name("inject.js").read_text(encoding="utf-8")
SETTLE_DOM_SILENCE_MS = 500


class StableState:
    """网络空闲 ∧ DOM 静默 500ms 的稳定判定状态。"""

    def __init__(self):
        self.inflight = 0
        self.last_mutation_ms = time.monotonic_ns() // 1_000_000
        self._long_conn_ids: set[str] = set()   # websocket/SSE 等常驻连接不算 in-flight

    def net_open(self, request_id: str, url: str) -> None:
        if any(k in url for k in ("ws://", "wss://", "/sse", "eventsource")):
            self._long_conn_ids.add(request_id)
            return
        self.inflight += 1

    def net_close(self, request_id: str) -> None:
        if request_id in self._long_conn_ids:
            self._long_conn_ids.discard(request_id); return
        self.inflight = max(0, self.inflight - 1)

    def mark_mutation(self) -> None:
        self.last_mutation_ms = time.monotonic_ns() // 1_000_000


async def wait_stable(state: StableState, timeout: float) -> str:
    """两条件：inflight==0 且 距上次突变 >=500ms。返回 stable/timeout。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        now = time.monotonic_ns() // 1_000_000
        if state.inflight == 0 and now - state.last_mutation_ms >= SETTLE_DOM_SILENCE_MS:
            return "stable"
        await asyncio.sleep(0.05)
    return "timeout"


async def record(out_dir, start_url, chrome_path, settle_timeout=30.0, port=None) -> dict:
    out_dir = pathlib.Path(out_dir)
    writer = SessionWriter(out_dir)
    state = StableState()
    stop_evt = asyncio.Event()
    chrome = None
    inflight_bodies: dict[str, str] = {}      # request_id -> mime（是否抓 body）
    action_q: asyncio.Queue = asyncio.Queue() # 注入上报 → 处理协程

    # ---- 起浏览器 ----
    port = port or _free_port()
    chrome = subprocess.Popen([
        str(chrome_path),
        f"--remote-debugging-port={port}",
        "--user-data-dir=%s" % (out_dir / "chrome-profile"),
        "--no-first-run", "--no-default-browser-check",
        "--disable-frency-features", "--window-size=1280,900",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import urllib.request
    ws_url = None
    for _ in range(50):  # 等 devtools 端口就绪，~5s
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as r:
                for t in json.loads(r.read()):
                    if t.get("type") == "page":
                        ws_url = t["webSocketDebuggerUrl"]; break
            if ws_url: break
        except Exception:
            await asyncio.sleep(0.1)
    if not ws_url:
        chrome.kill()
        raise RuntimeError("浏览器 devtools 端口未就绪（检查 DISPLAY/端口占用，可用 --port 换端口）")

    client = await CDPClient.connect(port)

    writer.emit("session_start", {"url": start_url, "ts": time.time(),
                                  "chrome": str(chrome_path), "pid": chrome.pid})
    try:
        # ---- 挂域 + binding + 注入 ----
        await client.send("Network.enable")
        await client.send("Page.enable")
        await client.send("Runtime.enable")
        await client.send("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT_JS})
        # binding 必须在注入脚本运行前注册：改用 Runtime.addBinding + 手动评估当前页
        await client.send("Runtime.addBinding", {"name": "__brEvent"})
        await client.send("Runtime.evaluate", {"expression": INJECT_JS})  # 当前页立即生效

        # ---- 事件处理 ----
        def on_req(p):
            state.net_open(p["requestId"], p.get("request", {}).get("url", ""))
            writer.emit("request", {
                "request_id": p["requestId"], "method": p.get("request", {}).get("method"),
                "url": p.get("request", {}).get("url"), "headers": p.get("request", {}).get("headers"),
                "post_body": _post_body(p), "initiator": p.get("initiator", {}).get("type"),
            })
        client.on("Network.requestWillBeSent", on_req)

        def on_resp(p):
            state.net_close(p["requestId"])
            writer.emit("response", {
                "request_id": p["requestId"], "status": p["response"].get("status"),
                "mime": p["response"].get("mimeType"), "headers": p["response"].get("headers"),
                "size": p["response"].get("encodedDataLength"),
            })
            # body 抓取放队列外直接调度
            asyncio.get_running_loop().create_task(_fetch_body(client, writer, p["requestId"]))
        client.on("Network.responseReceived", on_resp)

        def on_loading_fail(p):
            state.net_close(p["requestId"])
        client.on("Network.loadingFailed", on_loading_fail)

        def on_nav(p):
            if p.get("frame", {}).get("parentId") is None:  # 主 frame
                writer.emit("nav", {"url": p.get("frame", {}).get("url", ""),
                                    "title": ""})
        client.on("Page.frameNavigated", on_nav)

        async def binding_handler(method, params):
            if method != "Runtime.bindingCalled" or params.get("name") != "__brEvent": return
            try:
                payload = json.loads(params["payload"])
            except json.JSONDecodeError:
                return
            t = payload.get("type")
            if t == "control_stop":
                stop_evt.set()
            elif t == "dom_mutations":
                state.mark_mutation()
                writer.emit("dom_mutations", {"count": payload.get("count", 0)})
            elif t in ("click", "input", "submit"):
                await action_q.put(payload)
        client.on("*", lambda m, p: asyncio.get_running_loop().create_task(binding_handler(m, p)))

        # ---- 动作处理协程：双截图 ----
        async def action_loop():
            while True:
                payload = await action_q.get()
                if payload is None: break
                seq = writer.emit("action", {
                    "type": payload["type"],
                    "element": {"rect": payload.get("rect"), "viewport": payload.get("viewport"),
                                 "descriptor": payload.get("descriptor")},
                    "value": payload.get("value"), "html_type": payload.get("html_type"),
                    "before_shot": None, "after_shot": None,
                })
                # before（尽力而为）
                before_status = "ok"
                try:
                    shot = await client.send("Page.captureScreenshot", {"format": "png"})
                    _save_shot(out_dir, seq, "before", shot["data"])
                except Exception:
                    before_status = "raced"
                # after（等稳定）
                how = await wait_stable(state, settle_timeout)
                try:
                    shot = await client.send("Page.captureScreenshot", {"format": "png"})
                    _save_shot(out_dir, seq, "after", shot["data"])
                    after_status = how
                except Exception:
                    after_status = "failed"
                writer.emit("screenshot", {"action_seq": seq, "phase": "before",
                                            "file": f"{seq:04d}-before.png", "status": before_status})
                writer.emit("screenshot", {"phase": "after",
                                            "action_seq": seq,
                                            "file": f"{seq:04d}-after.png", "status": after_status})

        actions = asyncio.create_task(action_loop())

        # ---- 导航 + 停止等待 ----
        await client.send("Page.navigate", {"url": start_url})
        stop_reason = "browser_closed"
        stop_waiters = [
            asyncio.create_task(_wait_browser_closed(client)),
            asyncio.create_task(stop_evt.wait()),
            asyncio.create_task(_wait_terminal_q()),
        ]
        done, pending = await asyncio.wait(stop_waiters, return_when=asyncio.FIRST_COMPLETED)
        for t in pending: t.cancel()
        if stop_evt.is_set(): stop_reason = "hotkey"
        elif any(t.result() == "q" for t in done if t in stop_waiters[2:3] and t.done() and not t.cancelled()):
            stop_reason = "terminal_q"
        abnormal = stop_reason == "browser_closed" and chrome.poll() not in (None, 0)
        await action_q.put(None)
        actions.cancel()
        writer.emit("session_end", {"abnormal": abnormal, "stop_reason": stop_reason})
        return {"events": writer._seq, "out_dir": str(out_dir), "abnormal": abnormal,
                "stop_reason": stop_reason}
    finally:
        try: await client.close()
        except Exception: pass
        writer.close()
        if chrome.poll() is None:
            chrome.terminate()
            try: chrome.wait(timeout=5)
            except subprocess.TimeoutExpired: chrome.kill()


def _free_port() -> int:
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


def _post_body(p: dict):
    req = p.get("request", {})
    if "postData" in req:
        return req["postData"]
    return None


async def _fetch_body(client, writer, request_id: str):
    try:
        r = await client.send("Network.getResponseBody", {"requestId": request_id}, timeout=5)
        writer.emit("response_body", {
            "request_id": request_id,
            "body": r.get("body", ""),
            "body_base64": r.get("base64Encoded", False),
        })
    except Exception:
        writer.emit("response_body", {"request_id": request_id, "error": "evicted"})


def _save_shot(out_dir, seq: int, phase: str, b64: str) -> None:
    (out_dir / "screenshots" / f"{seq:04d}-{phase}.png").write_bytes(base64.b64decode(b64))
```

- [ ] **Step 2: 冒烟编译验证**

```bash
uv run python -c "from browser_recorder.recorder import record, wait_stable, StableState; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add projects/browser-recorder/src
git commit -m "feat(browser-recorder): recorder.py——三域挂载/双截图/稳定等待/三层停止"
```

---

### Task 7: 端到端测试——真浏览器录制

**Files:**
- Test: `projects/browser-recorder/tests/test_recorder.py`

**Interfaces:**
- Consumes: `record()`（Task 6）、`local_site`/`chrome_path` fixture（Task 4）

- [ ] **Step 1: 写 e2e 测试**

```python
"""端到端：真浏览器 + 本地静态站 + 程序化操作 → 断言事件流。"""
import asyncio
import json

import pytest

from browser_recorder.cdp import CDPClient
from browser_recorder.recorder import record


async def _click_btn(client: CDPClient, sel: str):
    await client.send("Runtime.evaluate", {
        "expression": f"document.querySelector('{sel}').click()",
        "awaitPromise": False,
    })


@pytest.mark.asyncio
async def test_record_session_flow(local_site, chrome_path, tmp_path):
    result = await asyncio.wait_for(
        record(tmp_path / "sess", local_site + "/index.html", chrome_path,
               settle_timeout=5.0),
        timeout=120,
    )
```

e2e 录"程序化操作"需要注入驱动：录制内部已在跑，测试另开 ws 连接同 port 去驱动 DOM 操作（`Runtime.evaluate` 调 `document.querySelector('#btn-fetch').click()`、给 input 派发 input 事件）。由于 record() 的 port 是内部随机分配，**此处接口微调**：`record(..., port=…)` 已支持；测试先 `_free_port` 固定端口再启动第二个客户端驱动。

完整测试（重写 Step 1 的文件）：

```python
"""端到端：真浏览器 + 本地静态站 + 程序化驱动操作 → 断言事件流/截图/脱敏。"""
import asyncio
import json
import pathlib
import socket

import pytest

from browser_recorder.recorder import record


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


async def _drive(port: int, base: str):
    """测试侧第二连接：导航后驱动页面操作。"""
    from browser_recorder.cdp import CDPClient
    for _ in range(50):
        try:
            c = await CDPClient.connect(port); break
        except Exception:
            await asyncio.sleep(0.2)
    else:
        raise RuntimeError("drive client 连不上")
    await asyncio.sleep(1.5)  # 等首页加载+注入生效
    await c.send("Runtime.evaluate", {"expression":
        "document.querySelector('#btn-fetch').click()"})
    await asyncio.sleep(1.5)  # 等 settle + 双截图完成
    await c.send("Runtime.evaluate", {"expression":
        "const i=document.querySelector('input[name=user]');"
        "i.value='alice'; i.dispatchEvent(new Event('input',{bubbles:true}));"})
    await asyncio.sleep(0.8)
    await c.send("Runtime.evaluate", {"expression":
        "const p=document.querySelector('input[name=pass]');"
        "p.value='hunter2'; p.dispatchEvent(new Event('input',{bubbles:true}));"})
    await asyncio.sleep(0.8)
    # 停止：直接杀浏览器（也验证 browser_closed 收尾）
    return c


@pytest.mark.asyncio
async def test_record_session_flow(local_site, chrome_path, tmp_path):
    port = _free_port()
    out = tmp_path / "sess"

    async def drive_task():
        await _drive(port, local_site)

    dt = asyncio.create_task(drive_task())
    result = await asyncio.wait_for(
        record(out, local_site + "/index.html", chrome_path,
               settle_timeout=5.0, port=port),
        timeout=120,
    )
    await dt

    # ---- 断言产物 ----
    lines = [json.loads(l) for l in (out / "session.jsonl").read_text().splitlines()]
    kinds = [l["kind"] for l in lines]
    assert "session_start" in kinds and "session_end" in kinds
    assert "nav" in kinds                       # 导航事件
    assert kinds.count("action") >= 3           # click + 2x input
    acts = [l for l in lines if l["kind"] == "action"]
    assert any(a["type"] == "click" for a in acts)
    ins = [a for a in acts if a["type"] == "input"]
    assert any(a.get("value") == "alice" for a in ins)
    assert any(a.get("value") == "***" for a in ins)   # password 脱敏
    assert any(a.get("value") == "alice" for a in ins)
    # 截图文件存在
    shots = list((out / "screenshots").glob("*.png"))
    assert len(shots) >= 6                       # >=3 动作 x before/after
    # 网络：页面自身的请求（index.html、page2 若触发）被记录
    reqs = [l for l in lines if l["kind"] == "request"]
    assert any("index.html" in r["url"] for r in reqs)
    # screenshot 事件带稳定状态
    scr = [l for l in lines if l["kind"] == "screenshot"]
    assert any(s["phase"] == "after" and s.get("status") == "stable" for s in scr)


@pytest.mark.asyncio
async def test_record_hotkey_stop(local_site, chrome_path, tmp_path):
    """页面内热键停止（Ctrl+Shift+F9 经注入脚本路径，用 dispatchEvent 模拟）。"""
    port = _free_port()
    out = tmp_path / "sess2"

    async def drive():
        from browser_recorder.cdp import CDPClient
        for _ in (0,):
            pass
        for _ in range(50):
            try:
                c = await CDPClient.connect(port); break
            except Exception:
                await asyncio.sleep(0.2)
        await asyncio.sleep(1.5)
        await c.send("Runtime.evaluate", {"expression":
            "document.dispatchEvent(new KeyboardEvent('keydown',"
            "{ctrlKey:true, shiftKey:true, key:'F9', keyCode:120, bubbles:true}))"})
        await c.close()

    dt = asyncio.create_task(drive())
    result = await asyncio.wait_for(
        record(out, local_site + "/index.html", chrome_path, port=port),
        timeout=60,
    )
    await dt
    assert result["stop_reason"] == "hotkey"
    assert result["abnormal"] is False
```

- [ ] **Step 2: 跑 e2e**

```bash
uv run pytest tests/test_recorder.py -v
```

Expected: 2 passed（如浏览器起不来：检查 DISPLAY，必要时 `xvfb-run -a uv run pytest …`；沙箱无头环境用 `--headless=new` 参数追加到 record 的 chrome 启动参数——在 `record()` 加 `headless: bool = False` 形参并条件追加）

**注意：** 沙箱内跑 e2e 若无 X 环境，给 `record()` 增加 `headless` 参数（默认 False，e2e 传 True），并在 chrome 启动列表条件追加 `--headless=new`。这是对 Task 6 接口的修订，**改 Task 6 的 record 签名为**：

```python
async def record(out_dir, start_url, chrome_path, settle_timeout=30.0, port=None,
                 headless: bool = False) -> dict:
```

启动参数处：

```python
    args = [str(chrome_path), f"--remote-debugging-port={port}",
            "--user-data-dir=%s" % (out_dir / "chrome-profile"),
            "--no-first-run", "--no-default-browser-check",
            "--window-size=1280,900", "about:blank"]
    if headless: args.append("--headless=new")
    chrome = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

- [ ] **Step 3: Commit**

```bash
git add projects/browser-recorder/tests projects/browser-recorder/src
git commit -m "test(browser-recorder): e2e 真浏览器录制——事件流/脱敏/截图/热键停止"
```

---

### Task 8: annotator.py——截图红框标注

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/annotator.py`
- Test: `projects/browser-recorder/tests/test_annotator.py`

**Interfaces:**
- Consumes: 截图 PNG（recorder `_save_shot` 产物）、action 事件的 `element.rect` + `element.viewport.dpr`
- Produces: `annotate(png_path: pathlib.Path, rect: dict, dpr: float = 1.0, seq: int | None = None) -> pathlib.Path`（原地覆写，返回路径）

- [ ] **Step 1: 写失败测试**

```python
"""annotator 单测：红框几何与序号渲染。"""
import json

from PIL import Image

from browser_recorder.annotator import annotate


def test_annotate_draws_box(tmp_path):
    # 造一张 200x100 灰图
    img = Image.new("RGB", (200, 100), (128, 128, 128))
    p = tmp_path / "0001-before.png"
    img.save(p)
    rect = {"x": 10, "y": 20, "w": 30, "h": 40}
    out = annotate(p, rect, dpr=1.0, seq=1)
    im = Image.open(out)
    assert im.size == (200, 100)
    # 框线上应有红色像素（矩形边缘中点）
    edge_pts = [(25, 20), (25, 60), (10, 40), (40, 40)]
    for x, y in edge_pts:
        r, g, b = im.getpixel((x, y))[:3]
        assert r > 180 and g < 100 and b < 100, f"({x},{y})={r,g,b}"
    # 框外远处不受影响
    r, g, b = im.getpixel((5, 5))[:3]
    assert abs(r - 128) < 30 and abs(g - 128) < 30
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_annotator.py -v
```

Expected: FAIL `ImportError`

- [ ] **Step 3: 实现 annotator.py**

```python
"""截图红框标注：rect × dpr → 像素框 + 动作序号。原地覆写。"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

RED = (255, 0, 0, 255)


def annotate(png_path: pathlib.Path, rect: dict, dpr: float = 1.0, seq: int | None = None) -> pathlib.Path:
    png_path = pathlib.Path(png_path)
    im = Image.open(png_path).convert("RGB")
    d = ImageDraw.Draw(im)
    x, y = rect["x"] * dpr, rect["y"] * dpr
    w, h = rect["w"] * dpr, rect["h"] * dpr
    lw = max(2, int(2 * dpr))
    for i in range(lw):
        d.rectangle([x - i, y - i, x + w + i, y + h + i], outline=RED)
    if seq is not None:
        label = str(seq)
        fs = max(14, int(16 * dpr))
        d.text((x + 2, y - fs - 4), label, fill=RED)  # 无字体依赖，默认位图字体
    im.save(png_path)
    return png_path
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_annotator.py -v
```

Expected: PASS

- [ ] **Step 5: 接线 recorder——`_save_shot` 后调 annotate**

Task 6 `action_loop` 中两张截图保存后各追加（rect/dpr 来自 payload）：

```python
                from .annotator import annotate
                vp = payload.get("viewport") or {}
                dpr = vp.get("dpr") or 1.0
                rt = (payload.get("rect") or {})
                if rt.get("w"):
                    for ph in ("before", "after"):
                        f = out_dir / "screenshots" / f"{seq:04d}-{ph}.png"
                        if f.exists():
                            annotate(f, rt, dpr=dpr, seq=seq)
```

（放 `_save_shot` 调用与 screenshot 事件 emit 之间。）

- [ ] **Step 6: 全量回归**

```bash
uv run pytest tests/ -v
```

Expected: 全部 PASS（e2e 2 个 + 单测若干）

- [ ] **Step 7: Commit**

```bash
git add projects/browser-recorder/src projects/browser-recorder/tests
git commit -m "feat(browser-recorder): annotator——截图红框+序号标注，接线 recorder"
```

---

### Task 9: cli.py——record/export 子命令

**Files:**
- Create: `projects/browser-recorder/src/browser_recorder/cli.py`

**Interfaces:**
- Consumes: `record()`（Task 6，含 headless 参数）
- Produces: `main()`（console_script 入口）；`browser-recorder record [URL]`、`browser-recorder export <session_dir>`

- [ ] **Step 1: 实现 cli.py**

```python
"""CLI 入口：record / export。"""
from __future__ import annotations

import asyncio
import os
import pathlib
import zipfile
from datetime import datetime

import click

from .recorder import record

DEFAULT_CHROME = pathlib.Path(
    os.environ.get("BR_CHROME",
                   str(pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome")))


@click.group()
def main():
    """browser-recorder：浏览器操作录制 → session.jsonl + 双截图 + PROMPT.md。"""


@main.command()
@click.argument("start_url", default="about:blank")
@click.option("--out", "-o", "out_root", default="sessions",
              help="session 输出根目录（默认 sessions/，自动建时间戳子目录）")
@click.option("--settle-timeout", default=30.0, show_default=True,
              help="after 截图稳定等待兜底秒数")
@click.option("--port", default=None, type=int, help="调试端口（默认随机）")
@click.option("--headless/--no-headless", default=False,
              help="无头模式（默认有头；CI/无 DISPLAY 用 --headless）")
def record_cmd(start_url, out_root, settle_timeout, port, headless):
    """录制：拉起 Chromium，开始记录操作与网络请求。

    停止：页面内 Ctrl+Shift+F9 / 关闭浏览器窗口 / 终端输 q+回车
    """
    out_dir = pathlib.Path(out_root) / datetime.now().strftime("%Y%m%d-%H%M%S")
    click.echo(f"session 目录: {out_dir}")
    click.echo("停止方式：页面内 Ctrl+Shift+F9 ｜ 关闭浏览器窗口 ｜ 终端 q+回车")
    chrome = DEFAULT_CHROME
    if not chrome.exists():
        raise click.ClickException(f"chrome 未找到: {chrome}（可用 BR_CHROME 环境变量指定）")
    result = asyncio.run(record(out_dir, start_url, chrome,
                                settle_timeout=settle_timeout, port=port,
                                headless=headless))
    click.echo(f"完成：{result['events']} 事件，abnormal={result['abnormal']}")
    raise SystemExit(2 if result["abnormal"] else 0)


main.add_command(record_cmd, name="record")


@main.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False))
def export(session_dir):
    """导出 session 目录为 zip（jsonl+screenshots+PROMPT.md）。"""
    src = pathlib.Path(session_dir)
    zip_path = src.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and "chrome-profile" not in f.parts:
                z.write(f, f.relative_to(src))
    click.echo(f"导出: {zip_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 冒烟验证**

```bash
uv run browser-recorder --help && uv run browser-recorder record --help && uv run browser-recorder export --help
```

Expected: 三条帮助文本正常输出

- [ ] **Step 3: Commit**

```bash
git add projects/browser-recorder/src
git commit -m "feat(browser-recorder): cli.py——record/export 子命令"
```

---

### Task 10: PROMPT.md 模板与会话落盘

**Files:**
- Create: `projects/browser-recorder/templates/PROMPT.md.tmpl`
- Modify: `projects/browser-recorder/src/browser_recorder/recorder.py`（session_end 后写 PROMPT.md）
- Test: `projects/browser-recorder/tests/test_recorder.py`（追加断言）

**Interfaces:**
- Consumes: `record()` 的 out_dir
- Produces: 每个 session 目录落 `PROMPT.md`（模板拷贝，spec §3.2 全文）

- [ ] **Step 1: 写模板**

`templates/PROMPT.md.tmpl`（spec §3.2 逐字落盘）:

````markdown
# 任务：将本次浏览器操作录制转化为操作指引文档

## 输入
- session.jsonl —— 单时钟混排事件流（本文件所在目录）
- screenshots/ —— 双截图，文件名动作序号与 jsonl 对应，红框标记动作位置

## 你的职责
1. **步骤划分**：以 action + nav 为骨架切分步骤；连续 input 到同一表单可合并为一步
2. **动作↔请求归组**：action 之后到下一个 action 之前的 request/response 属于该步骤
   （结合 initiator 与时间邻近度微调）
3. **降噪分层**：埋点/监控/静态资源类请求 → 折叠为该步骤末尾一行摘要；
   业务请求 → 详录 method/url/关键请求参数/响应要点
4. **双截图引用**：before 展示"操作前页面"，after 展示"操作效果"；raced 的
   before 跳过不引用，改用文字描述
5. **登录态提示**：文档开头检测 session 事件中的登录流程，如有，单独一节说明
6. **输出**：写 guide.md 到本目录，人类步骤指引在前、API 逆向详情在后（两附录）

## 硬约束
- 只使用 session.jsonl 中实际存在的事件，禁止臆测未记录的请求或参数
- 敏感字段已脱敏（***），文档中保持脱敏形态，禁止尝试还原
````

- [ ] **Step 2: recorder 落盘逻辑**

`recorder.py` 收尾处（`session_end` emit 后、finally 前）追加：

```python
        import shutil
        tmpl = pathlib.Path(__file__).parent / "templates" / "PROMPT.md.tmpl"
        if not tmpl.exists():
            # wheel 安装态：shared-data 展开位置
            tmpl = pathlib.Path(__file__).parent.parent / "templates" / "PROMPT.md.tmpl"
        if tmpl.exists():
            shutil.copy(tmpl, out_dir / "PROMPT.md")
```

（源码态模板在 `projects/browser-recorder/templates/`，开发运行路径 `src/browser_recorder/../templates/`——修正查找顺序：先 `src` 同级 `templates/`，再包内。实现时以 `pathlib.Path(__file__).resolve().parent.parent / "templates"` 为第一候选。）

- [ ] **Step 3: e2e 追加断言**

`test_recorder.py` 的 `test_record_session_flow` 末尾追加：

```python
    assert (out / "PROMPT.md").exists()
    assert "操作指引" in (out / "PROMPT.md").read_text(encoding="utf-8")
```

- [ ] **Step 4: 跑全量**

```bash
uv run pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add projects/browser-recorder
git commit -m "feat(browser-recorder): PROMPT.md 模板随 session 落盘"
```

---

### Task 11: README 完整版 + 收尾验证

**Files:**
- Modify: `projects/browser-recorder/README.md`（覆盖骨架版）
- Modify: `/workspace/README.md`（能力清单表加一行）

**Interfaces:**
- Consumes: 全部前置任务

- [ ] **Step 1: 写完整 README**

````markdown
# browser-recorder

浏览器操作录制 CLI：**裸 CDP 直连**（无 Playwright/Selenium），录制真人浏览器操作 + 全量网络请求，产出 `session.jsonl`（单时钟事件流）+ 每动作双截图（红框标注）+ `PROMPT.md`（Claude Code 文档生成模板）。

## 产物结构

```
sessions/20260829-153000/
├── session.jsonl     # 操作+网络事件单时钟混排（全量、脱敏、不截断）
├── screenshots/      # NNNN-before.png / NNNN-after.png（红框=动作位置）
└── PROMPT.md         # 给 Claude Code 的文档生成指令
```

## 快速开始

```bash
cd projects/browser-recorder
uv sync
uv run browser-recorder record https://example.com
# 浏览器弹出 → 正常操作 → 停止：页面内 Ctrl+Shift+F9 / 关窗 / 终端 q+回车
uv run browser-recorder export sessions/20260829-153000   # 导出 zip
```

## 生成操作指引文档

session 目录下启动 Claude Code，直接说"按 PROMPT.md 执行"，产出 `guide.md`（人类步骤指引 + API 逆向详情两附录）。

文档质量不满意 → 改 `templates/PROMPT.md.tmpl` 重录/重生成即可，不动录制端。

## 事件流 schema（摘要）

每行 `{t_mono, kind, seq, ...}`；kind：`session_start/end`、`nav`、`action`（含 element.rect/descriptor）、`request/response/response_body`（全量 body，硬脱敏：敏感 header 只记键名、password 恒 `***`、URL token 类参数打码）、`dom_mutations`、`screenshot`（before/after + stable/timeout/raced）、`note`、`control_stop`。

## 配置

- `BR_CHROME`：浏览器二进制路径（默认 `~/.cache/ms-playwright/chromium-1208/chrome-linux/chrome`）
- `--settle-timeout`：after 截图稳定等待兜底（默认 30s，网络差的环境可再调大）
- `--headless`：无 DISPLAY 环境用

## 已知限制（spec §4）

单 tab 录制（新开标签记 note 不录）；iframe 内坐标为 frame 视口坐标；下载行为拦截不落盘；before 截图与极速跳转存在竞态（标 `raced`，descriptor 兜底）。

设计文档：`docs/2026-08-29-browser-recorder-design.md`
````

- [ ] **Step 2: 工作区 README 能力清单加行**

`/workspace/README.md` projects 表追加：

```markdown
| [browser-recorder](projects/browser-recorder) | Python `browser-recorder` | 浏览器操作录制：裸 CDP 直连 → session.jsonl + 双截图 + 文档生成模板 |
```

- [ ] **Step 3: 全量测试 + CLI 冒烟**

```bash
cd /workspace/projects/browser-recorder && uv run pytest tests/ -v
uv run browser-recorder --help
```

Expected: 全 PASS + 帮助文本正常

- [ ] **Step 4: Commit**

```bash
git add projects/browser-recorder/README.md /workspace/README.md
git commit -m "docs(browser-recorder): README 完整版 + 工作区能力清单"
```
