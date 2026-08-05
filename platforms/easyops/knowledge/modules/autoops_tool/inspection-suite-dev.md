---
name: inspection-suite-dev
kind: module
module: autoops_tool
tags:
- AutoOps
- 巡检套件
- 巡检包
- inspection
- InspectionInfo
- 采集脚本
- 指标组
- 阈值
- 巡检报告
completeness: partial
gaps:
- 复合套件（composition，多原子套件组合）的结构未整理（确认存在，本知识未覆盖）
- 巡检任务（InspectionTask）创建接口未整理（套件 vs 任务的边界已明确：任务引用套件、不属于套件包）
- info.yaml 全字段中 isapp/issystem/type(builtIn)/identifiers/subplugins/suffix/pathid/pathmodel/*authorizers 等字段语义来自示例归纳，未逐项源码核对（relationid 已实测为定位主机必填，见 §2.2）
- 报告模板 detail.yaml 的 displaytype/abscissaid/transposed 等展示字段取值集未核对（示例仅见 Form）
- metrics.yaml 指标 type 取值，对象层记 int/string、导出包记 num/string，实为同一物的两种序列化写法（导出包内是 num/string），以导出包为准
scope:
- 从零开发一个巡检套件包（info.yaml + metrics.yaml + collectors/script.py + models.json + reports_temp/detail.yaml）并打包成 tar.gz
- 导入/查询/删除巡检套件（inspection.info.* API，HTTP 调用方式见 concepts/api-calling）
- 调试巡检套件（DebugCollector 真实下发执行，看 status/msg/metric_groups）
- 排查巡检套件采集失败/指标缺失/导入报错（instanceid 冲突、relationidwithhost 缺失、输出格式不符）
- 修改并更新已上架套件（导出→改→重打包→先删后导）
related:
- concepts/cmdb-model（objectid/keys/relationidwithhost 依赖 CMDB 模型的 objectId/attrList/relation_list 结构）
- concepts/instance-id（instanceid/collectorid 为 13/24 位十六进制 ID，需全局唯一）
- modules/autoops_tool/tool-package-dev（同为 AutoOps 制品开发知识；工具包 vs 巡检套件是两种不同制品）
- concepts/api-calling（本知识涉及的所有 HTTP 接口的调用方式以此为准：内网直连 host:port + user/org 头 / OpenAPI AK+SK 签名 / 列表自动翻页；inspection 服务端口 8103，CMDB 模型描述接口走 cmdbservice 8079）
last_verified: '2026-07-29'
note: 'EasyOps AutoOps 巡检套件（agent 方式，inspector_<name>.tar.gz）开发说明。两个互补信息源融合：
  (1) 概念模型与接口层——InspectionInfo/Collector/MetricGroup/Template 对象模型、
  ExportSuite/ImportSuite/DeleteInspectionInfo/DebugCollector API、运行时链路、status 自检语义；
  (2) 包结构与字段层——tar 包内 5 个文件的逐字段说明、采集脚本 content(json.dumps+Python2.7)与输出格式
  (-------start/end------- 包裹)、args 注入规则（custom 直引 / attr_id 用 EASYOPS_ 前缀、struct 注入为 dict 非 JSON 字符串）、
  instanceid 全局唯一约束、relationidwithhost 填法与缺失处理。覆盖：开发→打包→导入→调试→修改→更新（先删后导）全流程。
  切面定位：本知识描述巡检套件「构造/开发态+生命周期管理」；接口怎么发 HTTP 调（鉴权/签名/翻页）统一见 concepts/api-calling。
  来源：inspection 组件 proto/接口与执行链路源码 + 套件包字段实践整理。
  **2026-07-29 经真实环境端到端验证（inspector_mysql）**：relationid 为定位主机隐性必填（§2.2）、DebugCollector 必传 content/script（§5）、
  target 正则约束、status=ok≠采到数据（§5）、目标机 py2.7 缺失 127 转 py3（§2.4）均实测确认；DebugCollector 链路（导入→定位主机→agent 下发→解析）走通。'
---
# EasyOps AutoOps 巡检套件开发说明

> 面向 LLM 的开发指南。融合两个互补信息源：
> **A. 概念/接口层**（inspection 组件 proto + `inspection.info@ExportSuite/ImportSuite/DeleteInspectionInfo` + `inspection.collector@DebugCollector` 与执行链路源码）
> **B. 包结构/字段层**（套件包内各文件逐字段说明 + 采集脚本规范）
> 目标：理解巡检套件结构与每个文件各字段的意义和配置方法，能够**开发、导入、调试、修改、更新**巡检套件，最终交付巡检套件包（tar.gz）。
>
> **HTTP 接口怎么调**（鉴权、签名、翻页、URL 拼接）不在本文展开，统一以 `concepts/api-calling/api-calling.md` 为准——本文只给各接口的 method/path/port/参数。

---

## 0. 总体模型：巡检体系的组成

```
巡检套件 InspectionInfo（巡检什么、怎么采、怎么判）—— 套件包交付的就是这部分
├─ 基本信息：name/objectId/keys(唯一键)/relationIdWithHost/method
├─ 采集脚本 InspectionCollector（怎么采）
│   ├─ content 脚本内容 + script 脚本类型
│   └─ args[] 脚本入参定义（来源 CMDB 属性或自定义）
├─ 指标组 InspectionMetricGroup[]（采什么、怎么判）
│   ├─ dims[] 维度（实例的分组维度，如"磁盘分区"）
│   └─ vals[] 指标（阈值判定条件 conditions[]，分级 notice/warning/emergency）
└─ 报告模板 InspectionTemplate（怎么呈现，独立对象）

巡检任务 InspectionTask（对谁巡、何时巡、通知谁）——引用套件，不属于套件包
巡检历史 InspectionHistory（巡的结果：score/passingRate/targets 状态）
```

**运行时链路**：巡检任务触发 → 按套件的 `objectId + keys` 从 CMDB 取巡检对象实例 → 按 `relationIdWithHost/counterSideId` 找到实例关联的主机 → 在主机上（agent 方式）执行采集脚本 → 脚本输出按指标组 dims/vals 解析为指标数据 → 按 conditions 阈值判定等级 → 汇总评分（score，按指标 weight 加权）→ 生成报告。

**套件状态自检**（`InspectionInfo.status`，判断套件是否可用，系统维护无需配置）：

| status                     | 含义                         |
| -------------------------- | ---------------------------- |
| `ok`                     | 正常                         |
| `object_deleted`         | 关联的 CMDB 模型被删除       |
| `keys_deleted`           | 唯一键属性被删除             |
| `keys_not_unique`        | 唯一键不唯一（取实例会错乱） |
| `object_relation_not_ok` | 与主机的关系配置不符合要求   |

**两个序列化形态对照（重要，别混）**：

- **API 对象层**（A 源）：驼峰字段名 `objectId`/`relationIdWithHost`/`comparatorType`/`maxValue`，指标类型 `int`/`string`，用于 DebugCollector 等接口的 JSON。
- **导出包文件层**（B 源）：全小写字段名 `objectid`/`relationidwithhost`/`comparators`/`maxvalue`，指标类型 `num`/`string`，是 tar 包内 yaml 的实际写法。

**开发套件 = 手工搓导出包文件层**（B），导入后平台反序列化为对象层（A）。改套件时导出的包也是 B 形态。本文 §1 讲对象模型（理解语义），§2 讲包文件（动手开发）。

---

## 1. 套件核心对象模型（语义层）

### 1.1 InspectionInfo（套件基本信息）

| 字段                   | 类型     | 说明 / 配置方法                                                                                                                                                        |
| ---------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                 | string   | 套件 ID（pluginId），如`inspector_redis`                                                                                                                             |
| `name`               | string   | 套件名，如"MySQL 巡检套件"                                                                                                                                             |
| `memo`               | string   | 备注                                                                                                                                                                   |
| `index`              | int      | 套件索引（排序用）                                                                                                                                                     |
| `objectId`           | string   | **巡检对象的 CMDB 模型 ID**（如 `MYSQL`、`REDIS@ONEMODEL`、自定义模型）。套件围绕这个模型的实例展开巡检。模型结构见 `concepts/cmdb-model.md`               |
| `objectName`         | string   | 模型名称（展示）                                                                                                                                                       |
| `keys`               | string[] | **唯一键列表（CMDB 模型的属性 ID）**：唯一标识一个巡检实例并拼实例名（如 `sid(pid xxx)` 由唯一键值拼接）。**必须保证在模型内唯一**，否则 keys_not_unique |
| `relationIdWithHost` | string   | **巡检对象模型与主机模型的关系 ID**——巡检脚本最终要在主机上执行，通过此关系从业务实例找到目标主机。填法细则见 §2.2                                            |
| `counterSideId`      | string   | 关系对端模型 ID（通常`host`，也可以是其他承载 agent 的模型）                                                                                                         |
| `method`             | string   | 执行方式：`agent`（通过 agent 在目标主机执行，当前唯一方式）                                                                                                         |
| `status`             | string   | 健康状态（见 §0 表）                                                                                                                                                  |

**配置决策（LLM 引导）**：

1. 巡检对象是什么？→ 选 CMDB 模型 objectId（如 Oracle 实例、K8s 集群、主机本身）；
2. 用什么区分一个实例？→ 选唯一键 keys（如 `sid`、`name+port` 组合），从模型 `attrList` 挑属性 id；
3. 脚本在哪台机器跑？→ 配 objectId 与 HOST 的关系（relationIdWithHost）；若 objectId 就是 HOST，关系可直通；
4. 一个套件只针对一个模型。巡检多个模型 = 多个套件（或用复合套件组合，见 gaps）。

### 1.2 InspectionCollector（采集脚本）

| 字段              | 说明 / 配置方法                                               |
| ----------------- | ------------------------------------------------------------- |
| `id` / `name` | 脚本 ID / 名称                                                |
| `content`       | **脚本内容全文**（shell/python 等，与 script 类型对应） |
| `script`        | 脚本类型（`shell` / `python`）                            |
| `args[]`        | 脚本入参定义，执行时按巡检实例把参数值注入脚本环境            |

**args[]（InspectionArg）**：

| 字段        | 说明                                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| `key`     | 入参 key（脚本内取值的变量名）                                                                                            |
| `alias`   | 别名（展示名）                                                                                                            |
| `source`  | **参数来源**：`attr_id`（取巡检实例的 CMDB 属性值，如实例的 port/用户名）/ `custom`（自定义固定值，填 default） |
| `type`    | 输入框类型（表单展示控件；`text` 明文 / `password` 密码）                                                             |
| `require` | 是否必填                                                                                                                  |
| `default` | 默认值（source=custom 时即参数值）                                                                                        |
| `memo`    | 辅助说明                                                                                                                  |

> 设计要点：实例级差异参数（端口、账号、数据目录）用 `attr_id` 从 CMDB 实例属性取；全局固定参数（超时、阈值开关）用 `custom`。**能用 attr_id 就不用 custom**。

### 1.3 InspectionMetricGroup（指标组）

| 字段              | 说明 / 配置方法                                                                                     |
| ----------------- | --------------------------------------------------------------------------------------------------- |
| `id` / `name` | 指标组 ID / 名称（如"磁盘使用率"）。ID 用小写字母+下划线，避免与 CMDB 模型属性 ID 冲突              |
| `category`      | **两级分类，`.` 分隔**，如 `主机状态.基本配置`——决定报告中指标的分组归属                |
| `dims[]`        | **维度** `[{id, name}]`：指标细分维度。如磁盘按"挂载点"分维度，一个实例产出多行。无维度则空 |
| `vals[]`        | **指标**（见下表）                                                                            |
| `memo`          | 指标组说明                                                                                          |

**vals[]（InspectionVal）**：

| 字段              | 说明                                                                                                             |
| ----------------- | ---------------------------------------------------------------------------------------------------------------- |
| `id` / `name` | 指标 ID / 名称（如`disk_usage` / 磁盘使用率）                                                                  |
| `type`          | 指标类型：`int`（数值，阈值按区间判定）/ `string`（字符，阈值按值匹配）。（导出包内写作 `num`/`string`） |
| `unit`          | 单位（`%`、`MB`、`个` 等）                                                                                 |
| `weight`        | **指标权重**：汇总实例评分（score）时的加权系数，重要指标给高权重                                          |
| `memo`          | 备注                                                                                                             |
| `conditions[]`  | **阈值判定条件**（见下表）                                                                                 |

**conditions[]（InspectionCondition）**：

| 字段                        | 说明                                                                                                                                                         |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `comparatorType`          | 比较器类型（导出包写作`comparators`，取值见 §3.3）                                                                                                        |
| `level`                   | **告警等级：`0`=notice（提醒/通知）、`5`=warning（警告）、`10`=emergency（严重/紧急）**。一个指标可配多级（如 >80 为 warning，>95 为 emergency） |
| `maxValue` / `minValue` | **仅数值型有效**：该等级命中的数值区间（导出包写作 `maxvalue`/`minvalue`，左开右闭，配法见 §3.3）                                                 |
| `value`                   | **仅 string 型有效**：该等级命中的匹配值                                                                                                               |

> 判定逻辑：脚本采回指标值 → 逐条匹配 conditions → 命中最高 level 即该指标异常等级；实例评分按 vals.weight 加权汇总；任何指标命中 level>0 → 实例状态 abnormal。

---

## 2. 套件包结构（tar.gz，动手开发的交付物）

**最终交付物是一个 tar.gz 压缩包**，解压后目录结构（顶层目录名 = `inspector_<name>`）：

```
inspector_<name>/
├── info.yaml              # 套件基本信息（必需）
├── metrics.yaml           # 指标组定义（必需）
├── models.json            # 关联 CMDB 模型定义（必需，dict 形式的 json）
├── collectors/            # 采集脚本目录（必需）
│   ├── __init__.py
│   └── script.py          # 采集脚本（YAML 格式，content 是 json.dumps 后的 Python 代码）
└── reports_temp/          # 报告模板（必需）
    └── detail.yaml
```

**命名规范**：目录名 `inspector_<英文名>`；套件名 `XXX巡检(ONEMODEL)`；tar.gz 文件名带版本号，如 `IBMMQ巡检(ONEMODEL)_v1.0.2.tar.gz`。

**打包**：

```bash
cd /path/to/parent-dir
tar -czvf "套件名称(ONEMODEL)_v{版本号}.tar.gz" inspector_xxx/
```

### 2.1 `info.yaml` —— 套件基本信息

核心字段（对应 §1.1 InspectionInfo，全小写序列化）：

| 字段                   | 说明                                                                                                    | 示例                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `id`                 | 套件 ID，正则`^[a-zA-Z_][0-9a-zA-Z_]{0,31}$`                                                          | `inspector_webspheremq`                          |
| `name`               | 套件名称，套用模型名称                                                                                  | `IBMMQ巡检(ONEMODEL)`                            |
| `objectid`           | 关联 CMDB 模型                                                                                          | `IBMMQ@ONEMODEL`                                 |
| `objectname`         | 模型显示名                                                                                              | `IBMMQ部署实例`                                  |
| `method`             | 采集方式                                                                                                | `agent`                                          |
| `relationidwithhost` | 与主机的关系 ID，须来自模型真实定义的`→HOST` 关系（网络/存储设备类常缺失，需先在 CMDB 补建，见 §6） | `ARTIFACT_INST@ONEMODEL_host_artifactInsts_HOST` |
| `countersideid`      | 计数器 ID                                                                                               | `host`                                           |
| `relationid`         | 关系 ID，查询模型设置获取                                                                               | `artifactInsts`                                  |
| `instanceid`         | 实例 ID，13 位十六进制，**必须全局唯一**（见下方约束）                                            | `5a5e2b88db442`                                  |
| `collectorid`        | 采集脚本 ID，24 位十六进制，必须唯一                                                                    | `5a5e2b88db442a14dd828a30`                       |
| `keys`               | 唯一键列表（对应 §1.1；可为空`[]`）                                                                  | `[]`                                             |

其余字段（`isapp`/`issystem`/`type`/`identifiers`/`subplugins`/`suffix`/`pathid`/`pathmodel`/`creator`/`*authorizers` 等）仿照示例填写即可（见 gaps，未逐项源码核对）。

> **⚠️ instanceid 必须全局唯一！** `info.yaml` 的 `instanceid`、`metrics.yaml` 中每个指标组的 `instanceid`、`reports_temp/detail.yaml` 的 `instanceid` **三者两两不能重复**。数据库对 instanceid 有唯一约束，重复会导致导入报 `ERR_ABORTED: 数据写入部分失败`。ID 生成规则见 `concepts/instance-id.md`。

### 2.2 `relationidwithhost` 填法（关键，易错）

巡检套件靠 `relationidwithhost` 把巡检对象关联到一台主机（HOST），平台才知道由哪台 agent 执行采集（即便脚本是 SNMP 等远程采集，调度仍需定位 agent 主机）。**值不能编造**，必须来自关联模型（`objectid`，含继承链）真实定义的、`right_object_id == HOST` 的关系（关系结构见 `concepts/cmdb-model.md` 的 `relation_list`）：

- `relationidwithhost`：取该关系的 `relation_id`，格式 `<左模型>_<left_id>_<right_id>_HOST`
- `countersideid`：取该关系的 `left_id`（通常是 `host`）
- `relationid`：取 `relationidwithhost` 拆解出的 `right_id` 段（第 3 段，如 `ARTIFACT_INST@ONEMODEL_host_artifactInsts_HOST` → `artifactInsts`）

> **⚠️ `relationid` 是定位巡检主机的隐性必填项（2026-07-29 实测）**：objectId ≠ HOST（需经关系跳转到主机）时，`relationidwithhost`/`countersideid`/`objectid` 全对、CMDB 实例 host 关系也建好，只要 `relationid` 留空，`DebugCollector`/巡检就报「**没有找到套件关联的主机**」；补上 `relationid`（=relationidwithhost 第 3 段）立即恢复。注意参照套件（如 mssql）该字段虽为空、但那是在其主机映射已建立的历史数据上——**新建套件务必显式填 `relationid`**，勿照抄留空。

**模型缺到 HOST 的关系时不能留空硬导**，处理流程见 §6「无法定位巡检主机」。

**被采实例与 agent 机可分离（远程采集模型）**：采集脚本在 `host` 关系指向的 agent 机上执行，被采 DB/中间件的连接地址走 `attr_id`（如 `ip`/`ports`）注入——二者**不必同机**。例：MYSQL 实例 `ip` 填被采库地址（无 agent 的库服务器），`host` 关系指向任一 agent 在线的主机，脚本在该 agent 机上跑、经 `EASYOPS_ip` 远程连库。`host` 关系只需指向有 agent 的主机即可定位。

### 2.3 `metrics.yaml` —— 指标组定义（list）

```yaml
- id: metric_group_id        # 指标组ID
  pluginid: inspector_xxx    # 套件ID
  instanceid: 7250a77ba9628  # 13位十六进制，必须与 info.yaml/detail.yaml 的 instanceid 完全不重复
  internalid: 7250a77ba9628  # 同 instanceid
  name: 指标组名称
  memo: ""
  category: 分类1.子分类1     # 两级，. 分隔
  dims:                       # 维度定义
  - id: dim_id
    name: 维度名称
  vals:                       # 指标定义
  - id: val_id
    name: 指标名称
    type: string              # string 或 num（对应对象层 string/int）
    memo: ""
    unit: ""
    weight: 50
    conditions:               # 告警条件
    - comparators: nin        # 比较器（见 §3.3）
      level: 0                # 0通知/5警告/10紧急
      value: RUNNING          # string 型的匹配值
      maxvalue: 0             # num 型区间（左开右闭）
      minvalue: 0
```

### 2.4 `collectors/script.py` —— 采集脚本（YAML 壳 + content 是代码）

文件本身是 YAML；`content` 字段是 **Python 代码经 `json.dumps()` 转义后的字符串**。运行环境默认按 **Python 2.7.18** 编写（`print` 语句，shebang 指向 `/usr/local/easyops/python/bin/python`）。

> **⚠️ 目标 agent 机可能无 py2.7（2026-07-29 实测）**：shebang 指向的解释器不存在时执行报 `Process exited with status 127: ... No such file or directory`，debug 返回 `status=unknown`。实测有 agent 机缺 `/usr/local/easyops/python/bin/python`——脚本转 py3（shebang `#!/usr/bin/env python3` + `print()`）后正常。**建议脚本 py2/py3 兼容，或按目标环境实际解释器选 shebang**。

```yaml
collectorid: 5d4be73159b8ce514171438d  # 24位十六进制，唯一，由 pluginid 生成
pluginid: inspector_xxx
name: 巡检名称
content: "<json.dumps 后的 Python 代码字符串>"
args:
- key: redis_password
  alias: Redis密码
  type: password        # text明文 / password密码
  require: false
  source: custom        # custom普通参数 / attr_id实例属性
  default: ""
  memo: Redis认证密码
script: python
```

**生成 content 的方法**：

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
content_value = json.dumps(script_content, ensure_ascii=False)
```

**args 参数在脚本内的引用规则（注入为全局变量，非环境变量）**：

- **`source=custom`**：直接按 key 名引用（如 `redis_password`）
- **`source=attr_id`**：用 `EASYOPS_<key>` 引用（key 为 `ip` 则用 `EASYOPS_ip`）。**参数值为原始类型**——CMDB 属性定义为 list 就传入 list，str 就是 str，不要当字符串额外解析。

> **⚠️ struct/结构体类型参数注入为 Python dict，不是 JSON 字符串。** source=attr_id 且模型属性为 struct 的参数（如网络设备的 `auth` 认证结构体），平台直接注入为 dict，**不要直接 `json.loads()`**（对 dict 调会抛 TypeError）。正确写法兼容两种类型，并用 `globals().get()` 规避参数未注入的 NameError：
>
> ```python
> _auth_raw = globals().get("EASYOPS_auth")
> if isinstance(_auth_raw, dict):
>     auth = _auth_raw                      # 巡检套件：原始类型注入为 dict
> elif _auth_raw:
>     try:
>         auth = json.loads(_auth_raw)      # 兜底：JSON 字符串
>     except (ValueError, TypeError):
>         auth = {}
> else:
>     auth = {}
> ```
>
> **与资源采集套件（resource-collector-kit）的区别**：资源采集套件参数经环境变量 `EASYOPS_COLLECTOR_<name>` 传递（只能是字符串，struct 是 JSON 字符串需 `json.loads`）；**巡检套件是全局变量直接注入，struct 是 dict**。两者机制不同，不要互相照搬。

### 2.5 `models.json` —— 关联 CMDB 模型定义

dict 形式的 json，内容 = 调 CMDB 模型描述接口拿到的模型描述（`data` 部分）。接口：

```
GET http://<host>:8079/object/{modelId}     # cmdbservice，modelId 如 REDIS@ONEMODEL
Headers: user=<user>, org=<org>             # 内网直连鉴权，见 concepts/api-calling
```

将返回的 `data` **直接保存**为 `models.json`。

> **⚠️ 属性名必须与 CMDB 模型定义完全一致**——严格按接口返回的 `attrList` 中的 `id` 字段保存，不要自行推测/修改。常见属性名错误：`model` 应为 `mdl`，`firmwareVersion` 应为 `microcode`。模型结构（attrList/值类型/relation_list）见 `concepts/cmdb-model.md`。

### 2.6 `reports_temp/detail.yaml` —— 报告模板

```yaml
- name: 巡检报告名称
  memo: ""
  pluginid: inspector_xxx
  instanceid: 7250a77ba9628   # 13位十六进制，与 info.yaml/metrics.yaml 的 instanceid 完全不重复
  internalid: 7250a77ba9628
  summarytemplates:
    metricgroups:              # 摘要区引用的指标组（带布局宽高）
    - id: metric_group_id
      index: 1
      width: 12
      height: 12
      displaytype: Form
      transposed: false
    metrics: []
  metricgroups:                # 详情区指标组排列
  - id: metric_group_id
    index: 0
    displaytype: Form
    abscissaid: ""
    transposed: false
```

`summarytemplates.metricgroups` 与 `metricgroups` 都按 `id` 引用 metrics.yaml 里定义的指标组，`index` 控制排列顺序。

---

## 3. 采集脚本规范

### 3.1 输出格式（必须遵守，平台按此解析）

脚本 stdout 必须用 `-------start-------` 和 `-------end-------` 包裹一个 JSON：

```json
[
  {
    "id": "metric_group_id",
    "dims": [{"id": "dim_id", "value": "dim_value"}],
    "vals": [{"id": "val_id", "value": "val_value"}]
  }
]
```

- `id` 对应 metrics.yaml 的指标组 id；一个指标组可输出多条（每条带不同 dims 值）
- `dims`/`vals` 的 `id` 对应指标组内定义的维度/指标 id，`value` 为采集值

**返回码语义**：返回码 0 = 采集成功（再按阈值判 normal/abnormal）；返回码 > 0 = 执行失败（target 状态 failed）；未执行 = unexecuted。

### 3.2 常用采集模式

| 模式                  | 适用场景         | 要点                                           |
| --------------------- | ---------------- | ---------------------------------------------- |
| 命令行采集 + 正则解析 | shell 命令取数据 | `subprocess.Popen` 执行，正则 groupdict 提取 |
| API 调用              | HTTP API 取数据  | `requests.request`，注意超时                 |
| 配置文件解析          | 读本地配置       | `os.path.exists` 判存在性后逐行解析          |
| 多指标组 / 带维度多行 | 一次采多组/多行  | 按指标组 append 多条，每条带各自 dims          |

> 先在本机手工把脚本跑通（输出格式正确、能取到值）再配置进套件。采集失败的健壮性：连接失败也应输出带默认值的合法 JSON（如目标服务连不上时输出 `status: stopped` 之类的兜底值），不要让脚本裸抛异常导致返回码 >0。

### 3.3 告警条件（conditions）配置

**比较器（comparators）与适用类型**：

| comparators | 说明       | 适用类型 |
| ----------- | ---------- | -------- |
| `nin`     | 不在列表中 | string   |
| `in`      | 在列表中   | string   |
| `eq`      | 等于       | string   |
| `neq`     | 不等于     | string   |
| `gt`      | 大于       | num      |
| `lt`      | 小于       | num      |
| `between` | 区间       | num      |

> num 类型只能用 `gt`/`lt`/`between`。

**num 型阈值用 `minvalue`/`maxvalue`，左开右闭**：

- **lt（小于）**：`minvalue: 0`，`maxvalue: 目标值`。例：队列深度 < 100 告警 → `comparators: lt, minvalue: 0, maxvalue: 100`
- **gt（大于）**：`minvalue: 目标值`，`maxvalue: 0`。例：CPU >= 80 告警 → `comparators: gt, minvalue: 80, maxvalue: 0`

```yaml
# 队列深度大于 5 告警
- id: CURDEPTH
  type: num
  conditions:
  - comparators: gt
    level: 0
    value: ""
    minvalue: 5
    maxvalue: 0
```

---

## 4. 生命周期管理 API（查询/导入/导出/删除）

以下接口均走 **inspection 服务（端口 8103）**，鉴权（内网 `user`/`org` 头 / OpenAPI AK+SK 签名）、URL 拼接、自动翻页统一按 `concepts/api-calling/api-calling.md` 的方式发 HTTP。下文只给 method/path/参数。

### 4.1 查询套件列表

```
GET /api/v1/inspection?page=<n>&pageSize=<m>[&keyword=<关键字>]
```

分页返回 `data.list` + `data.total`。取全部时按 `page` 递增自动翻页直到 `len(items) < pageSize`（见 concepts/api-calling 翻节约定）。返回项含 `id`/`name`/`status`/`method`/`objectId`/`relationIdWithHost`/`ctime` 等。

> 按套件 id 精确查找：keyword 走显示名模糊匹配，传套件 id（如 `inspector_svc`）可能不命中——需拉全量后按 `id` 精确匹配兜底。

### 4.2 导出 `inspection.info.export.ExportSuite`

```
GET /api/v1/inspection-export/:pluginId
```

产出 tar 文件（套件完整定义：基本信息 + 采集脚本 + 指标组）。用途：跨环境分发、版本备份、套件源码化管理、**修改套件的起点**（导出→改→重打包→重导）。

### 4.3 导入 `inspection.info.import.ImportSuite`

```
POST /api/v1/inspection-import
Content-Type: multipart/form-data
Body: file=<套件tar文件>
```

上传 tar 包即完成创建。**导入是新建而非覆盖更新**——同套件再次导入会产生新套件或冲突。因此"更新套件"的标准姿势是**先删后导**（见 §6.2）：删除旧套件（§4.4）→ 再导入新包。

### 4.4 删除 `inspection.info.delete.DeleteInspectionInfo`

```
DELETE /api/v1/inspection/:pluginId
```

**删除前确认**：该套件没被巡检任务引用（被引用的套件删除后任务失效）；复合套件中的原子套件需先从复合套件移除。

---

## 5. 调试套件 `inspection.collector.debug.DebugCollector`

```
POST /api/v1/inspection/:pluginId/collector-debug
```

| 参数         | 必填       | 说明                                                             |
| ------------ | ---------- | ---------------------------------------------------------------- |
| `pluginId` | 是（路径） | 套件 id。**仅用于定位套件关系**（取 objectId/relationidwithhost 找主机），采集跑的是请求里的 `content` |
| `target`   | 是         | **执行目标实例 ID**（objectId 模型下的一个真实 CMDB 实例），13 位十六进制，正则 `^[0-9a-z]{13}$` 校验 |
| `content`  | 是         | **采集脚本内容**（即 `collectors/script.py` 的 `content` 字段，JSON 转义串原样传入）。**漏传报 `必填 key content 不存在`** |
| `script`   | 是         | 脚本类型（`python` / `shell`），与 content 对应 |
| `args`     | 否         | 脚本入参覆盖`[{key, value}]`——调试用临时值，不改套件定义     |

> **⚠️ DebugCollector 是「调试一段脚本内容」，不是「调试已上架套件」**（2026-07-29 实测）：必须显式传 `content` + `script`；`pluginId` 只决定「按哪个套件的关系找主机」。调试未保存的脚本改动时直接传新 content 即可，无需先更新套件。

**响应**：

| 字段              | 说明                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| `status`        | `ok`（正常执行且通过）/ `failed`（正常执行但有指标命中阈值）/ `unknown`（执行失败或输出解析失败） |
| `msg`           | 执行日志（脚本 stdout/stderr、解析过程）——**排查脚本问题的第一现场**                            |
| `metric_groups` | 解析出的指标组数据（按 dims/vals 结构化的采集结果）                                                     |

> **⚠️ `status=ok` ≠ 采到数据（2026-07-29 实测）**：`status` 只反映「脚本执行 + 输出解析」是否成功。连接失败走兜底（只输出部分指标组）时 `status` 仍为 `ok`，但 `metric_groups[]` 里未输出的组 `metric_group_status: missing`。判断采全与否看 `metric_groups[].metric_group_status`（`ok`/`missing`），阈值判定看 `val_status`——兜底/连接失败场景下阈值判定可能不完整（如 `status=stopped` 未触发 emergency），勿仅凭顶层 `status` 下结论。

**执行链路**（源码 `DebugJob` 实证）：取套件定义 → 按 objectId+target 过滤出实例 → 准备采集任务（args 注入、实例-主机映射）→ 若 agentType=easyops 先下发 sampler 配置 → 通过命令通道在目标主机**真实执行采集脚本**（`CollectNowV2`，可配置 collectCount 多次采集）→ 解析结果返回。

> ⚠️ 调试是**真实下发执行**（不是 dry-run）：脚本会在 target 关联的主机上跑，确保调试脚本无副作用；选 target 时挑测试实例。

**调试工作流**：

1. 新建/修改后，先选一个**典型实例** debug → 看 `unknown`（脚本错误/输出格式错误，读 msg 修脚本）；
2. `failed` → 看 metric_groups 哪个指标命中阈值：是真实异常（套件 OK）还是阈值不合理（调 conditions）；
3. 用 args 覆盖参数反复调试不同取值场景；
4. 再选一个**边缘实例**（数据缺失/规格不同）验证健壮性。

---

## 6. 开发→更新 全流程与排错

### 6.1 完整开发流程

1. **明确巡检对象**：哪个 CMDB 模型？唯一键？实例与主机的关系是否已建模？（没有先在 CMDB 建关系，否则 object_relation_not_ok）
2. **取模型**：调 CMDB 模型描述接口（§2.5）把 `data` 存为 `models.json`（属性名严格按 attrList 的 id）
3. **写采集脚本**：本机手工跑通；实例差异参数走 attr_id；输出格式对齐 §3.1
4. **定义指标组**：category `一级.二级`；每个指标 type/unit/weight；conditions 分级（int 配区间、string 配匹配值）
5. **配 info.yaml + detail.yaml**：relationidwithhost 填法见 §2.2；instanceid 全局唯一
6. **打包**：`tar -czvf "名称(ONEMODEL)_v{版本}.tar.gz" inspector_xxx/`
7. **导入**：ImportSuite（§4.3）
8. **调试**：DebugCollector 验证（§5）
9. **导出分发**：ExportSuite 拿 tar 包纳入版本管理

### 6.2 修改与更新套件

| 场景                         | 操作                                                                                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 小改（调阈值/改脚本/加指标） | 改包文件 → 重打包 → 先删后导（§4.4 删旧 → §4.3 导新）                                                                       |
| 更新到目标环境               | **DeleteInspectionInfo（卸载旧）→ ImportSuite（导新包）**；导入是新建语义，不支持原位覆盖                                 |
| 更新前检查                   | 旧套件被哪些巡检任务引用（任务需同步调整）；套件 status 是否 ok                                                                  |
| 优化阈值误报                 | debug 看 metric_groups 实际采集值分布 → 调 conditions 区间/level；weight 调整影响评分敏感性                                     |
| 脚本执行 unknown             | 读 msg：脚本报错（修脚本）、输出解析失败（对齐 §3.1 格式）、目标主机无 agent/关系断裂（修 relationidwithhost 或 CMDB 关系数据） |

### 6.3 常见坑速查

| 现象                                     | 排查                                                                                                                                                                   |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 导入报`ERR_ABORTED: 数据写入部分失败`  | **instanceid 重复**：查 info.yaml / metrics.yaml 每个指标组 / detail.yaml 三处的 instanceid，确保互不相同；次要查 models.json 属性名是否与模型 attrList 完全一致 |
| 套件 status=keys_not_unique              | keys 选的属性组合在模型内不唯一 → 换/加唯一键属性                                                                                                                     |
| status=object_relation_not_ok            | objectId 与 HOST 的关系没建/建错 → CMDB 检查 relationIdWithHost                                                                                                       |
| 无法定位巡检主机 / relationidwithhost 空 | 见下方专项                                                                                                                                                             |
| debug 返回 unknown                       | 读 msg：脚本语法错误、输出格式不符解析约定、目标机 agent 不在线                                                                                                        |
| debug 返回 failed 但实例实际正常         | 阈值 conditions 不合理 → 按 metric_groups 实际值调区间                                                                                                                |
| 实例取不到/为空                          | objectId 下无实例、唯一键属性为空、实例与主机关系数据缺失                                                                                                              |
| 导入后任务不巡检新套件                   | 导入是新建套件（新 pluginId），巡检任务引用旧套件 id → 任务需重新关联                                                                                                 |

### 6.4 专项：无法定位巡检主机 / relationidwithhost 缺失

`relationidwithhost` 为空或填错会出现"无法定位巡检主机"。**关键前置：模型必须先有到 HOST 的关系。** 中间件/数据库类（继承 `ARTIFACT_INST` 等）通常自带；但**网络/存储设备类**（交换机、路由器、防火墙、负载均衡、存储等，继承 `BASE_NETWARE`）的模型**经常缺失**这条关系。处理：

1. 调 CMDB 模型描述接口（§2.5）查 `relation_list`，筛 `right_object_id == HOST` 的条目；
2. 若**没有**：先在 CMDB 给该模型补建一条到 HOST 的关系（参照平台已有同类套件，如交换机参照光纤交换机 `FIBERCHANNEL_SWITCH@ONEMODEL_host_fc_switches_HOST`），再用真实 `relation_id` 填入 info.yaml；
3. 补建后重新拉取模型更新 models.json。

> 参照方法：用查询套件接口（§4.1）找平台同类型、能正常工作的巡检套件，取其 `relationIdWithHost` 字段值当模板。

---

## 7. 说明

本知识聚焦巡检套件的**结构、字段语义与生命周期**（开发/打包/导入/调试/修改/更新），所有 HTTP 接口只给 method/path/port/参数。**怎么发请求**（内网 `user`/`org` 头鉴权、OpenAPI AK+SK HMAC-SHA1 签名、URL 拼接、列表自动翻页）不在此重复，统一以 `concepts/api-calling/api-calling.md` 为准。
