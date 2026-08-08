---
name: bpmn-compliance-rules
kind: module
module: process_design
tags: [ITSM, 流程, BPMN, 合规检测, bpmnlint, flowable, 网关, 开始事件, 流程设计]
completeness: full
gaps: []
last_verified: ''
---

# ITSM 流程设计合规规则（BPMN）

> 本文是 easyops itsc 平台**流程设计态**的领域规则知识：BPMN 2.0 XML（兼容 flowable / camunda 扩展）
> 流程在导入/保存前必须满足的合规约束。规则集共 **27 条**，其中 **15 条默认启用**（error/warn）、**12 条默认关闭**（off）。
> 同目录 `check_compliance.py` 是本规则集的可执行校验器（零依赖，把下述规则从文档变成可跑的检查）。
>
> 规则来源（仅溯源）：后台 `applications_sa/itsc-union-standalone-NA/bricks/itsc-process-manage/dist/lazy-bricks/process-design.e0d5~lazy-bricks/process-detail.e0d5.fe534c4c.js` 内嵌的 **bpmn-js-bpmnlint** 模块（[bpmn-io/bpmn-js-bpmnlint](https://github.com/bpmn-io/bpmn-js-bpmnlint)）。
>
> 语义定位：本规则集描述流程**设计态**的静态合规；`registry/process` 描述流程**运行态**的 flowable 接口（创建/保存/跳转），两者同名对象不同切面，非重复。

---

## 一、规则等级与产出

每条规则带等级，违规时产出一条问题，含：规则名（`rule`）、等级（`level`=`error`/`warn`）、
违规元素 id / 类型（`$type`）/ 名称、源 XML 行号、消息。

- **error**：必须修复，否则流程设计不合规（如缺开始事件、网关直连、节点未连接、重名）。
- **warn**：建议修复，不阻断（如包容/并行网关未成对）。
- **off**：默认不检查，可用 `--include-off` 强制开启。

其中 `flow-conditional-error` 与 `form-flow` 经评估误报较多，已从 error 降为 off（见「四、与源码的差异」）。

适用：流程导入前预检、流程设计自查、CI 校验。

---

## 二、规则清单（27 条）

等级与源码 `oD` 配置完全一致。**定位元素**指 `t.report(id, ...)` 上报的元素 id
（可能与被检查元素不同，如容器规则上报子元素）。

### 结构完备性

| 规则                         | 等级  | 触发条件                                                                                                                 | 消息                                                                        | 定位元素 |
| ---------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- | -------- |
| `start-event-required`     | error | Process / SubProcess 的 flowElements 中无 StartEvent                                                                     | `Process is missing start event` / `Sub process is missing start event` | 容器本身 |
| `end-event-required`       | error | Process / SubProcess 的 flowElements 中无 EndEvent                                                                       | `Process is missing end event` / `Sub process is missing end event`     | 容器本身 |
| `single-blank-start-event` | error | FlowElementsContainer 中「无事件定义的 StartEvent」>1 个                                                                 | `流程有多个开始事件` / `子流程有多个开始事件`                           | 容器本身 |
| `no-disconnected`          | error | Task/Gateway/SubProcess/Event/CallActivity（非事件触发型）未连接：StartEvent 无出口、EndEvent 无入口、其它节点缺入或缺口 | `Element is not connected`                                                | 节点本身 |
| `flow-elements-length`     | error | FlowElementsContainer 有子元素但无任何 UserTask                                                                          | `进程缺少用户任务`                                                        | 容器本身 |

### 连线与流向

| 规则                            | 等级          | 触发条件                                                                  | 消息                                                                                          | 定位元素                           |
| ------------------------------- | ------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------- |
| `conditional-flows`           | **off** | 元素有默认流或任一出口有条件、且出口>1 时，存在「无条件且非默认」的出口流 | `Sequence flow is missing condition`                                                        | 出口 SequenceFlow                  |
| `no-duplicate-sequence-flows` | error         | 两条 SequenceFlow 的`源#目#条件体` 完全相同                             | `SequenceFlow is a duplicate`；并对源/目追加 `Duplicate outgoing/incoming sequence flows` | 重复的 SequenceFlow 及其源、目节点 |
| `no-implicit-split`           | **off** | Task/Event 的出口中，「无条件且非默认」的流 >1                            | `Flow splits implicitly`                                                                    | 节点本身                           |

### 网关

| 规则                                            | 等级          | 触发条件                                                                      | 消息                                                               | 定位元素     |
| ----------------------------------------------- | ------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------ |
| `no-complex-gateway`                          | error         | 元素为 ComplexGateway                                                         | `Element has disallowed type <bpmn:ComplexGateway>`              | 网关本身     |
| `no-inclusive-gateway`                        | **off** | 元素为 InclusiveGateway                                                       | `Element has disallowed type <bpmn:InclusiveGateway>`            | 网关本身     |
| `no-gateway-join-fork`                        | **off** | Gateway 同时有多入(>1)与多出(>1)                                              | `Gateway forks and joins`                                        | 网关本身     |
| `superfluous-gateway`                         | **off** | Gateway 恰好 1 入 1 出（冗余）                                                | `Gateway is superfluous. It only has one source and target.`     | 网关本身     |
| `inclusive-gateway-appear-in-pairs`           | warn          | 容器内 InclusiveGateway 数量为奇数                                            | `Gateway appear in pairs`                                        | 最后一个网关 |
| `parallel-gateway-appear-in-pairs`            | warn          | 容器内 ParallelGateway 数量为奇数                                             | `Gateway appear in pairs`                                        | 最后一个网关 |
| `gateway-cannot-be-directly-connected`        | error         | Inclusive/Exclusive/Parallel 网关的入向源或出向目标是同类网关（网关直连网关） | `Gateway cannot be directly connected`                           | 网关本身     |
| `gateway-cannot-be-directly-connected-to-end` | warn          | Inclusive/Exclusive 网关上游直连 StartEvent 或下游直连 EndEvent               | `Gateway cannot be directly connected to start` / `... to end` | 网关本身     |

### 事件与子流程

| 规则                                    | 等级          | 触发条件                                                                                                                 | 消息                                                                                                                               | 定位元素            |
| --------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| `single-event-definition`             | **off** | Event 拥有 >1 个事件定义                                                                                                 | `Event has multiple event definitions`                                                                                           | 事件本身            |
| `event-sub-process-typed-start-event` | **off** | 事件子流程（triggeredByEvent）内的 StartEvent 无事件定义                                                                 | `Start event is missing event definition`                                                                                        | StartEvent          |
| `sub-process-blank-start-event`       | **off** | 非事件子流程的 SubProcess 内 StartEvent 带了事件定义（应为空白开始）                                                     | `Start event must be blank`                                                                                                      | StartEvent          |
| `sub-process-start`                   | error         | CallActivity 上游直连 StartEvent，或下游连 Inclusive/Exclusive 网关                                                      | `The starting node cannot directly connect to subprocesses` / `Cannot connect to inclusive/exclusive gateway after subprocess` | 相连的 SequenceFlow |
| `sub-process-quote`                   | error         | Inclusive/Parallel 网关后有多条出口指向 CallActivity，且首尾两个 CallActivity 的`calledElement` 相同（引用同一子流程） | `The subprocesses behind the inclusive/parallel gateway cannot reference the same subprocess`                                    | 两个 CallActivity   |

### 命名

| 规则                 | 等级  | 触发条件                                                            | 消息                                                                                                                | 定位元素 |
| -------------------- | ----- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | -------- |
| `name-required`    | error | UserTask/CallActivity 中存在重名；或名称长度 >20；或名称为空/纯空白 | `Node names cannot be duplicated` / `The node name cannot exceed 20 characters` / `Node name cannot be empty` | 违规节点 |
| `is-empty-element` | error | 元素类型严格为`bpmn:Task`（裸 `<task>`，非 UserTask 等子类型）  | `节点类型错误`                                                                                                    | 节点本身 |

### 业务/表单扩展（flowable）

下列规则依赖 flowable 扩展属性 `$attrs`：

- `flowable:isFormDecision="1"`：节点设为「表单决定流向」
- `flowable:formExpressionName="变量名:表单字段;..."`：表单表达式配置
- `flowable:strategy`：用户任务策略（如 `emptyAssign` 表跳过）

| 规则                       | 等级                    | 触发条件                                                                                                                                                                                                                                                                                                                                                                                                                                     | 消息                                                                                                                                            | 定位元素          |
| -------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `flow-conditional-error` | **off**（已关闭） | Inclusive/Exclusive/Parallel 网关出口>1 时，出口流条件未用`${...}` 包裹，或缺条件；若上游为「表单决定流向」节点，则校验表单变量名与出口表达式变量名一致 | `表达式需要用${}包裹` / `Sequence flow is missing condition` / `Used form to determine flow but did not configure variable names and form fields` / `The variable name in the form determines the flow does not match the expression variable name on the sequence flow` | 出口 SequenceFlow                                                                                                                               |                   |
| `inclusive-gateway`      | error                   | InclusiveGateway 入口≤1 时，其上游节点未设为「表单决定流向」                                                                                                                                                                                                                                                                                                                                                                                | `The node in front of the inclusive branch gateway must be set to form determines flow`                                                       | 入口 SequenceFlow |
| `form-flow`              | **off**（已关闭） | Inclusive/Exclusive/Parallel 网关（入口≤1）上游非「表单决定流向」时，出口流表达式不满足「含`==` 且不含 `>=`/`<=`/`>`/`<`/`!=`/`!==`」                                                                                                                                                                                                                                                                                         | `The expression symbol that determines the flow of the gateway node is not a form and must be used==`                                         | 出口 SequenceFlow |
| `auto-pass`              | warn                    | UserTask 设了`flowable:strategy`（非 `emptyAssign`）且非表单决定流向时，出口连向 Inclusive/Exclusive 网关                                                                                                                                                                                                                                                                                                                                | `When the strategy for a user task is set to "xx skip" and not determined by a form, it cannot be followed by an inclusive/exclusive gateway` | UserTask 本身     |

> **关于 `form-flow` 的语义提示**：源码逻辑为「表达式含 `==` 且不含 `>=`/`<=`/`>`/`<`/`!=`/`!==`」时才算合规，否则上报。
> 注意 `!=` 字符串中包含 `==` 子串，`a!=b` 会被判为合规。本实现忠实保留该逻辑。

---

## 三、表单决定流转机制

「表单决定流转」（form determines flow）是 ITSM 流程对接表单的核心机制：让**某个用户任务节点填写的表单字段值**决定后续网关走哪条分支。它由两个 flowable 扩展属性承载，存在 BPMN 节点的 `$attrs` 上。「二、规则清单」的「业务/表单扩展」4 条规则即校验这套机制是否配置自洽。

### 3.1 两个承载属性

| 属性 | 值 | 作用 |
|---|---|---|
| `flowable:isFormDecision` | `"1"` | 标记该 UserTask 为「表单决定流向」节点 |
| `flowable:formExpressionName` | `"变量名:表单字段;变量名:表单字段"` | 声明该节点哪些表单字段参与决定流向，及它们在表达式里的变量名 |

> 二者配合：`isFormDecision="1"` 开启机制，`formExpressionName` 列出参与字段。缺任一，机制不成立——这也是 `flow-conditional-error` / `inclusive-gateway` 等规则的判据。

### 3.2 `formExpressionName` 值格式

- 多组用 `;` 分隔：`变量名1:表单字段1;变量名2:表单字段2`
- 每组用 `:` 分隔：左侧=表达式里的变量名，右侧=表单字段 `modelField`
- 设计器属性面板按此格式拼装/解析：`split(";")` 拆多组、`split(":")` 拆每组；「添加变量」在末尾追加 `;`

示例：
```xml
<bpmn:userTask id="Task_Fill" flowable:isFormDecision="1"
               flowable:formExpressionName="level:fld_urgency;type:fld_category" />
```
表示该节点的 `fld_urgency` 字段在表达式中叫 `level`，`fld_category` 叫 `type`。

### 3.3 运行时流转链路

```
[填表节点 Task_Fill]   isFormDecision=1, formExpressionName="level:fld_urgency;..."
        │   用户填表 → 表单值注入流程变量（level/type 取自对应字段）
        ▼
[包容/排他网关]   出口 SequenceFlow 条件用这些变量名
        │   conditionExpression: "${level}=='紧急'"  → 走分支 A
        │   conditionExpression: "${level}=='一般'"  → 走分支 B
        ▼
   flowable 引擎按表单实际填写值选分支
```

### 3.4 设计期校验如何用这套属性

「业务/表单扩展」4 条规则即检查这套机制配置是否正确：

- **变量名一致性**（`flow-conditional-error`，默认 off）：网关上游若是 isFormDecision 节点，其 `formExpressionName` 声明的变量名须与出口条件表达式里用到的变量名一致。
- **网关前置必设**（`inclusive-gateway`，error）：包容网关入口的上游节点必须设 `isFormDecision="1"`。
- **跳过策略冲突**（`auto-pass`，warn）：节点设了跳过策略（非 `emptyAssign`）又没设表单决定流向，出口不能接包容/排他网关。
- **表达式符号**（`form-flow`，默认 off）：非表单决定流向时，网关出口表达式须用 `==`。

> 设计期校验只保证「配置自洽」（属性齐全、变量名对得上）；真正的「按表单值选分支」是 flowable 引擎运行时行为，不在静态校验范围。属性机制与表单字段结构的衔接（变量名→modelField）见 `knowledge/modules/form_design/form-design-spec.md`。

---

## 四、与源码的差异

1. **修正 `bpmn:ParallelGatewa` 笔误**：源码在 `gateway-cannot-be-directly-connected`、
   `flow-conditional-error`、`form-flow` 三条规则的类型数组中写作 `"bpmn:ParallelGatewa"`
   （漏一个 `y`），导致 ParallelGateway 永不匹配、这三条规则对并行网关失效。
   本实现修正为 `bpmn:ParallelGateway`，使并行网关能被正确检查。
2. **`off` 规则默认不运行**：与 bpmnlint 行为一致；可用 `--include-off` 强制开启。
3. **主动关闭 `flow-conditional-error` 与 `form-flow`**：这两条业务扩展规则对
   flowable 表达式/网关符号的判定较激进（如 `form-flow` 要求表达式「含 `==` 且不含
   `>=`/`<=`/`>`/`<`/`!=`/`!==`」才算合规，与实际流程写法出入大），在现有流程中误报较多。
   已在 `RULES` 表中由 `error` 降为 `off`，默认不检查；如需临时复查可用 `--include-off`。
   规则的判定逻辑本身保留在代码中，未删除。
4. **行号定位为增强项**：源码运行在浏览器 bpmn-js 内，问题通过画布 overlay 呈现、
   无「源码行号」概念。本实现额外用 expat 扫描记录每个带 `id` 元素的 XML 起始行号，
   便于离线定位。行号解析失败时退化为 `0`，不影响规则判定。
5. **表达式变量提取 `nD`**：源码用 math.js 的 AST 提取 `SymbolNode` 作为表达式变量名；
   本实现用正则近似（去 `${}`、替换 `&&`/`||`、提取非保留字、非函数名的标识符），
   在常见比较表达式上结果等价，极端嵌套表达式可能有细微差异。

---

## 五、局限

- 仅解析 `<definitions>/<process>` 下的流程元素；规则本身不依赖 `bpmndi` 图形坐标。
  **但 `check_compliance.py` 已额外增加 DI 存在性检查**（2026-08-04 主机申请流程实战补充）：
  - `diagram-required`（error）：BPMN XML 缺 `<bpmndi:BPMNDiagram>` 时报错——bpmn-js 渲染流程图依赖
    `BPMNShape`（节点坐标）/`BPMNEdge`（连线坐标），缺失时流程设计器报 **"no diagram to display"**。
    注意这是**图形层**要求，与流程逻辑合规（发起工单）无关——逻辑不依赖 DI 也能流转，但页面无法渲染流程图。
  - `diagram-element-missing`（warn）：`BPMNDiagram` 存在但为空（无 Shape/Edge）时提示。
  - 这两条是 bpmnlint 27 条之外的**补充规则**（bpmnlint 本身不检查 DI），不属于 27 条清单。
- `MessageFlow`、`DataObject` 等非 FlowNode 元素不在规则覆盖范围。
- 表单表达式变量提取为正则近似，与 math.js AST 在复杂表达式上可能略有差异。
- 行号定位依赖 expat 对完整 XML 的扫描；XML 片段（无根元素）会跳过行号但不影响规则。

---



> 规则来源（后台路径，仅供溯源，非本目录文件）：
> `applications_sa/itsc-union-standalone-NA/bricks/itsc-process-manage/dist/lazy-bricks/process-design.e0d5~lazy-bricks/process-detail.e0d5.fe534c4c.js`
