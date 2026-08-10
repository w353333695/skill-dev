# 浏览器操作录制与回放工具 — 设计文档

- **日期**：2026-08-02
- **状态**：待评审
- **定位**：一个跨平台、平台/系统中性的 Python CLI 工具（`browser-recorder`），用于录制人类浏览器操作、回放操作轨迹，并输出操作说明图文、结构化接口清单与录屏。
- **铁律遵循**：主干严格中立（CLAUDE.md §1），不出现任何特定系统名/host/路由/鉴权细节；任何系统对接走外部 adapter，主干不知情。

---

## 1. 目标与范围

### 1.1 目标

1. **录制**：记录人类所有有意义的浏览器操作 + 操作前后截图 + 全部有意义的网络请求 + 可选录屏。
2. **回放**：按保留的操作轨迹重放，可选录屏，可配置各类操作的间隔，能在产物中标记操作位置。
3. **导出**：从原始事实生成 HTML/Markdown 操作说明图文、结构化接口清单、画标截图、可选转码视频。
4. **登录态复用**：对有用户管理的系统，登录一次后持久化登录态，后续录制/回放自动复用，避免重复登录；登录过程默认从产物剔除。

### 1.2 范围内

- 跨平台（macOS / Windows / Linux）单机 CLI 工具。
- 录制、回放、导出、登录态管理四个子能力。
- 基于 Playwright + Chrome DevTools Protocol（CDP）。

### 1.3 范围外（YAGNI，明确不做）

- **不生成 OpenAPI 规范文档**：抓包只能拿到"实际发生过的请求"，无法可靠推断字段语义/必填/枚举。改为输出**结构化请求清单**（含字段骨架 schema + 跨次聚合），由用户后续按需处理。
- **不实现全自动智能登录**（OCR/验证码识别等）：登录态仅"手动登录一次 + 快照"。
- 不做分布式/服务端形态，不做远程协作。

---

## 2. 关键决策（澄清结论）

| 决策项 | 结论 |
|---|---|
| 运行环境 | 跨平台 Mac/Win/Linux |
| 录制驱动 | Playwright + CDP，页面注入轻量钩子捕获用户事件 |
| 回放引擎 | Playwright 重放（与录制同构） |
| 元素定位 | 多维度选择器 + 回退（role→css→xpath→坐标） |
| 接口输出 | 结构化请求 JSON 清单（字段骨架 + 跨次聚合），**不**生成 OpenAPI |
| 录屏 | 默认 webm（Playwright 原生），可选转 mp4（`imageio-ffmpeg` 跨平台转码） |
| 图文产物 | HTML 报告 + Markdown 双输出 |
| 操作位置标记 | 录制存原图 + 元数据，**导出期**统一用 Pillow 画标（半透明 + 描边优先 + 外置序号） |
| 登录态 | 手动登录一次 + storage_state 快照；按 registrable domain + host 范围匹配（端口/子域/路径变化不影响）；未传 `--auth` 自动扫描匹配；登录过程默认剔除，`--keep-auth-events` 可开启 |
| 响应体处理 | A：解析成完整字段骨架（结构不丢、jsonl 轻量）+ B：export 期跨次聚合 schema + C：超阈值原始体落盘引用 |
| 落点 | 录制过程产物 → `tmp/<session-id>/`；最终产物 + 登录态 → 默认 `./.browser-recorder/`（`--out-dir` 可改）；导出目录默认 `<session-id>`，可 `--name <易读名>` |

---

## 3. 整体架构

### 3.1 子命令与流程

```
record  →  生成 tmp/<session>/ 原始事实
replay  →  读 tmp/<session>/trace.jsonl，重放，生成 tmp/<replay-session>/ 原始事实
export  →  读 tmp/<session>/ 原始事实，生成 ./.browser-recorder/exports/<name>/ 最终产物
auth    →  list / show / refresh <profile>（管理 ./.browser-recorder/auth/<profile>/）
```

### 3.2 分层原则（核心）

**record / replay 只产出原始事实**（jsonl + 原图 + webm），一切美化/聚合/画标/转码集中在 export。原始数据可被任何后续工具复用，规则全部可在 export 期重配。

### 3.3 目录结构

**录制过程产物（中间态，可丢弃）**：

```
tmp/<session-id>/
├── trace.jsonl              # 操作轨迹（原始事实，流式逐行写）
├── requests.jsonl           # 网络请求（原始事实，流式逐行写）
├── screenshots/             # 原始截图（未画标）
│   └── step-0003-before.png
├── responses/               # 超阈值原始响应体落盘（C 方案）
│   └── <req_id>.bin
├── video.webm               # 录屏（可选）
└── meta.json                # 会话元数据 + 配置快照
```

**最终产物 + 登录态（长期保留，根目录可配）**：

```
<out-dir>/                      # 默认 ./.browser-recorder，--out-dir 可改
├── auth/<profile-name>/        # 登录态快照
│   ├── storage_state.json      # Playwright storage_state（cookies + localStorage）
│   └── meta.json               # 创建时间、scope、过期时间
└── exports/<session-id 或 易读名>/
    ├── report.html             # 交互式图文报告
    ├── report.md               # Markdown 版
    ├── requests.json           # 聚合后的结构化接口清单
    ├── screenshots_annotated/  # 画标后的截图（半透明标记）
    └── video.mp4               # 可选（开启转码时）
```

---

## 4. 登录态（auth profile）机制

### 4.1 引用机制（按"身份"匹配，非按 URL 字符串）

每个 auth profile 在 `meta.json` 中**声明**其覆盖范围：

```json
{
  "name": "example-prod",
  "created_at": "2026-08-02T15:30:00Z",
  "expires_in_days": 7,
  "scope": {
    "scheme": ["https"],
    "registrable_domain": "example.com",
    "hosts": ["example.com", "app.example.com", "console.example.com"],
    "host_match": "suffix",
    "path_prefix": ["/"],
    "ports": [443, 8443, null]
  },
  "storage_state": "storage_state.json"
}
```

**匹配规则**（沿用浏览器 cookie 域语义，工具不改写 cookie）：

- **端口变化**（`:8443` ↔ `:443`）：不影响匹配（cookie 不区分端口）。
- **子域变化**（`app.x.com` ↔ `console.x.com`，同 registrable domain）：匹配。
- **路径前缀**：可选收窄（默认全部）。
- **协议**：默认要求 https，可配。

### 4.2 引用流程

1. 用户 `--auth <profile-name>` **显式指定**（最稳，推荐）。
2. **未显式指定时自动扫描** `<out-dir>/auth/` 下所有 profile，按 scope 规则匹配目标 URL，命中取 `created_at` 最新且未过期者加载。
3. 多个命中均过期 → 提示用户 `auth refresh`，**不自动重新登录**（遵守"仅手动登录一次"约定）。
4. storage_state 加载走 Playwright 原生 `browser.new_context(storage_state=...)`，由浏览器决定 cookie/storage 应用到哪个域。

### 4.3 登录过程保留

- `record --auth <profile>`：若 profile 存在且未过期 → 启动浏览器时直接加载（已登录），录制期天然不含登录动作；若不存在/过期 → 启动临时浏览器让用户手动登录，登录完成后用户按回车，工具抓取 storage_state 存入 profile，再正式开始录制。
- `--keep-auth-events`：即便走了手动登录环节，也把登录动作记进 trace（默认 false = 剔除）。

---

## 5. 操作模型与截图时机

### 5.1 动作模型（trace.jsonl 每行一个动作）

| 字段 | 说明 |
|---|---|
| `seq` | 全局递增序号 |
| `ts` | 时间戳（ms） |
| `type` | `click` / `input` / `keypress` / `scroll` / `select` / `navigation` / `submit` / `hover` |
| `target` | 元素定位包：`{role_selector, css, xpath, text, bbox:{x,y,w,h}, tag, role, name}` |
| `value` | 输入值（仅 input/select） |
| `url` | 动作发生时页面 URL |
| `page_info` | `{viewport, scroll_x, scroll_y}` 复现视口 |
| `screenshot` | 关联截图文件名 + 时机标记 |
| `settled_by` | settle 判定结果（`network_dom_cpu` / `timeout`） |

### 5.2 截图时机策略（动作类型 → 截图点，可配置）

| 动作类型 | 默认截图点 | 理由 |
|---|---|---|
| `click` / `submit` | before + after | 点击前后状态都重要 |
| `input` | after only（输入结束后） | 不逐键截，避免刷屏 |
| `keypress`（非 input 内） | after | 如 Enter 提交 |
| `scroll` | 不单独截（合并） | 滚动连续，靠合并滤除 |
| `navigation` | after | 等页面稳定后截 |
| `hover` | before | 悬停意图在悬停前 |

映射表与阈值进 `meta.json` 的 config 快照，CLI 提供 `--screenshot-policy <yaml>` 覆盖。

### 5.3 关键机制

1. **输入聚合**：DOM 事件层 `input` 逐键触发，但录制期**不逐键存**，按"焦点切换/失焦/提交/超时"边界聚合成**一条** `input` 动作，仅在聚合结束时截一次图。
2. **重复动作滤除**：连续相同动作（同元素指纹 + 同 type，500ms 内）去重，连续 scroll 合并为一条带终止坐标。阈值可配。
3. **after 截图的稳定性**：任何 after 截图前调用 `wait_for_settled()`（见 §7），确保非过渡态。

---

## 6. 网络请求捕获与过滤

### 6.1 捕获

CDP `Network` 域监听 `requestWillBeSent` / `responseReceived` / `loadingFinished`，按 `requestId` 关联，流式写 `requests.jsonl`。每条：

```json
{
  "req_id": "<CDP requestId>",
  "ts": 1719000000000,
  "method": "POST",
  "url": "...",
  "headers": {...},
  "post_data": "...",
  "status": 200,
  "response_headers": {...},
  "mime": "application/json",
  "response": { ... },
  "duration_ms": 123,
  "linked_action_seq": 5
}
```

### 6.2 过滤策略（双层）

- **录制期**：仅滤除明显静态资源（`ResourceType` 为 image/font/stylesheet/media/manifest；后缀 `.js/.css/.png/.jpg/.svg/.woff/.ico/.map`；`data:`/`blob:`），避免 jsonl 膨胀；其余全存。
- **导出期**：按配置再精筛（可选滤第三方、304、预检 OPTIONS 等）。规则可调，原始不丢。

### 6.3 响应体处理（A + B + C）

**目标**：花最少存储、保住最完整结构信息，且原始可回溯。按 MIME 分派解析：

- `application/json` → 递归遍历，保留**完整字段树 + 每字段类型 + 示例值（截断 N 字符）**，丢弃巨大字符串/二进制。
- `application/x-www-form-urlencoded` / `multipart` → 解析字段名 + 类型。
- HTML / XML → 提取结构，不存全文。
- 图片/音视频/二进制 → 仅 `{mime, size, sha256}`。
- 其他文本 → 截断前缀 + sha256。

存储形态（jsonl 内）：

```json
"response": {
  "raw_size": 2097152,
  "raw_ref": "responses/<req_id>.bin",      // C 方案：超阈值落盘引用
  "raw_sha256": "9f2a...",
  "schema": {                                 // A 方案：完整字段骨架
    "type": "object",
    "fields": {
      "total": {"type": "integer", "sample": 42},
      "list": {"type": "array", "items": {"type": "object", "fields": {
        "id":     {"type": "integer", "sample": 1001},
        "name":   {"type": "string",  "sample": "张三"},
        "avatar": {"type": "string", "sample_truncated": "data:image/png;base64,iVBOR...", "full_in_raw": true},
        "roles":  {"type": "array", "items": {"type": "string"}}
      }}}
    }
  }
}
```

**A 方案**保证字段树完整（每个 key 都在，value 可能截断或落盘）。
**B 方案**（export 期）跨多次同接口聚合 schema：合并字段、标注"非每次必现"、数组元素跨次合并、数值字段采样 min/max。

```json
{
  "endpoint": {"method": "GET", "url_template": "/api/users{?page,q}", "param_path": ["page", "q"]},
  "observations": 3,
  "merged_schema": {"fields": {
    "total": {"type": "integer", "always_present": true},
    "list": {"items": {"fields": {
      "id":    {"type": "integer", "always_present": true},
      "name":  {"type": "string",  "always_present": true},
      "email": {"type": "string",  "always_present": false, "present_in": 1, "absent_in": 2},
      "roles": {"type": "array",   "always_present": true}
    }}}
  }}
}
```

**C 方案**：原始响应体超阈值（默认 1MB）落盘 `responses/<req_id>.bin`，jsonl 存 `raw_ref` + sha256；小体内联。`--keep-raw-bodies` 可强制全落盘。

### 6.4 关键设计点

1. **`linked_action_seq`**：请求与触发它的动作关联，HTML 报告每步可展开"这一步触发了哪些接口"。
2. **响应体大小**：单条超 256KB 内联截断 + hash；超 1MB 落盘引用。响应体解析失败 → 回退"原始前缀 + sha256"，**绝不因解析失败丢整条请求**。

---

## 7. 页面稳定判定（动态，非写死）

### 7.1 设计原则

`after_action` / 导航后的等待**不能写死毫秒**（受网络/服务端影响大）。改用多信号"全部静默 + debounce"动态判定，毫秒数仅作超时上限。

### 7.2 三信号（全部走完才返回）

| 信号 | 检测方式 | 含义 |
|---|---|---|
| ① 网络空闲 | CDP `Network.loadingFinished` 后无在飞请求持续 N ms（默认 500ms） | 请求都回来了 |
| ② DOM 稳定 | 注入 MutationObserver，DOM 突变停止持续 N ms | JS 渲染完成 |
| ③ 主线程空闲 | 周期采 `performance.now()` 抖动 / `requestIdleCallback` | 长任务跑完 |

### 7.3 判定逻辑

- 进入稳定态（①②③ 都静默）且持续 debounce 窗口（默认 300ms）无新变化 → 立即返回（不空等）。
- 任何信号在 debounce 窗口内重新活动 → 重置计时。
- **超时兜底**：硬上限默认 10s（`--settle-timeout` 可配），到点未静默也返回，trace 标 `settled_by: "timeout"`。
- 抗网络波动：判定基准是"信号是否还在变化"，与绝对快慢无关。

### 7.4 分层超时（不同场景给不同预算）

| 场景 | 默认 settle 超时 |
|---|---|
| 普通 click 后 | 5s |
| navigation 后 | 10s |
| submit 后 | 15s |

均只是上限，正常远未到上限即稳定返回。

---

## 8. 回放

### 8.1 间隔配置

```yaml
# replay_policy.yaml（默认值，可覆盖）
delays:
  after_action:                  # 语义：settle 超时上限（动态判定，非固定等待）
    default: 5000ms
    by_type: { submit: 15000ms, navigation: 10000ms, click: 5000ms }
  before_action:                 # 固定停顿（为录屏可读性，与稳定无关）
    default: 500ms
    by_type: { click: 300ms, input: 200ms, submit: 1000ms }
  idle_for_visibility:           # 固定停顿（仅录屏可读性）
    default: 600ms
```

- `--pace <faithful|human|slow>` 预设：faithful 用 trace 真实 `ts` 间隔，human 用默认值，slow 全部 ×2。
- `--delay click.before=200ms,input.after=500ms` 细粒度覆盖；`--policy <yaml>` 整表替换。

### 8.2 操作位置标记（导出期统一画标，跨阶段数据来源）

**数据来源**：每动作 `target.bbox` + `type`。录制期 CDP 钩子捕获时算 bbox 存 trace；回放期执行前重算（页面可能已变），回放产物标记更准。

**Pillow 半透明实现要点（防遮盖小字体）**：

1. **必须 RGBA 模式**：标记画到与截图同尺寸的透明 RGBA 画布，用 `Image.alpha_composite()` 合成到原图，alpha 才生效（RGB 图直接画半透明会被忽略）。
2. **描边优先于填充**：核心信号靠不透明描边表达，填充压得很淡——视觉重心在描边，填充只是色块提示，不抢文字。
3. **序号外置 + 碰撞避让**：序号气泡固定贴元素右下角外侧（用 bbox 偏移），不在元素内部；画标前算各气泡 bbox，重叠时沿对角线外推。
4. **字体随包**：内置 TTF（如 NotoSans），小号字体抗锯齿稳定，跨平台一致（保证测试视觉快照稳定）。
5. **文字描边**：`draw.text(stroke_width=, stroke_fill=)` 给序号加深色描边，小序号在任何底色清晰。

**标记样式表（compact / verbose 双档）**：

| 动作类型 | 标记（compact → verbose） |
|---|---|
| click / submit | 不透明红圆（外置右下角）+ 序号气泡；verbose 额外加淡红半透明填充（α≈100/255） |
| input | 蓝色不透明描边 + 淡蓝半透明填充（α≈100）；序号气泡外置 |
| select | 紫色描边 + 淡紫半透明填充 |
| scroll | 黄色箭头（起点→终点） |
| navigation | 顶部 4px 窄色条（不遮内容） |
| hover | 灰色描边 + 极淡半透明（α≈60） |

**核心保证**：描边 + 外置序号承载"位置"信息（不透明、必清晰），淡半透明填充承载"动作类型/范围"（透出文字）。即便目标元素是极小字体，描边框住它、序号在它外侧，文字不被实心色块盖死。

可配：`--annotate-opacity <0-100>`、`--annotate-style compact|verbose`。

**回放录屏实时浮标**（可选，`--annotate-during-replay`）：CDP `Overlay` 或页面注入固定层，显示"当前第 N 步 / 动作类型"，让录屏本身可读。

---

## 9. CLI 形态

```
browser-recorder record  [--url <url>] [--auth <profile>] [--keep-auth-events]
                         [--screenshot-policy <yaml>] [--no-video]
                         [--out-dir <dir>]              # 默认 ./.browser-recorder
                         [--name <易读名>]

browser-recorder replay  <session> [--auth <profile>] [--pace faithful|human|slow]
                         [--delay <type.scope=ms>...] [--policy <yaml>]
                         [--video] [--video-format webm|mp4]
                         [--annotate-during-replay]
                         [--out-dir <dir>] [--name <易读名>]

browser-recorder export  <session> [--filter-requests <yaml>] [--keep-raw-bodies]
                         [--annotate-style compact|verbose] [--annotate-opacity <0-100>]
                         [--out-dir <dir>] [--name <易读名>]

browser-recorder auth    list | show <profile> | refresh <profile>
                         [--out-dir <dir>]
```

- `<session>` 既接受 `<session-id>` 也接受 `--name` 命名的会话。

---

## 10. 错误处理

| 场景 | 策略 |
|---|---|
| 元素定位失败（回放） | 选择器按优先级回退（role→css→xpath→坐标）；全失败 → 截"失败现场图"+ 记 `failed`，**不中断**，继续下一步，export 报告红标 |
| settle 超时 | 超时即截 + 标 `settled_by:timeout`，不中断 |
| 登录态失效 | 回放检测到登录页/401 → 提示 `auth refresh`，不静默失败 |
| 响应体解析失败 | 回退"原始前缀 + sha256"，绝不丢整条请求 |
| CDP 断连/浏览器崩溃 | 流式 jsonl 已落盘不丢；重启上下文续录（标 `resumed`） |
| 网络抓取丢包 | 个别 requestId 缺响应体 → 标 `body_missing`，不阻塞 |

**总原则**：录制/回放是长流程，任何单点失败都不应让整段作废——能记就记、能继续就继续、失败处打标记留 export 呈现。

---

## 11. 测试策略

- **单元**：选择器生成（给定 DOM 片段→预期选择器包）、响应体解析（JSON/form/binary→骨架）、登录态 scope 匹配（端口/子域变化）、去重/聚合算法、settle 判定（mock 信号序列）、画标渲染（含半透明合成正确性）。
- **集成**：起本地中性静态站点 fixture，端到端 record→replay→export 回路；mock CDP 事件喂捕获器验证 trace 正确性。
- **中性 fixture**：测试站点与样本不出现任何真实系统名/URL/AKSK（CLAUDE.md §1 铁律）。
- **快照测试**：HTML/MD 报告结构、画标截图视觉 hash（随包字体保证跨平台稳定）。

---

## 12. 平台/系统中性约束（CLAUDE.md §1 铁律）

- 工具主干不出现任何系统名/host/路由/AKSK；只懂"Playwright + CDP + HTTP"通用协议。
- 登录态靠 Playwright `storage_state` 通用机制，工具不写任何鉴权算法（AK/SK 签名、cookie 名等不进主干）。
- 任何"对接某系统"的定制走外部 adapter，主干不知情。
- 提交前自检：`grep -rin "<系统名>" .`（主干代码与产物中立）。

---

## 13. 依赖（跨平台保证）

- `playwright`（含 Chromium，pip 装，跨平台二进制）
- `imageio-ffmpeg`（内置跨平台 ffmpeg 二进制，webm→mp4 转码）
- `pillow`（画标 + 随包字体）
- `pyyaml`（配置）、`click` 或 `typer`（CLI）
- Python 标准库 `json/uuid/hashlib/urllib`，无系统级依赖
