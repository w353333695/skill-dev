# browser-recorder 设计规格书

> 版本: 0.1.1 | 日期: 2026-08-09 | 状态: 设计中

## 1. 概述

**browser-recorder** 是一个浏览器操作录制 CLI 工具，基于 Playwright + Chromium。一键启动浏览器，自动记录用户所有交互（点击、输入、选择、弹窗、导航）、网络请求，定时截图，最终产出带时间戳标记的 Markdown 图文报告。

### 1.1 核心能力

- 记录所有 DOM 交互事件（click / input / change / submit），含时间戳、选择器、值
- 记录 URL 变化（导航、SPA 路由、hash 变化）
- 记录网络请求（XHR/Fetch，可配置过滤）
- 智能截图（前帧点击标记 + 结果帧），自适应 DOM 稳定时机
- 生成 Markdown 图文报告，步骤序号 + 分类标签
- 支持弹窗、iframe、多标签页（新增/切换/关闭）
- 默认清理临时截图，可选择保留全部过程记录
- **基于录制事件的自动化回放**（支持倍速，条件等待与人为停顿区别对待）

### 1.2 非目标（v0.1）

- 服务端部署 / Web UI
- 多浏览器并发录制
- 视频录制

---

## 2. 技术选型

| 维度 | 选择 | 理由 |
|------|------|------|
| 语言 | Python >= 3.9 | Playwright 官方一等公民；报告生成生态丰富 |
| 浏览器 | Playwright Chromium | CDP 协议最全，网络拦截/脚本注入能力强 |
| CLI 框架 | Typer | 轻量、类型安全 |
| 截图处理 | Pillow | 点击位置标记（画圈） |
| 终端展示 | Rich | 录制状态实时展示 |
| 报告格式 | Markdown | 通用可读，方便 git diff |

### 2.1 依赖

```
playwright >= 1.40
typer >= 0.9
Pillow >= 10.0
rich >= 13.0
```

---

## 3. 架构设计

### 3.1 管道式可扩展架构

```
事件流 → [注入器] → [过滤器₁..ₙ] → [处理器₁..ₙ] → Reporter → 产物
```

核心抽象（Protocol 接口）：

```python
class EventFilter(Protocol):
    """过滤/变换原始事件"""
    def process(self, event: RawEvent) -> Optional[RawEvent]: ...

class EventHandler(Protocol):
    """消费事件，产生产物"""
    async def handle(self, event: Action, page: Page) -> None: ...

class Reporter(Protocol):
    """从累积记录生成最终报告"""
    def generate(self, actions: list[Action], requests: list[RequestRecord],
                 output_dir: Path) -> Path: ...
```

内置实现：

| 角色 | 类 | 职责 |
|------|-----|------|
| Filter | `InputMergeFilter` | 合并同一 input 的连续输入事件 |
| Filter | `DedupFilter` | 去重重复事件 |
| Handler | `ScreenshotHandler` | 智能截图（前帧标记 + 结果帧） |
| Handler | `RequestHandler` | page.route() 网络请求拦截 |
| Handler | `JsonlWriter` | 增量写 events.jsonl |
| Handler | `ReplayHandler` | 读 events.jsonl 回放操作链 |
| Reporter | `MarkdownReporter` | 生成 record.md |

### 3.2 项目结构

```
projects/browser-recorder/
├── pyproject.toml
├── .python-version              # 3.9
├── src/browser_recorder/
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI 入口
│   ├── recorder.py              # 核心编排器
│   ├── replay.py                # 事件链回放引擎
│   ├── injector.py              # JS 注入 + 事件 push
│   ├── network.py               # page.route() 拦截
│   ├── screenshoter.py          # 智能截图 + Pillow 标记
│   ├── reporter.py              # Markdown 报告生成
│   ├── cleaner.py               # 临时文件清理
│   ├── filters.py               # 内置 EventFilter
│   ├── handlers.py              # 内置 EventHandler
│   └── models.py                # 数据模型
├── tests/
│   ├── conftest.py
│   ├── test_injector.py
│   ├── test_network.py
│   ├── test_recorder.py
│   ├── test_reporter.py
│   └── fixtures/
│       ├── basic.html
│       ├── dialog.html
│       ├── modal.html
│       ├── iframe.html
│       ├── shadow.html
│       ├── spa.html
│       └── multi_tab/
│           ├── opener.html      # 主页：window.open / target=_blank 触发点
│           ├── child_a.html     # 子页 A：交互 + 自关闭
│           ├── child_b.html     # 子页 B：交互 + 再开孙页
│           └── popup.html       # window.open(features) 弹窗
└── docs/
    └── 2026-08-09-browser-recorder-design.md
```

---

## 4. 数据模型

### 4.1 操作记录

```python
@dataclass
class Action:
    step: int                    # 步骤序号（全局递增）
    timestamp_ms: float          # epoch 毫秒
    tag: ActionTag               # CLICK | INPUT | CHANGE | SUBMIT | NAV | DIALOG | TAB | SHOT
    selector: str                # CSS selector 路径
    value: Optional[str]         # 输入值 / 选择值（密码脱敏）
    tag_name: str                # 元素 tag（button, input, a, select...）
    text: Optional[str]          # 元素可见文本（截断）
    url: str                     # 所在页面 URL
    page_id: str                 # 页面标识（用于多标签归属）
    frame_id: Optional[str]      # iframe 标识
    coords: Optional[tuple]      # (x, y) 点击坐标
    screenshot_before: Optional[str]  # 前帧路径（含点击标记）
    screenshot_after: Optional[str]   # 结果帧路径
```

### 4.2 网络请求

```python
@dataclass
class RequestRecord:
    timestamp_ms: float
    method: str                  # GET/POST/...
    url: str
    status: int
    duration_ms: float
    resource_type: str           # xhr/fetch/document/...
    req_headers: dict
    res_headers: dict
    req_body: Optional[str]      # 截断到 10KB
    res_body: Optional[str]      # 截断到 10KB
```

---

## 5. 核心机制详解

### 5.1 事件捕获（零遗漏）

**Push 模式：** `page.expose_function()` 暴露 Python 回调给 JS。

```
JS 注入脚本：
  每个事件 → JSON 序列化 → 放入缓冲区
  缓冲区满（10条）或 50ms 超时 → 调用 window.__recorder_push__(batch)

Python 侧：
  __recorder_push__ 回调 → 经 Filter 管道 → 分发到各 Handler
```

**强制 flush 触发点：**

| 触发点 | 机制 |
|--------|------|
| `page.on('framenavigated')` | 旧页面 flush 后导航 |
| `page.on('close')` | 页面前 flush |
| `context.on('close')` | 上下文前 flush |
| 注入脚本 `beforeunload` | 页面卸载前 flush |
| 录制停止 (Ctrl+C) | 最终 flush |

**增量落盘：** JsonlWriter 每 N 条事件 append 写入 `events.jsonl`，进程崩溃不丢已记录数据。

### 5.2 网络请求拦截（零遗漏）

```python
page = await context.new_page()
await page.route("**/*", handle_request)  # ① 先挂
await page.goto(url)                       # ② 后导航
```

`page.route()` 覆盖所有帧、所有标签页、所有重定向。默认过滤：

- 记录：`resource_type in ('xhr', 'fetch', 'document')`
- 忽略：`image, script, stylesheet, font, media, websocket, other`
- `--req-all` 覆盖，记录一切
- `--req-filter "*.api.example.com/*"` 自定义 glob

### 5.3 智能截图

**双帧策略：前帧标记 + 结果帧**

```
Step N 的截图时机：
  前帧 = Step N-1 的结果帧（即操作前的页面）
        → Pillow 在图上画红色圆圈标记点击坐标
        → 输出: screenshots/step_N_click.jpg
  结果帧 = DOM 稳定后的全页面截图
        → 输出: screenshots/step_N_result.jpg

Step 1 (NAV)：无前帧，仅结果帧
纯 INPUT 步骤：不单独截图，归属到最近的交互型步骤
```

**DOM 稳定检测（注入脚本）：**

```
用户 click →
  ① 记录事件（push）
  ② 启动 MutationObserver
  ③ 连续 300ms 无 mutation → notify Python "ready"
  ④ 附带 mutation 摘要（增/删/改节点数）

最多等待 5s → 超时强制截

导航期间（framenavigated 触发）：
  → 取消当前等待中的 observer
  → 等 networkidle → 截新页面
```

**兜底定时截图：**

- 独立 asyncio 定时器，30s（可配）无事件 → 截一张 `[SHOT]`
- 连续截图去重：间隔 < 1s 且页面无变化 → 跳过

### 5.4 多标签页管理

```
context.on('page') → 新 tab 诞生
  → 注入录制脚本
  → 挂 page.route()
  → 监听 page 事件
  → 分配唯一 page_id

每个 Action 携带 page_id，时间线中按 page_id 区分归属

标签关闭：
  page.on('close') → flush 事件 → 标记 TAB_CLOSE → 移除 page 引用
  其他页面不受影响，继续录制

切回已存在的标签：
  事件自然归属到对应的 page_id（page 引用未变）
```

### 5.5 弹窗处理

| 类型 | 处理 |
|------|------|
| `alert/confirm/prompt` | `page.on('dialog')` → 记录类型+消息 → 自动 accept/dismiss → DIALOG 事件 |
| JS 自定义模态框 | 注入脚本的 click 监听已覆盖（模态框上的元素点击同样是 DOM 事件） |

### 5.6 iframe 处理

| 类型 | 处理 |
|------|------|
| 同源 iframe | `page.on('frameattached')` + 初始化时遍历 `page.frames` → 注入脚本到每个 frame |
| 跨域 iframe | 注入受限 → 降级：仅记录 frame 导航 URL + 尺寸 |

### 5.7 Shadow DOM

注入脚本使用 `event.composedPath()` 穿透 shadow root，生成完整 CSS selector 路径。

### 5.8 SPA 路由变化

注入脚本监听 `popstate` + `hashchange`，变化时 push NAV 事件。

### 5.9 事件回放

回放基于录制产出的 `events.jsonl`，读入 Action 序列后在新浏览器上下文中自动执行。

**核心机制：区分两种等待**

| 等待类型 | 来源 | 倍速影响 |
|----------|------|----------|
| **条件等待** | 等元素可见、等 networkidle、等 DOM 稳定 | **不加速**，等到条件满足为止（有超时） |
| **人为停顿** | 操作间自然间隔（打字、阅读停顿） | **按倍速缩放** |

```
回放伪代码：
  for each action:
      case NAV:     page.goto(url) → wait networkidle
      case CLICK:   wait selector visible → page.click(selector)
      case INPUT:   page.fill(selector, value)
      ...

      人为停顿 = 录制时间间隔 - 上一步条件等待耗时
      sleep(人为停顿 / speed)
```

**回放时的截图与报告：** 回放过程中同样运行 ScreenshotHandler + RequestHandler，每次回放产出独立的 markdown 报告。回放产物的 step 编号后缀 `(R)` 标记为回放步骤。

**多标签页回放：** `events.jsonl` 中每条 Action 已携带 `page_id`，回放时按同样顺序在对应 page 上执行，支持跨标签操作链的完整还原。新标签页的出现（如 `window.open`）在回放时会自然触发 `context.on('page')`，回放引擎接管新页面继续执行该 `page_id` 的后续事件。

注入脚本监听 `popstate` + `hashchange`，变化时 push NAV 事件。

---

## 6. CLI 接口

```bash
recorder start --url URL [OPTIONS]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--url` | str | (必填) | 起始 URL |
| `--output` | Path | `./record-<timestamp>` | 输出目录 |
| `--interval` | int | 30 | 兜底截图间隔（秒） |
| `--req-all` | flag | False | 记录所有请求 |
| `--req-filter` | str | None | 请求过滤 glob |
| `--keep-all` | flag | False | 保留全部过程文件 |
| `--max-duration` | int | 0(不限) | 最大录制时长（秒） |
| `--plugin` | Path | None | 加载自定义 handler 模块 |

**子命令：**

```bash
recorder doctor    # 检查环境（chromium 是否安装）
recorder replay    # 回放录制的事件链
recorder version   # 版本号
```

### 6.1 replay 子命令

```bash
recorder replay <events.jsonl> [OPTIONS]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `EVENTS` | Path | (必填) | 录制的 events.jsonl 文件路径 |
| `--speed` | float | 1.0 | 人为停顿的倍速（条件等待不加速） |
| `--repeat` | int | 1 | 重复回放次数 |
| `--output` | Path | 自动 | 输出目录（默认 events.jsonl 旁 `-replay<N>`） |
| `--keep-all` | flag | False | 保留回放的全部过程文件 |

---

## 7. 报告格式

### 7.1 输出目录结构

```
record-20260809_143025/
├── record.md         ← 主报告（默认保留）
├── requests.json     ← 关键请求记录（默认保留）
└── screenshots/      ← 截图（默认清理）
    ├── step_001_result.jpg
    ├── step_002_click.jpg
    ├── step_002_result.jpg
    └── ...
```

`--keep-all` 时额外保留：
```
├── events.jsonl          ← 全部原始事件
├── requests_full.json    ← 完整请求记录（含静态资源）
└── screenshots/          ← 不删除
```

### 7.2 record.md 格式

```markdown
# 录制报告 — example.com
> **开始**: 2026-08-09 14:30:25 | **时长**: 5m32s | **步骤**: 23 | **请求**: 15

---

## [Step 1] [NAV] 00:00.000 | page:main
导航到 https://example.com
![step_001](screenshots/step_001_result.jpg)

## [Step 2] [CLICK] 00:02.150 | page:main
点击 `#login-btn` "登录"

点击位置：
<img src="screenshots/step_002_click.jpg" width="300"/>
操作结果：
<img src="screenshots/step_002_result.jpg" width="100%"/>

## [Step 3] [INPUT] 00:05.320 | page:main
输入 `#username` = "admin"

## [Step 4] [TAB] 00:10.500 | page:child_0
切换到新标签页 #child_0: https://example.com/dashboard

---

## 网络请求记录

| # | 时间 | 方法 | URL | 状态 | 耗时 |
|---|------|------|-----|------|------|
| 1 | 00:01.2 | GET | /api/config | 200 | 85ms |
| 2 | 00:02.8 | POST | /api/login | 200 | 320ms |
```

---

## 8. 清理策略

```
默认（录制结束时）：
  ✓ 保留: record.md, requests.json
  ✗ 清理: screenshots/ 整个目录

--keep-all：
  ✓ 保留: 所有文件
```

---

## 9. 错误处理

| 场景 | 策略 |
|------|------|
| Chromium 未安装 | 提示 `recorder doctor` 自动安装 |
| 页面崩溃/关闭 | flush 已有数据 + 标记异常结束 + 不崩溃 |
| 注入脚本失败（极端 CSP） | 降级：仅记录 URL 变化 + 网络请求 |
| 截图失败（页面已关闭） | 跳过该帧，markdown 标记 `(截图不可用)` |
| 请求 body 过大 | 截断到 10KB，标记 `[truncated]` |
| 磁盘不足 | 告警 + 停止截图，继续记录事件 |

---

## 10. 测试策略

### 10.1 测试矩阵

| 模块 | 类型 | 内容 |
|------|------|------|
| injector | 单元 | JS 注入脚本的事件捕获正确性 |
| network | 单元 | 请求过滤、全量、自定义过滤 |
| reporter | 单元 | Markdown 生成格式校验 |
| recorder | 集成 | 端到端，Playwright + 本地 HTTP server |

### 10.2 多标签页专项（重点）

| 场景 | 操作 | 断言 |
|------|------|------|
| window.open 开子页 | 主页 click → 子页 NAV + 交互 | 子页事件 page_id = 子页 |
| target=_blank 点击 | 同上 | 同上 |
| 主页→子页→切回主页 | 切回后 click | 主页事件 page_id = 主页，时间戳晚于子页事件 |
| 子页 A→子页 B 切换 | 跨子页操作 | 各自 page_id 正确 |
| 快速切换（1s×3） | stress | 无串号 |
| 关闭子页，主页继续 | 子页 close → 主页操作 | 子页 close 已记录，主页后续正常 |
| 关闭主页，子页继续 | 主页 close | 子页正常或优雅结束，不崩溃 |
| 全关 | 逐一关闭 | 报告完整，事件不丢 |
| 开 3 子页，各操作，逐一关 | 三级链条 | 各级 page_id 正确 |
| 孙页 (子页内 window.open) | 三级页面 | 三级 page_id 正确 |

### 10.3 测试 fixture 服务器

测试用 `http.server` 启动本地 fixtures 目录，Playwright 连接。fixture HTML 覆盖所有交互类型和边界场景。

---

## 11. 未来扩展（不在 v0.1）

通过插件接口可扩展：

- **WebSocketHandler** — 实时上报到服务端
- **CodegenReporter** — 导出 Playwright 测试代码
- **VideoHandler** — 视频录制

---

## 12. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-09 | 0.1.0 | 初始设计规格 |
| 2026-08-09 | 0.1.1 | 新增 `recorder replay` 回放能力：条件等待/人为停顿区分 + 倍速 + 重复回放 + 回放生成独立报告 |
