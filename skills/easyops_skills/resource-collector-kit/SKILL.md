---
name: resource-collector-kit
description: 开发 EasyOps 资源信息采集套件（simple-script 类型），生成完整插件 zip 包（配置文件、采集脚本、模型定义、资源发现定义），支持从 API 文档自动生成采集逻辑、采集测试、导入/更新到平台。
version: 0.1.0
---
# EasyOps 资源采集套件开发指南

本 skill 用于指导开发 EasyOps 平台的资源信息采集插件（simple-script 类型），采集配置信息写入 CMDB。

与监控插件的区别：

- **监控插件**：采集性能指标（时序数据），输出 dims + vals（指标值）
- **资源采集套件**：采集配置信息（CMDB 实例数据），输出通过 GATHERING DATA 标记包裹，写入 CMDB

## 插件结构

```
插件名称/
├── plugin.yaml                    # 插件主配置（必需）
├── package.conf.yaml              # 部署配置（必需）
├── <MODEL_ID>.json                # 采集目标 CMDB 模型定义（必需）
├── resource_discovery_define.json # 资源发现定义（必需）
├── origin_metric.json             # 空列表 []（必需）
├── image.png                      # logo（可选）
├── readme                         # 使用说明（必需）
├── src/                           # 采集脚本目录（必需）
│   ├── <ScriptName>.orig          # 源代码（不含环境变量）
│   └── <ScriptName>.py            # 运行代码（含环境变量）
├── alertRule/                     # 留空
├── dashboard/                     # 留空
└── pic/                           # 留空
```

## 开发流程

### 步骤 1 — 收集需求信息

向用户收集以下信息：

- **采集目标描述**：什么设备/资源的什么信息
- **数据源类型**：Redfish / SNMP / HTTP API / 自定义协议
- **API 文档**：URL / 文件路径 / 纯文字描述
- **采集目标 CMDB 模型 ID**（如已有）

### 步骤 2 — 获取 CMDB 模型定义

```bash
python scripts/get_model.py --model-id MODEL_ID --host <easyops_host> --org <org_id>
```

- 列出模型的所有属性，标注哪些需要采集
- **如果模型属性不足以支持采集数据的写入，自动在模型 JSON 中添加缺失属性**
- 如果模型不存在，引导用户创建

### 步骤 3 — 分析参数来源（关键步骤）

分析每个采集参数的最佳获取方式：

| 参数类型              | defaultValue     | isFromSecret | 示例                 |
| --------------------- | ---------------- | ------------ | -------------------- |
| CMDB 实例属性自动获取 | `$.field_name` | false        | ip, instanceId, port |
| 用户手动填写          | `""`           | false        | 自定义参数           |
| 密钥管理获取          | `""`           | true         | username, password   |

**原则**：尽可能从 CMDB 实例中获取参数（如 IP、端口、SNMP 团体字等），减少用户手动配置。

常见参数设计：

| 参数          | 建议来源             | 说明                            |
| ------------- | -------------------- | ------------------------------- |
| instanceId    | `$.instanceId`     | 实例 ID，必须自动获取           |
| ip            | `$.ip`             | 设备 IP，从实例获取             |
| port          | `$.port` 或 `""` | 端口，视模型情况                |
| user/username | 密钥管理             | 认证用户名                      |
| password      | 密钥管理 + isEncrypt | 认证密码                        |
| secretName    | `""` display:false | 密钥实例名称                    |

> **⚠️ `$.xxx` 引用约束（重要，违反会报错）**：`defaultValue: $.field` 中的 `field` **必须是关联 CMDB 模型（`relateObjectId`，含继承链）真实存在的属性**。平台导入时会校验，引用了模型中不存在的字段会报错「$.类型的参数要来源于cmdb模型且有应用场景」。因此：
> - 只把**设备/资源自身的属性**（IP、端口、认证结构体、实例ID 等）用 `$.xxx` 引用
> - **agent 运行环境相关的东西**（如 CLI 命令路径、工具目录）**不是设备属性**，绝不能用 `$.xxx`——要么作为普通自定义入参（`defaultValue: ""`，`display: true`，由用户按需填写），要么直接在脚本里依赖系统 PATH，不设为参数
> - 拿不准某字段是否存在于模型时，用 `scripts/get_model.py` 查 `attrList` 确认后再引用

**结构体认证字段（重要）**：当模型上已有结构体类型的认证字段（如网络设备 `BASE_NETWARE` 继承的 `auth` 字段，含 `snmpVersion` / `community` / `securityLevel` / `securityName` / `authProtocol` / `authKey` / `privProtocol` / `privKey` / `contextName`），**优先用 `$.auth` 整体获取**，而不是把团体字/版本/用户名/密码拆成多个独立入参。这样：

- 用户在 CMDB 实例上一次性维护认证信息，采集插件无需重复配置
- 支持 SNMPv3 完整认证（authPriv 等）而不用增加入参数量
- 脚本中解析 `auth` 结构体（资源采集套件参数经环境变量传递，struct 为 **JSON 字符串**，需 `json.loads`）构造 SNMP 客户端

```yaml
- name: auth
  valueType: string         # struct 字段以 string(JSON) 传入
  defaultValue: $.auth
  display: false
  isFromSecret: false       # 来自实例字段而非密钥管理
```

```python
auth = json.loads(os.environ.get("EASYOPS_COLLECTOR_auth", "{}") or "{}")
snmp_version = auth.get("snmpVersion", "2c")
community = auth.get("community", "")
# v3 完整字段
security_level = auth.get("securityLevel", "")
security_name = auth.get("securityName", "")
auth_protocol = auth.get("authProtocol", "")
auth_key = auth.get("authKey", "")
priv_protocol = auth.get("privProtocol", "")
priv_key = auth.get("privKey", "")
```

> **⚠️ struct 参数类型：资源采集套件里是 JSON 字符串（需 `json.loads`）。**
> 资源采集套件（simple-script）的参数经**环境变量** `EASYOPS_COLLECTOR_argname` 传递，环境变量只能是字符串，故 struct 类型参数（如 `auth`）是 **JSON 字符串**，脚本必须用 `json.loads` 解析（见上）。
>
> **注意与巡检套件（inspection-kit）的区别**：巡检套件（agent）的 struct 参数是**全局变量直接注入的 dict（原始类型）**，不需要也不应该 `json.loads`。本套件（资源采集）用环境变量传参，struct 是 JSON 字符串，两者机制不同，不要互相照搬。

**CLI 命令路径与 PATH 回退**：当采集脚本通过 CLI 命令（如 `mysql`、`snmpwalk`、`snmpget`）采集数据时，目标 agent 机器上命令可能不在系统 PATH 中。正确做法是**脚本内先检查命令是否可执行，不可执行则给出明确报错**，让用户在 agent 机器上把命令加入 PATH，或安装到 PATH 标准目录。

> **⚠️ 不要把 agent 端命令路径设计成 `$.installPath` 入参**。`installPath` 是 **agent 运行环境的工具路径**，不是被采集设备/资源的属性，模型中没有这个字段，用 `$.installPath` 引用会触发「$.类型的参数要来源于cmdb模型且有应用场景」报错。如确需让用户自定义命令路径，应作为**普通自定义入参**（`defaultValue: ""`，`display: true`），由用户手动填写，而非从 CMDB 实例引用。

### 步骤 4 — 生成插件脚手架

使用脚本自动创建目录结构和配置文件：

```bash
.venv/bin/python3 scripts/generate_scaffold.py \
    --name "插件名称" \
    --model-id "MODEL_ID" \
    --script-name "ScriptName" \
    --category "分类" \
    --memo "插件描述" \
    --params '[
        {"name":"instanceId","defaultValue":"$.instanceId","isFromSecret":false,
         "displayName":"实例ID","description":"CMDB实例ID","display":true,
         "valueType":"string","optional":false,"isEncrypt":false},
        {"name":"ip","defaultValue":"$.ip","isFromSecret":false,
         "displayName":"IP地址","description":"目标IP","display":true,
         "valueType":"string","optional":false,"isEncrypt":false},
        {"name":"user","defaultValue":"","isFromSecret":true,
         "displayName":"用户名","description":"","display":true,
         "valueType":"string","optional":false,"isEncrypt":false},
        {"name":"password","defaultValue":"","isFromSecret":true,
         "displayName":"密码","description":"","display":true,
         "valueType":"password","optional":false,"isEncrypt":true}
    ]' \
    --collect-agent '$.ip' \
    --group '["remoteScan","cloudTypePrivateCloud","collectContentResourceInfo"]' \
    --output-dir "./output"
```

可选参数：

- `--model-json <path>`：复制模型 JSON 到插件目录
- `--discovery-models '<json>'`：资源发现模型列表
- `--install-path <path>`：安装路径

脚本自动创建完整目录结构，生成 plugin.yaml、package.conf.yaml、origin_metric.json、resource_discovery_define.json、readme 模板和采集脚本骨架。

### 步骤 5 — 生成采集脚本

LLM 根据以下信息生成采集脚本：

1. API 文档（步骤 1 收集）— 如果有 URL/文件，使用 LLM 直接解析或 doc_reader.py 脚本读取
2. 模型属性（步骤 2 获取）— 确定 vals 中需要输出哪些字段
3. `references/collect-template.md` — 脚本结构和输出格式规范

生成两个文件：

**`.orig` 文件**：不含环境变量获取，参数通过 `os.environ.get()` 带默认值用于调试

**`.py` 文件**：在 .orig 基础上添加环境变量获取代码（去掉默认值）

输出格式：

```python
print("-----BEGIN GATHERING DATA-----")
print(json.dumps(data, indent=4))
print("-----END GATHERING DATA-----")
```

数据格式：

```json
[
    {
        "dims": {
            "object_id": "模型ID",
            "pks": ["主键字段名"],
            "upsert": true
        },
        "vals": {
            "field1": "value1",
            "field2": "value2"
        }
    }
]
```

**采集对象（主模型）写入唯一键（重要）**：

资源采集中，**采集对象本身就是被采集的 CMDB 实例**（通过资源发现绑定），写入时**必须用 `instanceId` 作为唯一键**，让平台直接定位到该实例更新，而不是按 `name` 等业务字段匹配（否则设备名变更会产生重复实例、跨实例串写）：

```json
{"dims": {"object_id": "采集对象模型ID", "pks": ["instanceId"], "upsert": true},
 "vals": {"instanceId": "...", "其他字段": "..."}}
```

- `pks: ["instanceId"]` 是平台约定的特殊主键，表示按当前采集实例的 `instanceId` 定位，vals中的instanceId使用$.instanceId填充
- **仅采集对象（主模型）**用 `instanceId`；子模型/关联模型仍用自己的业务主键（如 `wwpn` / `name`）

**多模型 + 关系建立（重要）**：

- 关系**写在子模型 vals 里**，键 = 子模型 `relation_list` 中指向父模型的 `left_id`，值 = `[{"_object_id": "父模型ID", "instanceId": "<父实例ID>"}]`（数组，每个元素包含 `_object_id` 和 `instanceId`）
- **不要在 dims 中使用 `set_relation_ids`**（旧用法，方向易错）
- 父实例 instanceId 通常通过 `$.instanceId` 入参传入

```json
[
    {"dims": {"object_id": "采集对象模型ID", "pks": ["instanceId"], "upsert": true},
     "vals": {"name": "..."}},
    {"dims": {"object_id": "子模型ID", "pks": ["业务主键"], "upsert": true},
     "vals": {"业务主键": "...", "<relation_field>": [{"_object_id": "父模型ID", "instanceId": "<父instanceId>"}]}}
]
```

关系字段名通过 `scripts/get_model.py` 查子模型的 `relation_list`，找 `left_object_id == 子模型` 的条目，取 `left_id`。
详见 `references/collect-template.md`。

**人工维护字段保护（重要）**：

CMDB 中的资产盘点字段（如 `brand` / `mdl` / `sn` 等）通常由人工录入维护，采集脚本**不应覆盖**这些字段。约定：

- **采集字段**：使用 `c*` 前缀（如 `cBrand` / `cMdl` / `cSn` / `cSysName` / `cSysDescr`）— 由采集自动同步，可写
- **资产字段**：无前缀（`brand` / `mdl` / `sn`）— 人工维护，采集脚本不写

实现方式：在脚本中维护 `HUMAN_MANAGED_FIELDS` 集合，输出前过滤：

```python
HUMAN_MANAGED_FIELDS = {"brand", "mdl", "sn"}  # 按模型实际情况调整

def strip_human_managed_fields(vals):
    return {k: v for k, v in vals.items() if k not in HUMAN_MANAGED_FIELDS}

main_vals = strip_human_managed_fields(main_vals)
```

判断规则：模型属性中如果存在成对的 `xxx` 和 `cXxx`，则 `xxx` 是人工字段，`cXxx` 是采集字段；其他情况按业务约定决定。

### 步骤 6 — 采集测试（可选）

询问用户是否需要进行采集测试：

```
是否需要进行采集测试？如需测试请提供环境参数（如 IP、端口、认证信息等），或选择跳过。
```

如果用户提供参数，执行：

```bash
EASYOPS_COLLECTOR_ip="x.x.x.x" \
EASYOPS_COLLECTOR_user="admin" \
EASYOPS_COLLECTOR_password="xxx" \
.venv/bin/python3 src/ScriptName.py
```

验证输出中是否包含 `-----BEGIN GATHERING DATA-----` 和 `-----END GATHERING DATA-----` 标记，以及 JSON 数据格式是否正确。

### 步骤 7 — 打包（带版本号）

**版本号管理规范**：

- 插件目录下维护 `.version` 文件（存放语义化版本号，如 `1.0.4`）
- 打包时自动递增 patch 版本号（`1.0.3` → `1.0.4`）
- zip 文件名格式：`{插件名称}_v{版本号}.zip`
- `.version` 文件不打包进 zip

**使用打包脚本**：

```bash
.venv/bin/python3 scripts/pack_plugin.py output/插件名称
```

脚本自动执行：

1. 读取 `插件名称/.version` 获取当前版本号（不存在则默认 `1.0.0`）
2. 递增 patch 版本号（`1.0.3` → `1.0.4`）
3. 生成 `插件名称_v1.0.4.zip`
4. 更新 `.version` 文件为新版本号

**可选参数**：

- `--no-increment`：不递增版本号，使用当前版本（如需重新打包同版本）

```bash
.venv/bin/python3 scripts/pack_plugin.py output/插件名称 --no-increment
```

### 步骤 8 — 导入/更新到平台（可选）

询问用户是否需要导入或更新到 EasyOps 平台。

**查询是否已存在**：

```bash
python scripts/search_instance.py --model-id _COLLECTOR_EASYOPS_PLUGIN --query '{"name":"插件名称"}' --host <easyops_host> --org <org_id>
```

**如果不存在** → 导入新插件：

```bash
python scripts/plugin_manage.py import --file /path/to/插件名称.zip --name 插件名称 --host <easyops_host> --org <org_id>
```

获取返回的 instanceId 后启用：

```bash
python scripts/plugin_manage.py activate --plugin-id <instanceId> --host <easyops_host> --org <org_id>
```

**如果已存在** → 更新插件（版本号递增）：

```bash
python scripts/plugin_manage.py update --file /path/to/插件名称.zip --plugin-id <instanceId> --version <递增版本号> --host <easyops_host> --org <org_id>
```

## 配置文件说明

### plugin.yaml 核心字段

详见 `references/plugin-yaml-schema.md`。

关键字段：

| 字段                   | 说明       | 资源采集常用值           |
| ---------------------- | ---------- | ------------------------ |
| `type`               | 插件类型   | `simple-script`        |
| `samplerType`        | 采样器类型 | `process_sampler`      |
| `agentType`          | Agent 类型 | `easyops`              |
| `collectAgent`       | 采集 Agent | `$.ip`                 |
| `origin_metric.json` | 指标定义   | `[]`（资源采集无指标） |

### 密码类型参数

涉及密码、密钥等敏感信息的入参，在 `paramDefine` 中应设置 `valueType: password`，并配合 `isFromSecret: true` 和 `isEncrypt: true`：

```yaml
- name: password
  valueType: password
  isFromSecret: true
  isEncrypt: true
```

## 插件命名规范

- **中文**：`XXX信息采集`，如 `交换机SNMP信息采集`、`存储设备信息采集`
- **脚本名**：大驼峰，如 `Switch_SNMP_Config_Info`
- **zip 文件名**：`{插件名称}_v{版本号}.zip`，如 `光纤交换机SNMP信息采集_v1.0.4.zip`

## Python 2.7.18 兼容性

采集脚本运行环境为 **Python 2.7.18**，开发时需注意：

1. 使用 `from __future__ import print_function`
2. 使用 `urllib2`（非 `urllib.request`）
3. 使用 `from urlparse import urljoin`（非 `urllib.parse`）
4. 使用 `class Foo(object):` 新式类写法
5. 不可用 f-string，使用 `.format()` 格式化
6. **`subprocess` 限制**：不可使用 `Popen.communicate(timeout=N)`（Python 3.3+），不可捕获 `subprocess.TimeoutExpired`（Python 3.3+），`communicate()` 调用不要传 timeout 参数
7. **`bytes` 与 `str`**：Python 2 中 `str` 即 `bytes`，无需 `.encode()`/`.decode()` 转换，但 `subprocess` 输出的字符串调用 `.decode('utf-8', errors='ignore')` 不会报错

## 完成输出

操作完成后，输出以下信息：

1. **套件路径**：`/path/to/插件名称.zip`
2. **套件 URL**（如果已导入/更新）：

```
http://<host>/next/monitor-kit/kit/easyops/<instanceId>/detail?tab=readme
```

## 示例

`examples/` 目录包含完整的资源采集插件示例说明，参考 `output/物理服务器Redfish信息采集/` 目录。
