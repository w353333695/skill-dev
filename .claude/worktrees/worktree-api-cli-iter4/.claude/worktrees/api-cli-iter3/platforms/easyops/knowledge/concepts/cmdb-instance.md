---
name: cmdb-instance
kind: concept
tags:
- CMDB
- 实例
- instance
- 写入
- importInstance
- failed_count
- 跨模块
completeness: partial
gaps:
- importInstance 的 datas 每行字段约束（值类型/枚举/必填/正则）来自模型定义，跨字段组合校验规则（如 A 字段依赖 B 字段）未展开
- updateInstance 与 importInstance 的失败判定是否一致（updateInstance 是否也 code=0 + failed_count）未实测
- 批量导入的 failed 行 detail 结构未以真实失败样本核对
last_verified: '2026-07-29'
scope: CMDB 实例读写操作规范（查模型约束 → 按约束构造数据 → 写入 → failed_count 判定）；流程脚本 / 编排 / 独立脚本写 CMDB 通用
related:
- concepts/cmdb-model.md          # 模型定义（字段约束来源：value.type/regex/required）
- registry/cmdb_instance          # 实例操作接口卡片（importInstance/updateInstance/searchInstanceV3 等）
- modules/process_development/process-definition-v2-dev.md  # 流程脚本回写 CMDB 场景（§4.5④）
note: 'CMDB 实例「写」操作规范（importInstance/updateInstance + 关系 set/append/remove）：写之前必须 GET 模型定义核对字段约束（值类型 value.type /
  枚举候选 value.regex / 必填 required / 正则 regex，约束细节见 concepts/cmdb-model §2-§4），按约束构造实例数据；写入后失败判定
  必须看 data.failed_count（code=0 也可能部分行失败——枚举值不匹配/值类型错/必填缺/正则不过都让对应行 failed）。是跨模块通用规范：
  流程节点脚本回写、编排写 CMDB、独立调用脚本都适用。来源：2026-07-28 主机申请流程验收脚本回写 HOST 实测（_environment 枚举值、
  status 枚举值、failed_count 判定）；2026-07-29 巡检套件调试建 MYSQL/HOST 实例实测（keys 必须带唯一键、关系字段不能 import 需走 relation/set、
  left_max=1 不能 append、列表接口不返关系值需 GET 详情）。'
---

# CMDB 实例操作规范（cmdb-instance）

> CMDB 实例「写」操作的跨模块通用规范。模型字段约束（值类型/枚举/必填/正则）的定义见 `concepts/cmdb-model`（§2 值类型、§3 属性结构、§4 填写细则），本文**不重复约束细节**，只讲「怎么按模型约束正确写实例 + 怎么判定写入成功」。

## 一、写实例前：GET 模型定义核字段约束

> ⚠️ **臆测字段值是 CMDB 写入失败的首要原因**。写实例前必须先查目标模型定义，逐字段核对约束。

```bash
# 内网 cmdb.service 8079
GET http://<host>:8079/object/<objectId>   # 返回 attrList（每个字段的约束）
```

逐字段核对（`attrList[].value` / `attrList[]` 顶层）：

| 约束 | 字段位置 | 说明 | 不遵守的后果 |
| --- | --- | --- | --- |
| **值类型** | `value.type` | `str`/`int`/`float`/`enum`/`enums`/`ip`/`struct`/`structs`/`arr`/`json`/`bool`/`datetime` 等 12 种（完整见 cmdb-model §2） | int 字段传字符串、struct 字段传裸值 → 行 failed |
| **枚举候选** | `value.regex`（enum/enums 类型） | enum 的候选是 **JSON 数组字符串**（如 `'["无","开发","测试","生产"]'`）；值**必须在候选内** | 枚举值不在候选内（如臆测 test/prod，实际是 开发/测试/生产）→ 行 failed |
| **必填** | `required`（字符串 `"true"`/`"false"`，⚠️ 非布尔） | required="true" 的字段必传 | 必填字段漏传 → 行 failed |
| **正则** | `value.regex`（ip/str 类型） | ip 字段有 IPv4/IPv6 正则；str 字段可能配自定义正则 | 值不过正则（如非法 IP）→ 行 failed |

> 实测案例（HOST 模型）：`_environment` 是 enum，真实候选 `['无','开发','测试','预发布','生产','灾备']`（regex 字段）；`status` enum 候选含 `运营中`（非"运行中"）；`ip` 有 IPv4/IPv6 正则。臆测值会导致 importInstance 静默失败。

## 二、写实例：importInstance（批量创建/更新）

> 接口卡片见 `registry/cmdb_instance/importInstance`。`POST /object/{objectId}/instance/_import`（cmdb.service 8079）。

```json
{
  "objectId": "HOST",
  "keys": ["hostname"],            // 匹配键：存在则更新，不存在则新增
  "importMetadata": true,          // 创建时填 mtime/modifier
  "ignoreReadonlyFields": true,    // 忽略只读字段
  "datas": [                       // 多行 = 批量；每行一个实例的部分字段
    {"hostname": "web-01", "ip": "10.0.0.1", "cpus": 8, "_environment": "生产", "status": "运营中"},
    {"hostname": "web-02", "ip": "10.0.0.2", "cpus": 8, "_environment": "生产", "status": "运营中"}
  ]
}
```

- `datas[]` 每行只需传**本次要写的字段**（不必全字段），但**必填字段必须传**；
- `keys` 决定 upsert 语义：按 keys 字段匹配，命中则更新、未命中则新增；
- **`keys` 必须带模型的唯一键属性**（2026-07-29 实测）：不传或唯一键值全空 → 报「导入唯一键的值全部为空，实例导入失败」（`code=133504`）。唯一键因模型而异——HOST 是 `deviceId`（readonly，通常 agent 上报生成）、MYSQL@ONEMODEL 是 `id`（实例标识）；查 `attrList[].unique=="true"` 确认。readonly 唯一键手工建实例时需配 `ignoreReadonlyFields: true` 强行写入；
- 单实例也可用 `updateInstance`（PUT `/object/{objectId}/instance/{instanceId}`），但批量/不确定是否存在时用 importInstance 更稳。

> **⚠️ 关系字段不能靠 importInstance 写入**（2026-07-29 实测）：`datas` 里传关系字段（如 MYSQL 的 `host: ["<HOST instanceId>"]`）**不写库**（insert_count=1 但关系为空）。建关系要走专门接口 `POST /object/{objectId}/relation/{relationId}/set`，body `{"instance_ids": [...], "related_instance_ids": [...]}`。`left_max=1` 的关系（如部署主机）**不能 append**（报 `relation max is not great than one, cannot append, please use set`），须用 `set`。

## 二附、实例关系操作（set / append / remove）

| 操作 | 接口 | 适用 |
| --- | --- | --- |
| set | `POST /object/{objectId}/relation/{relationId}/set` | 覆盖式设置关系（left_max=1 的唯一关系只能用它） |
| append | `POST /object/{objectId}/relation/{relationId}/append` | 追加关系（left_max>1 或 -1 时） |
| remove | `POST /object/{objectId}/relation/{relationId}/remove` | 移除关系 |

- `relationId` 是关系字段的 `left_id`（如 MYSQL→HOST 关系在 MYSQL 实例侧叫 `host`），不是完整 `relation_id`；
- body 均为 `{"instance_ids": ["<主体实例id>"], "related_instance_ids": ["<被关联实例id>"]}`；
- **关系值在实例「列表」接口不返回**（`host` 显示 null），需 GET 单实例详情 `/object/{objectId}/instance/{instanceId}` 才看得到关系数组。

## 三、写入成功判定：必须看 failed_count（不能只看 code）

> ⚠️ **`code=0` ≠ 写入成功**。CMDB importInstance 即使部分行校验失败也返回 `code=0`，失败的行体现在 `data.failed_count` + `data.detail`。

```python
result = response.json()
detail = (result.get("data") or {})
failed = detail.get("failed_count", 0)
# 失败判定：code!=0 或 failed_count>0 都算失败
if result.get("code") != 0:
    raise_error("CMDB 写入失败 code=%s error=%s" % (result.get("code"), result.get("error", "")))
if failed > 0:
    raise_error("CMDB 导入有 %d 条失败（值类型/枚举值/必填/正则校验不通过）：%s" % (failed, detail.get("detail")))
# 成功
print("写入成功 insert=%s update=%s" % (detail.get("insert_count", 0), detail.get("update_count", 0)))
```

> 流程节点脚本（前置+同步）场景：failed_count>0 必须 `raise`（阻塞节点动作），否则工单照常流转但数据没写对（静默丢数据）。详见 `process_development` §4.5。

## 四、读实例：searchInstanceV3 / getInstanceDetail

| 操作 | 接口 | 用途 |
| --- | --- | --- |
| 搜索实例 | `POST /object/{objectId}/instance/_search`（searchInstanceV3） | 按条件查实例列表（分页） |
| 实例详情 | `GET /object/{objectId}/instance/{instanceId}`（getInstanceDetail） | 查单个实例全字段 |

> 接口卡片见 `registry/cmdb_instance`。读实例返回的字段值形态遵循 cmdb-model §2（如 enum 字段返回字符串、struct 返回对象）。

## 五、消费场景（跨模块）

| 场景 | 入口 |
| --- | --- |
| 流程节点脚本回写 CMDB（如验收创建 HOST） | `process_development` §4.5（脚本编写规范）+ 本文（写入规范） |
| 编排写 CMDB（DAG 卡片 importInstance/updateInstance） | `registry/cmdb_instance` 卡片 + 本文（构造数据 + failed_count 判定） |
| 独立调用脚本写 CMDB | `concepts/api-calling`（客户端基座）+ 本文（写入规范） |

> 本文是「写实例」的**单一真相源**：约束细节查 cmdb-model、接口怎么调查 registry/cmdb_instance、本文只讲跨场景通用的「按约束写 + failed_count 判定」规范。
