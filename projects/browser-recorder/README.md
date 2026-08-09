# browser-recorder

录制浏览器操作，一次产出三类产物，并支持回放复现。

## 安装

```bash
cd projects/browser-recorder
uv sync
uv run playwright install chromium   # 如本机无浏览器缓存
uv run browser-recorder doctor       # 自检
```

## 使用

### 录制（headed，生产环境有 UI）

```bash
# 首次：手动登录一次，登录态存到 .browser-recorder/auth/<host>.json
browser-recorder login --url http://172.30.0.232

# 之后录制自动带登录态；过期会提示原地重登（不中断录制）
browser-recorder record --url http://172.30.0.232
# 在浏览器里正常操作，Ctrl+C 或关闭浏览器结束录制
```

### 录制（CDP attach，无 UI 环境 / 登录态兜底）

```bash
# 本机 Chrome 以调试端口启动（或 ssh 隧道转发远端 9222）
chrome --remote-debugging-port=9222

# attach 后直接录（attach 后会自动 reload 一次以注入录制脚本）
browser-recorder record --cdp http://localhost:9222
# 或 attach 后跳到指定起始页
browser-recorder record --cdp http://localhost:9222 --url http://172.30.0.232
```

### 回放

```bash
browser-recorder replay .browser-recorder/sessions/20260809_153000_172.30.0.232
# 参数化（record.jsonl 中步骤设了 param_key 时覆盖输入值）
browser-recorder replay <session_dir> --param password=xxx
# 失败不中断 / 录像
browser-recorder replay <session_dir> --on-fail skip --video
```

### 无 UI 环境调试

```bash
# 无头模式录制（调试用；正常录制应 headed 或 --cdp）
browser-recorder record --url http://localhost:8000 --headless
```

## 产物

```
.browser-recorder/sessions/<ts>_<host>/
├── record.jsonl      # 结构化操作记录（回放数据源；sensitive 字段含原值）
├── requests.jsonl    # fetch/XHR 请求记录（step_seq 关联操作步骤；敏感 header 不录）
├── doc.md            # 图文操作手册（密码步骤显示 ***）
├── meta.json
├── screenshots/      # step-NNN.png（点击位置红圈标注 + 步骤序号徽标）
└── replay/           # report.json + 回放截图（+ video/）
```

> ⚠️ `record.jsonl` 保留密码等敏感输入的原值（回放需要）；`.browser-recorder/` 已在 gitignore 中，请勿外发 session 目录。

## 环境说明

- **CDP 模式**：attach 后必须有一次导航/reload 录制脚本才生效（Playwright init script 只对 attach 后的导航生效），工具已自动处理。
- **CDP 模式不支持录制期录像**（Playwright 限制）；回放录像（`replay --video`）不受影响。
- **iframe**：同源 iframe 内操作可录制（事件经 parent 桥上报）；跨域 iframe 事件会丢弃并在 console warn。回放第一阶段只定位 main frame。
- **SPA 路由**：`pushState/replaceState/popstate/hashchange` 会记录为 navigate 步骤。
- **请求记录**：经 `context.route` 拦截所有 fetch/XHR（静态资源/媒体/websocket 除外），请求体 + 响应体（≤64KB）都记；doc.md 末尾附"关键请求"表（写操作 + 非 2xx）。
