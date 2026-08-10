#!/usr/bin/env bash
# run.sh —— skill 统一执行入口（自动检测 OS/ARCH + 环境，skill 不感知）。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
#
# Go 二进制查找顺序：
#   ① bin/api-cli-<os>-<arch>（skill 自带预编译，按当前 OS/ARCH 选——零环境依赖）
#   ② bin/api-cli（兼容旧打包，单平台）
#   ③ PATH 上的 api-cli
#   ④ go build 增量编译（开发态）
#
# Python 脚本（lint-platforms.py 等）也通过本入口间接可用——
# skill 文档不直接调 python3，统一走 scripts/run.sh + scripts/ 子命令。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- OS/ARCH 探测（不含 windows）---
case "$(uname -s)" in
    Linux*)  OS=linux;;
    Darwin*) OS=darwin;;
    *) echo "run.sh: 不支持的 OS: $(uname -s)（仅 linux/darwin）" >&2; exit 1;;
esac
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH=amd64;;
    aarch64|arm64) ARCH=arm64;;
    *) echo "run.sh: 不支持的 ARCH: $ARCH（仅 amd64/arm64）" >&2; exit 1;;
esac

# --- Go 二进制查找 ---
# ① 预编译按平台（分发态首选）
if [ -x "$SKILL_DIR/bin/api-cli-$OS-$ARCH" ]; then
    exec "$SKILL_DIR/bin/api-cli-$OS-$ARCH" "$@"
fi
# ② 兼容旧打包（单平台直接放 bin/api-cli）
if [ -x "$SKILL_DIR/bin/api-cli" ]; then
    exec "$SKILL_DIR/bin/api-cli" "$@"
fi
# ③ PATH 上有
if command -v api-cli &>/dev/null; then
    exec api-cli "$@"
fi
# ④ 开发态 go build
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ] && [ -d "$REPO_ROOT/projects/api-cli" ]; then
    export PATH="$PATH:$HOME/.local/go-parent/go/bin"
    BIN="$REPO_ROOT/tmp/.api-orchestrator/api-cli"
    mkdir -p "$(dirname "$BIN")"
    ( cd "$REPO_ROOT/projects/api-cli" && go build -o "$BIN" ./cmd/api-cli )
    exec "$BIN" "$@"
fi

echo "run.sh: 找不到 api-cli 二进制（bin/api-cli-$OS-$ARCH / bin/api-cli / PATH / go build 均未命中）" >&2
exit 1
