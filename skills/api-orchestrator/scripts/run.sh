#!/usr/bin/env bash
# run.sh —— api-cli 统一执行入口（自动检测环境）。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
#
# 自动检测：
#   ① api-cli 在 PATH 上（分发态）→ 直接 exec
#   ② 不在 PATH（开发态）→ go build 增量编译后 exec
# skill 文档统一用 scripts/run.sh，不区分环境。
set -euo pipefail

# ① 分发态：api-cli 已在 PATH
if command -v api-cli &>/dev/null; then
    exec api-cli "$@"
fi

# ② 开发态：go build
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
export PATH="$PATH:$HOME/.local/go-parent/go/bin"
cd "$REPO_ROOT"
BIN="$REPO_ROOT/tmp/.api-orchestrator/api-cli"
mkdir -p "$(dirname "$BIN")"
( cd projects/api-cli && go build -o "$BIN" ./cmd/api-cli )
exec "$BIN" "$@"
