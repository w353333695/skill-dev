# EasyOps CMDB（platforms/demo）

外接 EasyOps CMDB 的接入资料——**唯一真相来源**，换环境/换 LLM 从这里读。按 SKILL.md 设计的 5 类位置组织，知识分门别类，不堆 README。

## 资料地图（知识在哪，按需查）

| 文件 | 装什么 | 何时查 |
|---|---|---|
| **systems.yaml** | 系统接入：鉴权三件套 / 端口 / org 体系 / user 权限 / 环境变量 / capabilities | 「怎么连」「用哪个 org/user」|
| **objects.yaml** | 对象模型 + 副作用规则：CmdbObject 结构、属性 value、关系约束、import upsert、删除 133129、NDJSON、fields 必填；实例 cmdb_instance（CRUD 批量语义/关系字段/instanceId 格式）| 「建模规则」「实例规则」「接口行为」|
| **entities.yaml** | 字段锚 + 转换：objectId/instance_id/org/user 格式、跨实体 step 接力（含实例 search→import/delete）| 「字段格式」「编排接线」|
| **flows/*.yaml** | e2e 流程模板：模型层 build-model/add-attributes/delete-model；实例层 create-instances/update-instances-batch/delete-instances-by-range；跨模型链路 search-by-relation-chain | 「规划挡 build/change」「直通挡 链路查询」|
| **easyops-cmdb.yaml** | api-cli 清单：18 verb 命令树 + body schema（三层：模型/关系/实例）| 「实际调用」|
| formats/ | （本系统不适用——无 BPMN/插件格式包）| — |

## 快速调用

```bash
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
export EASYOPS_ORG=18832008 EASYOPS_USER=easyops   # 测试 org + 模型系统管理员（0/1/2 禁动）
api-cli --spec platforms/demo/easyops-cmdb.yaml <resource> <verb> [args] --insecure   # 开发态用 scripts/run.sh 等价
```

- 鉴权/端口/org/user → 查 `systems.yaml` 的 `runtime:` 段
- 建模/属性/关系/约束/接口行为 → 查 `objects.yaml`
- 字段格式/编排接线 → 查 `entities.yaml`
- 端到端建/改/删模型 → 查 `flows/`

## 三层体系（19 verb）

`object_model`（模型：list/detail/import/import_check/export/delete）· `object_attr`/`object_relation`（属性/关系细粒度 CRUD + `object_relation.related_key` 跨模型链路发现）· `object_instance`（实例：search/import/delete——CRUD 全走批量，import 是建+改的 upsert 统一入口）。命令树与 body schema 详见 `easyops-cmdb.yaml`。

## 多模型关系链路（related_key + search 协同）

跨模型沿链取字段/过滤（如 TESTWWH→HOST→服务集→系统）：
1. **发现链路**：`object_relation.related_key`（src, dst）→ 拿 `reverseQueryKey`（dst→src，喂 dst 模型 search）+ 从 `path[].relation_side_id` 拼正向键（src→dst，喂 src 模型 search）。
2. **穿越**：`object_instance.search` 用该键多层 jsonPath——`fields:["<key>.name"]` 取终端名，`query:{<key>.name:{$eq}}` 按终端名过滤。
   实测：HOST search `serviceSets.system.name` 取到系统名 `"Easyops"`。

## cmdb-instance e2e 场景 → resource.verb 映射

| 场景 | 挡位 | 流程 |
|---|---|---|
| ① 新建 N 实例（含关联）| 规划 | `object_instance.import`（keys+datas，关系字段=Out.Id）→ flows/create-instances.yaml |
| ② 查某网段有几个实例 | 直通 | `object_instance.search`（query ip $like），读 `data.total` |
| ③ 给所有实例补属性 | 规划 | search 取列表 → import 定向改（keys=[instanceId]）→ flows/update-instances-batch.yaml |
| ④ 按 ip 范围删实例 | 规划 | search 取 instanceIds → `object_instance.delete`（分号串）→ flows/delete-instances-by-range.yaml |

## 数据来源

契约 `data/api-doc/cmdb-object.json`（4 EAML，模型层）+ `data/api-doc/cmdb-instance.json`（3 有效契约：PostSearchV3/ImportInstance/DeleteInstanceBatch，实例层；剔除 csv/json/excel 文件上传噪声）+ 后端 `data/sources/backend/CMDB/cmdb_service`（object + instance(_extend) 的 route.go / message/*.pb.go，补全契约缺失端点并修正批量删路径笔误 `instance_batch`）。
