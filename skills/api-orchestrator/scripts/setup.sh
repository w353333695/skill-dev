#!/usr/bin/env bash
# api-orchestrator setup（分发态，部署机跑一次）。
#
# 与 python skill 的 setup.sh 不同：本 skill 依赖 golang project(api-cli)，
# 不装 whl——api-cli 由 scripts/pack-go.sh 独立交叉编译分发（AGENTS §6/§7），
# 用户挑平台二进制拷 ~/.local/bin/api-cli。本脚本只做：
#   1. 检查 api-cli 可用（PATH 或本地 vendor/bin 兜底）
#   2. platforms/ 设只读（写保护，防 orchestration 模式污染）
#   3. 跑 lint 自检 platforms 完整
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAT="$SKILL_DIR/platforms"

# 1. api-cli 可用？
if command -v api-cli >/dev/null 2>&1; then
  echo "[setup] ✓ api-cli: $(command -v api-cli)"
elif [ -x "$SKILL_DIR/vendor/bin/api-cli" ]; then
  echo "[setup] ✓ 本地 vendor/bin/api-cli（建议拷 PATH：cp $SKILL_DIR/vendor/bin/api-cli ~/.local/bin/）"
else
  cat >&2 <<EOF
[setup] ✗ api-cli 不在 PATH。
  装（开发机/构建机跑）：scripts/pack-go.sh api-cli -o tmp/
    → 解压 tmp/api-cli-binaries-*/  挑对应平台（arm64=aarch64=Apple Silicon）
    → chmod +x api-cli-*-<os>-<arch>
    → 拷 ~/.local/bin/api-cli（确认 ~/.local/bin 在 PATH）
  详见 projects/api-cli/README.md「分发打包」。
EOF
  exit 1
fi

# 2. platforms/ 只读（写保护）—— orchestration 模式防污染
if [ -d "$PLAT" ]; then
  if chmod -R a-w "$PLAT" 2>/dev/null; then
    echo "[setup] ✓ platforms/ 已设只读（写保护：orchestration 模式不会误改）"
  else
    echo "[setup] ⚠ platforms/ 设只读失败（权限不足？以当前用户看是只读态即可）"
  fi
fi

# 3. lint 自检（python3 在的话）
if command -v python3 >/dev/null 2>&1 && [ -d "$PLAT" ]; then
  echo "[setup] lint platforms/ ..."
  python3 "$SCRIPT_DIR/lint-platforms.py" demo || echo "[setup] ⚠ lint 报错（见上），onboarding 修正后再用"
fi

cat <<EOF
[setup] ✅ 就绪。
  orchestration 模式（默认 /api-orchestrator）：platforms 只读，自然语言→编排执行。
  onboarding 模式（改 platforms，/api-orchestrator onboarding）：先解锁
    chmod -R u+w $PLAT
  改完跑 lint（0 ERR）后再 chmod -R a-w 锁回。
EOF
