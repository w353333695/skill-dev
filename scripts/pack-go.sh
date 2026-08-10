#!/usr/bin/env bash
# 通用 golang project 分发打包：交叉编译二进制 + zip 大礼包 / skill 打包。
#
# 两种模式：
#   ① 大礼包（默认）：pack-go.sh <project-name> [-o <dir>] [--targets ...] ...
#      产物：<dir>/<name>-binaries-<ver>/ + .zip（全平台二进制）
#
#   ② skill 打包（--skill）：pack-go.sh --skill <skill-name> [--target <os/arch>] [--dist]
#      读 skills/<skill>/manifest.sh 的 GOLANG_PROJECTS，编译到 skill bin/，
#      可选 --dist 打 tar.gz 整个 skill 分发包。
#
# 选项（通用）:
#   --cmd <path>          go 入口包路径（默认自动探测）
#   --version <ver>       版本号（默认 git describe / dev）
#   --ldflags <flags>     go ldflags（默认 -s -w，--no-strip 关）
#   --no-zip              不打 zip
#   --no-strip            保留调试符号
#   -h, --help
#
# 选项（--skill 模式专用）:
#   --skill <name>        读 manifest.sh，编译到 skill bin/
#   --target <os/arch>    单平台（默认当前平台），减小分发包体积
#   --dist                连 skill 整体打 tar.gz 到 tmp/
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NAME=""
OUT_DIR=""
OPT_TARGETS=""
CMD_PATH=""
OPT_VERSION=""
OPT_LDFLAGS=""
NO_ZIP=0
NO_STRIP=0
SKILL_MODE=0
SKILL_NAME_OPT=""
SKILL_TARGET=""
SKILL_DIST=0

usage() {
  cat <<'EOF'
用法:
  大礼包模式: pack-go.sh <project-name> [选项]
  skill 模式: pack-go.sh --skill <skill-name> [--target <os/arch>] [--dist]

选项（通用）:
  -o <dir>              输出根目录（默认 tmp/）
  --cmd <path>          go 入口包路径（如 ./cmd/api-cli），默认自动探测
  --version <ver>       版本号（默认 git describe / dev）
  --ldflags <flags>     go ldflags（默认 -s -w，--no-strip 关）
  --no-zip              不打 zip
  --no-strip            保留调试符号
  --targets <list>      [大礼包] os/arch 逗号分隔，默认:
                        linux/amd64,linux/arm64,darwin/amd64,darwin/arm64,windows/amd64
  -h, --help

选项（--skill 模式）:
  --skill <name>        读 skills/<name>/manifest.sh GOLANG_PROJECTS，编译到 bin/
  --target <os/arch>    单平台（默认当前平台），减小分发包体积
  --dist                连 skill 整体打 tar.gz 到 tmp/
EOF
}

# 解析参数
while [ $# -gt 0 ]; do
  case "$1" in
    --skill)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --skill 需要参数" >&2; exit 2; }
      SKILL_MODE=1; SKILL_NAME_OPT="$2"; shift 2 ;;
    --target)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --target 需要参数" >&2; exit 2; }
      SKILL_TARGET="$2"; shift 2 ;;
    --dist)   SKILL_DIST=1; shift ;;
    -o)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ -o 需要参数" >&2; exit 2; }
      OUT_DIR="$2"; shift 2 ;;
    --targets)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --targets 需要参数" >&2; exit 2; }
      OPT_TARGETS="$2"; shift 2 ;;
    --cmd)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --cmd 需要参数" >&2; exit 2; }
      CMD_PATH="$2"; shift 2 ;;
    --version)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --version 需要参数" >&2; exit 2; }
      OPT_VERSION="$2"; shift 2 ;;
    --ldflags)
      [ $# -ge 2 ] || { echo "[pack-go] ✗ --ldflags 需要参数" >&2; exit 2; }
      OPT_LDFLAGS="$2"; shift 2 ;;
    --no-zip)    NO_ZIP=1; shift ;;
    --no-strip)  NO_STRIP=1; shift ;;
    -h|--help)   usage; exit 0 ;;
    --)          shift; break ;;
    -*)          echo "[pack-go] ✗ 未知选项: $1（--help 查用法）" >&2; exit 2 ;;
    *)
      if [ -z "$NAME" ]; then NAME="$1"; shift
      else echo "[pack-go] ✗ 多余参数: $1" >&2; exit 2; fi ;;
  esac
done

# ===================== --skill 模式 =====================
if [ "$SKILL_MODE" -eq 1 ]; then
    SKILL_DIR="$REPO_ROOT/skills/$SKILL_NAME_OPT"
    [ -d "$SKILL_DIR" ] || { echo "[pack-go] ✗ skill 不存在: skills/$SKILL_NAME_OPT" >&2; exit 1; }
    # shellcheck disable=SC1091
    source "$SKILL_DIR/manifest.sh"

    [ "${#GOLANG_PROJECTS[@]}" -gt 0 ] || {
        echo "[pack-go] ✗ $SKILL_NAME_OPT 的 manifest.sh 未声明 GOLANG_PROJECTS" >&2; exit 1; }

    # 目标平台：--target > 当前平台
    if [ -n "$SKILL_TARGET" ]; then
        TGT_OS="${SKILL_TARGET%/*}"; TGT_ARCH="${SKILL_TARGET#*/}"
    else
        TGT_OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
        TGT_ARCH="$(uname -m)"
        case "$TGT_ARCH" in x86_64|amd64) TGT_ARCH=amd64;; aarch64|arm64) TGT_ARCH=arm64;; esac
    fi

    LDFLAGS="${OPT_LDFLAGS:--s -w}"
    export CGO_ENABLED=0 GOTOOLCHAIN=local
    SKILL_BIN="$SKILL_DIR/bin"
    mkdir -p "$SKILL_BIN"

    # go 工具链
    command -v go >/dev/null 2>&1 || {
        export PATH="$PATH:$HOME/.local/go-parent/go/bin"
        command -v go >/dev/null 2>&1 || { echo "[pack-go] ✗ 未找到 go 工具链" >&2; exit 1; }
    }

    for proj in "${GOLANG_PROJECTS[@]}"; do
        PROJ_DIR="$REPO_ROOT/projects/$proj"
        [ -f "$PROJ_DIR/go.mod" ] || { echo "[pack-go] ✗ projects/$proj/go.mod 不存在" >&2; exit 1; }

        # cmd 入口探测
        if [ -n "$CMD_PATH" ]; then CMD_RESOLVED="$CMD_PATH"
        elif [ -f "$PROJ_DIR/cmd/$proj/main.go" ]; then CMD_RESOLVED="./cmd/$proj"
        else
            CMD_RESOLVED="$(cd "$PROJ_DIR" && find cmd -maxdepth 1 -type d 2>/dev/null | head -1)"
            [ -n "$CMD_RESOLVED" ] || { echo "[pack-go] ✗ 无法确定 $proj 入口包，用 --cmd" >&2; exit 1; }
            CMD_RESOLVED="./$CMD_RESOLVED"
        fi

        echo "[pack-go] skill=$SKILL_NAME_OPT project=$proj target=$TGT_OS/$TGT_ARCH ldflags='$LDFLAGS'"
        ( cd "$PROJ_DIR" && GOOS="$TGT_OS" GOARCH="$TGT_ARCH" go build \
            -trimpath -buildvcs=false -ldflags "$LDFLAGS" \
            -o "$SKILL_BIN/$proj" "$CMD_RESOLVED" )
        chmod +x "$SKILL_BIN/$proj"
        echo "[pack-go]   ✓ bin/$proj ($(du -h "$SKILL_BIN/$proj" | cut -f1))"
    done

    # --dist：连 skill 整体打包
    if [ "$SKILL_DIST" -eq 1 ]; then
        TS="$(date +%Y%m%d%H%M%S)"
        DIST="$REPO_ROOT/tmp/${SKILL_NAME}-${TS}.tar.gz"
        # 收集 skill 文件（排除 __pycache__、.pyc、bin 里的旧多平台二进制）
        ( CDPATH= cd "$REPO_ROOT" && tar czf "$DIST" \
            --transform="s,^skills/$SKILL_NAME,$SKILL_NAME," \
            --exclude='__pycache__' --exclude='*.pyc' \
            --exclude='bin/api-cli-*-*' \
            "skills/$SKILL_NAME" 2>/dev/null )
        echo "[pack-go] ✅ $DIST ($(du -h "$DIST" | cut -f1))"
        echo "[pack-go] 分发: 解压到 skill 目录 → scripts/run.sh 自动找 bin/$proj"
    else
        echo "[pack-go] ✅ 编译完成，bin/ 已就绪（加 --dist 打 tar.gz 分发包）"
    fi
    exit 0
fi

# ===================== 大礼包模式（原有逻辑）=====================
[ -n "$NAME" ] || { usage >&2; echo "[pack-go] ✗ 缺少 <project-name> 或 --skill <name>" >&2; exit 2; }

PROJ_DIR="$REPO_ROOT/projects/$NAME"
[ -f "$PROJ_DIR/go.mod" ] || {
  echo "[pack-go] ✗ 不是 golang project（缺 go.mod）: projects/$NAME" >&2; exit 1; }

# 输出根目录
[ -n "$OUT_DIR" ] || OUT_DIR="$REPO_ROOT/tmp"
case "$OUT_DIR" in
  /*) ;;
  *)  OUT_DIR="$PWD/$OUT_DIR" ;;
esac

# 版本回退链
if [ -n "$OPT_VERSION" ]; then
  VER="$OPT_VERSION"
elif [ -n "${VERSION:-}" ]; then
  VER="$VERSION"
else
  VER="$(git -C "$PROJ_DIR" describe --tags --always 2>/dev/null || true)"
  [ -n "$VER" ] || VER="dev"
fi

# cmd 入口探测
detect_cmd() {
  if [ -n "$CMD_PATH" ]; then echo "$CMD_PATH"; return 0; fi
  if [ -f "$PROJ_DIR/cmd/$NAME/main.go" ]; then echo "./cmd/$NAME"; return 0; fi
  if [ -d "$PROJ_DIR/cmd" ]; then
    local mains=() d
    while IFS= read -r d; do
      if grep -rqE '^[[:space:]]*package[[:space:]]+main([[:space:]]|$)' \
           "$d"/*.go 2>/dev/null; then
        mains+=("$d")
      fi
    done < <(find "$PROJ_DIR/cmd" -mindepth 1 -maxdepth 1 -type d | sort)
    if [ "${#mains[@]}" -eq 1 ]; then
      d="${mains[0]}"
      echo "./${d#"$PROJ_DIR/"}"
      return 0
    fi
  fi
  echo "[pack-go] ✗ 无法确定 go 入口包，请用 --cmd <path> 显式指定" >&2
  return 1
}

CMD_PATH_RESOLVED="$(detect_cmd)" || exit 1

# targets
TARGETS_STR="${GO_TARGETS:-linux/amd64,linux/arm64,darwin/amd64,darwin/arm64,windows/amd64}"
[ -n "$OPT_TARGETS" ] && TARGETS_STR="$OPT_TARGETS"
TARGETS_STR="${TARGETS_STR//[[:space:]]/}"
IFS=',' read -ra TARGET_ARR <<< "$TARGETS_STR"

# ldflags
LDFLAGS="${OPT_LDFLAGS:-}"
if [ -z "$LDFLAGS" ] && [ "$NO_STRIP" -eq 0 ]; then
  LDFLAGS="-s -w"
fi

export CGO_ENABLED=0 GOTOOLCHAIN=local

OUT_SUBDIR="$OUT_DIR/$NAME-binaries-$VER"
echo "[pack-go] $NAME v$VER · targets: $TARGETS_STR"
echo "[pack-go] 入口: $CMD_PATH_RESOLVED  →  $OUT_SUBDIR"

mkdir -p "$OUT_SUBDIR"
rm -f "$OUT_SUBDIR/$NAME"-* "$OUT_SUBDIR/checksums.txt"

command -v go >/dev/null 2>&1 || {
  echo "[pack-go] ✗ 未找到 go 工具链" >&2; exit 1; }

echo "[pack-go] go mod download（cache-only，best-effort）..."
if ! (cd "$PROJ_DIR" && GOPROXY=off go mod download) >/dev/null 2>&1; then
  echo "[pack-go]   cache 不全；build 改 cache-only" >&2
  export GOPROXY=off
fi

ok_count=0
for t in "${TARGET_ARR[@]}"; do
  case "$t" in
    */*) os="${t%%/*}"; arch="${t#*/}" ;;
    *) echo "[pack-go] ✗ 无效 target '$t'" >&2; exit 1 ;;
  esac
  ext=""
  [ "$os" = "windows" ] && ext=".exe"
  out_file="$OUT_SUBDIR/$NAME-$VER-$os-$arch$ext"
  echo "[pack-go] 编译 $os/$arch ..."
  (cd "$PROJ_DIR" && GOOS="$os" GOARCH="$arch" go build \
    -trimpath -buildvcs=false -ldflags "$LDFLAGS" \
    -o "$out_file" "$CMD_PATH_RESOLVED")
  echo "[pack-go]   ✓ $(basename "$out_file") ($(du -h "$out_file" | cut -f1))"
  ok_count=$((ok_count + 1))
done
echo "[pack-go] 全部 ${ok_count} 个 target 编译完成"

while IFS= read -r f; do chmod +x "$f"; done \
  < <(find "$OUT_SUBDIR" -type f ! -name '*.exe')

( cd "$OUT_SUBDIR" && sha256sum "$NAME"-* > checksums.txt )
echo "[pack-go]   ✓ checksums.txt"

ZIP=""
if [ "$NO_ZIP" -eq 0 ]; then
  ZIP="$OUT_DIR/$NAME-binaries-$VER.zip"
  echo "[pack-go] 压缩 -> $(basename "$ZIP")..."
  rm -f "$ZIP"
  ( CDPATH= cd "$OUT_DIR" && zip -qr "$ZIP" "$(basename "$OUT_SUBDIR")" )
fi

echo "[pack-go] ✅ $OUT_SUBDIR"
[ -n "$ZIP" ] && echo "[pack-go] ✅ $ZIP ($(du -h "$ZIP" | cut -f1))"
