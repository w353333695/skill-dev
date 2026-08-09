# EasyOps CMDB（platforms/demo）

外接 EasyOps CMDB 的接入资料——**唯一真相来源**，换环境/换 LLM 从这里读。按 SKILL.md 设计的 5 类位置组织，知识分门别类，不堆 README。

## 资料地图（知识在哪，按需查）

| 文件 | 装什么 | 何时查 |
|---|---|---|
| **systems.yaml** | 系统接入：鉴权三件套 / 端口 / org 体系 / user 权限 / 环境变量 / capabilities | 「怎么连」「用哪个 org/user」|
| **objects.yaml** | 对象模型 + 副作用规则：CmdbObject 结构、属性 value、关系约束、import upsert、删除 133129、NDJSON、fields 必填 | 「建模规则」「接口行为」|
| **entities.yaml** | 字段锚 + 转换：objectId/instance_id/org/user 格式、跨实体 step 接力 | 「字段格式」「编排接线」|
| **flows/*.yaml** | e2e 流程模板：build-model / add-attributes / delete-model | 「规划挡 build/change」|
| **easyops-cmdb.yaml** | api-cli 清单：16 verb 命令树 + body schema（三层：模型/关系/实例）| 「实际调用」|
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

## 三层体系（16 verb）

`object_model`（模型：list/detail/import/import_check/export/delete）· `object_attr`/`object_relation`（属性/关系细粒度 CRUD）· `object_instance`（实例 search）。命令树与 body schema 详见 `easyops-cmdb.yaml`。

## 数据来源

契约 `data/api-doc/cmdb-object.json`（4 EAML）+ 后端 `data/sources/backend/CMDB/cmdb_service`（route.go / message/*.pb.go，补全契约缺失的删除/详情/属性/关系 CRUD）。
