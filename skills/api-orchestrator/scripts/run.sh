#!/usr/bin/env bash
# run.sh —— skill 统一执行入口（自动探测 OS/ARCH + 查找二进制，skill 不感知环境）。
# 用法: scripts/run.sh <api-cli-args...>
# 例:   scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
#
# 所有路径相对 run.sh 自身定位（不依赖项目结构/REPO_ROOT），skill 换位置不影响。
#
# Go 二进制查找顺序：
#   ① bin/api-cli-<os>-<arch>（skill 自带预编译，按当前 OS/ARCH 选——零环境依赖）
#   ② bin/api-cli（兼容旧打包，单平台）
#   ③ PATH 上的 api-cli
#   ④ go build 增量编译（开发态，往上找 projects/api-cli）
set -euo pipefail

# --- 相对 run.sh 自身定位（skill 可在任意位置）---
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

# --- Go 二进制查找（全相对 SKILL_DIR）---
# ① 预编译按平台（分发态首选）
if [ -x "$SKILL_DIR/bin/api-cli-$OS-$ARCH" ]; then
    exec "$SKILL_DIR/bin/api-cli-$OS-$ARCH" "$@"
fi
# ② 兼容旧打包（单平台）
if [ -x "$SKILL_DIR/bin/api-cli" ]; then
    exec "$SKILL_DIR/bin/api-cli" "$@"
fi
# ③ PATH 上有
if command -v api-cli &>/dev/null; then
    exec api-cli "$@"
fi

# ④ 开发态 go build（从 SCRIPT_DIR 往上找 projects/api-cli，兼容 skill 在任意子目录）
_DEV_ROOT="$SCRIPT_DIR"
for _ in 1 2 3 4 5; do
    if [ -d "$_DEV_ROOT/projects/api-cli" ]; then
        export PATH="$PATH:$HOME/.local/go-parent/go/bin"
        BIN="$_DEV_ROOT/tmp/.api-orchestrator/api-cli"
        mkdir -p "$(dirname "$BIN")"
        ( cd "$_DEV_ROOT/projects/api-cli" && go build -o "$BIN" ./cmd/api-cli )
        exec "$BIN" "$@"
    fi
    _DEV_ROOT="$(dirname "$_DEV_ROOT")"
done

echo "run.sh: 找不到 api-cli（bin/api-cli-$OS-$ARCH / bin/api-cli / PATH / go build 均未命中）" >&2
echo "       分发态：确认 pack-go.sh 已预编译到 bin/" >&2
echo "       开发态：确认在项目仓库内（含 projects/api-cli/）" >&2
exit 1
