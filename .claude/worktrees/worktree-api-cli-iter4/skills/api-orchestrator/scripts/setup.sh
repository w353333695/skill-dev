#!/usr/bin/env bash
# api-orchestrator setup（分发态，部署机跑一次）。
#
# Go skill 不需要 setup 装 runtime——预编译二进制 bin/api-cli 随 skill 打包，
# scripts/run.sh 自动找到它，零环境依赖（不装 whl、不配 PATH、不要 go）。
#
# 本脚本只做：
#   1. 确认 bin/api-cli 存在（不存在则 warn，run.sh 会 fallback）
#   2. platforms/ 设只读（写保护，防 orchestration 模式污染）
#   3. 跑 lint 自检 platforms 完整
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAT="$SKILL_DIR/platforms"

# 1. 确认 bin/api-cli 存在
if [ -x "$SKILL_DIR/bin/api-cli" ]; then
  echo "[setup] ✓ bin/api-cli 就绪（run.sh 自动引用，零环境依赖）"
else
  echo "[setup] ⚠ bin/api-cli 不存在——run.sh 会 fallback 到 PATH/go build"
  echo "        分发打包时请预编译：scripts/pack-go.sh → 拷到 bin/api-cli"
fi

# 2. platforms/ 只读（写保护）
if [ -d "$PLAT" ]; then
  if chmod -R a-w "$PLAT" 2>/dev/null; then
    echo "[setup] ✓ platforms/ 已设只读"
  else
    echo "[setup] ⚠ platforms/ 设只读失败（权限？）"
  fi
fi

# 3. lint 自检
if command -v python3 >/dev/null 2>&1 && [ -d "$PLAT" ]; then
  echo "[setup] lint platforms/ ..."
  python3 "$SCRIPT_DIR/lint-platforms.py" demo || echo "[setup] ⚠ lint 报错，onboarding 修正后再用"
fi

cat <<EOF
[setup] ✅ 就绪。零环境依赖：bin/api-cli 随 skill 打包，run.sh 自动找到。
  orchestration（默认）：platforms 只读，自然语言→编排执行。
  onboarding（改 platforms）：先 chmod -R u+w $PLAT，改完 lint 0 ERR 后 chmod -R a-w 锁回。
EOF
