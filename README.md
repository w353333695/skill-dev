# skill-dev

> 基于「**能力 project + 编排 skill**」两层结构的工作空间。

## 是什么

用「能力 project + 编排 skill」两层结构组织 Claude Code 工作空间：

- **能力层** `projects/<name>/`：可独立打包的 Python 包，提供 CLI/库，各自独立 venv。
- **编排层** `skills/<name>/`：SKILL.md + 轻量脚本，把自然语言意图翻译成 project 的 CLI 调用，**不携带能力代码**。

一个 skill 可编排多个 project，一个 project 可被多个 skill 复用（多对多）。skill 与 project 通过 **CLI 边界**耦合：只调 CLI + 读产物文件，不 import 代码。

## 目录结构

| 目录 | 职责 |
|---|---|
| `projects/<name>/` | 能力层：独立 Python 包 + CLI（独立 venv） |
| `skills/<name>/` | 编排层：SKILL.md + manifest.sh + 脚本 |
| `platforms/` | 跨 skill 共享的平台资产（契约/知识库/注册表等，可拔插） |
| `scripts/` | workspace 级通用脚本（如打包） |
| `tmp/` | 临时产物（不入库） |

## 能力清单

### projects/

| 能力 | CLI | 说明 |
|---|---|---|
| [api-console](projects/api-console) | `api-console` | API 资产建设 + 调用编排 CLI，平台中性，adapter 可拔插 |
| [browser-recorder](projects/browser-recorder) | `browser-recorder` | 跨平台浏览器操作录制/回放/导出 CLI |

- **api-console**：把后端契约/swagger + 前端 openapi 半自动注册成标准化「API 卡片」库；按自然语言需求生成调用 DAG（读聚合 / 写创建更新回滚），确定性校验后真调执行。
- **browser-recorder**：录制浏览器操作流程，可回放、导出为多种格式，用于场景沉淀与自动化。

### skills/

| Skill | 编排的 project | 说明 |
|---|---|---|
| [api-console](skills/api-console) | api-console | 已对接平台（如 EasyOps）的 API 卡片库建设与跨接口编排执行 |

> `browser-recorder` 目前作为独立 project 存在，尚未被 skill 编排。

### platforms/easyops

EasyOps 平台的共享资产（外部可拔插部件）：

- `manifest.yaml` — 平台配置（环境、认证模式、调用策略）
- `registry/` — API 卡片注册表
- `knowledge/` — 平台知识库（概念、模块文档）
- `sources/` — 后端契约 + 前端指南
- `auth/` — 认证凭证（**已 `.gitignore`，不入库**）

## 快速开始

### 前置

- [uv](https://docs.astral.sh/uv/)（推荐）或 pip/pipx
- 指向内部 PyPI 的 index（分发态拉包用）

### 开发态：跑能力 / 测能力

```bash
# 用对应 project 的 venv 跑 CLI（editable，改完即生效）
uv run --project projects/api-console api-console --help
uv run --project projects/browser-recorder browser-recorder --help

# 跑某个 project 的测试
cd projects/api-console && uv run pytest
```

### 分发打包

通用脚本 [`scripts/pack-dist.sh`](scripts/pack-dist.sh) 读 skill 的 `manifest.sh`，把依赖的 project 打成 whl 塞进 `vendor/`，连同 skill 整体打成 zip：

```bash
bash scripts/pack-dist.sh api-console
# 产物: tmp/api-console-dist-<ver>.zip
```

zip 不含 `platforms/`（外部部件，由 skill 方另行分发）和 dev 专用 `scripts/run.sh`。部署侧（解压到 workspace 根后）：

```bash
bash skills/api-console/scripts/setup.sh   # 幂等装好依赖的 CLI
```

> **当前进度**：`skills/api-console` 已含 `manifest.sh`；按规范配套的 `scripts/setup.sh` / `scripts/run.sh` 待补。

### 分发态调用

```bash
uvx api-console ...          # 有 uv：免安装，自动拉包建隔离环境
api-console ...              # 无 uv：pipx / pip install 后裸调
```

## 开发约定（摘要）

- **venv 隔离**：每个 project 一个 venv，用 uv 管（`uv venv` + `uv sync`）。skill 不拥有 venv、不 `pip install`。
- **调用方式**：`uv run --project projects/<name> <cli> ...`（自动用该 project 的 venv）。
- **CLI 边界**：skill 只调 project 的 CLI + 读产物，不 import / 不复制 project 代码。
- **运行时大件**（chromium 等）不进 whl，由 project 的 `doctor` / `install-deps` 子命令补，缓存 `~/.cache`。
- **中文优先**：沟通、文档、注释用中文。
- **改完即提交**：工作空间有自动 `chore(ai)` 提交机制，改完代码立即手动 commit，避免混入不准的自动提交。

完整规范见 [`CLAUDE.md`](CLAUDE.md)。

## .gitignore 要点

以下均不入库：

- `platforms/easyops/auth/` — 认证凭证
- `platforms/easyops/sources/raw/` — 公司内部源码
- `.env` — 本地凭证存储（GitHub token 等）
- `.venv/`、`tmp/`、`__pycache__/` — 常规
