# EasyOps CMDB —— api-cli 清单（platforms/demo）

`easyops-cmdb.yaml` 是 EasyOps CMDB 的 api-cli 集中清单，覆盖**三层体系**：模型(object)、关系(relation)、实例(instance)。由 `data/scenarios/cmdb-object.md` 的 onboarding 需求生成。

- **数据来源**：契约 `data/api-doc/cmdb-object.json`（4 个 EAML 契约）+ 后端 `data/sources/backend/CMDB/cmdb_service/object/route.go`（补全契约缺失的删除/详情/属性/关系 CRUD）。
- **调用**：`scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml <resource> <verb> [args]`。写操作先 `--dry-run`/`--print-curl` 预览。

## 接入面与鉴权

| 接入面 | base_url | 用途 |
|---|---|---|
| **backend**（默认） | `http://172.30.0.90:8079` | 直连 cmdb_service。object 域所有 verb 干净命中（无 per-API 网关前缀）。**模型管理走这里。** |
| frontend | `https://172.30.0.90` | 前端网关。网关按每个 API 路由（path_prefix 随 verb 变），一个 endpoint 只能持一个前缀，故仅 `object_instance.search` 通用。 |

两者均用 `auth: easyops-cookie`（`~/.api-cli/auth.d/easyops-cookie.yaml`，`provider: cookie`，持 `PHPSESSID`）。环境变量：`EASYOPS_CMDB_BACKEND_URL` / `EASYOPS_CMDB_FRONTEND_URL`。

## 资源总览

| 资源 | verb | 后端路由 | 说明 |
|---|---|---|---|
| `object_model` | `list` | `GET /object_basic` | 模型基本信息列表（q/category/objectIds 过滤，分页） |
| | `detail` | `GET /object/{object_id}` | 单模型完整详情（属性/关系/视图/索引） |
| | `delete` | `DELETE /object/{object_id}?forceDelete=` | 删除模型 |
| | `import` | `POST /v2/object_import` | **声明式建/改模型（upsert）** |
| | `import_check` | `POST /v2/object_import_check` | 导入预检（dry-run） |
| | `export` | `POST /v2/object_export` | 按 ID 批量导出完整定义 |
| `object_attr` | `create/read/update/delete` | `/object/{object_id}/attr[/{attr_id}]` | 属性细粒度 CRUD |
| `object_relation` | `list/create/read/update/delete` | `/object_relation[/{relation_id}]` | 关系细粒度 CRUD |
| `object_instance` | `search` | `POST /v3/object/{object_id}/instance/_search` | 实例搜索（MongoDB 风格 query） |

## 模型设计知识（CmdbObject / message.Response）

EasyOps 的「模型」是一个完整定义，**通过 `object_model.import` 一次性声明**（upsert：存在则更新）。五大设计要素：

```
CmdbObject {
  objectId*        模型 ID，约定 NAME@NAMESPACE（如 OCEANBASE@EASYOPS）。无正则，仅非空。
  name*            模型名（同命名空间不可重复）
  category         分类，点分多级（如「应用资源.数据库」）
  protected        受保护(核心)模型，true 不可删
  view             视图/布局：attr_category_order / attr_order / show_key / visible
  attrList*        属性列表（≥1）—— 见下
  relation_list    关系列表 —— 见下
  relation_groups  关系分组
  indexList        索引：{ name, propertyIds[], unique }
  *Authorizers     update/delete/read 权限白名单
}
```

**属性 Property（attrList 项）**：`id*` / `name*` / `value*` + `unique/readonly/required`（字符串 "true"/"false"）/ `tag`（分组标签）/ `description`/`tips`。
> 给**已存在**模型新增属性时，新属性 `id` 加 `_` 前缀（如 `_regulatory_level`）标识为新增。

**属性值 value**（核心）：
- `type*`：`int|enum|str|arr|date|datetime|struct|structs|ip|bool|float|json|enums|attachment`（`FK/FKs` 已弃用）。`enum`=单选、`enums`=多选。
- `regex`：`enum/enums` 时是**枚举值数组**（如 `["一级","二级"]`）；`json` 时是 JSON schema；其余是正则。
- `default_type`：`value|function|auto-increment-id|series-number`；`series-number`/`auto-increment-id` 须配 `prefix`。
- `struct_define`：`struct/structs` 类型的子字段定义（`id/name/type/regex`）。

**关系 Relation（relation_list 项）**：一条关系连两端模型，各持 `object_id` / `id`（对端 ID）/ `description` / `min` / `max`。
- 必填：`left_object_id/left_id/left_description` 与 `right_*` 三组。
- **正则约束**：`left_id`/`right_id`/`relation_groups.id` = `^[0-9a-zA-Z_]{1,32}$`。
- `left_id == right_id` 禁止；同批关系 id/名称不可重复。
- `*_max = -1` 表无限（一对多）；`1` 表一对一。
- 关系对端模型须已存在或在同批导入内（否则 `ignore_dst_relation: true`）。

**导入校验约束**（validator + service 两层）：`object_list` 必填；每模型 `objectId/name/attrList(≥1)` 必填；每属性 `id/name/value` 必填；同请求模型 ID/名称不可重复；索引引用的属性须存在（仅更新已有模型时校验）。导入返回逐模型/逐属性/逐关系的 `code/message`（`code=0` 成功）。

## e2e 场景覆盖（data/scenarios/cmdb-object.md）

| 场景 | 用什么 verb | 要点 |
|---|---|---|
| ① 查「IT资源监控」相关模型 | `object_model list --q "IT资源监控"` | 关键词模糊匹配 id/name |
| ② 建 oceanbase 模型（属性+关系：运维负责人/部署主机） | `object_model import --body-file oceanbase.json` | 一次声明 objectId/attrList/relation_list；`import_check` 先预检 |
| ③ 给 oceanbase 加分类属性（监管等级/服务时间） | `object_model import`（重导含新属性的完整模型）或 `object_attr create` | 新属性 id 加 `_` 前缀；枚举值放 `value.regex` 数组 |
| ④ 删除 oceanbase 模型 | `object_model delete "OCEANBASE@EASYOPS"` | protected 模型须 `--forceDelete` |

**验收 URL**：模型列表 `http://172.30.0.90/next/cmdb-model-management?...`；模型详情 `.../object/{objectId}/detail`。

## 示例：建 oceanbase 模型

```bash
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model import_check \
  --body-file tmp/onboarding-cmdb/oceanbase-import.json --yes        # 先预检
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model import \
  --body-file tmp/onboarding-cmdb/oceanbase-import.json --yes        # 再导入
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model detail "OCEANBASE@EASYOPS"   # 校验
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model list --q "OceanBase"         # 列表核实
```

`oceanbase-import.json` 见 `tmp/onboarding-cmdb/`（含 3 属性 + 2 关系示例）。
