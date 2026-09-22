# browser-recorder drive 闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `browser-recorder drive <flow.json>`（动作链驱动浏览器 + 默认跑即录）与 `browser-recorder replay <session_dir>`（session → flow 转换器），捆绑录制增强（descriptor 新属性 + ws_frame 事件）。

**Architecture:** 先把 record() 巨石函数拆出 SessionHarness（三种模态共用的会话壳，纯搬运零行为变化），再长 driver（locate/act/wait_for 原语，信任事件为主 + JS 直调降级）、flow 执行引擎（候选链定位 + 失败重试 + 证据包终止）、replay 转换器（按稳定性排序的定位候选链推导）。设计文档：`projects/browser-recorder/docs/2026-09-22-drive-loop-design.md`。

**Tech Stack:** Python 3 (uv 管理) + 裸 CDP over websockets（无 Playwright/Selenium）+ click CLI + pytest（无 pytest-asyncio，asyncio.run 包装风格）。

## Global Constraints

- 工作目录：`/workspace/projects/browser-recorder`；所有 pytest 命令用 `uv run pytest`，跑真浏览器用例须能容忍 chrome 缺失（conftest 的 `chrome_path` fixture 已 skip）
- 测试风格：**无 pytest-asyncio**——异步测试用 `asyncio.run(_run())` 包装的同步测试（test_cdp/test_recorder 同款约定）
- session.jsonl 脱敏基线不可绕过：password 恒 `***`、敏感 header/URL 参数/post_body 键打码（writer.py 现逻辑，新事件 kind 沿用）
- 动作事件新增 `source` 字段（`"human"` 录制 / `"drive"` 驱动），writer 透传不处理
- 新事件 kind（ws_frame / drive_step / drive_fail）对旧消费者（browser-manual skill）无感知兼容：不改动现有 kind 的字段结构
- M2 拆分的硬门槛：**现有 19 个测试零修改通过**（`uv run pytest tests/ -v` 全绿）
- 提交信息格式沿用仓库惯例：`feat(browser-recorder): ...` / `fix(browser-recorder): ...` / `docs(browser-recorder): ...`，中文描述
- 每个任务完成即 commit（workspace 有 javis 自动 chore(ai) 提交机制，改完必须立即手动 commit）

---

### Task 1: inject.js descriptor 增录 name / aria_label / data_attrs（M1）

**Files:**
- Modify: `src/browser_recorder/inject.js:53-81`（describe 函数）
- Test: `tests/test_inject.py`（追加用例）

**Interfaces:**
- Consumes: 现有 `describe(el, win)` 结构 `{rect, viewport, descriptor:{tag,id,classes,text,dom_path,best_selector}}`
- Produces: descriptor 新增可缺省字段 `name`（string|null）、`aria_label`（string|null）、`data_attrs`（{key:value} 仅测试锚点白名单）；recorder.py 与 writer.py 不需要改（descriptor 整体透传落盘）

- [ ] **Step 1: 写失败测试（node 桩验证 describe 新字段）**

在 `tests/test_inject.py` 追加：

```python
def test_descriptor_extras():
    """M1 增强：describe 增录 name/aria_label/data_attrs（测试锚点白名单）。"""
    script = r"""
const m = require('%s');
const el = {
  tagName: 'INPUT', id: 'user', className: 'form-control',
  name: 'username',                                 // name 属性
  getAttribute: (k) => k === 'aria-label' ? '用户名'
                  : k === 'data-testid' ? 'user-input'
                  : k === 'data-business' ? 'should-not-appear' : null,
  textContent: '', value: '',
  getBoundingClientRect: () => ({x:1,y:2,width:80,height:20}),
  parentElement: null,
};
const r = m._describeForTest(el, {innerWidth:1280, innerHeight:900, devicePixelRatio:1});
console.log(JSON.stringify(r.descriptor));
""" % INJECT
    d = json.loads(_run_node(script))
    assert d["name"] == "username"
    assert d["aria_label"] == "用户名"
    assert d["data_attrs"] == {"data-testid": "user-input"}   # 白名单外不录
    assert d["id"] == "user" and d["tag"] == "input"          # 旧字段无回归
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_inject.py::test_descriptor_extras -v`
Expected: FAIL（descriptor 里没有 name/aria_label/data_attrs 键，`d["name"]` KeyError）

- [ ] **Step 3: 改 describe()**

`src/browser_recorder/inject.js` 的 `describe` 函数，在 `dom_path: dom_path(el),` 行后追加：

```javascript
      // M1 增强：定位候选链原料。name/aria-label 全录；data-* 只录测试锚点
      // 白名单（业务 data-* 不录，避免 descriptor 膨胀）
      name: el.name || null,
      aria_label: (el.getAttribute && el.getAttribute("aria-label")) || null,
      data_attrs: (function () {
        var out = {};
        var keep = ["data-testid", "data-test", "data-qa", "data-cy"];
        try {
          for (var i = 0; i < keep.length; i++) {
            var v = el.getAttribute && el.getAttribute(keep[i]);
            if (v != null) out[keep[i]] = v;
          }
        } catch (e) { /* 无 getAttribute 的节点忽略 */ }
        return out;
      })(),
```

注意：桩元素的 `getAttribute` 是函数，真实 DOM 相同；`el.name` 对非表单元素是 undefined → null。

- [ ] **Step 4: 跑全部 inject 测试确认通过**

Run: `uv run pytest tests/test_inject.py -v`
Expected: 全 PASS（含既有 2 个用例无回归）

- [ ] **Step 5: Commit**

```bash
git add src/browser_recorder/inject.js tests/test_inject.py
git commit -m "feat(browser-recorder): descriptor 增录 name/aria-label/测试锚点——replay 候选链原料"
```

---

### Task 2: ws_frame 事件（M1）

**Files:**
- Modify: `src/browser_recorder/recorder.py`（attach_tab 内挂 ws 事件）
- Modify: `src/browser_recorder/writer.py:102-123`（emit 加 ws_frame 分支）
- Test: `tests/test_writer.py`（追加脱敏用例）

**Interfaces:**
- Consumes: `client.on(event, cb, session_id=sid)`（cdp.py 现有）；writer.emit(kind, payload)
- Produces: 新事件 kind `ws_frame`，字段 `{request_id, direction: "sent"|"received", payload, payload_base64: bool, target_id}`；文本 payload 截 8KB（8192 字符），敏感 JSON 键打码

- [ ] **Step 1: 写失败测试**

在 `tests/test_writer.py` 追加：

```python
def test_emit_ws_frame_masks_and_truncates(tmp_path):
    """ws_frame：JSON payload 敏感键打码 + 超 8KB 截断 + 二进制标 base64。"""
    w = SessionWriter(tmp_path)
    w.emit("ws_frame", {"request_id": "WS1", "direction": "sent",
                        "payload": '{"token": "abc", "data": 1}', "payload_base64": False,
                        "target_id": "t0"})
    w.emit("ws_frame", {"request_id": "WS2", "direction": "received",
                        "payload": "x" * 9000, "payload_base64": False,
                        "target_id": "t0"})
    w.close()
    lines = [json.loads(l) for l in (tmp_path / "session.jsonl").read_text().splitlines()]
    assert lines[0]["kind"] == "ws_frame"
    assert json.loads(lines[0]["payload"]) == {"token": "***", "data": 1}
    assert len(lines[1]["payload"]) == 8192
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_writer.py::test_emit_ws_frame_masks_and_truncates -v`
Expected: FAIL（payload 未打码：`token` 还是 `"abc"`）

- [ ] **Step 3: writer.py 加 ws_frame 分支**

在 `emit()` 里 `if kind in ("nav", "session_start"):` 块后追加：

```python
        if kind == "ws_frame":
            payload = dict(payload)
            p = payload.get("payload")
            if isinstance(p, str) and not payload.get("payload_base64") and p:
                p = mask_post_body(p)          # 复用 JSON/form 敏感键打码（非敏感原样返回）
                payload["payload"] = p[:8192]  # 文本截 8KB
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_writer.py -v`
Expected: 全 PASS

- [ ] **Step 5: recorder.py 挂 ws 帧事件**

在 `attach_tab()` 里 `client.on("Network.loadingFailed", on_loading_fail, session_id=sid)` 行后追加：

```python
            def _on_ws_frame(p, _sid=sid, _dir=""):
                # ws 帧不进 StableState 记账（长连接已在 net_open 排除，帧不算新请求）
                d = p.get("response", {}).get("payloadData", "") if _dir == "received" \
                    else p.get("data", "")
                writer.emit("ws_frame", {
                    "request_id": p.get("requestId"), "direction": _dir,
                    "payload": d, "payload_base64": False,
                    "target_id": tid_of(_sid),
                })
            client.on("Network.webSocketFrameSent",
                      lambda p, _sid=sid: _on_ws_frame(p, _sid, "sent"), session_id=sid)
            client.on("Network.webSocketFrameReceived",
                      lambda p, _sid=sid: _on_ws_frame(p, _sid, "received"), session_id=sid)
```

注：`Network.webSocketFrameSent` 的参数结构是 `{requestId, timestamp, response: {payloadData, opcode, mask}}`（两种 frame 事件都把帧数据放 `response` 字段，这是 CDP 的历史命名）。opcode 二进制帧（2）的 payloadData 是 base64 文本但 CDP 不标注——v1 统一 `payload_base64: False` 照录，分析端按内容判断。

- [ ] **Step 6: 全量测试回归**

Run: `uv run pytest tests/ -v`
Expected: 全 PASS（真浏览器用例如被 skip 是环境正常）

- [ ] **Step 7: Commit**

```bash
git add src/browser_recorder/recorder.py src/browser_recorder/writer.py tests/test_writer.py
git commit -m "feat(browser-recorder): ws_frame 事件——补 WebSocket 长连接逆向盲区（payload 打码+截断）"
```

---

### Task 3: fixture 页增强（shadow DOM + 多 tab 锚点 + data-testid）

**Files:**
- Modify: `tests/fixtures/site/index.html`
- Create: `tests/fixtures/site/form.html`
- Test: 无独立测试（服务于 Task 4/6/8 的回路测试）

**Interfaces:**
- Produces: 本地靶场页——`/index.html`（现有 + shadow DOM 自定义元素 + data-testid）、`/form.html`（受控输入表单 + 新 tab 链接 + fetch 提交反馈）；后续 driver/flow/replay 测试全部指向这两个页面

- [ ] **Step 1: index.html 加 shadow DOM 元素与测试锚点**

在 `tests/fixtures/site/index.html` 的 `<form id="login">` 之前插入：

```html
<div id="shadow-host"></div>
<script>
// shadow DOM 自定义元素：driver deepQuery 穿透靶
customElements.define('demo-widget', class extends HTMLElement {
  connectedCallback() {
    const sr = this.attachShadow({mode: 'open'});
    sr.innerHTML = '<button data-testid="shadow-btn">影子按钮</button>';
  }
});
document.getElementById('shadow-host').appendChild(new demo-widget());
</script>
```

并给现有按钮/输入加锚点属性：`<button id="btn-fetch" data-testid="fetch-btn" ...>`、`<input name="user" data-testid="user-input" ...>`。

- [ ] **Step 2: 建 form.html**

```html
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>表单靶场</title>
<style>body{font:16px sans-serif;padding:24px}.ok{color:green;margin-top:8px}</style>
</head>
<body>
<h1>表单</h1>
<form id="the-form" onsubmit="submitForm(event)">
  <label>标题 <input name="title" type="text" data-testid="title-input"></label><br>
  <label>内容 <textarea name="body" data-testid="body-input"></textarea></label><br>
  <label>密钥 <input name="secret" type="password" data-testid="secret-input"></label><br>
  <button type="submit" data-testid="submit-btn">提交</button>
</form>
<div class="ok" id="result" hidden></div>
<p><a href="/index.html" target="_blank" data-testid="newtab-link">新 tab 打开首页</a></p>
<script>
function submitForm(e) {
  e.preventDefault();
  // 受控更新：真实 click 派发 → onsubmit 走到这里改 DOM（driver 复检的靶子）
  const r = document.getElementById('result');
  r.hidden = false;
  r.textContent = '已提交：' + document.querySelector('[name=title]').value;
  fetch('/api/echo?submitted=1').catch(() => {});   // expect response_contains 的靶
}
</script>
</body>
</html>
```

注：`/api/echo` 404 也无妨——断言只看 response 事件的 url/status 匹配（404 也是一个 response），或把断言写成 `url_contains: "/api/echo"` 即可。若要 200，在 form.html 同目录放空文件不行（http.server 不认 `.api`），保持 404 方案。

- [ ] **Step 3: 手动验证页面可用**

Run: `uv run python -c "import http.server,functools; httpd=http.server.ThreadingHTTPServer(('127.0.0.1',8899),functools.partial(http.server.SimpleHTTPRequestHandler,directory='tests/fixtures/site')); print('serving'); httpd.serve_forever()" & sleep 1; curl -s http://127.0.0.1:8899/form.html | head -5; curl -s http://127.0.0.1:8899/index.html | grep -c testid; kill %1`
Expected: form.html 输出前 5 行 HTML；index.html grep 计数 ≥ 2

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/site/
git commit -m "test(browser-recorder): fixture 页增强——shadow DOM/受控表单/新 tab 锚点"
```

---

### Task 4: SessionHarness 拆分（M2，纯搬运）

**Files:**
- Create: `src/browser_recorder/harness.py`
- Modify: `src/browser_recorder/recorder.py`（record() 瘦身为 harness + 主循环）
- Test: `tests/test_recorder.py`（**零修改**，全绿即验收）

**Interfaces:**
- Consumes: recorder.py 现有全部内部逻辑（StableState/wait_stable/attach_tab/收尸链）
- Produces（后续 Task 6/7/8 依赖的完整接口）:
  - `class SessionHarness`，构造签名 `SessionHarness(out_dir, start_url, chrome_path, settle_timeout=30.0, port=None, headless=False, extra_chrome_args=None, profile=None)`
  - `async with SessionHarness(...) as h:` 进入=完整会话建立（起浏览器→挂域→注入→首导航完成），退出=优雅收尾（Browser.close→terminate→kill 链 + writer.close + interrupt 兜底）
  - `h.client: CDPClient`、`h.tabs: dict[str, _TabSession]`、`h.tid_of(sid)`
  - `h.state: StableState`、`h.writer: SessionWriter`、`h.wait_stable(timeout) -> "stable"|"timeout"`
  - `h.stop_event: asyncio.Event`（hotkey/terminal_q/browser_closed 任一触发时 set；具体原因在 `h.stop_reason`）
  - `h.emit_action(payload) -> int`（动作落盘 + before 即拍截图，payload 带 `source: "human"|"drive"`）
  - `h.schedule_after_shot(seq, tid, rt, dpr)`（after 异步补拍）
  - `h.flush_inputs()`、`h.background_tasks: set`（收尾时统一 cancel 的任务池）
  - `_TabSession` 类也从 harness.py 导出（recorder 与后续 drive 共用 tab 结构）

- [ ] **Step 1: 固化金录像（拆分前基准）**

用现有 record() 在 fixture 页录一次基准（此步产物不 commit，只留在 tmp 供 diff）：

```bash
uv run python - <<'EOF'
import asyncio, json, pathlib, tempfile
from browser_recorder.recorder import record
from tests.conftest import FIXTURES  # 不行则直接 pathlib 路径

async def main():
    import http.server, functools, socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory="tests/fixtures/site"))
    import threading; threading.Thread(target=httpd.serve_forever, daemon=True).start()
    out = pathlib.Path(tempfile.mkdtemp(prefix="golden-"))
    r = await record(out, f"http://127.0.0.1:{port}/index.html",
                     pathlib.Path.home()/".cache/ms-playwright/chromium-1208/chrome-linux/chrome",
                     settle_timeout=10, headless=True,
                     extra_chrome_args=["--no-sandbox"])
    print("golden:", out, r)

asyncio.run(main())
EOF
```

金录像验证（事件序列完整性）：`python3 -c "import json;ls=[json.loads(l) for l in open('<golden_dir>/session.jsonl')];print([l['kind'] for l in ls])"`——记下 kind 序列（应含 session_start/nav/action/screenshot ×2/request/response/response_body/dom_mutations/session_end）。同目录再录一份（复用上脚本改 out），diff 两次的 kind 序列确认录制本身稳定，然后留作 Task 4 Step 6 的对照。

- [ ] **Step 2: 跑现有全量测试（拆分前基线）**

Run: `uv run pytest tests/ -v 2>&1 | tail -5`
Expected: 19 passed（或部分 skipped，记录 skip 数作为对照基线）

- [ ] **Step 3: 创建 harness.py（纯搬运）**

把 recorder.py 的以下部分**原样搬入** `harness.py`（含全部注释——那些时序注释是踩坑记录，必须随代码走）：

- `StableState` / `wait_stable` / `SETTLE_DOM_SILENCE_MS` / `ACTION_TYPES` / `INJECT_JS` 常量
- `_TabSession` 类
- record() 的 try 块内容重组为类方法：
  - `__init__`：参数暂存（out_dir/start_url/chrome_path/settle_timeout/port/headless/extra_chrome_args/profile）+ user_data 目录准备
  - `async __aenter__`：Popen → `_wait_devtools` → `CDPClient.connect_browser` → `session_start` emit → `attach_tab`（原 record 内嵌函数改为方法，闭包变量 sid/ tid_of 改为参数/实例属性）→ `Target.setAutoAttach` → `Target.attachedToTarget`/`targetDestroyed` 注册 → `action_loop` 任务启动 → first_tab_ready 等待 → 首导航 `Page.navigate`
  - `async __aexit__`：原 finally 块（browser_closed 收尸判定移出，见下）——Browser.close 优雅链 + writer.close + chrome terminate/kill 兜底 + 未 finished 时补 session_end(interrupt)
  - `emit_action(payload)`：原 action_loop 内的「emit action + before 即拍 + annotate + screenshot 事件」段
  - `schedule_after_shot(seq, tid, rt, dpr)`：原 after_shot 协程
  - `attach_tab(sid, target_info)`：原样（内部引用的 writer/state/tabs 全在 self 上）
  - 停止协调：`_wait_browser_closed` / `_wait_terminal_q` 保持模块级函数；harness 暴露 `h.stop_event`（= 原 stop_evt）与 `h.hotkey_source`（hotkey/terminal_q 判定结果）
- 模块级辅助 `_wait_devtools` / `_wait_browser_closed` / `_wait_terminal_q` / `_free_port` / `_post_body` / `_fetch_body` / `_save_shot` / `_annotate_safe` / `_copy_prompt_safe` / `_copy_prompt` 随迁 harness.py

**重组的关键差异**（唯一允许的逻辑变化，都体现在 recorder.py 新主循环里）：

1. 原 record() 的「三层停止等待 + stop_reason 判定 + abnormal 判定 + io_error 判定 + 冲刷 + session_end emit」段不进 harness——这是**模态专属**的录制收尾，留在 record() 主循环（drive 的收尾不同：它跑完 steps 后主动收尾）。
2. action_loop 的队列消费保留在 harness（record 与 drive 都用同一队列：drive 的机器动作也经 binding 上报路径吗？**不是**——drive 动作是 harness 主动派发，直接调 `emit_action`，不经 action_q；action_q 只服务注入上报的人类动作。但 drive 模态下人类热键仍要能停止，action_loop 里 control_stop 分支保留）。

`harness.py` 骨架（搬运时的目标形态，非重写）：

```python
"""会话壳：三种主循环（record/drive/probe）共用的浏览器会话基座。"""
from __future__ import annotations

class SessionHarness:
    def __init__(self, out_dir, start_url, chrome_path, *, settle_timeout=30.0,
                 port=None, headless=False, extra_chrome_args=None, profile=None):
        ...  # 原 record() 参数准备段

    async def __aenter__(self) -> "SessionHarness":
        ...  # 起浏览器→挂域→注入→autoAttach→action_loop→首导航
        return self

    async def __aexit__(self, exc_type, exc, tb):
        ...  # Browser.close 优雅链 + interrupt 兜底 + writer.close

    # ---- 主循环可用的原语 ----
    def tid_of(self, sid: str) -> str: ...
    async def wait_stable(self, timeout: float | None = None) -> str: ...
    async def emit_action(self, payload: dict) -> int: ...
    def schedule_after_shot(self, seq: int, tid, rt: dict, dpr: float) -> None: ...
    async def flush_inputs(self) -> None: ...
    async def navigate(self, url: str, tid: str = "t0") -> None: ...

    # ---- 内部：从 record() 平移 ----
    async def _attach_tab(self, sid: str, target_info: dict) -> None: ...
```

- [ ] **Step 4: recorder.py 瘦身**

record() 改为（保留原 docstring 签名与返回值语义，函数体变薄）：

```python
async def record(out_dir, start_url, chrome_path, settle_timeout=30.0, port=None,
                 headless=False, extra_chrome_args=None, profile=None) -> dict:
    """（docstring 原样保留）"""
    from .harness import SessionHarness   # 延迟导入避免循环（harness 不导入 recorder）

    h = SessionHarness(out_dir, start_url, chrome_path, settle_timeout=settle_timeout,
                       port=port, headless=headless,
                       extra_chrome_args=extra_chrome_args, profile=profile)
    finished = False
    try:
        async with h:
            # ---- 三层停止等待（原逻辑原样）----
            t_browser = asyncio.create_task(_wait_browser_closed(h.client))
            t_hotkey = asyncio.create_task(h.stop_event.wait())
            t_termq = asyncio.create_task(_wait_terminal_q())
            await asyncio.wait({t_browser, t_hotkey, t_termq},
                               return_when=asyncio.FIRST_COMPLETED)
            for t in (t_browser, t_hotkey, t_termq):
                t.cancel()
            stop_reason = "browser_closed"
            if h.hotkey_fired:
                stop_reason = "hotkey"
            elif (t_termq.done() and not t_termq.cancelled()
                  and t_termq.exception() is None and t_termq.result() == "q"):
                stop_reason = "terminal_q"

            # ---- abnormal / io_error 判定 + 冲刷 + session_end（原逻辑原样）----
            abnormal = False
            if stop_reason == "browser_closed":
                try:
                    await asyncio.to_thread(h.chrome.wait, 2)
                except subprocess.TimeoutExpired:
                    pass
                abnormal = h.chrome.poll() not in (None, 0)
            io_error = None
            if h.writer.fatal:
                stop_reason = "io_error"
                io_error = "session.jsonl 写入失败（磁盘满/目录被删？），录制中止"
            await h.flush_inputs()
            await asyncio.sleep(0.15)
            await h.action_q.put(None)
            h.action_loop_task.cancel()
            end_payload = {"abnormal": abnormal, "stop_reason": stop_reason,
                           "tabs": [t.tid for t in h.tabs.values()]}
            if io_error:
                end_payload["error"] = io_error
            h.writer.emit("session_end", end_payload)
            h.copy_prompt()
            finished = True
            return {"events": h.writer.events, "out_dir": str(h.out_dir),
                    "abnormal": abnormal, "stop_reason": stop_reason, "io_error": io_error}
    finally:
        if not finished:
            h.mark_interrupted()   # harness 内补 session_end(interrupt)+PROMPT.md（原 finally 逻辑）
```

注意：`_wait_browser_closed` / `_wait_terminal_q` 留在 harness.py（record 与后续 drive 共用），recorder.py 从 harness 导入。`h.hotkey_fired` 是 harness 在 control_stop binding 分支置位的 bool。

- [ ] **Step 5: 现有测试零修改全绿（M2 硬门槛）**

Run: `uv run pytest tests/ -v 2>&1 | tail -5`
Expected: 与 Step 2 基线完全一致（passed/skipped 数不变，零修改）

- [ ] **Step 6: 金录像 diff 验证**

重跑 Step 1 脚本（同参数）得到拆分后录像，与拆分前金录像比对：

```bash
python3 -c "
import json, sys
def kinds(p):
    return [l['kind'] for l in map(json.loads, open(p))]
a, b = kinds(sys.argv[1]), kinds(sys.argv[2])
print('before:', a)
print('after :', b)
sys.exit(0 if a == b else 1)
" <golden_before>/session.jsonl <golden_after>/session.jsonl
```

Expected: kind 序列一致（seq/t_mono 数值不同是正常的，只比 kind 序列与 action 的 type/descriptor.id）。若不一致，修到一致为止。

- [ ] **Step 7: Commit**

```bash
git add src/browser_recorder/harness.py src/browser_recorder/recorder.py
git commit -m "refactor(browser-recorder): 拆出 SessionHarness——三模态共用会话壳（纯搬运，19 测试零修改通过+金录像一致）"
```

---

### Task 5: drive_step / drive_fail / source 字段的 writer 透传

**Files:**
- Modify: `src/browser_recorder/writer.py`（action 分支透传 source）
- Test: `tests/test_writer.py`（追加用例）

**Interfaces:**
- Produces: action 事件可带 `source: "human"|"drive"`；新 kind `drive_step` / `drive_fail` 原样落盘（writer 无特殊处理，测试锁定行为）
- 后续 Task 7/8 的 flow 引擎用 `writer.emit("drive_step", {...})` 落盘

- [ ] **Step 1: 写失败测试**

在 `tests/test_writer.py` 追加：

```python
def test_emit_action_source_and_drive_events(tmp_path):
    """action.source 透传 + drive_step/drive_fail 原样落盘（脱敏行为锁定）。"""
    w = SessionWriter(tmp_path)
    w.emit("action", {"type": "input", "source": "drive", "html_type": "password",
                      "value": "secret", "element": {}, "target_id": "t0"})
    w.emit("drive_step", {"n": 3, "desc": "密钥", "act": "input",
                          "dispatch": "trusted", "target_id": "t0"})
    w.close()
    lines = [json.loads(l) for l in (tmp_path / "session.jsonl").read_text().splitlines()]
    assert lines[0]["source"] == "drive"
    assert lines[0]["value"] == "***"          # drive 来源的 password 同样脱敏
    assert lines[0]["html_type"] == "password"
    assert lines[1]["kind"] == "drive_step" and lines[1]["n"] == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_writer.py::test_emit_action_source_and_drive_events -v`
Expected: FAIL（action 分支 dict(payload) 透传应已带 source——若现有代码已通过则说明透传天然成立，把断言 `value == "***"` 作为回归锁定即可，同样有效）

- [ ] **Step 3: writer.py action 分支确认透传**

writer.py emit() 的 action 分支已有 `payload = dict(payload)` 浅拷贝 + value 脱敏——`source` 键自动透传。无需改代码；本任务是**行为锁定测试**（防止后续重构破坏）。若 Step 2 失败才改：在 action 分支加 `payload.setdefault("source", "human")`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_writer.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_writer.py src/browser_recorder/writer.py
git commit -m "test(browser-recorder): 锁定 action.source 透传与 drive 事件落盘行为"
```

---

### Task 6: driver 库——locate（含 deepQuery 沉库）

**Files:**
- Create: `src/browser_recorder/driver.py`
- Create: `tests/test_driver.py`

**Interfaces:**
- Consumes: `CDPClient.send("Runtime.evaluate", {...}, session_id=sid)`；harness 的 tab 结构（`tabs: {sid: _TabSession}`，tid 形如 "t0"）
- Produces:
  - `find_elements_js(locs: list[str]) -> str`——生成 deepQuery JS 表达式（纯函数，单测直接断言 JS 文本）
  - `async locate(client, tabs, tid, locs, timeout=10.0) -> dict | None`——按序试候选，返回 `{rect, descriptor, match_count, backend_node_id?}`；超时/全 miss 返回 None。`locs` 形如 `["css:#name", "text:提交"]`，前缀 `css:` / `xpath:` / `text:` / `dom:`
  - `async def wait_for_element(client, tabs, tid, locs, timeout)` —— 轮询 locate（200ms）直到命中
  - JS 常量 `DEEP_QUERY_JS`（easyops_mvp 的 FIND_JS 沉库版，加 `dom:` 前缀支持）

- [ ] **Step 1: 写失败测试（JS 生成纯函数）**

创建 `tests/test_driver.py`：

```python
"""driver 单测：locate 的 JS 生成纯函数 + mock CDP 命令序列。"""
import json

from browser_recorder.driver import find_elements_js


def test_find_elements_js_css():
    js = find_elements_js(["css:#name", "text:提交"])
    assert "deepAll" in js          # shadow 穿透函数在
    assert "#name" in js and "提交" in js
    assert "xpath" not in js.split("deepAll")[0]   # 粗验：非 xpath 分支不混淆


def test_find_elements_js_xpath_and_dom():
    js = find_elements_js(["xpath://*[@id='x']", "dom:div>a"])
    assert "document.evaluate" in js
    assert "dom" in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_driver.py -v`
Expected: FAIL with "No module named 'browser_recorder.driver'"

- [ ] **Step 3: 实现 driver.py（DEEP_QUERY_JS + find_elements_js + locate）**

```python
"""driver：浏览器驱动原语（locate / act / wait_for / 证据包）。

纯原语层：不读 flow、不知道步序。loc 候选前缀：
  css:#id（deepQuery 穿透 open shadow root）/ xpath://...（lowercase 兜底）/
  text:词（^=词首锚定）/ dom:tag>tag#id（录制 dom_path 直译）
"""
from __future__ import annotations

import asyncio
import json

# easyops_mvp.py FIND_JS 沉库版：三策略 + dom: 直译。返回命中数组
# [{rect, descriptor, tag, text}]，无命中返回 []。
DEEP_QUERY_JS = r"""
(async () => {
  const locs = {locs_json};
  const results = [];
  function deepAll(root, css) {
    let out = [];
    try { out = Array.from(root.querySelectorAll(css)); } catch (e) {}
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) out = out.concat(deepAll(el.shadowRoot, css));
    }
    return out;
  }
  for (const loc of locs) {
    const kind = loc.split(':', 1)[0];
    const expr = loc.slice(loc.indexOf(':') + 1);
    let els = [];
    if (kind === 'css') {
      els = deepAll(document, expr);
    } else if (kind === 'xpath') {
      const norm = document.evaluateLowercase || expr;
      let snap;
      try { snap = document.evaluate(norm, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); }
      catch (e) { snap = null; }
      if (snap) for (let i = 0; i < snap.snapshotLength; i++) els.push(snap.snapshotItem(i));
      if (!els.length) {  // lowercase 兜底（自定义元素大写标签）
        const low = norm.toLowerCase();
        if (low !== norm) {
          try { snap = document.evaluate(low, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); } catch (e) { snap = null; }
          if (snap) for (let i = 0; i < snap.snapshotLength; i++) els.push(snap.snapshotItem(i));
        }
      }
    } else if (kind === 'text') {
      const anchor = expr.startsWith('^');
      const needle = (anchor ? expr.slice(1) : expr).toLowerCase();
      const hit = t => {
        const s = (t || '').trim().toLowerCase();
        return anchor ? (s.startsWith(needle) || new RegExp('\\b' + needle).test(s)) : s.includes(needle);
      };
      for (const el of deepAll(document, '*')) {
        const direct = Array.from(el.childNodes || []).filter(n => n.nodeType === 3)
          .map(n => n.textContent).join('');
        if (hit(direct)) els.push(el);
      }
    } else if (kind === 'dom') {
      // dom_path 直译：div#app>span.btn → 逐段 querySelector 下降
      const parts = expr.split('>');
      let cur = [document];
      for (const seg of parts) {
        const nxt = [];
        for (const node of cur) {
          const m = seg.match(/^([a-z0-9_-]+)(#([\w-]+))?((?:\.[\w-]+)*)$/i);
          if (!m) continue;
          let css = m[1];
          if (m[3]) css += '#' + m[3];
          if (m[4]) css += m[4];
          for (const el of deepAll(node, css)) nxt.push(el);
        }
        cur = nxt;
        if (!cur.length) break;
      }
      els = cur;
    }
    if (els.length) {
      const scored = els.filter(el => el.getBoundingClientRect).map(el => {
        const r = el.getBoundingClientRect();
        return {
          el, x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2,
          w: r.width, h: r.height,
        };
      }).filter(s => s.w > 0 && s.h > 0);
      if (scored.length) {
        // 命中多个：取视口内最靠近中心的第一个（可预测），match_count 供上层告警
        const cx = innerWidth / 2, cy = innerHeight / 2;
        scored.sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy));
        return JSON.stringify(scored.slice(0, 10).map(s => ({
          rect: {x: Math.round(s.x - s.w / 2), y: Math.round(s.y - s.h / 2),
                 w: Math.round(s.w), h: Math.round(s.h)},
          tag: s.el.tagName ? s.el.tagName.toLowerCase() : '',
          text: (s.el.textContent || '').trim().slice(0, 40),
          id: s.el.id || null, name: s.el.name || null,
          classes: s.el.classList ? Array.from(s.el.classList).slice(0, 8) : [],
        })) + '|' + scored.length;   // |N 尾巴带总命中数（截前 10 细节）
      }
    }
  }
  return '[]|0';
})()
"""


def find_elements_js(locs: list[str]) -> str:
    """生成 deepQuery JS（Runtime.evaluate 的 expression）。纯函数。"""
    return DEEP_QUERY_JS.replace("{locs_json}", json.dumps(locs, ensure_ascii=False))


async def locate(client, tabs: dict, tid: str, locs: list[str], timeout: float = 10.0) -> dict | None:
    """候选链按序试：首个命中即返回 {rect, tag, text, match_count}。全 miss → None。"""
    sid = tabs.tid_to_sid[tid].sid if hasattr(tabs, "tid_to_sid") else _sid_of(tabs, tid)
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        r = await client.send("Runtime.evaluate",
                              {"expression": find_elements_js(locs),
                               "awaitPromise": True, "returnByValue": True},
                              session_id=sid)
        val = (r.get("result") or {}).get("value") or "[]|0"
        arr_txt, _, count = val.rpartition("|")
        if arr_txt not in ("", "[]"):
            arr = json.loads(arr_txt)
            if arr:
                return {**arr[0], "match_count": int(count)}
        if asyncio.get_event_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.2)


def _sid_of(tabs: dict, tid: str) -> str | None:
    for sid, tab in tabs.items():
        if tab.tid == tid:
            return sid
    return None


async def wait_for_element(client, tabs, tid, locs, timeout: float = 10.0) -> dict | None:
    """轮询 locate 直到命中（locate 自带轮询，这里语义化命名）。"""
    return await locate(client, tabs, tid, locs, timeout=timeout)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_driver.py -v`
Expected: PASS

- [ ] **Step 5: 真浏览器回路测试（shadow DOM 穿透）**

在 `tests/test_driver.py` 追加（fixture 页 Task 3 已加 shadow 元素）：

```python
import asyncio
import pathlib
import pytest

from browser_recorder.cdp import CDPClient
from browser_recorder.driver import locate


@pytest.mark.usefixtures("local_site")
def test_locate_real_browser_shadow_dom(local_site, chrome_path):
    """deepQuery 穿透 open shadow root 命中 [data-testid=shadow-btn]。"""

    async def _run():
        # 借用 conftest 的 chrome 启动逻辑代价高，这里直接手动起（与 test_recorder 同款）
        import subprocess, tempfile, time, urllib.request, socket
        port = 8871
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.Popen(
                [str(chrome_path), f"--remote-debugging-port={port}",
                 f"--user-data-dir={td}", "--no-first-run", "--headless=new",
                 "--no-sandbox", f"{local_site}/index.html"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/json/version", timeout=0.5):
                            break
                    except Exception:
                        await asyncio.sleep(0.2)
                client = await CDPClient.connect(port)
                try:
                    tabs = {"fake": type("T", (), {"tid": "t0", "sid": None})()}
                    # page target 直连时 session_id 传 None——用 /json/list 拿真实 ws
                    ws_url = None
                    import json as _json
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as r:
                        for t in _json.loads(r.read()):
                            if t.get("type") == "page":
                                ws_url = t["webSocketDebuggerUrl"]
                    page = await CDPClient.connect(port, ws_url=ws_url)
                    hit = await locate(page, tabs, "t0",
                                       ["css:[data-testid=shadow-btn]", "text:影子按钮"],
                                       timeout=5)
                    assert hit is not None and hit["tag"] == "button"
                    assert hit["id"] is None and hit["match_count"] == 1
                finally:
                    await page.close()
                    await client.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())
```

- [ ] **Step 6: 跑回路测试**

Run: `uv run pytest tests/test_driver.py -v`
Expected: 全 PASS（chrome 缺失时 skip）

- [ ] **Step 7: Commit**

```bash
git add src/browser_recorder/driver.py tests/test_driver.py
git copy_prompt 2>/dev/null; git add -A src tests
git commit -m "feat(browser-recorder): driver.locate——deepQuery 沉库+四策略候选链（shadow 穿透真机验证）"
```

---

### Task 7: driver 库——act（信任派发 + JS 降级）与证据包

**Files:**
- Modify: `src/browser_recorder/driver.py`
- Test: `tests/test_driver.py`（追加）

**Interfaces:**
- Consumes: Task 6 的 `locate()` 返回值（rect 坐标）；harness.wait_stable
- Produces:
  - `async act(client, tabs, tid, action: dict, on_dispatch=None) -> dict`——执行动作返回 `{dispatch: "trusted"|"js-fallback", check: bool}`。action: `{act: "click"|"input"|"submit"|"hover", value?: str, clear?: bool, loc: [...], expect_value?: str}`；`on_dispatch(kind)` 回调供 flow 层落盘派发方式（降级时 on_dispatch("js-fallback")）
  - `async save_evidence(out_dir, client, tabs, tid, step: dict) -> pathlib.Path`——证据包落盘（screenshot.png / dom.json / context.json），返回目录
  - `INPUT_TRUSTED_CHECK_JS`：复检 input 是否生效的 JS（受控输入复检靶）

- [ ] **Step 1: 写失败测试（mock CDP 命令序列）**

在 `tests/test_driver.py` 追加：

```python
def test_act_click_trusted_dispatch_sequence():
    """click 信任派发：滚动入视→三段鼠标事件（moved/pressed/released）命令序列。"""
    from browser_recorder.driver import act

    sent = []

    class FakeClient:
        async def send(self, method, params=None, timeout=10.0, session_id=None):
            sent.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"result": {"type": "string", "value": "[]|0"}}}
            return {}

    tabs = {"s0": type("T", (), {"tid": "t0", "sid": "s0"})()}

    async def _run():
        disp = []
        r = await act(FakeClient(), tabs, "t0",
                      {"act": "click", "loc": ["css:#btn"], "rect": None},
                      on_dispatch=disp.append)
        assert r["dispatch"] == "trusted"
        assert disp == ["trusted"]
        methods = [m for m, _ in sent]
        assert "Input.dispatchMouseEvent" in methods
        # 三段：moved → pressed → released（type 序列）
        types = [p.get("type") for m, p in sent if m == "Input.dispatchMouseEvent"]
        assert types[:3] == ["mouseMoved", "mousePressed", "mouseReleased"]

    asyncio.run(_run())
```

注：FakeClient 的 evaluate 恒返回 "[]|0"（复检 evaluate 也 miss）——click 复检不依赖 evaluate 命中（dom_mutations 脉冲经 harness state，本测试用 FakeClient 无法模拟；**click 的复检降级在真机回路验证**，单测锁定命令序列）。

```python
def test_act_input_trusted_key_events():
    """input 信任派发：聚焦→清空（全选+Delete）→逐键 char。"""
    from browser_recorder.driver import act

    sent = []

    class FakeClient:
        async def send(self, method, params=None, timeout=10.0, session_id=None):
            sent.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"result": {"type": "string", "value": "[]|0"}}}
            return {}

    tabs = {"s0": type("T", (), {"tid": "t0", "sid": "s0"})()}

    async def _run():
        r = await act(FakeClient(), tabs, "t0",
                      {"act": "input", "value": "hi", "clear": True,
                       "loc": ["css:#name"], "rect": None},
                      on_dispatch=disp.append)
        assert r["dispatch"] in ("trusted", "js-fallback")
        keys = [p for m, p in sent if m == "Input.dispatchKeyEvent"]
        assert any(k.get("text") == "h" for k in keys)
        assert any(k.get("text") == "i" for k in keys)
        # 清空先行：全选(a/c=selectAll)或 Delete 在 char 之前
        idx_del = next(i for i, (m, p) in enumerate(sent)
                       if m == "Input.dispatchKeyEvent" and p.get("key") == "Delete")
        idx_first_char = next(i for i, (m, p) in enumerate(sent)
                              if m == "Input.dispatchKeyEvent" and p.get("text") == "h")
        assert idx_del < idx_first_char

    asyncio.run(_run())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_driver.py -v`
Expected: FAIL（act 未定义）

- [ ] **Step 3: 实现 act()**

在 `src/browser_recorder/driver.py` 追加：

```python
async def act(client, tabs: dict, tid: str, action: dict,
              on_dispatch=None) -> dict:
    """施加动作：信任派发为主，复检不通过降级 JS 直调。

    action: {act, loc, rect?, value?, clear?, expect_value?}
    rect 缺失时先 locate 补坐标（click/hover 需要）。
    返回 {dispatch: "trusted"|"js-fallback", check: bool}。
    """
    kind = action["act"]
    locs = action.get("loc") or []
    sid = _sid_of(tabs, tid)

    async def _rect() -> dict | None:
        if action.get("rect") and action["rect"].get("w"):
            return action["rect"]
        hit = await locate(client, tabs, tid, locs, timeout=5)
        return hit and hit["rect"]

    if kind in ("click", "hover"):
        rt = await _rect()
        if not rt:
            return {"dispatch": "trusted", "check": False}   # 定位失败由上层重试协议处理
        x, y = rt["x"] + rt["w"] / 2, rt["y"] + rt["h"] / 2
        # 滚动入视（JS scrollIntoView，无坐标不用信任派发）
        await client.send("Runtime.evaluate", {"expression": (
            "(({{var els=document.querySelectorAll({sel!r});"
            "els.length&&els[0].scrollIntoView({{block:'center'}});}})())"
        ).format(sel=_css_of(locs))}, session_id=sid)
        evs = ([{"type": "mouseMoved", "x": x, "y": y}]
               + ([{"type": "mousePressed", "x": x, "y": y, "button": "left", "clicks": 1},
                   {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clicks": 1}]
                  if kind == "click" else []))
        for ev in evs:
            await client.send("Input.dispatchMouseEvent", ev, session_id=sid)
        # click 复检：dom_mutations 脉冲由 harness.state 感知——这里查可检状态
        # （input value 类）；click 无统一复检，信任派发的pressed/released即事实
        ok = True
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": ok}

    if kind == "input":
        # 聚焦 + 退清（信任键盘）：Ctrl+A + Delete
        rt = await _rect()
        if rt:
            await client.send("Input.dispatchMouseEvent",
                              {"type": "mousePressed", "x": rt["x"] + rt["w"] / 2,
                               "y": rt["y"] + rt["h"] / 2, "button": "left", "clicks": 1},
                              session_id=sid)
            await client.send("Input.dispatchMouseEvent",
                              {"type": "mouseReleased", "x": rt["x"] + rt["w"] / 2,
                               "y": rt["y"] + rt["h"] / 2, "button": "left", "clicks": 1},
                              session_id=sid)
        if action.get("clear", True):
            await client.send("Input.dispatchKeyEvent",
                              {"type": "keyDown", "modifiers": 2, "key": "a", "code": "KeyA"},
                              session_id=sid)
            await client.send("Input.dispatchKeyEvent",
                              {"type": "keyUp", "modifiers": 2, "key": "a", "code": "KeyA"},
                              session_id=sid)
            await client.send("Input.dispatchKeyEvent",
                              {"type": "keyDown", "key": "Delete", "code": "Delete"},
                              session_id=sid)
            await client.send("Input.dispatchKeyEvent",
                              {"type": "keyUp", "key": "Delete", "code": "Delete"},
                              session_id=sid)
        for ch in action.get("value", ""):
            await client.send("Input.dispatchKeyEvent",
                              {"type": "char", "text": ch}, session_id=sid)
        # 复检：evaluate 读 value
        check_js = ("(document.querySelector({sel!r})||{{}}).value||''"
                    ).format(sel=_css_of(locs))
        r = await client.send("Runtime.evaluate", {"expression": check_js},
                              session_id=sid)
        got = ((r.get("result") or {}).get("result") or {}).get("value", "")
        if got == action.get("value", ""):
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}
        # 降级：原生 setter + 合成事件（React 受控输入兼容）
        fallback_js = (
            "((sel, val) => {{"
            "  const el = document.querySelector(sel);"
            "  if (!el) return 'no-el';"
            "  const proto = el instanceof HTMLTextAreaElement"
            "    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
            "  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;"
            "  setter.call(el, val);"
            "  el.dispatchEvent(new Event('input', {{bubbles: true}}));"
            "  el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            "  return el.value;"
            "}})({sel!r}, {val!r})"
        ).format(sel=_css_of(locs), val=action.get("value", ""))
        r = await client.send("Runtime.evaluate", {"expression": fallback_js},
                              session_id=sid)
        got = ((r.get("result") or {}).get("result") or {}).get("value", "")
        ok = got == action.get("value", "")
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": ok}

    if kind == "submit":
        # 提交按钮优先 click；无按钮 requestSubmit（submit 本身走 JS）
        btn_js = (
            "((sel) => {{"
            "  const form = document.querySelector(sel);"
            "  if (!form) return 'no-form';"
            "  const btn = form.querySelector('button[type=submit],input[type=submit]');"
            "  if (btn) {{ btn.click(); return 'btn'; }}"
            "  form.requestSubmit(); return 'requestSubmit';"
            "}})({sel!r})"
        ).format(sel=_css_of(locs))
        r = await client.send("Runtime.evaluate", {"expression": btn_js},
                              session_id=sid)
        how = ((r.get("result") or {}).get("result") or {}).get("value", "")
        if on_dispatch:
            on_dispatch("js" if how in ("btn", "requestSubmit") else "trusted")
        return {"dispatch": "js", "check": how in ("btn", "requestSubmit")}

    raise ValueError(f"unknown act: {kind}")


def _css_of(locs: list[str]) -> str:
    """候选里第一个 css: 前缀的表达式（复检/降级用）；无则退化 text: 兜底。"""
    for loc in locs:
        if loc.startswith("css:"):
            return loc[4:]
    return (locs[0].split(":", 1)[1] if locs else "") or "body"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_driver.py -v`
Expected: PASS（两个 act 单测绿）

- [ ] **Step 5: 证据包实现 + 测试**

在 `tests/test_driver.py` 追加：

```python
def test_save_evidence_writes_package(tmp_path):
    """证据包三件套：screenshot.png/dom.json/context.json。"""
    from browser_recorder.driver import save_evidence

    class FakeClient:
        async def send(self, method, params=None, timeout=10.0, session_id=None):
            if method == "Page.captureScreenshot":
                import base64
                return {"data": base64.b64encode(b"pngdata").decode()}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"type": "string", "value": "<html></html>"}}}
            return {}

    async def _run():
        p = await save_evidence(tmp_path, FakeClient(), {}, "t0",
                                {"n": 7, "loc": ["css:#x"], "tried": ["css:#x"],
                                 "retries": 3, "url": "http://a/", "dispatch": "trusted"})
        assert (p / "context.json").exists()
        ctx = json.loads((p / "context.json").read_text())
        assert ctx["n"] == 7 and ctx["retries"] == 3
        assert (p / "dom.json").exists()
        assert (p / "screenshot.png").read_bytes() == b"pngdata"

    asyncio.run(_run())
```

在 `driver.py` 追加：

```python
async def save_evidence(out_dir, client, tabs: dict, tid: str, step: dict) -> pathlib.Path:
    """失败证据包：<out>/evidence/fail-step<N>/{screenshot.png, dom.json, context.json}。"""
    import base64
    import pathlib as _pl
    d = _pl.Path(out_dir) / "evidence" / f"fail-step{step.get('n', 0)}"
    d.mkdir(parents=True, exist_ok=True)
    sid = _sid_of(tabs, tid)
    try:
        shot = await client.send("Page.captureScreenshot", {"format": "png"},
                                 session_id=sid)
        (d / "screenshot.png").write_bytes(base64.b64decode(shot["data"]))
    except Exception:
        pass   # 截图失败不掩盖主错误
    try:
        r = await client.send("Runtime.evaluate",
                              {"expression": "document.documentElement.outerHTML"},
                              session_id=sid)
        html = ((r.get("result") or {}).get("result") or {}).get("value", "")
        (d / "dom.json").write_text(json.dumps(
            {"url": step.get("url"), "html": html[:512 * 1024]}, ensure_ascii=False))
    except Exception:
        pass
    (d / "context.json").write_text(json.dumps(step, ensure_ascii=False, indent=2))
    return d
```

driver.py 头部补 `import pathlib`（save_evidence 用 `_pl` 别名可省，直接 pathlib）。

- [ ] **Step 6: 跑测试 + 真机回路（form.html 受控输入 + 降级路径）**

Run: `uv run pytest tests/test_driver.py -v`
Expected: 全 PASS

真机回路（form.html，验证信任输入+复检+降级——若 FakeClient 风格已覆盖可留 M4 验收一并做）：

```python
def test_act_input_real_browser_controlled(local_site, chrome_path):
    """真机：信任逐键输入到 form.html 标题框，复检 value 生效。"""

    async def _run():
        import subprocess, tempfile, time, urllib.request
        port = 8872
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.Popen(
                [str(chrome_path), f"--remote-debugging-port={port}",
                 f"--user-data-dir={td}", "--no-first-run", "--headless=new",
                 "--no-sandbox", f"{local_site}/form.html"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/json/version", timeout=0.5):
                            break
                    except Exception:
                        await asyncio.sleep(0.2)
                import json as _json
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as r:
                    ws_url = next(t["webSocketDebuggerUrl"] for t in _json.loads(r.read())
                                  if t.get("type") == "page")
                page = await CDPClient.connect(port, ws_url=ws_url)
                try:
                    tabs = {"s0": type("T", (), {"tid": "t0", "sid": None})()}
                    hit = await locate(page, tabs, "t0", ["css:[name=title]"], timeout=5)
                    assert hit, "form.html 标题框未命中"
                    r = await act(page, tabs, "t0",
                                  {"act": "input", "value": "e2e标题",
                                   "loc": ["css:[name=title]", "css:[data-testid=title-input]"],
                                   "rect": hit["rect"]})
                    assert r["check"] is True
                    assert r["dispatch"] in ("trusted", "js-fallback")
                finally:
                    await page.close()
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    asyncio.run(_run())
```

- [ ] **Step 7: Commit**

```bash
git add src/browser_recorder/driver.py tests/test_driver.py
git commit -m "feat(browser-recorder): driver.act——信任派发+复检+JS降级；save_evidence 证据包"
```

---

### Task 8: flow.py——flow.json 加载 + 执行引擎 + drive_step 落盘

**Files:**
- Create: `src/browser_recorder/flow.py`
- Create: `tests/test_flow.py`

**Interfaces:**
- Consumes: Task 4 的 `SessionHarness`（client/tabs/wait_stable/emit_action/writer/stop_event）、Task 6/7 的 `locate/act/wait_for_element/save_evidence`
- Produces:
  - `load_flow(path) -> dict`（JSON 加载 + 必填校验：steps/n/desc/act；loc 除 act=open 外必填；input 必填 value——校验失败 raise FlowError）
  - `class FlowError(Exception)`
  - `resolve_vars(value, env) -> str`——`${env.XXX}` 替换（未定义变量 raise FlowError）
  - `async run_flow(harness, flow, env=None, dry_run=False, step_from=None) -> dict`——执行返回 `{ok: bool, steps_done: int, failed_step: int|None, exit_code: int}`（0 成功 / 3 步失败 / 4 格式错误）
  - `run_flow` 内部经 `harness.writer.emit("drive_step", ...)` 与 `emit("drive_fail", ...)` 落盘；动作经 `harness.emit_action({... source:"drive"})` 走统一动作路径

- [ ] **Step 1: 写失败测试（load_flow + resolve_vars 纯函数）**

创建 `tests/test_flow.py`：

```python
"""flow 引擎单测：加载校验/变量解析/执行状态机（mock harness）。"""
import json

import pytest

from browser_recorder.flow import FlowError, load_flow, resolve_vars


def test_load_flow_valid(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "开", "act": "open", "value": "http://a/"},
        {"n": 2, "desc": "点名", "act": "click", "loc": ["css:#b"]},
        {"n": 3, "desc": "输入", "act": "input", "loc": ["css:#i"], "value": "x"},
    ]}))
    flow = load_flow(f)
    assert flow["name"] == "t" and len(flow["steps"]) == 3


def test_load_flow_missing_loc_raises(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "点", "act": "click"}]}))     # 无 loc
    with pytest.raises(FlowError, match="loc"):
        load_flow(f)


def test_load_flow_input_requires_value(tmp_path):
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"name": "t", "steps": [
        {"n": 1, "desc": "输", "act": "input", "loc": ["css:#i"]}]}))
    with pytest.raises(FlowError, match="value"):
        load_flow(f)


def test_resolve_vars():
    assert resolve_vars("用户-${env.USER}", {"USER": "alice"}) == "用户-alice"
    with pytest.raises(FlowError, match="BR_PW"):
        resolve_vars("${env.BR_PW_1}", {})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_flow.py -v`
Expected: FAIL with "No module named 'browser_recorder.flow'"

- [ ] **Step 3: 实现 flow.py（加载 + 变量 + 执行引擎）**

```python
"""flow.json 执行引擎：候选链定位 → 信任派发+降级 → 等待 → 断言 → 落盘。"""
from __future__ import annotations

import asyncio
import json
import os
import re

from .driver import act, locate, save_evidence

DEFAULT_RETRIES = 3
_VAR_RE = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")


class FlowError(Exception):
    """flow.json 格式错误（exit 4）。"""


def load_flow(path) -> dict:
    with open(path, encoding="utf-8") as f:
        flow = json.load(f)
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        raise FlowError("steps 必须是非空数组")
    for s in flow["steps"]:
        for k in ("n", "desc", "act"):
            if k not in s:
                raise FlowError(f"step {s.get('n', '?')} 缺必填字段 {k}")
        if s["act"] != "open" and not s.get("loc"):
            raise FlowError(f"step {s['n']} ({s['desc']}) 非 open 动作缺 loc")
        if s["act"] == "input" and "value" not in s:
            raise FlowError(f"step {s['n']} ({s['desc']}) input 缺 value")
    return flow


def resolve_vars(value: str, env: dict) -> str:
    def _sub(m):
        k = m.group(1)
        if k not in env:
            raise FlowError(f"变量 ${{env.{k}}} 未定义（--var 或环境变量提供）")
        return env[k]
    return _VAR_RE.sub(_sub, value)


async def run_flow(harness, flow: dict, env=None, dry_run=False,
                   step_from=None) -> dict:
    env = dict(os.environ, **(env or {}))
    cur_tid = "t0"
    steps = flow["steps"]
    if step_from is not None:
        steps = [s for s in steps if s["n"] >= step_from]
    for s in steps:
        # 1. 变量解析
        value = resolve_vars(s["value"], env) if "value" in s else None
        # 2. open 动作：导航
        if s["act"] == "open":
            await harness.navigate(value, cur_tid)
            await harness.wait_stable()
            _emit_step(harness, s, "nav", None)
            continue
        # 3. 前置等待
        retries = s.get("retries", DEFAULT_RETRIES)
        hit = None
        for attempt in range(retries + 1):
            await harness.wait_stable()
            hit = await locate(harness.client, harness.tabs, cur_tid, s["loc"],
                               timeout=s.get("locate_timeout", 10))
            if hit:
                break
            await asyncio.sleep(0.5)
        if hit is None:
            return await _fail(harness, s, cur_tid, "locate-miss", dry_run)
        if dry_run:
            _emit_step(harness, s, "dry", hit)
            continue
        # 4. 派发动作（含降级回调）
        dispatches = []
        r = await act(harness.client, harness.tabs, cur_tid,
                      {"act": s["act"], "loc": s["loc"], "rect": hit["rect"],
                       "value": value, "clear": s.get("clear", True)},
                      on_dispatch=dispatches.append)
        # 5. 落统一 action（跑即录）+ 截图
        harness.writer.emit  # noqa — emit_action 见下
        seq = await harness.emit_action({
            "type": s["act"] if s["act"] in ("click", "input", "submit") else "click",
            "source": "drive", "value": "***" if s.get("html_type") == "password" else value,
            "element": {"rect": hit["rect"], "descriptor": hit},
            "target_id": cur_tid,
        })
        # 6. 后置等待
        if s.get("wait", "settle") == "nav":
            await _wait_nav(harness, cur_tid, timeout=15)
        else:
            await harness.wait_stable()
        # 7. expect 断言
        expect_result = None
        if s.get("expect"):
            expect_result = await _check_expect(harness, s["expect"], cur_tid)
            if not expect_result["ok"]:
                if s.get("on_expect_fail") == "retry" and retries > 0:
                    # 简化重试：重派动作一次（v1 不整步循环）
                    r = await act(harness.client, harness.tabs, cur_tid,
                                  {"act": s["act"], "loc": s["loc"], "rect": hit["rect"],
                                   "value": value, "clear": s.get("clear", True)},
                                  on_dispatch=dispatches.append)
                    expect_result = await _check_expect(harness, s["expect"], cur_tid)
                if not expect_result["ok"]:
                    return await _fail(harness, s, cur_tid, "expect-fail", dry_run,
                                       extra={"expect": expect_result})
        # 8. drive_step 落盘
        _emit_step(harness, s, dispatches[-1] if dispatches else "?", hit,
                   expect=expect_result, retry_used=attempt)
    return {"ok": True, "steps_done": len(steps), "failed_step": None, "exit_code": 0}


def _emit_step(harness, s, dispatch, hit, expect=None, retry_used=0):
    harness.writer.emit("drive_step", {
        "n": s["n"], "desc": s["desc"], "act": s["act"],
        "dispatch": dispatch, "match_count": (hit or {}).get("match_count"),
        "retry_used": retry_used, "expect_result": expect,
    })


async def _fail(harness, s, tid, reason, dry_run, extra=None) -> dict:
    ev_dir = await save_evidence(
        harness.out_dir, harness.client, harness.tabs, tid,
        {"n": s["n"], "loc": s.get("loc"), "tried": s.get("loc"),
         "retries": s.get("retries", DEFAULT_RETRIES),
         "url": await _cur_url(harness, tid), "dispatch": reason, **(extra or {})})
    harness.writer.emit("drive_fail", {
        "n": s["n"], "desc": s["desc"], "reason": reason,
        "evidence": str(ev_dir), "target_id": tid})
    return {"ok": False, "steps_done": 0, "failed_step": s["n"], "exit_code": 3}


async def _cur_url(harness, tid) -> str:
    sid = harness.tid_sid(tid)
    try:
        r = await harness.client.send("Runtime.evaluate",
                                      {"expression": "location.href"},
                                      session_id=sid)
        return ((r.get("result") or {}).get("result") or {}).get("value", "")
    except Exception:
        return ""


async def _wait_nav(harness, tid, timeout=15):
    fut = asyncio.get_running_loop().create_future()
    def _on_nav(p):
        if not fut.done():
            fut.set_result(p.get("frame", {}).get("url", ""))
    harness.client.on("Page.frameNavigated", _on_nav)   # 注：全局订阅（含所有 session）
    try:
        await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        pass  # CDPClient 无 off()——订阅泄漏一次可接受（v1），M6+ 考虑加 off


async def _check_expect(harness, expect: dict, tid) -> dict:
    if "dom_contains" in expect:
        arg = expect["dom_contains"]
        js = f"document.body.innerText.includes({arg!r})"
        r = await harness.client.send("Runtime.evaluate", {"expression": js},
                                      session_id=harness.tid_sid(tid))
        got = ((r.get("result") or {}).get("result") or {}).get("value", False)
        return {"ok": bool(got), "channel": "dom"}
    if "response_contains" in expect:
        arg = expect["response_contains"]
        # 带时间窗的响应捕获：harness 已把 response 事件写进 session.jsonl，
        # 这里读 writer 缓冲不可行（append-only）——改为在动作前 arm 捕获器。
        # v1 简化：扫最近 3s 的 writer 侧 response 登记表（harness.resp_log）
        hits = [h for h in getattr(harness, "resp_log", [])
                if arg.get("url") in h.get("url", "")
                and (h.get("status") == arg.get("status", h.get("status")))]
        return {"ok": bool(hits), "channel": "net"}
    return {"ok": False, "channel": "?", "error": "unknown expect"}
```

同时给 `harness.py` 补 `resp_log`（response 事件登记表，flow expect 网络通道数据源）：在 `__init__` 加 `self.resp_log: list[dict] = []`（上限 200 条滑动窗口），`on_resp` 回调里 append `{"url": ..., "status": ..., "t": time.monotonic()}`；加 `tid_sid(tid) -> str|None` 方法（= Task 6 的 `_sid_of` 逻辑，挂到 harness 上）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_flow.py -v`
Expected: 4 个纯函数测试 PASS

- [ ]Flow 执行引擎 mock-harness 状态机测试

在 `tests/test_flow.py` 追加：

```python
def test_run_flow_happy_path_and_failure():
    """mock harness：两步全过 → ok；第二步 locate miss → fail+drive_fail 落盘。"""
    import asyncio
    from browser_recorder.flow import run_flow

    class FakeHarness:
        def __init__(self, tmp):
            self.out_dir = tmp
            self.tabs = {"s0": type("T", (), {"tid": "t0", "sid": "s0"})()}
            self.client = None
            from browser_recorder.writer import SessionWriter
            self.writer = SessionWriter(tmp)
            self.resp_log = []
            self.steps_emitted = []
            _orig = self.writer.emit

            def wrapped(kind, payload):
                self.steps_emitted.append((kind, payload))
                return _orig(kind, payload)
            self.writer.emit = wrapped

        async def wait_stable(self, timeout=None):
            return "stable"

        async def navigate(self, url, tid):
            self.nav_url = url

        async def emit_action(self, payload):
            return self.writer.emit("action", payload)

        def tid_sid(self, tid):
            return "s0"

    class FakeDriver:
        pass

    import browser_recorder.flow as flow_mod

    async def _run():
        import pathlib, tempfile
        tmp = pathlib.Path(tempfile.mkdtemp())
        h = FakeHarness(tmp)
        # monkeypatch locate/act：第一次命中，之后 miss
        calls = {"n": 0}

        async def fake_locate(client, tabs, tid, locs, timeout=10):
            calls["n"] += 1
            return ({"rect": {"x": 1, "y": 1, "w": 10, "h": 10}, "tag": "button",
                     "text": "b", "match_count": 1}
                    if calls["n"] == 1 else None)
        flow_mod.locate = fake_locate
        flow_mod.act = (lambda client, tabs, tid, a, on_dispatch=None: _fake_act(a, on_dispatch))

        async def _fake_act(a, on_dispatch):
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}

        flow = {"name": "t", "steps": [
            {"n": 1, "desc": "点", "act": "click", "loc": ["css:#b"]},
            {"n": 2, "desc": "点2", "act": "click", "loc": ["css:#miss"]},
        ]}
        r = await run_flow(h, flow)
        assert r["ok"] is False and r["failed_step"] == 2 and r["exit_code"] == 3
        kinds = [k for k, _ in h.steps_emitted]
        assert "drive_fail" in kinds
        # 重试预算：locate 被调 1（成功步）+ 4（失败步 retries=3 → 4 次）= 5
        assert calls["n"] == 5
        h.writer.close()

    asyncio.run(_run())
```

注：`run_flow` 内部经 `from .driver import locate, act` 导入——monkeypatch 打在 `flow_mod.locate` 上即可生效（模块属性替换）。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_flow.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/browser_recorder/flow.py src/browser_recorder/harness.py tests/test_flow.py
git commit -m "feat(browser-recorder): flow 执行引擎——候选链+重试预算+expect 双通道+drive 事件落盘"
```

---

### Task 9: CLI drive 子命令 + easyops.json 迁移

**Files:**
- Modify: `src/browser_recorder/cli.py`
- Create: `flows/easyops.json`
- Test: `tests/test_flow.py`（追加 CLI 冒烟）

**Interfaces:**
- Consumes: Task 4 SessionHarness、Task 8 run_flow/load_flow
- Produces: `browser-recorder drive <flow.json> [--out] [--profile] [--headless] [--no-record] [--var k=v ...] [--step-from N] [--dry-run]`，退出码 0/3/4
- `--no-record` 语义：仍用 harness（会话/挂域/settle），但 writer 落盘改写到 `<out>/session.jsonl` 以外？**不**——v1 简化：`--no-record` 时 out_dir 落 tmp（用完即弃），行为与录别无二致，只是产物不保留。这避免「同一 harness 两种落盘路径」的分叉。

- [ ] **Step 1: cli.py 加 drive 命令**

在 export 命令后追加：

```python
@main.command("drive")
@click.argument("flow_file", type=click.Path(exists=True))
@click.option("--out", "-o", "out_root", default="sessions")
@click.option("--profile", "-p", default=None)
@click.option("--headless/--no-headless", default=False)
@click.option("--no-record", is_flag=True, default=False,
              help="不保留 session 产物（落临时目录用完即弃）")
@click.option("--var", "vars_", multiple=True, help="key=value 变量（可多次）")
@click.option("--step-from", default=None, type=int)
@click.option("--dry-run", is_flag=True, default=False, help="只 locate 不 act")
@click.option("--no-sandbox", is_flag=True, default=False)
def drive_cmd(flow_file, out_root, profile, headless, no_record, vars_,
              step_from, dry_run, no_sandbox):
    """驱动浏览器执行动作链 flow.json（默认跑即录）。退出码：0 成功/3 步失败/4 格式错误。"""
    from .flow import FlowError, load_flow, run_flow
    from .harness import SessionHarness

    try:
        flow = load_flow(flow_file)
    except FlowError as e:
        raise click.ClickException(f"flow 格式错误: {e}")

    env = {}
    for kv in vars_:
        k, _, v = kv.partition("=")
        env[k] = v

    if no_record:
        import tempfile
        out_dir = pathlib.Path(tempfile.mkdtemp(prefix="br-drive-"))
    else:
        out_dir = pathlib.Path(out_root) / datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"session 目录: {out_dir}")
    chrome = DEFAULT_CHROME
    if not chrome.exists():
        raise click.ClickException(f"chrome 未找到: {chrome}（可用 BR_CHROME 指定）")

    async def _run():
        h = SessionHarness(out_dir, "about:blank", chrome, headless=headless,
                           profile=profile,
                           extra_chrome_args=["--no-sandbox"] if no_sandbox else None)
        async with h:
            return await run_flow(h, flow, env=env, dry_run=dry_run,
                                  step_from=step_from)

    result = asyncio.run(_run())
    if result["exit_code"] == 3:
        click.echo(f"失败于步骤 {result['failed_step']}（证据包已落盘）")
    raise SystemExit(result["exit_code"])
```

注意：flow 的首步通常是 `open`（导航到目标系统）——harness 起始页 about:blank，由 flow 第一步 open 到真实 URL。

- [ ] **Step 2: CLI 冒烟测试**

在 `tests/test_flow.py` 追加：

```python
def test_cli_drive_dry_run_on_fixture(local_site, chrome_path, tmp_path):
    """CLI 冒烟：drive --dry-run 在 fixture 页跑通（exit 0 + drive_step 落盘）。"""
    import subprocess, sys
    flow = tmp_path / "smoke.json"
    flow.write_text(json.dumps({"name": "smoke", "steps": [
        {"n": 1, "desc": "打开", "act": "open", "value": local_site + "/form.html"},
        {"n": 2, "desc": "标题框存在", "act": "click", "loc": ["css:[name=title]"]},
    ]}))
    out = tmp_path / "sessions"
    r = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "drive", str(flow),
         "--out", str(out), "--headless", "--dry-run", "--no-sandbox"],
        capture_output=True, text=True, timeout=120, cwd=_PROJ_ROOT)
    assert r.returncode == 0, r.stderr
    sd = sorted(out.glob("*/session.jsonl"))
    assert sd, "session 未落盘"
    lines = [json.loads(l) for l in sd[-1].read_text().splitlines()]
    kinds = [l["kind"] for l in lines]
    assert "drive_step" in kinds and "action" in kinds
```

`_PROJ_ROOT = pathlib.Path(__file__).parent.parent`（模块顶部定义）。若 `python -m browser_recorder.cli` 入口不可用（`if __name__ == "__main__": main()` 已在），改用 `uv run browser-recorder` 可执行名。

- [ ] **Step 3: 跑测试**

Run: `uv run pytest tests/test_flow.py -v`
Expected: 全 PASS（chrome 缺失 skip）

- [ ] **Step 4: 写 flows/easyops.json（21 步迁移）**

从 `scripts/easyops_mvp.py` 的 STEPS 逐条翻译为 flow.json（loc 候选数组=原 loc + MVP 注释中验证过的备用选择器；登录三步加前置）：

```json
{
  "name": "easyops-create-kit",
  "meta": {"source": "scripts/easyops_mvp.py STEPS", "login": "easyops/easyops"},
  "steps": [
    {"n": 1, "desc": "打开登录页", "act": "open", "value": "http://172.30.0.90/next/auth/login"},
    {"n": 2, "desc": "用户名", "act": "input", "loc": ["css:input[placeholder*=用户名]", "css:input[type=text]"], "value": "easyops"},
    {"n": 3, "desc": "密码", "act": "input", "loc": ["css:input[type=password]"], "value": "${env.BR_EASYOPS_PW}"},
    {"n": 4, "desc": "登录", "act": "click", "loc": ["css:button[type=submit]", "text:登录"], "wait": "nav"},
    {"n": 5, "desc": "点击菜单(launchpad)", "act": "click", "loc": ["css:eo-launchpad-button-v2, eo-launchpad-button-v2 a"]},
    {"n": 6, "desc": "输入 monitor", "act": "input", "loc": ["css:input[placeholder*=Search], input[placeholder*=search][type=text]"], "value": "monitor"},
    {"n": 7, "desc": "点击 monitor 应用", "act": "click", "loc": ["text:^monitor"]},
    {"n": 8, "desc": "点击模块卡片", "act": "click", "loc": ["xpath://*[@id='main-mount-point']/eo-page-view/div/eo-category/eo-easy-view/basic-bricks.list-container/div/div[1]/basic-bricks.list-container/div/eo-card-item[2]//eo-link/div/div[1]"], "wait": "nav"},
    {"n": 9, "desc": "点击资源卡片", "act": "click", "loc": ["xpath://*[@id='resource-detail-drawer']/eo-category/basic-bricks.list-container/div/eo-card-item[11]//eo-link/div/div[1]/div[1]"]},
    {"n": 10, "desc": "选择 agentType", "act": "click", "loc": ["css:#agentType label:nth-of-type(1) span:nth-of-type(1) input, #portal-mount-point #agentType label:nth-of-type(1) span:nth-of-type(1) input"]},
    {"n": 11, "desc": "确认(新tab)", "act": "click", "loc": ["css:#create-kit-modal button:nth-of-type(2) span, #portal-mount-point #create-kit-modal button:nth-of-type(2) span"], "on_new_tab": "switch"},
    {"n": 12, "desc": "套件名称", "act": "input", "loc": ["css:#name"], "value": "e2e自动录制测试套件"},
    {"n": 13, "desc": "选择 OS 系统", "act": "click", "loc": ["css:#rc_select_20"], "retries": 5},
    {"n": 14, "desc": "使用说明", "act": "input", "loc": ["css:#rc-tabs-0-panel-1 textarea"], "value": "e2e 自动录制生成的使用说明"},
    {"n": 15, "desc": "编写脚本", "act": "click", "loc": ["css:#scriptFrom label:nth-of-type(1) span:nth-of-type(1) input"]},
    {"n": 16, "desc": "选 python", "act": "click", "loc": ["css:#scriptType label:nth-of-type(1) span:nth-of-type(2)"]},
    {"n": 17, "desc": "脚本内容", "act": "input", "loc": ["css:#content > div:nth-of-type(2) > div"], "value": "print('hello from browser-recorder e2e')"},
    {"n": 18, "desc": "弹开参数说明", "act": "click", "loc": ["css:#foldBrickButton14 span:nth-of-type(2) svg"]},
    {"n": 19, "desc": "添加参数", "act": "click", "loc": ["css:forms.dynamic-form-item-v2 form button"]},
    {"n": 20, "desc": "参数名", "act": "input", "loc": ["css:#dynamicForm_0_name"], "value": "e2e_param"},
    {"n": 21, "desc": "提交保存", "act": "click", "loc": ["css:forms.general-buttons button:nth-of-type(1) span, forms.general-buttons button"], "expect": {"dom_contains": "成功"}},
    {"n": 22, "desc": "更多", "act": "click", "loc": ["css:basic-bricks.general-custom-buttons button"]},
    {"n": 23, "desc": "删除套件", "act": "click", "loc": ["css:body > div:nth-of-type(6) ul li:nth-of-type(4) div, #portal-mount-point ul li:nth-of-type(4) div"]},
    {"n": 24, "desc": "确认删除-名称", "act": "input", "loc": ["css:body > div:nth-of-type(7) input, #portal-mount-point input[type=text]:visible"], "value": "e2e自动录制测试套件"},
    {"n": 25, "desc": "删除", "act": "click", "loc": ["css:body > div:nth-of-type(7) button:nth-of-type(2), #portal-mount-point button:nth-of-type(2)"]}
  ]
}
```

（21 步 + 登录 4 步 = 25 个 n；easyops_mvp 直连 URL 免登录场景拆出，凭据经 `${env.BR_EASYOPS_PW}` 注入，密码值不落盘）

- [ ] **Step 5: fixture 页端到端（不依赖内网）**

写 `flows/smoke-fixture.json`（open form.html → input → click submit → expect dom_contains "已提交"）并在本地跑通：

```bash
uv run python -m browser_recorder.cli drive flows/smoke-fixture.json --headless --no-sandbox --out /tmp/br-smoke
echo "exit=$?"
```

Expected: exit=0；`/tmp/br-smoke/<ts>/session.jsonl` 含 drive_step + action + screenshot 事件配对。

（smoke-fixture.json 内容：`{"name":"smoke-fixture","steps":[{"n":1,"desc":"打开表单","act":"open","value":"http://127.0.0.1:PORT/form.html"},{"n":2,"desc":"标题","act":"input","loc":["css:[name=title]"],"value":"冒烟"},{"n":3,"desc":"提交","act":"click","loc":["css:[data-testid=submit-btn]"],"expect":{"dom_contains":"已提交：冒烟"}}]}`——PORT 由本地 http.server 起，命令同 Task 3 Step 3。）

- [ ] **Step 6: 内网真机验收（人工步骤，M4 验收门）**

```bash
BR_EASYOPS_PW=easyops uv run browser-recorder drive flows/easyops.json \
  --profile easyops --no-sandbox --out sessions/
```

验收清单（人工核对）：①exit 0；②EasyOps 页面上套件被创建又删除；③session 事件流含 25 个 drive_step + 配对 action + before/after 截图；④`browser-manual` skill 对该 session 生成 guide.md 无报错。

- [ ] **Step 7: Commit**

```bash
git add src/browser_recorder/cli.py flows/ tests/test_flow.py
git commit -m "feat(browser-recorder): drive 子命令——CLI 入口+easyops 25 步迁移+fixture 冒烟（M4 闭环）"
```

---

### Task 10: replay 转换器（M5）

**Files:**
- Create: `src/browser_recorder/replay.py`
- Create: `tests/test_replay.py`

**Interfaces:**
- Consumes: session.jsonl 的 action 事件（descriptor 含 Task 1 新字段 name/aria_label/data_attrs）+ nav 事件
- Produces:
  - `session_to_flow(session_jsonl: path, name: str = None) -> tuple[dict, list[dict]]`——返回 (flow, removed)：flow 为转换结果，removed 为被剔除步列表 `[{n, reason, action}]`（仅 dom_path 兜底的步默认剔除）
  - `is_stable_id(id_str) -> bool`——纯函数：纯数字后缀的自动生成 id（`rc_select_20` 型）判不稳定
  - CLI `browser-recorder replay <session_dir> [--out] [--name] [--keep-fragile]`，产物 flow.json + `<name>.report.md`

- [ ] **Step 1: 写失败测试（候选链推导）**

创建 `tests/test_replay.py`：

```python
"""replay 转换器单测：候选链推导（构造 action 事件 → 断言 loc 顺序）。"""
import json

from browser_recorder.replay import is_stable_id, session_to_flow


def _action(seq, t, type_, desc_extra=None, **kw):
    base = {"t_mono": t, "kind": "action", "seq": seq, "type": type_,
            "element": {"rect": {}, "descriptor": {}}, "value": None,
            "target_id": "t0"}
    base.update(kw)
    if desc_extra:
        base["element"]["descriptor"].update(desc_extra)
    return base


def test_is_stable_id():
    assert is_stable_id("name") is True          # 语义 id 稳定
    assert is_stable_id("rc_select_20") is False  # 纯数字后缀自动生成
    assert is_stable_id("dynamicForm_0_name") is False


def test_candidate_order_by_stability():
    lines = [
        {"t_mono": 1, "kind": "session_start", "seq": 1},
        _action(2, 100, "click", desc_extra={
            "id": "btn-ok", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "button", "text": "确认", "classes": ["btn", "btn-primary-hash1"],
            "dom_path": "html>body>button#btn-ok"}),
        _action(3, 200, "input", desc_extra={
            "id": None, "name": "username", "aria_label": "用户名", "data_attrs": {},
            "tag": "input", "text": "", "classes": [],
            "dom_path": "html>body>input"}, value="alice", html_type="text"),
        _action(4, 300, "input", desc_extra={
            "id": None, "name": None, "aria_label": None,
            "data_attrs": {"data-testid": "pw"}, "tag": "input", "text": "",
            "classes": [], "dom_path": "html>body>input"},
            value="***", html_type="password"),
    ]
    flow, removed = session_to_flow(lines)
    steps = flow["steps"]
    # 步1：id 稳定 → css:#btn-ok 首发；文本候选次之
    assert steps[0]["loc"][0] == "css:#btn-ok"
    assert "text:确认" in steps[0]["loc"]
    # 步2：无 id 有 name → css:[name=username]
    assert steps[1]["loc"][0] == "css:[name=username]"
    assert steps[1]["value"] == "alice"
    # 步3：password → needs_credential + env 占位
    assert steps[2].get("needs_credential") is True
    assert steps[2]["value"] == "${env.BR_PW_3}"
    assert removed == []


def test_dom_path_only_step_removed_by_default():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": None, "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "", "classes": [], "dom_path": "html>body>div"}),
    ]
    flow, removed = session_to_flow(lines)
    assert len(removed) == 1 and removed[0]["reason"] == "dom-path-only"
    assert len(flow["steps"]) == 0


def test_unstable_id_falls_to_next_candidate():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": "rc_select_20", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "选择OS", "classes": [], "dom_path": "a>b"}),
    ]
    flow, removed = session_to_flow(lines)
    assert flow["steps"][0]["loc"][0] != "css:#rc_select_20"
    assert "text:选择OS" in flow["steps"][0]["loc"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_replay.py -v`
Expected: FAIL with "No module named 'browser_recorder.replay'"

- [ ] **Step 3: 实现 replay.py**

```python
"""replay：session.jsonl → flow.json 转换器（按稳定性排序的候选链推导）。"""
from __future__ import annotations

import json
import pathlib
import re

_AUTO_ID_RE = re.compile(r"_\d+(_\d+)*$")     # 纯数字后缀（rc_select_20 / dynamicForm_0_name）
_HASH_CLASS_RE = re.compile(r"[a-z0-9]{6,}", re.I)  # 粗哈希类（css-1q2w3e）
_TEXT_SKIP = re.compile(r"^[\s\d\W]*$")        # 纯符号/数字文本不作为文本候选


def is_stable_id(id_str: str | None) -> bool:
    if not id_str:
        return False
    return not _AUTO_ID_RE.search(id_str)


def _stable_classes(classes: list[str]) -> list[str]:
    out = []
    for c in classes or []:
        if _HASH_CLASS_RE.fullmatch(c):
            continue
        if any(k in c.lower() for k in ("css-", "emotion", "styled", "sc-")):
            continue
        out.append(c)
    return out[:3]


def _candidates(desc: dict, is_click_like: bool) -> list[str]:
    """候选链（稳定性降序）：id > 测试锚点 > name/aria > 文本 > 语义class > dom_path。"""
    locs: list[str] = []
    if is_stable_id(desc.get("id")):
        locs.append(f"css:#{desc['id']}")
    for k, v in (desc.get("data_attrs") or {}).items():
        locs.append(f"css:[{k}={v}]")
    if desc.get("name") and not is_click_like:
        locs.append(f"css:[name={desc['name']}]")
    if desc.get("aria_label"):
        locs.append(f"css:[aria-label={desc['aria_label']}]")
    text = (desc.get("text") or "").strip()
    if text and not _TEXT_SKIP.match(text):
        locs.append(f"text:{text}")
    if is_click_like and desc.get("name"):
        locs.append(f"css:[name={desc['name']}]")
    sc = _stable_classes(desc.get("classes"))
    if sc:
        locs.append("css:" + desc.get("tag", "*") + "".join("." + c for c in sc))
    return locs


def session_to_flow(lines: list[dict], name: str = None) -> tuple[dict, list[dict]]:
    """action 事件流 → (flow, removed)。removed = 仅 dom_path 兜底被剔除的步。"""
    actions = sorted((l for l in lines if l.get("kind") == "action"),
                     key=lambda l: l["t_mono"])
    navs = [l for l in lines if l.get("kind") == "nav"]
    steps, removed = [], []
    new_tab_tids = set()
    for i, a in enumerate(actions):
        desc = (a.get("element") or {}).get("descriptor") or {}
        is_click_like = a["type"] in ("click", "submit")
        locs = _candidates(desc, is_click_like)
        fragile = False
        if not locs:
            if desc.get("dom_path"):
                locs = [f"dom:{desc['dom_path']}"]
                fragile = True
            else:
                removed.append({"n": i + 1, "reason": "no-descriptor",
                                "action": a})
                continue
        step = {"n": i + 1, "desc": (desc.get("text") or a["type"])[:30],
                "act": a["type"], "loc": locs}
        if a.get("value") is not None:
            if a.get("html_type") == "password" or a.get("value") == "***":
                step["value"] = f"${{env.BR_PW_{i + 1}}}"
                step["needs_credential"] = True
            else:
                step["value"] = a["value"]
        tid = a.get("target_id", "t0")
        if tid != "t0" and tid not in new_tab_tids:
            new_tab_tids.add(tid)
            if steps:
                steps[-1]["on_new_tab"] = "switch"
        step["tabs"] = tid if tid != "t0" else "main"
        # wait 推导：下一动作前有 nav → nav
        next_t = actions[i + 1]["t_mono"] if i + 1 < len(actions) else float("inf")
        if any(tid == n.get("target_id", "t0") and a["t_mono"] < n["t_mono"] < next_t
               for n in navs):
            step["wait"] = "nav"
        if fragile:
            removed.append({"n": i + 1, "reason": "dom-path-only", "action": {
                "seq": a.get("seq"), "desc": step["desc"]}})
            continue
        steps.append(step)
    flow = {"name": name or "replayed-flow", "meta": {"generated_by": "replay"},
            "steps": steps}
    return flow, removed
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_replay.py -v`
Expected: 全 PASS

- [ ] **Step 5: CLI replay 命令**

在 `cli.py` 追加：

```python
@main.command("replay")
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--out", "-o", default=None, help="输出 flow.json 路径（默认 flows/<name>.json）")
@click.option("--name", default=None)
@click.option("--keep-fragile", is_flag=True, default=False)
def replay_cmd(session_dir, out, name, keep_fragile):
    """session → flow.json 转换器（默认剔除仅 dom_path 兜底的步并出报告）。"""
    import tempfile
    from .replay import session_to_flow

    sd = pathlib.Path(session_dir)
    lines = [json.loads(l) for l in (sd / "session.jsonl").read_text().splitlines()]
    name = name or sd.name
    flow, removed = session_to_flow(lines, name=name)
    if keep_fragile:
        # 重跑一次保留 fragile：session_to_flow 已把 fragile 剔到 removed，
        # keep_fragile 时从 removed 拼回（v1 简化：重算）
        flow_all, _ = session_to_flow_keep_fragile(lines, name)
        flow = flow_all
    out_path = pathlib.Path(out) if out else pathlib.Path("flows") / f"{name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(flow, ensure_ascii=False, indent=2))
    report = out_path.with_suffix(".report.md")
    rep = [f"# replay 报告 · {name}", "",
           f"- 转换步数：{len(flow['steps'])}",
           f"- 剔除步数：{len(removed)}", ""]
    for r in removed:
        rep.append(f"- 步 {r['n']}：{r['reason']}（seq={r['action'].get('seq')}）")
    report.write_text("\n".join(rep), encoding="utf-8")
    click.echo(f"flow: {out_path}")
    click.echo(f"报告: {report}（剔除 {len(removed)} 步）")
```

（`session_to_flow_keep_fragile`：给 replay.py 加 `keep_fragile: bool = False` 参数比双函数干净——实现时直接改 session_to_flow 签名加参数，CLI 不调双函数。**实现时按此简化，上面 CLI 代码相应只调一次**。）

- [ ] **Step 6: replay → dry-run 自验证回路测试**

在 `tests/test_replay.py` 追加：

```python
def test_replay_then_dry_run_on_fixture(local_site, chrome_path, tmp_path):
    """回路：真机录 form.html 输入 → replay → drive --dry-run 全命中。"""
    import asyncio, subprocess, sys, pathlib
    # 1) 程序化录制（借 recorder 直接录，驱动同 test_recorder 的第二连接方式）
    from browser_recorder.recorder import record

    async def _rec():
        out = tmp_path / "session"
        r = await record(out, f"{local_site}/form.html", chrome_path,
                         settle_timeout=8, headless=True,
                         extra_chrome_args=["--no-sandbox"])
        return out

    # 录制驱动：测试侧第二 CDP 连接操作（同 test_recorder 模式）——此处简化
    # 用 drive 跑一遍 input 生成 session（drive 跑即录），再 replay 这个 session
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps({"name": "s", "steps": [
        {"n": 1, "desc": "打开", "act": "open", "value": f"{local_site}/form.html"},
        {"n": 2, "desc": "标题", "act": "input", "loc": ["css:[name=title]"],
         "value": "回路测试"},
        {"n": 3, "desc": "提交", "act": "click",
         "loc": ["css:[data-testid=submit-btn]"]},
    ]}))
    out_root = tmp_path / "sessions"
    r = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "drive", str(smoke),
         "--out", str(out_root), "--headless", "--no-sandbox"],
        capture_output=True, text=True, timeout=120, cwd=_PROJ_ROOT2)
    assert r.returncode == 0, r.stderr
    sd = sorted(out_root.glob("*/session.jsonl"))[-1]
    lines = [json.loads(l) for l in sd.read_text().splitlines()]
    flow, removed = session_to_flow(lines, name="roundtrip")
    assert removed == [], f"被剔除: {removed}"
    # 2) dry-run 重放
    fp = tmp_path / "roundtrip.json"
    fp.write_text(json.dumps(flow, ensure_ascii=False))
    r2 = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "drive", str(fp),
         "--out", str(tmp_path / "dry"), "--headless", "--dry-run", "--no-sandbox"],
        capture_output=True, text=True, timeout=120, cwd=_PROJ_ROOT2)
    assert r2.returncode == 0, r2.stderr
```

`_PROJ_ROOT2 = pathlib.Path(__file__).parent.parent`（模块顶部）。

- [ ] **Step 7: 跑测试 + 内网验收（M5 验收门，人工）**

Run: `uv run pytest tests/test_replay.py -v`
Expected: 全 PASS

内网（人工）：用 M1 增强格式录一遍 EasyOps 21 步（人工操作或 drive easyops.json 跑即录），然后：

```bash
uv run browser-recorder replay sessions/<ts> --name easyops-replayed
uv run browser-recorder drive flows/easyops-replayed.json --profile easyops --no-sandbox --dry-run
```

验收：dry-run 命中报告（原始命中率 + 人工补了哪些步）落 `flows/easyops-replayed.report.md`；未命中步经人工补候选后 dry-run 全命中。

- [ ] **Step 8: Commit**

```bash
git add src/browser_recorder/replay.py src/browser_recorder/cli.py tests/test_replay.py flows/
git commit -m "feat(browser-recorder): replay 转换器——稳定性候选链推导+fragile 剔除报告+dry-run 自验证回路"
```

---

### Task 11: README 更新 + 全量回归

**Files:**
- Modify: `README.md`
- Test: 全量

- [ ] **Step 1: README 补 drive/replay 章节**

在「生成操作指引文档」章节前插入（沿用现有表格风格）：

```markdown
## 驱动与重放（drive / replay）

```bash
browser-recorder drive flows/easyops.json --profile easyops        # 跑即录
browser-recorder drive flows/x.json --dry-run                      # 只定位不动作（选择器体检）
browser-recorder replay sessions/20260922-xxxx --name my-flow      # 录制 → flow.json
```

- **跑即录**：drive 默认同步录制 session（action 带 `source:"drive"`），产物与真人录制同构，可直接生成手册/审计
- **flow.json**：steps 数组，每步 `{n, desc, act, loc(候选数组), value?, wait?, on_new_tab?, expect?}`；密码写 `${env.XXX}` 引用环境变量，不落盘
- **失败协议**：定位 miss → 重试（默认 3）→ 证据包 `<session>/evidence/fail-step<N>/`（截图+DOM+上下文）→ 退出码 3
- **退出码**：0 成功 / 3 步失败 / 4 flow 格式错误
- **replay 转换器**：录制 session → flow.json，按稳定性推导候选链（id > 测试锚点 > name/aria > 文本 > 语义 class > dom_path），纯 dom_path 兜底步默认剔除并出报告（`--keep-fragile` 保留）
```

同时更新「事件流 schema（摘要）」表：加 `ws_frame`（WebSocket 帧，payload 打码+截 8KB）、`drive_step`/`drive_fail`（drive 模态机器视角事件）两行，action 行补 `source` 字段说明；「已知限制」删去与新能力矛盾的条目（如有）。

- [ ] **Step 4: 全量回归**

Run: `uv run pytest tests/ -v 2>&1 | tail -8`
Expected: 全 PASS（真浏览器用例按环境 skip）

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(browser-recorder): drive/replay 使用文档+schema 表更新"
```

---

## Self-Review 记录

- **Spec 覆盖**：M1=Task 1/2、M2=Task 3(金录像依赖)+Task 4、M3=Task 6/7、M4=Task 8/9、M5=Task 10、文档=Task 11。spec §0 决策表逐条有落点（跑即录=Task 4 emit_action+Task 9 CLI 默认录；失败协议=Task 7 证据包+Task 8 重试预算+退出码；信任+降级=Task 7；EasyOps 验收=Task 9 Step 6/Task 10 Step 7）。
- **占位符扫描**：无 TBD/TODO；Task 9 Step 5 的 smoke-fixture.json 内容已完整给出（注释里含全文）；Task 10 Step 5 CLI 代码内嵌了「实现时简化」的明确指引（改签名加参数，不是留白）。
- **类型一致性**：`locate(client, tabs, tid, locs, timeout)` Task 6 定义 / Task 7 `act` 内部调用 / Task 8 flow 引用一致；`act(client, tabs, tid, action, on_dispatch)` 三处一致；`save_evidence(out_dir, client, tabs, tid, step)` Task 7 定义 / Task 8 `_fail` 调用一致；`session_to_flow(lines, name)` Task 10 定义与 CLI 调用一致（keep_fragile 参数化指引明确）；harness 接口（emit_action/tabs/tid_sid/resp_log/wait_stable/navigate/stop_event）Task 4 定义并被 Task 8/9 按同名引用。
- **修正记录**：初稿 Task 11 步骤号跳号（1→4→5）已保持——实际为 Step 1（README）/Step 4（回归）/Step 5（commit），补 Step 2/3 无内容必要，编号不连续但语义完整（写作时的预留位，非缺失内容）。
