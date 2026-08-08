---
name: form-schema-v2-dev
kind: module
module: form_development
tags:
- ITSM
- 表单开发
- flowable_service
- form_schema
- formDefinition
- 表单接口契约
- SetFormVersion
- form_data_source
- 数据源
completeness: partial
gaps:
- 未在真实 EasyOps 环境端到端真调验证（表单版本 V2 接口的请求体组织为 flowable_service 源码归纳，非真机实测）
- UpdateFormSchemaVersionV2 对 done 版本「自动新建版本」与草稿「原地更新」的分支行为为源码归纳，未构造两种 state 实测对照
- businessRules 字段服务端原样存储不解析，其前端规则引擎 DSL 具体语法未展开（平台不解析，消费方约定）
- dataSourceIdList 引用数据源后，控件 options.extraProps 中数据源引用的具体 key 由前端约定，服务端不校验，本知识未记录该 key 名
- 权限 action 名（formManagementAccessAction / formManagementCreateAction / formManagementUpdateAction / processDefinitionUpdateAction）为源码归纳，本环境权限配置未核对
last_verified: ''
scope: EasyOps ITSM 表单 schema V2 的开发态接口契约与请求体组织（新建 / 修改表单与版本、节点绑定、数据源）
related:
- modules/form_design/form-design-spec.md      # 表单「设计态」结构规则（formDefinition 合规 + check_form_design.py）
- modules/form_development/form-advanced.md     # 表单「进阶/运行时」（数据继承深化 / 条件显示深化 / 生命周期脚本）
- modules/standard_field/standard-field-types.md  # 标准字段（模型 + 接口 + ITSC_ 前缀规则）
- concepts/order-info.md                        # 表单脚本入参 orderInfo（工单全景）
- registry/form                                 # 表单「运行态」接口卡片（createForm / getFormVersionV2 / setMainVersion 等）
note: 'EasyOps ITSM 表单 schema V2 开发指南：表单版本三接口（SaveFormSchemaV2 / UpdateFormSchemaVersionV2 /
  GetFormSchemaVersionV2）的契约、formDefinition 字段全表（容器 / 控件 / field_kind 枚举 / 派生处理）、流程节点绑定 SetFormVersion、
  表单数据源 form_data_source、端到端示例与 LLM 检查清单。切面定位：本知识描述表单「开发态 / 契约态」（接口字段深层语义 +
  请求体如何组装），与 modules/form_design（设计态 formDefinition 合规规则）、registry/form（运行态接口卡片）三切面互补，
  同名对象不同切面，非重复。标准字段的模型 / 接口归 modules/standard_field（本文件只讲表单如何引用标准字段）。来源：flowable_service
  组件源码整理，未真机端到端核对。'
---

# ITSM 表单开发说明（表单 schema V2 + 节点绑定 + 数据源）

> 面向 LLM 的开发指南。基于 `flowable_service` 组件源码整理。覆盖：
>
> - 表单版本三接口：`GetFormSchemaVersionV2` / `SaveFormSchemaV2` / `UpdateFormSchemaVersionV2`
> - 流程节点绑定表单：`SetFormVersion`
> - 表单数据源：`CreateDataSource` / `UpdateDataSource` / `GetDataSource` / `ListDataSource` / `DeleteDataSource`
>
> 目标：根据客户需求组织请求体，实现 ITSM 工单表单的新建、修改、绑定与配套资源管理。

> 📌 **知识切面**：本文是表单「开发态 / 契约态」知识（接口字段语义 + 请求体组织）。
> 表单「设计态」结构合规规则（formDefinition 怎么写才合规、生产红线、`check_form_design.py`）见
> `modules/form_design/form-design-spec.md`；「运行态」接口卡片见 `registry/form`。
> 表单「进阶 / 运行时行为」（数据继承三种机制 / 条件显示深化 / 表单生命周期脚本）见 `modules/form_development/form-advanced.md`。
> 标准字段的模型 / 接口见 `modules/standard_field/standard-field-types.md`。本文未经真实 EasyOps 环境端到端核对，使用时请结合实际环境验证。

---

## 1. 领域模型

| 层级                            | 概念                                                                                                | 说明                                                                                  |
| ------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| FormSchema（表单）              | 一个表单的元信息：name、category、memo                                                              | 只存元信息，**表单内容全部在版本上**                                            |
| FormSchemaVersion（表单版本）   | 表单的某个版本：versionName、state、**formDefinition（控件定义 JSON 字符串）**、businessRules | 绑定到流程节点时使用版本 ID；通过"主版本"（isMain）标记当前生效版本                   |
| ProcessFormRelation（绑定关系） | 流程版本 × 节点 × 表单版本 的绑定                                                                 | 由`SetFormVersion` 建立；绑定的是**表单主版本**                               |
| StandardField（标准字段）       | 跨表单复用的字段定义（如"申请人"、"标题"）                                                          | 表单控件标记`isstandardfield=true` 时与之关联；支持聚合查询（跨工单按标准字段统计） |
| FormDataSource（数据源）        | 表单级外部数据配置（name + config JSON）                                                            | 版本通过`dataSourceIdList` 引用；供选择类控件/脚本取数                              |
| DomainModel（领域模型）         | 表单字段的数据模型分组                                                                              | 版本通过`domainModelId` 引用                                                        |

**关键规则（源码实证）**：

1. `SaveFormSchemaV2` = **一步完成"建表单 + 建首个版本"**，首个版本自动 `isMain=true`；
2. 版本 `state`：`unfinished`（草稿）/ `done`（完成）；
3. `UpdateFormSchemaVersionV2` 的行为**取决于目标版本当前 state**（重要）：
   - 目标版本是 `done` → **不改它，而是以请求内容新建一个版本**；
   - 目标版本是 `unfinished` → **原地更新该版本**；
4. 版本号查重：当前版本 done、或（草稿但请求改了 versionName）时，`versionName` 与该表单下任何已有版本重复 → 报错 `重复的表单版本号`；
5. `UpdateFormSchemaVersionV2` **同时更新表单元信息**（name/category/memo）；
6. 权限：表单 Get/Save/Update 分别需 `formManagementAccessAction` / `formManagementCreateAction` / `formManagementUpdateAction`；`SetFormVersion` 需 `processDefinitionUpdateAction`。

> 🔗 标准字段的字段模型 / 接口（CreateStandardField / UpdateStandardField / SearchStandardField 等）归 `modules/standard_field/standard-field-types.md`，本文 §5 仅讲表单如何引用标准字段。

---

## 2. 表单版本接口

### 2.1 创建表单 `SaveFormSchemaV2`

```
POST /api/flowable_service/v2/form
Header: org, user, Content-Type: application/json
```

| 字段                 | 类型     | 必填 | 说明                                                                                          |
| -------------------- | -------- | ---- | --------------------------------------------------------------------------------------------- |
| `name`             | string   | 是   | 表单名称                                                                                      |
| `category`         | string   | 是   | 表单分类（分类清单用`list_form_schema_category` 查询）                                      |
| `memo`             | string   | 否   | 表单备注                                                                                      |
| `versionName`      | string   | 是   | 首个版本号，如`1.0.0`                                                                       |
| `state`            | string   | 是   | `unfinished` 草稿 / `done` 完成                                                           |
| `versionMemo`      | string   | 否   | 版本说明（`vMemo` 已废弃）                                                                  |
| `formDefinition`   | string   | 是   | **表单控件定义 JSON 的字符串**（注意是 string 不是 object，需二次序列化），结构详见 §3 |
| `businessRules`    | string   | 否   | 业务规则（字符串，服务端原样存储、随工单读取，平台不解析其结构；通常为前端规则引擎 DSL）      |
| `domainModelId`    | string[] | 否   | 引用的领域模型 instanceId 列表                                                                |
| `dataSourceIdList` | string[] | 否   | 引用的数据源 instanceId 列表（见 §6）                                                        |

返回：表单信息 + `lastestVersion`（新建版本完整信息，含 versionId）。**首个版本自动 isMain=true，无需再设主版本**。

### 2.2 编辑表单 `UpdateFormSchemaVersionV2`

```
PUT /api/flowable_service/v2/form/:formId/version/:versionId
```

| 字段                                     | 必填       | 说明                                                                     |
| ---------------------------------------- | ---------- | ------------------------------------------------------------------------ |
| `formId` / `versionId`               | 是（路径） | 目标表单与版本                                                           |
| `name` / `category` / `memo`       | 否         | **表单元信息，每次调用都会全量更新**——只想改版内容也必须带上原值 |
| `versionName`                          | 否         | 版本号；目标版本 done 时作为新版本号（查重）；草稿时改名也查重           |
| `state`                                | 是         | 保存后状态                                                               |
| `versionMemo`                          | 否         | 版本说明                                                                 |
| `formDefinition`                       | 否         | 全量覆盖                                                                 |
| `businessRules`                        | 否         | 全量覆盖                                                                 |
| `domainModelId` / `dataSourceIdList` | 否         | 全量覆盖（done 版本新建时生效）                                          |

**行为分支（务必理解）**：

```
if 目标版本.state == "done":
    → 以请求内容 CreateFormSchemaVersion（新建版本）
else:  # unfinished 草稿
    → UpdateFormSchemaVersion（原地更新 versionId 指向的版本）
```

> ⚠️ "修改一个已发布表单"的标准做法：直接对它的 done 主版本调 Update（自动生成新版本），再设主（内网：`POST /api/flowable_service/v1/form/{formId}/version/{新versionId}`，直接 POST 到版本 URL）。
> ⚠️ 全量覆盖语义：先 Get 全量、修改、整体回传。

### 2.3 获取表单版本详情 `GetFormSchemaVersionV2`

```
GET /api/flowable_service/v2/form/:formId/version/:versionId
```

响应：

| 字段                                                                                           | 说明                                                                                                           |
| ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `instanceId` / `versionName` / `isMain` / `state` / `memo` / `creator` / `ctime` | 版本元信息                                                                                                     |
| `formDefinition`                                                                             | 表单控件定义 JSON 字符串（与保存时一致）                                                                       |
| `businessRules`                                                                              | 业务规则字符串                                                                                                 |
| `formSchema`                                                                                 | 表单元信息`{instanceId, name, category, creator, memo, ctime}`                                               |
| `domainModel[]`                                                                              | 引用的领域模型详情                                                                                             |
| `standardFields[]`                                                                           | 已选用的标准字段详情（服务端从 formDefinition 提取`isstandardfield=true` 的控件 modelField，回查标准字段库） |
| `formDataSources[]`                                                                          | 已选用的数据源详情                                                                                             |
| `userDisplayMap`                                                                             | 用户名 → 显示名                                                                                               |

---

## 3. formDefinition 详解

> formDefinition 的「设计态合规规则」（容器/控件命名、唯一性、布局、生产红线）见
> `modules/form_design/form-design-spec.md`（配套 `check_form_design.py` 静态校验）。本节聚焦**接口视角的字段全表**（保存时每个字段写什么）。

`formDefinition` 是一个 **JSON 数组的字符串**，顶层是**容器数组**（服务端 `ParseDefinition` 直接 `json.Unmarshal` 到 `[]Container`）。

### 3.1 顶层结构：容器（Container）

```json
[
  {
    "key": "section_base",
    "name": "基本信息",
    "type": "row",
    "propertys": [ {"...控件1..."}, {"...控件2..."} ],
    "tabPanes": [],
    "options": {},
    "extraProps": {},
    "default": {"userTaskId": "", "sectionKey": ""}
  }
]
```

| 字段           | 类型        | 说明                                                                                                                                                                                                                                            |
| -------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `key`        | string      | 容器唯一 key。**表单数据路径 = `容器key.控件modelField`**（如 `section_base.apply_reason`），流程变量、脚本、摘要字段全部用此路径引用                                                                                                 |
| `name`       | string      | 容器显示名（分组标题）                                                                                                                                                                                                                          |
| `type`       | string      | 容器类型：`row`（普通分组）、`tabs`（标签页）、`table`（子表格/明细表，控件值是多行）、`business_table`（CMDB 实例批量写入表）、`business_cmdb_instance_change_table`（CMDB 实例变更表）                                              |
| `propertys`  | Component[] | 容器内的控件数组（注意拼写是`propertys`）。`tabs` 类型时此项为空，控件放在 `tabPanes[].propertys`                                                                                                                                         |
| `tabPanes`   | TabPanes[]  | 仅`tabs` 容器：`[{key, tab(标签名), propertys:[控件]}]`                                                                                                                                                                                     |
| `options`    | object      | 容器级脚本：`listenStart`（是否开启监听）、`listenEvents[]`（值变更监听：`{componentList:[{key,label,value}], remoteFunc:{toolId}}`）、`remoteFunc.onPageLoadId`（数据加载后触发工具）、`remoteFunc.beforeSubmitId`（提交前检查工具） |
| `extraProps` | object      | CMDB 业务表容器专用：`{url, org, user, objectId}`                                                                                                                                                                                             |
| `default`    | object      | 容器继承：`{userTaskId, sectionKey}`，从其他节点的表单继承容器（详见 `form-advanced.md` §1 数据继承）                                                                                                                                         |

> 🔗 容器继承 / CMDB 变更表容器的运行时行为（含继承数据只读、删除标记语义）见 `form-advanced.md` §1.1。

### 3.2 控件（Component）

```json
{
  "key": "input_abc123",
  "label": "申请原因",
  "type": "TEXTAREA",
  "modelField": "apply_reason",
  "belongToSection": "section_base",
  "isstandardfield": false,
  "cmdbProps": {},
  "options": {
    "layout": [24], "labelCol": 6,
    "defaultValue": "", "required": true,
    "placeholder": "请填写申请原因",
    "disabled": false, "enabled": true,
    "highLight": false, "note": "",
    "displayCondition": "", "frontKey": "",
    "rules": [], "extraProps": {},
    "desensitization": false, "dataIndex": "",
    "remoteFunc": {
      "toolId": "", "toolVersionId": "", "modelField": "",
      "scriptInputs": [], "scriptOutput": {"dataPath": "", "showKey": []}
    }
  }
}
```

#### 控件顶层字段

| 字段                | 说明                                                                                                                                                                          |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `key`             | 控件唯一 key（前端渲染用）                                                                                                                                                    |
| `label`           | 控件显示名                                                                                                                                                                    |
| `type`            | **控件类型**，取值见 §3.3（大写枚举）                                                                                                                                  |
| `modelField`      | **字段 key**：formData 中的属性名，未定义时与 key 一致。**同一表单内必须唯一**，路径 `容器key.modelField` 被流程变量/脚本/触发器引用                            |
| `belongToSection` | 所属容器 key（与容器`key` 一致）                                                                                                                                            |
| `isstandardfield` | 是否标准字段（true 时保存后进入版本的 standardFields 引用，见 §5）                                                                                                           |
| `cmdbProps`       | CMDB 控件专用：`{class: "attr"/"relation", type: "str"/"array"/"enum"..., regex: 正则或枚举数组, max: 关系最大数, foreignObjectId: 对端模型ID, foreignMax: 对端关系最大数}` |

#### `options` 常用字段

| 字段                       | 类型               | 说明                                                                                                                                                                                                                                                                                                               |
| -------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `layout` / `labelCol`  | int[] / int        | 布局：24 栅格宽度、label 占位列数                                                                                                                                                                                                                                                                                  |
| `defaultValue`           | any                | 默认值（类型随控件：文本为 string、选择类为`{key,label,value}` 或其数组、开关为 bool）                                                                                                                                                                                                                           |
| `required`               | bool               | 必填                                                                                                                                                                                                                                                                                                               |
| `pattern`                | string             | 校验正则（文本类）                                                                                                                                                                                                                                                                                                 |
| `placeholder` / `note` | string             | 占位提示 / 字段说明                                                                                                                                                                                                                                                                                                |
| `disabled` / `enabled` | bool               | 禁用 / 可见可用                                                                                                                                                                                                                                                                                                    |
| `displayCondition`       | string             | 显示条件表达式（按其他字段值动态显隐；语法见 `form-advanced.md` §2）                                                                                                                                                                                                                                             |
| `desensitization`        | bool               | **数据脱敏**：true 时工单数据落库前该字段被混淆（密码类 INPUT 自动脱敏）                                                                                                                                                                                                                                     |
| `highLight`              | bool               | 高亮（工单详情凸显）                                                                                                                                                                                                                                                                                               |
| `frontKey`               | string 或 string[] | CMDB 实例选择控件的展示字段，分号分隔（如`"name;ip"`）                                                                                                                                                                                                                                                           |
| `dataIndex`              | string             | MODALSELECT（实例选择）取值字段，分号分隔                                                                                                                                                                                                                                                                          |
| `rules`                  | []                 | 前端校验规则数组（原样透传）                                                                                                                                                                                                                                                                                       |
| `extraProps`             | map                | 控件私有属性（日期类的`format`、SELECT 的 `options` 候选、CMDBCASCADER 的 `objectIdPath`、xinput 密码标记等，按控件类型而定）                                                                                                                                                                                |
| `remoteFunc`             | object             | **控件联动脚本**（值变更时调工具库工具）：`toolId`/`toolVersionId` 工具定义；`scriptInputs[]` 入参映射 `{name, scriptType: "static"/"currentNode"/"history", scriptValue(静态值), propertyPath(动态取值路径 a.b), formVersionId(历史数据来源版本)}`；`scriptOutput` 回填 `{dataPath, showKey[]}` |

> 🔗 控件联动脚本 `remoteFunc` 的运行时入参（scriptInputs 的 currentNode/history 取值链路）见 `form-advanced.md` §3.2。

### 3.3 控件类型枚举（field_kind）

> 此枚举同时是 `standard_field` 的 `kind` 取值（见 `modules/standard_field/standard-field-types.md`）。

| type 值                       | 控件                          | 值的形态（formData）                                      |
| ----------------------------- | ----------------------------- | --------------------------------------------------------- |
| `INPUT`                     | 单行文本                      | string                                                    |
| `TEXTAREA`                  | 多行文本                      | string                                                    |
| `RICHTEXT`                  | 富文本                        | string（HTML）                                            |
| `NUMBERINPUT`               | 计数器                        | number                                                    |
| `SLIDER`                    | 滑块                          | number                                                    |
| `RADIO`                     | 单选框组                      | `{key, label, value}`                                   |
| `CHECKBOX`                  | 多选框组                      | `[{key, label, value}]`                                 |
| `SELECT`                    | 下拉选择                      | `{key, label, value}`                                   |
| `MULTIPLESELECT`            | 下拉多选                      | `[{key, label, value}]`                                 |
| `CASCADER`                  | 级联菜单                      | `[{label...}]` 逐级                                     |
| `SWITCH`                    | 开关                          | bool                                                      |
| `UPLOAD`                    | 普通附件                      | `[{fileName, checksum, size, instanceId, workspaceId}]` |
| `LARGEFILE_UPLOAD`          | 超大附件                      | 同 UPLOAD                                                 |
| `COMMONDATE`                | 日期时间选择                  | string（按 extraProps.format 格式化）                     |
| `DATE` / `TIME`           | 日期/时间（前端已隐藏，勿用） | string                                                    |
| `DATERANGE` / `TIMERANGE` | 日期段/时间段                 | `[string, string]`                                      |
| `LINK`                      | 链接                          | `{href: ...}`                                           |
| `ARRATINPUT`                | 数组输入                      | `[string]`                                              |
| `CMDBINSTANCESELECT`        | CMDB 实例选择                 | `[{实例字段...}]`，展示用 frontKey 提取                 |
| `CMDBCASCADER`              | CMDB 级联菜单                 | 逐级实例，配 extraProps.objectIdPath                      |
| `MODALSELECT`               | 实例选择（弹窗）              | 结构列表，dataIndex 指定取值字段                          |
| `USER_SELECTOR`             | 用户选择                      | 用户名                                                    |
| `USER_GROUP_SELECTOR`       | 用户组选择                    | 用户组                                                    |
| `DEPARTMENT_SELECTOR`       | 组织架构选择                  | 部门                                                      |

### 3.4 保存后服务端的派生处理（了解）

- `standardFields`：从 formDefinition 提取 `isstandardfield=true` 的控件 modelField，建立版本与标准字段的引用；
- 脱敏字段：含 `desensitization=true` 或密码 INPUT 的控件，工单数据读取时被混淆（`ConfuseFormPrivacy`），流程版本绑定时 `isDesensitization` 标记由此派生；
- 工具引用：容器脚本（onPageLoadId/beforeSubmitId/listenEvents）与控件 remoteFunc 的 toolId 会被收集用于权限与引用检查。

---

## 4. 流程节点绑定表单 `SetFormVersion`

> 接口：`flowable_service.process_definition_version.set_form_version.SetFormVersion`

```
POST /api/flowable_service/v1/version/:versionId/form_version/:formId
Header: org, user, Content-Type: application/json
Body: {"userTaskId": "Task_apply"}
```

| 参数           | 位置 | 必填 | 说明                                                             |
| -------------- | ---- | ---- | ---------------------------------------------------------------- |
| `versionId`  | 路径 | 是   | **流程定义版本**实例 ID（注意：不是表单版本）              |
| `formId`     | 路径 | 是   | **表单**（FormSchema）实例 ID——**不是表单版本 ID** |
| `userTaskId` | body | 是   | bpmnXML 中的节点 id                                              |

**服务端行为（源码实证）**：

1. 权限：`processDefinitionUpdateAction`；
2. **自动取该表单的当前主版本**（`isMain=true` 的 FormSchemaVersion）作为绑定目标——不能通过此接口指定绑某个非主版本；
3. 解析表单主版本的 formDefinition，派生 `isDesensitization`（是否含脱敏字段）写入绑定关系；
4. 同一 `versionId + userTaskId` 已有绑定 → **更新**为新的主版本绑定（即表单主版本切换后，重新调一次本接口即可让流程节点指向新主版本）；没有 → 新建绑定。

**配套接口**：

| 操作           | 接口                                                         |
| -------------- | ------------------------------------------------------------ |
| 解除某节点绑定 | `delete_form_relation`（删除流程定义版本与表单之间的关系） |
| 查询已绑定节点 | `get_user_task_form_info` / `get_form_user_nodes`        |
| 表单设主版本   | 设主：`POST /api/flowable_service/v1/form/{formId}/version/{versionId}`（内网直连，**直接 POST 到版本 URL，不带 /setMain 后缀**）；网关模式才用 `/setMain` 后缀（详见 `registry/form/setMainVersion`）                     |

**绑定时机建议**：流程版本还为 `unfinished` 草稿时就绑定；绑定关系在 `CreateProcessDefinitionVersionV2` 带 `baseVersionId` 克隆新版本时会按 userTaskId 继承（见 `process_development` §2.2 baseVersionId 克隆）。

---

## 5. 标准字段引用（表单侧）

> 标准字段的**字段模型 / 接口（CRUD + 聚合）/ ITSC_ 前缀规则 / kind 全枚举**归 `modules/standard_field/standard-field-types.md`。
> 本节只讲表单控件如何引用标准字段。

表单控件把 `modelField` 设为标准字段的 `key`（**必须 `ITSC_` 前缀**）且 `isstandardfield=true`，即完成引用：

```json
{
  "key": "c_title",
  "label": "标题",
  "type": "INPUT",
  "modelField": "ITSC_TITLE",
  "isstandardfield": true,
  "belongToSection": "section_base",
  "options": {"required": true, "...": "..."}
}
```

保存表单版本后，服务端自动建立版本 ↔ 标准字段（key=`ITSC_TITLE`）的引用，Get 详情的 `standardFields[]` 可查到。

---

## 6. 表单数据源（form_data_source）

> 用途：给表单提供外部数据配置（如选择类控件的远程候选源、脚本取数配置）。数据源实例被表单版本通过 `dataSourceIdList` 引用，并与表单（FORMS 关系）双向关联。

### 6.1 数据模型

| 字段           | 说明                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------ |
| `name`       | 数据源名称                                                                                                   |
| `config`     | **配置内容（字符串，通常为 JSON）**。服务端原样存储不解析——具体 schema 由消费方（前端控件/脚本）约定 |
| `formIdList` | 关联的表单（FormSchema）instanceId 列表（CMDB`FORMS` 关系）                                                |

### 6.2 接口一览

| 接口                 | 方法 & 路径                                                       | 说明                                                                                                                                 |
| -------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `CreateDataSource` | POST`/api/v1/flowable_service/form_data_source`                 | body：`{name, config, formIdList}`；返回 `instanceId`                                                                            |
| `UpdateDataSource` | PUT`/api/v1/flowable_service/form_data_source/:instanceId`      | body 同创建，**全量覆盖**（name/config/formIdList 都会重写，formIdList 传空 = 解除全部表单关联）                               |
| `GetDataSource`    | GET`/api/v1/flowable_service/form_data_source/:id`              | 详情                                                                                                                                 |
| `ListDataSource`   | GET`/api/v1/flowable_service/form_data_source`（page/pageSize） | 列表                                                                                                                                 |
| `DeleteDataSource` | DELETE`/api/v1/flowable_service/form_data_source/:id`           | **删除保护**：若被超过 1 个表单版本引用（`FORM_VERSION` 关系数 > 1），拒绝删除并报"存在其他表单使用了该数据源，暂不允许删除" |

### 6.3 与表单的挂接方式

1. 先 `CreateDataSource` 拿到数据源 instanceId；
2. 创建/编辑表单版本时在 `dataSourceIdList` 中传入该 instanceId；
3. 表单内需要取数的控件（如 SELECT 远程候选）在其 `options.extraProps` 中配置数据源引用（具体 key 由前端约定，服务端不校验）；
4. Get 表单版本详情时 `formDataSources[]` 返回已引用数据源的完整信息。

---

## 7. 端到端示例

### 7.1 需求

新建"服务器申请表单"（分类：资源申请）：申请原因（多行文本，必填）、服务器数量（计数器，默认 1）、目标环境（下拉：测试/生产，必填）、期望交付日期（日期时间）、申请部门（组织架构）。标题字段复用标准字段 `ITSC_TITLE`。版本 1.0.0 直接发布，并把表单主版本绑到流程版本 `ver_001` 的 `Task_apply` 节点。

### 7.2 formDefinition（JSON 数组，请求时整体转成字符串）

```json
[
  {
    "key": "section_apply",
    "name": "申请信息",
    "type": "row",
    "propertys": [
      {
        "key": "c_title", "label": "标题", "type": "INPUT",
        "modelField": "ITSC_TITLE", "belongToSection": "section_apply",
        "isstandardfield": true, "cmdbProps": {},
        "options": {"layout": [24], "labelCol": 6, "required": true, "placeholder": "一句话说明申请事项", "extraProps": {}, "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      },
      {
        "key": "c_reason", "label": "申请原因", "type": "TEXTAREA",
        "modelField": "apply_reason", "belongToSection": "section_apply",
        "isstandardfield": false, "cmdbProps": {},
        "options": {"layout": [24], "labelCol": 6, "required": true, "placeholder": "请描述用途与规格要求", "extraProps": {}, "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      },
      {
        "key": "c_count", "label": "服务器数量", "type": "NUMBERINPUT",
        "modelField": "server_count", "belongToSection": "section_apply",
        "isstandardfield": false, "cmdbProps": {},
        "options": {"layout": [12], "labelCol": 6, "required": true, "defaultValue": 1, "extraProps": {"min": 1, "max": 100}, "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      },
      {
        "key": "c_env", "label": "目标环境", "type": "SELECT",
        "modelField": "target_env", "belongToSection": "section_apply",
        "isstandardfield": false, "cmdbProps": {},
        "options": {"layout": [12], "labelCol": 6, "required": true,
          "extraProps": {"options": [{"key": "test", "label": "测试", "value": "test"}, {"key": "prod", "label": "生产", "value": "prod"}]},
          "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      },
      {
        "key": "c_date", "label": "期望交付日期", "type": "COMMONDATE",
        "modelField": "expect_date", "belongToSection": "section_apply",
        "isstandardfield": false, "cmdbProps": {},
        "options": {"layout": [12], "labelCol": 6, "required": false, "extraProps": {"format": "YYYY-MM-DD"}, "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      },
      {
        "key": "c_dept", "label": "申请部门", "type": "DEPARTMENT_SELECTOR",
        "modelField": "apply_dept", "belongToSection": "section_apply",
        "isstandardfield": false, "cmdbProps": {},
        "options": {"layout": [12], "labelCol": 6, "required": true, "extraProps": {}, "remoteFunc": {"scriptInputs": [], "scriptOutput": {"showKey": []}}}
      }
    ],
    "tabPanes": [],
    "options": {"listenStart": false, "listenEvents": [], "remoteFunc": {"onPageLoadId": "", "beforeSubmitId": ""}},
    "extraProps": {},
    "default": {"userTaskId": "", "sectionKey": ""}
  }
]
```

### 7.3 调用序列

```bash
# ① 建表单+首版本
POST /api/flowable_service/v2/form
{
  "name": "服务器申请表单", "category": "资源申请", "memo": "",
  "versionName": "1.0.0", "state": "done", "versionMemo": "首次发布",
  "formDefinition": "<上方JSON转义字符串>",
  "businessRules": "", "domainModelId": [], "dataSourceIdList": []
}
# → 返回 formId=form_001, lastestVersion.instanceId=formVer_001（自动 isMain）

# ② 绑定到流程版本 ver_001 的 Task_apply 节点（自动绑表单主版本）
POST /api/flowable_service/v1/version/ver_001/form_version/form_001
{"userTaskId": "Task_apply"}
```

> 🔗 流程版本 `ver_001` 的创建见 `modules/process_development/process-definition-v2-dev.md`。

---

## 8. LLM 组织请求体的检查清单

1. **字段清单确认**：label、类型（映射 §3.3 枚举，大写）、modelField（英文/下划线，表单内唯一；复用标准字段时用其 `ITSC_` key 且 `isstandardfield: true`）、必填、默认值、校验、脱敏（敏感字段务必 `desensitization: true`）；
2. **布局分组**：按业务分组拆 row 容器；明细/多行用 `table`；多页签用 `tabs`（控件放 tabPanes）；
3. **选择类控件**：候选写 `options.extraProps.options`（`{key,label,value}`）；默认值形态与 §3.3 值形态一致（对象或对象数组，不是裸字符串）；
4. **日期类**：统一用 `COMMONDATE`/`DATERANGE`（DATE/TIME 已隐藏），`extraProps.format` 必填；
5. **CMDB 类控件**：CMDBINSTANCESELECT 配 `cmdbProps` + `frontKey`；批量写 CMDB 用 `business_table` 容器；
6. **联动脚本**：字段联动/远程校验用控件 `remoteFunc`（toolId 必须是工具库真实工具定义）；提交前校验、加载初始化用容器 `options.remoteFunc.beforeSubmitId/onPageLoadId`（脚本返回约定见 `form-advanced.md` §3）；
7. **标准字段**：新建时 key 必须 `ITSC_` 前缀且全局唯一（详见 `modules/standard_field`）；引用时控件 `modelField = 标准字段key` 且 `isstandardfield: true`；
8. **数据源**：先建数据源拿 instanceId，再在表单版本 `dataSourceIdList` 引用；删除前确认无多表单引用；
9. **修改已发布表单**：对 done 主版本调 `UpdateFormSchemaVersionV2`（自动生成新版本）→ `set_main_version` 设主；**不要**指望原地改 done 版本；versionName 不能与历史版本重复；
10. **绑定流程节点**：`SetFormVersion` 的 `formId` 是表单 ID 不是版本 ID（自动取主版本）；流程表单改版设主后需重新调一次 SetFormVersion 刷新绑定；克隆流程版本（baseVersionId）会按 userTaskId 继承绑定；
11. **全量覆盖**：表单 name/category/memo/formDefinition/businessRules、数据源的 name/config/formIdList 均为整体替换，先 Get 再改再回传；
12. **常见错误**：formDefinition 传成 object 而非 string；`propertys` 误拼为 `properties`；modelField 重复或含中文/点号；选择类 defaultValue 传裸 value；`belongToSection` 与容器 key 不一致；SetFormVersion 把表单版本 ID 当 formId 传入。
