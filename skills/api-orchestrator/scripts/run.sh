#!/usr/bin/env bash
# run.sh —— 通用 skill CLI 执行入口（Go / Python 均适用）。
# 用法: scripts/run.sh <cli-args...>
# 例:   scripts/run.sh --spec $PLATFORMS_ROOT/demo/easyops-itsm.yaml form list
#        （PLATFORMS_ROOT 见 orchestration.md「步骤 0」；run.sh 自动 export API_CLI_PLATFORMS_DIR）
#
# 所有路径相对 run.sh 自身定位，skill 换位置不影响。
# 自动读 manifest.sh 判断 Go/Python，查找顺序：
#   Go:   bin/<name> → bin/<name>-<os>-<arch> → PATH → go build
#   Py:   PATH(vendor whl 装后) → uv run --project projects/<name>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- 读 manifest.sh ---
# shellcheck disable=SC1091
source "$SKILL_DIR/manifest.sh" 2>/dev/null || {
    echo "run.sh: 找不到 manifest.sh（$SKILL_DIR/manifest.sh）" >&2; exit 1; }

# --- 部署根解析（platforms/auth/env 三者归一到 $API_CLI_DEPLOYMENT_ROOT）---
# 默认随调用方 cwd 项目走（$PWD/.api-orchestrator）；想固定则 shell rc 里 export API_CLI_DEPLOYMENT_ROOT。
# ⚠️ env 变量始终最高优先级覆盖；env.d/<dep>.env 里只放业务变量，不放路径变量（不自举）。
_APIORCH_ROOT="${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
: "${API_CLI_DEPLOYMENT_ROOT:=$_APIORCH_ROOT}"
: "${API_CLI_AUTH_D:=$_APIORCH_ROOT/auth.d}"
: "${API_CLI_ENV_FILE:=$_APIORCH_ROOT/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
: "${API_CLI_PLATFORMS_DIR:=$_APIORCH_ROOT/platforms}"
export API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT

# --- 自动加载非密环境变量（密钥由 api-cli 走 $API_CLI_AUTH_D，默认部署根/auth.d）---
# 约定：$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env 放 org/user/endpoint 等非密值；
#   调用方零传输——初始化一次后 run.sh 自动 source。opt-in：无文件即跳过。
#   API_CLI_ENV_FILE 直指文件；API_CLI_DEPLOYMENT 选部署（默认 demo）。
#   ⚠️ 文件里的值会覆盖 shell 已设的同名 env（set -a 导出）；想临时覆盖，调用前 export。
[ -f "$API_CLI_ENV_FILE" ] && { set -a; . "$API_CLI_ENV_FILE"; set +a; }

# --- Go skill ---
if [ "${#GOLANG_PROJECTS[@]}" -gt 0 ]; then
    BIN_NAME="${GOLANG_PROJECTS[0]}"

    # ① 预编译单平台（分发态首选）
    if [ -x "$SKILL_DIR/bin/$BIN_NAME" ]; then
        exec "$SKILL_DIR/bin/$BIN_NAME" "$@"
    fi
    # ② 兼容多平台打包
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    case "$ARCH" in x86_64|amd64) ARCH=amd64;; aarch64|arm64) ARCH=arm64;; esac
    if [ -x "$SKILL_DIR/bin/$BIN_NAME-$OS-$ARCH" ]; then
        exec "$SKILL_DIR/bin/$BIN_NAME-$OS-$ARCH" "$@"
    fi
    # ③ PATH
    if command -v "$BIN_NAME" >/dev/null 2>&1; then
        exec "$BIN_NAME" "$@"
    fi
    # ④ 开发态 go build（从 SCRIPT_DIR 往上找 projects/<name>）
    _DEV_ROOT="$SCRIPT_DIR"
    for _ in 1 2 3 4 5; do
        if [ -d "$_DEV_ROOT/projects/$BIN_NAME" ]; then
            export PATH="$PATH:$HOME/.local/go-parent/go/bin"
            BIN="$_DEV_ROOT/tmp/.$SKILL_NAME/$BIN_NAME"
            mkdir -p "$(dirname "$BIN")"
            ( cd "$_DEV_ROOT/projects/$BIN_NAME" && go build -ldflags "-s -w" -o "$BIN" ./cmd/"$BIN_NAME" )
            exec "$BIN" "$@"
        fi
        _DEV_ROOT="$(dirname "$_DEV_ROOT")"
    done

    echo "run.sh: 找不到 $BIN_NAME（bin/ / PATH / go build 均未命中）" >&2
    exit 1
fi

# --- Python skill ---
if [ "${#PROJECTS[@]}" -gt 0 ]; then
    ENTRY="${PROJECTS[0]}"
    PROJ_NAME="${ENTRY%%=*}"
    CLI_NAME="${ENTRY#*=}"

    # ① PATH（分发态——用户手动装过）
    if command -v "$CLI_NAME" >/dev/null 2>&1; then
        exec "$CLI_NAME" "$@"
    fi
    # ② 开发态 uv run
    _DEV_ROOT="$SCRIPT_DIR"
    for _ in 1 2 3 4 5; do
        if [ -d "$_DEV_ROOT/projects/$PROJ_NAME" ]; then
            exec uv run --project "$_DEV_ROOT/projects/$PROJ_NAME" "$CLI_NAME" "$@"
        fi
        _DEV_ROOT="$(dirname "$_DEV_ROOT")"
    done

    echo "run.sh: 找不到 $CLI_NAME（PATH / uv run 均未命中）" >&2
    exit 1
fi

echo "run.sh: manifest.sh 未声明 PROJECTS 或 GOLANG_PROJECTS" >&2
exit 1
