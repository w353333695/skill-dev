#!/usr/bin/env bash
# pack-go.sh —— 预编译 api-cli 多平台二进制，输出到 skill 的 bin/ 目录。
# 分发打包时跑一次：交叉编译 linux/darwin × amd64/arm64 四平台（不含 windows）。
# 输出：bin/api-cli-<os>-<arch>（run.sh 按 uname 自动选）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
API_CLI_DIR="$REPO_ROOT/projects/api-cli"
OUT="$SKILL_DIR/bin"
mkdir -p "$OUT"

export PATH="$PATH:$HOME/.local/go-parent/go/bin"

PLATFORMS=(
    "linux/amd64"
    "linux/arm64"
    "darwin/amd64"
    "darwin/arm64"
)

for P in "${PLATFORMS[@]}"; do
    GOOS="${P%/*}"
    GOARCH="${P#*/}"
    BIN="$OUT/api-cli-$GOOS-$GOARCH"
    echo "[pack] $P → $BIN"
    ( cd "$API_CLI_DIR" && GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 go build -o "$BIN" ./cmd/api-cli )
done

echo "[pack] ✅ $(ls -1 "$OUT"/api-cli-* | wc -l) 个平台二进制已输出到 $OUT/"
ls -lh "$OUT"/api-cli-*
