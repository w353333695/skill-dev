#!/usr/bin/env bash
# 通用 golang project 分发打包：交叉编译全平台二进制 + zip 大礼包。
# 与 pack-dist.sh（python）完全独立，不共享逻辑、不读 manifest。
#
# 用法: scripts/pack-go.sh <project-name> [-o <dir>] [--targets <list>]
#          [--cmd <path>] [--version <ver>] [--ldflags <flags>] [--no-zip] [--no-strip]
#
# 产物（<dir> 由 -o 指定，默认 tmp/）:
#   <dir>/<name>-binaries-<ver>/
#     <name>-<ver>-<os>-<arch>[.exe]   各平台二进制（CGO=0 纯静态）
#     checksums.txt                    sha256 校验
#   <dir>/<name>-binaries-<ver>.zip    全平台大礼包
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

usage() {
  cat <<'EOF'
用法: pack-go.sh <project-name> [选项]
  <project-name>        projects/<name> 下的 golang project（必填）
选项:
  -o <dir>              输出根目录（默认 tmp/）
  --targets <list>      os/arch 逗号分隔，默认:
                        linux/amd64,linux/arm64,darwin/amd64,darwin/arm64,windows/amd64
                        （也可用 GO_TARGETS 环境变量覆盖）
  --cmd <path>          go 入口包路径（如 ./cmd/api-cli），默认自动探测
  --version <ver>       版本号，默认回退: VERSION env / git describe / dev
  --ldflags <flags>     透传 go ldflags（默认 -s -w，--no-strip 关）
  --no-zip              只留二进制目录，不打 zip 大礼包
  --no-strip            不加 -s -w，保留调试符号（排查 panic 用）
  -h, --help            显示本帮助
EOF
}

# 解析参数（位置参数 project-name 可在任意位置，取第一个非选项值）
while [ $# -gt 0 ]; do
  case "$1" in
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

[ -n "$NAME" ] || { usage >&2; echo "[pack-go] ✗ 缺少 <project-name>" >&2; exit 2; }

PROJ_DIR="$REPO_ROOT/projects/$NAME"
[ -f "$PROJ_DIR/go.mod" ] || {
  echo "[pack-go] ✗ 不是 golang project（缺 go.mod）: projects/$NAME" >&2; exit 1; }

# 输出根目录（转绝对：build 在 PROJ_DIR 子 shell 跑，相对 OUT_DIR 会被解析到
# projects/<name>/ 下而非调用方 cwd，导致产物写到错处）
[ -n "$OUT_DIR" ] || OUT_DIR="$REPO_ROOT/tmp"
case "$OUT_DIR" in
  /*) ;;
  *)  OUT_DIR="$PWD/$OUT_DIR" ;;
esac

# 版本回退链: --version → VERSION env → git describe --tags --always → dev
if [ -n "$OPT_VERSION" ]; then
  VER="$OPT_VERSION"
elif [ -n "${VERSION:-}" ]; then
  VER="$VERSION"
else
  VER="$(git -C "$PROJ_DIR" describe --tags --always 2>/dev/null || true)"
  [ -n "$VER" ] || VER="dev"
fi

# cmd 入口探测（命中即停，多 main 不猜）
detect_cmd() {
  # 1. 显式 --cmd
  if [ -n "$CMD_PATH" ]; then echo "$CMD_PATH"; return 0; fi
  # 2. ./cmd/<name>/（标准 go 项目约定）
  if [ -f "$PROJ_DIR/cmd/$NAME/main.go" ]; then echo "./cmd/$NAME"; return 0; fi
  # 3. ./cmd/ 下恰好一个 package main 子目录
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
  # 4. 都不命中 → 报错列候选
  echo "[pack-go] ✗ 无法确定 go 入口包，请用 --cmd <path> 显式指定（如 --cmd ./cmd/${NAME}）" >&2
  if [ -d "$PROJ_DIR/cmd" ]; then
    echo "  cmd/ 下子目录：" >&2
    ( cd "$PROJ_DIR/cmd" && ls -d */ ) >&2 2>/dev/null || true
  else
    echo "  （projects/$NAME 下没有 cmd/ 目录）" >&2
  fi
  echo "  解法: 1) 传 --cmd ./cmd/<dir>  2) 检查目录是否 package main  3) 若 main.go 在根，传 --cmd ." >&2
  return 1
}

CMD_PATH_RESOLVED="$(detect_cmd)" || exit 1

# targets（去空白，兼容 "a, b" 写法）
TARGETS_STR="${GO_TARGETS:-linux/amd64,linux/arm64,darwin/amd64,darwin/arm64,windows/amd64}"
[ -n "$OPT_TARGETS" ] && TARGETS_STR="$OPT_TARGETS"
TARGETS_STR="${TARGETS_STR//[[:space:]]/}"
IFS=',' read -ra TARGET_ARR <<< "$TARGETS_STR"

# ldflags：显式 > 默认(-s -w，--no-strip 关)
LDFLAGS="${OPT_LDFLAGS:-}"
if [ -z "$LDFLAGS" ] && [ "$NO_STRIP" -eq 0 ]; then
  LDFLAGS="-s -w"
fi

# 环境：纯静态 + 禁止偷偷下载 toolchain（go.mod 无 toolchain 行，老 go 会联网拉）
export CGO_ENABLED=0 GOTOOLCHAIN=local

OUT_SUBDIR="$OUT_DIR/$NAME-binaries-$VER"
echo "[pack-go] $NAME v$VER · targets: $TARGETS_STR"
echo "[pack-go] 入口: $CMD_PATH_RESOLVED  →  $OUT_SUBDIR"

mkdir -p "$OUT_SUBDIR"
# 重复运行时清旧产物（只删本 name 的二进制 + checksums，不删目录）
rm -f "$OUT_SUBDIR/$NAME"-* "$OUT_SUBDIR/checksums.txt"

# go 工具链（紧贴使用点校验：cmd 探测等纯文件操作已先跑完）
command -v go >/dev/null 2>&1 || {
  echo "[pack-go] ✗ 未找到 go 工具链（CGO=0 交叉编译需要 go）" >&2
  echo "  装 go: https://go.dev/dl/ 或 apt-get install golang-go" >&2
  exit 1
}

# 预下载依赖（best-effort，cache-only）：无外网或 go.sum 含其他平台专用依赖
# （如 cobra 的 windows-only mousetrap）导致全量 download 失败时，不阻断——
# go build 按目标平台用 cache，cache 真缺才在 build 阶段报错。
echo "[pack-go] go mod download（cache-only，best-effort）..."
if ! (cd "$PROJ_DIR" && GOPROXY=off go mod download) >/dev/null 2>&1; then
  echo "[pack-go]   本地 cache 不全或含其他平台专用依赖；build 改 cache-only（GOPROXY=off）" >&2
  export GOPROXY=off
fi

# 逐 target 编译（单 target 失败即退出）
ok_count=0
for t in "${TARGET_ARR[@]}"; do
  case "$t" in
    */*) os="${t%%/*}"; arch="${t#*/}" ;;
    *) echo "[pack-go] ✗ 无效 target '$t'（应为 os/arch，如 linux/amd64）" >&2; exit 1 ;;
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

# 非 windows 产物加可执行位（zip 里 +x 位在，解压可直接跑）
while IFS= read -r f; do chmod +x "$f"; done \
  < <(find "$OUT_SUBDIR" -type f ! -name '*.exe')

# checksums
( cd "$OUT_SUBDIR" && sha256sum "$NAME"-* > checksums.txt )
echo "[pack-go]   ✓ checksums.txt"

# zip 大礼包
ZIP=""
if [ "$NO_ZIP" -eq 0 ]; then
  ZIP="$OUT_DIR/$NAME-binaries-$VER.zip"
  echo "[pack-go] 压缩 -> $(basename "$ZIP")..."
  rm -f "$ZIP"
  ( CDPATH= cd "$OUT_DIR" && zip -qr "$ZIP" "$(basename "$OUT_SUBDIR")" )
fi

echo "[pack-go] ✅ $OUT_SUBDIR"
[ -n "$ZIP" ] && echo "[pack-go] ✅ $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "[pack-go] 使用: 解压 zip → 挑对应平台二进制（arm64 = aarch64 = Apple Silicon）→ chmod +x → 拷 PATH"
