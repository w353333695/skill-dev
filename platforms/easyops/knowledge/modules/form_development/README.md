# ITSM 表单开发（form_development）

easyops itsc 平台**表单开发态 / 契约态 + 进阶运行时行为**领域的知识包：表单 schema V2 接口契约、formDefinition
字段全表、流程节点绑定、数据源、以及表单运行时行为（数据继承 / 条件显示 / 生命周期脚本）。归在 `knowledge/modules/`
作为**领域知识的延伸**（接口字段深层语义 + 运行时行为为平台特定，不进 skill）。

> **切面定位（重要）**：ITSM 表单在本知识库分三个互补切面，同名对象、非重复：
>
> | 切面 | 位置 | 回答什么 |
> | --- | --- | --- |
> | **开发态 / 契约态**（本模块） | `knowledge/modules/form_development/` | 接口字段什么含义、请求体怎么组装、字段间联动规则 |
> | **设计态**（结构合规规则） | `knowledge/modules/form_design/` | formDefinition 怎么写才合规（容器/控件/布局/红线 + `check_form_design.py`） |
> | **运行态**（接口卡片） | `registry/form/` | 接口怎么调（method/path/params，给 verify_dag/execute_dag 用） |
>
> 调表单接口前先读本模块懂字段语义，再用 `registry/form` 卡片发起调用；产出 formDefinition 前先过
> `form_design` 的静态合规校验。

## 文件清单

| 文件 | 作用 | 给谁用 |
| --- | --- | --- |
| `form-schema-v2-dev.md` | 表单版本 V2 三接口契约 + formDefinition 字段全表 + 流程节点绑定 SetFormVersion + 表单数据源 + 端到端示例 + 检查清单 | LLM 读（生成表单请求体 / 编排表单接口时） |
| `form-advanced.md` | 数据继承三种机制 + 条件显示深化 + 表单生命周期脚本（事件/入参/返回/formConfig 动态改写/执行链路）+ 速查配置落点 | LLM 读（设计表单运行时行为 / 写表单脚本时） |

> 本模块以 markdown 知识为主（给 LLM 读），**不含可执行校验脚本**——表单结构静态校验在姊妹模块
> `form_design/`（`check_form_design.py`）。

## 与流程脚本、标准字段、orderInfo 的关系（跨模块边界）

本模块讲**表单事件脚本**（afterDataLoad / preSubmitCheck / onValueChange / componentLoad）。下列相邻知识已按切面归位，避免重复：

| 主题 | 归属 | 说明 |
| --- | --- | --- |
| **流程节点前后置脚本**（配置态 preScript/postScript/scriptIdList/operations） | `modules/process_development/` §4.2 | 流程节点 done/reject 时由流程引擎触发 |
| **流程节点前后置脚本**（编写态：入参 action/scriptType、执行链路、输出协议） | `modules/process_development/`「流程节点脚本编写」章节 | 与表单事件脚本区分，归流程侧 |
| **orderInfo（工单全景）** | `concepts/order-info.md` | 表单事件脚本（非首节点）+ 流程节点脚本的**共享入参**，单一真相源 |
| **标准字段**（字段模型 / CRUD 接口 / ITSC_ 前缀规则 / kind 全枚举） | `modules/standard_field/standard-field-types.md` | 独立实体，本模块只讲表单如何引用 |
| **脚本工具包**（输出标记协议 `##PARAMETER_.._RETEMARAP##`） | `modules/autoops_tool/tool-package-dev.md` | 表单脚本 / 节点脚本都调工具库工具 |

## 来源与完整性

- **来源**：`flowable_service` 组件源码（`process_script` / `internal/form` / `internal/tool`）+ 产品手册整理。
- **完整性**：`completeness=partial`，`last_verified` 为空——**未经真实 EasyOps 环境端到端真调核对**，
  接口契约与运行时行为依源码归纳。具体待核对项见各正文 frontmatter `gaps`。
- 使用本知识组织请求体 / 设计运行时行为时，关键字段（UpdateVersionV2 的 done 分支行为、displayCondition 表达式求值、
  formConfig 动态改写、CMDB 变更容器继承）建议结合现场环境验证；命中 `gaps` 的部分需明说"待核对，不能确定"。
