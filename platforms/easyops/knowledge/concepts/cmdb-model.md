---
name: cmdb-model
kind: concept
module: ''
tags:
- CMDB
- 模型
- objectId
- attrList
- 值类型
- value.type
- enum
- struct
- relation_list
- 跨级关系
- trans_hier_relation_list
- view
- 对象类型
- CI类型
- 资源模型
completeness: partial
gaps:
- 跨级关系query_path确切语法（样例为null，无真实跨级关系样本）
- indexList与*Authorizers确切结构（样例为空[]）
- relation_groups完整字段（仅反推含id/name）
- 命名规则未证实（objectId大写/属性id小写仍属样例归纳，非规则级铁证；relation_id命名规则已由样例逐段吻合+用户确认，见§5.1）
- default_type="series"序列号语义（推断，代码仅见!=="value"判断，无series字样）
- struct_define子项是否固定6字段（样本归纳，前端列定义仅展示4列）
scope:
- 构建/生成单个 CMDB 模型 JSON（生产型需求）
- 问答 CMDB 模型结构（字段类型/关系/跨级关系）
- 编排涉及 CMDB 对象（objectId 是实例所属的"类型 ID"）
- 区分 CMDB 模型 与 ITSM 领域模型（domain_model）—— 二者不同体系
related:
- instance-id（objectId 是实例 instanceId 所属的类型 ID）
- domain_model（ITSM 领域模型，走 flowable_service，关联 standard_field，会 queryCMDBInstance 引用本概念；非同一物）
- standard_field（ITSM 标准字段，与 CMDB 属性是不同体系）
last_verified: '2026-08-03'
---

# CMDB 模型构建 Schema（LLM 构建模型用）

> **⚠️ 概念边界（最重要，勿混淆）**：
> 本概念描述的是 **EasyOps CMDB 平台的「模型」**（对象类型 / CI 类型：objectId、attrList、relation_list、跨级关系），
> 用于建模基础设施资源（主机、网络设备等）。**不是** ITSM 的「领域模型」（`registry/domain_model`，走 `flowable_service`，关联 `standard_field` 标准字段）。
> 二者是两套独立体系：CMDB 模型描述"资源有什么属性/关系"；ITSM 领域模型描述"工单字段模型"并通过 `queryCMDBInstance` 反向查询 CMDB 实例。
> 详见下方 §"与 ITSM 领域模型的区别"。
>
> **事实来源**（无推测，置信度见每节标注与 §10）：
> - 字段结构 / 值类型 / 默认值 / 嵌套形态 —— 全部取自真实模型导出 `concepts/cmdb-model-sample.json`（TESTWWH：15 属性、覆盖 12 种值类型、含 1 条关系）。
> - 字段语义注释 / 约束规则 —— 取自 CMDB「模型管理」前端应用导出 `tmp/bootstrap-mini.81b50da9e84ef1c.json` 内嵌 TS 接口与表单逻辑。
>
> **产物形态**：顶层是一个 JSON 数组，数组每个元素是一个模型对象（即一个"对象类型"）。最小可用产物是 `[{...一个模型...}]`。
>
> **⚠️ 阅读约定**：`✅实测` = 真实样例直接佐证；`✅代码` = 前端 TS 接口/注释原文佐证；`⚠️推断` = 样例归纳或行为反推，非规则级铁证，**构建时勿当确定结论**（已登记 frontmatter `gaps`）。

---

## 0. 速查：最小可用模型骨架

```json
[
  {
    "objectId": "<模型ID>",
    "name": "<模型中文名>",
    "icon": "",
    "category": "<模型分类>",
    "memo": "",
    "protected": false,
    "system": "",
    "notifyDenied": false,
    "view": { "见 §6" },
    "attrList": [ "见 §3 / §4" ],
    "relation_groups": [],
    "relation_list": [],
    "indexList": [],
    "updateAuthorizers": [],
    "deleteAuthorizers": [],
    "readAuthorizers": [],
    "wordIndexDenied": false,
    "isAbstract": false,
    "parentObjectId": "",
    "parentObjectIds": []
  }
]
```

> 注：`_version`、`creator`、`modifier`、`permissionDenied` 为**系统元数据**，新建时通常省略（由后端回填）。下方 §1 列出其形态以备解读既有数据。

---

## 0.1 模型创建接口（前端 vs 后端/脚本）⚠️ 2026-08-03 真调纠正

| 场景 | 接口 | 说明 |
|------|------|------|
| **前端界面**（CMDB 模型管理页） | `model_create`（POST /object）+ `attr_create`（POST /object/{objectId}/attr）+ `relation_create` | 细粒度接口，界面分步操作用。**`model_create` 只建模型骨架（objectId/name/category），不含 attrList**；属性须 `attr_create` 逐个加。不适合脚本/批量建模。 |
| **后端/脚本/批量建模** ⭐推荐 | `model_import`（POST /v2/object_import） | **自行组装完整模型 json**（§0 骨架，含 attrList/view/relation_list，参照 `cmdb-model-sample.json`）一次性导入；导入前可 `model_import_check`（POST /v2/object_import_check）校验。模型导出用 `model_export`（POST /v2/object_export）拿完整 json 作模板。 |

> **铁律**（已踩）：脚本/编排建模默认走 `model_import` 自行组装完整 json，**不要**用 `model_create`+`attr_create`（前端接口；`model_create` 不建属性须 `attr_create` 补，步骤碎易漏；且 `importInstance` 建实例会漏填字段需 PUT 补）。

---

## 1. 模型对象顶层字段（全部字段）

来源：`cmdb-model-sample.json[0]` 实测字段集（共 26 个 key）。✅实测

| 字段 | 类型 | 必填 | 默认/样例 | 说明 | 置信度 |
|---|---|---|---|---|---|
| `objectId` | string | ✅ | `"TESTWWH"` | 模型唯一 ID | ✅实测（存在性）；命名规则⚠️推断 |
| `name` | string | ✅ | `"测试模型"` | 模型显示名 | ✅实测 |
| `icon` | string | | `""` | 图标（旧版字符串，新版用 `view.icon`） | ✅实测 |
| `category` | string | ✅ | `"部署"` | 模型分类（如 部署/网络/中间件） | ✅实测 |
| `memo` | string | | `""` | 备注 | ✅实测 |
| `protected` | bool | | `false` | 是否内置受保护模型 | ✅实测 |
| `system` | string | | `""` | 系统标识 | ✅实测 |
| `notifyDenied` | bool | | `false` | 是否关闭通知 | ✅实测 |
| `view` | object | ✅ | 见 §6 | 视图配置 | ✅实测 |
| `attrList` | array | ✅ | 见 §3 | 属性列表 | ✅实测 |
| `relation_groups` | array | | `[]` | 关系分组定义，见 §5.2 | ✅实测（结构⚠️推断） |
| `relation_list` | array | | `[]` | 关系列表（含左右双向），见 §5.1 | ✅实测 |
| `indexList` | array | | `[]` | 唯一索引/组合索引，见 §7 | ⚠️结构未知 |
| `updateAuthorizers` | array | | `[]` | 更新鉴权 | ⚠️结构未知 |
| `deleteAuthorizers` | array | | `[]` | 删除鉴权 | ⚠️结构未知 |
| `readAuthorizers` | array | | `[]` | 读取鉴权 | ⚠️结构未知 |
| `wordIndexDenied` | bool | | `false` | 是否关闭全文索引 | ✅实测 |
| `isAbstract` | bool | | `false` | 是否抽象模型（被继承、不建实例） | ✅实测 |
| `parentObjectId` | string | | `""` | 父模型 ID（继承场景） | ✅实测（语义⚠️推断） |
| `parentObjectIds` | array | | `[]` | 祖先模型 ID 链 | ✅实测（语义⚠️推断） |
| `_version` | int | 系统回填 | `77` | 版本号，新建不填 | ✅实测 |
| `creator` | string | 系统回填 | `"easyops"` | 创建人，新建不填 | ✅实测 |
| `modifier` | string | 系统回填 | `"easyops"` | 修改人，新建不填 | ✅实测 |
| `permissionDenied` | bool | 系统回填 | `false` | 鉴权快照，新建不填 | ✅实测 |

> **⚠️推断（命名规则，未证实）**：`objectId` "大写字母+数字+下划线" 来自 TESTWWH 单一样例归纳（前端 i18n 有一条 `PATTERN_RULE` 文案匹配，但无法确认归属 objectId）。构建时建议沿用大写，但**不要**据此断言平台一定按此校验。

---

## 2. 属性值类型完整枚举（12 种）

来源：`cmdb-model-sample.json` 的 `value.type` 实测取值 ∪ `bootstrap-mini` 的 `attrValueType` 映射。✅实测 + ✅代码

| `value.type` | 中文 | default 值类型 | 是否用 `regex` | 是否用 `struct_define` | 备注 |
|---|---|---|---|---|---|
| `str` | 字符型 | 字符串 | 可选（正则） | 否 | `mode` 可为 `"default"` / `"password"`（密码以 `*` 展示）✅代码 |
| `int` | 整型 | 数字 | 否 | 否 | |
| `float` | 浮点型 | 数字 | 否 | 否 | |
| `bool` | 布尔型 | `true/false` | 否 | 否 | |
| `date` | 日期 | 日期字符串 | 否 | 否 | |
| `datetime` | 时间 | 时间字符串 | 否 | 否 | |
| `ip` | IP | 字符串 | **是**（IPv4+IPv6 大正则） | 否 | regex 由系统预置，照搬即可 |
| `enum` | 枚举型（单选） | 字符串 | **是**（**JSON 数组字符串**，见 §4.2） | 否 | 单选 |
| `enums` | 多选枚举型 | 字符串数组 | **是**（**JSON 数组字符串**，见 §4.2） | 否 | 多选 |
| `struct` | 结构体（单行） | 对象 | 否 | **是**（子项数组，见 §4.3） | 只可添加一行信息 |
| `structs` | 结构体数组（多行） | 对象数组 | 否 | **是**（子项数组，见 §4.3） | 可添加多行；`mode="attachment"` 时为附件结构 |
| `arr` | 数组 | 数组 | 否 | 否 | 简单值数组 |
| `json` | JSON | 对象 | 否 | 否 | 前端映射表存在（✅代码），`cmdb-model-sample.json` 未含样例 |

> **值类型判定规律**（✅实测）：
> - `regex` 字段：`ip` 放正则；`enum/enums` 放**枚举项 JSON 数组**；其余类型 regex 为 `""` 或 `".*"`。
> - `struct_define` 字段：仅 `struct` / `structs` 非空，其余类型为 `[]`。

---

## 3. 属性结构（`attrList[i]`）

### 3.1 属性顶层字段（每个属性 16 个 key）✅实测

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | string | — | 属性 ID，模型内唯一（命名规则⚠️推断：样例为小写） |
| `name` | string | — | 属性显示名 |
| `protected` | bool | `false` | 是否内置属性 |
| `custom` | **string** | `"true"` | 是否自定义属性。⚠️ **是字符串 `"true"`/`"false"`，不是布尔** |
| `unique` | **string** | `"false"` | 是否唯一。⚠️ 字符串 |
| `readonly` | **string** | `"false"` | 是否只读。⚠️ 字符串 |
| `required` | **string** | `"false"` | 是否必填。⚠️ 字符串 |
| `tag` | array | `["基本信息"]` | 属性分组标签（对应 `view.attr_category_order` 的分组名） |
| `description` | string | `""` | 描述 |
| `tips` | string | `""` | 提示文案 |
| `value` | object | — | 值定义，见 §3.2（**核心**） |
| `wordIndexDenied` | bool | `false` | 该属性是否不进全文索引 |
| `isInherit` | bool | `false` | 是否继承自父模型 |
| `notifyDenied` | bool | `false` | 该属性变更是否不通知 |
| `inheritObjectId` | string | `""` | 继承来源模型 ID |
| `isMetadata` | bool | `false` | 是否元数据属性（系统字段） |

> **⚠️推断（命名规则，未证实）**：属性 `id` "小写字母+数字+下划线" 来自样例归纳（`ip`、`category_type`），无规则文本。

### 3.2 `value` 子字段（所有类型统一 9 个 key）✅实测

无论 `value.type` 是哪种，`value` 对象**结构固定**为下面 9 个字段，差异只在取值：

| 子字段 | 类型 | 默认 | 说明 | 置信度 |
|---|---|---|---|---|
| `type` | string | — | 值类型，见 §2（必填） | ✅实测 |
| `regex` | string | `""` | 正则 / 枚举项 JSON 数组字符串，语义随 type 变，见 §4 | ✅实测 |
| `default_type` | string | `""` | 默认值类型 | ✅实测（`"value"`）；⚠️推断（`"series"` 见下） |
| `default` | any | `null` | 默认值（类型随 `type`；密码模式展示为 `*`） | ✅实测 |
| `struct_define` | array | `[]` | 结构体子项定义，仅 `struct/structs` 非空，见 §4.3 | ✅实测 |
| `mode` | string | `""` | 模式：`""` / `"default"` / `"attachment"` / `"password"` | ✅实测 + ✅代码 |
| `prefix` | string | `""` | 序列号前缀 | ✅实测（语义⚠️推断） |
| `start_value` | int | `0` | 序列号起始值 | ✅实测（语义⚠️推断） |
| `series_number_length` | int | `0` | 序列号位数（不足前补零） | ✅实测（语义⚠️推断） |

> **⚠️推断（default_type="series"，未证实）**：`"value"`=固定值 ✅实测；`"series"`=序列号模式 是从 `prefix/start_value/series_number_length` 字段推断，**前端代码仅见 `default_type !== "value"` 判断，无 `"series"` 字样**。序列号语义本身也属推断。构建序列号属性时需以真实系统为准。

---

## 4. 各值类型填写细则（关键差异，附实测样例）

### 4.1 普通标量类型（str/int/float/bool/date/datetime/ip/arr/json）
`regex` 一般为 `""` 或 `".*"`；`struct_define` 为 `[]`。✅实测
- `str` 实测：`{"type":"str","regex":".*","default_type":"value","default":null,"struct_define":[],"mode":"default",...}`
- `ip` 实测：`regex` 是一长串 IPv4+IPv6 正则（约 1200 字符，由系统预置，照搬即可）。

### 4.2 `enum` / `enums`（枚举）—— ⚠️ `regex` 是 JSON 数组 ✅实测
`regex` 存的是**枚举可选项**，是一个 JSON 数组：

实测 `enum`（单选，`category_type` 属性）：
```json
"regex": ["服务：安全服务", "服务：安装整理", "服务：线路服务", "软件：办公软件", "硬件：办公设备"]
```
实测 `enums`（多选）：
```json
"regex": ["枚举1", "枚举2", "枚举3"]
```
> 即：每个枚举项是一个字符串。`enum` 单选 default 为单个字符串；`enums` 多选 default 为字符串数组。

### 4.3 `struct` / `structs`（结构体）—— `struct_define` 子项 ✅实测
`struct_define` 是数组，每个元素是一个"结构项"。样例中每项含以下字段：

| 子项字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 结构项 ID（如 `attr1`、`url`） |
| `name` | string | 结构项显示名 |
| `type` | string | 该项的值类型（取值集合同 §2，如 `str/int/float`） |
| `regex` | string | 该项的正则/枚举，规则同 §4（可为 `""` 或 `null`） |
| `protected` | bool | 是否内置项 |
| `mode` | string | 模式（`"default"` / `""`） |

> **⚠️推断（子项字段集，未证实完整）**：上表 6 字段来自样例归纳；前端列定义（`bootstrap-mini` 的 `attr-list-table-type-table`）只展示 4 列（`name/id/type/regex`）。**是否还有更多字段无法确认**。

实测 `struct`（`stract` 属性，单行结构体）：
```json
"struct_define": [
  {"id":"attr1","name":"属性1","type":"str","regex":"","protected":false,"mode":"default"},
  {"id":"attr2","name":"属性2","type":"int","regex":"","protected":false,"mode":""}
]
```
实测 `structs`（`file` 属性，多行，`mode="attachment"` 附件）：
```json
"mode": "attachment",
"struct_define": [
  {"id":"name","name":"name","type":"str","regex":"","protected":false,"mode":"default"},
  {"id":"type","name":"type","type":"str","regex":"","protected":false,"mode":"default"},
  {"id":"url", "name":"url", "type":"str","regex":"","protected":false,"mode":"default"},
  {"id":"size","name":"size","type":"float","regex":null,"protected":false,"mode":""}
]
```
> `struct` 与 `structs` 的 `struct_define` 形态完全一致；区别在顶层 `type`（`struct`=单对象、`structs`=对象数组）和 `mode`（附件用 `attachment`）。

---

## 5. 关系

### 5.1 `relation_list` —— 关系定义（含左右双向）✅实测 + ✅代码注释

**来源契约**：`bootstrap-mini` 内嵌 `interface ModelObjectRelation`（含官方注释）。一条关系同时定义"左端视角"和"右端视角"两个方向。

| 字段 | 类型 | 说明（✅代码注释原文/✅实测） |
|---|---|---|
| `relation_id` | string | 关系唯一 ID（命名惯例⚠️推断，见下） |
| `name` | string | 关系名 |
| `protected` | bool | `true`=内置关系 |
| `notifyDenied` | bool | 是否不通知 |
| `isInherit` | bool | 是否继承自父模型 |
| `left_object_id` | string | 左端模型 ID |
| `left_id` | string | 左端视角的关系字段别名 |
| `left_name` | string | 左端视角显示名 |
| `left_description` | string | 左端视角描述 |
| `left_groups` | array | 左端所属关系分组 ID 列表 |
| `left_tags` | array | 左端标签 |
| `left_min` / `left_max` | int | 左端最少/最多关联数；**`-1`=无限多**；✅代码注释："一般情况填 1 或者 -1" |
| `left_required` | bool | 左端是否必选 |
| `leftInheritObjectId` | string | 左端继承来源 |
| `right_object_id` | string | 右端模型 ID |
| `right_id` | string | **✅代码注释原文**：*"关系右端模型中表达左端模型实例的别名字段；如应用的负责人需要在应用的实例中表达出一个字段；对已有模型添加关系时这个 ID 需加下划线前缀避免冲突"* |
| `right_name` | string | 右端视角显示名（与 right_id 对应，仅展示） |
| `right_description` | string | 右端视角描述（与 right_id 相反含义，仅展示） |
| `right_groups` | array | 右端所属关系分组 |
| `right_tags` | array | 右端标签 |
| `right_min` / `right_max` | int | 右端最少/最多关联数；**`-1`=无限多** |
| `right_required` | bool | 右端是否必选 |
| `rightInheritObjectId` | string | 右端继承来源 |
| `_version` | int | 版本号（新建可不填） |
| `attrList` | array | 关系上的扩展属性（一般为 `[]`） |
| `indexList` | array | 关系上的索引（一般为 `[]`） |

> **✅实测（relation_id 命名规则，已确认）**：`<左objectId>_<left_id>_<right_id>_<右objectId>`。
> 样例 `TESTWWH_HOST_TEST_HOST` = `TESTWWH`(左objectId) + `HOST`(left_id) + `TEST`(right_id) + `HOST`(右objectId)，逐段精确吻合；已由用户确认（2026-07-23）。
>
> ⚠️注意：当 `right_id` 带下划线前缀（见上 right_id 冲突规则）时，拼接会出现**连续下划线**——如 `VM_HOST__VM_HOST`（right_id=`_VM`），是规则的自然结果，非错误。

实测样例（`TESTWWH` ↔ `HOST` 双向关联）：
```json
{
  "relation_id": "TESTWWH_HOST_TEST_HOST",
  "name": "", "protected": false, "notifyDenied": false, "isInherit": false,
  "left_object_id": "TESTWWH", "leftInheritObjectId": "",
  "left_id": "HOST", "left_description": "关联测试模型实例", "left_remark": "",
  "left_name": "关联主机", "left_min": 0, "left_max": -1,
  "left_groups": [], "left_tags": [], "left_required": false,
  "right_object_id": "HOST", "rightInheritObjectId": "",
  "right_id": "TEST", "right_description": "关联主机", "right_remark": "",
  "right_name": "关联测试模型实例", "right_min": 0, "right_max": -1,
  "right_groups": [], "right_tags": [], "right_required": false,
  "_version": 1, "attrList": [], "indexList": []
}
```
> ⚠️ 实测比接口契约多了 `left_remark` / `right_remark`（备注），填写时建议一并带上。

### 5.2 `relation_groups` —— 关系分组 ⚠️反推
用于把关系归类展示。`cmdb-model-sample.json` 中为 `[]`（无样例）。结构据 `bootstrap-mini` 处理逻辑 `_.keyBy(modelData.relation_groups, "id")` 与 `.name` 访问**反推**至少含：
```json
{ "id": "<分组ID>", "name": "<分组名>" }
```
> **⚠️反推（未证实完整）**：仅确认有 `id`/`name`，**完整字段集未知**。关系通过 `left_groups` / `right_groups` 引用分组 ID。不分组时填 `[]`，关系 `*_groups` 也填 `[]`。

### 5.3 跨级关系 `trans_hier_relation_list`（⚠️ 挂在 `view` 下，不在 `relation_list`）✅代码

**关键事实**（✅代码）：跨级关系不是普通关系，而是**模型视图层**对"跨多级模型关联路径"的定义，存放在 **`view.trans_hier_relation_list`**。

- 存放位置：`view.trans_hier_relation_list`（数组；`cmdb-model-sample.json` 中为 `null`，即未定义）
- 处理逻辑来源：`bootstrap-mini` 内嵌 TS（`CTX.objectDetail?.view?.trans_hier_relation_list`、`trans_hier_relation_list.forEach(...)`）

每项字段（✅代码，从处理代码读到 `relation.<field>` 访问）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `relation_id` | string | 跨级关系 ID |
| `relation_name` | string | 显示名 |
| `relation_object` | string | 关联的目标模型 ID |
| `groups` | array | 所属关系分组 ID 列表 |
| `tags` | array | 标签 |
| `is_inherit` | bool | 是否继承 |
| `protected` | bool | 是否内置 |
| `query_path` | string | **跨级路径**；✅代码：实例查询键为 `query_path + ".instanceId"` |

> ✅代码：高级模式（`bootstrap-mini` 的 `ADVANCED_MODE_DEFINITION_TIP`）：*"高级模式定义跨级关系路径时支持添加过滤条件"*，配套场景示例组件 `SCENE_EXAMPLE` 与解析器 `event_center.alert_rule@ParseRelationKeys:1.0.0`。
>
> **⚠️待确认（query_path 确切语法）**：`cmdb-model-sample.json` 无真实跨级关系样例（值为 `null`），**`query_path` 的确切语法无法从既有数据确认**——构建跨级关系时需参照目标平台 CMDB 的跨级路径文档，**不要凭空编造语法**。

---

## 6. `view` 视图配置（13 个 key，全部实测）✅实测

| 字段 | 类型 | 默认/样例 | 说明 |
|---|---|---|---|
| `visible` | bool | `true` | 模型是否可见（✅代码注释"是否可见"） |
| `attr_order` | array | `["ip","str",...]` | 属性展示顺序（属性 id 列表） |
| `attr_category_order` | array | `["基本信息"]` | 属性分组顺序（分组名列表，对应属性 `tag`） |
| `hide_columns` | array | `["stracts"]` | 隐藏的属性/关系 id 列表（✅代码注释"设置隐藏属性"） |
| `show_key` | array | `["instanceId"]` | 实例默认显示的主属性 |
| `icon` | object | `{"category":..,"icon":..,"lib":..}` | 模型图标（新版，结构为图标库定义） |
| `image` | string | `""` | 模型图片 |
| `attr_authorizers` | object | `{}` | 属性级鉴权映射 |
| `inherit_attr_category_map` | object/null | `null` | 继承属性分组映射 |
| `relation_default_attr` | any | `null` | 关系默认展示属性 |
| `relation_group_order` | array/null | `null` | 关系分组展示顺序（✅代码注释"关系分组顺序"） |
| `relation_order` | array/null | `null` | 关系展示顺序（✅代码注释"关系分组里关系的顺序"） |
| `trans_hier_relation_list` | array/null | `null` | **跨级关系列表**，见 §5.3 |

> `bootstrap-mini` 内嵌的 `interface ModelObjectView` 是该结构的**子集**（仅 `visible / showHideAttrs / hide_columns / relation_group_order / relation_order`），上表以 `cmdb-model-sample.json` 实测全集为准。

---

## 7. 索引与鉴权（`cmdb-model-sample.json` 中为空，结构未知）⚠️

- `indexList`：唯一索引/组合索引。`cmdb-model-sample.json` 为 `[]`，**无样例，确切结构未知**（前端代码亦无 `indexList` 结构定义）。
- `updateAuthorizers` / `deleteAuthorizers` / `readAuthorizers`：操作鉴权列表，`cmdb-model-sample.json` 均为 `[]`，**无样例，结构未知**。

> **⚠️待确认**：以上三项因无真实样例、前端代码无结构定义，**确切结构未知**。LLM 构建时**留空 `[]`**，**不要编造字段**。需精确结构时从真实系统补样本。

---

## 8. LLM 构建模型 —— 填写约束清单（防错）

来源：✅实测字段类型 + ✅代码官方注释 + ⚠️推断（已标注）。

1. **布尔 vs 字符串陷阱**（✅实测）：属性 `custom / unique / readonly / required` 是**字符串** `"true"`/`"false"`（不是布尔）；`protected / wordIndexDenied / isInherit / notifyDenied / isMetadata` 是**布尔**。
2. **`objectId` 大写、属性 `id` 小写**（⚠️推断：样例归纳，非规则级铁证）。
3. **值类型决定 `value` 取值**（✅实测）：先定 `value.type`，再按 §2/§4 填 `regex`（枚举放 JSON 数组、ip 放正则、其余 `""`）和 `struct_define`（仅 struct/structs 非空）。
4. **`enum/enums` 的 `regex` 是数组**（✅实测）：每项是字符串可选项，不是正则。
5. **关系的 `right_id` 冲突规则**（✅代码注释）：对**已有模型**添加关系时，`right_id` 需加**下划线前缀**避免与既有字段冲突。
6. **`*_max` 语义**（✅代码注释）：`-1` 表示无限多，一般关系填 `1` 或 `-1`。
7. **跨级关系位置**（✅代码）：放 `view.trans_hier_relation_list`，**不要**放进 `relation_list`。
8. **属性分组一致性**（⚠️建议）：属性 `tag` 里的分组名建议能在 `view.attr_category_order` 里找到。
9. **系统字段不填**：`_version / creator / modifier / permissionDenied` 由后端回填。
10. **无样例字段留空**（⚠️待确认）：`indexList / *Authorizers / trans_hier_relation_list` 在无确切格式时留 `[]` / `null`，不编造。

---

## 9. 完整构建示例（参考 `cmdb-model-sample.json` 精简版）

一个含 3 种典型属性（str / enum / struct）+ 1 条关系 + 基本视图的模型：

```json
[
  {
    "objectId": "MY_MODEL",
    "name": "我的模型",
    "icon": "",
    "category": "部署",
    "memo": "LLM 生成示例",
    "protected": false,
    "system": "",
    "notifyDenied": false,
    "view": {
      "visible": true,
      "attr_order": ["name", "level", "profile"],
      "attr_category_order": ["基本信息"],
      "hide_columns": [],
      "show_key": ["instanceId"],
      "icon": {},
      "image": "",
      "attr_authorizers": {},
      "inherit_attr_category_map": null,
      "relation_default_attr": null,
      "relation_group_order": null,
      "relation_order": null,
      "trans_hier_relation_list": null
    },
    "attrList": [
      {
        "id": "name", "name": "名称",
        "protected": false, "custom": "true", "unique": "false",
        "readonly": "false", "required": "true",
        "tag": ["基本信息"], "description": "", "tips": "",
        "value": {
          "type": "str", "regex": ".*", "default_type": "value", "default": null,
          "struct_define": [], "mode": "default", "prefix": "",
          "start_value": 0, "series_number_length": 0
        },
        "wordIndexDenied": false, "isInherit": false,
        "notifyDenied": false, "inheritObjectId": "", "isMetadata": false
      },
      {
        "id": "level", "name": "级别",
        "protected": false, "custom": "true", "unique": "false",
        "readonly": "false", "required": "false",
        "tag": ["基本信息"], "description": "", "tips": "",
        "value": {
          "type": "enum", "regex": ["高", "中", "低"],
          "default_type": "", "default": null,
          "struct_define": [], "mode": "default", "prefix": "",
          "start_value": 0, "series_number_length": 0
        },
        "wordIndexDenied": false, "isInherit": false,
        "notifyDenied": false, "inheritObjectId": "", "isMetadata": false
      },
      {
        "id": "profile", "name": "档案",
        "protected": false, "custom": "true", "unique": "false",
        "readonly": "false", "required": "false",
        "tag": ["基本信息"], "description": "", "tips": "",
        "value": {
          "type": "struct", "regex": "", "default_type": "", "default": null,
          "struct_define": [
            {"id": "owner", "name": "负责人", "type": "str", "regex": "", "protected": false, "mode": "default"}
          ],
          "mode": "", "prefix": "", "start_value": 0, "series_number_length": 0
        },
        "wordIndexDenied": false, "isInherit": false,
        "notifyDenied": false, "inheritObjectId": "", "isMetadata": false
      }
    ],
    "relation_groups": [],
    "relation_list": [
      {
        "relation_id": "MY_MODEL_HOST__MY_HOST",
        "name": "", "protected": false, "notifyDenied": false, "isInherit": false,
        "left_object_id": "MY_MODEL", "leftInheritObjectId": "",
        "left_id": "HOST", "left_description": "关联主机", "left_remark": "",
        "left_name": "关联主机", "left_min": 0, "left_max": -1,
        "left_groups": [], "left_tags": [], "left_required": false,
        "right_object_id": "HOST", "rightInheritObjectId": "",
        "right_id": "_MY", "right_description": "关联我的模型", "right_remark": "",
        "right_name": "关联我的模型", "right_min": 0, "right_max": -1,
        "right_groups": [], "right_tags": [], "right_required": false,
        "_version": 1, "attrList": [], "indexList": []
      }
    ],
    "indexList": [],
    "updateAuthorizers": [],
    "deleteAuthorizers": [],
    "readAuthorizers": [],
    "wordIndexDenied": false,
    "isAbstract": false,
    "parentObjectId": "",
    "parentObjectIds": []
  }
]
```

> 注：`relation_id="MY_MODEL_HOST__MY_HOST"` 按✅实测命名规则 `<左objectId>_<left_id>_<right_id>_<右objectId>` 拼接（因 `right_id="_MY"` 带下划线前缀而出现连续下划线）；`right_id` 下划线前缀沿用✅代码注释的防冲突规则。

---

## 10. 事实置信度汇总（哪些确定、哪些待确认）

| 内容 | 置信度 | 依据 |
|---|---|---|
| 顶层 26 字段、属性 16 字段、value 9 子字段、view 13 字段 | ✅实测 | `cmdb-model-sample.json` 实测全集 |
| 12 种值类型及 regex/struct_define 行为 | ✅实测+✅代码 | 实测 + 前端 `attrValueType` 映射 |
| `enum/enums` 的 regex 是 JSON 数组 | ✅实测 | 实测样例 |
| 关系 `relation_list` 字段集 | ✅实测+✅代码 | 实测样例 + `ModelObjectRelation` 接口 |
| 关系语义注释（`right_id` 下划线前缀、`*_max=-1`） | ✅代码 | 接口 JSDoc 注释原文 |
| 跨级关系**存放位置**（`view.trans_hier_relation_list`）与**字段集** | ✅代码 | 前端处理代码 |
| `mode` 含 `password`/`attachment` | ✅代码+✅实测 | 前端 `=== "password"` 判断 + 附件样例 |
| `relation_id` 命名规则 `<左objectId>_<left_id>_<right_id>_<右objectId>` | ✅实测 | 样例逐段吻合 + 用户确认 |
| `objectId`/属性`id` 命名规则（大写/小写） | ⚠️推断 | 样例归纳，非规则级铁证 |
| `default_type="series"` 序列号语义 | ⚠️推断 | 代码仅见 `!== "value"`，无 series 字样 |
| `struct_define` 子项固定 6 字段 | ⚠️推断 | 样例归纳，前端列定义仅展示 4 列 |
| `relation_groups` 完整字段 | ⚠️反推 | 仅从处理逻辑反推含 `id/name` |
| 跨级关系 `query_path` 确切语法 | ⚠️待确认 | 样例为 `null`，无真实跨级关系样本 |
| `indexList` / `*Authorizers` 结构 | ⚠️待确认 | 样例为空，前端代码无结构定义 |

> **构建铁律**：✅项可直接用；⚠️项构建时可沿用形态但**勿当确定结论**断言平台校验；⚠️待确认项**留空不编造**，需精确值时从真实系统补样本并回填本文件 + 关闭对应 `_gaps.yaml` 条目。


---

## 附：CMDB 模型 与 ITSM 领域模型（domain_model）的区别 ⚠️ 勿混淆

二者是 EasyOps 平台两套独立体系，常被名称"模型"误导：

| 维度 | **CMDB 模型**（本概念） | **ITSM 领域模型**（`registry/domain_model`） |
|---|---|---|
| 所属平台 | EasyOps CMDB（配置管理） | EasyOps ITSM / flowable_service（工单流程） |
| 接口域 | CMDB 资源管理接口 | `/api/flowable_service/v1/domain_model` |
| 描述对象 | 资源/CI 类型（主机、网络设备…）：有什么属性、什么关系 | 工单的字段模型：关联哪些标准字段（standard_field） |
| 核心字段 | `objectId` / `attrList` / `relation_list` / `view.trans_hier_relation_list` | `modelId` / 关联的标准字段集 |
| 标识符 | `objectId`（大写，如 HOST） | `modelId`（走 instanceId 规则，见 `instance-id`） |
| 二者关系 | 被引用方：领域模型通过 `queryCMDBInstance` 查 CMDB 实例 | 引用方：可跨查 CMDB 实例数据 |

**一句话**：CMDB 模型 = "资源长什么样"；ITSM 领域模型 = "工单表单字段怎么组"。本文件只讲前者。
