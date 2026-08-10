---
name: cmdb-collector
description: 解析三方 API 文档或数据库/中间件数据结构，生成 CMDB 模型定义（含关系）和数据采集脚本（声明式字段映射），支持多认证模式（Basic/AKSK/Token）和工具包打包。
---
# CMDB 数据采集脚本生成

解析三方 API 文档，生成 CMDB 模型定义和数据采集脚本。

**重要：所有文件输出到用户当前工作目录（Primary working directory），不是 skill 目录！**

## 强制规则

**必须遵守，无例外：**

1. 解析文档前必须先检索用户工作目录下的 `./apis/` 缓存
2. 解析后必须将 OpenAPI 文档保存到用户工作目录下的 `./apis/` 目录
3. 即使文档不是标准 API 文档，也要生成 OpenAPI 规范并保存
4. **必须生成 CMDB 模型 JSON 文件**（所有模型合并到一个文件）
5. **必须生成采集脚本**

## 工作流程

```
┌──────────────────────┐
│ 0. 判断数据源类型    │
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     │           │
   API接口    数据库/中间件(Kafka/MySQL/Redis等)
     │           │
     ▼           ▼
┌──────────┐  跳过步骤 1-3，直接进入步骤 4
│ 步骤 1-3 │
└──────────┘
           │
           ▼
┌────────────────────────────────────┐
│ 4. 【强制】列出模型让用户确认    │  ← 不可跳过！
└──────────┬─────────────────────────┘
           ▼
┌────────────────────────────────────┐
│ 5. 【强制】生成 CMDB 模型 JSON    │  ← 不可跳过！
└──────────┬─────────────────────────┘
           ▼
┌────────────────────────────────────┐
│ 6. 【强制】生成采集脚本           │  ← 不可跳过！
└──────────┬─────────────────────────┘
           ▼
┌────────────────────────────────────┐
│ 7. 询问用户是否打包为工具包       │  ← 用户确认后执行
└────────────────────────────────────┘
```

### 数据源类型判断

| 数据源类型    | 示例                             | 步骤 1-3           | 说明                                |
| ------------- | -------------------------------- | ------------------ | ----------------------------------- |
| API 接口      | REST API、OpenAPI 文档           | **必须执行** | 解析文档 → 保存 OpenAPI → ./apis/ |
| 数据库/中间件 | Kafka、MySQL、Redis、MongoDB、ES | **可跳过**   | 用户直接提供数据示例或模型定义      |

**当数据源为数据库/中间件时：**

- 跳过步骤 1（检索 apis 缓存）
- 跳过步骤 2（解析源文档）
- 跳过步骤 3（保存 OpenAPI）
- 直接从用户提供的数据示例或模型定义开始，进入步骤 4

## 步骤 1：检索 apis 缓存

**在用户当前工作目录下检索：**

```bash
mkdir -p ./apis
ls -la ./apis/*.yaml 2>/dev/null || echo "apis 目录为空"
```

缓存命名规则：

| 源文档              | 缓存文件                      |
| ------------------- | ----------------------------- |
| `oceanbase.pdf`   | `./apis/oceanbase-api.yaml` |
| `vmware-api.docx` | `./apis/vmware-api.yaml`    |

## 步骤 2：解析源文档（缓存未命中时）

- **PDF 文档**：

  ```bash
  python scripts/doc_reader.py --type pdf --file "path/to/api.pdf"
  ```
- **Word 文档**：

  ```bash
  python scripts/doc_reader.py --type docx --file "path/to/api.docx"
  ```
- **Markdown 文档**：直接使用 Read 工具读取
- **URL**：使用 WebFetch 工具获取网页内容

## 步骤 3：保存 OpenAPI 到 ./apis/（强制）

**这是强制步骤，必须执行！保存到用户当前工作目录下的 ./apis/ 目录！**

```bash
mkdir -p ./apis
# 使用 Write 工具将 OpenAPI 内容写入 ./apis/[api-name]-api.yaml
```

**特殊情况**：如果源文档不是标准 API 文档（如 UI 操作手册），基于数据结构推断 API 并保存，在 `info.description` 中注明原始文档为非 API 文档。

## 步骤 4：列出模型让用户确认（强制）

**这是强制步骤，必须执行！在生成模型 JSON 之前，必须先列出所有待生成的模型让用户确认。**

### 确认格式

按分类列出所有模型，包含模型 ID、名称、分类：

```
根据文档分析，将生成以下 CMDB 模型：

【弹性计算】
1. ECS@APSARA - 云服务器
2. SNAPSHOT@APSARA - 快照
3. ESS@APSARA - 弹性伸缩组

【网络】
4. VPC@APSARA - 专有网络
5. SLB@APSARA - 负载均衡
6. EIP@APSARA - 弹性公网IP

【存储】
7. OSS@APSARA - 对象存储
8. NAS@APSARA - 文件存储

【数据库】
9. RDS_MYSQL@APSARA - RDS MySQL
10. REDIS@APSARA - Redis

共 10 个模型，是否确认生成？
```

### 确认要点

1. **必须等待用户确认后才能继续生成模型**
2. 用户可以要求增加或删除某些模型
3. 用户确认后，按确认的列表生成模型

## 步骤 5：生成 CMDB 模型 JSON（强制）

**这是强制步骤，必须执行！必须严格遵循 `references/model-schema.md` 中的规范！**

### 输出文件

**所有模型合并到一个 JSON 文件：** `{system_name}_models.json`

**文件格式必须是模型数组**（参见 `examples/sample_model.json`）：

```json
[
    { "objectId": "MODEL1@SYSTEM", ... },
    { "objectId": "MODEL2@SYSTEM", ... }
]
```

**注意：** 文件内容是纯数组，不要包装成 `{"object_list": [...]}` 格式。导入 API 会自动处理。

### 模型分类（category）规范

**category 字段支持二级分类，使用英文句号 `.` 分隔。**

格式：`{系统名称}.{资源类别}`

| 系统   | 资源类别 | category 值         |
| ------ | -------- | ------------------- |
| 阿里云 | 弹性计算 | `阿里云.弹性计算` |
| 阿里云 | 网络     | `阿里云.网络`     |
| 阿里云 | 存储     | `阿里云.存储`     |
| 阿里云 | 数据库   | `阿里云.数据库`   |
| 阿里云 | 中间件   | `阿里云.中间件`   |
| VMware | 计算     | `VMware.计算`     |
| VMware | 网络     | `VMware.网络`     |
| OCP    | 集群     | `OCP.集群`        |
| OCP    | 租户     | `OCP.租户`        |

**示例：**

```json
{
    "objectId": "ECS@APSARA",
    "name": "云服务器",
    "category": "阿里云.弹性计算",
    ...
}
```

### 模型 ID 命名规范

**格式：`{NAME}@{SYSTEM}`**

| 系统   | 模型   | objectId        |
| ------ | ------ | --------------- |
| OCP    | 集群   | `CLUSTER@OCP` |
| OCP    | 主机   | `HOST@OCP`    |
| Zabbix | 主机   | `HOST@ZABBIX` |
| VMware | 虚拟机 | `VM@VMWARE`   |

**规则：**

- `NAME`：资源类型，大写英文，如 HOST、CLUSTER、TENANT、VM
- `SYSTEM`：数据源系统标识，大写英文，如 OCP、ZABBIX、VMWARE
- 使用 `@` 分隔，便于识别数据来源

### 关键规则

1. `required`、`readonly`、`unique` 必须是字符串 `"true"` 或 `"false"`，不是布尔值
2. `value` 必须包含 `default`、`mode`、`default_type` 字段
3. `tag` 是分类标签如 `["基本信息"]`，用于字段分组
4. 必须包含 `view` 配置
5. 导入 API 使用 `POST /v2/object_import`
6. **必须分析字段生成 `relation_list` 模型关系**

### 模型关系生成

分析 API 响应中的引用字段，自动生成模型关系：

| 字段模式                         | 关系类型 | 示例                              |
| -------------------------------- | -------- | --------------------------------- |
| `{model}_id` / `{model}Id`   | 多对一   | `cluster_id` → VM 关联 CLUSTER |
| `{model}_ids` / `{model}Ids` | 多对多   | `host_ids` → 多对多关系        |
| `parent_{model}`               | 父子关系 | `parent_zone` → 自关联         |

**重要：同一个关系只需在一端定义一次！** 如 ZONE 和 CLUSTER 的关系，只在 ZONE 模型中定义，不要在 CLUSTER 中重复定义，否则导入会报"关系定义重复"错误。

**关系 ID 格式**：`{左模型ID}_{左关系ID}_{右关系ID}_{右模型ID}`

**关系 ID 命名**：

- `left_id` / `right_id` 使用复数小写形式（如 `clusters`、`tenants`）
- 用于实例数据写入时的关系字段名

**关系名称与描述**：

- `left_name` = "关联{右侧模型名称}"
- `left_description` = "关联{左侧模型名称}实例"
- `right_name` = "关联{左侧模型名称}实例"
- `right_description` = "关联{右侧模型名称}"

**关系基数**：

- `left_max: 1` - 左侧只能关联一个（多对一的"多"侧）
- `left_max: -1` - 左侧可关联多个
- `right_max: 1` - 右侧只能关联一个（多对一的"一"侧）
- `right_max: -1` - 右侧可关联多个

完整关系结构参见 `references/model-schema.md`。

### 关系数据写入格式（重要）

**实例数据中写入关系时，必须使用对端模型唯一键的对象数组格式，不可传纯字符串数组！**

```python
# ✅ 正确：使用对端模型唯一键的对象数组
"HOST_ALL": [{"ip": "10.122.246.2"}]
"CLUSTER": [{"clusterId": "cluster-001"}]

# ❌ 错误：传纯字符串数组
"HOST_ALL": ["10.122.246.2"]
"CLUSTER": ["cluster-001"]
```

**规则：**

- 关系字段名为 `relation_list` 中定义的 `left_id` 或 `right_id`
- 值为数组，每个元素是包含对端模型唯一键的字典
- 唯一键取对端模型中 `unique: "true"` 的字段（如 `ip`、`clusterId`）

### 字段类型映射

| API 类型             | CMDB 类型 | 说明                               |
| -------------------- | --------- | ---------------------------------- |
| string               | str       | 普通字符串                         |
| string + enum        | enum      | 单选枚举，必须提供 regex           |
| integer              | int       | 整数                               |
| number/float         | float     | 浮点数                             |
| boolean              | bool      | 布尔值                             |
| array[string]        | arr       | 字符串数组                         |
| array[string] + enum | enums     | 多选枚举，必须提供 regex           |
| object               | struct    | 结构体，必须提供 struct_define     |
| array[object]        | structs   | 结构体数组，必须提供 struct_define |

复杂类型（enum/enums/struct/structs）的完整定义和 OpenAPI 类型识别规则，参见 `references/field-types.md`。

## 步骤 6：生成采集脚本（强制）

**这是强制步骤，必须执行！**

**生成到用户当前工作目录：** `{system_name}_collector.py`

### 采集脚本规范

- 使用 `logging` 模块
- 使用 `requests` 库
- 包含重试机制
- **不使用 argparse，直接在脚本顶部定义配置变量**
- **脚本末尾给出使用示例**
- **必须包含日期时间格式转换函数**（参见 `examples/parse_datetime.py`）
- **⚠️ CMDBClient 类必须严格参照 `examples/collector_template.py` 实现**
- **⚠️ 端口直接写在各 API 方法内部，不使用全局常量**
- **⚠️ PORT_APP_MAP 作为类变量定义在 CMDBClient 中，根据脚本涉及的服务填写映射**
- **⚠️ 支持 OpenAPI 签名认证（AK/SK），通过配置区域开关切换**
- **⚠️ 使用声明式 MODELS 配置 + 通用 `transform()` 函数进行数据转换，不要为每个模型写独立的转换函数**

### 数据转换规范（声明式字段映射）

**使用 `MODELS` 字典统一配置所有模型的 API 路径、唯一键和字段映射，配合通用 `transform()` 函数完成转换。**

字段映射值支持三种类型：

| 映射值类型 | 格式                          | 说明                                               |
| ---------- | ----------------------------- | -------------------------------------------------- |
| 字符串     | `"source_field"`            | 简单字段映射，支持点号嵌套如 `"metadata.region"` |
| 元组       | `("source_field", default)` | 带默认值的字段映射                                 |
| 函数       | `lambda item: ...`          | 自定义转换逻辑（类型转换、关系字段格式化等）       |

```python
MODELS = {
    "CLUSTER@OCP": {
        "api": "/api/v1/clusters",
        "keys": ["clusterId"],
        "mapping": {
            "clusterId": "id",                    # 简单映射
            "region": "metadata.region",           # 嵌套字段
            "status": ("status", "unknown"),        # 带默认值
            "ctime": lambda item: parse_datetime(item.get("createTime")),  # 自定义转换
            # 关系字段：使用对端唯一键的对象数组
            "tenants": lambda item: [{"tenantId": tid} for tid in item.get("tenantIds", [])],
        },
    },
}
```

通用 `transform()` 和 `get_nested()` 函数已在模板中实现，直接使用即可。

采集入口使用 `run_collect()` 函数遍历所有模型：

```python
run_collect(MODELS, third_party, cmdb, BATCH_SIZE)
```

### CMDBClient 实现规范（强制）

**必须严格按照 `examples/collector_template.py` 中的 CMDBClient 类实现，不可自行修改！**

关键配置：

| 配置项         | 正确值                                                   | 说明              |
| -------------- | -------------------------------------------------------- | ----------------- |
| Agent 配置路径 | `/usr/local/easyops/agent/conf/conf.yaml`              | Linux 路径        |
| Agent 配置路径 | `C:\easyOps\agent\conf\conf.yaml`                      | Windows 路径      |
| CMDB 端口      | `8079`（直接写在 `import_instance` 方法内）          | 不是 80 或 443    |
| API 路径       | `object/{object_id}/instance/_import`                  | 批量导入接口      |
| org 读取       | `dic['base']['client_id']`                             | 从 conf.yaml 读取 |
| host 读取      | `dic['command']['server_groups'][0]['hosts'][0]['ip']` | 从 conf.yaml 读取 |
| PORT_APP_MAP   | 类变量，`{8079: "cmdbservice"}`                        | OpenAPI 路由映射  |

**禁止的错误实现：**

```python
# ❌ 错误：使用 agent.conf
conf_path = "/usr/local/easyops/agent/agent.conf"

# ❌ 错误：使用 80 端口
url = f"http://{self.host}:80/api/cmdb/..."

# ❌ 错误：错误的 API 路径
path = f"/api/cmdb/v2/object/{object_id}/instance"

# ❌ 错误：自行实现配置读取逻辑
config = configparser.ConfigParser()
```

### 认证模式支持（重要）

**三方 API 认证**：如果 API 文档定义了多种认证模式，采集脚本必须全部支持！

常见认证模式：

| 认证类型   | 配置变量示例             | 说明              |
| ---------- | ------------------------ | ----------------- |
| Basic Auth | `AUTH_TYPE = "basic"`  | HTTP Basic 认证   |
| AK/SK      | `AUTH_TYPE = "aksk"`   | HMAC 签名认证     |
| Token      | `AUTH_TYPE = "token"`  | Bearer Token      |
| API Key    | `AUTH_TYPE = "apikey"` | Header/Query 传递 |

**CMDB 写入侧认证**：CMDBClient 已内置内网和 OpenAPI 双模式，通过配置区域 AK/SK 自动切换。详见 `examples/collector_template.py`。

**实现要求：**

1. 配置区域定义 `AUTH_TYPE` 变量，用户可选择认证方式
2. 同时定义所有认证方式所需的配置变量
3. 客户端类中实现 `_get_auth_headers()` 方法，根据 `AUTH_TYPE` 返回对应的认证头
4. 参考 OpenAPI 规范中的 `securitySchemes` 定义实现签名算法

完整认证实现示例参见 `examples/auth_example.py`。

## 步骤 7：打包为工具包 tar.gz

**生成采集脚本后，询问用户是否需要打包为工具包 tar.gz。用户确认需要打包后再执行。**

生成采集脚本后，将其打包为 EasyOps 工具包格式。原始 `.py` 脚本保留供用户查看。

### 打包时机选择

**生成采集脚本后，必须询问用户选择打包时机：**

1. **立即打包** - 直接打包为工具包
2. **验证后打包** - 用户先提供实际配置变量，运行采集脚本验证数据正确后再打包

选择「验证后打包」时：

- 引导用户修改脚本配置区域的变量（如 API 地址、认证信息、Kafka 地址等）
- 用户运行脚本验证采集结果
- 用户确认数据正确后，再执行打包流程

### 打包流程

1. **提取脚本配置变量为 inputs 参数**
2. **注释掉脚本中的配置变量**（变量由工具参数传入）
3. **生成 config 配置文件**
4. **打包为 tar.gz**

### 变量处理

将脚本配置区域的变量注释掉，添加说明：

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

### 执行打包

```bash
python scripts/pack_tool.py \
    --name "{tool_name}" \
    --script "./{system_name}_collector.py" \
    --config "./{tool_name}_config.json" \
    --output "./"
```

如果不提供 `--config`，脚本会自动生成基础配置（仅含执行目标参数）。

### inputs 参数生成规则

从脚本配置区域提取变量，转换为 inputs 参数。详细规则参见 `references/package-spec.md`。

**注意：** `@agents` 执行目标参数是固定的，必须包含。其他参数根据脚本变量生成。

### 清理临时文件

打包完成后，删除打包过程中生成的临时文件（config JSON 和注释变量后的脚本副本），只保留原始 `.py` 脚本和 `.tar.gz` 工具包。

## 完成检查清单

执行完毕前，确认：

- [ ] 是否判断了数据源类型？（API 接口 vs 数据库/中间件）
- [ ] **（仅 API 数据源）** 是否检索了 `./apis/` 缓存？
- [ ] **（仅 API 数据源）** 是否已将 OpenAPI 保存到 `./apis/` 目录？
- [ ] **是否列出模型并获得用户确认？**
- [ ] **是否生成了 CMDB 模型 JSON？**（`{system_name}_models.json`）
- [ ] **模型 category 是否使用了二级分类？**（如 `阿里云.弹性计算`）
- [ ] **是否分析字段并生成了模型关系 `relation_list`？**
- [ ] **是否生成了采集脚本？**（`{system_name}_collector.py`）
- [ ] **是否询问用户是否需要打包？**（用户确认后打包 `{tool_name}.tar.gz`）

**必须输出的文件：**

| 文件                             | API 数据源 | 数据库/中间件数据源 |
| -------------------------------- | ---------- | ------------------- |
| `./apis/{api-name}-api.yaml`   | 必须       | 不需要              |
| `./{system_name}_models.json`  | 必须       | 必须                |
| `./{system_name}_collector.py` | 必须       | 必须                |
| `./{tool_name}.tar.gz`         | 用户确认后 | 用户确认后          |

## 参考资源

### 参考文档/

- **`references/model-schema.md`** - 模型 JSON 完整结构和导入 API
- **`references/field-types.md`** - 字段类型详解、复杂类型定义、OpenAPI 类型识别规则
- **`references/package-spec.md`** - 工具包打包规范、config 配置格式、inputs 参数规则

### 示例文件

- **`examples/collector_template.py`** - 采集脚本完整模板
- **`examples/parse_datetime.py`** - 日期时间格式转换函数（采集脚本必须包含）
- **`examples/auth_example.py`** - 多认证模式实现示例
- **`examples/sample_model.json`** - 模型 JSON 示例

### 工具脚本

- **`scripts/pack_tool.py`** - 工具包打包脚本
