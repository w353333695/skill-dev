---
name: inspection-kit
description: 开发、修改、排查 EasyOps agent 方式巡检套件（巡检包）：生成或更新完整套件包（info.yaml、metrics.yaml、采集脚本、报告模板、CMDB 模型），支持指标告警条件配置、采集脚本开发与修复、自动打包和导入 EasyOps 环境（含增删改查）。也用于排查已有巡检套件/巡检包采集失败、指标采集不到/缺失等问题，按套件规范（content 字段 json.dumps 转义、Python 2.7.18 运行环境、pack_plugin.py 打包）定位并修复采集脚本缺陷。
version: 0.1.0
---
# EasyOps 巡检套件开发指南

本 skill 用于指导开发 EasyOps 平台的巡检套件（agent 方式）。

## 套件结构

```
inspector_<name>/
├── info.yaml              # 套件基本信息（必需）
├── metrics.yaml           # 指标组定义（必需）
├── models.json            # 关联CMDB模型定义（必需,dict形式的json）
├── collectors/            # 采集脚本目录（必需）
│   ├── __init__.py
│   └── script.py          # 采集脚本（YAML格式）
└── reports_temp/          # 报告模板（必需）
    └── detail.yaml
```

## 开发流程

### 1. 确定巡检需求

收集以下信息：

- 巡检对象类型（中间件、数据库、应用等）
- 巡检项列表（状态检查、配置检查、性能指标等）
- 采集命令（shell 命令、SQL 查询等）
- 告警条件（阈值、状态判断等）

### 2. 获取关联 CMDB 模型

查询现有模型详情：

```bash
python scripts/get_model.py --model-id MODEL_ID --host <easyops_host> --org <org_id>
```

如果在 EasyOps agent 节点上执行，可省略 `--host` 和 `--org`：

```bash
python scripts/get_model.py --model-id MODEL_ID
```

将返回的模型详情直接保存为 `models.json`。

> **注意**：`models.json` 中的属性名必须与 CMDB 模型定义完全一致。常见的属性名错误包括：`model` 应为 `mdl`，`firmwareVersion` 应为 `microcode`。请严格按 API 返回的 `attrList` 中的 `id` 字段保存，不要自行推测或修改。

### 3. 生成套件文件

按照 `references/` 中的模板生成各配置文件。

### 4. 自动打包套件（带版本号）

如需打包为 tar.gz 格式（平台要求），可手动执行：

```bash
cd /path/to/parent-dir
tar -czvf "套件名称(ONEMODEL)_v{版本号}.tar.gz" inspector_xxx/
```

注意：开发完成后必须自动打包，无需等待用户确认。

## 配置文件说明

### info.yaml 核心字段

| 字段               | 说明                                                                                                | 示例                                               |
| ------------------ | --------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| id                 | 套件ID，符合正则^[a-zA-Z_][0-9a-zA-Z_]{0,31}$                                                       | `inspector_webspheremq`                          |
| name               | 套件名称，套用模型名称                                                                              | `IBMMQ巡检(ONEMODEL)`                            |
| objectid           | 关联CMDB模型                                                                                        | `IBMMQ@ONEMODEL`                                 |
| objectname         | 模型显示名                                                                                          | `IBMMQ部署实例`                                  |
| method             | 采集方式                                                                                            | `agent`                                          |
| relationidwithhost | 与主机的关系ID，须来自模型真实定义的 `→HOST` 关系（网络/存储设备类模型常缺失，需先在 CMDB 补建，详见常见问题） | `ARTIFACT_INST@ONEMODEL_host_artifactInsts_HOST` |
| countersideid      | 计数器ID                                                                                            | `host`                                           |
| relationid         | 关系ID，查询模型设置获取                                                                            | `artifactInsts`                                  |
| instanceid         | 实例ID，13位十六进制数字，**必须全局唯一**（与metrics.yaml和detail.yaml中的instanceid不重复） | `5a5e2b88db442`                                  |
| collectorid        | 采集脚本ID，24位十六进制数字，必须唯一                                                              | `5a5e2b88db442a14dd828a30`                       |

其他字段仿照examples中示例填写

> **重要：instanceid 必须全局唯一！** `info.yaml` 的 `instanceid`、`metrics.yaml` 中每个指标组的 `instanceid`、以及 `reports_temp/detail.yaml` 的 `instanceid` 三者之间不能有任何重复。数据库对 instanceid 有唯一约束，重复会导致导入时直接返回 `ERR_ABORTED: 数据写入部分失败` 错误。

### metrics.yaml 指标组定义

```yaml
- id: metric_group_id        # 指标组ID
  pluginid: inspector_xxx    # 套件ID
  instanceid: 7250a77ba9628  # 实例ID，13位十六进制数字，必须与info.yaml和detail.yaml中的instanceid完全不重复
  internalid: 7250a77ba9628
  name: 指标组名称
  category: 分类1.子分类1   # 指标组分类
  dims:                      # 维度定义
  - id: dim_id
    name: 维度名称
  vals:                      # 指标值定义
  - id: val_id
    name: 指标名称
    type: string             # string 或 num
    unit: ""
    weight: 50
    conditions:              # 告警条件
    - comparators: nin       # nin/in/gt/lt/gte/lte/eq/neq
      level: 0               # 告警级别，0:通知，5:警告，10:紧急
      value: RUNNING         # 比较值
```

### collectors/script.py 采集脚本

采集脚本使用 YAML 格式存储，`content` 字段是 Python 代码经过 `json.dumps()` 后的字符串，python运行环境版本为2.7.18

args为巡检套件入参，直接使用不需要从环境变量里获取，引用规则：

- **source=custom 的普通参数**：直接按 key 名称引用（如 `mysql_user`）
- **source=attr_id 的 CMDB 模型属性参数**：使用 `EASYOPS_argname` 格式引用（argname 替换为实际 key 名，如 key 为 ip 则使用 `EASYOPS_ip`）。参数值为原始类型，CMDB 属性定义为 list 则传入的就是 list，定义为 str 就是 str，不需要当作字符串额外解析。
- 能使用attr_id的，不使用custom

> **⚠️ struct/结构体类型参数按原始类型（dict）注入，不是 JSON 字符串。** 巡检套件中 source=attr_id 且模型属性为 struct 的参数（如网络设备的 `auth` 认证结构体），平台直接注入为 Python `dict`，**不是 JSON 字符串**。脚本里不要直接 `json.loads()`——对 dict 调 `json.loads` 会抛 TypeError。正确做法是兼容两种类型（dict 优先，JSON 字符串兜底），并用 `globals().get()` 规避参数未注入时的 NameError：
>
> ```python
> # auth 参数（struct 类型）兼容写法
> _auth_raw = globals().get("EASYOPS_auth")
> if isinstance(_auth_raw, dict):
>     auth = _auth_raw            # 巡检套件：原始类型注入为 dict
> elif _auth_raw:
>     try:
>         auth = json.loads(_auth_raw)   # 兜底：JSON 字符串
>     except (ValueError, TypeError):
>         auth = {}
> else:
>     auth = {}
> snmp_version = auth.get("snmpVersion") or "2c"
> ```
>
> **注意与资源采集套件（resource-collector-kit）的区别**：资源采集套件参数经环境变量 `EASYOPS_COLLECTOR_argname` 传递，环境变量只能是字符串，故 struct 是 **JSON 字符串**（需 `json.loads`）；巡检套件是全局变量直接注入，struct 是 **dict**。两者机制不同，不要互相照搬。

```yaml
pluginid: inspector_xxx
name: 巡检名称
collectorid: 5d4be73159b8ce514171438d # 脚本id，24位十六进制数字，唯一，由pluginid生成
content: "#!/usr/local/easyops/python/bin/python\n# coding:utf-8\nimport json\nimport os\n\n# source=custom 的参数直接按key名引用\ncustom_param = custom_param\n# source=attr_id 的CMDB属性用 EASYOPS_argname 引用\ninstall_path = EASYOPS_installPath\nmysql_bin = install_path + '/bin/mysql' if install_path else 'mysql'\n\nresult = [{\"id\": \"basic\", \"dims\": [], \"vals\": [{\"id\": \"status\", \"value\": \"ok\"}]}]\nprint \"-------start-------\"\nprint json.dumps(result)\nprint \"-------end-------\"\n"
args:
- key: redis_password 
  alias: Redis密码
  type: password # text明文，password密码
  require: false
  source: custom # custom表示普通参数；attr_id表示实例属性，key对应属性id
  default: ""
  memo: Redis认证密码，无密码可留空
script: python
```

生成 content 字段的方法：

```python
import json

script_content = '''#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json

result = [{"id": "basic", "dims": [], "vals": [{"id": "status", "value": "ok"}]}]
print "-------start-------"
print json.dumps(result)
print "-------end-------"
'''

# content 字段值
content_value = json.dumps(script_content,ensure_ascii=False)
```

### reports_temp/detail.yaml 报告模板

```yaml
- name: 巡检报告名称
  pluginid: inspector_xxx
  instanceid: 7250a77ba9628  # 实例ID，符合正则[\d,a-z]{13}，必须与info.yaml和metrics.yaml中的instanceid完全不重复
  internalid: 7250a77ba9628
  summarytemplates:
    metricgroups:
    - id: metric_group_id
      index: 1
      width: 12
      height: 12
      displaytype: Form
      transposed: false
  metricgroups:
  - id: metric_group_id
    index: 0
    displaytype: Form
    transposed: false
```

## 采集脚本规范

### 输出格式

采集脚本必须输出以下格式（用 `-------start-------` 和 `-------end-------` 包裹）：

```json
[
  {
    "id": "metric_group_id",
    "dims": [{"id": "dim_id", "value": "dim_value"}],
    "vals": [{"id": "val_id", "value": "val_value"}]
  }
]
```

### 常用采集模式

1. **命令行采集 + 正则解析**：执行 shell 命令，用正则提取数据
2. **API 调用**：调用目标系统 API 获取数据
3. **配置文件解析**：读取并解析配置文件

详见 `references/collect-patterns.md`。

## 告警条件说明

| comparators | 说明       | 适用类型 |
| ----------- | ---------- | -------- |
| nin         | 不在列表中 | string   |
| in          | 在列表中   | string   |
| eq          | 等于       | string   |
| neq         | 不等于     | string   |
| gt          | 大于       | num      |
| lt          | 小于       | num      |
| between     | 区间       | num      |

注意：num 类型指标只能使用 gt、lt、between 三种比较器。

### num 类型阈值设置

对于 num 类型指标，使用 `minvalue` 和 `maxvalue` 设置阈值，左开右闭：

- **lt（小于）**：`minvalue: 0`，`maxvalue: 目标值`
  - 示例：队列深度 < 100 告警 → `comparators: lt, minvalue: 0, maxvalue: 100`
- **gt（大于）**：`minvalue: 目标值`，`maxvalue: 0`
  - 示例：CPU 使用率 >= 80 告警 → `comparators: gt, minvalue: 80, maxvalue: 0`

```yaml
# 示例：队列深度大于 5 告警
- id: CURDEPTH
  name: CURDEPTH
  type: num
  conditions:
  - comparators: gt
    level: 0
    value: ""
    minvalue: 5
    maxvalue: 0
```

## 打包套件

```bash
.venv/bin/python3 ../resource-collector-kit/scripts/pack_plugin.py output/inspector_xxx
```

或手动 tar.gz 打包（带版本号）：

```bash
cd /path/to/parent-dir
tar -czvf "套件名称_v{版本号}.tar.gz" inspector_xxx/
```

## 导入到 EasyOps 环境

开发并打包完成后，询问用户是否需要将套件导入到 EasyOps 环境。使用 `scripts/manage_suite.py` 管理巡检套件的增删改查。

### 导入套件

```bash
python scripts/manage_suite.py import \
    --file output/套件名称_v1.0.0.tar.gz \
    --name inspector_xxx \
    --host <easyops_host> --org <org_id>
```

**导入自动重试机制**：如果导入失败（通常因为同名套件已存在），脚本会自动：

1. 根据 `--name` 查找已存在的同名套件
2. 提示用户确认是否删除旧套件
3. 删除后重新导入

**强制覆盖**（跳过确认）：

```bash
python manage_suite.py import --file suite.tar.gz --name inspector_xxx --force
```

### 查询套件

```bash
# 按关键字查询
python manage_suite.py list --keyword "redis" --host <host> --org <org>

# 获取全部
python manage_suite.py list --all --json --host <host> --org <org>
```

### 删除套件

```bash
python manage_suite.py delete --plugin-id <套件ID> --host <host> --org <org>
python manage_suite.py delete --plugin-id <套件ID> --force  # 跳过确认
```

## 示例文件

`examples/` 目录包含完整的巡检套件示例：

- `ibmmq-inspection/` - IBMMQ 巡检套件示例

## 套件命名规范

- **目录名**：`inspector_<英文名>`，如 `inspector_webspheremq`
- **套件名称**：`XXX巡检(ONEMODEL)`，如 `IBMMQ巡检(ONEMODEL)`
- **tar.gz 文件名**：带版本号，如 `IBMMQ巡检(ONEMODEL)_v1.0.2.tar.gz`

## 常见问题

### 指标组 ID 命名

- 使用小写字母和下划线
- 避免与 CMDB 模型属性 ID 冲突

### 维度与指标值

- dims：用于区分不同巡检对象（如队列名、通道名）
- vals：实际采集的指标值

### 告警级别

- level: 0 - 通知
- level: 5 - 告警
- level: 10 - 紧急

### 导入报错 "ERR_ABORTED: 数据写入部分失败"

该错误通常由 **instanceid 重复** 引起。数据库对 instanceid 有唯一约束，`info.yaml` 的 `instanceid`、`metrics.yaml` 中每个指标组的 `instanceid`、以及 `reports_temp/detail.yaml` 的 `instanceid` 三者之间不能有任何相同值。

**排查方法**：

1. 检查 `info.yaml` 中的 `instanceid` 值
2. 检查 `metrics.yaml` 中每个指标组的 `instanceid` 值
3. 检查 `reports_temp/detail.yaml` 中的 `instanceid` 值
4. 确保以上所有 instanceid 互不相同

**次要排查**：检查 `models.json` 中的属性名是否与 CMDB 模型返回的字段名完全一致（常见错误：`model` 应为 `mdl`，`firmwareVersion` 应为 `microcode`）。修改后重新导入即可。

### 无法定位巡检主机 / relationidwithhost 为空

巡检套件靠 `relationidwithhost` 把巡检对象关联到一台主机（HOST），平台才知道由哪台 agent 执行采集（即便脚本是 SNMP 等远程采集，调度仍需定位 agent 主机）。若该字段为空或填错，会出现"无法定位巡检主机"。

`relationidwithhost` 的值**不能编造**，必须来自关联模型（`objectid`，含继承链）真实定义的、`right_object_id == HOST` 的关系。填写规则：

- `relationidwithhost`：取模型那条 `→ HOST` 关系的 `relation_id`，格式 `<左模型>_<left_id>_<right_id>_HOST`
- `countersideid`：取该关系的 `left_id`（通常是 `host`）
- `relationid`：取 `relationidwithhost` 拆解出的 `right_id` 段（即第 3 段）

**⚠️ 关键前置：模型必须先有到 HOST 的关系。** 中间件/数据库类（继承 `ARTIFACT_INST` 等）通常自带；但**网络/存储设备类**（交换机、路由器、防火墙、负载均衡、存储等，继承 `BASE_NETWARE`）的模型**经常缺失**这条关系——此时不能留空硬导，必须先处理：

1. 用 `scripts/get_model.py --model-id <objectid>` 查 `relation_list`，筛选 `right_object_id == HOST` 的条目
2. 若**没有**：需先在 CMDB 给该模型补建一条到 HOST 的关系（参照平台已有的同类套件，如交换机参照光纤交换机 `FIBERCHANNEL_SWITCH@ONEMODEL_host_fc_switches_HOST`），再用真实 `relation_id` 填入 `info.yaml`
3. 补建后重新拉取模型更新 `models.json`

> 参照方法：用 `scripts/manage_suite.py list` 找平台上同类型的、能正常工作的巡检套件，查其 `relationIdWithHost` 字段值作为模板。