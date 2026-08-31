export LD_LIBRARY_PATH=/usr/local/easyops/ens_client/sdk:${LD_LIBRARY_PATH}

/usr/local/easyops/deploy_init/tools/config_tool update \
  --config "check_auth_token.enable|false" \
  --appID "deploy_init" \
  --namespaceName "common" \
  --updateExists=true

/usr/local/easyops/deploy_init/tools/config_tool release \
  --appID "deploy_init" \
  --namespaceName "common"

/usr/local/easyops/deploy_init/tools/restart_components_with_section.py common

/usr/local/easyops/deploy_init/tools/config_tool get \
  --appID "deploy_init" \
  --namespaceName "common" \
  --key "check_auth_token.enable"

sed -i 's/check_auth_token.enable = true/check_auth_token.enable = false/g' /usr/local/easyops/deploy_init/easy_env.ini

# cd /usr/local/ucpro/ucpro_service/bin/  && ./component_manager -o restart -f ../conf/restart_components.yaml -r

agent安装:待acl开放即可,策略
dmz代理:IP已申请,虚拟机制作中
地市金融元数据推送平台对接,待确认负责人

agent策略:
1. 直连
  - 源: 所有agent
  - 目标ip: server
  - 目标端口: 5511
2. 走代理
