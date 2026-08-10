#!/usr/bin/env bash
# run.sh —— skill 统一执行入口（自动探测 OS/ARCH + 查找二进制，skill 不感知环境）。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
#
# 所有路径相对 run.sh 自身定位（不依赖项目结构/REPO_ROOT），skill 换位置不影响。
#
# 预期打包结构（单平台，按目标机器只放一个二进制）：
#   bin/api-cli    ← 预编译当前平台二进制（-s -w 精简，~12M）
#
# fallback 查找顺序：
#   ① bin/api-cli（skill 自带预编译——零环境依赖）
#   ② bin/api-cli-<os>-<arch>（兼容多平台打包）
#   ③ PATH 上的 api-cli
#   ④ go build 增量编译（开发态，往上找 projects/api-cli）
set -euo pipefail

# --- 相对 run.sh 自身定位（skill 可在任意位置）---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Go 二进制查找（全相对 SKILL_DIR）---
# ① 预编译单平台（分发态首选——打包时只放目标平台一个二进制，减小分发包体积）
if [ -x "$SKILL_DIR/bin/api-cli" ]; then
    exec "$SKILL_DIR/bin/api-cli" "$@"
fi
# ② 兼容多平台打包（bin/api-cli-<os>-<arch>）
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in x86_64|amd64) ARCH=amd64;; aarch64|arm64) ARCH=arm64;; esac
if [ -x "$SKILL_DIR/bin/api-cli-$OS-$ARCH" ]; then
    exec "$SKILL_DIR/bin/api-cli-$OS-$ARCH" "$@"
fi
# ③ PATH 上有
if command -v api-cli &>/dev/null; then
    exec api-cli "$@"
fi

# ④ 开发态 go build（从 SCRIPT_DIR 往上找 projects/api-cli）
_DEV_ROOT="$SCRIPT_DIR"
for _ in 1 2 3 4 5; do
    if [ -d "$_DEV_ROOT/projects/api-cli" ]; then
        export PATH="$PATH:$HOME/.local/go-parent/go/bin"
        BIN="$_DEV_ROOT/tmp/.api-orchestrator/api-cli"
        mkdir -p "$(dirname "$BIN")"
        ( cd "$_DEV_ROOT/projects/api-cli" && go build -ldflags "-s -w" -o "$BIN" ./cmd/api-cli )
        exec "$BIN" "$@"
    fi
    _DEV_ROOT="$(dirname "$_DEV_ROOT")"
done

echo "run.sh: 找不到 api-cli（bin/api-cli / bin/api-cli-<os>-<arch> / PATH / go build 均未命中）" >&2
echo "       分发态：确认 pack-go.sh 已预编译到 bin/api-cli" >&2
echo "       开发态：确认在项目仓库内（含 projects/api-cli/）" >&2
exit 1
