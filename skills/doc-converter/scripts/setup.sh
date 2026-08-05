#!/usr/bin/env bash
# 通用 skill setup：读 manifest.sh，装好声明的 n 个 project CLI。
# 部署态跑一次。每个 skill 复制一份本脚本（内容通用，差异在 manifest.sh）。
#
# 可选环境变量:
#   SKILL_INDEX_URL  内部 PyPI index URL（透传给 uv/pipx/pip；不设用默认源）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDOR="$SKILL_DIR/vendor"
# shellcheck disable=SC1091
source "$SKILL_DIR/manifest.sh"

# 选工具 uv > pipx > pip
if command -v uv >/dev/null 2>&1; then TOOL=uv
elif command -v pipx >/dev/null 2>&1; then TOOL=pipx
elif command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1; then TOOL=pip
else
  echo "[setup] 需 uv / pipx / pip（装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh）" >&2
  exit 1
fi
# pip 模式检查 Python>=3.9（uv/pipx 自带 python 管理）
if [ "$TOOL" = pip ]; then
  PY="$(command -v python3 || command -v python)"
  "$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)' \
    || { echo "[setup] Python < 3.9，不支持" >&2; exit 1; }
fi
# 内部 PyPI index
if [ -n "${SKILL_INDEX_URL:-}" ]; then
  case "$TOOL" in
    uv)        export UV_INDEX_URL="$SKILL_INDEX_URL" ;;
    pipx|pip)  export PIP_INDEX_URL="$SKILL_INDEX_URL" ;;
  esac
fi

# 装一个 project：vendor whl 优先（离线），否则 PyPI 包名
install_one() {
  local name="$1" cli="$2"
  if command -v "$cli" >/dev/null 2>&1; then
    echo "[setup] $cli 已就绪，跳过"; return 0
  fi
  local uscore="${name//-/_}" src whl
  whl="$(ls "$VENDOR/$name"-*.whl "$VENDOR/$uscore"-*.whl 2>/dev/null | head -1 || true)"
  if [ -n "$whl" ]; then src="$whl"; else src="$name"; fi
  echo "[setup] 用 $TOOL 安装 $name（CLI: $cli）：$src"
  case "$TOOL" in
    uv)   uv tool install "$src" ;;
    pipx) pipx install "$src" ;;
    pip)  pip3 install --user "$src" 2>/dev/null || pip install --user "$src" ;;
  esac
}

for entry in "${PROJECTS[@]}"; do
  install_one "${entry%%=*}" "${entry#*=}"
done

# 自检
fail=0
for entry in "${PROJECTS[@]}"; do
  cli="${entry#*=}"
  command -v "$cli" >/dev/null 2>&1 || { echo "[setup] ⚠ $cli 不在 PATH" >&2; fail=1; }
done
if [ $fail -eq 0 ]; then
  echo "[setup] ✅ 全部就绪，skill 可直接调 CLI"
else
  echo "[setup] 部分 CLI 不在 PATH，通常装在 ~/.local/bin：" >&2
  echo "  export PATH=\$HOME/.local/bin:\$PATH" >&2
  exit 1
fi
