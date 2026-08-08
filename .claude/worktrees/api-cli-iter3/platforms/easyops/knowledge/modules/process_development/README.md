# ITSM 流程开发（process_development）

easyops itsc 平台**流程开发态 / 接口契约态**领域的知识包：`flowable_service.process_definition_version`
模块 V2 接口的契约语义、bpmnXML/processSetting 字段详解、端到端请求体组织。归在 `knowledge/modules/`
作为**领域知识的延伸**（接口字段深层语义为平台特定，不进 skill）。

> **切面定位（重要）**：ITSM 流程在本知识库分三个互补切面，同名对象、非重复：
>
> | 切面 | 位置 | 回答什么 |
> | --- | --- | --- |
> | **开发态 / 契约态**（本模块） | `knowledge/modules/process_development/` | 接口字段什么含义、请求体怎么组装、字段间联动规则 |
> | **设计态**（静态规则） | `knowledge/modules/process_design/` | BPMN XML 怎么画才合规（27 条 bpmnlint + 配套校验脚本） |
> | **运行态**（接口卡片） | `registry/process/` | 接口怎么调（method/path/params，给 verify_dag/execute_dag 用） |
>
> 调流程接口前先读本模块懂字段语义，再用 `registry/process` 卡片发起调用；产出 bpmnXML 前先过
> `process_design` 的静态合规校验。

## 文件清单

| 文件 | 作用 | 给谁用 |
| --- | --- | --- |
| `process-definition-v2-dev.md` | 四个 V2 接口契约 + bpmnXML/processSetting 字段全表 + 端到端示例 + 请求体检查清单 | LLM 读（生成请求体 / 编排流程接口时） |

> 本模块以 markdown 知识为主（给 LLM 读），**不含可执行校验脚本**——静态合规校验在姊妹模块
> `process_design/`（`check_compliance.py` / `check_layout.py`）。

## 来源与完整性

- **来源**：`flowable_service` 组件 `process_definition_version` 模块源码整理。
- **完整性**：`completeness=partial`，`last_verified` 为空——**未经真实 EasyOps 环境端到端真调核对**，
  请求体组织依源码归纳。具体待核对项见正文 frontmatter `gaps`（dataVersion 取值、权限 action 名、
  `cleanSetting` 清洗边界、附带接口契约等）。
- 使用本知识组织请求体时，关键字段（处理人 userType 映射、rejectNodes 清洗、权限 action）建议结合
  现场环境验证；命中 `gaps` 的部分需明说"待核对，不能确定"。

## 相邻知识

- 流程设计态静态合规规则：`../process_design/compliance-rules.md`（+ `check_compliance.py`）
- 节点绑定表单的设计态结构：`../form_design/form-design-spec.md`
- 节点前后置脚本引用的工具包结构：`../autoops_tool/tool-package-dev.md`
- 流程运行态接口卡片：`registry/process/`（`createProcessDefinition` / `saveProcessDefinitionVersion` /
  `updateProcessDefinition` / `listProcessDefinition` / `deleteProcessDefinitionVersion` 等）
