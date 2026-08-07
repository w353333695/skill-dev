#!/usr/bin/env bash
# browser-manual：步骤 1-3 确定性 CLI 编排。
#
# 用法：
#   scripts/run.sh --system <sys> --url <url> --scenario <scn>
#                  [--login-url <u>] [--root <dir>] [--reauth] [--headed|--headless]
#
# 产出：<root>/<system>/exports/<scenario>/{report.md,requests.json,structure.json,screenshots_annotated/}
# 步骤 4（主题过滤 → requests.theme.json + 接口清单.md）与 5（manual.md）由 skill 内 Claude 语义完成。
set -euo pipefail

SYSTEM="" URL="" SCENARIO="" LOGIN_URL=""
ROOT="${BROWSER_RECORDINGS_ROOT:-./.browser-recordories}"
REAUTH=0 HEADLESS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --system)    SYSTEM="$2"; shift 2;;
    --url)       URL="$2"; shift 2;;
    --scenario)  SCENARIO="$2"; shift 2;;
    --login-url) LOGIN_URL="$2"; shift 2;;
    --root)      ROOT="$2"; shift 2;;
    --reauth)    REAUTH=1; shift;;
    --headless)  HEADLESS=1; shift;;
    --headed)    HEADLESS=0; shift;;
    -h|--help)
      sed -n '2,9p' "$0"; exit 0;;
    *) echo "未知参数: $1（用 -h 看用法）" >&2; exit 2;;
  esac
done
[[ -n "$SYSTEM" && -n "$URL" && -n "$SCENARIO" ]] || { echo "用法: $0 --system <sys> --url <url> --scenario <scn> [--login-url <u>] [--root <dir>] [--reauth] [--headless]" >&2; exit 2; }
LOGIN_URL="${LOGIN_URL:-$URL}"
OUT="$ROOT/$SYSTEM"
HEADED_FLAG="--headed"; [[ "$HEADLESS" == "1" ]] && HEADED_FLAG="--headless"
mkdir -p "$OUT"

# 定位 browser-recorder CLI：优先 PATH，否则用 uv run --project 跑仓库内实例
if command -v browser-recorder >/dev/null 2>&1; then
  BR=(browser-recorder)
else
  ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  BR_DIR="$ROOT_DIR/projects/browser-recorder"
  [[ -d "$BR_DIR" ]] || { echo "找不到 projects/browser-recorder（$BR_DIR）；请先 uv sync 或把 browser-recorder 装进 PATH" >&2; exit 1; }
  BR=(uv run --project "$BR_DIR" browser-recorder)
fi

# 步骤 1：登录态保障
#   --reauth：强制先重登（profile 名 = system 名），再录制。
#   否则：直接 record——recorder 在 headed 下检测到 profile 缺失/过期会自动弹登录窗、
#         抓 storage_state 存入 profile 再正式录制（首次登录动作即被剔除，后续复用）。
if [[ "$REAUTH" == "1" ]]; then
  if [[ "$HEADLESS" == "1" ]]; then
    echo "[browser-manual] --reauth 需要 --headed（无头无法人工登录）" >&2; exit 2
  fi
  echo "[browser-manual] --reauth：请在弹出浏览器完成 $SYSTEM 登录，登录后回终端按回车。"
  "${BR[@]}" auth refresh "$SYSTEM" --url "$LOGIN_URL" --out-dir "$OUT" --headed
fi

# 步骤 2：录制（A2 默认全捕、不传 --interactive-only；headed 便于人工操作）
echo "[browser-manual] 录制中：操作完成后按 Ctrl/Cmd+Shift+X 或关浏览器结束。"
"${BR[@]}" record --url "$URL" --auth "$SYSTEM" --name "$SCENARIO" --out-dir "$OUT" $HEADED_FLAG

# 步骤 3：导出（A1 默认 md；A3 自动产 structure.json）
"${BR[@]}" export "$SCENARIO" --out-dir "$OUT" --format md

echo "[browser-manual] 步骤 1-3 完成。产物在：$OUT/exports/$SCENARIO/"
echo "[browser-manual] 接下来由 Claude 做步骤 4（主题过滤）+ 5（手册分章）。"
