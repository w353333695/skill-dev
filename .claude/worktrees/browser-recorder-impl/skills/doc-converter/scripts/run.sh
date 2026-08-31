#!/usr/bin/env bash
# 通用 skill dev 运行壳（仅开发态，不进分发包）：
#   run.sh <cli> [args...]  ->  uv run --project projects/<对应project> <cli> [args]
# 方便开发时直接测 skill，免记 --project 路径。分发态不用本壳（setup.sh 装好后裸调 CLI）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC1091
source "$SKILL_DIR/manifest.sh"

if [ $# -lt 1 ]; then
  echo "用法: run.sh <cli> [args...]（dev 壳，转发到 uv run --project）" >&2
  echo "  已注册 CLI:" >&2
  for e in "${PROJECTS[@]}"; do echo "    ${e#*=}  (project: ${e%%=*})" >&2; done
  exit 2
fi
CLI="$1"; shift
PROJ=""
for entry in "${PROJECTS[@]}"; do
  if [ "${entry#*=}" = "$CLI" ]; then PROJ="${entry%%=*}"; break; fi
done
[ -n "$PROJ" ] || { echo "[run] 未知 cli: ${CLI}（manifest 未声明）" >&2; exit 1; }

# 从 skill 目录向上查找含 projects/<name> 的目录（最多 5 级）——skill 可能位于
# 顶层 skills/ 或 .claude/skills/ 下，固定层级推导（原 ../..）在后者会指错位置。
# 与 api-orchestrator run.sh 的开发态查找同思路。
DEV_ROOT="$SKILL_DIR"
for _ in 1 2 3 4 5; do
  if [ -d "$DEV_ROOT/projects/$PROJ" ]; then
    exec uv run --project "$DEV_ROOT/projects/$PROJ" "$CLI" "$@"
  fi
  DEV_ROOT="$(dirname "$DEV_ROOT")"
done
echo "[run] 找不到 projects/$PROJ（从 $SKILL_DIR 向上 5 级未命中）" >&2
exit 1
