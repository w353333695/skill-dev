---
name: order-info
kind: concept
tags:
- orderInfo
- 工单全景
- 脚本入参
- 跨模块
- 表单脚本
- 节点前后置脚本
- processInstance
- stepList
- formData
completeness: partial
gaps:
- orderInfo 顶层字段经 2026-07-28 真实工单样本核对（formData 结构已实测修正：list[{key,values}]）；个别边缘字段是否存在/为空仍待更多样本佐证
- orderNum 工单号格式（如 ITSC-YYYYMMDD-NNN）为源码摘录示例，本环境实际工单号格式未核对
- rTime 的 Go duration 格式在异常工单（如未开始计时）下的取值未核对
last_verified: '2026-07-28'
scope: ITSM 工单「全景 + 当前步骤上下文」运行时数据结构；表单生命周期脚本 / 流程节点前后置脚本 / 控件联动脚本的核心入参
related:
- modules/form_development/form-advanced.md   # 表单生命周期脚本（消费 orderInfo）
- modules/process_development/process-definition-v2-dev.md   # 流程节点前后置脚本（消费 orderInfo）
- modules/autoops_tool/tool-package-dev.md    # 脚本工具包（orderInfo 经工具入参注入）
note: 'ITSM 工单「全景 + 当前步骤上下文」运行时数据结构（JSON 字符串，脚本中需 json.loads）。由 flowable_service
  internal/process_instance/manager.go::GetOrderInfo 组装，语义 = 当前工单全量信息 + 当前步骤上下文。是三类脚本的核心入参：
  表单生命周期脚本（afterDataLoad/preSubmitCheck/onValueChange/componentLoad，非首节点）、流程节点前后置脚本（preScript/postScript）、
  控件联动脚本（经 scriptInputs 间接取 currentNode/history 值）。⚠️ 首节点发起时工单尚未创建，orderInfo 不存在（表单脚本需做存在性兼容）。
  来源：flowable_service 源码归纳，未以真实工单完整实例逐字段核对。'
---

# ITSM 工单全景 orderInfo（脚本入参）

> 跨模块全局概念：表单生命周期脚本、流程节点前后置脚本、控件联动脚本共用的「工单全景 + 当前步骤上下文」数据结构。
> 消费方见 `related`：`modules/form_development/form-advanced.md`（表单脚本）、`modules/process_development/process-definition-v2-dev.md`（节点脚本）。
>
> ⚠️ `orderInfo` 是 **JSON 字符串**，脚本中需 `json.loads(orderInfo)` 解析；其内 `formData`、各 `stepList[].formData` 也是字符串（双重 JSON）。
> ⚠️ **首节点发起时工单尚未创建，orderInfo 不存在**——表单脚本（onPageLoad/onValueChange/preSubmitCheck）入参此时只有 `loginUser/eventSource/args/formData`，脚本需做存在性兼容（`locals().get("orderInfo")`）。

## 一、顶层结构总览

```json
{
  "instanceId": "当前步骤(step)实例ID",
  "userTaskId": "当前节点ID(bpmnXML中的节点id)",
  "taskName": "当前节点名称",
  "processInstance": { "...工单对象..." },
  "process": { "...流程定义..." },
  "processVersion": { "...流程版本..." },
  "serviceInstance": { "...服务..." },
  "serviceRelevanceOrder": [ "...关联工单..." ],
  "userTaskList": [ "...节点视图..." ],
  "subTaskList": [ "...子流程节点..." ],
  "nodeList": [ "...节点+配置..." ],
  "stepList": [ "...全部步骤简报..." ],
  "finishedStepList": ["已完成步骤ID"],
  "userTaskInfo": [ "...节点操作人信息..." ],
  "stopAts": ["..."],
  "allowedOp": { "...当前用户可用操作..." },
  "stepOperationRecord": [ "...操作流水..." ],
  "userInfoMap": {"用户名": "显示名"},
  "formData": "当前步骤表单数据JSON字符串（解析后是 list[{key:容器key, values:[行]}]）",
  "variables": [{"name": "...", "value": "..."}],
  "status": "running",
  "creator": "...", "operator": "...",
  "ctime": "...", "otime": "...", "etime": "...", "mtime": "..."
}
```

## 二、当前步骤上下文字段（顶层，最常用）

| 字段                                          | 类型          | 说明                                                                                                                                                                                                                                                      |
| --------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `instanceId`                                | string        | **当前步骤（step）的实例 ID**，不是工单 ID（工单 ID 在 `processInstance.instanceId`）                                                                                                                                                             |
| `userTaskId`                                | string        | 当前节点 ID（bpmnXML 节点 id）                                                                                                                                                                                                                            |
| `taskName`                                  | string        | 当前节点名称                                                                                                                                                                                                                                              |
| `status`                                    | string        | 当前步骤状态：`ready`（待派单/待认领）/ `running`（处理中）/ `done`（已完成）/ `rejected`（已驳回）/ `closed`（已关闭）                                                                                                                         |
| `type`                                      | string        | 步骤类型                                                                                                                                                                                                                                                  |
| `creator` / `creatorShowName`             | string        | 步骤创建人用户名 / 显示名                                                                                                                                                                                                                                 |
| `operator` / `operatorShowName`           | string        | 当前操作人用户名 / 显示名                                                                                                                                                                                                                                 |
| `operatorLeader`                            | string        | 操作人的 leader                                                                                                                                                                                                                                           |
| `ctime` / `otime` / `etime` / `mtime` | string        | 创建 / 开始处理 / 完成 / 更新时间（格式`2006-01-02 15:04:05`）                                                                                                                                                                                          |
| `action`                                    | string        | 本步骤最近动作（`pass`/`reject` 等，前后置脚本场景与入参 action 一致）                                                                                                                                                                                |
| `memo`                                      | string        | 审批意见                                                                                                                                                                                                                                                  |
| `formData`                                  | string        | **当前步骤表单数据（JSON 字符串，需二次解析）**。解析后是 **list**：`[{key: 容器key, values: [行0, 行1, ...]}, ...]`（每行 = `{控件modelField: 值}`；table 容器 values 是多行，row 容器 values 通常 1 行）。⚠️ 选择类控件（SELECT/RADIO/CHECKBOX 等）的值是 **`{key,label,value}` 对象**，取 `.value` 而非裸字符串。节点前置脚本（CompleteProcessInstance 调用链）取的是**本次提交的新表单数据**；其他场景取库里已存的数据 |
| `variables`                                 | object[]      | 流程变量`[{name, value}]`（如分支条件里的 `pass`）                                                                                                                                                                                                    |
| `isSubStep`                                 | bool          | 是否子流程产生的步骤                                                                                                                                                                                                                                      |
| `subProcessInstanceId`                      | string        | 子流程工单实例 ID（子流程步骤时）                                                                                                                                                                                                                         |
| `isTimeout` / `timeoutTime`               | bool / string | 是否已超时 / 超时时间                                                                                                                                                                                                                                     |
| `isAck`                                     | bool          | 是否已确认（响应）                                                                                                                                                                                                                                        |
| `isExtraAssignee` / `extraAssigneeType`   | bool / string | 当前操作人是否额外加签人员 / 加签类型                                                                                                                                                                                                                     |
| `extraAssigneeList`                         | object[]      | 加签列表`[{extraAssignee, assignee, extraAssigneeType, isDone}]`                                                                                                                                                                                        |
| `unassigned`                                | bool          | 是否未分配处理人                                                                                                                                                                                                                                          |
| `consignors`                                | string[]      | 委托人列表（转派来源）                                                                                                                                                                                                                                    |
| `slaStatus` / `toolStatus`                | string        | SLA 状态 / 工具执行状态                                                                                                                                                                                                                                   |
| `rTime`                                     | string        | 剩余时间（如`"2h30m0s"`；挂起/作废为 `"--"`）                                                                                                                                                                                                         |
| `isDelete`                                  | bool          | 是否已删除                                                                                                                                                                                                                                                |
| `nrOfInstances`                             | int           | 会签实例总数（会签节点）                                                                                                                                                                                                                                  |
| `executionId` / `flowableTaskId`          | string        | flowable 执行 ID / 任务 ID（引擎层标识，一般用不到）                                                                                                                                                                                                      |

## 三、`processInstance`（工单对象，第二常用）

| 字段                                             | 说明                                                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `instanceId`                                   | **工单实例 ID**                                                                                              |
| `orderNum`                                     | **工单号**（如 `ITSM-20260727-001`，展示用）                                                               |
| `name`                                         | 工单标题                                                                                                           |
| `creator` / `ctime`                          | 提单人 / 提单时间                                                                                                  |
| `category`                                     | 分类                                                                                                               |
| `status`                                       | 工单状态：`running`（流转中）/ `ended`（已完成）/ `closed`（已关单）                                         |
| `isSuspended` / `isCancelled` / `isDelete` | 挂起 / 作废 / 删除标记（⚠️ 这三个是独立于 status 的布尔位，判断工单是否终止要同时看）                            |
| `isSubInstance`                                | 是否子工单                                                                                                         |
| `serviceId`                                    | 服务实例 ID                                                                                                        |
| `stepIdList`                                   | 全部步骤 ID 列表                                                                                                   |
| `currentAssigneeList`                          | 当前处理人列表                                                                                                     |
| `isTimeout` / `timeoutTime` / `rTime`      | 超时信息（rTime 计算规则：已结束用结束时间算；挂起/作废显示`--`）                                                |
| `handleWay`                                    | 处理方式（directly/send_directly/...）                                                                             |
| `influenceScope` / `urgency`                 | 影响范围 / 紧急度（优先级计算输入）                                                                                |
| `slaStatus`                                    | SLA 状态                                                                                                           |
| `source`                                       | 工单来源（手工/定时/告警等）                                                                                       |
| `visibleRange`                                 | 可见范围                                                                                                           |
| `isComment`                                    | 是否已评价                                                                                                         |
| `scheduledTicketId`                            | 定时工单 ID（定时发起的工单）                                                                                      |
| `versionRelevanceUserTaskInfo`                 | 节点-表单绑定快照`[{userTaskId, formVersionId, formDisplayMode, isDesensitization, fbFormId, fbFormInstanceId}]` |
| `suspendTimeLimitConf`                         | 挂起时限配置`[{userTaskId, initTimeLimit, restTimeLimit}]`（秒）                                                 |
| `supervisorList`                               | 督办人列表                                                                                                         |
| `flowableInstanceId`                           | flowable 引擎实例 ID                                                                                               |

## 四、流程 / 版本 / 服务信息

**`process`**：`{instanceId, name, category}` —— 流程定义。

**`processVersion`**：`{instanceId, versionName, bpmnXML, isJumpable}` —— 当前工单使用的流程版本。`bpmnXML` 是完整 XML 字符串，脚本需要解析图结构时可用；`isJumpable` 是否开启直通车。

**`serviceInstance`**（BriefService）：服务简报（instanceId、name、category 等）。

**`serviceRelevanceOrder[]`**：本工单关联的其他工单（父子/关联单）：

| 字段                                                                                        | 说明                            |
| ------------------------------------------------------------------------------------------- | ------------------------------- |
| `serviceInstanceId` / `serviceInstanceName` / `serviceInstanceCategory`               | 关联单的服务信息                |
| `processInstanceId` / `processInstanceNum` / `processInstanceName`                    | 关联单的工单 ID / 工单号 / 标题 |
| `processInstanceStatus` / `processInstanceIsSuspended` / `processInstanceIsCancelled` | 关联单状态                      |
| `relevanceType`                                                                           | 关联类型（父子/普通关联）       |

## 五、节点与步骤列表

**`nodeList[]`**（TaskNode = BPMNTaskNode + Setting）：流程**定义层**的节点全量信息（含节点配置 nodeSettings），结构同流程开发说明 taskInfo 的 node+setting。脚本需要"看后面还有哪些节点"、"某节点配置的处理人"时用它。

**`userTaskList[]` / `subTaskList[]`**：用户任务视图 / 子流程节点（deprecated 兼容字段，建议用 nodeList）。

**`stepList[]`**（BriefStepInfo）：**已产生的步骤**简报（与 nodeList 的区别：nodeList 是定义，stepList 是运行实例）：

| 字段                                                                    | 说明                                                                                                                                                                  |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `instanceId` / `userTaskId` / `taskName`                          | 步骤 ID / 节点 ID / 节点名                                                                                                            |
| `status` / `action` / `memo`                                      | 步骤状态 / 动作 / 审批意见                                                                                                            |
| `operator` / `ctime` / `otime` / `etime` / `mtime`            | 操作人与各时间                                                                                                                        |
| `formData`                                                            | **该步骤的表单数据**（JSON 字符串，解析后 list[{key,values}]，同顶层 formData 结构）。历史节点取数关键：遍历 stepList 找目标 userTaskId 且 status=done 的步骤                                 |
| `assignees`                                                           | 当前处理人`{role, assigneeList, assigneeGroupList}`（仅 running 且非子步骤时填充；role 取值 `assignee`/`distribute`/`claim`） |
| `fileInfo` / `consignors` / `toolStatus`                          | 附件信息 / 委托人 / 工具状态                                                                                                          |
| `isSubStep` / `subProcessInstanceId` / `subProcessInstanceStepId` | 子流程相关信息                                                                                                                        |

**`finishedStepList[]`**：已完成步骤 ID 列表（string）。

**`userTaskInfo[]`**（TaskOperatorInfo）：各节点操作人汇总信息。

**`stepOperationRecord[]`**（StepOperationRecord）：工单操作流水（谁、何时、什么动作、审批意见），审计场景用。

**`userInfoMap`**：`{用户名: 显示名}`——把 operator/creator 等用户名翻译成显示名，避免脚本再调用户接口。

**`allowedOp`**（AllowedOp）：**当前登录用户**在该步骤可用的操作集合（按钮级），脚本要做"当前人能不能操作 X"判断时用。

## 六、脚本开发典型用法（python）

```python
import json

order = json.loads(orderInfo)            # orderInfo 是字符串，先解析
ticket = order["processInstance"]
cur_step_form = json.loads(order["formData"]) if order.get("formData") else {}

# 1. 拿工单号、标题、提单人
order_num = ticket["orderNum"]
title = ticket["name"]
creator = ticket["creator"]              # 显示名: order["userInfoMap"].get(creator, creator)

# 2. 拿当前节点表单字段值（formData 是 list[{key,values}]，按容器 key 找）
reason = ""
for sec in cur_step_form:                          # cur_step_form 是 list
    if sec.get("key") == "section_apply":
        for row in sec.get("values", []):          # values 是行数组
            reason = row.get("apply_reason", reason)

# 3. 拿历史节点（如 Task_apply）填的表单
history_value = ""
for step in order["stepList"]:
    if step["userTaskId"] == "Task_apply" and step["status"] == "done" and step.get("formData"):
        fd = json.loads(step["formData"])          # fd 是 list[{key,values}]
        for sec in fd:
            if sec.get("key") == "section_apply":
                for row in sec.get("values", []):
                    history_value = row.get("server_count", history_value)

# 4. 判断当前节点/动作
cur_node = order["userTaskId"]
# action/scriptType 是节点前后置脚本的独立入参（见 process_development），不在 orderInfo 里

# 5. 看后续节点配置（定义层）
for node in order["nodeList"]:
    if node["id"] == "Task_impl":
        assignee_value = node.get("assigneeValue", "")

# 6. 用户名 → 显示名
show_name = order["userInfoMap"].get(operator, operator)
```

## 七、注意事项

1. **双重 JSON**：`orderInfo` 本身是字符串；其内 `formData`、各 `stepList[].formData` 也是字符串——用到哪层解析哪层；
2. **空值形态**：列表字段在 pb 序列化后空值是 `[]` 而非 `null`（`ToJSON` 用 jsonpb），但字符串字段空为 `""`；取值前判空；
3. **首节点无 orderInfo**：表单生命周期脚本（onPageLoad/onValueChange/preSubmitCheck）在首节点发起时入参只有 `loginUser/eventSource/args/formData`，脚本要做 `orderInfo` 存在性兼容（`locals().get("orderInfo")`）；
4. **判断工单终止态**：要同时看 `status` 和 `isSuspended/isCancelled/isDelete` 三个布尔位，单看 status 会漏；
5. **时间格式**：均为 `YYYY-MM-DD HH:mm:ss` 本地时间字符串；剩余时间 `rTime` 是 Go duration 格式（`2h30m0s`）或 `--`；
6. **formData 解析后是 list 不是 dict**：`formData` 解析后是 `[{key: 容器key, values: [行...]}, ...]`（按容器 key 找 `values` 数组），**不是** `{容器key: [行...]}`。table 容器 `values` 是多行（每行一组字段）；row 容器 `values` 通常 1 行。row 容器单控件也要 `values[0][modelField]`。
