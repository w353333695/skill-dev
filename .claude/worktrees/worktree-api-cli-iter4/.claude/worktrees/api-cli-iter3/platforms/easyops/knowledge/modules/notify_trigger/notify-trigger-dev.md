# ITSM 通知策略 & 触发器管理开发说明

> 面向 LLM 的开发指南。基于 `flowable_service` 组件 `notify_policy`、`trigger` 模块源码整理。
> 目标：通过自然语言驱动 LLM 完成通知策略（NotifyPolicy）与触发器（ITSCTrigger）的增删改查，并理解二者的联动关系（触发器 → 动作 → 引用通知策略）。

---

## 0. 总体模型：通知策略与触发器的关系

```
触发器 ITSCTrigger（何时做）                 通知策略 NotifyPolicy（通知谁、说什么）
├─ scope  作用域（工单/任务/服务/SLA...）
├─ event  监听信号（start,pass,reject...）
├─ status enabled/disabled
└─ config.actionList[]  动作列表
   ├─ name: send_message  ──→ args.notifyPolicyId ──→ 引用通知策略
   │                          args.notifyInterval / notifyTimes
   ├─ name: update_process_instance_status（改工单状态）
   ├─ name: update_priority（改优先级）
   ├─ name: update_process_task_status（改任务状态）
   ├─ name: update_service_status（改服务状态）
   ├─ name: exec_tool（执行工具）
   └─ name: update_assignee（改处理人，内部动作）
```

**运行时链路（源码实证 `internal/trigger/trigger.go`）**：工单/任务/服务发生信号 → 查询 `status=enabled` 且 event 匹配、且与该工单关联（绑定在服务上 / 绑定在流程定义上 / 节点 nodeSettings.triggerIdList 上）的触发器 → 对每个 action 用 `evaluator.CheckConditions` 做条件求值 → 命中的 action 投递到消息队列由 handler 执行（send_message 则按 notifyPolicyId 找到策略发送通知）。

**权限**：通知策略 `itsc:notify_config_access/create/update/delete`；触发器 `itsc:trigger_manage_access/create/update/delete`。

---

## 1. 通知策略（notify_policy）

### 1.1 数据模型（Create/Update 请求体全字段）

```json
{
  "name": "工单完成通知创建人",
  "notifyType": "process_instance",
  "triggerSignal": "finish",
  "notifyRange": ["creator"],
  "notifyMode": ["email", "wechat_work"],
  "subject": "【${service_name}】您的工单 ${process_instance_number} 已完成",
  "content": "工单 ${process_instance_name} 已于 ${action} 完成，请及时查看。",
  "customUserGroup": {
    "usernameList": ["user1", "user2"],
    "groupIdList": ["groupId1"]
  },
  "domainModel": {"instanceId": "领域模型ID"}
}
```

| 字段                | 类型     | 必填 | 说明                                                                                                                                                                                                                                                          |
| ------------------- | -------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`            | string   | 是   | 策略名称，**全局唯一**（创建/改名重复报 `通知名称[xxx]已存在！`）                                                                                                                                                                                     |
| `notifyType`      | string   | 是   | 通知类型（= 触发类型），取值见 §1.2；决定可用的信号/范围/变量                                                                                                                                                                                                |
| `triggerSignal`   | string   | 是   | 触发信号，取值取决于 notifyType，见 §1.2；`common` = 通用信号                                                                                                                                                                                              |
| `notifyRange`     | string[] | 是   | 通知范围（通知谁），取值见 §1.3                                                                                                                                                                                                                              |
| `notifyMode`      | string[] | 是   | 通知方式（渠道），可用渠道由 msgsender 动态提供（`ListEnums(name=notifyMode)` 查询）；常见：`email`（邮件）、`wechat_work`（企业微信）、`ding_talk`（钉钉）；**老数据 `ding_talk` 会在读取时自动转换为新渠道 key**（convertLegacyNotifyMode） |
| `subject`         | string   | 是   | 通知标题，支持`${变量}` 占位（§1.4）                                                                                                                                                                                                                       |
| `content`         | string   | 是   | 通知正文，支持`${变量}` 占位                                                                                                                                                                                                                                |
| `customUserGroup` | object   | 否   | **notifyRange 含 `custom_user` 时使用**：`usernameList` 指定用户名列表、`groupIdList` 用户组 ID 列表                                                                                                                                              |
| `domainModel`     | object   | 否   | 领域模型`{instanceId}`                                                                                                                                                                                                                                      |

### 1.2 notifyType 与 triggerSignal 取值

`notifyType` 枚举（`trigger_type.Signal`）：

| key                                 | 含义          | 可用信号（triggerSignal）                                                                                                                                                                                                                                                                                              |
| ----------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `process_instance`                | 工单信号      | `start` 发起、`finish` 完成、`suspend` 挂起、`activate` 重启、`cancel` 作废、`close` 关单、`revoke` 撤销、`comment` 评价、`invite_comment` 邀请评价、`priority_change` 优先级变更、`supervise` 督办、`common` 通用。（创建时可选中排除 `warning`/`timeout`/`delete`，这两个走 SLA 类型） |
| `process_task`                    | 工单任务信号  | `todo` 待办、`pass` 通过、`reject` 退回、`jump` 直达、`withdraw` 撤回、`assign` 转派、`distribute` 派单、`cc` 分阅、`cc_read` 分阅已读、`add` 加签、`add_todo` 加签待办、`add_reject` 加签驳回、`claim` 认领、`common` 通用。（排除 `ack`/SLA 四个信号）                                 |
| `service_instance`                | 服务信号      | `enabled` 启用、`disabled` 禁用                                                                                                                                                                                                                                                                                    |
| `process_instance_sla`            | 工单 SLA 信号 | `warning` 超过预警时间、`timeout` 超过完成时间（主要由 SLA 规则引用，见 ListNotifyPolicy 的 slaRules）                                                                                                                                                                                                             |
| `process_task_sla`                | 任务 SLA 信号 | `answer_warning` 超过预警响应时间、`answer_timeout` 超过响应时间、`done_warning` 超过预警完成时间、`done_timeout` 超过完成时间                                                                                                                                                                                 |
| `duty_shift_change`               | 交接班信号    | （值班交接场景，变量为值班组系列）                                                                                                                                                                                                                                                                                     |
| `scheduler_ticket`                | 定时工单信号  | （定时工单场景，变量同工单）                                                                                                                                                                                                                                                                                           |
| `process_node` / `process_line` | 节点/线条信号 | ⚠️ 二期功能，**接口不加载，勿用**                                                                                                                                                                                                                                                                              |

> 建议：正式使用前先调 `ListNotifyTypeV2`（`list_notify_type_v2`）获取当前环境实际可选的 notifyType→triggerSignal/notifyRange/变量映射（名称会随全局文案配置动态变化）。

### 1.3 notifyRange 取值（通知谁）

| key               | 含义                                       | key                     | 含义             |
| ----------------- | ------------------------------------------ | ----------------------- | ---------------- |
| `all`           | 全员                                       | `cc_user`             | 待阅人员         |
| `creator`       | 工单创建人                                 | `cc_creator`          | 分阅人员         |
| `todo_user`     | 待办人                                     | `commenter`           | 评论员           |
| `oper_user`     | 经手人                                     | `extra_assignee`      | 副署（加签）人员 |
| `curr_operator` | 当前处理人                                 | `claimed_user`        | 待认领人员       |
| `supervisor`    | 督办人                                     | `permission_operator` | 权限涉及人员     |
| `custom_user`   | **自定义人员**（配 customUserGroup） |                         |                  |

值班专用：`hand_over_leader` 交班领导、`take_over_leader` 接班领导、`hand_over_group` 交班组人员、`take_over_group` 接班组人员。

> ⚠️ 限制：`notifyType=service_instance` 时 notifyRange **只允许 `all` 或 `permission_operator`**（`ListAllNotifyType` 源码逻辑）。

### 1.4 subject/content 变量语法

- 占位格式：**`${变量key}`**；
- 内置变量按 notifyType 提供（`ListAllNotifyType` 返回 `variables`）：

| notifyType                                  | 可用变量（key → 含义）                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `process_instance` / `scheduler_ticket` | `process_instance_id` 工单ID、`process_instance_name` 工单名称、`process_instance_number` 工单编号、`process_instance_creator` 提单人、`process_instance_ctime` 提单时间、`process_instance_status` 工单当前状态、`supervisor` 督办人、`action` 动作、`service_name` 服务名称、`service_category` 服务分类、`service_catalog` 服务类型 |
| `process_task`                            | 上述工单变量（除 ctime）+`process_instance_step_status` 任务当前状态、`process_instance_step_name` 任务节点名称、`process_instance_step_operator` 任务处理人、`process_instance_step_id` 任务Id                                                                                                                                                      |
| `service_instance`                        | `service_category`、`service_name`、`service_manager` 服务负责人、`action`                                                                                                                                                                                                                                                                           |
| `duty_shift_change`                       | `hand_over_leader`、`take_over_leader`、`hand_over_group`、`take_over_group`、`hand_over_user`、`take_over_user`、`shift_change_log_url`、`shift_change_time`、`duty_group_name`                                                                                                                                                           |

- **标准字段变量**：`ITSC_` 开头的标准字段也可作为变量（`${ITSC_TITLE}`），按控件类型自动提取可读值（实例选择/CMDB 级联按 showKey 渲染）；
- 未匹配到的变量保留原文（通知场景）；
- 时间类变量另有 `sup:` 前缀等高级用法（工单名称模板场景）。

### 1.5 接口一览

| 接口                                              | 方法 & 路径                                                         | 说明                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CreateNotifyPolicy`                            | POST`/api/itsc_trigger/v1/notify_policy`                          | body 即 §1.1；返回`instanceId`                                                                                                                                                                                                                                                                                                                                |
| `UpdateNotifyPolicy`                            | PUT`/api/itsc_trigger/v1/notify_policy/:instanceId`               | 全量覆盖（字段同创建）；改名查重                                                                                                                                                                                                                                                                                                                                 |
| `GetNotifyPolicyDetai`（GetNotifyPolicyDetail） | GET`/api/itsc_trigger/v1/notify_policy/:instanceId`               | 详情（含 subject/content/customUserGroup）                                                                                                                                                                                                                                                                                                                       |
| `ListNotifyPolicy`                              | POST`/api/itsc_trigger/v1/notify_policy/_search`（page/pageSize） | 列表。过滤参数：`name`（模糊）、`notifyType`、`triggerSignal`、`notifyRange`（模糊）、`notifyMode`（模糊）、`creator`（模糊）、`st`/`et`（ctime 范围）、`Q`（全字段模糊，支持中文枚举名匹配）。每项额外返回 `triggers[]`（引用该策略的触发器 id+name）和 `slaRules[]`（引用该策略的 SLA 规则）——**判断"策略被谁用了"靠这两个字段** |
| `DeleteNotifyPolicy`                            | DELETE`/api/itsc_trigger/v1/notify_policy/:instanceIds`           | **批量**，instanceIds 用 `;` 分隔。**内置策略（builtin=true）禁止删除**，混合删除时内置的跳过并在错误信息中列出                                                                                                                                                                                                                                    |
| `ListNotifyTypeV2`                              | GET`.../notify_type_v2`                                           | 获取通知类型/信号/文案映射（推荐先调）                                                                                                                                                                                                                                                                                                                           |
| `ListEnums`                                     | GET`.../enums?name=notifyMode`                                    | 查动态枚举；`name=notifyMode` 返回当前环境可用通知渠道                                                                                                                                                                                                                                                                                                         |

---

## 2. 触发器（trigger）

### 2.1 数据模型（Create/Update 请求体全字段）

```json
{
  "name": "工单完成后通知提单人并关单",
  "scope": "process_instance",
  "memo": "完成时通知",
  "status": "enabled",
  "event": "finish",
  "config": {
    "actionList": [
      {
        "name": "send_message",
        "args": {
          "notifyPolicyId": "5c2d520975c6b",
          "notifyInterval": "0",
          "notifyTimes": 1
        },
        "condition": {
          "logical": "and",
          "conditionList": [
            {
              "logical": "and",
              "ruleList": [
                {"variable": "process_instance_service_category", "operator": "==", "value": "request"},
                {"variable": "ITSC_PRIORITY", "operator": "==", "value": "high;critical"}
              ]
            }
          ]
        }
      },
      {
        "name": "update_process_instance_status",
        "args": {"status": "closed"},
        "condition": null
      }
    ]
  },
  "domainModelId": "领域模型ID"
}
```

#### 顶层字段

| 字段                    | 类型     | 必填 | 说明                                                                                                                                                                        |
| ----------------------- | -------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                | string   | 是   | 触发器名称，**全局唯一**（`CheckSameCmdbName` 查重）                                                                                                                |
| `scope`               | string   | 是   | 作用域 = 触发类型，取值同 §1.2 notifyType（`process_instance`/`process_task`/`service_instance`/`process_instance_sla`/`process_task_sla`；节点/线条二期未开放） |
| `event`               | string   | 是   | **监听信号，可多个，英文逗号分隔**（如 `"pass,reject"`；存储为字符串，匹配时 split）                                                                                |
| `status`              | string   | 是   | `enabled` 启用 / `disabled` 停用。**只有 enabled 才会被运行时匹配**                                                                                               |
| `memo`                | string   | 否   | 备注                                                                                                                                                                        |
| `config.actionList[]` | object[] | 是   | 动作列表（§2.2/§2.3/§2.4）。⚠️ pb 序列化后 Create 时**只持久化 ActionList**（condition 在 action 内）                                                            |
| `domainModelId`       | string   | 否   | 领域模型 ID。**注意：触发器已被服务/流程/节点关联后，不允许再改领域模型**（`checkUpdateTrigger` 拦截报"触发器已关联了其他资源，不能更改领域模型"）                  |

#### Update 特有行为

- `UpdateTrigger` 路径 `/api/flowable_service/v1/trigger/:triggerId`，**全量覆盖**（name/scope/memo/status/event/config 整体替换）；
- 改名时查重；
- 已有 serviceInstances/processDefinitions 关联时禁止改 domainModelId。

#### Delete 特有行为

- `RemoveTrigger`：triggerIds 用 `;` 分隔批量删；
- **有关联资源的触发器禁止删除**：被服务实例（serviceInstances）、流程定义（processDefinitions）、流程节点（processVersionTasks）引用的触发器会被跳过，报错列出名称。删除前先用 `ListTrigger` 看这三类关联字段。

### 2.2 actionList[].name 取值与 args 约定

| name                               | 含义                   | args（键→值，源码 parse 实证）                                                                                                                                                             |
| ---------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `send_message`                   | 发送通知消息           | `notifyPolicyId`（string，**通知策略 instanceId，必填**）、`notifyInterval`（string，重复通知间隔，如 `"0"` 表示不重复）、`notifyTimes`（number，通知次数，`1` = 只发一次） |
| `update_process_instance_status` | 修改工单状态           | `status`（string）：`cancel` 作废 / `suspend` 挂起 / `running` 重启（仅挂起态可改回）。**限制**：已作废/删除/完成的工单拒绝执行；不允许直接改为 `ended`（完成）             |
| `update_priority`                | 修改优先级             | `priority`（string）：优先级 value，候选见 `GetTriggerEnums` 的 `priorityEnums`                                                                                                       |
| `update_process_task_status`     | 修改任务状态           | `status`（string）：任务状态值，候选见 `GetTriggerEnums.processInstanceStepStatus`                                                                                                      |
| `update_service_status`          | 修改服务状态           | `status`（string）：`enabled` / `disabled`（仅 scope=service_instance 场景有意义）                                                                                                    |
| `exec_tool`                      | 执行工具               | `toolId`（string，工具库工具定义 ID；以触发器方式执行，入参为 orderInfo 系列，见《表单进阶》§3.2 节点脚本入参）                                                                          |
| `update_assignee`                | 修改处理人（内部动作） | `stepId`（string）、`userNameList`（string[]）、`groupNameList`（string[]）                                                                                                           |

### 2.3 action 条件（condition）—— 什么时候执行该动作

未设置 condition 或 conditionList 为空 → **无条件执行**。

```json
"condition": {
  "logical": "and",
  "conditionList": [
    {
      "logical": "or",
      "ruleList": [
        {"variable": "process_instance_status_change", "operator": "==", "value": "running"}
      ]
    }
  ]
}
```

**两层逻辑结构**（`evaluator.CheckConditions`）：

- 外层 `logical`：`and`（所有 conditionList 组都满足）/ `or`（任一满足）；
- 内层每组 `logical`：组内 ruleList 的 and/or；
- 每条 rule：`{variable, operator, value}`：
  - `operator`：govaluate 表达式运算符（`==`、`!=`、`>`、`>=`、`<`、`<=`、`in` 等）；值为字符串比较；
  - `value`：**分号 `;` 分隔多值 = 任一命中**（`"high;critical"` 等价于 IN）；
  - **变更类变量自带"值必须发生变化"约束**：`process_instance_status_change`、`process_instance_priority_change`、`process_task_status_change`、`service_status_change` 四个变量，不仅要求表达式匹配，还要求本次事件前后该值**真的变了**（changes 判定）；其他变量无此约束。

**可用变量**（`triggers.Variables`，`GetTriggerEnums.triggerConditionVariable` 可查）：

| variable                              | 含义                                                                          | 取值来源                                                                      |
| ------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `process_instance_name`             | 工单名称                                                                      | 文本                                                                          |
| `process_instance_creator`          | 工单创建人                                                                    | 用户名                                                                        |
| `process_instance_urgency`          | 工单紧急程度                                                                  | urgencyEnums 的 value                                                         |
| `process_instance_influence_scope`  | 工单影响范围                                                                  | influenceScopeEnums 的 value                                                  |
| `process_instance_priority`         | 工单优先级                                                                    | priorityEnums 的 value                                                        |
| `process_instance_service_category` | 服务类型                                                                      | serviceCategory 的 key（`GetTriggerEnums.serviceCategory`）                 |
| `process_instance_curr_assignee`    | 工单当前处理人                                                                | 用户名（多人`;` 连接）                                                      |
| `process_instance_status_change`    | 工单状态变更（变更为）                                                        | processInstanceStatus 枚举：`running`/`ended`/`closed` 等（带变更约束） |
| `process_instance_priority_change`  | 优先级变更为                                                                  | priorityEnums（带变更约束）                                                   |
| `process_task_status_change`        | 任务状态变化                                                                  | processInstanceStepStatus 枚举（带变更约束）                                  |
| `service_status_change`             | 服务状态变化                                                                  | `enabled`/`disabled`（带变更约束，服务场景）                              |
| `ITSC_*`                            | **任意标准字段**：当前步骤表单数据里 `ITSC_` 前缀的字段自动注入为变量 | 文本/单选取 value；多值/数值/布尔暂不支持（解析为空字符串）                   |

### 2.4 触发器的"绑定"方式（触发器如何作用于具体流程）

创建/更新接口本身**不带绑定参数**，绑定是反向的（资源引用触发器）：

| 绑定位置 | 方式                                                | 说明                         |
| -------- | --------------------------------------------------- | ---------------------------- |
| 服务实例 | 创建/编辑服务时传 triggerList                       | 该服务下所有工单都匹配       |
| 流程定义 | 流程定义 triggerIdList（`EditProcessDefinition`） | 该流程所有版本/工单都匹配    |
| 流程节点 | nodeSettings[].triggerIdList（保存流程版本）        | 只有走到该节点的任务信号匹配 |

`ListTrigger` 返回中的 `serviceInstances[]`、`processDefinitions[]`（含主版本 processVersionId）、`processVersionTasks[]`（userTaskId/userTaskName/processVersionId/processVersionName/processDefinitionName）即这三类绑定的反查结果。

### 2.5 接口一览

| 接口                         | 方法 & 路径                                                       | 说明                                                                                                                                                                                                                                                                                                |
| ---------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CreateTrigger`            | POST`/api/flowable_service/v1/trigger`                          | body 即 §2.1；返回完整 ITSCTrigger（含 instanceId）                                                                                                                                                                                                                                                |
| `UpdateTrigger`            | PUT`/api/flowable_service/v1/trigger/:triggerId`                | 全量覆盖；限制见 §2.1                                                                                                                                                                                                                                                                              |
| `GetTrigger`               | GET`/api/flowable_service/v1/trigger/:triggerId`                | 详情（含 config.actionList 全量）                                                                                                                                                                                                                                                                   |
| `ListTrigger`              | POST`/api/flowable_service/v1/trigger/_search`（page/pageSize） | 过滤：`scope`、`domainModelId`、`instanceId`（逗号分隔多个）、`Q`（name/memo/creator/ctime 模糊）。返回含三类绑定反查                                                                                                                                                                       |
| `RemoveTrigger`            | DELETE`/api/flowable_service/v1/trigger/:triggerIds`            | `;` 分隔批量；有关联的跳过（§2.1）                                                                                                                                                                                                                                                               |
| `GetTriggerEnums`（enums） | GET`.../trigger/enums`                                          | **强烈建议先调**：返回 triggerEvent（scope→信号树，含 SLA 两组）、triggerAction、triggerConditionVariable、processInstanceStatus/processInstanceStepStatus/serviceStatus/serviceCategory/workingTimeRange、influenceScope/urgency/priority 三组枚举及其 sourceDataConf。文案随全局配置动态化 |

---

## 3. 端到端示例

**需求**："服务器申请"流程，审批节点通过或驳回时，用企业微信通知提单人；工单完成时通知创建人并自动关单；仅服务类型为 request 时生效。

**Step 1 — 建通知策略 A（节点结果通知）**：

```json
POST /api/itsc_trigger/v1/notify_policy
{
  "name": "审批结果通知提单人",
  "notifyType": "process_task",
  "triggerSignal": "common",
  "notifyRange": ["creator"],
  "notifyMode": ["wechat_work"],
  "subject": "【${service_name}】工单 ${process_instance_number} 审批${action}",
  "content": "您的工单 ${process_instance_name} 在节点「${process_instance_step_name}」被 ${process_instance_step_operator} 处理（${action}），请查看。"
}
```

**Step 2 — 建通知策略 B（完成通知）**：

```json
{
  "name": "工单完成通知创建人",
  "notifyType": "process_instance",
  "triggerSignal": "finish",
  "notifyRange": ["creator"],
  "notifyMode": ["wechat_work"],
  "subject": "工单 ${process_instance_number} 已完成",
  "content": "您的工单 ${process_instance_name} 已完成。"
}
```

**Step 3 — 建触发器（引用两个策略 + 关单动作）**：

```json
POST /api/flowable_service/v1/trigger
{
  "name": "服务器申请-通知与自动关单",
  "scope": "process_instance",
  "status": "enabled",
  "event": "finish",
  "config": {
    "actionList": [
      {
        "name": "send_message",
        "args": {"notifyPolicyId": "<策略B-id>", "notifyInterval": "0", "notifyTimes": 1},
        "condition": {
          "logical": "and",
          "conditionList": [{
            "logical": "and",
            "ruleList": [{"variable": "process_instance_service_category", "operator": "==", "value": "request"}]
          }]
        }
      },
      {
        "name": "update_process_instance_status",
        "args": {"status": "closed"},
        "condition": null
      }
    ]
  }
}
```

**Step 4 — 绑定**：在流程定义 `EditProcessDefinition` 的 `triggerIdList` 加入该触发器 ID（作用于整个流程）；或绑定到服务实例。节点级触发器（如审批 pass/reject 通知，策略 A）则建 `scope=process_task`、`event=pass,reject` 的触发器，并在流程版本 nodeSettings 的对应节点 `triggerIdList` 中引用。

---

## 4. LLM 操作检查清单

1. **先查枚举再动手**：调 `GetTriggerEnums`（触发器枚举）和 `ListNotifyTypeV2`（通知类型）获取当前环境合法的 scope/event/信号/变量/优先级候选——文案与枚举随环境定制，不要硬编码中文名；
2. **通知策略先行**：触发器 `send_message` 动作必须有 `notifyPolicyId`——先建/查策略（`ListNotifyPolicy` 按 name 查），拿到 instanceId 再组触发器；
3. **event 是逗号分隔字符串**不是数组；scope 决定 event 合法值（§1.2）；
4. **条件变量带变更约束**：`xxx_change` 系列变量隐含"值必须变化"，做"当优先级被改为 high 时通知"才用它；做"优先级是 high 的工单完成时通知"用 `process_instance_priority`（无变更约束）；
5. **service_instance 类型通知范围受限**：只能 `all`/`permission_operator`；
6. **删除前查关联**：触发器看 ListTrigger 的 serviceInstances/processDefinitions/processVersionTasks；策略看 ListNotifyPolicy 的 triggers/slaRules；有关联先解绑（改服务/流程/节点配置）再删；
7. **内置对象不可删**：通知策略 builtin=true 禁止删除；
8. **领域模型一旦有关联不可改**；
9. **自动关单限制**：`update_process_instance_status` 不能置 `ended`；已作废/删除/完成的工单状态修改会被拒；
10. **全量覆盖**：Update 两个资源都是整体替换——先 Get 详情、改局部、整体回传。

---

## 5. 相关知识

- 通知策略的**另一消费方**：SLA 规则（`sla` 模块）按预警/超时信号引用通知策略，详见 SLA 协议管理相关流程。
- 流程定义 `EditProcessDefinition` 的 `triggerIdList`、流程版本 `nodeSettings[].triggerIdList` 绑定触发器，见 `modules/process_development/process-definition-v2-dev.md`。
- 节点 `exec_tool` 动作以触发器方式执行工具，入参为 orderInfo 系列，见 `modules/form_development/form-advanced.md` §3.2 节点脚本入参、`concepts/order-info.md`。
