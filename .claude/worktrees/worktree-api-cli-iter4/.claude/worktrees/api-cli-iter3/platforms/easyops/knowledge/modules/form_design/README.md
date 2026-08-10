# ITSM 表单设计校验（form_design）

easyops itsc 平台**表单设计态**领域的资产包：流程表单 JSON（`formDefinition`）的结构知识 + 静态校验工具 + 样例。
归在 `knowledge/modules/` 作为**领域知识的延伸**（结构规则为平台特定，不进 skill）。

> **切面定位**：本模块描述表单**设计态**（`formDefinition` JSON 的结构/配置/联动规则）；`registry/form`
> 描述表单**运行态**（flowable 的 createForm / getFormVersion / deleteFormVersion 等接口）。同名对象（ITSM 表单）不同切面，非重复。

## 文件清单

| 文件 | 作用 | 给谁用 |
|---|---|---|
| `form-design-spec.md` | 表单结构知识（数据结构/7 容器/31 控件/布局/条件显示/数据继承/脚本绑定/生产红线） | LLM 读（业务语义） |
| `check_form_design.py` | 设计期 schema 静态校验（id 命名/唯一/标题/引用/正则/布局/CMDB 容器…） | 确定性执行 |
| `sample.json` | 合规表单样例（5 容器 / 27 控件全展示） | 跑脚本用 |
| `sample.invalid.json` | 故意违规的反例（演示校验器检出） | 跑脚本用 |

> 脚本**零依赖**（仅 Python 3.8+ 标准库），独立运行，不接入 api-console 的卡片/DAG 体系。

## 用法

```bash
# 校验（退出码：error=1 / 仅warn或无问题=0 / 解析错误=2）
python3 check_form_design.py sample.json
python3 check_form_design.py sample.json --json          # JSON 输出
python3 check_form_design.py sample.invalid.json          # 反例：检出多条 error

# 也接受 JSON 原文 / stdin
cat form.json | python3 check_form_design.py -
python3 check_form_design.py '[{...容器...}]'
```

结构细节、31 种控件配置、条件显示 `#{}` 语法、数据继承、脚本绑定契约、生产红线见 `form-design-spec.md`。

## 与卡片联动（编排视角）

- `registry/form/createForm` 的 `formDefinition` 参数 = 本模块描述的表单 JSON；生产表单时按本规则构造并预检。
- `registry/form/getFormVersion`/`getFormVersionV2` 返回的 formDefinition 即本结构。
- 典型编排：拉表单 → `check_form_design.py` 离线校验 → 改后新版本提交。

## 规则来源（仅溯源）

前端 bundle `tmp/index.9c69d18d.js`（表单设计器 i18n 文案常量 + 运行时代码，含 `displayConditionParse`/
`runDisplayExpression` 等核心函数）+ 真实样本 `sample.json`。

## 完整性说明

- **full 部分**：数据结构、7 容器、31 控件、dataType、布局、id 命名/唯一/标题红线、条件显示 `#{}` 语法、数据继承三元组——均有 bundle 文案常量/运行时代码 + 真实样本双重佐证。
- **partial 部分**（frontmatter `gaps` 已登记）：`remoteFunc` 脚本绑定的 `scriptValue` 取值路径精确格式、`scriptOutput.dataPath` 语义、`useTaskId` 对应关系，从 minified 代码反推，未用真实带脚本样本校准。编排涉及此处时以实际系统返回为准。
