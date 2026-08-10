SKILL_NAME="api-orchestrator"
SKILL_VERSION="0.0.1"
# 依赖 golang project api-cli（被执行的系统 API 零件）。
# 分发：manifest 框架的 pack-go.sh 读 GOLANG_PROJECTS 编译 api-cli，
#   -ldflags "-s -w" 精简二进制（~12M），输出到 skill 的 bin/api-cli（单平台）。
# 随 skill 打包分发 → scripts/run.sh 找 bin/api-cli exec（零环境依赖）。
# 打包时可指定目标平台（--goos/--goarch），只放一个二进制，减小分发包体积。
PROJECTS=()                  # 无 python project
GOLANG_PROJECTS=("api-cli")  # golang，manifest 框架 pack-go.sh 编译分发
