# 工具包打包规范

## 目录结构

```
{tool_name}/          # 工具名称，如"OCP数据采集"
├── config            # 配置文件（JSON 格式，无扩展名）
└── script            # 脚本文件（Python 代码，无扩展名）
```

- `config` 和 `script` 均无文件扩展名
- `script` 内容即为生成的采集脚本代码
- 打包为 `{tool_name}.tar.gz`

## config 配置文件格式

```json
{
    "batchStrategy": null,
    "blackList": [],
    "containerSandbox": {
        "enable": false,
        "image": ""
    },
    "defaultAgents": [],
    "defaultExecUser": "root",
    "deleteAuthorizers": [],
    "envLinux": null,
    "envWindows": null,
    "execPreAuth": null,
    "execTimeWindowConfig": [],
    "execUser": "",
    "executeAuthorizers": [],
    "forceShutdown": false,
    "functionType": "",
    "inputs": [],
    "level": 0,
    "listVisible": true,
    "lockAgents": "",
    "outputDefs": [],
    "readAuthorizers": [],
    "readExecutionResultAuthorizers": [],
    "readOnly": false,
    "rootExecuteAuthorizers": [],
    "rootModifyAuthorizers": [],
    "sandboxRun": false,
    "systemHide": false,
    "tableDefs": [],
    "tags": [],
    "templateType": "",
    "timeout": 86400,
    "toolLibs": [],
    "type": "python",
    "updateAuthorizers": [],
    "vDesc": "",
    "vId": "",
    "vName": "1.0.0",
    "whiteList": [],
    "windowsDefaultExecUser": "System",
    "windowsOnlyActiveSession": false,
    "windowsSession": false
}
```

## inputs 字段规则

### 执行目标（固定，必须包含）

```json
{
    "name": "@agents",
    "type": "cmdbInstances",
    "memo": "",
    "cmdbAttrId": "ip",
    "cmdbObjectId": "HOST",
    "cascade": false,
    "label": "执行目标",
    "multiple": true,
    "required": true,
    "primitive": false
}
```

### 脚本变量参数

将脚本配置区域中的变量提取为 inputs 参数。常见类型映射：

| Python 变量类型 | input type | 说明 |
|----------------|-----------|------|
| str | string | 单行字符串 |
| int / float | string | 数值（字符串传递） |
| bool | string | 布尔值 |
| list | string | JSON 数组字符串 |

参数格式：

```json
{
    "name": "变量名",
    "type": "string",
    "memo": "参数说明",
    "cascade": false,
    "label": "参数显示名",
    "multiple": false,
    "required": true,
    "primitive": true,
    "default": "默认值"
}
```

## 脚本变量处理

原脚本配置区域的变量需要注释掉，改为从工具参数读取：

```python
# ============ 配置区域 ============
# 以下变量由工具参数传入，无需手动修改
# HOST = None
# ORG = None
# API_URL = "https://api.example.com"
# API_KEY = ""
# OBJECT_ID = "CLOUD_VM"
# =================================
```

## vId 生成规则

`vId` 为 32 位十六进制哈希码，使用 Python 生成：

```python
import hashlib
import time
vId = hashlib.md5(str(time.time()).encode()).hexdigest()
```

## vDesc 版本说明

描述本版本的功能或变更：

```json
"vDesc": "初始版本：\n1. 支持xxx数据采集\n2. 支持xxx数据同步到CMDB"
```
