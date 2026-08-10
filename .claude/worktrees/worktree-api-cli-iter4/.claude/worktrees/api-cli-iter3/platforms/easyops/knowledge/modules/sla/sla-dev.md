# ITSM SLA 管理开发说明

> 面向 LLM 的开发指南。基于 `flowable_service` 组件 `sla` 模块源码整理。
> 目标：通过自然语言驱动 LLM 完成工作日历（营业时间）与 SLA 规则的增删改查，理解 SLA 计时、预警/超时、通知联动的完整机制。
> 前置阅读：[`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md)（SLA 规则的通知策略引用该文档中的 NotifyPolicy）。

---

## 0. 总体模型

```
工作日历 WorkingCalendar（什么是"营业时间"）         SLA 规则 SLARule（时限承诺与超时动作）
├─ 每周工作日 + 时段                                ├─ basicInfo: name/serviceCategory/status/type/ownerId/priorityId
├─ 补班(extraDay) / 休假(holiday)                   │   type=service(整体服务) | step(任务节点)
└─ 独立设置日(independenceDay)                      └─ slaConfig[]: 每个绑定对象(服务/节点)一条
        │                                            ├─ levelConfig[]: 每个优先级级别一行
        │                                            │   ├─ duration 时限 + workingCalendarId 日历
        │                                            │   └─ criticalRate 预警比例(%)
        │                                            ├─ notifyPolicy[]: 预警/超时通知(引用通知策略)
        │                                            ├─ highlight[]: 超时高亮字段
        │                                            └─ autoUpdate: 超时自动处理
        └──────── 计时引擎（internal/sla/helper.go）────────┘
              到期时间 = 起始时间 + duration（只累加日历中的营业时段）
              预警点  = 到期时间 - duration × criticalRate%
              到达预警/超时点 → 发 SLA 信号(warning/timeout/answer_*/done_*)
                              → 按 notifyPolicy 配置发通知（走 NotifyPolicy）
```

**关键认知**：

1. **SLA 计时只算营业时间**：非工作日、当天非工作时段不计时；起始时间在非工作时段时，从下一个工作时段起点开始计（`CalcDestTime`）；
2. **SLA 与通知的衔接**：SLA 规则里的 `notifyPolicy` 直接引用通知策略（NotifyPolicy），预警/超时信号（`warning`/`timeout`/`answer_warning`/`answer_timeout`/`done_warning`/`done_timeout`）同时也是触发器（trigger）的事件源——所以"超时后做动作"有两种实现路径：SLA 规则内置通知（简单场景）或 SLA 信号触发器（复杂动作，见 [`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md) §1.2 SLA 信号）；
3. **优先级联动**：SLA 规则可绑定一个"优先级集"（ITSC_SERVICE_PRIORTY），工单按自身优先级匹配 levelConfig 中对应级别的时限；**已绑定优先级后不允许再改绑**（UpdateSLARule 拦截："已绑定优先级， 不允许修改优先级"）。

**权限**：SLA 规则 `slaRuleAccessAction/Create/Update/Delete`（对应 `itsc:sla_rule_*`）；工作日历接口在 sla_service 中无权限校验（薄封装）。

---

## 1. 工作日历（Working Calendar）

### 1.1 数据模型（config 结构）

```json
{
  "name": "默认工作时间",
  "memo": "5x8",
  "key": "default",
  "builtin": false,
  "config": {
    "workingDayList": [
      {"weekday": 1, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 2, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 3, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 4, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 5, "hours": "09:00~12:00,13:00~18:00"}
    ],
    "holidayList": [
      {"from": "2026-10-01", "to": "2026-10-07", "memo": "国庆", "hours": "00:00~23:59"}
    ],
    "extraDayList": [
      {"from": "2026-09-28", "to": "2026-09-28", "memo": "国庆调休补班", "hours": "09:00~12:00,13:00~18:00"}
    ],
    "independenceDayList": [
      {"date": "2026-12-31", "isOff": 0, "hours": "09:00~12:00"}
    ]
  }
}
```

| 字段                             | 说明                                                                                                                                                       |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name` / `memo` / `key`    | 名称 / 备注 / 唯一标识 key（可按 key 查详情）                                                                                                              |
| `builtin`                      | 是否内置日历                                                                                                                                               |
| `config.workingDayList[]`      | **每周工作日**：`weekday`（0=周日，1~6=周一~周六），`hours` 当日工作时段（逗号分隔多段 `HH:mm~HH:mm`）；**不在此列表的星期 = 全天休息** |
| `config.holidayList[]`         | **休假区间**：`from`/`to`（`YYYY-MM-DD`，闭区间），`hours` 休假时段（空按全天 `00:00~23:59`）；与工作时间**做差集**（如上午休半天）  |
| `config.extraDayList[]`        | **补班区间**：`from`/`to` + `hours` 补班时段（空按全天）；休息日转工作日，工作日则与已有时间**做并集**                                   |
| `config.independenceDayList[]` | **独立设置日（最高优先级）**：`date` 单日，`isOff`（1=休息 / 0=工作），`hours` 对应休息/工作时段。**覆盖以上所有规则**                   |

**日期合成优先级**（`GetWorkdayByDate`）：独立设置日 > 每周工作日 > 补班（并集）> 休假（差集）。

**时间格式**：时段统一 `HH:mm~HH:mm`，多段英文逗号连接，如 `09:00~12:00,14:00~18:00`。

### 1.2 日历接口一览

| 接口                              | 方法 & 路径                                                   | 说明                                                                                  |
| --------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `CreateWorkingCalendar`         | POST`/api/flowable_service/v1/sla/calendar`                 | body 即 §1.1；返回`id`。**创建时自动生成三年（去年/今年/明年）的每日历数据** |
| `ListWorkingCalendar`           | GET`/api/flowable_service/v1/sla/calendar`（page/pageSize） | 列表（含 config）                                                                     |
| `GetWorkingCalendarDetail`      | GET`.../calendar/:id`                                       | 详情（按 id）                                                                         |
| `GetWorkingCalendarDetailByKey` | GET`.../calendar/key/:key`                                  | 详情（按 key）                                                                        |
| `EditCalendarConfig`            | PUT`.../calendar/:id`                                       | 修改 name/memo/config，**重新生成日历数据**                                     |
| `EditCalendarDay`               | PUT`.../calendar/:id/day`                                   | 修改指定日期：`{date, hours, isOff}`——即运行时插入/修改一个独立设置日             |
| `GetCalendarByMonth`            | GET`.../calendar/:id/month?year=&month=`                    | 按月展开每日：`[{date, isOff, workingHours, offHours}]`（合成后的最终生效结果）     |
| `GetCalendarByYear`             | GET`.../calendar/:id/year?year=`                            | 按年统计：`[{month, workingDayCount, holidayCount}]`                                |
| `DeleteWorkingCalendar`         | DELETE`.../calendar/:ids`                                   | 删除，`ids` 多个用 `;` 分隔                                                       |

---

## 2. SLA 规则（SLA Rule）

### 2.1 数据模型（Create/Update 请求体全字段）

```json
{
  "basicInfo": {
    "name": "生产服务SLA协议",
    "serviceCategory": "request",
    "memo": "生产环境服务级别协议",
    "status": "enabled",
    "ownerId": "负责人用户instanceId",
    "type": "service",
    "priorityId": "优先级集instanceId"
  },
  "slaConfig": [
    {
      "bindID": "",
      "bindName": "",
      "levelConfig": [
        {
          "levelName": "high",
          "agreementType": "calendar",
          "workingCalendarId": "工作日历id",
          "duration": "4h",
          "criticalRate": 80
        },
        {
          "levelName": "medium",
          "agreementType": "calendar",
          "workingCalendarId": "工作日历id",
          "duration": "8h",
          "criticalRate": 80
        }
      ],
      "notifyPolicy": [
        {"notifyType": "warning", "notifyPolicyId": "预警通知策略id", "count": 1, "interval": "0"},
        {"notifyType": "timeout", "notifyPolicyId": "超时通知策略id", "count": 3, "interval": "30m"}
      ],
      "highlight": ["ITSC_TITLE"],
      "autoUpdate": false
    }
  ]
}
```

#### basicInfo

| 字段                | 必填 | 说明                                                                                                                                                                         |
| ------------------- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`            | 是   | 规则名称                                                                                                                                                                     |
| `serviceCategory` | 是   | 服务类型（作用于该类型下的服务；值见`GetTriggerEnums.serviceCategory`，如 `request`/`incident`/`change`/`problem`）                                                |
| `memo`            | 否   | 备注                                                                                                                                                                         |
| `status`          | 是   | `enabled` / `disabled`                                                                                                                                                   |
| `ownerId`         | 是   | 规则负责人（用户 instanceId；一个规则只有一个负责人）                                                                                                                        |
| `type`            | 是   | **协议应用类型**：`service`（整体服务——对工单整体计时，承诺"工单从发起到完成的时限"）/ `step`（任务节点——对每个任务节点分别计时，承诺"节点响应时限+完成时限"） |
| `priorityId`      | 否   | 绑定的优先级集（ITSC_SERVICE_PRIORTY instanceId）。**绑定后不可改绑**；不绑则 levelConfig 按单一级别生效                                                               |

#### slaConfig[]（绑定配置，每条对应一个绑定对象）

| 字段                      | 说明                                                                                                                                                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bindID` / `bindName` | 绑定对象标识。`type=service`：服务整体一条，`bindID` 可为空（或填服务 id）；`type=step`：**每条对应流程中的一个 userTaskId**（bindID=节点 id，bindName=节点名）。服务关联流程后，节点清单从流程主版本节点读取 |
| `levelConfig[]`         | **每个优先级级别一行**（不绑优先级集时一行即可）：见下表                                                                                                                                                            |
| `notifyPolicy[]`        | 预警/超时通知配置：见下表                                                                                                                                                                                                 |
| `highlight[]`           | 超时后工单上需要**高亮显示的标准字段**（`ITSC_` 前缀）                                                                                                                                                            |
| `autoUpdate`            | 超时后是否自动处理（如自动流转/更新，按平台版本能力）                                                                                                                                                                     |

#### levelConfig[]（时限配置）

| 字段                  | 说明                                                                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `levelName`         | 级别名（绑定优先级集时 = 优先级 value，如`high`/`medium`/`low`，候选来自优先级集；不绑时自定义如 `default`）                                                                       |
| `agreementType`     | 计时类型：`calendar`（按工作日历计时，配 workingCalendarId）/ `natural`（自然时间 7x24，workingCalendarId 可空）                                                                       |
| `workingCalendarId` | 工作日历 id（`agreementType=calendar` 时必填，即 §1 创建的日历 id）                                                                                                                     |
| `duration`          | **承诺时限**（完成时限；step 类型时同时作为响应时限基准）。Go duration 格式：`"30m"`、`"4h"`、`"2h30m"`；跨天也用时小时表示（如 3 个工作日 = 按日历 24 营业小时 → `"24h"`） |
| `criticalRate`      | **预警比例（百分比整数）**：已消耗时限达到 duration × criticalRate% 时触发**预警**（warning）信号。如 duration=4h、criticalRate=80 → 营业时长消耗 3.2h 时预警，4h 时超时     |

#### notifyPolicy[]（通知配置）

| 字段               | 说明                                                                                                                                                                                                                                                                                                                              |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `notifyType`     | 通知触发点（`sla_task.NotifyTypes`）：`inst` 工单 / `step` 任务（按 type 选）；`warning` 预警 / `timeout` 超时；任务场景细分 `answer`（响应时间）/ `done`（完成时间）——组合语义：step 类型下"响应预警/响应超时/完成预警/完成超时"对应信号 `answer_warning`/`answer_timeout`/`done_warning`/`done_timeout` |
| `notifyPolicyId` | **通知策略 instanceId**（先按 [`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md) 创建 NotifyPolicy，其 notifyType 应为 `process_instance_sla` 或 `process_task_sla`）                                                                                                                                                                                    |
| `count`          | 通知次数（1 = 只发一次）                                                                                                                                                                                                                                                                                                          |
| `interval`       | 重复通知间隔（duration 格式，`"0"` 不重复；`"30m"` 每 30 分钟重发，共 count 次）                                                                                                                                                                                                                                              |

> **SLA 规则 ↔ 通知策略的引用关系**：`ListNotifyPolicy` 返回的 `slaRules[]` 即从此处反查（遍历所有规则 slaConfig.notifyPolicy）。删除通知策略前先确认没有被 SLA 规则引用。

### 2.2 接口一览

| 接口                        | 方法 & 路径                                                        | 说明                                                                                                                                                                                                                                                               |
| --------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CreateSLARule`           | POST`/api/flowable_service/v1/sla/rule`                          | body 即 §2.1；返回`instanceId`                                                                                                                                                                                                                                  |
| `UpdateSLARule`           | PUT`/api/flowable_service/v1/sla/rule/:ruleId`                   | **全量覆盖**（basicInfo + slaConfig 整体替换）；**已绑定优先级不允许改绑**（报"已绑定优先级， 不允许修改优先级"）                                                                                                                                      |
| `GetSLARule`              | GET`/api/flowable_service/v1/sla/rule/:ruleId`                   | 详情：含 basicInfo 全字段 + slaConfig 全量 + priority（instanceId/name/priorityValues）+ serviceInstanceId/Name                                                                                                                                                    |
| `SearchSLARule`           | POST`/api/flowable_service/v1/sla/rule/_search`（page/pageSize） | 过滤：`priorityId`、`instanceIds[]`、`name`（模糊）、`serviceName`（按关联服务名模糊）、`ownerName`（模糊）、`serviceCategory`、`status`、`Q`（name/服务名/负责人模糊）。返回列表含 serviceInstances[]（引用该规则的服务）、priority、负责人显示名 |
| `DeleteSLARule`           | DELETE`/api/flowable_service/v1/sla/rule/:ruleIds`               | 批量，ruleIds 用`;` 分隔                                                                                                                                                                                                                                         |
| `GetSLAConfigByServiceId` | GET`.../sla/config/:serviceId`                                   | ⚠️**Deprecated**：按服务查 SLA 配置（serviceConfig + 流程节点 nodeConfig），仅供理解绑定关系                                                                                                                                                               |

### 2.3 SLA 与服务/工单的生效链路

1. **绑定**：服务实例关联 SLA 规则（服务侧 `slaRuleId`，建/编服务时设置；`set_service_sla_config` 配置服务质量）；一条规则可被多个服务引用（SearchSLARule 的 serviceInstances 反查）；
2. **计时启动**：工单发起 → 按其优先级（及规则的 levelConfig）确定 duration 与日历 → 计算到期时间 `timeoutTime`（只累加营业时段）；step 类型则每个任务节点进入时分别计时（响应时限 + 完成时限，挂起时限见流程 nodeSettings.suspendSetting）；
3. **预警/超时**：消耗达 criticalRate% → 发预警信号；达 100% → 超时信号。工单级：`warning`/`timeout`；任务级：`answer_warning`/`answer_timeout`（响应）、`done_warning`/`done_timeout`（完成）；
4. **通知**：信号到达 → 按 slaConfig.notifyPolicy 发送（NotifyPolicy 渲染 `${变量}`，变量同 [`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md) §1.4）；
5. **状态呈现**：工单/任务 `slaStatus` 字段：工单 `normal`/`warning`/`timeout`；任务 `unAnswer`/`answered`/`answer_warning`/`answer_timeout`/`done_warning`/`done_timeout`；
6. **剩余时间**：`rTime` 展示（挂起/作废显示 `--`；已完成的用完成时间反算）。

---

## 3. SLA 报表接口（只读，供数据看板）

统一前缀 `/api/flowable_service/v1/sla/report/...`，时间参数 `st`/`et`（`YYYY-MM-DD HH:mm:ss`）：

| 接口                          | 说明                                                |
| ----------------------------- | --------------------------------------------------- |
| `GetSLAReportSLAEnabled`    | SLA 覆盖面占比（已配置/未配置 SLA 的服务数）        |
| `GetSLAReportSLAStatus`     | 工单运行占比统计（正常/预警/超时分布）              |
| `GetSLAReportStatistical`   | SLA 工单量统计（按时间粒度 timeInterval）           |
| `GetSLAReportTimeConsuming` | 解决时长统计占比（按 scope/action 聚合耗时区间）    |
| `GetSLAReportTimeout`       | 超时责任人排行（st/et + page）                      |
| `GetSLAReportWarning`       | 预警责任人排行                                      |
| `GetSLAReportAnswer`        | 任务响应排行                                        |
| `GetSLAReportDone`          | 任务完成排行                                        |
| `GetSLAReportComment`       | 服务评价排行（评价平均分，未配置 SLA 计入"未设置"） |
| `GetSLAReportServiceLevel`  | 服务级别占比                                        |
| `GetSLAReportWorkingDay`    | 营业时间占比                                        |

---

## 4. 端到端示例

**需求**："生产环境的事件工单（incident），高优先级 4 营业小时解决、80% 预警，中优先级 8 营业小时；预警邮件通知当前处理人 1 次，超时每 30 分钟通知督办人共 3 次。"

**Step 1 — 建工作日历**（如已有可跳过，用 `ListWorkingCalendar` 拿 id）：

```json
POST /api/flowable_service/v1/sla/calendar
{
  "name": "默认工作时间", "key": "default_5x8", "builtin": false, "memo": "周一至周五 9-18",
  "config": {
    "workingDayList": [
      {"weekday": 1, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 2, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 3, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 4, "hours": "09:00~12:00,13:00~18:00"},
      {"weekday": 5, "hours": "09:00~12:00,13:00~18:00"}
    ],
    "holidayList": [], "extraDayList": [], "independenceDayList": []
  }
}
```

**Step 2 — 建两个通知策略**（参考 [`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md)）：

- 策略 A：`notifyType=process_instance_sla`，`triggerSignal=warning`，notifyRange=`curr_operator`，notifyMode=`email`；
- 策略 B：`notifyType=process_instance_sla`，`triggerSignal=timeout`，notifyRange=`supervisor`。

**Step 3 — 建 SLA 规则**：

```json
POST /api/flowable_service/v1/sla/rule
{
  "basicInfo": {
    "name": "生产事件SLA",
    "serviceCategory": "incident",
    "memo": "",
    "status": "enabled",
    "ownerId": "<负责人用户id>",
    "type": "service",
    "priorityId": "<优先级集id>"
  },
  "slaConfig": [{
    "bindID": "", "bindName": "",
    "levelConfig": [
      {"levelName": "high", "agreementType": "calendar", "workingCalendarId": "<日历id>", "duration": "4h", "criticalRate": 80},
      {"levelName": "medium", "agreementType": "calendar", "workingCalendarId": "<日历id>", "duration": "8h", "criticalRate": 80}
    ],
    "notifyPolicy": [
      {"notifyType": "warning", "notifyPolicyId": "<策略A id>", "count": 1, "interval": "0"},
      {"notifyType": "timeout", "notifyPolicyId": "<策略B id>", "count": 3, "interval": "30m"}
    ],
    "highlight": [], "autoUpdate": false
  }]
}
```

**Step 4 — 服务绑定**：编辑目标服务实例，关联该 SLA 规则 id（`set_service_sla_config` / 编辑服务接口的 slaRuleId）。

---

## 5. LLM 操作检查清单

1. **先备齐引用物**：建 SLA 规则前确认 ① 工作日历 id（没有先建）、② 通知策略 id（notifyType 必须是 `process_instance_sla`/`process_task_sla` 的策略）、③ 优先级集 id（levelName 必须取自该优先级集的 value）；
2. **type 决定计时粒度**：`service` = 工单整体时限（一条 slaConfig）；`step` = 节点时限（每个 userTask 一条 slaConfig，bindID=节点 id，节点清单以流程主版本为准——流程改版后要检查 SLA 配置里的节点是否还存在）；
3. **duration 是营业时长**（calendar 类型）：客户说"3 天"要换算成营业小时（如 8h/天 → `"24h"`），或建议用 `natural` 自然时间；**不要**直接写 `"72h"` 配 calendar；
4. **criticalRate 是百分比整数**（80 = 80%），不是小数；
5. **优先级集绑定不可逆**：Update 时不允许改绑 priorityId——建规则前确认好；
6. **删通知策略/SLA 规则前查引用**：`ListNotifyPolicy` 看 slaRules/triggers；`SearchSLARule` 看 serviceInstances；
7. **全量覆盖**：UpdateSLARule 整体替换 basicInfo+slaConfig——先 GetSLARule 拿全量再改；
8. **超时后的复杂动作**（自动关单/升级/执行工具）：SLA 规则本身只做通知+高亮+autoUpdate；复杂动作用"SLA 信号触发器"（`process_instance_sla`/`process_task_sla` scope 的 trigger，事件 `warning`/`timeout`/`answer_timeout` 等），两者可叠加；
9. **日历变更影响在途工单**：EditCalendarConfig 会重新生成日历，在途工单的剩余时间按新日历重算，谨慎修改；
10. **报表口径**：超时/预警排行来自通知发送记录（sla_record），即"发了通知才算数"——notifyPolicy 的 count=0 或不配通知时报表无数据，排查报表问题先查通知配置。

---

## 6. 相关知识

- **通知策略/触发器**：SLA 规则的 `notifyPolicy` 引用 NotifyPolicy，SLA 信号（warning/timeout/answer_*/done_*）也是触发器事件源——见 [`notify-trigger-dev.md`](../notify_trigger/notify-trigger-dev.md)。
- **流程节点 SLA**：`type=step` 时 slaConfig 按 userTaskId 绑定，节点清单以流程主版本为准——见 [`process-definition-v2-dev.md`](../process_development/process-definition-v2-dev.md)。
- **工单 SLA 运行态字段**：`slaStatus`/`rTime`/`timeoutTime` 等，见 [`order-info.md`](../../concepts/order-info.md)。

