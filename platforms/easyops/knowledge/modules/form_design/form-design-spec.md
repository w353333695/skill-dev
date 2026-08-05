---
name: form-design-spec
kind: module
module: form_design
tags:
- ITSM
- 表单
- form
- 表单设计
- 控件
- widget
- 容器
- container
- 栅格
- CMDB容器
completeness: full
gaps: []
scope: EasyOps ITSM 流程表单「设计态」——表单 JSON（createForm 的 formDefinition / getFormVersion
  返回值）的结构、容器/控件/布局/联动规则
related:
- concepts/instance-id.md
- modules/form_development/form-schema-v2-dev.md
- modules/form_development/form-advanced.md
- modules/process_design/compliance-rules.md
last_verified: '2026-07-28'
---

# ITSM 表单设计规则（formDefinition 结构）

> 本文是 easyops itsc 平台**表单设计态**的领域知识：流程表单 JSON（即 `createForm` 卡片的 `formDefinition`
> 参数、`getFormVersion`/`getFormVersionV2` 的返回体）在生产/校验时必须满足的结构与配置约束。
> 同目录 `check_form_design.py` 是本规则集的可执行校验器（零依赖，把下述红线从文档变成可跑的检查）；
> `sample.json` 为合规样例，`sample.invalid.json` 为故意违规的反例。
>
> 规则来源（仅溯源）：前端 bundle `tmp/index.9c69d18d.js`（表单设计器 i18n 文案常量 + 运行时代码，
> 含 `displayConditionParse`/`runDisplayExpression` 等核心函数）+ 真实样本。
>
> 切面定位：本模块描述表单**设计态**（formDefinition JSON 的结构规则）；`registry/form` 描述表单
> **运行态**（flowable 的 createForm / getFormVersion / deleteFormVersion 等接口）。同名对象（ITSM 表单）不同切面，非重复。

---

## 一、数据结构总览

一份表单 = **一个 JSON 数组**，每个元素是一个**容器（container）**；容器的 `propertys` 是其下**控件（control）数组**。

```
[                          ← 顶层：容器数组（= formDefinition）
  { 容器1, "propertys": [ {控件}, ... ] },
  { 容器2, "propertys": [ ... ] }
]
```

> 控件不直接出现在顶层；顶层只能是容器。控件挂在某容器的 `propertys` 里，用 `belongToSection` 指回所属容器 key。

### 1.1 容器元素字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | string | 是 | 容器唯一标识，**必须等于 `modelField`**；命名规则见「八.1」 |
| `modelField` | string | 是 | 字段标识，**必须等于 `key`** |
| `name` | string | 是 | 容器标题，≤20 字符，非空/非纯空格 |
| `type` | string | 是 | 容器类型，见「二」（共 7 种） |
| `condition` | boolean | 是 | 是否参与流程条件，布尔（非字符串 `"true"`） |
| `displayCondition` | string | 否 | 显示条件表达式（空串=无条件，语法见「七.1」） |
| `layout` | `[x,y,w,h]` | 是 | 栅格坐标，见「三」 |
| `layoutConfig` | object | 是 | `{"layout":"vertical","columns":12}` |
| `propertys` | array | 是 | 控件数组（可空） |
| `extraProps` | object | CMDB 容器必填 | CMDB 容器放模型配置（见「二.1」） |

### 1.2 控件元素字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | string | 是 | 控件唯一标识，**必须等于 `modelField`** |
| `modelField` | string | 是 | 字段标识，**必须等于 `key`**；命名规则见「八.1」 |
| `label` | string | 是 | 控件标题，≤20 字符，非空/非纯空格 |
| `type` | string | 是 | 控件类型，见「四」（共 31 种） |
| `belongToSection` | string | 是 | 所属容器 `key`（**必须真实存在**） |
| `options` | object | 是 | 控件配置，见「1.3」 |

### 1.3 `options` 公共字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `defaultValue` | any | 默认值，类型随 `dataType`（见各控件） |
| `dataType` | string | 值类型，取值见「四.2」 |
| `required` / `only` / `disabled` / `enabled` | boolean | 必填 / 唯一 / 禁用 / 启用 |
| `isMore` / `highLight` / `desensitization` | boolean | 高级项 / 高亮 / 脱敏 |
| `enableFieldLinkage` | boolean | 启用字段联动 |
| `pattern` / `isEnablePattern` / `patternErrorHint` | string/boolean | 正则表达式 / 是否启用 / 失败提示（见「六.1」） |
| `placeholder` / `note` | string | 占位提示 / 备注（支持 `\n`） |
| `labelCol` / `layout` / `layoutSpan` | number/array | 标签栏宽 / 栅格坐标 / 跨度（见「三」） |
| `displayCondition` | string | 显示条件（见「七.1」） |
| `question` / `rules` | array | 问号提示 / 自定义校验（通常空） |
| `remoteFunc` | object | 绑定脚本（见「七.3」） |
| `extraProps` | object | 控件特有配置（见「五」） |
| `extraProps.fieldAttr` | array | 启用的属性开关，如 `["required","only","disabled"]` |

> `fieldAttr` 决定设计器展示哪些属性开关；`required/only/disabled` 是实际取值，二者应一致。

---

## 二、容器清单（7 种）

| `type` | 名称 | 用途 | 特殊约束 |
|---|---|---|---|
| `row` | 行容器 | 最常用分组容器 | — |
| `table` | table 容器 | 表格分组 | 不支持 CMDB 实例选择多模型 |
| `tabs` | 标签页容器 | 多页签 | 子项在 `tabPanes[].propertys` |
| `inspection_checklist` | 检查清单 | 巡检类 | 不允许自定义构件 |
| `cmdb_instance_operate_container` | CMDB 实例操作容器 | 对实例做操作 | **必须配模型**，见 2.1 |
| `business_table` | CMDB 数据写入容器 | 实例数据写入 | 先选模型；不允许手配/复制/删除/自定义 |
| `business_cmdb_instance_change_table` | CMDB 实例变更容器 | 实例变更 | 不允许手配/复制/删除/自定义 |

### 2.1 CMDB 容器配置（`cmdb_instance_operate_container`）

模型配置在**容器元素**的 `extraProps.cmdbInstanceChangeModel`（容器级 `extraProps`，非控件 `options.extraProps`）：

```jsonc
{ "type": "cmdb_instance_operate_container",
  "extraProps": { "cmdbInstanceChangeModel": {
    "objectId": "HOST@OCP",                       // 必填：CMDB 模型 ID
    "cmdbModifyFields": { "attrIds": ["name","ip"], "relationAttrIds": [] }  // 展示字段
  }}}
```

> 缺 `objectId` → 报「未配置模型ID」；缺 `cmdbModifyFields` → 「未配置展示字段」。

---

## 三、布局系统（12 栏栅格）

- `layout = [x, y, w, h]`：`x` 列起点 / `y` 行序号（同容器内递增）/ `w` 宽度（栏数，`w ≤ columns`）/ `h` 高度（多为 1，富文本等可设 4）。
- 容器 `layoutConfig.columns` = 总分栏数（默认 12）；控件默认 `w=12` 独占一行。
- `labelCol` 标签栏宽（默认 3，TIPS 类为 0）；`layoutSpan` 跨度（默认 12）。

---

## 四、控件清单（31 种）

### 4.1 控件总表

| `type` | 中文名 | 分组 | `dataType` | 默认值形态 |
|---|---|---|---|---|
| `INPUT` | 单行文本 | 输入 | `string` | 字符串 |
| `TEXTAREA` | 多行文本 | 输入 | `string` | 字符串 |
| `NUMBERINPUT` | 计数器 | 输入 | `number` | 数字 |
| `ARRATINPUT` | 数组输入 | 输入 | `stringarray` | `";"` 分隔串 |
| `RICHTEXT` | 富文本 | 输入 | `xml` | HTML 串 |
| `SELECT` | 下拉选择 | 选择 | `object` | 选项 value |
| `MULTIPLESELECT` | 下拉多选 | 选择 | `objectarray` | value 数组 |
| `RADIO` | 单选框组 | 选择 | `object` | 选项 value |
| `CHECKBOX` | 多选框组 | 选择 | `objectarray` | value 数组 |
| `CASCADER` | 级联菜单 | 选择 | `objectarray` | 路径数组 |
| `MODALSELECT` | 实例选择 | 选择 | `objectarray` | 对象数组 |
| `SWITCH` | 开关 | 选择 | `boolean` | `true/false` |
| `SLIDER` | 滑块 | 选择 | `number` | 数字 |
| `COMMONDATE` / `DATE` / `TIME` | 日期时间选择 | 日期 | `moment` | 时刻串 |
| `DATERANGE` / `TIMERANGE` | 日期段 / 时间段 | 日期 | `momentarray` | 起止数组 |
| `USER_SELECTOR` | 用户 | 人员 | `objectarray` | 对象数组 |
| `USER_GROUP_SELECTOR` | 用户组 | 人员 | `objectarray` | 对象数组 |
| `DEPARTMENT_SELECTOR` | 组织架构 | 人员 | `objectarray` | 对象数组 |
| `UPLOAD` | 普通附件 | 附件 | `filearray` | 文件数组 |
| `LARGEFILE_UPLOAD` | 超大附件 | 附件 | `filearray` | 文件数组 |
| `CMDBINSTANCESELECT` | CMDB 实例选择 | CMDB | `objectarray` | 对象数组 |
| `CMDBCASCADER` | CMDB 级联菜单 | CMDB | `string` | 字符串 |
| `CMDB_WRITE_STRUCTS` | 结构体 | CMDB | — | 结构体 |
| `DATAINHERIT` | 数据继承 | 其它 | `string` | 继承值（见「七.2」） |
| `TIPS` | 提示 | 其它 | `string` | 提示文本 |
| `IFRAME` | iframe | 其它 | `string` | — |
| `LINK` | 链接 | 其它 | `link` | — |
| `BUTTON` | 按钮 | 其它 | `button` | — |

### 4.2 `dataType` 全集

`string` · `stringarray` · `number` · `boolean` · `object` · `objectarray` · `moment` · `momentarray` · `xml` · `filearray` · `link` · `button`

> `defaultValue` 类型必须匹配 `dataType`，否则运行期报「数据类型与控件所需类型不匹配」（`DATA_CANNOT_RENDER_TIPS`）。

---

## 五、控件逐项配置（特有 `extraProps`）

> 仅列各控件特有 `options.extraProps`；通用字段见「1.3」。

**输入类**
- `INPUT`：`{isPasswordInput}` 密码框。
- `NUMBERINPUT`：`{numberSetting:{defaultValue,max,min,step}, max, min, step}`；`defaultValue` 必为数字。
- `ARRATINPUT`：`dataType=stringarray`，`defaultValue` 为 `";"` 分隔串。
- `RICHTEXT`：`{showOperationButton}`；`defaultValue` 为 HTML 串。

**选择类**

> ⚠️ **候选字段名按控件类型严格区分，前端无兜底，错位必崩**（源码 `itsc-ticket-center` 的控件渲染器 `Me` 直接 `extraProps.items.map(...)` / `extraProps.options.map(...)`，字段名错或缺失 → `Cannot read properties of undefined (reading 'map')`）：
>
> | 控件 | 候选字段位置 | 项结构 |
> | --- | --- | --- |
> | `SELECT` / `MULTIPLESELECT` / `CHECKBOX` | **`options.extraProps.items`** | `[{key,label,value,style,isDefault}]` |
> | `RADIO` / `CASCADER` | **`options.extraProps.options`** | RADIO 同上项结构；CASCADER 树形 `[{label,value,key,children}]` |
>
> 即：SELECT 类放 `items`、RADIO/CASCADER 类放 `options`——**不可混用**。`dataType`：单选类 `object`、多选类 `objectarray`。
- `MODALSELECT`：`{options:[], listMode}`（候选来自 remoteFunc 脚本，非 extraProps）。
- `SLIDER`：`{max,min,step,numberSetting}`。

**日期类**
- `COMMONDATE`/`DATE`/`TIME`：`{format, disabledPast, presetValue:{type,y,M,d,h,m,s}}`；`format` 必填（TIME 用 `"HH:mm:ss"`）。
- `DATERANGE`/`TIMERANGE`：`{format, disabledPast}`。

**人员类**（`USER_SELECTOR`/`USER_GROUP_SELECTOR`/`DEPARTMENT_SELECTOR`）
- `{objectId}`：`USER` / `USER_GROUP` / `ORGANIZATION@EASYOPS`。

**附件类**（`UPLOAD`/`LARGEFILE_UPLOAD`）
- `{buttonText, max_number, max_size, isEnableFileTypeLimit, fileType}`。

**CMDB 类**
- `CMDBINSTANCESELECT`：`{objectId, listMode, advancedPreQuery:{objectId,instances:{type,query}}}`。
- `CMDBCASCADER`：`{objectIdPath:[{objectId, showKey}]}`（按模型关联路径逐级下钻）。
- `CMDB_WRITE_STRUCTS`：围绕模型结构体 `structs` 配置。

**其它**
- `TIPS`：`{textHighLight, visibleIcon, offsetLeft, offsetRight}`；`labelCol` 常为 0。
- `IFRAME`：`{url, width, height}`；`url` 必填。
- `LINK`：`{label, href}`；`href` 必填。
- `BUTTON`：`{size, type, shape, buttonText}`。

---

## 六、通用配置规则

### 6.1 正则校验
- `isEnablePattern=true` → `pattern` 必填（合法正则）+ `patternErrorHint` 必填（失败提示）。
- `isEnablePattern=false` 时 `pattern` 不生效；ARRATINPUT 等数组类正则作用于每个元素。

### 6.2 默认值
- 类型须匹配 `dataType`；日期类须符合 `format`；选择类须存在于选项 `value` 集合（或 `isDefault:true`）。

### 6.3 字段联动 / 容器显示条件
- `enableFieldLinkage=true` 时用 `displayCondition`/`remoteFunc` 配置联动。
- 容器 `condition` 必为布尔；`displayCondition` 空串=无条件，非空用「七.1」求值。

---

## 七、高级特性指针（条件显示 / 数据继承 / 绑定脚本）

> 本模块聚焦 formDefinition 的**设计态结构合规规则**（§一~§六 + §八生产红线）。下列高级特性的**接口契约 / 字段语义 / 运行时行为**
> 已按切面归到 `form_development` 模块，本文只留**速查指针**，避免重复——编排时按需跳转：

| 高级特性 | 设计态速查（本文） | 完整知识（跳转） |
| --- | --- | --- |
| **条件显示** `displayCondition` | 占位符 `#{sectionKey[rowIndex].modelField}`，JS 表达式求值返布尔；跨节点联动用 `options.displayUserTaskId` | `modules/form_development/form-advanced.md` §2（两种配置位置 / 表达式语法 AND/OR 规则 / 特殊值 `""`/`"-"` / 动态 formConfig 改写） |
| **数据继承** `DATAINHERIT` | 控件级运行时自动从来源取值回填（`default.{userTaskId,sectionKey,modelField}`），用户不能填；常配 `options.hidden:true` 做数据搬运 | `modules/form_development/form-advanced.md` §1（容器继承 / 父子工单 / 工单转换三种机制，别混淆） |
| **绑定脚本** `remoteFunc` | 选择类控件 `options.remoteFunc` = `{toolId, scriptInputs[], scriptOutput}`；脚本返回须 JSON 字符串且 `JSON.parse` 后为数组，否则报 `TOOL_RETURN_DATA_STRUCTURE_INVALID` | `modules/form_development/form-advanced.md` §3（表单生命周期脚本：afterDataLoad/preSubmitCheck/onValueChange/componentLoad 事件 / 入参 / 返回约定 / formConfig 动态改写 / 执行链路） |

> ⚠️ §7.3 旧注（`scriptValue` 取值路径、`scriptOutput.dataPath`、`useTaskId` 对应关系从 minified 代码反推、未校准）——这些**控件联动脚本入参**的
> 精确语义在 `form_development/form-advanced.md` §3.2（控件联动脚本 `scriptInputs` 的 static/currentNode/history 三种来源）有更完整描述，
> 编排涉及此处时以该文档 + 实际系统返回为准。

> 🔔 **流程节点前后置脚本**（nodeSettings.scriptSettings，节点 done/reject 时触发）不是表单脚本，归
> `modules/process_development/process-definition-v2-dev.md` §4.2（配置态）+ §4.4（编写态），与表单事件脚本区分。

---

## 八、生产红线（对应 `check_form_design.py` 规则）

> 设计期硬性 schema 约束，违反即被校验器判为 error/warn。

### 8.1 标识命名（`id-invalid` · error）
容器 `key`、控件 `key`/`modelField`：**不能纯数字，不能含 `@ _` 外特殊字符**（只允许字母/数字/`@`/`_`，且至少一个非数字）。

### 8.2 唯一性（error）
`field-id-duplicate`（控件 `modelField` 全表唯一）/ `container-id-duplicate`（容器 `key` 唯一）/ `*-id-empty`（非空）。

### 8.3 标题（error）
控件 `label`、容器 `name`：非空、非纯空格、≤20 字符。

### 8.4 引用完整性（error / warn）
`belong-disconnected`（`belongToSection` 须指向真实存在的容器）/ `belong-missing`（应填 `belongToSection`）。

### 8.5 正则配置完整性（error / warn）
`pattern-enabled-but-empty` / `pattern-hint-missing` / `pattern-without-flag`。

### 8.6 布局（error / warn）
`layout-malformed`（`layout` 须为 4 数字）/ `layout-width-exceed`（控件 `w` ≤ 容器 `columns`）。

### 8.7 CMDB 容器（error / warn）
`cmdb-operate-no-model`（须配 `objectId`）/ `cmdb-operate-no-show-fields`（须配 `cmdbModifyFields`）。

### 8.8 一致性 / 类型（warn / error）
`modelfield-key-mismatch`（`modelField==key`）/ `condition-boolean`（`condition` 须布尔）/ `unknown-container-type` / `unknown-control-type`（类型须在清单内）。

---

## 八.五、前端渲染必需字段（⚠️ 校验器盲区，2026-07-28 真调补）

> **`check_form_design.py` 通过 ≠ 前端能渲染**。设计态校验查 schema 合规（命名/唯一/引用），但前端渲染器（`itsc-ticket-center` 的 `Ht`/`ge`/`Fe`/`Me` 函数）对若干字段**直接 `.map` / 下标读，无 `||[]` 兜底**，缺失即崩（报错 `Cannot read properties of undefined (reading 'map')`）。本节列已实测确认的崩点字段，构造 formDefinition 时**必须齐全**（参照 `sample.json`）。

### 容器级（每类容器）

| 字段 | 必填 | 说明 / 崩点 |
| --- | --- | --- |
| `layout` `[x,y,w,h]` | **是** | 前端按 `container.layout[1]` 对容器排序（无兜底）。缺 → 崩 |
| `layoutConfig` `{layout:"vertical",columns:12}` | **是** | 栅格分栏配置 |
| `modelField` | 是 | 一般 = `key` |
| `condition` bool | 是 | 是否参与流程条件 |
| `displayCondition` string | 是 | 显示条件（空串=无条件） |
| `propertys` [] | **是**（含 TABLE/BUSINESS_TABLE） | 控件数组；`TABLE`/`BUSINESS_TABLE` 在 `Ut.b` 归一化前就被 `Ft.a`/`Ut.a` 遍历，缺 propertys → 崩（即便空也要 `[]`） |
| `tabPanes` | 仅 `tabs` | tabs 容器必填（每 pane 含 `propertys`/`tab`/`key`） |
| `extraProps.cmdbInstanceChangeModel` | 仅 cmdb 操作容器 | 含 `objectId` |

> ⚠️ **row 容器不要带 `options`/`tabPanes`/`extraProps`**（sample row 容器没有，带多余字段也可能触发前端异常分支）。继承容器才带 `default:{userTaskId,sectionKey}`。

### 控件级（每个控件 `options`）

| 字段 | 必填 | 崩点 |
| --- | --- | --- |
| `options` 对象 | **是** | 前端直接读 `options.highLight/note/required/...`（无 `?.`）。缺 options → 崩 |
| `options.layout` `[x,y,w,h]` | **是** | 前端按 `layout[2]`/`layout[3]` 算宽高（无兜底）。缺 → 崩 |
| `options.layoutSpan` / `labelCol` | 是 | 栅格布局 |
| `options.rules` [] | 是 | 前端 `rules.map`（无兜底） |
| `options.question` [] | 是 | 问号提示 |
| `options.remoteFunc` `{toolId,scriptInputs}` | 是 | `scriptInputs` 是数组；`scriptOutput` 仅 MODALSELECT 需要 |
| `options.extraProps.items` | SELECT/MULTIPLESELECT/CHECKBOX | **候选必须放 items**（见 §五，前端 `items.map` 无兜底） |
| `options.extraProps.options` | RADIO/CASCADER | 候选放 options |
| `options.dataIndex` string | 选择类/附件 | 字符串（`;` 分隔），`.split(';')` |
| `options.frontKey` **数组** | CMDB/实例选择类 | 前端 `frontKey.map`/`filter`，**必须是数组**（不能是字符串） |

### 已知校验器盲区（check_form_design.py 已补 / 待补）

| 崩点字段 | 校验规则 | 状态 |
| --- | --- | --- |
| SELECT 类候选放 `items` / RADIO 类放 `options` | `select-candidate-field` (error) | ✅ 已加（2026-07-28） |
| 容器顶层 `layout` 必填 | `container-layout-required` (error) | ✅ 已加 |
| 控件 `options.layout` 必填 | `control-layout-required` (error) | ✅ 已加 |
| 控件 `options` 本身缺失 | 待补 | ⏳ |
| TABLE/BUSINESS_TABLE `propertys` 缺失 | 待补 | ⏳ |
| `frontKey` 必须是数组 | 待补 | ⏳ |

> 排查方法：前端崩 `.map` 时，对照本节表查哪个数组字段缺失；或读 `itsc-ticket-center/dist/index.*.js` 的 `Me`（控件渲染器）/`Fe`（行渲染器）函数定位无兜底 `.map`。

---

## 九、与卡片的关系（编排视角）

| 卡片（`registry/form`） | 与本知识的关系 |
|---|---|
| `createForm` | 其 `request.required.formDefinition` **即本文描述的表单 JSON 数组**；生产表单时按本规则构造，可用 `check_form_design.py` 预检 |
| `getFormVersion` / `getFormVersionV2` | 返回体的 formDefinition 即本结构；解析/校验返回表单时对照本文 |
| `getFormSchemaCategory` | 表单分类（与表单结构正交） |
| `deleteFormVersion` | 按版本删除（不涉及结构） |

> 典型编排：`getFormVersionV2` 拉某表单 → `check_form_design.py` 离线校验其 formDefinition 合规性 → 必要时改后 `createForm` 新版本提交。
