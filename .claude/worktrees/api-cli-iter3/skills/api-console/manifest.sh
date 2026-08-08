# skills/api-console/manifest.sh
# skill 依赖声明（setup.sh / run.sh / pack-dist.sh 共用，bash source）。
# 用 bash 数组而非 yaml：setup.sh 在用户环境跑，不能依赖 pyyaml 解析。
#
# 格式：PROJECTS 数组，每项 "project名=cli名"
#   project 名 = projects/<name> 目录名 = dist 名（连字符）
#   cli 名     = console script 名（装好后 PATH 里的命令）
SKILL_NAME="api-console"
SKILL_VERSION="0.1.0"
PROJECTS=(
  "api-console=api-console"
  # "browser-recorder=browser-recorder"   # 若 skill 依赖多 project，按此追加
)
