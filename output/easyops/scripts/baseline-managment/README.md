# 配置基线管理

基于 EasyOps CMDB 平台的配置基线检查工具。通过声明式规则引擎驱动基线检查，检查规则以 CMDB 实例形式存储，脚本作为通用引擎执行检查并记录结果。

## 文件说明

| 文件 | 说明 |
|------|------|
| `baseline_models.json` | CMDB 模型定义（基线规则 + 检查结果） |
| `baseline_checker.py` | 基线检查主脚本 |
| `README.md` | 本文档 |

## 快速开始

### 1. 导入 CMDB 模型

将 `baseline_models.json` 通过 EasyOps 平台的模型导入功能导入，创建以下两个模型：

- **BASELINE_RULE@BASELINE** - 基线规则模型（分类：基线管理.规则）
- **BASELINE_RESULT@BASELINE** - 检查结果模型（分类：基线管理.结果）

### 2. 创建基线规则

在 CMDB 中创建 `BASELINE_RULE@BASELINE` 实例，每条实例代表一个基线规则。

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 基线名称，如"CentOS版本检查" |
| targetModelId | 是 | 目标模型 ID，如 `HOST@CLOUD` |
| query | 是 | json 类型，实例过滤条件 |
| rules | 是 | 结构体数组，每条包含 ruleName/ruleDesc/logic/conditions |
| description | 否 | 基线说明 |

### 3. 运行检查

**内网模式**（Agent 部署环境，自动读取配置）：

```bash
python baseline_checker.py
```

**OpenAPI 模式**（远程调用，修改脚本顶部配置区）：

```python
EASYOPS_HOST = "your-easyops-host"
EASYOPS_ORG = "your-org-id"
EASYOPS_AK = "your-access-key"
EASYOPS_SK = "your-secret-key"
```

**指定基线规则**（修改脚本顶部配置区）：

```python
BASELINE_INSTANCEIDS = ["rule_id_1", "rule_id_2"]
```

## 参数说明

所有参数在脚本顶部配置区域直接修改。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| BASELINE_INSTANCEIDS | list | [] | 基线规则实例 ID 列表，为空则检查全部 |
| RESULT_RETENTION_DAYS | int | 30 | 检查结果保留天数 |
| EASYOPS_HOST | str | "" | OpenAPI 模式的主机地址 |
| EASYOPS_ORG | str | "" | OpenAPI 模式的组织 ID |
| EASYOPS_AK | str | "" | OpenAPI 模式的 Access Key |
| EASYOPS_SK | str | "" | OpenAPI 模式的 Secret Key |

## 规则配置指南

### 规则结构

`rules` 字段为结构体数组（structs），每个元素包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| ruleName | str | 规则名称，便于识别 |
| ruleDesc | str | 规则说明，描述检查目的 |
| logic | str | 条件间逻辑关系：AND 或 OR |
| conditions | str | JSON 格式的条件数组 |

多个 rule 之间是 **OR** 关系（任一通过即合规），单个 rule 内 conditions 之间由 `logic` 字段决定。

**CMDB 中的存储格式（结构体数组）：**

```json
[
  {
    "ruleName": "CentOS版本要求",
    "ruleDesc": "检查 CentOS 发行版版本不低于 7.0",
    "logic": "AND",
    "conditions": "[{\"attr\":\"osDistro\",\"preprocess\":\"lower\",\"op\":\"contains\",\"value\":\"centos\"},{\"attr\":\"osVersion\",\"preprocess\":\"extract_version\",\"op\":\"version_gte\",\"value\":\"7.0\"}]"
  }
]
```

**conditions 字段内部结构：**

```json
[
  {"attr": "osDistro", "preprocess": "lower", "op": "contains", "value": "centos"},
  {"attr": "osVersion", "preprocess": "extract_version", "op": "version_gte", "value": "7.0"}
]
```

`query` 字段为 json 类型，直接存储查询条件对象：

```json
{"osSystem": "Linux"}
```

### 操作符

**数值比较：** `gt`（大于）、`gte`（大于等于）、`lt`（小于）、`lte`（小于等于）

**版本比较：** `version_gt`、`version_gte`、`version_lt`、`version_lte`
> 按语义化版本规则比较，如 `8.1.2` > `8.1` > `8.0.3`

**字符串匹配：** `eq`（等于）、`neq`（不等于）、`contains`（包含）、`not_contains`（不包含）、`regex`（正则）、`in`（在列表中）、`not_in`（不在列表中）

**空值判断：** `is_empty`（为空）、`is_not_empty`（不为空）

### 预处理器

在条件判断前对属性值进行预处理，通过 `preprocess` 字段指定：

| 预处理器 | 说明 | 示例 |
|---------|------|------|
| `extract_number` | 提取数字 | `"v7.0"` → `"7.0"` |
| `extract_version` | 提取版本号 | `"version 8.1.2"` → `"8.1.2"` |
| `extract_regex` | 自定义正则提取 | 需配合 `preprocess_arg` |
| `strip` | 去首尾空格 | `" abc "` → `"abc"` |
| `lower` | 转小写 | `"CentOS"` → `"centos"` |
| `upper` | 转大写 | `"centos"` → `"CENTOS"` |
| `split_nth` | 分割取第 N 段 | `preprocess_arg: ";,1"` |

**链式预处理**：`preprocess` 支持数组形式：

```json
{"attr": "osVersion", "preprocess": ["extract_version", "lower"], "op": "version_gt", "value": "7.0"}
```

### 嵌套属性

支持 `attr1.attr2.attr3` 语法，遇到 `list[dict]` 时自动展开轮巡检查。

例如 `disks.usagePercent` 取到 `[65, 80, 90]`，搭配 `"op": "lte", "value": 85` 时，值 `90` 不满足条件，该实例记录为不合规。

## 规则配置示例

### 示例 1：CentOS 版本检查

检查所有 Linux 主机的 CentOS 版本是否 >= 7.0：

```json
{
  "name": "CentOS版本检查",
  "targetModelId": "HOST@CLOUD",
  "query": {"osSystem": "Linux"},
  "rules": [
    {
      "ruleName": "CentOS版本要求",
      "ruleDesc": "CentOS 发行版版本不低于 7.0",
      "logic": "AND",
      "conditions": "[{\"attr\":\"osDistro\",\"preprocess\":\"lower\",\"op\":\"contains\",\"value\":\"centos\"},{\"attr\":\"osVersion\",\"preprocess\":\"extract_version\",\"op\":\"version_gte\",\"value\":\"7.0\"}]"
    }
  ]
}
```

### 示例 2：内核版本检查（OR 条件）

内核版本以 5.x 或 4.x 开头即合规：

```json
{
  "name": "内核版本检查",
  "targetModelId": "HOST@CLOUD",
  "query": {},
  "rules": [
    {
      "ruleName": "内核版本白名单",
      "ruleDesc": "内核版本需为 4.x 或 5.x 系列",
      "logic": "OR",
      "conditions": "[{\"attr\":\"kernelVersion\",\"op\":\"regex\",\"value\":\"^5\\\\.\"},{\"attr\":\"kernelVersion\",\"op\":\"regex\",\"value\":\"^4\\\\.\"}]"
    }
  ]
}
```

### 示例 3：多规则 OR（任一通过即合规）

RedHat >= 8.0 或 CentOS >= 7.0 均视为合规：

```json
{
  "name": "操作系统版本基线",
  "targetModelId": "HOST@CLOUD",
  "query": {"osSystem": "Linux"},
  "rules": [
    {
      "ruleName": "RedHat版本要求",
      "ruleDesc": "RedHat 发行版版本不低于 8.0",
      "logic": "AND",
      "conditions": "[{\"attr\":\"osDistro\",\"preprocess\":\"lower\",\"op\":\"contains\",\"value\":\"redhat\"},{\"attr\":\"osVersion\",\"preprocess\":\"extract_version\",\"op\":\"version_gte\",\"value\":\"8.0\"}]"
    },
    {
      "ruleName": "CentOS版本要求",
      "ruleDesc": "CentOS 发行版版本不低于 7.0",
      "logic": "AND",
      "conditions": "[{\"attr\":\"osDistro\",\"preprocess\":\"lower\",\"op\":\"contains\",\"value\":\"centos\"},{\"attr\":\"osVersion\",\"preprocess\":\"extract_version\",\"op\":\"version_gte\",\"value\":\"7.0\"}]"
    }
  ]
}
```

## 执行流程

1. 初始化客户端（自动检测内网/OpenAPI 模式）
2. 查询基线规则实例（全部或按指定 ID）
3. 遍历每条规则：解析 query 查询目标实例 → 解析 rules → 逐实例检查 → 收集不合规结果
4. 删除当天旧结果（幂等性保证）
5. 批量写入新的不合规结果
6. 清理过期结果（超过保留天数）
7. 输出执行摘要

## 幂等性

每次执行前会先删除对应基线规则的所有旧结果，再写入本次检查的不合规记录。这样确保：
- 同一实例同一规则只保留一条最新结果，不会产生重复
- 已恢复合规的实例，其旧的不合规记录会被自动清除

## 日志级别

| 级别 | 场景 |
|------|------|
| DEBUG | 属性取值、预处理前后值、条件判断详情 |
| INFO | 执行开始/结束、实例数/不合规数、写入/清理数量 |
| WARNING | 规则跳过、属性不存在、预处理失败 |
| ERROR | API 调用失败、JSON 解析失败、未知操作符 |

调试时可设置环境变量或修改脚本中的日志级别为 DEBUG：

```python
logger.setLevel(logging.DEBUG)
```

## 依赖

- Python 3.6+
- requests
- pyyaml（内网模式需要）

## 维护说明

### 扩展操作符

在 `evaluate_condition()` 函数中添加新的 `if op == "xxx"` 分支。

### 扩展预处理器

1. 定义预处理函数 `preprocess_xxx(value, arg)`
2. 注册到 `PREPROCESSORS` 字典

### 检查结果查看

在 EasyOps CMDB 中查看 `BASELINE_RESULT@BASELINE` 模型的实例，可按 `baselineName`、`checkTime` 等字段筛选。
