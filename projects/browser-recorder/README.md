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
```

浏览器二进制默认找 Playwright 缓存的 Chromium（见下 `BR_CHROME`）；退出码 0=正常停止，2=异常（崩溃/被杀）。

## CLI 旗子

`browser-recorder record [START_URL]`（默认 `about:blank`）：

| 旗子 | 默认 | 说明 |
|---|---|---|
| `-o, --out <dir>` | `sessions/` | session 输出根目录，自动建时间戳子目录 |
| `--settle-timeout <sec>` | `30` | after 截图稳定等待兜底（网络空闲 ∧ DOM 静默 500ms 即稳，超时走满此值；网络差可调大） |
| `--port <n>` | 随机 | CDP 调试端口（端口占用时换） |
| `--headless / --no-headless` | 有头 | 无 DISPLAY/CI 环境用 `--headless` |
| `--no-sandbox` | 不加 | 透传 `--no-sandbox` 给 chrome。**容器/AppArmor/无 user namespace 环境必需**（否则 chrome 起不来）；桌面环境默认不加——该旗子会关闭浏览器沙箱安全边界，仅在受控隔离环境使用 |

`browser-recorder export <SESSION_DIR>`：session 目录 → 同名 zip（自动排除 `chrome-profile/`）。

## 环境变量

- `BR_CHROME`：浏览器二进制路径。默认 `~/.cache/ms-playwright/chromium-1208/chrome-linux/chrome`（可指向任何 Chromium 系二进制；chrome 不存在时启动即报错并提示用此变量）

## 生成操作指引文档

session 目录下启动 Claude Code，直接说"按 PROMPT.md 执行"，产出 `guide.md`（人类步骤指引 + API 逆向详情两附录）。

文档质量不满意 → 改 `templates/PROMPT.md.tmpl` 重录/重生成即可，不动录制端。

## 事件流 schema（摘要）

每行 `{t_mono, kind, seq, ...}`，`t_mono` 为录制进程单调时钟毫秒，全流唯一排序键。kind 与实现一致（`writer.py` / `recorder.py`）：

| kind | 触发 | payload 关键字段 |
|---|---|---|
| `session_start` / `session_end` | 录制起止 | url、ts、chrome 路径、pid；end 带 `abnormal`、`stop_reason`（hotkey/browser_closed/terminal_q） |
| `nav` | 主 frame 导航 | url, title |
| `action` | 注入脚本上报 click/input/submit | type, element{rect, viewport, descriptor}, value, html_type |
| `request` / `response` / `response_body` | CDP Network 域 | request: method/url/headers/post_body/initiator；response: status/mime/headers/size；body: 全量不截断，取不到记 `error: "evicted"` |
| `dom_mutations` | MutationObserver 150ms 聚合 | count |
| `screenshot` | 每动作双截图完成 | action_seq, phase(before/after), file, status(ok/raced/timeout/failed) |
| `control_stop` | 页面内 Ctrl+Shift+F9 | — |

**硬脱敏**（写死在 `writer.py`，不可配置）：`Authorization`/`Cookie`/`Set-Cookie`/token 类 header 只记键名不记值；`type=password` input 值恒 `***`；URL 中 `token`/`password`/`secret` 类参数值打码为 `***`。body 不截断。

## 已知限制（spec §4）

- 单 tab 录制：只跟启动 tab，新开标签页/弹窗不录（设计中的 `note` 事件未实现，新 tab 无记录）
- iframe 内操作坐标为 frame 视口坐标（MVP 不做换算，文档生成时结合截图判断）
- 下载行为未拦截（设计 §4 #8 的 `Browser.setDownloadBehavior` 未实现，下载走浏览器原生行为）
- before 截图与极速跳转存在竞态：截不到时标 `raced`，rect + descriptor 兜底仍落盘

## 开发

```bash
cd projects/browser-recorder
uv sync
uv run pytest tests/ -v   # 13 个测试（writer 脱敏 / cdp / inject / recorder 流程 / annotator）
```

设计文档：`docs/2026-08-29-browser-recorder-design.md`（实现计划：`docs/2026-08-29-browser-recorder-plan.md`）
