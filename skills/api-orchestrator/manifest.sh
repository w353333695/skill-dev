SKILL_NAME="api-orchestrator"
SKILL_VERSION="0.0.1"
# 依赖 golang project api-cli（被执行的系统 API 零件）。
# golang 不走 pack-dist.sh（python whl 流程），用 scripts/pack-go.sh api-cli 独立分发
# （AGENTS §6/§7）；setup.sh 检查 api-cli 是否在 PATH。
PROJECTS=()                  # 无 python project（pack-dist whl 流程不适用本 skill）
GOLANG_PROJECTS=("api-cli")  # golang，pack-go.sh 交叉编译分发
