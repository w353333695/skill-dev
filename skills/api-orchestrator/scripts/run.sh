#!/usr/bin/env bash
# run.sh —— api-cli 统一执行入口（自动检测，skill 不感知环境）。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
#
# 查找顺序：
#   ① skill 自带的预编译二进制 bin/api-cli（分发态，随 skill 打包）
#   ② PATH 上的 api-cli（用户手动装的）
#   ③ go build 增量编译（开发态，源码可编辑）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ① skill 自带预编译二进制（分发态——随 skill 打包，零环境依赖）
if [ -x "$SKILL_DIR/bin/api-cli" ]; then
    exec "$SKILL_DIR/bin/api-cli" "$@"
fi

# ② PATH 上有（用户手动装过）
if command -v api-cli &>/dev/null; then
    exec api-cli "$@"
fi

# ③ 开发态：go build 增量编译
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
export PATH="$PATH:$HOME/.local/go-parent/go/bin"
cd "$REPO_ROOT"
BIN="$REPO_ROOT/tmp/.api-orchestrator/api-cli"
mkdir -p "$(dirname "$BIN")"
( cd projects/api-cli && go build -o "$BIN" ./cmd/api-cli )
exec "$BIN" "$@"
