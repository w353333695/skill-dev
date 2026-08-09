# browser-recorder

> 浏览器操作录制 CLI 工具，基于 Playwright + Chromium

一键启动浏览器，自动记录用户所有交互（点击、输入、选择、弹窗、导航）、网络请求，智能截图，产出带时间戳标记的 Markdown 图文报告，并支持事件回放。

同域名自动共享鉴权（cookies/localStorage），不同场景独立录制，互不覆盖。

## 快速开始

```bash
pip install dist/browser_recorder-0.1.0-py3-none-any.whl
playwright install chromium

# 录制（按域名+场景自动管理产物）
recorder start --url https://example.com --name login

# 同域名二次录制 — 自动加载鉴权
recorder start --url https://example.com/dashboard --name browse

# 查看所有 session
recorder list
```

## 功能

- **全事件捕获** — click / input / change / submit / dialog / scroll / nav，含时间戳 + CSS selector + 坐标
- **智能截图** — 双帧策略：前帧 Pillow 标记点击位置 + 结果帧 MutationObserver DOM 稳定后截图
- **网络记录** — page.route() 拦截 XHR/Fetch/Document，可配置 glob 过滤
- **多标签管理** — context.on('page') 全生命周期，page_id 归属，支持 window.open / target=_blank
- **Shadow DOM** — composedPath 穿透，生成完整 CSS selector
- **SPA 路由** — popstate + hashchange + pushState/replaceState monkey-patch
- **增量落盘** — events.jsonl 批量追加写，进程崩溃不丢数据
- **事件回放** — 读 events.jsonl 自动执行，条件等待不加速，人为停顿按倍速缩放
- **鉴权共享** — 同域名 auth.json 自动保存/恢复（Playwright storage_state），录一次登录即可
- **场景隔离** — `--name` 区分同域名不同录制场景，产物独立不覆盖
- **产物管理** — 默认保留 record.md + requests.json，清理临时截图

## CLI 命令

```
recorder start --url URL [--name NAME]  启动录制
recorder replay EVENTS [--speed N]      回放事件链
recorder list                           列出所有域名和场景
recorder doctor                         环境检查
recorder version                        版本号
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--url` | (必填) | 起始 URL |
| `--name` / `-n` | `default` | 场景名，同域名下区分不同录制 |
| `--output` | 自动 | 输出目录（默认 `<domain>/<name>/`） |
| `--interval` | 30 | 兜底截图间隔（秒） |
| `--req-all` | False | 记录所有请求 |
| `--req-filter` | None | 请求过滤 glob |
| `--keep-all` | False | 保留全部过程文件 |
| `--speed` | 1.0 | 回放倍速 |
| `--repeat` | 1 | 重复回放次数 |

## 目录结构

```
./browser-recorder/
├── index.json                     # 全局域名索引
├── example.com/
│   ├── auth.json                  # 🔐 鉴权（跨场景共享，自动保存/恢复）
│   ├── meta.json                  # 域名元信息 + 场景列表
│   ├── login-flow/                # 场景: 登录流程
│   │   ├── meta.json
│   │   ├── events.jsonl
│   │   ├── requests.json
│   │   ├── record.md
│   │   └── screenshots/
│   └── dashboard/                 # 场景: 仪表盘操作
│       └── ...
└── 192.168.1.1_8080/
    ├── auth.json
    └── admin/
        └── ...
```

## 架构

```
事件流 → [注入器] → [过滤器₁..ₙ] → [处理器₁..ₙ] → Reporter → 产物
```

三层 Protocol 抽象，可扩展：

| 角色 | 接口 | 内置实现 |
|------|------|---------|
| EventFilter | `process(event) → list[dict]` | InputMergeFilter, DedupFilter |
| EventHandler | `handle(action, page)` | JsonlWriter |
| Reporter | `generate(actions, requests, dir) → Path` | MarkdownReporter |

## 项目结构

```
src/browser_recorder/
├── cli.py            # Typer CLI 入口
├── recorder.py       # 录制编排器（核心）
├── replay.py         # 回放引擎
├── injector.py       # JS 注入脚本 + Push 回调
├── filters.py        # 事件过滤器
├── handlers.py       # 事件处理器 (JsonlWriter)
├── network.py        # 网络请求拦截
├── screenshoter.py   # 智能截图 + Pillow 标记
├── reporter.py       # Markdown 报告生成
├── cleaner.py        # 临时文件清理
└── models.py         # 数据模型
```

## 测试

```bash
pytest tests/ -v        # 78 tests: 单元 + 集成（Playwright + 本地 HTTP server）
```

## 依赖

- Python >= 3.9
- Playwright >= 1.40 (Chromium)
- Typer >= 0.9
- Pillow >= 10.0
- Rich >= 13.0

## 文档

- [设计规格书](docs/superpowers/2026-08-09-browser-recorder-spec.md) (v0.1.1)
- [实现计划](docs/superpowers/plans/2026-08-09-browser-recorder-implementation.md)
