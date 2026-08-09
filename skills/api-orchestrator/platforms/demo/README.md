# EasyOps CMDB —— api-cli 清单（platforms/demo）

`easyops-cmdb.yaml` 是 EasyOps CMDB 的 api-cli 集中清单，覆盖**三层体系**：模型(object)、关系(relation)、实例(instance)。由 `data/scenarios/cmdb-object.md` 的 onboarding 需求生成。

- **数据来源**：契约 `data/api-doc/cmdb-object.json`（4 个 EAML 契约）+ 后端 `data/sources/backend/CMDB/cmdb_service/object/route.go`（补全契约缺失的删除/详情/属性/关系 CRUD）。
- **调用**：`scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml <resource> <verb> [args]`。写操作先 `--dry-run`/`--print-curl` 预览。

## 接入真相（鉴权三件套 + 端口）—— 换环境必读，坑都在这

> 这是外接 EasyOps 的**唯一真相来源**。下列每一项都是实测踩出来的坑，缺一不可。

### 端口与服务

| 服务 | 地址 | 说明 |
|---|---|---|
| cmdb_service（后端，默认接入） | `http://172.30.0.232:8079` | 模型/关系/实例所有 API。直连，路由挂在 gin root（无前缀）。 |
| user_service | `http://172.30.0.232:8111` | 查 org 列表（`GET /api/v1/org/list`）、用户管理。 |
| 前端页面/网关 | `https://172.30.0.232`（或 `172.30.0.90`） | 浏览器入口。网关 per-API 路由，api-cli 不走（见下）。 |

所有直连都要带 **Host 头 `admin.easyops.local`**（IP 直连 + 网关按 host 路由）。

### 鉴权三件套（cookie 不够！）

直连后端 :8079，**光有 cookie 不行**，必须同时带三个东西：

| 凭证 | 来源 | 缺了报什么 |
|---|---|---|
| `Cookie: PHPSESSID=...` | 浏览器登录 user_service 后的会话 cookie，存 `~/.api-cli/auth.d/easyops-cookie.yaml` | 401/未授权 |
| `org: <整数>` header | 租户号。系统自带 0/1/2，测试用 18832008 | `empty org` (100003) |
| `user: <账号>` header | 模型系统管理员 `easyops` | `empty user` (100003) |

**后端代码佐证**：`cmdb_service/cmd/cmdb_service/main.go:549,691` 的 `Header.Get("org")`/`Header.Get("user")`。前端网关本来会从 PHPSESSID 解出 org/user 注入 header；直连后端没有这层，必须手动带。

**api-cli 怎么配**：spec 的 `endpoint.headers` 声明固定头（每个请求自动注入），值走环境变量：

```yaml
endpoints:
  backend:
    base_url: ${EASYOPS_CMDB_BACKEND_URL}   # http://172.30.0.232:8079
    host: admin.easyops.local
    auth: easyops-cookie
    headers:
      org: ${EASYOPS_ORG}     # 测试 18832008 / 业务 1
      user: ${EASYOPS_USER}   # easyops（管理员）
```

```bash
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
export EASYOPS_ORG=18832008      # 测试 org；0/1/2 是系统自带，禁止写
export EASYOPS_USER=easyops      # 模型系统管理员（有 ObjectImport/删除权限）
```

### org 体系（动错了会污染系统库）

- **org 0/1/2 是系统自带，禁止写操作**：0 无库（报 `Can not find 0 database`）；1=主业务库（22 模型）；2=名字服务库（9 模型）。
- validator 规则 `org gte:1`（0 必无效）。
- **测试用 org=18832008**（2026-07-31 建的非系统 org）。查可用 org：`user_service GET :8111/api/v1/org/list`（带 cookie + host）。
- default org 配置链（user_service）：agollo `common.org` > 环境变量 `COMMON_ORG` > yaml `default_org`。

### user 体系（读写权限不同）

- 模型系统管理员 = **`easyops`**（有 ObjectImport / 模型删除权限）。
- **读模型元数据**（`object_model.list/detail`）权限宽，任意非空 user 都能过。
- **读实例 / 写操作**（`object_instance.search`、`import`、`delete`）要**真实有权限的 user**；占位值（如 `admin`）会 403 `import object(s) permission denied` / `instance_access: action not found`。

### frontend 网关为何不走

前端网关按**每个 API** 路由（path_prefix 形如 `/next/api/gateway/cmdb.cmdb_object.<Verb>`），一个 endpoint 只能持一个 path_prefix，装不下多 verb 的 resource。且网关会自动注入 org/user（解 cookie），故走网关反而不用手动带 header——但 api-cli 的 endpoint 模型不支持 per-verb 前缀。结论：**全部走 backend 直连**，手动带 org/user。


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

## 调用踩坑录（实测，真相来源的一部分）

### 分页返回是流式 NDJSON，不是 `{data:{list:[...]}}` 包裹
`list` / `search` 分页时，api-cli 以 **NDJSON 流**输出——每行一个完整对象，**没有**外层 `{code,data:{list}}` 包装。解析要逐行 `json.loads`，不能当单对象解析（会报 `Extra data`）。非分页的单对象接口（如 `detail`）才是 `{code,data:{...}}`。

### 搜实例 `fields` 必填
`object_instance.search` 的 body **必须带 `fields`**（要返回的属性 id 列表），否则 `100000 参数错误 / fields is required but not set`。例：`{"page":1,"page_size":20,"fields":["name","username"]}`。

### import 是声明式 upsert（不是纯 create）
`object_model.import` 幂等：模型存在则更新、不存在则建。返回的 `is_create=true/false` 区分。**建模型、加属性、改关系都用它**（重导完整模型定义）。每模型/属性/关系各自返回 `code/message`，`code=0` 成功。

### 新增属性 id 须加 `_` 前缀
给**已存在**模型加新属性时，新属性 `id` 加 `_` 前缀（如 `_regulatory_level`），后端据此识别为"新增"（返回「创建成功」）；不加前缀的已有 id 会「更新成功」。这是 easyops 的约定，不是正则强制。

### 关系对端模型必须存在（或同批导入）
`relation_list` 里 `left_object_id`/`right_object_id` 指向的模型必须**已存在**或**在同一批 import 内**：
- `import_check`/`import` 默认会校验对端，找不到报 `Can not find <X> object`（外层 `133116 没有权限查看或实例不存在`）。
- 跳过校验：body 里 `ignore_dst_relation: true`。此时对端不存在的关系会被「模型不存在,忽略创建」（不报错但不落库）。
- 实测：测试 org(18832008) 没有 `USER_ACCOUNT` 模型，故「运维负责人」关系被忽略；`HOST` 模型存在，关系正常。

### 删除模型：有关系定义时不能直接删
模型若含 `relation_list`，`object_model delete` 报 **`133129 当前模型存在关系定义，请先删除已有关系`**。两种解法：
- `--forceDelete true`（query 参数）：强删，连关系一起删（推荐，清理用）。
- 或先 `object_relation delete <relation_id>` 逐条删关系，再删模型。
- `protected: true` 的模型不可删（核心模型）。

### import_check 是真预检（不落库）
`object_model.import_check` 校验模型定义但不落库，返回逐项校验结果。建模型前先跑它看约束。注意它**会查关系对端存在性**（见上），所以预检通过 ≠ 关系都能建成。

### 鉴权坑（详见上节「接入真相」）
cookie 不够，还要 `org`+`user` header；user 读写权限不同（`easyops` 才能写）；org 0/1/2 禁动。



| 场景 | 用什么 verb | 要点 |
|---|---|---|
| ① 查「IT资源监控」相关模型 | `object_model list --q "IT资源监控"` | 关键词模糊匹配 id/name |
| ② 建 oceanbase 模型（属性+关系：运维负责人/部署主机） | `object_model import --body-file oceanbase.json` | 一次声明 objectId/attrList/relation_list；`import_check` 先预检 |
| ③ 给 oceanbase 加分类属性（监管等级/服务时间） | `object_model import`（重导含新属性的完整模型）或 `object_attr create` | 新属性 id 加 `_` 前缀；枚举值放 `value.regex` 数组 |
| ④ 删除 oceanbase 模型 | `object_model delete "OCEANBASE@EASYOPS"` | protected 模型须 `--forceDelete` |

**验收 URL**：模型列表 `http://172.30.0.90/next/cmdb-model-management?...`；模型详情 `.../object/{objectId}/detail`。

## 示例：建/改/删 oceanbase 模型（实测命令，全路径已 e2e 真调通过）

```bash
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
export EASYOPS_ORG=18832008 EASYOPS_USER=easyops   # 测试 org + 模型系统管理员

# ① 预检（不落库，会查关系对端）
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model import_check \
  --body-file tmp/onboarding-cmdb/oceanbase-import.json --insecure --yes
# ② 建模型（属性 name/version/port + 关系 运维负责人/部署主机）
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model import \
  --body-file tmp/onboarding-cmdb/oceanbase-import.json --insecure --yes
# ③ 加分类属性（监管等级/服务时间，新属性 id 加 _ 前缀）
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model import \
  --body-file tmp/onboarding-cmdb/oceanbase-add-attrs.json --insecure --yes
# 校验 + 清理（模型有关系定义，须 forceDelete）
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model detail "OCEANBASE@EASYOPS" --insecure
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model delete "OCEANBASE@EASYOPS" \
  --forceDelete true --insecure --yes
```

payload：`tmp/onboarding-cmdb/oceanbase-import.json`（建：3 属性 + 2 关系）、`oceanbase-add-attrs.json`（加：监管等级/服务时间）。**注意**：tmp/ 不进 git，这两个 payload 是示例，按 README「模型设计知识」自己编。
