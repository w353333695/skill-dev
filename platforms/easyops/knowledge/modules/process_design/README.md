# ITSM 流程设计校验（process_design）

easyops itsc 平台**流程设计态**领域的资产包：BPMN 2.0 XML 的静态校验工具 + 规则知识 + 样例。
归在 `knowledge/modules/` 作为**领域知识的延伸**（规则集为平台特定，不进 skill）。

> **切面定位**：本模块描述流程**设计态**（BPMN XML 的静态合规规则）；`registry/process`
> 描述流程**运行态**（flowable 引擎的创建/保存/查询/跳转接口）。同名对象（ITSM 流程）不同切面，非重复。

## 文件清单

| 文件 | 作用 | 给谁用 |
|---|---|---|
| `compliance-rules.md` | 27 条合规规则清单（等级/触发条件/消息/与源码差异） | LLM 读（业务语义） |
| `check_compliance.py` | 语义合规校验（缺开始事件、网关直连、未连接、重名…） | 确定性执行 |
| `check_layout.py` | 图形布局校验（节点重叠、压线、连线交叉、回流、坐标非法） | 确定性执行 |
| `sample.bpmn` | BPMN 测试样例（含排他/包容网关、表单决定流向） | 跑脚本用 |

> 两脚本**零依赖**（仅 Python 3.8+ 标准库），独立运行，不接入 api-console 的卡片/DAG 体系。

## 用法

```bash
# 语义合规（退出码：error=1 / 仅warn或无问题=0 / 解析错误=2）
python3 check_compliance.py sample.bpmn
python3 check_compliance.py sample.bpmn --json          # JSON 输出
python3 check_compliance.py sample.bpmn --include-off   # 连默认关闭的规则一起跑

# 图形布局（无 BPMNDI 图形层时优雅降级，退出码 0）
python3 check_layout.py sample.bpmn
python3 check_layout.py sample.bpmn --json
```

规则细节（27 条等级/触发条件/消息）、与后台源码的差异见 `compliance-rules.md`。

## 表单决定流转机制

流程对接表单的核心机制：某个用户任务节点（`flowable:isFormDecision="1"`）填写的表单字段值，经 `flowable:formExpressionName="变量名:表单字段;..."` 声明后，作为变量名出现在后续网关出口 SequenceFlow 的条件表达式里（如 `${level}=='紧急'`），由 flowable 引擎按表单实际值选分支。「业务/表单扩展」4 条规则即校验这套机制配置是否自洽。

机制原理（两个属性的值格式、运行时链路、与校验规则的关系）详见 `compliance-rules.md`「三、表单决定流转机制」；属性中的「表单字段」即 `form_design` 模块描述的 `modelField`（见 `knowledge/modules/form_design/form-design-spec.md`）。

## 规则来源（仅溯源）

后台 `applications_sa/itsc-union-standalone-NA/bricks/itsc-process-manage/dist/lazy-bricks/
process-design.e0d5~lazy-bricks/process-detail.e0d5.fe534c4c.js` 内嵌的
bpmn-js-bpmnlint（[bpmn-io/bpmn-js-bpmnlint](https://github.com/bpmn-io/bpmn-js-bpmnlint)）。
