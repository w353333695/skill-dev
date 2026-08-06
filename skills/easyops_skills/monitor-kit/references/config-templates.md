# 配置文件模板

## plugin.yaml 模板

```yaml
type: simple-script
name: ${PLUGIN_NAME}
version: "${VERSION}"
command:
    collect:
        interpreter: ""
        scriptPath:
            - src
            - ${PLUGIN_NAME}.py
        type: python
        user: ""
params:
    - ip
    - port
    # 添加其他参数...
paramDefine:
    - name: ip
      valueType: string
      defaultValue: ""
      display: true
      displayName: "目标IP"
      description: "采集目标的IP地址"
      use: collectParams
      optional: false
      isFromSecret: false
      isEncrypt: false
      extraArgs: null
    - name: port
      valueType: string
      defaultValue: "161"
      display: true
      displayName: "端口"
      description: "采集目标的端口"
      use: collectParams
      optional: false
      isFromSecret: false
      isEncrypt: false
      extraArgs: null
    # CMDB实例字段引用示例
    - name: dim_field
      valueType: string
      defaultValue: $.dim_field    # 从CMDB实例获取
      display: true
      displayName: "维度字段"
      description: ""
      use: collectParams
      optional: false
      isFromSecret: false
      isEncrypt: false
      extraArgs: null
agentType: easyops
category: ${CATEGORY}
scriptType: python
interpreter: ""
memo: ""
icon: null
relateObjectId: ${MODEL_ID}
installPath: ${PLUGIN_NAME}
samplerType: metric_sampler
jobFilter: null
protected: false
noPackage: false
collectType: []
collectAgent: ""
group: []
rating: 0
metricbeatName: ""
processors: []
extInfo: null
```

## package.conf.yaml 模板

```yaml
---
proc_list: []
port_list: []
proc_guard: ~
port_guard: ~
start_script: ""
stop_script: ""
monitor_script: ""
user: ""
restart_script: ""
install_prescript: ""
install_postscript: ""
update_prescript: ""
update_postscript: ""
rollback_prescript: ""
rollback_postscript: ""
user_pre_check: ""
user_check_script: ""
...
```

## origin_metric.json 模板

```json
[
    {
        "agentType": "easyops",
        "dataType": "double",
        "instanceId": "",
        "key": "num_val",
        "labels": [],
        "metricType": "gauge",
        "tagDefine": [
            {"name": "dim1", "readOnly": false},
            {"name": "dim2", "readOnly": false}
        ]
    },
    {
        "agentType": "easyops",
        "dataType": "string",
        "instanceId": "",
        "key": "str_val",
        "labels": [],
        "metricType": "gauge",
        "tagDefine": [
            {"name": "dim1", "readOnly": false},
            {"name": "dim2", "readOnly": false}
        ]
    }
]
```

## alias_metric.json 模板

```json
[
    {
        "dataType": "double",
        "description": "",
        "dims": [
            {"dimDisplayName": "", "dimName": "dim1", "isArray": false, "originDimName": "dim1"},
            {"dimDisplayName": "", "dimName": "dim2", "isArray": false, "originDimName": "dim2"}
        ],
        "displayName": "数值指标",
        "expression": "",
        "metricSet": ["默认指标集"],
        "name": "num_val",
        "objectId": "${MODEL_ID}",
        "originalMetrics": ["num_val"],
        "type": "normal",
        "unit": ""
    },
    {
        "dataType": "string",
        "description": "",
        "dims": [
            {"dimDisplayName": "", "dimName": "dim1", "isArray": false, "originDimName": "dim1"},
            {"dimDisplayName": "", "dimName": "dim2", "isArray": false, "originDimName": "dim2"}
        ],
        "displayName": "文本指标",
        "expression": "",
        "metricSet": ["默认指标集"],
        "name": "str_val",
        "objectId": "${MODEL_ID}",
        "originalMetrics": ["str_val"],
        "type": "normal",
        "unit": ""
    }
]
```

## metric_set.json 模板

```json
[
    {"name": "默认指标集"}
]
```

## CMDB 模型 JSON 模板

```json
[
    {
        "attrList": [
            {
                "id": "name",
                "name": "名称",
                "protected": false,
                "custom": "true",
                "readonly": "false",
                "required": "true",
                "unique": "true",
                "tag": ["基本信息"],
                "value": {
                    "type": "str",
                    "regex": null,
                    "default_type": "value",
                    "default": null
                }
            },
            {
                "id": "is_monit",
                "name": "是否监控",
                "protected": false,
                "custom": "true",
                "readonly": "false",
                "required": "true",
                "unique": "false",
                "tag": ["基本信息"],
                "value": {
                    "type": "bool",
                    "default": false
                }
            }
        ],
        "relation_list": [],
        "name": "${MODEL_NAME}",
        "objectId": "${MODEL_ID}",
        "memo": "",
        "category": "${CATEGORY}",
        "protected": false
    }
]
```

## readme 模板

```
- 采集对象为${MODEL_ID}模型实例，根据需求自行添加
  - 必填字段说明...
- 采集任务中监控对象建议通过条件动态筛选，是否监控: true
```

## 变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| ${PLUGIN_NAME} | 插件名称 | 动环监控 |
| ${VERSION} | 版本号（时间戳） | 1769673511 |
| ${MODEL_ID} | CMDB模型ID | ENV_MONITOR_SYSTEM_MONITOR_POINTS |
| ${MODEL_NAME} | CMDB模型名称 | 动环监控点信息 |
| ${CATEGORY} | 分类 | 硬件相关、基础设施.数据中心 |
