# 项目规则（最高优先级，所有 agent 必须遵守）

本文件为**项目级**规则，与用户全局 `~/.claude/CLAUDE.md` 并存；冲突时以本文件为准。

本工作空间用「**能力 project + 编排 skill**」两层结构组织：`projects/<name>/` 是可独立打包的能力包（**Python 或 golang**，提供 CLI），`skills/<name>/` 是把它们串起来的编排层。下列规范适用于所有 agent。

## 1. 通用约定

* 中文沟通、写文档、写注释。
* 只能操作项目内文件，项目外文件只读；删除非本次会话产生的临时文件前先确认。
* 不指定 superpowers，不主动介入。

## 2. 工作空间结构

| 目录 | 职责 |
|---|---|
| `projects/<name>/` | **能力层**：可独立打包的能力包，提供 CLI/库（Python 或 golang） |
| `skills/<name>/` | **编排层**：SKILL.md + 轻量脚本，调 project 的 CLI，不携带能力代码 |
| `platforms/` | 跨 skill 共享的平台产物（API 契约、模型等） |
| `tmp/` | 临时产物；按 scope 分子目录，不长期沉淀 |

* **命名与识别**：project 名 = 能力名 = dist 名（连字符，如 `browser-recorder`）。**识别 project 类型**：有 `go.mod` → golang，有 `pyproject.toml` → Python。Python 包目录用下划线（`browser_recorder`），golang 包目录随 module 名。
* skill 产物默认放 `tmp/`，不写进 plugin/skill 目录（除非固化）。
* **golang project**（有 `go.mod`，如 `projects/api-cli/`）与 Python project **平行支持，不再算"例外"**：
  - 打包：`scripts/pack-go.sh`（多平台交叉编译二进制 + zip 大礼包 + checksums，CGO=0 纯静态），**不走** whl / `pack-dist.sh`。
  - 编排层调用：开发态 `go run ./cmd/<name>` 或 `go build` 出单二进制；分发态裸二进制（从大礼包挑对应平台）。**不走** `uv run`。
  - 本沙箱 go 在 `/usr/local/go/bin/go`（go 1.22.5），**不在 PATH**，用前 `export PATH="/usr/local/go/bin:$PATH"`；拉 module 慢可设 `GOPROXY=https://goproxy.cn,direct`。
  - 项目文档隔离在 `projects/<name>/docs/`。

## 3. 开发：Python project 的 venv 与依赖

* **每个 project 一个独立 venv**，用 **uv** 管（`uv venv` + `uv sync`）。能力 project 之间依赖隔离，互不污染。
* **skill 不拥有 venv、不 `pip install` 任何依赖**。要装的东西属于某个 project。
* 调用 project 的 CLI：`uv run --project projects/<name> <cli> ...`（自动用该 project 的 venv，首次按 lock 建/sync）。
* **不要**：靠 `source .venv/bin/activate`（shell 状态不跨 Bash 调用持久）；不要共享一个 venv 装所有 project；不要 per-skill 建 venv。

### 3.1 依赖安装加速（本沙箱中国网络，必读）

本工作空间直连 PyPI / GitHub 慢或超时，**装依赖/二进制一律走镜像，别傻等**：

* **PyPI**（pip / uv）：
  - uv：`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv pip install <pkg>`（或 `uv sync --extra X`，命令前缀加该环境变量）
  - pip：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>`
* **playwright chromium**：`PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright` 前缀跑 `playwright install chromium`，绕开官方 CDN（官方常超时）。
* **GitHub 二进制 / release**：直连基本超时。**优先用 PyPI 自带二进制的包避开 github**——要 pandoc 装 `pypandoc-binary`（自带 pandoc 3.x）、要 typst 装 `typst`（PyPI wheel 自带引擎），**别自己从 github release 下 tarball**。
* **git push**：本仓库即 skill-dev 仓库，push 时须绕过镜像走真实远端（凭证 token 在 `.env`）。
* **先探测再批量**：`curl -sSL --max-time 10 -o /dev/null -w '%{http_code}' <url>` 先试一两个镜像可达性，再批量用；公共 ghproxy（ghproxy.com 等）多数已 403 限流，别浪费时间。

### 3.2 golang project 的开发与依赖

* 依赖走 `go.mod` / `go.sum`，`go mod download` 拉取；本沙箱 go 在 `/usr/local/go/bin`（**不在 PATH**，用前 `export PATH="/usr/local/go/bin:$PATH"`）。
* 调 CLI 验证：`cd projects/<name> && go run ./cmd/<name>`；`go build -o bin/<name> ./cmd/<name>` 出二进制。
* 跑测试：`cd projects/<name> && go test ./...`。
* 国内拉 module 慢：`GOPROXY=https://goproxy.cn,direct`（七牛镜像）。module cache 全局共享在 `~/go/pkg/mod`。
* **不用** venv / uv / pip——golang 有自己的工具链。

## 4. 调试

* 改 project 代码用 editable（`uv sync` 或 `uv pip install -e .`），改完即生效，`uv run --project` 立刻拿到最新。
* 跑测试：`cd projects/<name> && uv run pytest`。
* 调 CLI 验证：`uv run --project projects/<name> <cli> ...`。
* golang project：`cd projects/<name> && go run ./cmd/<name>` 调 CLI、`go test ./...` 跑测试（详见 §3.2）。
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
* **golang project 分发**：`scripts/pack-go.sh <name> -o <dir>` 交叉编译多平台二进制（CGO=0 纯静态）+ zip 大礼包 + `checksums.txt`。分发态：解压大礼包 → 挑对应平台二进制（**arm64 = aarch64 = Apple Silicon**）→ `chmod +x` → 拷 `~/.local/bin/<name>`。详见 `projects/api-cli/README.md`「分发打包」。

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
* **golang project 不走本套**：用独立的 `scripts/pack-go.sh`（多平台二进制大礼包），不读 `manifest.sh`、不进 `vendor/` whl。若一个 skill 同时依赖 Python 和 golang project，Python 走上述流程，golang 另跑 `pack-go.sh`，两套产物独立分发。
