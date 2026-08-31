#!/bin/bash
# Name    : start_script.py
# Date    : 2016.03.28
# Func    : 启动脚本
# Note    : 注意：当前路径为应用部署文件夹

#############################################################
# 初始化环境

# 用户自定义
app_folder="fintech_data"                 # 项目根目录
install_base="/usr/local/easyops"       # 安装根目录
data_base="/data/easyops"             # 日志/数据根目录

# 通用前置
# ulimit 设定
ulimit -n 100000
export LD_LIBRARY_PATH=/usr/local/easyops/ens_client/sdk:${LD_LIBRARY_PATH}

# 日志目录
log_path="${data_base}/${app_folder}/log"
mkdir -p ${log_path}
cd ${install_base}/${app_folder} && ln -snf ${log_path} log

cd ${install_base}/${app_folder}
./deploy/entrypoint.sh >/dev/null 2>log/${app_folder}.err &

