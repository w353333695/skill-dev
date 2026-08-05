---
name: standard-field-types
kind: module
module: standard_field
tags:
- 标准字段
- standard_field
- 字段类型
- kind
- sourceConfig
- ITSC_前缀
- 跨表单复用
completeness: partial
gaps:
- 各 kind 的 sourceConfig 专属 options.extraProps 配置（如 SELECT 的候选、DATE 的 format）复用表单控件结构，未逐
  kind 列出（见 form_development §3.2/§3.3，按控件类型而定）
- sourceType 枚举仅知 customize（自定义），其他取值（如内置/系统）未核对
- fileCfgResource（文件类字段配置资源）的具体结构未展开
- 未以真实标准字段实例端到端验证（字段模型/接口为 flowable_service 源码 + 领域模型 openapi 归纳，非真机实测）
last_verified: ''
scope: ITSM 标准字段（跨表单/跨工单复用字段）的字段模型、kind 枚举、sourceConfig 结构、CRUD + 聚合接口、表单引用方式
related:
- modules/form_development/form-schema-v2-dev.md
- concepts/instance-id.md
- registry/standard_field
note: ITSM 标准字段（跨表单/跨工单复用的统一字段，如标题/申请人/优先级）知识：字段模型（key 必须 ITSC_ 前缀、全局唯一）、 kind 枚举（取值同表单控件
  field_kind）、sourceConfig（= 控件定义 JSON 模板）、CRUD + 聚合接口、在表单中引用的方式。 切面定位：本知识描述标准字段「模型/契约」，registry/standard_field
  描述「运行态」接口卡片；field_kind 完整枚举的单一真相源在 modules/form_development/form-schema-v2-dev.md
  §3.3（标准字段 kind 取值同控件 type）。来源：flowable_service 源码 + 领域模型 openapi StandardFieldDetail
  归纳，未真机实测。
---

# 标准字段类型与配置（standard-field-types）

> ITSM 标准字段：跨表单/跨工单复用的统一字段（如"标题"、"申请人"、"优先级"）。表单控件把 `modelField` 设为标准字段的 `key`
> 且 `isstandardfield=true` 即完成引用；之后可用聚合接口跨工单按标准字段统计。
>
> 📌 **切面**：本文是标准字段「模型/契约」知识。表单如何引用标准字段见 `modules/form_development/form-schema-v2-dev.md` §5；
> 运行态接口卡片见 `registry/standard_field`（createStandardField / searchStandardField 等）。

## 一、字段模型

> 来源：领域模型 openapi StandardFieldDetail（已确认）+ flowable_service 源码（接口行为）。

| 字段                        | 说明                                                                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `instanceId`              | 字段实例 ID（12 位 hex，见 `concepts/instance-id.md`）                                                                                     |
| `key`                     | 标准字段唯一标识，**必须以 `ITSC_` 开头**（服务端强校验，否则报错"请使用前缀 ITSC_"）；**全局唯一**，重复创建报"唯一标识已存在" |
| `name`                    | 字段标题（显示名）                                                                                                                          |
| `kind`                    | 控件类型，取值同表单控件 `field_kind` 枚举（`INPUT`/`SELECT`/`USER_SELECTOR`/...，完整列表见 `modules/form_development/form-schema-v2-dev.md` §3.3） |
| `sourceType`              | 来源类型，自定义为 `customize`（其他取值待核，见 gaps）                                                                                   |
| `sourceConfig`            | **字符串化的控件定义 JSON**（结构 ≈ 表单控件对象：`key/modelField/label/type/options{...}`），作为该标准字段拖入表单时的默认控件模板（详见 §三） |
| `default`                 | 默认值                                                                                                                                      |
| `desc`                    | 描述                                                                                                                                        |
| `required` / `readonly` | 必填 / 只读                                                                                                                                 |
| `domainModelIds`          | 关联的领域模型 instanceId 列表                                                                                                              |
| `fileCfgResource`         | 文件配置资源（文件类字段用，结构未展开）                                                                                                    |
| `domainModels`            | 引用该字段的领域模型列表（读取时回填）                                                                                                      |

## 二、kind 字段类型枚举

`kind` 取值**同表单控件的 `field_kind`**（标准字段本质是"可复用的控件定义模板"）。完整枚举见
`modules/form_development/form-schema-v2-dev.md` §3.3，常见值：

| kind | 控件 | 值形态 |
| --- | --- | --- |
| `INPUT` / `TEXTAREA` / `RICHTEXT` | 文本类 | string |
| `NUMBERINPUT` / `SLIDER` | 数字类 | number |
| `RADIO` / `SELECT` | 单选类 | `{key,label,value}` |
| `CHECKBOX` / `MULTIPLESELECT` | 多选类 | `[{key,label,value}]` |
| `COMMONDATE` / `DATERANGE` | 日期类 | string / `[string,string]` |
| `USER_SELECTOR` / `USER_GROUP_SELECTOR` / `DEPARTMENT_SELECTOR` | 人员/组织类 | 用户名/用户组/部门 |
| `CMDBINSTANCESELECT` / `CMDBCASCADER` / `MODALSELECT` | CMDB/实例选择类 | 实例结构 |
| `SWITCH` | 开关 | bool |
| `UPLOAD` / `LARGEFILE_UPLOAD` | 附件类 | `[{fileName,...}]` |

> 完整 24 种枚举 + 各控件 `options.extraProps` 专属配置见 `form_development` §3.2/§3.3。

## 三、sourceConfig 配置结构

`sourceConfig` 在契约里 `type=string`，实际是 **JSON 字符串**，结构 = **表单控件定义对象**（标准字段拖入表单时作为默认控件模板）：

```jsonc
{
  "key": "ITSC_TITLE",          // = 标准字段 key
  "modelField": "ITSC_TITLE",   // = 标准字段 key（拖入表单后即控件 modelField）
  "label": "标题",
  "type": "INPUT",              // = kind
  "options": {
    "required": true,
    "placeholder": "...",
    "defaultValue": "",
    "extraProps": { "...": "按控件类型而定（同表单控件）" }
  }
}
```

**结构规则**：

- 通用字段（所有 kind）：`key` / `modelField` / `label` / `type` / `options.required` / `options.placeholder` / `options.defaultValue`；
- 各 kind 专属配置 = 该控件类型的 `options.extraProps`（如 `SELECT` 的 `options` 候选、`COMMONDATE` 的 `format`、`CMDBINSTANCESELECT` 的 `cmdbProps`），**与表单控件完全一致**——详见 `form_development` §3.2 控件 `options` 字段表 + §3.3 各控件类型。

> 即：sourceConfig 的结构问题 = 表单控件的结构问题，没有独立 schema。写标准字段 sourceConfig 时，按"它是个什么控件"对照 `form_development` §3.2 构造即可。

## 四、接口一览

> 运行态卡片见 `registry/standard_field`（createStandardField / updateStandardField / getStandardField / searchStandardField / deleteStandardField）。

| 接口                           | 方法 & 路径                                                | 说明                                                                                                                                 |
| ------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `CreateStandardField`        | POST`/api/flowable_service/v1/standard_field`            | 创建。body 即 §一字段；返回`instanceId`                                                                                         |
| `UpdateStandardField`        | PUT`/api/flowable_service/v1/standard_field/:instanceId` | 更新。**注意：`domainModelIds` 必传**（传空数组 = 解除所有领域模型关联）；key/kind/sourceType 变更会触发与已有字段的冲突检查 |
| `GetStandardField`           | GET`/api/flowable_service/v1/standard_field/:instanceId` | 详情                                                                                                                                 |
| `SearchStandardField`        | POST`/api/flowable_service/v1/standard_field/_search`    | 查询。参数：`page`/`pageSize`/`Q`（模糊）/`key`（精确）/`keyList`（批量）/`withSource`（是否带数据源信息）               |
| `DeleteStandardField`        | DELETE（instanceId 支持`;` 分隔批量）                    | **内置标准字段不允许删除**（`CheckBuiltin` 拦截）                                                                            |
| `CheckCanSave`               | `check_can_save`                                         | 表单设计器里"另存为标准字段"前的校验，返回`canCreate`/`canUpdate`/`updateId`                                                   |
| `SearchSourceDataFromConfig` | `search_source_data_form_config`                         | 从配置文件取标准字段源数据                                                                                                           |
| `AggregateStandardFieldData` | `aggregate_standard_field_data`                          | 跨工单按标准字段聚合统计（报表用）                                                                                                   |

## 五、在表单中引用标准字段

表单控件把 `modelField` 设为标准字段的 `key`（**`ITSC_` 前缀**）且 `isstandardfield=true`：

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

保存表单版本后，服务端自动建立版本 ↔ 标准字段（key=`ITSC_TITLE`）的引用，Get 表单版本详情的 `standardFields[]` 可查到。

> 详细引用规则见 `modules/form_development/form-schema-v2-dev.md` §5。

## 六、消费场景

1. **注册标准字段卡片**：LLM 读此文件，给 `searchStandardField`/`createStandardField` 卡片的 request 字段补约束（kind 枚举、sourceConfig 结构、ITSC_ 前缀）；
2. **编排创建标准字段**：LLM 据此填 sourceConfig（按 kind 选对的控件模板，对照 `form_development` §3.2）；
3. **表单引用标准字段**：控件 `modelField = 标准字段key`（`ITSC_` 前缀）+ `isstandardfield=true`；
4. **领域模型关联字段**：domain_model 的 standardFieldIds 引用的是这里的 instanceId。

## 七、来源与待补

- **已确认**：字段模型（领域模型 openapi StandardFieldDetail）、kind 枚举（同表单控件）、sourceConfig 结构（= 控件定义）、接口路径与行为（flowable_service 源码）。
- **待补（见 frontmatter gaps）**：sourceType 完整枚举、fileCfgResource 结构、各 kind sourceConfig 专属 extraProps（复用表单控件，未逐 kind 列）、真机端到端验证。
