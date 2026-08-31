# browser-recorder 设计文档

- 日期：2026-08-29
- 状态：已与用户逐节确认
- 前置：同名旧项目为废案（录制手段与输出质量均未达预期），已物理删除、git 无残留，本文档为从零重建的设计，不参考旧案

## 1. 定位与交付物

**browser-recorder**：`/workspace/projects/browser-recorder/` 下的 Python 能力 project（uv 管理、独立 venv、CLI 名 `browser-recorder`），符合工作空间「能力 project + 编排 skill」两层结构。

一次录制会话产出（均在 session 目录内）：

| 产物 | 内容 |
|---|---|
| `session.jsonl` | 操作事件 + 网络事件**单时钟混排**的结构化事件流（全量、不降噪） |
| `screenshots/` | 每次动作的双截图（before/after）PNG，红框标记动作位置 |
| `PROMPT.md` | 交给 Claude Code 的文档生成指令模板 |

CLI 两条子命令（MVP 范围）：

```
browser-recorder record    # 拉起 Chromium（headed），开始录制
browser-recorder export    # 将 session 目录导出为 zip
```

**明确边界**：

- 录制端 CLI 不内置任何 LLM 调用——文档由 Claude Code 会话按 `PROMPT.md` 生成，引擎外置
- `replaysession`（重放）不做，留待二期
- 多 tab 录制不做，单 target（见 §4 #4）

**选型结论**（逐项与用户确认过）：

| 决策点 | 结论 | 关键理由 |
|---|---|---|
| 录制手段 | 裸 CDP 直连（websockets，无 Playwright） | 响应体一等公民、单时钟、无安装摩擦；扩展方案因响应体拿不到/MV3 worker 重启丢事件/分发摩擦被否 |
| 分析引擎 | LLM 后处理（Claude Code 会话即引擎） | 上次败因"输出质量不行"的核心解法；零额外接入成本 |
| 录制范围 | 任意网站 | — |
| 噪声处理 | 录制全量不筛选，LLM 生成文档时降噪分层 | session 不丢信息 |
| 录制内容 | 操作步骤 + 请求响应全量详情 + 每步双截图 + DOM 变化摘要 | 用户勾选 |
| 交付终点 | MVP：录 + 存 + 模板 | — |

## 2. 架构与数据流

### 2.1 流程

```
browser-recorder record
  1. launch Chromium（headed）开 --remote-debugging-port，CLI 作为 ws 客户端直连该端口
  2. 裸 CDP 直连（websockets 库）
  3. 并行订阅三组域：
     · Network.*   —— requestWillBeSent / responseReceived / getResponseBody
     · Page.*      —— frameNavigated + 动作后双截图
     · Runtime.*   —— 注入采集脚本，监听 click/input/submit，取目标元素描述
  4. 全部事件归一化为 {t_mono, kind, ...} 写 session.jsonl（单时钟，append-only）
  5. 停止（页面内热键 / 关浏览器 / 终端 q）→ 优雅落盘，写 PROMPT.md，会话结束
```

### 2.2 模块划分

每个文件一个职责，目标均不超过 ~200 行：

| 模块 | 职责 | 对外接口 |
|---|---|---|
| `cdp.py` | ws 连接、命令收发、事件订阅 | `CDPClient.send(cmd, **params)` / `on(event, cb)` |
| `recorder.py` | 录制编排：起浏览器、挂三域、生命周期、稳定判定 | `record(out_dir)` |
| `inject.js` | 注入页面的操作采集脚本（content script 角色） | DOM 事件 → CDP binding 上报 |
| `writer.py` | 事件归一化 + jsonl append-only 落盘 + 脱敏 | `emit(kind, payload)` |
| `annotator.py` | 截图红框标注（Pillow 后处理） | `annotate(png_path, rect, seq)` |
| `cli.py` | click 入口：record / export | — |

### 2.3 动作定位

注入脚本上报每次 click/input/submit 时附带：

```
element: {
  rect: {x, y, w, h},        # getBoundingClientRect，视口坐标
  viewport: {w, h, scrollX, scrollY, dpr},   # dpr 用于映射到截图像素
  descriptor: {tag, id, classes, text(截断), dom_path, best_selector}
}
```

截图中标记动作位置：截图后用 Pillow 后处理，按 rect × dpr 画红框 + 动作序号。不往页面注高亮 DOM（会污染页面布局）。

### 2.4 双截图与稳定等待

```
动作事件到达 ──► 立即截 before ──► wait_stable() ──► 截 after
```

- **before**：动作发生瞬间的页面原貌（尽力而为）
- **after**：等待页面稳定后截，抓操作效果（跳转/弹窗/刷新）

`wait_stable()` 两条件同时满足：

- 条件 A：网络空闲——无 in-flight 请求（websocket/SSE/长轮询等常驻连接不计数）
- 条件 B：DOM 静默——注入脚本 MutationObserver 连续 500ms 无突变上报

**兜底超时 30s**（`--settle-timeout` 可调，默认 30s）：动画/轮询不停的页面强制截图，jsonl 标 `after_shot: "timeout"`。

已知竞态：动作直接触发跳转时 before 可能截到已跳转画面。缓解：rect + descriptor 与截图解耦必然落盘；此类事件标 `before_shot: "raced"`，不装作没发生。

### 2.5 停止录制（三层）

1. **主入口：页面内热键 `Ctrl+Shift+F9`**——注入脚本捕获（capture 阶段，覆盖所有 frame）→ CDP binding 上报 → 优雅收尾。操作者不离开浏览器。自拉起的干净 Chromium 无用户扩展抢占此组合键
2. **自然入口：直接关闭浏览器窗口**
3. **终端兜底：`q` + 回车**；Ctrl-C 保留信号处理器优雅落盘，但不作为宣传的停止方式（避免与复制混淆）

热键事件记为 `control_stop`（控制事件，不算操作，不进文档）。终端打印横幅提示停止方式。

## 3. session.jsonl 事件 Schema 与 PROMPT.md

### 3.1 事件 Schema

每行一个 JSON 对象，公共字段 + 按 `kind` 分化。`t_mono` 为录制进程单调时钟毫秒值，全事件流唯一排序键。

```jsonc
// 公共字段
{ "t_mono": 48123, "kind": "...", "seq": 107, ... }
```

| kind | 触发 | payload 关键字段 |
|---|---|---|
| `session_start` / `session_end` | 录制起止 | url、时间戳、浏览器/系统版本、页面列表；session_end 可带 `abnormal: true` |
| `nav` | Page.frameNavigated（主 frame） | url, title |
| `action` | 注入脚本上报 click/input/submit | type, element{rect, viewport, descriptor}, value_masked（密码恒为 `***`）, before_shot, after_shot |
| `request` | Network.requestWillBeSent | request_id, method, url, headers, post_body, initiator |
| `response` | Network.responseReceived | request_id, status, mime, headers, size |
| `response_body` | getResponseBody 结果 | request_id, body, body_base64（二进制） |
| `dom_mutations` | 注入脚本 MutationObserver 聚合上报 | count, snapshot_hint（变更节点摘要 ≤10 条） |
| `screenshot` | 双截图完成 | action_seq, phase(before/after), file, raced/timeout 标记 |
| `note` | 辅助记录（如新标签页打开未录制） | text |
| `control_stop` | 页面内热键停止 | — |

**body 不截断**：request/response body 一律全量落盘。大响应导致 session 膨胀时再引入压缩方案（gzip 每行 / body 外置 blobs/ 目录），届时独立决策。

**安全基线**（写死在 writer.py，不可配置）：

- `Authorization` / `Cookie` / `Set-Cookie` / `token` 类 header：只记键名不记值
- 密码型 input（type=password）：值恒为 `***`
- URL 中 `token=` / `password=` / `secret=` 等参数值替换为 `***`

### 3.2 PROMPT.md 模板

录制结束时自动写入 session 目录（源模板 `templates/PROMPT.md.tmpl` versioned 于项目内，录制时拷贝），是给 Claude Code 会话的完整指令。结构：

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

**质量闭环**（针对上次"输出质量不行"）：文档质量不满意时改模板重跑，不用改录制端代码。

## 4. 错误处理与边界情形

| # | 情形 | 处置 |
|---|---|---|
| 1 | CDP 连接断开（浏览器崩溃/被杀） | 优雅收尾：flush jsonl、写 session_end（`abnormal: true`）、退出码 2。已录内容不丢 |
| 2 | getResponseBody 失败（导航走了/响应体被释放） | response_body 记 `error: "evicted"`，不重试不装作成功 |
| 3 | 注入脚本失效（导航清掉旧注入） | `Page.addScriptToEvaluateOnNewDocument` 导航即重注，无需自愈 |
| 4 | 新开标签页/弹窗 | MVP 单 target：只跟启动 tab。新 tab 记 `note` 事件，PROMPT.md 指示 LLM 如实标注。多 tab 留二期 |
| 5 | 操作者停止 | 三层停止（§2.5）；Ctrl-C/Ctrl+Shift+F9/关窗均优雅落盘 |
| 6 | jsonl 写失败（磁盘） | 立即中止录制并明确报错——静默丢失不可接受 |
| 7 | 浏览器启动失败 | 明确报错退出，附排查提示（headed 需 DISPLAY；端口占用换 `--port`） |
| 8 | 下载行为 | Browser.setDownloadBehavior 拦截记事件，不真下载 |
| 9 | iframe 内操作 | CDP 对每个 attached frame 自动注入；跨 frame 事件带 frame_id。坐标为 frame 内视口坐标，文档生成时 LLM 结合截图判断，MVP 不做坐标换算 |
| 10 | 页面 beforeunload | 不处理，浏览器原生行为 |

## 5. 测试策略

按风险倒序，不搞单测框架崇拜：

1. **schema 一致性测试**（writer.py）：每种 kind 的事件 emit 后重新 json.loads，字段/脱敏规则断言——防手改 schema 时悄悄破坏
2. **端到端冒烟**：录本地静态页（tests/fixtures/ 小 html）+ 固定操作，断言 jsonl 事件序列、截图存在、PROMPT.md 存在。CI 可跑（本地 http.server，不依赖外网）
3. **PROMPT.md 模板快照测试**：模板改动 diff 出来提醒同步
4. 其余错误路径（#1/#5/#6/#7）code review + 手工验证

## 6. 二期候选（本次不做）

- `replaysession` 请求重放
- 多 tab 录制
- body 压缩/外置（触发条件：单 session 体积成为实际问题）
- 浏览器扩展录制手段（必须用日常浏览器录的场景）
