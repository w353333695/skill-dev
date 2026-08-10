SKILL_NAME="api-orchestrator"
SKILL_VERSION="0.0.1"
# 依赖 golang project api-cli（被执行的系统 API 零件）。
# 分发：pack-go.sh 交叉编译 api-cli 四平台 → 输出到 skill 的 bin/api-cli-<os>-<arch>
# → 随 skill 打包分发 → scripts/run.sh 按 uname 自动选平台二进制 exec（零环境依赖）。
# 消费方（manifest 框架）跑 pack-go.sh 时读 GOLANG_PROJECTS 编译，产物放 bin/。
PROJECTS=()                  # 无 python project
GOLANG_PROJECTS=("api-cli")  # golang，manifest 框架的 pack-go.sh 交叉编译分发
