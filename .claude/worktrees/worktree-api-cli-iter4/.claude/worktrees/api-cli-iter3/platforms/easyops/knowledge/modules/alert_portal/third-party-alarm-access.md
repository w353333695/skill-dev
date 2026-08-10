---
name: third-party-alarm-access
kind: module
module: alert_portal
tags:
- 三方告警接入
- 第三方事件接入
- 事件源
- webhook
- 资源关联
- 告警重定级
- alert_portal
- 接入策略
completeness: partial
gaps:
- 告警重定级 level 枚举实测仅 critical/warning/info 三种(_EVENT_ACCESS_RULE.rule schema anyOf 约束)，区别于平台等级全集 5 种(§6.3)；共济等级映射 1-2→critical、3→warning、4-5→info
- 接入策略 filters 告警筛选器 JSON 子结构未展开(隐藏模型字段已探明：_EVENT_ACCESS_HANDLER=name/source/priority/filters，_EVENT_ACCESS_RULE=name/type/rule[anyOf]/ignore_fail)
scope: 三方告警接入全链路（事件源注册→接入策略→资源关联/告警重定级规则→webhook 上报→告警规则→事件入库→排查）
related:
- cmdb-instance
- instance-id
- api-calling
last_verified: '2026-08-03'
---

# 三方告警接入（第三方事件接入）知识详解

> 适用产品：智能监控（HyperInsight / EasyOps 监控告警）
> 能力定位：让第三方监控平台（Zabbix / Prometheus / 自研平台等）的告警事件接入优维告警事件中心，统一对象定义、统一告警等级、统一内容格式，形成标准化事件后由告警规则做分组、通知、屏蔽等处理。
> 维护说明：本知识基于产品手册《监控.md》、接口文档 `alert_portal`、常见问题库与历史工单沉淀，供 LLM 回答"三方告警接入 / 第三方事件接入 / 事件源 / 资源关联 / 告警重定级 / webhook 上报告警"等问题使用。

---

## 一、概述

### 1.1 为什么需要三方告警接入

客户现场常按角色建设多套监控平台（应用、中间件、DB、机房、主机等），各平台产生的告警在**告警对象定义、告警等级、告警内容格式**上存在不一致，导致：

- **告警太多**：不同平台大量冗余事件重复告警，叨扰运维人员；
- **无法定位**：数据联系匮乏，无法对事件做上层消费（根因分析、统一派单等）。

通过三方告警接入，可以把第三方平台的告警汇聚到优维告警事件中心，实现**标准化的告警事件中心**。

### 1.2 核心能力

| 能力 | 说明 |
|------|------|
| IT资源翻译（资源关联） | 深度消费 CMDB，把告警事件关联到统一的 IT 资源实例，得到一致的告警对象定义、更丰富的告警信息，为告警根因分析打基础 |
| 告警重定级 | 按规则把第三方告警等级映射为平台统一等级，是事件标准化的重要手段 |
| 统一处理 | 第三方事件接入后，可由告警规则匹配告警事件，进行分组压缩、通知、屏蔽等处理，减少冗余告警通知 |
| 后续消费 | 支撑故障自愈、告警升级、超时自动解除、根因分析、统一派单等能力 |

### 1.3 完整接入流程（总览）

第三方事件接入会根据配置的策略及规则，对告警事件的原始数据进行加工处理（资源关联、告警重定级等），形成标准化事件后再写入告警库；继而由告警策略匹配告警事件，进行分组压缩、通知等处理。

```
第三方监控平台 --POST(webhook)--> alert_portal 接入网关
   ↓ 校验事件源(accessId) + 匹配接入策略(过滤条件)
   ↓ 资源关联规则(cmdb-translate) + 告警重定级规则
   ↓ 标准化事件 → Kafka(monitor.event)
   ↓ alert_channel_go 消费处理(分组/抑制/通知/入库)
   ↓ 告警库(monitor_event / monitor_event_last)
   ↓ 告警规则匹配 → 分组压缩 → 通知
```

**界面操作三步（核心流程）**：

1. 进入平台 → 菜单 **设置 > 告警规则 > 第三方事件接入**
2. 在 **事件源 TAB**，单击 **新建**，创建事件源（注册后会分配 webhook 地址）
3. 在 **事件接入策略 TAB**，单击 **新建**，创建事件接入策略
4. 在 **接入策略详情** 页，依次单击 **新建规则**，创建 **资源关联规则** 和 **告警重定级规则**
5. 第三方平台把告警 POST 到 webhook 地址
6. **必须再配置告警规则**，否则第三方告警事件不会在"当前告警"中显示

> 注：官方手册说明"更多接入说明可参考事件接入指引文档"，接入策略的简要说明见下文各章节。

### 1.4 组件架构与数据流向

| 组件 | 语言/端口 | 职责 |
|------|-----------|------|
| `alert_portal` | Go / 8149 | 第三方告警的**接入网关**：webhook 接收、事件源注册、接入规则维护、处理失败记录查询 |
| `alert_service` | Go / 8131 | 告警后台：告警事件查询/导出/管理 |
| `alert_channel_go` | Go / 6608 | 从 Kafka `monitor.event` 消费告警事件，跑事件动作管线（丢弃/显示名/阈值/资源关联/指标丰富/通知/自愈/屏蔽/分组/抑制），入库并驱动通知 |
| `alert_metric_process` | Rust / 8297 | 告警流组件（指标→告警事件加工） |

**关键存储对象（CMDB 隐藏模型）**：

| 模型 ID | 模型名 | 作用 |
|---------|--------|------|
| `_EVENT_ACCESS_DEFINE` | 事件接入注册信息 | 事件源实例，字段含 `source`（告警源标识）、`showName`（展示名）等，导出时把 source 翻译为 showName |
| `_EVENT_ACCESS_HANDLER` | 事件接入处理器 | 事件接入策略（过滤条件 + 处理规则），按 source + 过滤条件匹配 |
| `_EVENT_ACCESS_RULE` | 事件接入规则 | 资源关联规则（cmdb-translate）、告警重定级规则等 |

**Kafka**：`alert_portal` 处理完成后写入 Kafka topic `monitor.event`，`alert_channel_go` 消费。若 kafka topic 分区过少会导致告警处理慢、通知延时。

**日志**：接入网关日志位于组件部署目录 `log/alert_portal.log`（接入处理过程、失败原因）、`log/alert_portal_access.log`（HTTP 访问日志）。排查接入问题首选查看 `alert_portal.log`。

---

## 二、第一步：创建事件源

### 2.1 界面操作

设置 > 告警规则 > 第三方事件接入 → **事件源 TAB** → **新建**。

### 2.2 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| 事件源名称（source） | 是 | 告警源标识。第三方上报 body 中的 `source` 字段必须与之匹配；接入策略会先按该值筛选事件 |
| 展示名称（showName） | 否 | 告警源在平台上的展示名称，为空则显示 source |
| 备注（memo） | 否 | 备注说明 |

### 2.3 注册接口（接口方式）

- **接口**：`alert_portal.alert_portal.RegisterAccessDefine`
- **方法/路径**：POST `/api/v1/alert/register`
- **请求头**：`Content-Type: application/json`、`org`（机构ID）、`user`（用户名）
- **请求体**：`{ "source": "zabbix", "showName": "zabbix", "memo": "zabbix接入告警事件源" }`
- **返回**：`{ "code":0, "data": { "accessId": "5d430391654df" } }`

```bash
curl -X POST \
  -H 'Content-Type: application/json' \
  -H 'org: 2988466' \
  -H 'user: easyops' \
  -d '{"source":"zabbix","showName":"zabbix","memo":"zabbix接入告警事件源"}' \
  'http://127.0.0.1:8149/api/v1/alert/register'
```

### 2.4 webhook 地址构成

注册成功后分配一个 webhook 地址，所有发送到该地址的告警事件都会标记来源为该事件源：

```
{平台地址}/api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{accessId}
```

- `/api/gateway/alert_portal.webhook` 是 API 网关前缀（对应 `logic.alert_portal` 服务）；
- `{org}` 为机构 ID；
- `{accessId}` 为注册返回的接入 ID（用于识别事件源）。

> 示例：`http://192.168.100.90/api/gateway/alert_portal.webhook/api/v1/alert/common/8888/34996fb5149fc387388151f28ebc57204fd94ce8`

### 2.5 底层存储

事件源实例保存在 CMDB 模型 `_EVENT_ACCESS_DEFINE` 中。可用 CMDB 实例接口查询/管理，例如：

- 查询事件源：`POST /api/gateway/cmdb.instance.AggregateInstance/object/_EVENT_ACCESS_DEFINE/instance/aggregate`
- 新增事件源（注册接口）：`POST /api/gateway/alert_portal.alert_portal.RegisterAccessDefine/api/v1/alert/register`

---

## 三、webhook 上报格式（ThirdPartyAlert）

### 3.1 请求说明

- **接口**：`alert_portal.alert_portal.PostAlert`
- **方法/路径**：POST `/api/v1/alert/common/:org/:accessId`
- **请求头**：`Content-Type: application/json`
- **请求体**：JSON（见 3.2 字段表）
- **返回**：`{ "code":0, "data": { "status": "success" } }`

### 3.2 字段详解（每个字段含义）

| 字段 | 类型 | 说明 |
|------|------|------|
| `alertId` | string | **告警 ID，去重键**。相同 `alertId` 被视为同一告警事件（重复上报会累加告警次数而非新事件），建议用"告警规则+实例+指标+发生时间"构造唯一值 |
| `alertDims` | object | 告警维度（自定义键值对）。会写入事件中心"维度"字段，可用于告警规则通过维度过滤目标事件、通知模板取用 |
| `metricName` | string | 告警指标名，如 `node.cpu.usage` |
| `value` | string | 告警值 |
| `metricUnit` | string | 值单位，如 `%`、`bytes`，可为空 |
| `subject` | string | 告警标题 |
| `content` | string | 告警内容 |
| `time` | number(int) | 告警时间（**Unix 时间戳，秒，必须整数 int**——giraffe 契约 assertInteger，浮点会被拒 400；call_card 卡片声明 number 会 coerce float，须 `--param-json` 传 int）。**与平台时间偏差不能超过 30 分钟**，超时会话被丢弃 |
| `isRecover` | bool | 是否恢复事件。恢复通知需显式上报 `isRecover:true`，否则告警恢复不会同步到平台 |
| `extInfo` | object | 扩展信息，会填充到告警事件中心的 field 字段，可用于后续告警通知内容丰富、告警重定级取值等 |
| `originInfo` | object | 原始告警信息，即第三方告警转换为此结构体前的原始数据；过滤条件、资源关联的 `value_path`、重定级的 `key_path` 常从此取 |
| `source` | string | 告警源，**必须与注册事件源的 source 一致** |
| `level` | string | 第三方告警等级（可选，如 `info`/`warning`/`critical`），平台会按"告警重定级规则"映射为统一等级 |

### 3.3 curl 示例

```bash
curl --location --request POST 'http://192.168.100.90/api/gateway/alert_portal.webhook/api/v1/alert/common/8888/34996fb5149fc387388151f28ebc57204fd94ce8' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "alertId": "bbe540e74e2452511f8bb978544fe037729f9681",
    "alertDims": null,
    "metricName": "node.cpu.usage",
    "value": "59.18333333451301",
    "metricUnit": "",
    "subject": "Instance 192.168.100.163:18004 CPU 3 usage high",
    "content": "192.168.100.163:18004 CPU 3 usage above 50% (current value: 59.18333333451301)",
    "time": 1587783926,
    "isRecover": false,
    "extInfo": {},
    "originInfo": {"ip": "192.168.100.163"},
    "source": "prometheus"
  }'
```

### 3.4 响应与错误排查

- 正常返回：`{"code":0,"codeExplain":"","data":{"status":"success"}}` → 事件已被接入网关接收。
- **注意**：`status:"success"` 只代表接入网关**已接收**，不代表事件成功入库/产生告警。若入库失败，需查 `alert_portal.log` 或调用"查询处理失败记录"接口（见 §9）。
- 常见报错：`{"code":100000,"codeExplain":"ERR_INVALID_ARGUMENT","error":"[130006]alert \`xxx\` not handler match"}` → 该事件**没有匹配到任何接入策略**（过滤条件未命中），见 §10.2。

### 3.5 Prometheus 专用接口

若第三方为 Prometheus Alertmanager，可直接对接其 webhook 原生格式，无需自建转换：

- **接口**：`alert_portal.alert_portal.PostPrometheusAlert`
- **方法/路径**：POST `/api/v1/alert/prometheus/:org/:accessId`
- **请求体**：Prometheus Alertmanager 通知格式，**必须包含 `alerts` 数组**（每条 alert 含 `status/labels/annotations/startsAt/endsAt/generatorURL`），缺 `alerts` 字段会报错。

平台侧通过 `alert_portal` 组件配置 `prometheus_config` 完成字段映射（可按需调整）：

```yaml
prometheus_config:
  subject: "alerts.annotations.summary"   # 标题 ← alerts[].annotations.summary
  content: "alerts.annotations.description" # 内容 ← annotations.description
  metric:  "alerts.annotations.metric"
  value:   "alerts.annotations.value"
  unit:    "alerts.annotations.unit"
  alertDims: "alerts.0.labels"             # 维度 ← 第一条 alert 的 labels
  ext_info:
    - key: "alertInfo"                     # extInfo.alertInfo ← alerts[0] 整条
      path: "alerts.0"
```

### 3.6 时间约束（重点）

上报的 `time`（Unix 时间戳）与平台当前时间**偏差超过 30 分钟的事件会被丢弃**。客户端需保证与平台时钟同步，或用当前时间生成 `time` 字段。

---

## 四、第二步：创建事件接入策略

### 4.1 策略概念

第三方事件接入策略本质上是一套 **过滤条件 + 处理规则**：对所有接入的告警数据按事件源 + 过滤条件筛选，匹配到的告警事件将根据策略中的资源关联规则、告警重定级规则等对原始数据进行加工处理，形成标准化告警事件。

### 4.2 事件源

即注册的事件源名称（source）。接入策略会**先根据事件源筛选**第三方告警事件（即 `strategy.Source == event.source`）。

### 4.3 过滤条件

| 配置项 | 说明 |
|--------|------|
| 原始告警字段 | 在第三方告警事件数据中的取值路径，如 `originInfo.groupLabels.alertname` 会取 `originInfo` 下 `groupLabels` 的 `alertname` 字段 |
| 匹配方式 | 精确匹配 或 正则匹配 |
| 匹配值 | 匹配值或正则表达式 |

只有**满足所有过滤条件**的事件才会匹配到该事件接入策略。

### 4.4 匹配逻辑与常见问题

- 事件先按 `source` 找到对应事件源的接入策略，再逐条匹配过滤条件；
- 全部条件命中 → 应用策略下的资源关联规则、告警重定级规则；
- **一个事件没有匹配到任何策略时**，接入网关会返回 `not handler match` 报错（见 §10.2）；
- 正则匹配"看起来匹配成功但无事件"：正则需能完整命中目标值，且平台正则提取基于特定分隔（历史案例中客户最终用脚本自行处理正则提取，避免依赖策略内正则）。

---

## 五、资源关联规则（IT 资源翻译 / cmdb-translate）

### 5.1 概念与原理

资源关联规则将告警事件与 IT 资源（CMDB）实例关联。平台根据规则**组装 CMDB 查询条件**，查询对应资源实例，最终把查询到的**实例 id 和模型 id** 写入告警事件数据（对应标准化事件的 `instanceId` / `objectId` 字段）。

> 这是"第三方告警能关联到哪个资源、告警目标显示什么"的关键。关联成功后，后续告警规则可按该资源模型配置监控目标。

### 5.2 字段详解

```yaml
object_id: HOST                    # 要查询的 IT 资源模型 id（如 HOST / APP / 服务节点等）
query:                             # 查询条件，支持 eq、ne、like、in、lt、gt 等以及 and、or 逻辑
  ip:
    '$eq': '@{ip}'                 # @{ip} 引用 values 中定义的 ip 变量
values:                            # 变量值定义（每个 value 生成一个查询变量）
  - key: 'ip'                      # 变量标识（query 中用 @{key} 引用）
    value_path: 'origin_info.ip'   # 取值路径：从告警原始数据取哪个字段（点分法，origin_info.xxx / extInfo.xxx）
    match_multi: false             # 是否允许多个实例匹配；false 时只允许匹配到 1 个实例，默认 false
    match_regex: "^192.168"        # 取值正则：与 value_path 配合，用正则从字段值中提取，如 ip:端口 → [0-9.]+
```

| 属性 | 说明 |
|------|------|
| `object_id` | 关联查询的 CMDB 模型 ID（如 HOST、APP、CLUSTER 等） |
| `query` | CMDB 查询条件，形如 `字段: {操作符: 值}`。操作符支持 `$eq`（等于）、`$ne`（不等于）、`$like`（模糊）、`$in`（在集合中）、`$lt`/`$gt`（小于/大于）等，逻辑支持 `$and`、`$or`；值可以是字面量或 `@{变量}` 引用 |
| `values[].key` | 变量标识，query 中用 `@{key}` 引用 |
| `values[].value_path` | 变量取值路径，从告警事件取数（点分法），如 `originInfo.resource_id`、`extInfo.alertInfo.labels.instance`。⚠️ **实测前缀用驼峰**（2026-08-03 232 真调）：`originInfo.xxx` 命中资源关联，`origin_info.xxx`（下划线）不命中——与 §3.2 ThirdPartyAlert 字段名（驼峰 `originInfo`）一致；本节早期示例的 `origin_info` 系笔误，构建时用驼峰 |
| `values[].match_multi` | 是否允许匹配多个实例。`false`（默认）时**只允许匹配到恰好 1 个实例**：匹配 0 个或多于 1 个都不会正常入库；`true` 时匹配多个实例会生成多个事件 |
| `values[].match_regex` | 取值正则，配合 value_path 从原始字段值中提取所需部分。如 Prometheus 的 `192.168.100.162:18001`（ip:端口），可设 `[0-9.]+` 提取 ip |

### 5.3 完整示例

**示例一：按 ip 精确匹配主机**

```yaml
object_id: HOST
query:
  ip:
    '$eq': '@{ip}'
values:
  - key: 'ip'
    value_path: 'origin_info.ip'
    match_multi: false
```

**示例二：ip 是 ip:端口 格式，用正则提取**

```yaml
object_id: HOST
query:
  ip:
    '$eq': '@{ip}'
values:
  - key: 'ip'
    value_path: 'origin_info.ip'            # 原始值如 "192.168.100.162:18000"
    match_regex: '(?:[0-9]{1,3}\.){3}[0-9]{1,3}'   # 提取出纯 ip
    match_multi: false
```

### 5.4 多条件匹配（真实案例模板）

资源关联规则**支持多条件**，多个条件之间默认 `$and`，同一逻辑组内可再套 `$or`：

```yaml
object_id: HOST
query:
  $and:
    - $or:
        - ip:
            $eq: '@{ip}'
    - $or:
        - region.region:           # 关系属性（关联模型的字段）也支持
            $eq: '@{region}'
values:
  - key: ip
    match_multi: false
    match_regex: '^192.168'
    value_path: 'origin_info.ip'
  - key: region
    match_multi: false
    value_path: 'origin_info.region'
```

### 5.5 接口操作

- **新建资源关联规则 / 告警重定级规则**：`alert_portal.access_rule.CreateAccessRule` → POST `/api/v1/access_rule`
- **更新**：`alert_portal.access_rule.UpdateAccessRule` → PUT `/api/v1/access_rule/:instanceId`
- **删除**：CMDB 删除实例 → `DELETE /api/gateway/cmdb.instance.DeleteInstance/object/_EVENT_ACCESS_RULE/instance/{instanceId}`

**创建接入规则请求体**（type 为 `cmdb-translate` 表示资源关联/IT资源翻译）：

```json
{
  "ignore_fail": true,
  "name": "翻译规则",
  "type": "cmdb-translate",
  "handlerId": "5a73dd16cf738",
  "rule": {
    "match_multi": false,
    "object_id": "HOST",
    "query": { "ip": { "$eq": "@{ip}" } },
    "values": [
      { "key": "ip",
        "match_regex": "(?:[0-9]{1,3}\\.){3}[0-9]{1,3}",
        "value_path": "extInfo.alertInfo.labels.instance" }
    ]
  }
}
```

请求体字段：`name`（规则名）、`type`（规则类型，`cmdb-translate` 资源关联 / 告警重定级）、`handlerId`（所属接入策略实例 id）、`rule`（规则内容）、`ignore_fail`（匹配失败是否忽略）。

### 5.6 匹配规则与注意

- **必须恰好匹配到 1 条实例**（`match_multi:false` 时）：匹配 0 条或多条都不会正常入库/产生告警（真实案例反复验证）；
- `value_path` 取值取不到、正则提取不到，会导致变量为空、查询无结果；
- 关联字段要与 CMDB 实例实际属性对应（如 `originInfo.name` 与 APP 模型的 `name` 字段）；
- 未关联到资源的第三方事件默认不入库，需配合平台特性开关 `exception-events` 才可展示"未正常关联实例的异常接入事件"。

---

## 六、告警重定级规则

### 6.1 概念

将第三方告警事件的等级重新映射为平台统一等级。当满足 filters 条件时，把告警等级设置为配置的 level。

### 6.2 字段详解

```yaml
- filters:
  - key_path: 'extInfo.alertInfo.labels.severity'   # 取值路径（第三方事件中的路径，点分法）
    method: match                                    # 匹配方式（match 等）
    value: error                                     # 匹配值
  level: critical                                    # 满足条件后设置的平台等级
- filters:
  - key_path: 'extInfo.alertInfo.labels.severity'
    method: match
    value: warn
  level: warning
```

| 属性 | 说明 |
|------|------|
| `filters[].key_path` | 在第三方告警事件数据中的取值路径（点分法），如 `extInfo.alertInfo.labels.severity` |
| `filters[].method` | 匹配方式（如 `match`） |
| `filters[].value` | 匹配值 |
| `level` | 满足条件后设置的平台告警等级 |

### 6.3 平台告警等级体系

平台统一告警等级（字符串）为：`message`（提示）、`info`（通知/提示）、`warning`（警告）、`critical`（严重）、`emergency`（致命）。

> 等级数值排序：message=0 < info=1 < warning=2 < critical=3 < emergency=4。界面展示文案可通过 `alertLevelLabels` 配置调整；不同环境的等级中文文案有差异（3.0 环境：critical=紧急、emergency=危急；大禹/基础监控环境：warning=错误、critical=严重、emergency=致命）。

> ⚠️ **重定级规则 level 枚举实测仅 3 种**（2026-08-03 232 真调）：`_EVENT_ACCESS_RULE.rule` 的 json schema anyOf 约束 `level ∈ {critical, warning, info}`，**不含 message/emergency**。即告警重定级规则（§6）只能把第三方等级映射到 critical/warning/info 三档；message/emergency 无法经重定级规则设置。重定级 rule 结构实测为 **list**，每项 `{filters:[{key_path, method, value}], level}`，`filters[].method` 枚举 `{match, map}`。

### 6.4 示例：按 Prometheus severity 映射

```yaml
- filters:
  - key_path: 'extInfo.alertInfo.labels.severity'
    method: match
    value: error
  level: critical
- filters:
  - key_path: 'extInfo.alertInfo.labels.severity'
    method: match
    value: warning
  level: warning
```

### 6.5 与"告警升级"的区别

- **告警重定级（本规则）**：事件接入阶段，把第三方等级映射为平台等级（**直接改写事件的 level**）；
- **告警升级（平台能力）**：事件持续未恢复超过一定时长后，升级通知方式/通知接收人（不改 level 字符串本身），按告警规则中的告警升级策略配置。两者不要混淆。

### 6.6 注意事项

- 重定级规则取值应使用**实际存在的路径**（如 `extInfo` 中的真实字段值），不要使用特殊/无效值——真实案例中客户用了特殊 value 导致接入异常，切到 extInfo 实际值后恢复正常；
- 未配置重定级规则时，事件沿用上报的 `level` 字段值；若未上报 `level`，将按平台默认处理。

---

## 七、第三步：配置告警规则（触发、加工、通知）

### 7.1 为什么必须配置告警规则

第三方告警事件完成接入后，**必须进一步配置告警规则**，否则无法在平台直接查看到相关的第三方告警事件（webhook 已接收、事件已入库，但"当前告警"不显示）。

### 7.2 告警规则策略链

创建告警规则（设置 > 告警规则 > 新建规则），以可视化策略链配置：

| 模块 | 策略项 | 功能说明 |
|------|--------|----------|
| 监控范围 | 监控目标 | 定义触发告警的具体资源实例范围（如主机、服务、应用等），**需选择与接入策略资源关联规则一致的资源模型** |
| 触发规则 | 告警条件 | 为监控指标设置不同等级的阈值判断，支持"与/或"逻辑、多等级阈值、告警收敛、生效时间窗口、告警升级 |
| 告警增强 | 告警丰富 | 通知时补充上下文信息（资源信息丰富/指标信息丰富） |
| 告警聚合 | 分组压缩 | 按自定义维度把相似事件合并成一条通知，减少信息过载 |
| 告警通知 | 告警通知 | 配置通知渠道、接收人、通知内容模板 |
| 告警控制 | 通知屏蔽 | 指定时间段屏蔽特定资源/指标的通知（告警仍记录） |
| 告警控制 | 通知抑制 | 关键告警发生时抑制相关其他告警通知 |

> 注意：修改告警规则中引用的策略会影响所有使用该策略的告警规则。

### 7.3 通过告警维度过滤目标事件

第三方（如 Zabbix）接入的告警，维度都是自定义的。告警规则支持**按告警维度过滤**目标事件，再按需进行事件丰富、通知、屏蔽等处理，可更灵活地处理事件内容过滤。

例如：当第三方告警的 `alertDims` 中 `hostGroup` 属于 `bjucloud` 的主机时，指定特殊的告警规则。

### 7.4 第三方事件其他能力

- **故障自愈**：创建故障自愈规则时可选择事件来源为"第三方告警平台的告警"，按告警规则关键字等判断条件触发自愈流程；
- **告警超时自动解除**：第三方事件支持告警超时自动解除功能；
- **告警升级机制**：第三方告警事件支持告警升级机制。

---

## 八、事件入库后的标准化模型（MonitorEvent）

标准化事件主要字段（查询接口 `/api/v1/monitor_event/_search` 返回，供理解告警事件结构）：

| 字段 | 说明 |
|------|------|
| `eventId` / `_id` | 事件 ID |
| `alertId` | 告警 ID（去重键） |
| `alertCount` | 告警次数（重复上报累加） |
| `alertDims` | 告警维度（含 instanceId / objectId / _job 等） |
| `level` | 告警等级（message/info/warning/critical/emergency） |
| `source` | 告警来源（system=统一数据告警；三方接入为该事件源 source 的展示名） |
| `objectId` / `instanceId` | 关联的资源模型 id / 实例 id（**资源关联规则的结果**） |
| `target` | 告警资源（如 `192.168.100.163(29360128)`） |
| `metricName` / `metricValue` / `metricUnit` | 指标名 / 告警值 / 单位 |
| `subject` / `content` | 标题 / 内容 |
| `originContent` / `originTitle` | 原始告警内容 / 标题 |
| `time` / `startTime` / `insertTime` / `processTime` / `notifyTime` | 各类时间戳 |
| `isRecover` | 是否恢复 |
| `isGroup` | 是否已分组 |
| `status` | 事件状态（unsent/sent/group/suppress/block/converged/inhibition 等） |
| `handlers` | 命中的处理规则列表（含规则名、类型、起止时间） |
| `notifies` / `alertReceivers` | 通知信息 / 告警接收人 |
| `ruleId` / `alertRuleId` / `alertRuleVersion` | 命中的告警规则 |
| `recoverType` | 恢复类型（auto 自动 / manual 手动） |
| `type` | 事件类型（alert/change/event） |

> 第三方事件接入后一般 `strategyType` 为 `thirdPartyEvent`/`thirdPartyOriginalEvent`，在 `handlers` 中可见处理链。

---

## 九、接口清单汇总

| 操作 | 服务/接口 | 方法/路径 |
|------|-----------|-----------|
| 注册事件源（新增接入） | `alert_portal.RegisterAccessDefine` | POST `/api/v1/alert/register` |
| 展示所有告警源 | `alert_portal.ListSources` | GET `/api/v1/alert/source/list` |
| 第三方告警统一接入 | `alert_portal.PostAlert` | POST `/api/v1/alert/common/:org/:accessId` |
| Prometheus 告警推送 | `alert_portal.PostPrometheusAlert` | POST `/api/v1/alert/prometheus/:org/:accessId` |
| 事件上报 | `alert_portal.PostEvent` | POST `/api/v1/event/common` |
| 变更事件上报 | `alert_portal.PostChangeEvent` | POST `/api/v1/event/change` |
| **查询处理失败记录** | `alert_portal.SearchFailRecords` | POST `/api/v1/alert/fail/search` |
| 新建接入规则 | `alert_portal.CreateAccessRule` | POST `/api/v1/access_rule` |
| 更新接入规则 | `alert_portal.UpdateAccessRule` | PUT `/api/v1/access_rule/:instanceId` |
| 删除接入规则/策略 | `cmdb.instance.DeleteInstance` | DELETE `/_EVENT_ACCESS_RULE|_EVENT_ACCESS_HANDLER/instance/{instanceId}` |
| 查询接入策略 | `cmdb.instance.PostSearch` | POST `/object/_EVENT_ACCESS_HANDLER/instance/_search` |
| 新增接入策略 | `cmdb.instance.CreateInstance` | POST `/v2/object/_EVENT_ACCESS_HANDLER/instance` |
| 查询事件源 | `cmdb.instance.AggregateInstance` | POST `/object/_EVENT_ACCESS_DEFINE/instance/aggregate` |
| 查询告警事件 | `alert_service.SearchMonitorEvent` | POST `/api/v1/monitor_event/_search` |

> 网关调用时统一加前缀 `/api/gateway/{服务}.{接口}/{路径}`，如
> `/api/gateway/alert_portal.alert_portal.RegisterAccessDefine/api/v1/alert/register`。

---

## 十、常见问题排查指南（FAQ 沉淀）

### 10.1 上报成功（返回 success）但"当前告警"不显示

- **原因**：未配置告警规则。第三方事件入库后，需配置告警规则（监控目标/告警条件）才会产生告警事件、进入"当前告警"。
- **处理**：设置 > 告警规则，新建/复用告警规则，监控目标选择与接入策略资源关联一致的资源模型。

### 10.2 返回 `[130006]alert \`xxx\` not handler match`

- **含义**：该告警事件**没有匹配到任何事件接入策略**。
- **排查**：① 上报 `source` 是否与事件源一致；② 过滤条件是否满足；③ 资源关联规则 query 是否能命中实例。
- **真实案例**：把规则 query 的取值路径改成 `originInfo.name`，使其与 APP 模型的 `name` 字段匹配后恢复。

### 10.3 资源关联匹配不到 / 匹配多条

- 资源关联规则（`match_multi:false`）要求**恰好匹配 1 条实例**：匹配 0 条或多条都会失败。
- **排查**：查 `alert_portal.log` 确认是否匹配到实例；检查 `value_path`/`match_regex` 取值、CMDB 实例属性值是否匹配、是否有多条重复实例（建议相关字段设置唯一）。

### 10.4 上报的告警时间偏差超 30 分钟

- 上报 `time` 与平台时间偏差超过 30 分钟的事件会被丢弃。
- **处理**：客户端与平台做时钟同步，或用当前时间生成 `time`。

### 10.5 第三方告警恢复未同步

- **原因**：调用方**未发送恢复事件**（即未上报 `isRecover:true` 的恢复事件）。
- **处理**：第三方平台在告警恢复时同步上报恢复事件；排查侧先核对 alert_portal 日志里是否只有告警事件、没有恢复事件。

### 10.6 Prometheus 上报报错

- 对接 `post_prometheus_alert` 时 body 必须为 Alertmanager webhook 格式且**包含 `alerts` 数组**（缺失会报错）。
- 字段映射由 `alert_portal` 配置 `prometheus_config` 控制（subject/content/metric/value/unit/alertDims/extInfo）。

### 10.7 接入的告警处理慢、通知延时不稳定

- **原因**：`alert_channel_go` 消费能力不足，Kafka topic 分区过少。
- **处理**：增加 Kafka topic 分区（`monitor.event`），提升 `alert_channel_go` 消费能力（真实案例：2 分区 → 增加后恢复）。

### 10.8 告警重定级"切换 value 后接入异常"

- 重定级的 value 若使用**特殊/无效值**会导致异常；应取 `extInfo` 等字段中的**实际值**作为匹配值。

### 10.9 如何查看处理失败记录

调用 `POST /api/v1/alert/fail/search`，参数 `query`、`page`、`page_size`、`start_time`（默认 7 天前）、`end_time`，返回每条含 `alertId`、`accessId`、`failReason`、`handleHistory` 等，是**排查接入/入库失败的关键接口**。

### 10.10 相关特性开关

| 开关 | 默认 | 说明 |
|------|------|------|
| `ignore-third-party-events` | 开启 | 【通过"第三方事件接入策略"接入的事件】不入库（只显示满足 5.0 告警条件的第三方事件）；修改后需重启 `alert_channel_go` 与 `metadata_center` |
| `exception-events` | 关闭 | 打开异常事件：第三方事件没有正常关联实例时，支持展示这些异常接入事件 |
| `show-alert-config` | - | 告警规则的菜单调整（第三方事件接入/事件中心） |

---

## 十一、参考来源

- 产品手册：《监控.md》— 管理第三方事件接入 / 告警规则 / 事件中心
- 接口文档：`api_docs / alert_portal`（post_alert、register_access_define、create/update_access_rule、search_fail_records、post_prometheus_alert）
- 常见问题库：智能监控 / 超融合监控（HyperInSight） / 资源管理（CMDB）
- 组件说明：alert_portal / alert_service / alert_channel_go 组件清单与配置

---

## 十二、三方告警推送代码范例

以下代码用于将第三方监控平台的告警数据转换为平台标准格式并通过 webhook 推送到 EasyOps 平台。

> **与本文前十一章节的关系**：前十一章节讲的是"事件源注册 / 接入策略 / 资源关联规则 / 告警重定级规则"的**配置方法和每个属性含义**——那些通过界面或 API 做一次初始化即可。本章是**运行时推送告警数据**的代码范例，不含初始化操作。

**供 LLM 结合客户第三方平台 API 资料时作为骨架，按需替换告警数据转换逻辑。**

### 12.1 完整代码

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
三方告警数据转换与 webhook 推送脚本 (示例模板)
================================================

功能:
  将第三方监控平台的告警数据转换为平台标准 ThirdPartyAlert 格式,
  通过 webhook POST 推送到 alert_portal。

兼容性: Python 2.7+ / Python 3.x
依赖:   requests (pip install requests)

使用时需要用户提供:
  1. PLATFORM_HOST:  客户 EasyOps 平台地址
  2. ORG:            客户机构 ID
  3. ACCESS_ID:      已在平台上创建好的事件源的 accessId
  4. THIRD_PARTY_SOURCE: 事件源标识(source)

关键注意事项:
  - 上报 time 与平台时间偏差不能超过 30 分钟, 超时会被丢弃
  - 告警恢复时 isRecover 必须设置为 True, 否则恢复不同步
  - 返回 status:"success" 仅表示网关已接收; 实际入库需查
    alert_portal.log 或调用 POST /api/v1/alert/fail/search
"""

from __future__ import print_function, unicode_literals

import hashlib
import json
import logging
import os
import sys
import time
import traceback

# ---- Python 2/3 兼容 ----
if sys.version_info[0] >= 3:
    string_types = (str,)
else:
    string_types = (str, unicode)  # noqa: F821
    reload(sys)  # noqa: F821
    sys.setdefaultencoding('utf-8')

try:
    import requests
except ImportError:
    sys.stderr.write(
        "[ERROR] 缺少 requests 库, 请执行: pip install requests\n")
    sys.exit(1)


# ============================================================
# 配置 — 按客户实际环境修改
# ============================================================

# 平台地址(不需要末尾 /)
PLATFORM_HOST = os.environ.get('EASYOPS_HOST', 'http://192.168.100.162')

# 机构 ID
ORG = os.environ.get('EASYOPS_ORG', '8888')

# 已在平台上创建好的事件源的 accessId (在平台 设置>告警规则>第三方事件接入 中获取)
ACCESS_ID = os.environ.get('EASYOPS_ACCESS_ID', '34996fb5149fc387388151f28ebc57204fd94ce8')

# 事件源标识(与注册时的 source 一致)
THIRD_PARTY_SOURCE = os.environ.get('EASYOPS_SOURCE', 'zabbix')

# ---- 日志配置(含时间戳/级别/模块/行号) ----
LOG_FORMAT = (
    '%(asctime)s | %(levelname)-7s | %(module)s:%(lineno)d | %(message)s'
)
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('third_party_alert')


# ============================================================
# 工具函数
# ============================================================

def _json_dumps(obj):
    """Python 2/3 兼容的 JSON 序列化, 中文不转义."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _post_webhook(path, payload):
    """
    POST 请求到 alert_portal webhook。

    Args:
        path:    webhook 路径, 如 '/alert_portal.webhook/api/v1/alert/common/8888/abc123'
        payload: ThirdPartyAlert dict

    Returns:
        (status_code, response_dict) — 网络异常时返回 (None, None)

    将请求耗时、响应摘要写入日志, 方便追踪每次推送。
    """
    url = '{host}/api/gateway{path}'.format(host=PLATFORM_HOST, path=path)
    logger.info("[webhook] POST %s", url)

    headers = {
        'Content-Type': 'application/json',
        'org': str(ORG),
        # 注意: webhook 接口对 auth 要求较宽松(allow policy),
        # 但 org 请求头仍然建议填写以便日志追踪
    }
    body = _json_dumps(payload)
    logger.debug("[webhook] body(%d bytes): %s", len(body), body[:300])

    try:
        resp = requests.post(url, headers=headers, data=body, timeout=30)
    except requests.exceptions.Timeout:
        logger.error("[webhook] 请求超时: %s", url)
        return None, None
    except requests.exceptions.ConnectionError:
        logger.error("[webhook] 连接失败, 请检查平台地址 %s 是否可达", PLATFORM_HOST)
        return None, None
    except Exception:
        logger.error("[webhook] 请求异常:\n%s", traceback.format_exc())
        return None, None

    elapsed_ms = resp.elapsed.total_seconds() * 1000
    logger.info("[webhook] HTTP %d (%.0fms)", resp.status_code, elapsed_ms)

    try:
        data = resp.json()
    except Exception:
        logger.error("[webhook] 响应非 JSON: %s", resp.text[:500])
        return resp.status_code, None

    code = data.get('code', -1)
    if code != 0:
        logger.warning(
            "[webhook] 业务码=%s, error=%s",
            code, data.get('error', ''))

    return resp.status_code, data


# ============================================================
# 核心: 将第三方告警转换为 ThirdPartyAlert
# ============================================================
# 这是客户需要根据第三方平台 API 返回结构重点修改的部分。
# 以下以 Zabbix 风格的字段名作为示例。

def build_alert_payload(raw_alert, is_recover=False):
    """
    把第三方平台的一条原始告警转换为平台 ThirdPartyAlert 格式。

    Args:
        raw_alert:  dict, 第三方平台的原始告警数据
        is_recover: bool, 是否为恢复事件

    Returns:
        dict, 符合平台 webhook 接收格式

    ThirdPartyAlert 各字段含义(详见知识文档 §3.2):
      alertId   — 告警去重键; 相同的 alertId 会被平台视为同一告警事件
                  (重复上报只会累加告警次数而非新建事件)
      alertDims — 告警维度(自定义键值对), 可用于告警规则按维度过滤目标事件
      metricName— 告警指标名
      value     — 告警值
      metricUnit— 值单位
      subject   — 告警标题
      content   — 告警内容
      time      — 告警发生时间(Unix 秒级时间戳), 与平台偏差不能超过 30 分钟
      isRecover — 是否恢复事件
      extInfo   — 扩展信息, 入告警事件 field 字段, 供通知模板 / 重定级取值
      originInfo— 原始告警数据, 供接入策略过滤条件 / 资源关联规则 value_path 取值
      source    — 告警源标识, 必须与注册时的 source 一致
      level     — 第三方自身等级, 后续由告警重定级规则映射为平台统一等级
    """
    alert_id = _make_alert_id(raw_alert)

    return {
        'alertId': alert_id,
        'alertDims': _extract_dims(raw_alert),
        'metricName': raw_alert.get('trigger_name', 'unknown'),
        'value': str(raw_alert.get('current_value', '')),
        'metricUnit': raw_alert.get('unit', ''),
        'subject': _make_subject(raw_alert),
        'content': _make_content(raw_alert),
        'time': _make_timestamp(raw_alert),
        'isRecover': is_recover,
        'extInfo': _build_ext_info(raw_alert),
        'originInfo': raw_alert,              # 原始数据全量放入, 供资源关联 / 过滤匹配
        'source': THIRD_PARTY_SOURCE,
        'level': raw_alert.get('severity', 'info'),
    }


def _make_alert_id(raw_alert):
    """
    生成去重的告警 ID。

    原则: 同一告警(同一条规则 + 同一个实例 + 同一个指标 + 同一发生时段)
    应产生相同的 alertId; 平台用 alertId 做去重+累加计数。

    本示例使用 SHA1(事件ID|主机|触发器|触发器ID)。

    客户按实际情况调整拼接字段, 确保同一告警能稳定生成相同 ID。
    """
    parts = [
        str(raw_alert.get('event_id', '')),
        str(raw_alert.get('host', '')),
        str(raw_alert.get('trigger_name', '')),
        str(raw_alert.get('trigger_id', '')),
    ]
    raw = '|'.join(parts)
    if sys.version_info[0] >= 3:
        raw = raw.encode('utf-8')
    return hashlib.sha1(raw).hexdigest()


def _extract_dims(raw_alert):
    """
    从原始告警中提取维度, 写入 alertDims。

    维度后续用于:
      - 告警规则按维度过滤目标事件(如只对 bjucloud 的主机组发通知)
      - 通知模板引用(如 {{alert_dims.product}})
      - 分组压缩按维度聚合

    客户按第三方平台的实际字段调整提取逻辑。
    """
    dims = {}
    for key in ('host', 'host_group', 'application', 'service'):
        val = raw_alert.get(key)
        if val is not None:
            dims[key] = str(val)
    return dims


def _make_subject(raw_alert):
    """
    生成告警标题(subject)。

    标题在告警列表、通知消息中展示。
    建议包含严重等级、主机、告警摘要。
    """
    host = raw_alert.get('host', 'unknown')
    trigger = raw_alert.get('trigger_name', raw_alert.get('alert_name', 'unknown'))
    severity = raw_alert.get('severity', '')
    return '[{sev}] {host}: {trigger}'.format(
        sev=severity, host=host, trigger=trigger)


def _make_content(raw_alert):
    """
    生成告警内容(content)。

    内容在告警详情、通知消息体中展示。
    建议包含主机、指标名、当前值、阈值、原始描述。
    """
    host = raw_alert.get('host', 'unknown')
    trigger = raw_alert.get('trigger_name', 'unknown')
    value = raw_alert.get('current_value', '')
    threshold = raw_alert.get('threshold', '')
    description = raw_alert.get('description', '')
    lines = [
        '主机: {host}'.format(host=host),
        '触发器: {trigger}'.format(trigger=trigger),
    ]
    if value:
        lines.append('当前值: {val}'.format(val=value))
    if threshold:
        lines.append('阈值: {th}'.format(th=threshold))
    if description:
        lines.append('描述: {desc}'.format(desc=description))
    return '\n'.join(lines)


def _make_timestamp(raw_alert):
    """
    提取原始告警时间, 转为 Unix 秒级时间戳。

    如果第三方告警已有时间戳, 优先使用;
    否则使用当前时间(此时需确保客户端与平台时钟同步在 30 分钟内)。
    """
    ts = raw_alert.get('time')
    if isinstance(ts, (int, float)) and ts > 1000000000:
        return int(ts)
    # 无时间戳则用当前时间
    return int(time.time())


def _build_ext_info(raw_alert):
    """
    构建 extInfo(扩展信息)。

    extInfo 写入告警事件的 field 字段, 用于:
      - 告警通知内容模板: {{field.xxx}}
      - 告警重定级规则取值: key_path 可指向 extInfo.xxx
      - 告警丰富策略: 可把 extInfo 中的字段附加到通知内容
    """
    ext = {}
    ext['severity'] = raw_alert.get('severity', '')
    for key in ('trigger_id', 'trigger_url', 'event_id', 'host_group'):
        val = raw_alert.get(key)
        if val is not None:
            ext[key] = val
    return ext


# ============================================================
# 推送: 单条 + 批量
# ============================================================

def push_alert(payload, alert_index=1):
    """
    推送一条告警到平台 webhook。

    Args:
        payload:      build_alert_payload() 的返回 dict
        alert_index:  序号(仅用于日志标记)

    Returns:
        bool — 推送成功(HTTP 200 且 code==0)为 True

    webhook 地址:
      /api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{accessId}

    日志输出:
      - 每次推送记录请求摘要和响应结果
      - 失败时记录完整 payload(截断 500 字符)供排查
    """
    path = '/alert_portal.webhook/api/v1/alert/common/{org}/{access_id}'.format(
        org=ORG, access_id=ACCESS_ID)

    status, data = _post_webhook(path, payload)

    if status is None or data is None:
        logger.error(
            "[推送 #%d] 网络错误, alertId=%s",
            alert_index, payload.get('alertId'))
        return False

    if data.get('code') != 0:
        err = data.get('error', '')
        logger.error(
            "[推送 #%d] 失败, alertId=%s, code=%s, error=%s",
            alert_index, payload.get('alertId'), data.get('code'), err)
        # 失败时输出 payload 摘要方便排查(截断 500 字符)
        logger.debug(
            "[推送 #%d] 失败 payload: %s",
            alert_index, _json_dumps(payload)[:500])
        return False

    recv_status = data.get('data', {}).get('status', 'unknown')
    is_recover = payload.get('isRecover', False)
    logger.info(
        "[推送 #%d] 成功! alertId=%s, status=%s, isRecover=%s",
        alert_index, payload.get('alertId'), recv_status, is_recover)
    return True


def push_alerts_batch(raw_alerts, recover_event_ids=None):
    """
    批量推送告警。

    Args:
        raw_alerts:        第三方平台原始告警列表 (list of dict)
        recover_event_ids: 需发送恢复事件的事件 ID 集合(set of str), 可选

    Returns:
        (success_count, fail_count)

    日志输出:
      - 每条告警的推送结果(成功/失败+原因)
      - 结束后的统计汇总
      - 有失败时提示排查路径
    """
    if recover_event_ids is None:
        recover_event_ids = set()

    total = len(raw_alerts)
    logger.info(
        "开始批量推送: 共 %d 条, 恢复事件 %d 条",
        total, len(recover_event_ids))

    success = 0
    fail = 0

    for i, raw_alert in enumerate(raw_alerts, 1):
        alert_id = _make_alert_id(raw_alert)
        is_recover = alert_id in recover_event_ids
        if is_recover:
            logger.info("[#%d/%d] 恢复事件, alertId=%s", i, total, alert_id)

        # 构造 payload
        try:
            payload = build_alert_payload(raw_alert, is_recover=is_recover)
        except Exception:
            logger.error(
                "[#%d/%d] 构造 payload 异常:\n%s\n原始数据: %s",
                i, total, traceback.format_exc(), _json_dumps(raw_alert)[:500])
            fail += 1
            continue

        # 推送
        if push_alert(payload, alert_index=i):
            success += 1
        else:
            fail += 1

    logger.info(
        "推送完成: 成功 %d, 失败 %d, 共 %d", success, fail, total)

    if fail > 0:
        logger.warning(
            "存在 %d 条失败! 排查路径: 1)查 alert_portal.log 日志; "
            "2)调用 POST /api/v1/alert/fail/search 查失败记录", fail)

    return success, fail


# ============================================================
# 故障排查辅助: 拉取失败记录
# ============================================================

def query_fail_records(start_time=None, end_time=None):
    """
    调用平台接口查询处理失败记录, 用于排查接入问题。

    Args:
        start_time: Unix 秒级时间戳, 默认 7 天前
        end_time:   Unix 秒级时间戳, 默认当前时间

    Returns:
        失败记录列表(list of dict)

    每条记录含:
      alertId / accessId / source / objectId / instanceId
      / failReason / handleHistory / level / subject / content 等
    """
    if start_time is None:
        start_time = int(time.time()) - 7 * 24 * 3600
    if end_time is None:
        end_time = int(time.time())

    url = '{host}/api/gateway/alert_portal.alert_portal.SearchFailRecords/api/v1/alert/fail/search'.format(
        host=PLATFORM_HOST)
    headers = {
        'Content-Type': 'application/json',
        'org': str(ORG),
    }
    body = _json_dumps({
        'page': 1,
        'page_size': 50,
        'query': {},
        'start_time': start_time,
        'end_time': end_time,
    })

    logger.info("查询处理失败记录: %s", url)
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=30)
        data = resp.json()
    except Exception:
        logger.error("查询失败记录异常:\n%s", traceback.format_exc())
        return []

    records = data.get('data', {}).get('list', [])
    total = data.get('data', {}).get('total', 0)
    logger.info("失败记录: 共 %d 条, 当前页 %d 条", total, len(records))
    for rec in records:
        logger.warning(
            "  alertId=%s | accessId=%s | source=%s | failReason=%s",
            rec.get('alertId', 'N/A'),
            rec.get('accessId', 'N/A'),
            rec.get('source', 'N/A'),
            json.dumps(rec.get('failReason', {}), ensure_ascii=False))
    return records


# ============================================================
# 主流程示例
# ============================================================

def main():
    """
    示例主流程: 从第三方平台拉告警 → 转换 → 推送 → 排查。

    实际使用时需替换 fetch_alerts_from_third_party() 的实现,
    改为通过第三方平台 API 拉取真实告警数据。
    """
    logger.info(
        "===== 三方告警推送 =====\n"
        "平台:     %s\n"
        "机构:     %s\n"
        "事件源:   %s\n"
        "accessId: %s\n"
        "=========================",
        PLATFORM_HOST, ORG, THIRD_PARTY_SOURCE, ACCESS_ID)

    # ----- 1. 从第三方平台拉取告警(示例数据, 实际需替换) -----
    raw_alerts = fetch_alerts_from_third_party()
    logger.info("从第三方平台拉取到 %d 条告警", len(raw_alerts))

    if not raw_alerts:
        logger.info("无告警, 退出")
        return

    # ----- 2. 区分恢复事件(按第三方平台的告警状态字段判断) -----
    recover_ids = set()
    for a in raw_alerts:
        status = a.get('status', '')
        if status in ('OK', 'RESOLVED', 'recovered'):
            recover_ids.add(_make_alert_id(a))

    # ----- 3. 批量推送 -----
    success, fail = push_alerts_batch(raw_alerts, recover_ids)

    # ----- 4. 查询失败记录(如有失败则排查) -----
    if fail > 0:
        logger.warning("推送存在失败, 查询平台侧失败记录...")
        query_fail_records()

    logger.info("脚本执行完毕: 成功 %d, 失败 %d", success, fail)


def fetch_alerts_from_third_party():
    """
    从第三方平台拉取告警的占位函数。

    客户需替换为实现: 调第三方 API → 返回原始告警 dict 列表。

    返回示例(模拟 Zabbix 风格数据, 仅用于演示):
    """
    now = int(time.time())
    return [
        {
            'event_id': 'evt-10001',
            'host': '192.168.100.163',
            'host_group': 'bjucloud',
            'trigger_name': 'CPU usage high',
            'trigger_id': 'trig-10001',
            'current_value': '85.5',
            'threshold': '80',
            'unit': '%',
            'severity': 'warning',
            'status': 'PROBLEM',
            'description': 'CPU usage above 80% on host 192.168.100.163',
            'time': now - 60,
        },
        {
            'event_id': 'evt-10002',
            'host': '192.168.100.164',
            'host_group': 'bjucloud',
            'trigger_name': 'Disk space low',
            'trigger_id': 'trig-10002',
            'current_value': '92.1',
            'threshold': '90',
            'unit': '%',
            'severity': 'critical',
            'status': 'PROBLEM',
            'description': 'Disk usage above 90% on host 192.168.100.164',
            'time': now - 120,
        },
        {
            'event_id': 'evt-10001',      # 与第一条相同 event_id,
            'host': '192.168.100.163',    # 代表同一条告警已恢复
            'host_group': 'bjucloud',
            'trigger_name': 'CPU usage high',
            'trigger_id': 'trig-10001',
            'current_value': '45.2',
            'threshold': '80',
            'unit': '%',
            'severity': 'info',
            'status': 'OK',               # OK → 恢复事件
            'description': 'CPU usage back to normal on 192.168.100.163',
            'time': now,
        },
    ]


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(130)
    except Exception:
        logger.error("未预期的异常:\n%s", traceback.format_exc())
        sys.exit(1)
```

### 12.2 代码结构速览

| 模块 | 功能 | 客户需要改什么 |
|------|------|----------------|
| 配置区 | `PLATFORM_HOST` / `ORG` / `ACCESS_ID` / `THIRD_PARTY_SOURCE` | 替换为实际值 |
| `_post_webhook()` | HTTP POST 到 webhook, 记录请求耗时和响应 | 不改 |
| `build_alert_payload()` | 把第三方告警 dict → ThirdPartyAlert dict | **核心修改点**: 字段映射 |
| `_make_alert_id()` | 生成去重的 alertId | 按第三方平台的唯一标识字段调整 |
| `_extract_dims()` | 提取维度到 alertDims | 按实际字段调整 |
| `_make_subject()` / `_make_content()` | 生成标题/内容 | 按实际字段调整 |
| `_make_timestamp()` | 提取时间戳 | 按第三方时间字段调整 |
| `_build_ext_info()` | 构建 extInfo(扩展信息) | 把重定级/通知需要的字段放入 |
| `push_alert()` | 单条推送 | 不改 |
| `push_alerts_batch()` | 批量推送 + 恢复事件识别 + 统计 | 不改 |
| `query_fail_records()` | 查询平台侧处理失败记录 | 不改 |
| `fetch_alerts_from_third_party()` | 从第三方平台拉告警 | **核心修改点**: 调用第三方 API |
| `main()` | 编排: 拉取 → 转换 → 推送 → 排查 | 按间隔/调度逻辑调整 |

### 12.3 LLM 使用指南

拿到客户第三方平台 API 资料后, 按以下步骤输出代码:

1. **读 API 数据结构** → 确定告警事件包含哪些字段(主机标识、指标名、告警值、严重等级、状态、时间等)

2. **改 `fetch_alerts_from_third_party()`** → 调用第三方 API, 返回原始告警 dict 列表

3. **改 `build_alert_payload()` 及其子函数** → 把第三方字段映射到 ThirdPartyAlert:
   - `originInfo` 放原始数据全量(供资源关联规则取值匹配)
   - `extInfo` 放严重等级等关键字段(供告警重定级规则取值)
   - `alertDims` 放自定义维度(供告警规则按维度过滤)
   - `alertId` 按"规则+实例+指标+时间"构造稳定去重 ID
   - `isRecover=True` 针对已恢复的事件

4. **改配置区** → 填入客户实际平台地址、org、accessId、source

### 12.4 各平台对接要点

| 对接平台 | originInfo 放入 | extInfo 放入 | 资源关联常用路径 |
|----------|----------------|-------------|------------------|
| Zabbix | trigger + host 完整字段 | severity、trigger_id | `originInfo.host` 或 `originInfo.ip` 匹配 HOST |
| Prometheus | alerts[].labels + annotations | alertInfo=alerts[0] | `extInfo.alertInfo.labels.instance` 正则提取 IP |
| 日志告警(ELK等) | 全文内容 | application、host | 按内容提取的 host/ip |
| 自研平台 | 原始 body 全量 | 严重等级、标签 | 按实际字段 |
