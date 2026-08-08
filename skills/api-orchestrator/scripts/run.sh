#!/usr/bin/env bash
# run.sh —— 开发态调 api-cli 的壳。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/demo/cmdb.yaml inst read i-1 --print-curl
#
# 分发态（skill 打包后）直接裸调 api-cli，不用本壳。
set -euo pipefail

# 定位仓库根（skill 在 skills/api-orchestrator/，往上两级）
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"

# go 不在默认 PATH（见 AGENTS）
export PATH="$PATH:$HOME/.local/go-parent/go/bin"

# 开发态：go run api-cli（editable，改 api-cli 即生效）
cd "$REPO_ROOT"
# editable build：api-cli 改动后下次自动重编（go build 增量，cache 后极快）。
# 用 build 二进制而非 go run，是为了让 api-cli 进程 cwd = REPO_ROOT，
# 这样 --spec 等相对路径相对仓库根解析（go run 启动的进程 cwd 会落在 module 目录）。
BIN="$REPO_ROOT/tmp/.api-orchestrator/api-cli"
mkdir -p "$(dirname "$BIN")"
( cd projects/api-cli && go build -o "$BIN" ./cmd/api-cli )
exec "$BIN" "$@"
