---
name: process-definition-v2-dev
kind: module
module: process_development
tags:
- ITSM
- 流程开发
- flowable_service
- process_definition_version
- bpmnXML
- processSetting
- 接口契约
completeness: partial
gaps:
- '⚠️ 「首个 state=done 版本自动设主版本并部署」未在实测复现：定稿 done 后部署已发生（版本层 deploymentId/flowableDefinitionId），但 isMain 未自动置 true——「部署」与「设主」实测为两个动作。**显式设主内网 path 已找到并验证**：`PUT /api/flowable_service/v1/definition/{definitionId}/version/{versionId}`（8134，user/org 头，**注意是 /v1/definition/ 不是 /v2/**，设主会触发部署，超时设 120s）。设主后版本层 isMain=True，但**定义列表层 list_process_definition 的 isMain/deploymentId 仍有延迟/不同步**（平台特性，gap-034 原记"定义列表层空"即此）——以版本层 isMain/deploymentId 为准。'
- 处理人 userType 三件套在工单实际流转中的解析行为未验证（真调建库时 GET 已见 userType 正确解析如 loginUser / historyExecLeader / assigneeGroups，但未发起工单验证流转）
- dataVersion 固定写入 AssignListVariant 为源码摘录，其他 dataVersion 取值未核对
- 权限 action 名（processDefinitionCreateAction / processDefinitionUpdateAction / processDefinitionAccessAction）为源码归纳，本环境用 defaultUser + org 未遇权限拒绝但 action 名未单独核对
- cleanSetting 清洗规则的精确边界（nextAssignees / rejectNodes 指向不存在节点时的剔除逻辑）未实测（真调中 PUT 回传原样被接受，未构造脏数据验证清洗）
- set_form_version / set_process_version_stages / set_focus_field_v2 / set_main_version 等附带接口的精确契约未展开（仅指明分工）
last_verified: '2026-07-28'
scope: EasyOps ITSM 流程定义 V2 的开发态接口契约与请求体组织（新建 / 修改流程定义与版本）
related:
- modules/process_design/compliance-rules.md   # 流程「设计态」BPMN 静态合规规则（27 条 bpmnlint）
- registry/process                              # 流程「运行态」接口卡片（createProcessDefinition / saveProcessDefinitionVersion 等）
- modules/form_design/form-design-spec.md      # 节点绑定表单的设计态结构（formDefinition）
- concepts/order-info.md                        # 流程节点脚本入参 orderInfo（工单全景）
- modules/form_development/form-advanced.md     # 表单事件脚本（与流程节点脚本区分）
- modules/autoops_tool/tool-package-dev.md      # 脚本工具包（输出标记协议）
note: 'EasyOps ITSM 流程定义 V2 开发指南：flowable_service.process_definition_version 模块四个核心接口
  （EditProcessDefinition / GetProcessDefinitionVersionV2 / CreateProcessDefinitionVersionV2 / EditProcessDefinitionVersionV2）的契约、
  bpmnXML 详解（元素清单 / userTask 属性全表 / 处理人三件套 / 分支条件 / 子流程 / 图合法性约束）、processSetting 详解
  （lineSettings / nodeSettings 字段逐项 / allowedOps 取值 / candidateSettings / nextAssigneeSetting / scriptSettings / suspendSetting）、
  端到端示例与完整交付顺序、LLM 组织请求体检查清单。 切面定位：本知识描述流程「开发态 / 契约态」（接口字段深层语义 +
  请求体如何组装），与 modules/process_design（设计态 BPMN 静态合规规则）、registry/process（运行态接口卡片）三切面互补，
  同名对象不同切面，非重复。来源：flowable_service 组件 process_definition_version 模块源码整理；2026-07-27 已真调验证核心接口
  （Create 定义 / Create 版本 / Get 详情 / EditVersion 定稿）的 path / 字段 / 请求体 / taskInfo 视图全部命中；自动设主规则未复现、
  处理人工单流转 / 附带接口契约仍待验证（详见正文 §8）。'
---

# ITSM 流程开发说明（流程定义 V2）

> 面向 LLM 的开发指南。基于 `flowable_service` 组件 `process_definition_version` 模块源码整理。
> 覆盖四个核心接口：
>
> - `flowable_service.process_definition_version.edit_process_definition.EditProcessDefinition`（修改流程定义元信息）
> - `flowable_service.process_definition_version.get_process_definition_version_v2.GetProcessDefinitionVersionV2`（获取版本详情）
> - `flowable_service.process_definition_version.create_process_definition_version_v2.CreateProcessDefinitionVersionV2`（新建版本）
> - `flowable_service.process_definition_version.edit_process_definition_version.EditProcessDefinitionVersionV2`（修改未完成版本）
>
> 目标：根据客户需求组织 `bpmnXML` + `processSetting` 请求体，实现 ITSM 流程的新建与修改。

> 📌 **知识切面**：本文是流程「开发态 / 契约态」知识（接口字段语义 + 请求体组织）。流程「设计态」的 BPMN 静态合规规则见
> `modules/process_design/compliance-rules.md`（27 条 bpmnlint，配套 `check_compliance.py`）；「运行态」接口卡片见
> `registry/process`。三切面同名对象（ITSM 流程）、互补参照、非重复。核心接口已于 2026-07-27 真调验证（见 §8），自动设主规则、
> 处理人工单流转、附带接口契约仍待补充，使用时请结合实际环境验证。

---

## 1. 领域模型：流程的三层结构

| 层级                       | 概念                                             | 存储                 | 说明                                                                                                                                                                                           |
| -------------------------- | ------------------------------------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 流程定义 ProcessDefinition | 一个 ITSM 流程（如"服务器申请流程"）             | CMDB`ITSC_PROCESS` | 持有**名称、分类、备注、triggerIdList（定义级触发器）、useFormBuilder** 等元信息；**流程内容全部在版本上**。定义名称全局唯一（`CheckNameDuplicate` 校验，排除自身 definitionId） |
| 流程定义版本 DefVersion    | 定义的某个版本（versionName 如`1.0.0`）        | CMDB 版本模型        | 持有`bpmnXML`、`processSetting`、`state`（`unfinished` 草稿 / `done` 已完成）                                                                                                        |
| Flowable 部署              | 版本设为**主版本**时才部署到 flowable 引擎 | flowable             | 只有 done 且被设为主版本的版本才真正可发起工单                                                                                                                                                 |

**关键规则（源码实证）**：

1. 创建版本时 `versionName` 在同一 definition 下**不可重复**（重复直接报错 `版本号%s重复`）；
2. 第一个 `state=done` 的版本会**自动设为主版本并完成部署**（`setMainVersion` → `deployProcessAndModifyCMDB`）；之后的版本要用 `SetProcessDefinitionMainVersion` 接口手动设主；

   > ⚠️ **2026-07-27 实测偏差**：定稿 done 后**部署已发生**（版本层 `deploymentId` / `flowableDefinitionId` 已生成），但 **`isMain` 未自动置 true**。「自动设主」未复现——部署与设主实测为两个动作，需显式设主。
   >
   > ✅ **2026-07-28 设主 path 实测找到**：`PUT /api/flowable_service/v1/definition/{definitionId}/version/{versionId}`（8134 内网，user/org 头；**注意 `/v1/definition/` 非 `/v2/`**；设主会触发 flowable 部署，超时设 120s）。设主后版本层 `isMain=True` + `deploymentId`/`flowableDefinitionId` 生成。**定义列表层 `list_process_definition` 的 isMain/deploymentId 仍有延迟不同步**（平台特性，以版本层为准）。详见 §8。
3. `EditProcessDefinitionVersionV2` **只能改 `state=unfinished` 的版本**，已 done 的版本调用直接报错 `当前版本已完成，不可修改！`——要改已完成的流程，只能基于它新建版本（`baseVersionId` 克隆）；
4. 修改版本时若改了 `versionName`，同样做重复校验；
5. 权限：Create 需 `processDefinitionCreateAction`，Edit（定义和版本）需 `processDefinitionUpdateAction`，Get 需 `processDefinitionAccessAction`。

### 版本数据版本（dataVersion，内部字段，了解即可）

`AssignListVariant`（当前版本固定写入此值）表示：节点配置（nodeSettings）**独立存储**在 `processSetting` 中，而不是像老版本那样内嵌在 bpmnXML 的节点属性里。**V2 接口的新建/编辑都以 bpmnXML 描述图结构 + processSetting 描述节点配置为准**；读取时二者合并成 `taskInfo` 返回。

---

## 2. 接口契约

### 2.1 修改流程定义 `EditProcessDefinition`（定义级元信息）

```
PUT /api/flowable_service/v2/process_definition/:definitionId
Header: org, user, Content-Type: application/json
```

| 字段               | 类型     | 必填       | 说明                                                                                                                                                                                                                              |
| ------------------ | -------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `definitionId`   | string   | 是（路径） | 流程定义实例 ID                                                                                                                                                                                                                   |
| `name`           | string   | 是         | 流程定义名称。**全局唯一**：改名时服务端执行 `CheckNameDuplicate(name, definitionId)`（排除自身），与任何其他定义重名即报错。**注意：name 必填且全量覆盖，只想改分类/备注时也必须带上原名**，否则会被当成改名去查重 |
| `category`       | string   | 是         | 流程分类（全量覆盖；分类清单可用`list_process_definition_category` 查询）                                                                                                                                                       |
| `memo`           | string   | 否         | 备注（全量覆盖）                                                                                                                                                                                                                  |
| `triggerIdList`  | string[] | 否         | **定义级**触发器 ID 列表（全量覆盖）。与节点级 `nodeSettings[].triggerIdList` 的区别：定义级触发器作用于整个流程（如工单创建即触发），节点级作用于具体任务节点                                                            |
| `useFormBuilder` | bool     | 否         | 是否使用 form_builder 新版表单，默认`false`。影响后续 `set_form_version` 绑定表单时的表单类型（form_schema 老表单 vs form_builder 新表单）；切换后已绑定的表单关系不会自动迁移                                                |

返回：无 data（`types.Empty`），`code=0` 即成功。

**权限**：`processDefinitionUpdateAction`（与编辑版本相同）。

> ⚠️ 本接口**不碰任何版本内容**（bpmnXML/processSetting），也不触发部署；同理，版本接口也不会改定义的名称/分类。二者正交。
>
> ⚠️ 旧接口 `UpdateProcessDefinition` 已标记 **Deprecated**（它还顺带创建/更新版本，携带 `dVersionName`/`dVersionMemo`，行为混杂），新开发一律用 `EditProcessDefinition` + 版本接口分开操作。

### 2.2 新建版本 `CreateProcessDefinitionVersionV2`

```
POST /api/flowable_service/v2/process_definition/:definitionId
Header: org, user, Content-Type: application/json
```

| 字段               | 类型   | 必填       | 说明                                                                                                                                                                                                |
| ------------------ | ------ | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `definitionId`   | string | 是（路径） | 流程定义实例 ID。注意：**此接口只建版本**，流程定义本身需先用 `CreateProcessDefinitionV2` 建好                                                                                              |
| `baseVersionId`  | string | 否         | 基于某个已有版本新建：会**克隆**该版本的节点-表单绑定关系（`CloneFormRelation`）和基础设置（`CloneBaseVersionSetting`）。克隆按 userTaskId 匹配——bpmnXML 中节点 id 与基版本一致才能继承 |
| `bpmnXML`        | string | 是         | 流程图 XML，详见 §3                                                                                                                                                                                |
| `versionName`    | string | 是         | 版本号，同 definition 下唯一                                                                                                                                                                        |
| `memo`           | string | 否         | 版本说明                                                                                                                                                                                            |
| `state`          | string | 是         | `unfinished`（存草稿）/ `done`（保存完成）。**done 且是首个版本 → 自动设主版本并部署**                                                                                                   |
| `processSetting` | object | 是         | 流程+节点配置，详见 §4                                                                                                                                                                             |

返回：`{"definitionId": "...", "versionId": "..."}`

服务端处理流程：解析 bpmnXML → 校验 versionName 重复 → `cleanSetting` 清洗 nodeSettings 里的脏数据 → 创建版本记录 →（首个 done 版本）设主并部署 /（有 baseVersionId）克隆表单绑定 → 回写触发器引用关系（`UpdateTriggerRefs`，失败只记日志不影响主流程）。

### 2.3 编辑未完成版本 `EditProcessDefinitionVersionV2`

```
PUT /api/flowable_service/v2/process_definition/:definitionId/version/:versionId
```

| 字段               | 必填       | 说明                                                 |
| ------------------ | ---------- | ---------------------------------------------------- |
| `definitionId`   | 是（路径） |                                                      |
| `versionId`      | 是（路径） | 待修改的版本实例 ID，**必须 state=unfinished** |
| `versionName`    | 否         | 改名时做重复校验                                     |
| `memo`           | 否         |                                                      |
| `state`          | 是         | 本次保存后状态。`done` = 定稿（之后不可再改）      |
| `bpmnXML`        | 是         | 全量覆盖                                             |
| `processSetting` | 是         | 全量覆盖                                             |

> ⚠️ bpmnXML 与 processSetting 均为**全量替换**，不是增量 patch。正确做法：先 `GetProcessDefinitionVersionV2` 拿全量，改完整体回传。

### 2.4 获取版本详情 `GetProcessDefinitionVersionV2`

```
GET /api/flowable_service/v2/definition/:definitionId/version/:versionId
（versionId 传 "latest" 表示最新版本）
```

响应关键字段：

| 字段                                                                                                                                                              | 说明                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `definition`                                                                                                                                                    | 流程定义信息（instanceId、name 等）                                                                                                                                |
| `instanceId` / `versionName` / `memo` / `state` / `isMain` / `creator` / `ctime` / `deploymentId` / `deploymentTime` / `flowableDefinitionId` | 版本元信息                                                                                                                                                         |
| `bpmnXML`                                                                                                                                                       | 原始 XML 字符串                                                                                                                                                    |
| `taskInfo[]`                                                                                                                                                    | **节点列表 = bpmnXML 解析出的节点（node）+ processSetting 中对应配置（setting）+ 表单绑定（formInfo）+ 摘要配置（focusInfo）的合并视图**，按图的广度顺序排列 |
| `lineSettings[]`                                                                                                                                                | `processSetting.lineSettings`，线的配置                                                                                                                          |
| `triggerList[]`                                                                                                                                                 | 版本关联的触发器（instanceId、name）                                                                                                                               |
| `subDefNameMap`                                                                                                                                                 | 子流程 calledElement → 子流程定义名称映射                                                                                                                         |
| `userDisplayMap`                                                                                                                                                | 用户名 → 显示名                                                                                                                                                   |
| `stageSetting[]`                                                                                                                                                | 阶段配置`[{name, userTaskIds}]`（阶段配置用独立接口 `set_process_version_stages` 设置，不在 Create/Edit 请求体内）                                             |

`taskInfo[]` 每项结构：

```json
{
  "node":  { "id": "...", "name": "...", "...": "..." },
  "setting": { "userTaskId": "...", "...": "..." },
  "formInfo": {
    "relationId": "", "formId": "", "formVersionId": "",
    "formName": "", "isBind": false, "formDisplayMode": "",
    "isDesensitization": false, "fbForm": null
  },
  "focusInfo": { "userTaskId": "", "focusFieldsOrder": [], "highlightFields": [], "focusGroups": [] }
}
```

- `node`：BPMNTaskNode，见 §3.2；
- `setting`：NodeSetting，见 §4.2；
- `formInfo`：节点绑定的表单（由 `set_form_version` 接口绑定，不在版本请求体内）。

### 2.5 四个接口的分工（重要）

| 要改什么                                            | 用哪个接口                                                                     |
| --------------------------------------------------- | ------------------------------------------------------------------------------ |
| 定义的名称/分类/备注/定义级触发器/表单引擎开关      | `EditProcessDefinition`                                                      |
| 流程图、节点配置、版本号、版本状态                  | `CreateProcessDefinitionVersionV2` / `EditProcessDefinitionVersionV2`      |
| 读取版本全量内容（图 + 节点配置 + 表单绑定 + 摘要） | `GetProcessDefinitionVersionV2`                                              |
| 版本与表单的绑定、阶段、摘要字段                    | `set_form_version` / `set_process_version_stages` / `set_focus_field_v2` |
| 哪个版本生效（主版本）                              | `set_main_version`                                                           |

---

## 3. bpmnXML 详解

### 3.1 总体结构

服务端解析器（`internal/bpmn/xml/parser.go`）只认以下元素，**不解析 BPMN DI（图形坐标）**，画图坐标不影响逻辑：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <process id="process_xxx" name="流程名" isExecutable="true">

    <startEvent id="StartEvent_1"><outgoing>Flow_1</outgoing></startEvent>

    <userTask id="Task_apply" name="提交申请" ...>
      <incoming>Flow_1</incoming>
      <outgoing>Flow_2</outgoing>
    </userTask>

    <exclusiveGateway id="Gateway_1">
      <incoming>Flow_2</incoming><incoming>Flow_x</incoming>
      <outgoing>Flow_3</outgoing><outgoing>Flow_4</outgoing>
    </exclusiveGateway>

    <callActivity id="Task_sub" name="子流程" calledElement="子流程的flowableKey">
      <incoming>Flow_5</incoming><outgoing>Flow_6</outgoing>
    </callActivity>

    <endEvent id="Event_end"><incoming>Flow_9</incoming></endEvent>

    <sequenceFlow id="Flow_1" name="" sourceRef="StartEvent_1" targetRef="Task_apply"/>
    <sequenceFlow id="Flow_3" name="通过" sourceRef="Gateway_1" targetRef="Task_2">
      <conditionExpression>pass==1</conditionExpression>
    </sequenceFlow>
    ...
  </process>
</definitions>
```

支持的元素：`startEvent`、`endEvent`、`userTask`、`callActivity`（子流程）、`exclusiveGateway`（排他）、`inclusiveGateway`（包容）、`parallelGateway`（并行）、`sequenceFlow`。

### 3.2 `userTask` 属性全表（XML attribute → 节点字段）

| XML 属性                                            | 解析后字段                                              | 说明 / 取值                                                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                                              | `id`                                                  | 节点 ID，**nodeSettings、表单绑定、驳回配置全部以此 id 关联**。自定义建议 `Task_xxx` 风格，全图唯一                                                                                                                                                                                                                                                                                                 |
| `name`                                            | `name`                                                | 节点显示名                                                                                                                                                                                                                                                                                                                                                                                                  |
| `assignee` + `assigneeType` + `assigneeValue` | `userType` / `assigneeValue` / `assigneeListUser` | **处理人来源**，三者联动，规则见 §3.3                                                                                                                                                                                                                                                                                                                                                                |
| `assigneeList`                                    | （会签人员）                                            | 会签/串签时的候选人，分号分隔                                                                                                                                                                                                                                                                                                                                                                               |
| `assigneeGroup`                                   | `assigneeGroups`                                      | 用户组，分号分隔                                                                                                                                                                                                                                                                                                                                                                                            |
| `strategy`                                        | `skipStragety`                                        | 审批人为空/重复时的策略：`emptySkip`（为空跳过）、`emptyAssign`（为空转人工）、`sampleSkip`（与上节点相同审批人跳过）、`historySameSkip`                                                                                                                                                                                                                                                            |
| `handling`                                        | `handling`                                            | 处理方式：`directly`（直接处理）、`send_directly`（先派单后处理）、`claim_directly`（先认领后处理）、`send_claim_directly`（先派单后认领再处理）                                                                                                                                                                                                                                                    |
| `isFormDecision`                                  | `isFormDecision`                                      | 后续分支是否由表单值决定：`"1"` 是 / `"0"` 否（空按 `"0"`）。为 1 时线上的 conditionExpression 为表单表达式                                                                                                                                                                                                                                                                                           |
| `formExpressionName`                              | `formExpressionName`                                  | 表单决策变量名（如`pass`）                                                                                                                                                                                                                                                                                                                                                                                |
| `multiInstanceLoopCharacteristics` 子元素         | `approveType` / `countersignRate`                   | 多实例（会签/串签）：`<multiInstanceLoopCharacteristics isSequential="false"><completionCondition>${nrOfCompletedInstances/nrOfInstances >= 0.6}</completionCondition></multiInstanceLoopCharacteristics>`。存在即非单签：`isSequential="true"` → `sequence`（串签）；`false` → `countersign`（会签），`>=` 后的数字提取为通过率 `countersignRate`。**无此元素 = `single`（单签）** |

> 注意：老版本（dataVersion < SettingSplit）还把 `setAssignee/opsAllowed/script/triggerIdList/jumpableNodes/labelViews/subsequentConf/operationConf/suspendConf/suspendTimeLimit/memoLevel` 嵌在 XML 属性里。**V2 版本这些全部放进 `processSetting.nodeSettings`，XML 里不要写**（写了也会被忽略，因为 `GetTaskNodeTree` 只解析 §3.2 列出的属性）。

### 3.3 处理人来源（assignee 三件套 → userType）

`assignee` 属性是**标记串**，决定 `userType`；`assigneeType` 辅助区分；`assigneeValue` 存来源值：

| userType（解析结果）                          | XML 写法                                                  | assigneeValue 含义                                                                                                                              |
| --------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `loginUser` 提单人                          | `assignee="{{.loginUser}}"`                             | —                                                                                                                                              |
| `lastExec` 上一步执行人                     | `assignee="{{.lastExec}}"`                              | —                                                                                                                                              |
| `lastExecLeader` 上一步执行人的 leader      | `assignee="{{.lastExecLeader}}"`                        | —                                                                                                                                              |
| `historyExec` 历史节点处理人                | `assignee="{{.historyExec}}"`                           | 历史节点 ID                                                                                                                                     |
| `historyExecLeader` 历史节点处理人的 leader | `assignee="{{.historyExecLeader}}"`                     | 历史节点 ID                                                                                                                                     |
| `dutyGroup` 值班组（旧）                    | `assignee="{{.dutyGroup}}"`                             | 值班组 ID                                                                                                                                       |
| `dutyGroupV2` 值班组（新）                  | `assignee="{{.dutyGroupV2}}"`                           | 值班组 ID                                                                                                                                       |
| `formValue` 取表单字段值                    | `assignee="{{.formValue}}"`                             | 表单字段标识                                                                                                                                    |
| `userRule` 人员规则                         | `assigneeType="{{.userRule}}"`（assignee 任意非标记值） | 人员规则 JSON：`[{"userList":["u1"],"userGroupIdList":["g1"],"conditions":[{"variable":"uId.tableId.0.key","operator":"==","value":"123"}]}]` |
| `userTree` 用户树选择                       | `assigneeType="{{.userTree}}"`                          | 分号分隔的用户列表（同时填入 Assignees）                                                                                                        |
| `department` 部门                           | `assigneeType="{{.department}}"`                        | 部门 ID                                                                                                                                         |
| `specifyUser` 指定人员（默认兜底）          | `assignee="user1;user2"`（非标记串）                    | —（人员解析自 assignee 本身）；`assignee="${assignee}"` 或空时不填人（会签场景人员由 assigneeList 提供）                                     |

### 3.4 `sequenceFlow` 与分支条件

| 属性/子元素                            | 说明                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `id` / `sourceRef` / `targetRef` | 线 ID 与两端节点 ID                                                                               |
| `name`                               | 线名称（如"通过"/"驳回"），节点的`processOp.name` 优先取线名，无线名默认 `跳转至<下一节点名>` |
| `conditionExpression` 子元素         | 分支条件文本                                                                                      |
| `triggerIdList` 属性                 | 线上关联的触发器，分号分隔                                                                        |

**条件表达式两种形态**（`GetProcessVariable`）：

- **表单决策**（来源节点 `isFormDecision="1"`）：写任意表单表达式，整体作为 value（如 `pass>=1&&pass<=100`），name 取 `formExpressionName`；
- **非表单决策**：必须是 `变量==值` 形式（如 `pass==1`），解析为 `{name: "pass", value: "1"}`；不写条件默认 `{name: "pass", value: "0"}`。

**分支结构规则**（`GetUserTaskProcessOp`）：

- 节点直连下一节点：条件写在该线上；
- 节点 → 排他/包容网关 → 多分支：节点后的第一条线无条件，**条件写在网关出来的各条线上**；节点的 `processOp[]` 由网关后各线递归生成，每条对应一个 `targetTaskId`；
- 并行网关：节点 `isNextPar` 自动置 true；
- 到结束节点的线：生成 `{name: "跳转至结束", targetTaskId: <endEventId>}`。

### 3.5 `callActivity`（子流程节点）

| 属性                      | 说明                                                                                                                          |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `calledElement`         | **子流程的 flowable 定义 key**（即子流程主版本部署后的 definitionKey）。Get 详情的 `subDefNameMap` 用它映射子流程名称 |
| `calledElementTenantId` | 租户，一般不用                                                                                                                |

子流程节点在 taskInfo 中体现为 `node.subProcess = {"isSub": true, "subProcessId": "<calledElement>"}`，不参与表单绑定克隆。

### 3.6 图合法性约束（保存时 validate）

- 必须有 startEvent → 若干 userTask/callActivity → endEvent 的连通路径；
- incoming/outgoing 引用的线、sourceRef/targetRef 引用的节点必须存在；
- 节点 ID 全图唯一；
- 节点顺序：服务端按"图广度优先（含深度排序）"重排节点返回，XML 中元素书写顺序不要求严格，但建议按流转顺序书写。

> 🔗 **与设计态合规规则的关系**：本节的保存时 `validate` 是服务端运行时校验（图连通性 / 引用存在性）；
> `modules/process_design/compliance-rules.md` 的 27 条 bpmnlint 是设计期静态校验（网关成对 / 重名 / 隐式分裂等）。
> 二者层次不同、互补——设计期先过 bpmnlint，保存时再过服务端 validate。

---

## 4. processSetting 详解

```json
{
  "lineSettings": [ ... ],
  "nodeSettings": [ ... ]
}
```

### 4.1 `lineSettings[]`（线的配置）

Get 详情原样返回 `processSetting.lineSettings`。保存时服务端**不解析、不校验**，按序存储，随版本往返。线上需要配置（如线上触发器的补充设置）时按 Get 返回的原结构回传即可；无配置传 `[]`。

### 4.2 `nodeSettings[]`（节点配置，核心）

每个 userTask 对应一条（`userTaskId` 关联 bpmnXML 节点 id；**保存时服务端会清洗**：`nextAssignees` 中指向不存在节点的条目被剔除，`rejectNodes` 同理；nodeSettings 里引用不存在的节点配置在读取时被丢弃）。

完整结构：

```json
{
  "userTaskId": "Task_audit",

  "memoLevel": 1,
  "rejectNodes": ["Task_apply:驳回给申请人"],
  "allowedOps": ["assignee", "distribute", "claim", "withdraw", "cc", "SLAChange", "close", "add"],
  "labelViews": ["btnLabel:提交|statusLabel:审核中"],
  "triggerIdList": ["triggerInstanceId1", "triggerInstanceId2"],

  "candidateSettings": [
    {"operation": "distribute", "candidates": ["user1", "user2"], "dataSource": "organization"}
  ],

  "nextAssigneeSetting": {
    "enabled": true,
    "nextAssignees": [
      {"userTaskId": "Task_impl", "label": "实施人", "candidates": ["user3"], "dataSource": "user"}
    ]
  },

  "scriptSettings": {
    "preScript":  {"name": "前置脚本", "desc": "", "scriptIdList": ["toolDefId1"], "operations": ["done"], "isAsync": false},
    "postScript": {"name": "后置脚本", "desc": "", "scriptIdList": ["toolDefId2"], "operations": ["pass", "reject"], "isAsync": true}
  },

  "suspendSetting": {"isAutoActivate": true, "activateTime": 24}
}
```

#### 字段逐项说明

| 字段                    | 类型     | 说明                                                                                                                |
| ----------------------- | -------- | ------------------------------------------------------------------------------------------------------------------- |
| `userTaskId`          | string   | 关联的 bpmnXML 节点 id（必填锚点）                                                                                  |
| `memoLevel`           | int      | 审批意见展示级别：`-1` 不显示；`0` 显示但非必填；`1` 显示且必填                                               |
| `allowedOps`          | string[] | 节点允许的工单操作按钮，取值见下表                                                                                  |
| `rejectNodes`         | string[] | 本节点可驳回/跳回的目标节点，格式**`"<目标节点id>:<驳回线的显示名>"`**（源码按 `:` split 取节点 id 校验）。**驳回是运行时动态跳转，bpmnXML 不画反向驳回 sequenceFlow**——仅靠此字段声明跳转目标即可（见 §5 末「驳回机制实证」） |
| `labelViews`          | string[] | 操作按钮/状态文案自定义，分号分隔语义串                                                                             |
| `triggerIdList`       | string[] | 节点绑定的触发器实例 ID 列表；保存后服务端回写触发器引用关系                                                        |
| `candidateSettings[]` | object[] | 按操作限定候选人范围                                                                                                |
| `nextAssigneeSetting` | object   | "允许本节点人员设置后续节点处理人"                                                                                  |
| `scriptSettings`      | object   | 节点前置/后置脚本（调工具库的工具定义）                                                                             |
| `suspendSetting`      | object   | 挂起自动激活                                                                                                        |

**`allowedOps` 取值**（`operate_checker/operation.go`）：

| 值             | 操作                                 |
| -------------- | ------------------------------------ |
| `assignee`   | 审批处理                             |
| `distribute` | 派单                                 |
| `claim`      | 认领                                 |
| `withdraw`   | 撤回                                 |
| `cc`         | 抄送                                 |
| `SLAChange`  | SLA 变更（首节点默认拥有，无需配置） |
| `close`      | 关单                                 |
| `add`        | 添加额外处理人                       |

> 隐性规则：`done`（通过）和 `convert`（工单转换）**默认开启**，不在 allowedOps 中配置。

**`candidateSettings[]`**：限定某操作可选择的处理人范围。

| 字段           | 说明                                                                                                       |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `operation`  | 操作标识（同 allowedOps 取值，如`distribute`）                                                           |
| `candidates` | 候选人列表（用户/用户组/部门标识，空串会被清洗）                                                           |
| `dataSource` | 候选来源：`organization`（组织架构，**默认值**）、`tool`（工具脚本产出）、`department`（部门） |

**`nextAssigneeSetting`**：

| 字段                | 说明                                                                                                                                                                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`         | 是否允许本节点处理人指定后续节点处理人（对应老 XML 的`setAssignee`）                                                                                                                                                             |
| `nextAssignees[]` | 可指定哪些后续节点：`userTaskId`（必须真实存在于图中，否则被清洗）、`label`（显示名）、`candidates`（可选人范围）、`dataSource`（`user` 用户 / `group` 用户组 / `department` 部门；**读取时缺省补 `user`**） |

**`scriptSettings.preScript / postScript`（OperationScript）**：

| 字段                | 说明                                                                                                                              |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `name` / `desc` | 脚本名/描述                                                                                                                       |
| `scriptIdList`    | 工具定义 ID 列表（EasyOps 工具库中的 tool definitionId）。**为空 = 未配置脚本**（服务端 `len(scriptIdList)==0` 直接忽略） |
| `operations`      | **触发方式**（脚本在哪些工单操作时触发），取**原始 itemID**（⚠️ 非 allowedOps 的重映射值；`pass` 不是 `done`）。完整取值见下表                |
| `isAsync`         | **执行方式**：`true`=异步（**源码默认 `isAsync:!0`，推荐用默认**；不阻断主流程，工具异常忽略逐个触发）/ `false`=同步（线性执行，前一个失败后续不执行，**前置脚本失败会阻断当前节点动作**，慎用）。存 boolean 不存字符串 |

> 🔗 `scriptIdList` 引用的是 EasyOps 工具库的 tool definitionId，工具包结构见 `modules/autoops_tool/tool-package-dev.md`。
>
> 🔔 本节是节点脚本的**配置态**（流程图里怎么配 preScript/postScript）。脚本的**编写态**（入参 `orderInfo`/`action`/`scriptType`、执行链路、输出协议、与表单事件脚本的区别）见 §4.4「流程节点脚本编写」。

**`operations` 触发方式完整取值**（2026-07-28 从流程设计器源码 `process-design` 的 Checkbox.Group + `itemIdToI18nKeyMap` 实证）：

> ⚠️ **`scriptSettings.operations` 取原始 itemID，与 `allowedOps` 面板的取值不同**（`allowedOps` 把 pass→done/reject→jump 重映射；脚本 operations 不重映射）。**"通过时触发脚本"配 `["pass"]`，不是 `["done"]`**。

| operations 值 | 中文 | 说明 |
| --- | --- | --- |
| `pass` | 通过 | 工单审批通过 |
| `reject` | 退回/驳回 | 退回上一步 |
| `withdraw` | 撤回 | 撤回工单 |
| `claim` | 认领 | 认领任务 |
| `jump` | 直达 | 直达某节点 |
| `assignee` | 转派 | ⚠️ 原始 itemID 是 `assign`，存储时重映射为 `assignee`（配 `assignee` 不是 `assign`） |
| `distribute` | 派单 | 派单给处理人 |
| `cc` | 抄送 | 抄送 |
| `add` | 加签 | 加签 |
| `add_reject` | 加签退回 | 加签退回（仅节点开启加签时出现） |

> `operations` 是数组，可多选（脚本在勾选的任一操作触发时执行）。前端流程设计器：节点属性 → 前置/后置脚本 → 触发方式（多选）+ 执行方式（同步/异步单选）。

**`suspendSetting`**：

| 字段               | 说明                                                                              |
| ------------------ | --------------------------------------------------------------------------------- |
| `isAutoActivate` | 是否开启挂起时间限制（老 XML`suspendConf`）                                     |
| `activateTime`   | 挂起时限（**小时**；服务端运行时会 ×3600 转秒作为倒计时）。-1/0 表示不限制 |

### 4.3 不在 Create/Edit 请求体内的配置（需单独接口）

| 配置                   | 接口                                                                       |
| ---------------------- | -------------------------------------------------------------------------- |
| 节点绑定表单           | `set_form_version`（绑定用户任务对应表单）/ `set_process_version_form` |
| 阶段配置 stageSetting  | `set_process_version_stages`，结构 `[{name, userTaskIds[]}]`           |
| 摘要关注字段 focusInfo | `set_focus_field_v2` / `set_foucs_form_fields`                         |
| 设主版本               | `set_main_version`                                                       |
| 触发器定义本身         | `trigger` 模块接口；版本里只引用 triggerIdList                           |

### 4.4 流程节点脚本编写（编写态）

> 本节承接 §4.2 的 scriptSettings**配置态**，讲节点前后置脚本的**编写态**：脚本入参、执行链路、与表单事件脚本的区别。
> 节点脚本本质：流程引擎在节点 `done`/`reject` 时，按 `scriptSettings` 配置调工具库的工具，工具以沙箱方式执行，**无返回值要求**（节点脚本不回填表单，只做副作用：调外部接口/写 CMDB/发通知等）。

**节点前后置脚本入参**（`internal/process/script/manager.go::getInputs`）：

| 变量           | 内容                                |
| -------------- | ----------------------------------- |
| `orderInfo`  | 工单信息 JSON（**必有**）—— 详解见 `concepts/order-info.md`（工单全景 + 当前步骤上下文）              |
| `loginUser`  | 当前用户                            |
| `action`     | 触发动作（`pass`/`reject`/...） |
| `scriptType` | `pre`（前置）/ `rear`（后置）   |

> ⚠️ `action` / `scriptType` 是**独立入参**（不在 `orderInfo` 里），脚本里直接可用。`orderInfo` 是字符串需 `json.loads`（双重 JSON，见 order-info §七注意事项）。

**执行链路（源码实证）**：

1. **触发时机**：节点处理人操作（pass/reject）触发 `CompleteProcessInstance` 调用链，前置脚本（`scriptType=pre`）在动作前执行，后置脚本（`scriptType=rear`）在动作后执行；
2. **`operations` 信号匹配**：脚本是否触发看 `scriptSettings.operations` 是否含本次操作的**原始 itemID**（`pass`/`reject`/`withdraw`/...，见 §4.2 取值表）。⚠️ operations 用原始 itemID（`pass`），**不是** allowedOps 的重映射值（`done`）——配 `["pass"]` 才在"通过"时触发；配 `["done"]` 不会触发（`done` 不是合法的脚本 operations 值）；
3. **同步模式（`isAsync=false`）**：**线性执行**，多个 toolId 时前一个失败则后续不执行，且**失败会阻断当前节点动作**（前置脚本失败 = 节点不能 pass/reject）；
4. **异步模式（`isAsync=true`）**：**忽略异常逐个触发**，不阻断节点动作，工具执行结果不回灌流程；
5. **`scriptIdList` 为空 = 未配置**（服务端 `len(scriptIdList)==0` 直接忽略，不报错）；
6. **多工具输出**：节点脚本不消费工具返回值（区别于表单事件脚本），故多工具按顺序执行副作用即可。

**前置/后置 + 同步/异步 选型原则（重要）**：

> 脚本「位置」（pre 前置 / rear 后置）×「执行方式」（同步 / 异步）四个组合，按**副作用是否影响数据准确性 / 是否必须成功**选：

> **脚本按需配置**：节点前/后置脚本是可选的，**只在有自动化需求时才配**（非每节点必配）。两类需求：①执行自动化动作（回填 CMDB/调外部/通知）；②**动态指定下个节点处理人**（表单值需组合/匹配/查表算处理人；若表单值能直接当处理人，用 `assignee="{{.formValue}}"` 即可，无需脚本）。

| 场景 | 选型 | 理由 |
| --- | --- | --- |
| **影响数据准确性、必须成功才放行**（回写 CMDB 创建实例、扣库存、关键状态变更） | **前置 + 同步**（`preScript` + `isAsync=false`） | 前置在节点动作前执行；同步失败**阻断节点动作**（验收不能通过），保证数据一致性 |
| **动态指定下个节点处理人**（按本节点表单值组合/匹配/查表算出下个节点处理人） | **前置 + 同步**（`preScript` + `isAsync=false`） | 必须在节点 `pass` 前算出并设好下个节点处理人；同步失败阻断，避免工单流到下个节点却无人处理 |
| **不影响数据准确性、失败可容忍**（发通知、记日志、推送监控、清理缓存） | **后置 + 异步**（`postScript` + `isAsync=true`） | 后置在节点动作后执行（工单已流转）；异步忽略异常，不阻断主流程 |

> ⚠️ **避免「前置+异步」用于关键数据写入/处理人决策**——异步失败不阻断，工单照常流转但数据没写进去 / 处理人没设对，造成数据丢失或下个节点无人处理，且不易察觉。
>
> **本流程案例**：主机申请验收节点回写 CMDB HOST（影响数据准确性，必须成功），用**前置 + 同步**（`preScript` + `isAsync=false`）——脚本失败则验收不能通过，保证 HOST 实例一定被创建。

**与表单事件脚本的区别（重要，别混用）**：

| 维度 | 流程节点前后置脚本（本节） | 表单事件脚本（`modules/form_development/form-advanced.md` §3） |
| --- | --- | --- |
| 触发方 | 流程引擎（节点 done/reject） | 前端表单事件（afterDataLoad/preSubmitCheck/onValueChange） |
| 配置位置 | `nodeSettings.scriptSettings`（流程版本请求体） | 容器/控件 `options.remoteFunc`（表单 formDefinition） |
| 独立入参 | `action` / `scriptType` | `eventSource` / `args` / `formData` |
| 共享入参 | `orderInfo` / `loginUser`（见 `concepts/order-info.md`） | 同左（首节点无 orderInfo） |
| 返回约定 | **无要求**（只做副作用） | 按 eventName 严格约定（formData/formConfig/checkState 等） |
| 阻断性 | 同步模式失败可阻断节点动作 | 失败用 `raise` 字段抛错给前端 |

> 🔗 脚本工具包的输出标记协议（`##PARAMETER_.._RETEMARAP##`）见 `modules/autoops_tool/tool-package-dev.md`；
> 共享入参 `orderInfo` 的完整字段（工单全景/步骤上下文/stepList/nodeList 等）见 `concepts/order-info.md`。

### 4.5 脚本开发规范（2026-07-28 实战补）

**① 脚本迭代必须同步工具库（tool_update）**

> ⚠️ **本地改脚本 ≠ 工具库更新**。流程节点 `scriptIdList` 绑的是工具 ID，执行时取**工具库里的 content**（不是本地文件）。改了脚本必须同步：

```bash
# 内网 8181，PUT /tools/{toolId} 用新 content 生成新版本
PUT http://<host>:8181/tools/<toolId>
Body: {"name":"...","type":"python","content":"<新脚本>","sandboxRun":true,...}
```

工具库自动生成新版本，流程执行时取最新版本 content（`toolId` 不变）。详见 `autoops_tool` §4（`tool_create` 同 path，PUT 更新）。

**② 各类脚本的输入 / 输出契约**

> 脚本要**显式声明输入（tool 的 inputs）+ 按契约输出**，方便调试 + 表单脚本联动前端。两类脚本契约不同：

| 脚本类型 | 输入（流程引擎/前端注入） | 输出（按契约，前端/引擎消费） |
| --- | --- | --- |
| **流程节点前后置脚本**（本节） | `orderInfo`/`action`/`scriptType`/`loginUser`（全局变量注入） | **无强制输出**（只做副作用）；失败用 `raise` 字段抛可读错误（同步模式阻断节点动作） |
| **表单生命周期脚本**（`form_development/form-advanced.md` §3） | `orderInfo`/`eventSource`/`args`/`formData`/`loginUser` | **按事件类型严格约定**：afterDataLoad/onValueChange→`formData`(回填)+`formConfig`(改显隐)；preSubmitCheck→`checkState`/`submitCheck`；componentLoad→`result`。**输出是表单脚本联动前端的关键**——前端按输出 key 回填表单/改显隐/阻断提交 |

> 表单脚本的**输出契约必须精确**（key 名错前端不认）：`formData` 缺失直接报错"工具返回缺少关键字段"；`formConfig` 控制显隐（`-` 隐藏/`""` 显示）；`raise` 字段值直接抛给用户。详见 form-advanced §3.3。

> ⚠️ **工具 inputs 的 `type` 不要用 `json`**——工具库前端参数面板不支持 json 类型渲染会报错。需传 JSON 字符串的入参（如 `orderInfo`）用 **`string`** 类型，脚本内自行 `json.loads`。详见 `autoops_tool` §2.2.1 type 取值表。

**③ 脚本用 EASYOPS_ 内置变量（可迁移，禁硬编码）**

> 脚本里的 host/org 等**必须用平台内置变量**（`autoops_tool` 附录 C），不要硬编码 IP/org——保证脚本、ITSM 流程、ITSM 服务**迁移到其他环境依然可用**：

| 内置变量 | 含义 | 用法（沙箱注入为脚本变量，非环境变量，直接引用不要 getenv） |
| --- | --- | --- |
| `EASYOPS_LOCAL_IP` | 当前主机 IP（沙箱执行时 = 系统主机 IP） | 脚本调平台 API 时的 host（替代硬编码 `172.30.5.20`） |
| `EASYOPS_ORG` | 机构 ID | 请求头 `org`（替代硬编码 `5910`） |
| `EASYOPS_USER` | 登录用户 | 请求头 `user` |
| `EASYOPS_CMDB_HOST` / `EASYOPS_DEPLOY_HOST` 等 | 各服务主机 IP | 调对应服务时用 |

> ⚠️ 这些是**平台注入的脚本变量**（非环境变量），python 直接 `EASYOPS_LOCAL_IP` 引用，**不要** `os.environ.get`（取不到）。shell 用 `$EASYOPS_LOCAL_IP`。
>
> **反例**（不可迁移）：`HOST = "172.30.5.20"; ORG = "5910"` —— 换环境必改脚本。
> **正例**（可迁移）：`host = EASYOPS_LOCAL_IP; org = EASYOPS_ORG` —— 脚本随流程/服务迁移零改动。

**④ CMDB 回填类脚本：按模型约束写 + failed_count 判定**

> 脚本往 CMDB 写实例（importInstance/updateInstance）时，**必须先 GET 模型定义核对字段约束**（值类型/枚举候选/必填/正则），按约束构造实例数据；**写入成功判定看 `failed_count` 不能只看 `code`**（code=0 也可能部分行失败）。
>
> 完整写入规范（约束核对表、importInstance 构造、failed_count 判定代码）见 **`concepts/cmdb-instance.md`**（跨模块单一真相源）。本节只讲流程脚本场景要点：
> - 前置+同步脚本：`failed_count>0` 必须 `raise`（阻塞节点动作），否则工单流转但数据没写对（静默丢数据）；
> - 枚举值/值类型**不要臆测**——先 `GET /object/{objectId}` 查 `attrList`（本流程教训：_environment 臆测 test/prod 失败，实测候选 `['无','开发','测试','预发布','生产','灾备']`；status 实测 `运营中` 非"运行中"）。

---

## 5. 端到端示例

### 5.1 需求

"服务器申请流程"：申请（提单人）→ 审批（指定主管 user_mgr，可驳回给申请人，审批意见必填，允许派单）→ 实施（值班组，审批后结束）。审批节点挂起 24 小时自动激活。

> ⚠️ **驳回不画 bpmn 连线**：示例虽写"可驳回给申请人"，但驳回是**运行时动态跳转**，靠下方 §5.3 nodeSettings 的 `rejectNodes: ["Task_apply:驳回修改"]` 配置，**bpmnXML 里不画反向驳回 sequenceFlow**（§5.2 的 bpmnXML 只有 5 条前进连线）。详见 §4.2 `rejectNodes` 与本节末「驳回机制实证」。

### 5.2 bpmnXML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <process id="process_server_apply" name="服务器申请流程" isExecutable="true">
    <startEvent id="StartEvent_1"><outgoing>Flow_1</outgoing></startEvent>
    <userTask id="Task_apply" name="提交申请"
              assignee="{{.loginUser}}" strategy="emptyAssign" handling="directly">
      <incoming>Flow_1</incoming><outgoing>Flow_2</outgoing>
    </userTask>
    <userTask id="Task_audit" name="主管审批"
              assignee="user_mgr" strategy="emptyAssign" handling="directly">
      <incoming>Flow_2</incoming><outgoing>Flow_3</outgoing>
    </userTask>
    <userTask id="Task_impl" name="资源实施"
              assignee="{{.dutyGroupV2}}" assigneeValue="dutyGroupId_001" strategy="emptyAssign" handling="directly">
      <incoming>Flow_3</incoming><outgoing>Flow_5</outgoing>
    </userTask>
    <endEvent id="Event_end"><incoming>Flow_5</incoming></endEvent>
    <sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_apply"/>
    <sequenceFlow id="Flow_2" name="提交" sourceRef="Task_apply" targetRef="Task_audit"/>
    <sequenceFlow id="Flow_3" name="审批通过" sourceRef="Task_audit" targetRef="Task_impl"/>
    <sequenceFlow id="Flow_5" name="完成" sourceRef="Task_impl" targetRef="Event_end"/>
    <!-- 注意：驳回不画 sequenceFlow，靠 nodeSettings.rejectNodes 配置（见 §5.3） -->
  </process>
</definitions>
```

### 5.3 请求体（CreateProcessDefinitionVersionV2）

```json
{
  "bpmnXML": "<上方XML整体转义为字符串>",
  "versionName": "1.0.0",
  "memo": "首次发布",
  "state": "done",
  "processSetting": {
    "lineSettings": [],
    "nodeSettings": [
      {
        "userTaskId": "Task_apply",
        "memoLevel": 0,
        "allowedOps": ["assignee", "withdraw"],
        "rejectNodes": [],
        "nextAssigneeSetting": {"enabled": false, "nextAssignees": []},
        "scriptSettings": {"preScript": {}, "postScript": {}},
        "suspendSetting": {"isAutoActivate": false, "activateTime": -1}
      },
      {
        "userTaskId": "Task_audit",
        "memoLevel": 1,
        "allowedOps": ["assignee", "distribute", "cc"],
        "rejectNodes": ["Task_apply:驳回修改"],
        "candidateSettings": [
          {"operation": "distribute", "candidates": ["user_mgr", "user_mgr2"], "dataSource": "organization"}
        ],
        "nextAssigneeSetting": {
          "enabled": true,
          "nextAssignees": [
            {"userTaskId": "Task_impl", "label": "实施人", "candidates": [], "dataSource": "user"}
          ]
        },
        "scriptSettings": {"preScript": {}, "postScript": {}},
        "suspendSetting": {"isAutoActivate": true, "activateTime": 24}
      },
      {
        "userTaskId": "Task_impl",
        "memoLevel": 0,
        "allowedOps": ["assignee", "close"],
        "rejectNodes": [],
        "nextAssigneeSetting": {"enabled": false, "nextAssignees": []},
        "scriptSettings": {"preScript": {}, "postScript": {}},
        "suspendSetting": {"isAutoActivate": false, "activateTime": -1}
      }
    ]
  }
}
```

---

### 5.4 驳回机制实证（驳回靠 rejectNodes，不画 bpmn 连线）

> 本节是对 §5.2/§5.3「驳回」写法的**纠偏与铁证**。早期版本的 §5.2 曾画了一条 `<sequenceFlow Flow_4 驳回 Task_audit→Task_apply>`，**与真实环境不符，已删除**。

**EasyOps 驳回 = 运行时动态跳转**，处理人点「驳回」按钮后，流程引擎按节点 `nodeSettings.rejectNodes` 声明的目标节点动态回跳，**不需要在 bpmnXML 画反向驳回连线**。画了反而：(1) 让流程图杂乱；(2) 与设计器导出的真实 BPMN 不一致。

**铁证：host-apply 主机申请流程**（真实部署 + 已验收，导出包 `cmdb_service_instance.json` 的 `_ITSC_PROCESS_VERSION`）：

- **bpmnXML 只有前进连线，0 条驳回连线**（5 条全是前进：StartEvent→apply、网关→实施×2、实施→汇聚×2）：
  ```
  Flow_1: StartEvent_1 -> Task_apply
  Flow_6: Gateway_split -> Task_impl_hw
  Flow_7: Gateway_split -> Task_impl_net
  Flow_8: Task_impl_hw  -> Gateway_join
  Flow_9: Task_impl_net -> Gateway_join
  ```
- **驳回全靠 rejectNodes 配置**（3 个审批节点都驳回到 Task_apply）：
  ```
  Task_tech_review:   rejectNodes = ["Task_apply:驳回给申请人"]
  Task_direct_leader: rejectNodes = ["Task_apply:驳回给申请人"]
  Task_ops_leader:    rejectNodes = ["Task_apply:驳回给申请人"]
  ```
- `sample.bpmn`（平台流程设计器导出的标准样例）同理：所有 sequenceFlow 都是前进方向，无反向驳回连线。

**结论**：建流程时驳回**只配 `rejectNodes`**，bpmnXML 只画前进流向的 sequenceFlow。`rejectNodes` 的目标节点 id 必须在 bpmn 图里真实存在（如 host-apply 的 `Task_apply`），否则被 `cleanSetting` 清洗。

---

## 6. 完整交付顺序

**新建流程**：

1. `CreateProcessDefinitionV2` 建定义（名称/分类，后续可用 `EditProcessDefinition` 修改）；
2. `CreateProcessDefinitionVersionV2` 存版本（可先 `unfinished` 草稿）；
3. `set_form_version` 绑定各节点表单（按需：`set_process_version_stages` 阶段、`set_focus_field_v2` 摘要）；
4. `EditProcessDefinitionVersionV2` 把 state 置 `done`；
5. （非首版本）`set_main_version` 设主部署。

**修改已有流程**：

- 改定义元信息（名称/分类/备注/定义级触发器/表单引擎）→ `EditProcessDefinition`；
- 改流程内容 → 基于当前版本 `CreateProcessDefinitionVersionV2`（带 `baseVersionId` 克隆表单绑定）迭代新版本，done 后 `set_main_version` 生效；若目标版本还是 `unfinished` 草稿，直接 `EditProcessDefinitionVersionV2` 全量覆盖。

---

## 7. LLM 组织请求体的检查清单

接到流程需求时按序确认：

1. **定义元信息**：流程名称（全局唯一，先用 `list_process_definition` 查重）、分类（存在于平台分类清单）、定义级触发器（区分于节点级 triggerIdList）、`useFormBuilder` 与现场表单体系是否匹配 → 这些走 `CreateProcessDefinitionV2` / `EditProcessDefinition`，不要塞进版本请求体；
2. **节点拓扑**：每个节点 id/name/类型（userTask 还是 callActivity）、连线走向、网关类型 → 生成 bpmnXML；
3. **每个节点处理人**：映射到 §3.3 的 userType 三件套（提单人/上一步执行人/指定人/值班组/表单字段/人员规则…）；
4. **审批形态**：单签（默认）/ 会签（比例）/ 串签 → 决定是否写 `multiInstanceLoopCharacteristics` 与 `assigneeList`；
5. **分支条件**：哪些线有条件、是表单决策还是固定值 → conditionExpression；
6. **节点行为**：审批意见级别 memoLevel、允许操作 allowedOps、可驳回节点 rejectNodes（注意格式 `节点id:线名`，**目标节点 id 必须在 bpmn 图里真实存在（不是画驳回连线——驳回靠此字段动态跳转，见 §5.4）**）、是否允许指定后续处理人、前后置脚本（scriptIdList 必须是工具库真实 tool definitionId）、挂起时限；
7. **状态策略**：先 `unfinished` 存草稿迭代，定稿 `done`；done 后只能 baseVersionId 克隆新版本；
8. **附带动作**：表单绑定、阶段、摘要字段走独立接口，不在版本请求体内；
9. **常见错误**：versionName 重复；编辑已 done 版本；rejectNodes/nextAssignees 引用不存在的节点 id（会被静默清洗，表现为"配置没生效"）；bpmnXML 中老属性（opsAllowed 等）写了不生效——V2 必须放 nodeSettings；`EditProcessDefinition` 漏传 name 导致误查重。

---

## 8. 真调验证记录（2026-07-27）

环境：`172.30.5.20` 内网 `8134`（`easyops_internal`，user/org 头，免 cookie）。对象：主机申请流程（7 userTask + 2 parallelGateway）。

### 8.1 已验证（正向命中）

| 接口 | path（实测） | 验证点 | 结果 |
| --- | --- | --- | --- |
| 建定义 | `POST /api/flowable_service/v2/process_definition` | body `{name,category,memo,useFormBuilder}` → 返回 `data.instanceId` | ✓ code=0 |
| 建版本 | `POST /api/flowable_service/v2/process_definition/:definitionId` | body `{bpmnXML, versionName, memo, state, processSetting}` → 返回 `data.versionId` | ✓ code=0 |
| 取版本 | `GET /api/flowable_service/v2/definition/:definitionId/version/:versionId`（注意是 `definition` 非 `process_definition`） | 返回 `taskInfo[]` 合并视图（node+setting+formInfo+focusInfo）+ `lineSettings[]` + `bpmnXML` | ✓ 7 节点全出 |
| 定稿 | `PUT /api/flowable_service/v2/process_definition/:definitionId/version/:versionId` | 全量覆盖 `{versionName,memo,state:"done",bpmnXML,processSetting}`（nodeSettings 从 `taskInfo[].setting` 重构） | ✓ code=0 |

**附带佐证**：
- **请求体字段名**（`bpmnXML` / `processSetting` / `versionName` / `state` / `lineSettings` / `nodeSettings`）全部被服务端正确接受，无字段名偏差。
- **bpmnXML 格式**：`bpmn2:` 前缀 + `flowable:` 命名空间属性（assignee/assigneeValue/assigneeType/assigneeGroup/strategy/handling/isFormDecision…）被正常解析——GET 返回的 `taskInfo[].node.userType` 正确反推出 `loginUser` / `historyExecLeader` / `historyExec` / `assigneeGroups` 等。
- **全量覆盖语义**：定稿时用 GET 返回的原始 `bpmnXML` + 重构的 `nodeSettings` 整体 PUT，服务端原样接受（§2.3「拿什么回什么」成立）。
- **`flowable_service` 内网端口 = 8134**（与 `concepts/api-calling/api-calling.md` 一致），`easyops_internal` 模式 `user`/`org` 头鉴权有效。

### 8.2 与文档预期不符（反向发现，已记入 frontmatter gaps）

**「首个 done 版本自动设主版本」未复现**：定稿 `state=done` 后状态分裂——

| 视角 | state | isMain | deploymentId | flowableDefinitionId |
| --- | --- | --- | --- | --- |
| 版本详情（GET version） | done | **False** | `ITSC65794d59d5e4c`（有值） | `ITSC65794d59d5e4c`（有值） |
| 定义列表（list definition） | done | **False** | （空） | （空） |

- **部署确实发生了**（版本层有 `deploymentId` + `flowableDefinitionId`），但 **`isMain` 未自动置 true**，定义列表层不认这次部署。
- 推断：「部署」与「设主」是两个独立动作，文档 §1 规则 2 所述的 `setMainVersion → deployProcessAndModifyCMDB` 自动链路在实测环境未触发。**要让版本在 ITSM 层生效为主版本，疑似需显式调 `set_main_version`**（未实测）。
- 已在 §1 规则 2 处加 ⚠️ 注，frontmatter gaps 列首条。

### 8.3 仍待验证（保留在 frontmatter gaps）

- **处理人 userType 在工单流转中的实际解析**：建库时 GET 已见 `userType` 正确解析，但未**发起工单**验证占位人（`tech_reviewer` / `hardware_group` 等）在流转时是否真正生效 / 报错。
- **cleanSetting 清洗边界**：未构造脏 `nextAssignees`/`rejectNodes`（指向不存在节点）验证是否被清洗。
- **权限 action 名**（`processDefinitionCreateAction` 等）：实测用 `defaultUser + org=5910` 未遇权限拒绝，但 action 名本身未单独核对。
- **dataVersion 取值**：仅见当前固定 `AssignListVariant`，其他取值未核对。
- **附带接口契约**：`set_form_version` / `set_process_version_stages` / `set_focus_field_v2` / `set_main_version` / `EditProcessDefinition`（定义元信息修改）均未单独验证。

### 8.4 复用产物

- 调用脚本：`tmp/host-apply-process/create_via_api.py`（独立自包含，V2 接口直调，`--probe` / `--create` / `--finalize` 三模式）。
- 流程制品：`tmp/host-apply-process/host-apply.bpmn` + `create-version-request.json`（已通过 `check_compliance.py` + `check_layout.py` 静态校验）。
