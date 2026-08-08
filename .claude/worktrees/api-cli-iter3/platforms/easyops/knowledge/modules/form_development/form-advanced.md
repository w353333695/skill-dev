---
name: form-advanced
kind: module
module: form_development
tags:
- ITSM
- 表单进阶
- 数据继承
- 条件显示
- displayCondition
- 表单生命周期脚本
- remoteFunc
- afterDataLoad
- preSubmitCheck
- formConfig
completeness: partial
gaps:
- 未在真实 EasyOps 环境端到端真调验证（表单生命周期脚本 / 数据继承运行为 flowable_service 源码归纳，非真机实测）
- displayCondition 表达式语法（不支持跨字段 OR、AND 规则、字段优先级）为产品手册规范归纳，未构造多种表达式实测求值
- formConfig 动态改写的「与原表单定义同构的裁剪数组」规则为产品手册原文要点，未以真实脚本输出验证前端合并行为
- CMDB 变更容器的「删除标记 / 只读继承」运行时行为为源码（mergeData / ExecuteScriptTools）归纳，未构造变更实例实测
- 父子工单数据传递（service_subinst_deliver_config）与工单转换（update_service_convertible_config）仅指明分工，精确契约未展开
- 跨表单容器继承（实施表单容器 default 指向另一张申请表单的容器）+「继承容器+额外控件」的运行时数据回填行为为源码语义推断，未发起工单端到端实测（主机申请流程已配此结构，待真实工单验证继承是否生效 + 新增列数据共存）
last_verified: ''
scope: EasyOps ITSM 表单「进阶 / 运行时行为」：数据继承三种机制 / 条件显示深化 / 表单生命周期脚本 / 动态 formConfig
related:
- modules/form_development/form-schema-v2-dev.md   # 表单开发态接口契约（formDefinition 字段全表）
- modules/form_design/form-design-spec.md          # 表单设计态结构规则（displayCondition/DATAINHERIT/remoteFunc 简版）
- concepts/order-info.md                            # 表单脚本入参 orderInfo（工单全景）
- modules/process_development/process-definition-v2-dev.md  # 流程节点前后置脚本（与表单事件脚本区分）
- modules/autoops_tool/tool-package-dev.md         # 脚本工具包（输出标记协议）
note: 'EasyOps ITSM 表单「进阶 / 运行时行为」知识：数据继承三种机制（容器继承 / 父子工单 / 工单转换）、条件显示 displayCondition
  深化（两种配置位置 / 表达式语法 / 服务端行为）、表单生命周期脚本（事件类型 / 表单事件脚本入参 / 返回约定 / formConfig 动态改写 /
  执行链路）、速查配置落点。切面定位：本知识描述表单「运行时行为 / 脚本」，与 form-schema-v2-dev（开发态接口契约）、form_design
  （设计态结构规则）三切面互补。⚠️ 流程节点前后置脚本（nodeSettings.scriptSettings）的「编写态」归 process_development
  （本文件仅区分边界 + 交叉引用）；脚本共享入参 orderInfo 归 concepts/order-info。来源：flowable_service 源码（process_script /
  internal/form / internal/tool）+ 产品手册整理，未真机端到端核对。'
---

# ITSM 表单进阶：数据继承、条件显示、表单生命周期脚本

> 面向 LLM 的补充指南。基于 `flowable_service` 源码（`process_script`、`internal/form`、`internal/tool`）与产品手册整理。
> 阅读前请先掌握 `form-schema-v2-dev.md` 的 formDefinition 基础结构。

> 📌 **知识切面**：本文是表单「进阶 / 运行时行为」知识。
> - 表单**接口契约 / 请求体组织** → `form-schema-v2-dev.md`
> - 表单**设计态结构合规** → `modules/form_design/form-design-spec.md`
> - 表单**运行时行为 / 脚本**（数据继承深化、条件显示深化、生命周期脚本）→ 本文
>
> ⚠️ **脚本边界**：本文讲**表单事件脚本**（afterDataLoad / preSubmitCheck / onValueChange / componentLoad）。**流程节点前后置脚本**
> （nodeSettings.scriptSettings，节点 done/reject 时触发）是另一套，其「编写态」归 `modules/process_development/process-definition-v2-dev.md`，
> 「配置态」见同文件 §4.2 scriptSettings。两类脚本共享入参 `orderInfo`（见 `concepts/order-info.md`）。

---

## 1. 表单数据继承（三种机制，别混淆）

"继承"在 ITSM 里有三个不同层面的含义，LLM 必须按客户需求对号入座：

### 1.1 容器继承（同流程内，节点间表单容器复用）

**机制**：表单容器的 `default` 字段声明该容器继承自哪个节点的哪个容器。

```json
{
  "key": "section_change",
  "name": "变更信息",
  "type": "business_cmdb_instance_change_table",
  "default": {
    "userTaskId": "Task_apply",
    "sectionKey": "section_change"
  }
}
```

| 字段                   | 说明                                                     |
| ---------------------- | -------------------------------------------------------- |
| `default.userTaskId` | 继承来源节点 id（bpmnXML 中的节点）                      |
| `default.sectionKey` | 继承来源容器 key。**非空即表示本容器是"继承容器"** |

**行为规则（源码实证）**：

- 典型用于 **CMDB 变更容器**（`business_cmdb_instance_change_table`）的"实例模式"：后续节点可看到之前节点对实例的变更记录，继承过来的数据**只读**，当前节点配置的字段可继续编辑；
- 对继承容器，保存/合并数据时（`cmdb_instance_import/func.go::mergeData`）：**新表单数据中已不存在的旧数据会被打上删除标记**（`Deleted`）——即继承容器里的删减操作会语义化为"删除该实例变更"；
- 继承控件在实例选择脚本场景下（`process_script_service.go::ExecuteScriptTools`）：当前节点没有配置 remoteFunc 时**直接返回 nil 不报错**——继承的控件不需要重复配置脚本。

**继承容器 + 额外控件（继承 + 扩展，2026-07-28 实战用法）**：

继承容器的 `propertys`（控件定义）**不必与继承目标容器完全一致**——可在继承目标的基础上**新增目标没有的控件**。运行时：继承目标的数据回填到同 modelField 的控件（只读），新增控件由当前节点填写，**数据共存在同一容器**。

典型场景（主机申请流程）：实施节点表单的 `section_hosts`（table）用 `default.{Task_apply, section_hosts}` 继承申请节点的主机清单，并**新增 `ip` 列**：
- `hostname/cpus/memSize/diskSize/osSystem` 列 `disabled:true`（继承自申请，只读）
- `ip` 列 `disabled:false`（实施节点网络组填，可编辑）
- 验收脚本从该容器的 `formData` 一次读到全套（规格 + ip），无需在两个容器间配对

> 优势：数据集中在一个容器，人工读取 + 脚本解析都更简单（不用 `section_hosts` + `section_net` 两个 table 配对）。`default` 声明继承意图，新增列靠当前表单自己的 `propertys` 定义。

> 📝 对照 `modules/form_design/form-design-spec.md` §7.2 的控件级 `DATAINHERIT`（运行时自动从来源取值回填，用户不能填）——那是**控件级**数据搬运；本节 §1.1 是**容器级**整体复用，二者层级不同。

### 1.2 父子工单数据传递（父流程 → 子流程表单字段映射）

**机制**：子流程（callActivity）发起子工单时，把父工单表单数据按字段映射带入子工单表单。配置挂在**服务实例**上，接口：

```
PUT /api/flowable_service/v1/service_instance/:instanceId/service_subinst_deliver_config
{"cfgList": [SubinstDeliverCfg...]}
```

`SubinstDeliverCfg` 字段（`converter.go::SubInstDeliverCfgConvert`）：

| 字段                          | 说明                                                       |
| ----------------------------- | ---------------------------------------------------------- |
| `subProcName`               | 子流程名称（展示用）                                       |
| `subProcId`                 | 子流程定义 ID                                              |
| `subProcVerId`              | 子流程版本 ID                                              |
| `subTaskId`                 | 父流程中 callActivity 节点 id                              |
| `userTaskId`                | **父**流程取值节点 id（数据从哪个节点的表单取）      |
| `cntrId` / `ctrlId`       | **父**表单的容器 key / 控件 modelField               |
| `subCntrId` / `subCtrlId` | **子**流程目标表单的首节点容器 key / 控件 modelField |

即一条映射 = `父{userTaskId节点的表单}.cntrId.ctrlId` → `子流程首节点表单.subCntrId.subCtrlId`。`cfgList` 为该服务全部子工单配置，**全量覆盖**。

> 前置条件：服务关联的流程包含子流程（callActivity）。子流程节点（callActivity）的配置见 `process_development` §3.5。

### 1.3 工单转换数据携带（服务间转换）

`update_service_convertible_config`（设置服务转换控件）配置工单 A 处理中可转换为工单 B，表单数据按转换配置携带。与 1.2 的"父子"关系不同，这是**平级服务间**的转换，配置在服务转换控件上（`ServiceConvertConfig`），不在本文展开。

---

## 2. 条件显示（displayCondition）

### 2.1 两种配置位置

| 位置                     | 写法                                                                                                | 说明                       |
| ------------------------ | --------------------------------------------------------------------------------------------------- | -------------------------- |
| **静态**（设计时） | 容器或控件的`displayCondition` 属性（容器在 Container 顶层、控件在 `options.displayCondition`） | 表达式为真 → 显示         |
| **动态**（运行时） | 表单脚本返回`formConfig` 动态改写（见 §3.3）                                                     | 脚本按当前表单数据实时计算 |

### 2.2 表达式语法（产品手册规范）

- 引用字段：`#{容器key.控件modelField}`，取 `.value` 参与比较，如：

```
"#{gqjmjp5jhd.gqjmupwzyj}.value > 5"
```

- 特殊值：
  - `""`（空字符串）= **无条件显示**（默认）；
  - `"-"` = **一定隐藏**（它是非法表达式，求值失败即隐藏）。动态脚本控制显隐就是返回这两个值；
- 组合规则：
  - 多个联动配置组之间是 **AND** 关系；
  - ❌ 不支持跨字段 OR：`A == 1 || B == 2`；
  - ✅ 支持 `A == 1 && B == 2`、同字段 `A == 1 || A == 2`；
  - 优先级：**字段自身的 displayCondition 配置 > 全局显隐配置**；
- 同一 DSL 还支持：**设置默认值**（trigger.options 给下拉类字段设候选，格式 `[{label, value}]`）、**设置禁用/非禁用**（未满足表达式 → 禁用）、**设置必填/非必填**（未满足表达式 → 保持原始状态）。

> 📝 占位符正则细节（`#{sectionKey[rowIndex].modelField}`、跨节点联动 `options.displayUserTaskId`）见 `modules/form_design/form-design-spec.md` §7.1。

### 2.3 服务端行为提示

后端只在 `Component.Options` 上透传 `displayCondition`（string），**求值在前端**；但动态场景下后端会把脚本返回的 `formConfig` 透传给前端合并（见 §3.3）。LLM 生成表单时，条件显示属"前端契约"，按 §2.2 语法写即可，不要试图在业务侧解析它。

---

## 3. 表单生命周期脚本

表单/控件上的脚本本质是：**前端在特定事件点调 `process_script` 服务的执行接口，后端以沙箱方式执行工具库中的工具，工具的输出按事件类型约定的 key 解析并回传前端**。

> 🔔 **与流程节点前后置脚本区分**：本节讲**表单事件脚本**（前端表单事件触发）。**流程节点前后置脚本**（节点 done/reject 时由流程引擎触发，配在 `nodeSettings.scriptSettings`）是另一套：
> - 配置态（preScript/postScript/scriptIdList/operations/isAsync）→ `process_development` §4.2
> - 编写态（入参 action/scriptType、执行链路、与配置态关系）→ `process_development` 的「流程节点脚本编写」章节
>
> 两类脚本共享入参 `orderInfo`，见 `concepts/order-info.md`。

### 3.1 事件类型与配置位置

| 事件       | eventName 枚举     | 配置位置                                                                                                              | 触发时机                 |
| ---------- | ------------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| 数据加载后 | `afterDataLoad`  | 容器`options.remoteFunc.onPageLoadId`（工具 ID）                                                                    | 表单打开、数据加载完成后 |
| 提交前检查 | `preSubmitCheck` | 容器`options.remoteFunc.beforeSubmitId`                                                                             | 点击提交，校验通过才放行 |
| 值变更     | `onValueChange`  | 容器`options.listenStart=true` + `options.listenEvents[].remoteFunc.toolId`；或控件 `options.remoteFunc.toolId` | 监听控件值变化           |
| 控件加载   | `componentLoad`  | 控件级（如 iframe 控件）                                                                                              | 控件初始化               |
| 实例选择   | `instSelect`     | 控件`options.remoteFunc`（实例选择类控件）                                                                          | 打开实例选择弹窗取数     |

> 💡 **onValueChange 监听脚本的赋值方式（2026-08-04 实测）**：
> - 监听脚本回填 formData 的**赋值方式默认用「替换」**（脚本输出的 formData 整体覆盖原表单数据，不是追加/合并）。设计时无需额外配置，脚本按"替换"语义组织输出即可。
> - **监听表格容器**（`componentList` 用 `type:"table_container"`，如 `[{key:"section_hosts", label:"主机清单(table)", value:"section_hosts", type:"table_container"}]`）时：**`formData` 是变更前的数据**（被监听容器 `section_hosts` 在 formData 里**没有值**），**表格的真实数据在 `args` 里**（`args` 是表格所有行的 JSON 数组字符串，`eventSource=容器key`）。脚本取表格数据必须**从 `args` 解析**，不能从 formData 取。
> - 监听场景 formData 的 section 行数据用 `"value"` 键（`{"key":"section_summary","value":[...]}`），与提交前/加载场景的 `"values"` 不同——回填时按 `value` 优先。

### 3.2 表单事件脚本入参（工具可读取的变量）

**表单事件脚本**（afterDataLoad/preSubmitCheck/onValueChange/componentLoad）入参（`process_script_service.go::makeToolExecInput`）：

| 变量            | 内容                                                                                  |
| --------------- | ------------------------------------------------------------------------------------- |
| `orderInfo`   | 工单信息 JSON（工单 + 当前步骤；**首节点发起时工单尚未创建，无此参数**）—— 详解见 `concepts/order-info.md`        |
| `loginUser`   | 当前登录用户名                                                                        |
| `eventSource` | 事件源——触发事件的**控件 id**                                                 |
| `args`        | 事件值——触发事件的**控件的值**                                                |
| `formData`    | 整个当前表单数据 JSON                                                                 |
| `extArgs`     | 额外参数`Record<string,any>`；**table 容器内触发时用于定位行**：`{page: 1}` |

> ⚠️ **首节点无 orderInfo**：表单事件脚本在首节点发起时入参只有 `loginUser/eventSource/args/formData`，脚本要做存在性兼容（`locals().get("orderInfo")`）。

**控件联动脚本**（控件 remoteFunc，`ExecuteScriptTools`）入参由表单设计中 `scriptInputs` 声明，三种来源（`GetScriptInput`）：

| scriptType      | 取值                                                                                                     |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| `static`      | 静态值`scriptValue`                                                                                    |
| `currentNode` | 当前节点表单值（`propertyPath` 声明取值路径 `容器key.控件field`，前端解析后传 `currentNodeValue`） |
| `history`     | 历史节点表单值（配`formVersionId` 指定历史表单版本）                                                   |

### 3.3 脚本返回约定（按事件类型，key 必须精确）

工具通过**输出变量**（输出标记协议，见 `modules/autoops_tool/tool-package-dev.md`）返回，后端 `formEventDataParsing` 按 eventName 解析：

**afterDataLoad / onValueChange**：

| 输出 key       | 必填         | 说明                                                                 |
| -------------- | ------------ | -------------------------------------------------------------------- |
| `formData`   | **是** | 回填的表单数据 JSON（缺了直接报错"工具返回缺少关键字段： formData"） |
| `formConfig` | 否           | **动态表单配置**：改写显隐/禁用等（见 §3.4）                  |
| `ticketName` | 否           | 动态设置工单标题                                                     |

**preSubmitCheck**：

| 输出 key        | 必填       | 说明                                                   |
| --------------- | ---------- | ------------------------------------------------------ |
| `checkState`  | 二选一必有 | 校验状态                                               |
| `submitCheck` | 二选一必有 | 校验结果描述（两者全无 → 报错"至少需要设置一个返回"） |
| `ticketName`  | 否         | 动态工单标题                                           |

**componentLoad**：

| 输出 key   | 必填         | 说明         |
| ---------- | ------------ | ------------ |
| `result` | **是** | 控件加载结果 |

**错误反馈**：工具执行失败时，若输出含 `raise` 字段，其值会**直接作为错误信息抛给前端用户**——脚本里用 `raise` 输出可读的中文错误（如"库存不足，无法申请"）。

### 3.4 formConfig 动态改写规范（控制显隐/禁用）

`formConfig` 是一个**与原表单定义同构的裁剪数组**，规则（产品手册原文要点）：

- **保留原表单定义的整体结构**，只写要改的元素；**每一层都必须带 `key`**（容器 key、控件 key）；
- 容器显隐：`{"key": "gqnft7yobm", "displayCondition": "-"}`（`-` 隐藏，`""` 显示）；
- 控件显隐/禁用：

```json
[
  {
    "key": "gqnft7yobm",
    "propertys": [
      {
        "key": "gqnft7yobn",
        "options": {
          "disabled": false,
          "displayCondition": ""
        }
      }
    ]
  }
]
```

**示例脚本（python，onValueChange）**：

```python
# 入参变量直接可用：formData, eventSource, args, orderInfo, loginUser
if "选项1" in args:
    formConfig = [{"key": "gqsl300395", "displayCondition": ""}]   # 显示
else:
    formConfig = [{"key": "gqsl300395", "displayCondition": "-"}]  # 隐藏

import json
# 按工具输出标记协议输出（见 modules/autoops_tool/tool-package-dev.md）
import base64
def out(key, value):
    print("##PARAMETER_%s:%s:%s_RETEMARAP##" % (key, base64.b64encode(value).strip(), key))

out("formData", formData)                      # 原样回传或修改后的表单数据
out("formConfig", json.dumps(formConfig))
```

### 3.5 执行链路与注意事项（源码实证）

1. **沙箱执行**：表单脚本走 `ExecuteToolByRunner`（py_script_runner 快速通道），仅 **python 脚本**能同步返回；非 python 脚本降级为"异步下发 + 轮询结果"。报错"表单事件异常， 工具未设置沙箱执行或工具未执行"时检查工具的 sandboxRun/沙箱配置；
2. **执行记录**：每次执行落 `ProcessInstanceToolExecRecord`（含 toolId、eventName=scriptType、eventSource=propertyKey）；**首节点表单脚本执行时工单尚未创建，记录无法关联工单**（源码注释明确的已知限制）；
3. **多工具输出覆盖**：同一脚本配多个 toolId 时，返回的 outputs 是**最后一个工具的输出**（源码注释标记的 bug，设计时避免依赖多工具返回值合并）。

> 🔔 **节点前后置脚本**（区别于表单事件脚本）的执行链路（同步线性/异步忽略异常、`operations` 中 `done` 同时匹配 pass 和 reject 信号）见 `process_development` 的「流程节点脚本编写」章节，不在本文展开。

---

## 4. 速查：三类需求的配置落点

| 客户需求                                | 配置位置                                                                                                                                      |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 节点 B 的表单要看到/沿用节点 A 填的数据 | ① 同表单不同节点：直接绑同一个表单版本；② 容器级复用：容器`default.{userTaskId, sectionKey}`（§1.1）；③ CMDB 变更场景用变更容器实例模式 |
| 子工单要带父工单的字段值                | 服务实例`service_subinst_deliver_config`（§1.2）                                                                                           |
| 某字段按其他字段值显隐                  | 静态：控件`options.displayCondition` 表达式（§2.2）；动态：onValueChange 脚本返回 formConfig（§3.4）                                      |
| 打开表单时自动带出数据                  | 容器`options.remoteFunc.onPageLoadId` + afterDataLoad 脚本返回 formData（§3.3）                                                            |
| 提交前做业务校验                        | 容器`options.remoteFunc.beforeSubmitId` + preSubmitCheck 脚本返回 checkState/submitCheck，错误用 `raise` 输出（§3.3）                    |
| 下拉候选随其他字段变化                  | 控件`options.remoteFunc`（currentNode 入参）或字段联动 trigger.options DSL（§2.2）                                                         |
| 节点审批通过/驳回时跑自动化             | 流程 nodeSettings.scriptSettings（pre/postScript）—— **见 `process_development`「流程节点脚本编写」章节**，入参 orderInfo/action/scriptType |
