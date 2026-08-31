#!/bin/bash
app_name="fintech_data"
data_base="/data/easyops"
install_base="/usr/local/easyops"
install_path="${install_base}/${app_name}"

#Log
log_path="${data_base}/${app_name}/log"
mkdir -p ${log_path} && ln -snf ${log_path} ${install_path}/log

#Data
data_path="${data_base}/${app_name}/data"
mkdir -p ${data_path} && ln -snf ${data_path} ${install_path}/data

export LD_LIBRARY_PATH=/usr/local/easyops/ens_client/sdk:${LD_LIBRARY_PATH}
#TODO: add pre-start script

#TODO: edit your start command
start_cmd="./bin/fintech_data"
cd ${install_path} && exec ${start_cmd}