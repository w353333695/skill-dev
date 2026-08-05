#!/usr/bin/env bash
# 通用 skill 分发打包：读 skills/<skill>/manifest.sh，打 n 个 project whl + skill
# -> tmp/<skill>-dist-<ver>.zip
#
# 不含 platforms/（外部可拔插部件，由 skill 方自行分发）
# 不含 scripts/run.sh（dev 壳，仅开发用，不进分发）
#
# 用法: scripts/pack-dist.sh <skill-name>
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -ge 1 ] || { echo "用法: pack-dist.sh <skill-name>" >&2; exit 2; }
SKILL_NAME_ARG="$1"
SKILL_DIR="$REPO_ROOT/skills/$SKILL_NAME_ARG"
[ -d "$SKILL_DIR" ] || { echo "[pack] skill 不存在: skills/$SKILL_NAME_ARG" >&2; exit 1; }
# shellcheck disable=SC1091
source "$SKILL_DIR/manifest.sh"

ZIP="$REPO_ROOT/tmp/${SKILL_NAME}-dist-${SKILL_VERSION}.zip"
VENDOR="$SKILL_DIR/vendor"
echo "[pack] $SKILL_NAME v$SKILL_VERSION，projects: ${PROJECTS[*]}"

# 1. 打每个 project 的 whl，塞进 skill 的 vendor/
mkdir -p "$VENDOR"
rm -f "$VENDOR"/*.whl 2>/dev/null || true
for entry in "${PROJECTS[@]}"; do
  name="${entry%%=*}"
  proj_dir="$REPO_ROOT/projects/$name"
  [ -d "$proj_dir" ] || { echo "[pack] ✗ project 不存在: projects/$name" >&2; exit 1; }
  echo "[pack] 打 whl: $name"
  (cd "$proj_dir" && uv build) >/dev/null 2>&1
  whl="$(ls "$proj_dir/dist/${name//-/_}"-*.whl 2>/dev/null | head -1 || true)"
  [ -f "$whl" ] || { echo "[pack] ✗ $name whl 未生成" >&2; exit 1; }
  cp "$whl" "$VENDOR/"
  echo "[pack]   $(basename "$whl")"
done
trap 'rm -f "$VENDOR"/*.whl; rmdir "$VENDOR" 2>/dev/null || true' EXIT

# 2. zip skill（含 vendor whl + setup.sh + manifest + SKILL.md/references/evals）
#    排除 dev run.sh + __pycache__/pyc
echo "[pack] 压缩 -> $(basename "$ZIP")..."
rm -f "$ZIP"
(CDPATH= cd "$REPO_ROOT" && zip -qr "$ZIP" "skills/$SKILL_NAME" \
  -x '*/__pycache__/*' '*.pyc' '*/scripts/run.sh')

echo "[pack] ✅ $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "[pack] 使用: 解压到 workspace 根 -> bash skills/$SKILL_NAME/scripts/setup.sh"
