# browser-recorder

浏览器操作录制 CLI：**裸 CDP 直连**（websockets，无 Playwright/Selenium），录制真人浏览器操作 + 全量网络请求，产出 `session.jsonl`（单时钟事件流）+ 每动作双截图（红框标注）+ `PROMPT.md`（Claude Code 文档生成模板）。

文档生成引擎外置：录制端不调 LLM，session 目录下的 `PROMPT.md` 交给 Claude Code 会话产出 `guide.md`。

## 产物结构

```
sessions/20260829-153000/
├── session.jsonl     # 操作+网络事件单时钟混排（全量、脱敏、不截断）
├── screenshots/      # NNNN-before.png / NNNN-after.png（红框=动作位置）
├── PROMPT.md         # 给 Claude Code 的文档生成指令
└── chrome-profile/   # 录制用临时浏览器配置（export 时自动排除）
```

## 快速开始

```bash
cd projects/browser-recorder
uv sync
uv run browser-recorder record https://example.com
# 浏览器弹出 → 正常操作 → 停止：页面内 Ctrl+Shift+F9 / 关窗 / 终端 q+回车
uv run browser-recorder export sessions/20260829-153000   # 导出 zip
# 驱动重放（详见「驱动与重放」）：录制 → flow.json → 无人值守跑即录
uv run browser-recorder replay sessions/20260829-153000 --name demo
uv run browser-recorder drive flows/demo.json --dry-run
```

浏览器二进制会自动探测 Playwright 缓存及系统安装的 Chrome/Chromium（macOS 会检查 `/Applications/*.app/Contents/MacOS/`）；退出码 0=正常停止，2=异常（崩溃/被杀），130=Ctrl-C 中断（已录事件已落盘）。drive/replay 的退出码见各自章节。

## CLI 旗子

`browser-recorder record [START_URL]`（默认 `about:blank`）：

| 旗子 | 默认 | 说明 |
|---|---|---|
| `-p, --profile <name>` | `default` | 持久登录态 profile（`~/.browser-recorder/profiles/<name>`）——cookie/登录跨录制存活，**免反复登录**。多系统隔离用不同名（如 `-p easyops` / `-p oa`） |
| `--incognito` | 关 | 一次性 profile：不落 `~/.browser-recorder`，录完即弃不留登录态（敏感账号场景） |
| `-o, --out <dir>` | `sessions/` | session 输出根目录，自动建时间戳子目录 |
| `--settle-timeout <sec>` | `30` | after 截图稳定等待兜底（网络空闲 ∧ DOM 静默 500ms 即稳，超时走满此值；网络差可调大） |
| `--port <n>` | 随机 | CDP 调试端口（端口占用时换） |
| `--headless / --no-headless` | 有头 | 无 DISPLAY/CI 环境用 `--headless` |
| `--no-sandbox` | 不加 | 透传 `--no-sandbox` 给 chrome。**容器/AppArmor/无 user namespace 环境必需**（否则 chrome 起不来）；桌面环境默认不加——该旗子会关闭浏览器沙箱安全边界，仅在受控隔离环境使用 |

> 登录态存储提示：profile 目录是本机明文（与日常浏览器记住密码等同风险）。清掉：`rm -rf ~/.browser-recorder/profiles/<name>`。

`browser-recorder export <SESSION_DIR>`：session 目录 → 同名 zip（自动排除 `chrome-profile/`）。

## 环境变量

- `BR_CHROME`：浏览器二进制路径，优先级最高。macOS 示例：`export BR_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`。未设置时自动寻找 Playwright Chromium、macOS 的 Google Chrome/Chromium/Brave/Edge，以及 PATH 中的 Chromium 系命令。

## 驱动与重放（drive / replay）

```bash
browser-recorder drive flows/easyops.json --profile easyops        # 跑即录（session 与真人录制同构）
browser-recorder drive flows/easyops.json --dry-run                # 只定位不动作（选择器体检）
browser-recorder drive flows/easyops.json --step-from 8 --var BR_PW_8=x   # 断点续跑 + 注入变量
browser-recorder replay sessions/20260922-xxxx --name my-flow      # 录制 session → flow.json
```

- **跑即录**：drive 默认同步录制 session——每步除机器视角的 `drive_step` 事件外，同时落统一 `action` 事件（带 `source:"drive"`）+ 双截图，产物与真人录制同构，可直接生成手册/审计。`--no-record` 不留产物（临时目录用完即删，行为不变）
- **flow.json**：`steps` 数组，每步 `{n, desc, act, loc(候选数组), value?, clear?, tabs?, wait?, on_new_tab?, expect?, on_expect_fail?, retries?, locate_timeout?}`；act ∈ open/click/input/submit/hover，wait ∈ settle(缺省)/none(跳过后置等待)/nav。密码写 `${env.XXX}` 引用环境变量（`--var KEY=VALUE` 或环境变量注入），credential 步的值在 session/证据包中恒 `***` 不落盘
- **候选链 loc**：按序试到首个命中——`css:#id`（穿透 open shadow root）/ `xpath://...` / `text:词`（`^` 前缀=词首锚定）/ `dom:div#app>span.btn`（录制 dom_path 直译）
- **失败协议**：定位 miss → 重试（默认 3，步级 `retries` 可覆盖）→ 证据包 `<session>/evidence/fail-step<N>/`（截图+DOM dump+context.json）→ 退出码 3。失败原因：locate-miss / check-fail / expect-fail / hotkey-stop
- **退出码**：0 成功 / 3 步失败（证据包已落盘）/ 4 flow 格式错误（含 `${env.XXX}` 变量未定义）
- **replay 转换器**：录制 session → flow.json，按稳定性推导候选链（id > 测试锚点 data-* > name/aria > 文本 > 语义 class；dom_path 兜底），并自动合成 open 起点、推导 `tabs`/`on_new_tab`/`wait:nav`；仅 dom_path 兜底的步默认剔除并出报告 `flows/<name>.report.md`（`--keep-fragile` 保留，标 `fragile:true`）。password 值转 `${env.BR_PW_<n>}` 占位（`needs_credential:true`），产物必须过 drive 同一校验

**drive 旗子**：`-p/--profile`（默认一次性，不留登录态）、`--headless`、`-o/--out`、`--var KEY=VALUE`（可多次）、`--step-from N`（从步号 N 续跑，自动补回起点导航）、`--dry-run`、`--no-record`、`--no-sandbox`（容器环境必需）。

## 生成操作指引文档

session 目录下启动 Claude Code，直接说"按 PROMPT.md 执行"，产出 `guide.md`（人类步骤指引 + API 逆向详情两附录）。

文档质量不满意 → 改 `templates/PROMPT.md.tmpl` 重录/重生成即可，不动录制端。

## 事件流 schema（摘要）

每行 `{t_mono, kind, seq, ...}`，`t_mono` 为录制进程单调时钟毫秒，全流唯一排序键。kind 与实现一致（`writer.py` / `recorder.py`）：

| kind | 触发 | payload 关键字段 |
|---|---|---|
| `session_start` / `session_end` | 录制起止 | url、ts、chrome 路径、pid；end 带 `abnormal`、`stop_reason`（hotkey/browser_closed/terminal_q/io_error/interrupt，drive 模态另有 drive_done/drive_fail），io_error 时附 `error` |
| `nav` | 主 frame 导航 | url, title |
| `action` | 注入脚本上报 click/input/submit（drive 模态为机器动作落盘） | type, source（`"drive"`=drive 派发的机器动作；缺省=真人操作）, element{rect, viewport, descriptor}, value, html_type, target_id |
| `request` / `response` / `response_body` | CDP Network 域 | request: method/url/headers/post_body/initiator；response: status/mime/headers/size；body: 全量不截断，取不到记 `error: "evicted"` |
| `ws_frame` | WebSocket 帧收/发 | request_id, direction(sent/received), payload（文本帧复用 post_body 敏感键打码+截 8KB）, payload_base64 |
| `dom_mutations` | MutationObserver 150ms 聚合 | count |
| `screenshot` | 每动作双截图完成 | action_seq, phase(before/after), file, status（before: ok/raced；after: stable/timeout；截取失败: failed） |
| `drive_step` | drive 每步执行成功（机器视角） | n, desc, act, dispatch（trusted/js-fallback/js/dry/nav）, match_count, retry_used, expect_result, target_id |
| `drive_fail` | drive 步失败 | n, desc, reason（locate-miss/check-fail/expect-fail/hotkey-stop）, evidence（证据包路径）, target_id |
| `control_stop` | 页面内 Ctrl+Shift+F9 | — |

**硬脱敏**（写死在 `writer.py`，不可配置）：`Authorization`/`Cookie`/`Set-Cookie`/token 类 header 只记键名不记值；`type=password` input 值恒 `***`；URL（nav/session_start/request/response）中 `token`/`password`/`secret` 类参数值打码为 `***`；`post_body` JSON 顶层敏感键值与 form 形态敏感参数值打码。body 不截断。

## 已知限制（spec §4）

- ~~单 tab 录制~~ **已解决**：autoAttach 自动跟随新开标签页/弹窗（事件带 `target_id` 区分），drive 侧 `tabs`/`on_new_tab` 显式建模多 tab
- iframe 内操作坐标为 frame 视口坐标（MVP 不做换算，文档生成时结合截图判断）
- WebSocket 二进制帧不落内容（`payload_base64` 恒 `false`，文本帧打码+截 8KB）；`ws://` 常驻连接不计入稳定判定（防 wait_stable 永不达稳）
- 下载行为未拦截（设计 §4 #8 的 `Browser.setDownloadBehavior` 未实现，下载走浏览器原生行为）
- before 截图与极速跳转存在竞态：截不到时标 `raced`，rect + descriptor 兜底仍落盘

## 开发

```bash
cd projects/browser-recorder
uv sync
uv run pytest tests/ -v   # 73 个测试（writer 脱敏 / cdp / inject / recorder 流程 / driver / flow 引擎 / replay / annotator；真浏览器用例无 Chrome 环境自动 skip）
```

设计文档：`docs/2026-08-29-browser-recorder-design.md`（实现计划：`docs/2026-08-29-browser-recorder-plan.md`）
