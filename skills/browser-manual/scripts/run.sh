#!/usr/bin/env bash
# 通用 skill dev 运行壳（仅开发态，不进分发包）：
#   run.sh <guide_dir> […]  ->  uv run --project projects/browser-recorder python scripts/prepare_guide_images.py <guide_dir> […]
# 依赖 Pillow：复用 browser-recorder 项目 venv（dev 态；分发态请用含 Pillow 的环境跑 .py）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 从 skill 目录向上查找含 projects/browser-recorder 的目录（最多 5 级），
# 与 doc-converter / api-orchestrator 的 dev 壳同思路——不依赖当前工作目录。
DEV_ROOT="$SCRIPT_DIR"
for _ in 1 2 3 4 5; do
  if [ -d "$DEV_ROOT/projects/browser-recorder" ]; then
    exec uv run --project "$DEV_ROOT/projects/browser-recorder" \
      python "$SCRIPT_DIR/prepare_guide_images.py" "$@"
  fi
  DEV_ROOT="$(dirname "$DEV_ROOT")"
done
echo "[run] 找不到 projects/browser-recorder（从 $SCRIPT_DIR 向上 5 级未命中）" >&2
exit 1
