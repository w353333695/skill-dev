# skill-dev

> 基于「**能力 project + 编排 skill**」两层结构的工作空间。

## 是什么

用「能力 project + 编排 skill」两层结构组织 Claude Code 工作空间：

- **能力层** `projects/<name>/`：可独立打包的 Python 或 Go 包，提供 CLI/库，各自独立 venv。
- **编排层** `skills/<name>/`：SKILL.md + 轻量脚本，把自然语言意图翻译成 project 的 CLI 调用，**不携带能力代码**。

一个 skill 可编排多个 project，一个 project 可被多个 skill 复用（多对多）。skill 与 project 通过 **CLI 边界**耦合：只调 CLI + 读产物文件，不 import 代码。

## 目录结构

| 目录 | 职责 |
|---|---|
| `projects/<name>/` | 能力层：独立 Python/Go 包 + CLI（独立 venv） |
| `skills/<name>/` | 编排层：SKILL.md + manifest.sh + 脚本 |
| `platforms/` | 跨 skill 共享的平台资产/部署配置（契约/知识库/实体映射/流程模板等，可拔插） |
| `scripts/` | workspace 级通用脚本（如打包） |
| `tmp/` | 临时产物（不入库） |

## 能力清单

### projects/

| 能力 | 语言/CLI | 说明 |
|---|---|---|
| [api-cli](projects/api-cli) | Go `api-cli` | 声明式 API CLI：YAML 清单 → 分层命令树 + MCP tools，鉴权/分页可拔插 |
| [doc-converter](projects/doc-converter) | Python `doc-converter` | 文档格式转换（MD/PDF/Word/图片/Excel 互转）CLI |
| [browser-recorder](projects/browser-recorder) | Python `browser-recorder` | 浏览器操作录制：裸 CDP 直连 → session.jsonl + 双截图 + 文档生成模板 |

### skills/

| Skill | 编排的 project | 说明 |
|---|---|---|
| [api-orchestrator](skills/api-orchestrator) | api-cli | 通用 API 编排：自然语言 → 跨系统调用编排（onboarding 接入新能力域 + orchestration 编排执行） |
| [doc-converter](skills/doc-converter) | doc-converter | 文档格式转换 |
| [browser-manual](skills/browser-manual) | browser-recorder（session 产物） | 录制 session → 图文操作指引 guide.md（+可选 API 分析报告 api-report.md / api-calls.json） |
| [easyops_skills](skills/easyops_skills) | — | EasyOps 业务 skill 集（monitor-kit / resource-collector-kit / sso-provider / alarm-access 等） |

### platforms/

跨 skill 共享的可拔插资产。当前：

- `platforms/demo/` — api-orchestrator 的演示接入配置（`systems.yaml` 等）

> platforms 是 skill 的外部可拔插部件，不在通用打包范围，由 skill 方自行分发。

## 快速开始

### 前置

- [uv](https://docs.astral.sh/uv/)（推荐，Python project）或 pip/pipx
- Go ≥1.22（Go project；本空间用 `~/.local/go-parent/go/bin/go`）
- 指向内部 PyPI 的 index（分发态拉 Python 包用）

### 开发态：跑能力 / 测能力

```bash
# Go project（api-cli）：go run 或 build
go run ./projects/api-cli/cmd/api-cli --help
# 或通过编排 skill 的开发态壳
skills/api-orchestrator/scripts/run.sh --spec projects/api-cli/examples/easyops-cmdb.yaml object_instance search FLOW_BUILDER_API_CONTRACT@EASYOPS --print-curl

# Python project：用对应 venv 跑 CLI（editable，改完即生效）
uv run --project projects/doc-converter doc-converter --help

# 跑某 project 的测试
cd projects/api-cli && go test ./...
cd projects/doc-converter && uv run pytest
```

### 分发打包

- **Go project**：`scripts/pack-go.sh <name> -o tmp/` 交叉编译多平台二进制 + zip 大礼包（CGO=0 纯静态）。
- **Python project**：`scripts/pack-dist.sh <skill>` 读 skill 的 `manifest.sh`，把依赖的 project 打 whl 塞进 `vendor/`，连同 skill 整体 zip。
- **skill 部署**：解压到 workspace 根 → `bash skills/<skill>/scripts/setup.sh` → 依赖的 CLI 就位。

详见 [`AGENTS.md`](AGENTS.md) §6-7。

## 开发约定（摘要）

- **venv 隔离**：每个 Python project 一个 venv，用 uv 管（`uv venv` + `uv sync`）。skill 不拥有 venv、不 `pip install`。
- **调用方式**：Python 用 `uv run --project projects/<name> <cli> ...`；Go 用 `go run ./projects/<name>/cmd/<name>` 或 build 二进制。
- **CLI 边界**：skill 只调 project 的 CLI + 读产物，不 import / 不复制 project 代码。
- **运行时大件**（chromium 等）不进包，由 project 的 `doctor` / `install-deps` 子命令补，缓存 `~/.cache`。
- **中文优先**：沟通、文档、注释用中文。
- **改完即提交**：工作空间有自动 `chore(ai)` 提交机制，改完代码立即手动 commit，避免混入不准的自动提交。

完整规范见 [`AGENTS.md`](AGENTS.md)。

## .gitignore 要点

以下均不入库：

- `platforms/*/auth/` — 认证凭证
- `platforms/*/sources/raw/` — 公司内部源码（若有）
- `.env` — 本地凭证存储（GitHub token 等）
- `.venv/`、`tmp/`、`__pycache__/` — 常规
