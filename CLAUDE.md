# 项目规则（最高优先级，所有 agent 必须遵守）

本文件为**项目级**规则，与用户全局 `~/.claude/CLAUDE.md` 并存；冲突时以本文件为准。

本工作空间用「**能力 project + 编排 skill**」两层结构组织：`projects/<name>/` 是可独立打包的 Python 能力包（提供 CLI），`skills/<name>/` 是把它们串起来的编排层。下列规范适用于所有 agent。

## 1. 通用约定

* 中文沟通、写文档、写注释。
* 只能操作项目内文件，项目外文件只读；删除非本次会话产生的临时文件前先确认。
* 不指定 superpowers，不主动介入。

## 2. 工作空间结构

| 目录 | 职责 |
|---|---|
| `projects/<name>/` | **能力层**：可独立打包的 Python 包，提供 CLI/库，有自己的 venv |
| `skills/<name>/` | **编排层**：SKILL.md + 轻量脚本，调 project 的 CLI，不携带能力代码 |
| `platforms/` | 跨 skill 共享的平台产物（API 契约、模型等） |
| `tmp/` | 临时产物；按 scope 分子目录，不长期沉淀 |

* **命名**：project 名 = 能力名 = dist 名（连字符，如 `browser-recorder`）；Python 包目录用下划线（如 `browser_recorder`）。
* skill 产物默认放 `tmp/`，不写进 plugin/skill 目录（除非固化）。

## 3. 开发：虚拟环境与依赖

* **每个 project 一个独立 venv**，用 **uv** 管（`uv venv` + `uv sync`）。能力 project 之间依赖隔离，互不污染。
* **skill 不拥有 venv、不 `pip install` 任何依赖**。要装的东西属于某个 project。
* 调用 project 的 CLI：`uv run --project projects/<name> <cli> ...`（自动用该 project 的 venv，首次按 lock 建/sync）。
* **不要**：靠 `source .venv/bin/activate`（shell 状态不跨 Bash 调用持久）；不要共享一个 venv 装所有 project；不要 per-skill 建 venv。

## 4. 调试

* 改 project 代码用 editable（`uv sync` 或 `uv pip install -e .`），改完即生效，`uv run --project` 立刻拿到最新。
* 跑测试：`cd projects/<name> && uv run pytest`。
* 调 CLI 验证：`uv run --project projects/<name> <cli> ...`。
* **改完立即手动 `git commit`**：工作空间有自动 `chore(ai):` 提交机制，会扫描工作区未提交改动并打包成 message 不准的 commit（还可能混入并发变更）。别留未提交改动去跑长任务。

## 5. skill 与 project 的边界

* skill 通过 **CLI 边界**依赖 project：只调 `<cli> ...` 命令 + 读产物文件，**不 import project 代码、不复制代码**。
* 一个 skill 可编排多个 project，一个 project 可被多个 skill 复用（多对多）。
* skill 的职责：把自然语言意图翻译成 CLI 参数 + 编排产物后处理；不是携带一份执行引擎。

## 6. 分发

* project 打包 whl：`cd projects/<name> && uv build` → `dist/*.whl`，发到**内部 PyPI**（主）；无内部源 / 离线分发时，whl 随 skill 包 vendor。
* 分发态调用（去掉对本地路径的依赖）：
  - 有 uv：`uvx <name> ...`（免安装，自动拉包建隔离环境）；锁版本 `uvx <name>@<ver> ...`。
  - 无 uv：裸调 `<name> ...`，安装三选一 —— `uv tool install <name>` / `pipx install <name>` / `pip install --user <name>`，装到 `~/.local` 隔离工具环境，CLI 进 `~/.local/bin`。
* **运行时大件**（chromium 等）不进 whl：project 提供 `doctor` / `install-deps` 子命令封装（如内部跑 `playwright install chromium`），缓存在 `~/.cache`（如 `~/.cache/ms-playwright`）全局共享。skill 开头自检调 `doctor`。
* **版本锁定**：skill 在 SKILL.md 声明依赖范围（`<name>>=x,<y`），关键路径用 `@<ver>` 钉死，避免上游 breaking change 暗算。
* 目标环境前置：只需 uv（或 pip/pipx）+ 指向内部 PyPI 的 index；chromium 等由 project 子命令补。

## 7. skill 分发打包（通用脚本）

一个 skill 可依赖 **n 个 project**，用统一脚本一键打包/部署。差异只在各 skill 的 `manifest.sh`，脚本本身通用。

* **`skills/<skill>/manifest.sh`**：声明 skill 依赖的 project（bash 数组，不用 yaml——`setup.sh` 在用户环境跑，不能依赖 pyyaml 解析）：
  ```bash
  SKILL_NAME="<skill>"; SKILL_VERSION="<ver>"
  PROJECTS=("api-console=api-console" "browser-recorder=browser-recorder")  # project名=cli名
  ```
* **`skills/<skill>/scripts/setup.sh`**（分发态，每 skill 复制一份通用脚本）：读 manifest，对每个 project 幂等装好 CLI（vendor whl 优先离线，否则 PyPI 名；工具 uv>pipx>pip；pip 模式查 Python>=3.9）。部署阶段跑一次。
* **`skills/<skill>/scripts/run.sh`**（仅开发态，**不进分发包**）：`run.sh <cli> [args]` → `uv run --project projects/<对应project> <cli> [args]`，方便开发时直接测 skill。分发态裸调 CLI，不用本壳。
* **`scripts/pack-dist.sh <skill>`**（workspace 根通用打包）：读 manifest，对每个 project `uv build` 打 whl 塞进 `skills/<skill>/vendor/`，连 skill 整体 zip 到 `tmp/<skill>-dist-<ver>.zip`。**排除 `scripts/run.sh`（dev 壳）和 `__pycache__`**。
* **`platforms/` 不在通用打包范围**：它是 skill 的外部可拔插部件（如 api-console 的平台资产），由 skill 方自行手动分发，通用脚本不处理。
* 用户使用：解压 zip 到 workspace 根 → `bash skills/<skill>/scripts/setup.sh` → n 个 CLI 就位 → skill 直接调。
