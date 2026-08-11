# EasyOps demo 部署（platforms/demo）

外接 EasyOps 的接入资料——**唯一真相来源**，换环境/换 LLM 从这里读。按 SKILL.md 设计的 5 类位置组织，知识分门别类，不堆 README。

## 接入的系统（3 个，同 cookie/org/user，不同 service/端口）

| 系统 | service:端口 | spec | 三层 + verb |
|---|---|---|---|
| **easyops-cmdb** | cmdb_service:8079 | easyops-cmdb.yaml | 模型/关系/实例（19 verb）|
| **easyops-autoops** | tool_service:8181 | easyops-autoops.yaml | 工具/版本/库 + 执行/导入导出 |
| **easyops-itsm** | flowable_service:8134 | easyops-itsm.yaml | 表单/版本/内容（8 verb）|

## 资料地图（知识在哪，按需查）

| 文件 | 装什么 | 何时查 |
|---|---|---|
| **systems.yaml** | 3 系统接入：鉴权三件套（+ itsc 权限 for itsm）/ 端口 / org / user / capabilities | 「怎么连」「用哪个 org/user」|
| **objects.yaml** | 3 系统对象模型 + 副作用：cmdb(模型/实例) + autoops(工具/内置变量/工具包) + itsm(表单/版本/容器/控件/脚本/继承/条件显示) | 「对象规则」「接口行为」|
| **entities.yaml** | 字段锚 + 转换：3 系统主键格式 + 跨实体 step 接力 | 「字段格式」「编排接线」|
| **flows/*.yaml** | e2e 流程模板：cmdb(模型/实例/链路) + autoops(工具) + itsm(表单 build/add-version/delete/list) | 「规划挡 build/change」「直通挡 读/链路」|
| **easyops-{cmdb,autoops,itsm}.yaml** | 各系统 api-cli 清单：命令树 + body schema | 「实际调用」|
| **sdk/** | 编排侧 Python SDK（api-cli 缺口补丁）：`easyops_client.py`（自包含 py2/3，双模式 openapi AK/SK 签名 + 内网直连，补 multipart/binary 缺口）。【编排侧 tool_package 导入导出/openapi 用；非 agent 工具脚本依赖，属 platform_conventions 例外】| 「编排侧 tool_package 导入导出」「外网 AK/SK 调用」|
| formats/ | （本部署不适用——无 BPMN/插件格式包）| — |

## 快速调用

```bash
# 鉴权已统一：cookie@~/.api-cli/auth.d/（密钥）+ 非密 env@~/.api-cli/env.d/demo.env（run.sh 自动 source）
# 调用方零传输——无需手 export EASYOPS_*。
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml <resource> <verb> [args] --insecure   # 统一入口（自动检测环境）
```

- 鉴权/端口/org/user → 查 `systems.yaml` 的 `runtime:` 段
- 建模/属性/关系/约束/接口行为 → 查 `objects.yaml`
- 字段格式/编排接线 → 查 `entities.yaml`
- 端到端建/改/删模型 → 查 `flows/`

## 计数 / total

场景"有几个/多少" → `object_instance.search` 读 **stderr** 的 `_meta.total`（新版 binary）：

```bash
# objectId 速查 entities.yaml#common_models（物理机=PHYSICAL_SERVER@ONEMODEL、主机=HOST）
scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_instance search PHYSICAL_SERVER@ONEMODEL \
  --body '{"fields":["instanceId"],"page":1,"page_size":1,"ignore_missing_field_error":true}'
# stderr → {"_meta":{"total":N}}；stdout 是 NDJSON 实例（计数时 page_size:1，几乎不拉数据）
```

- 非空结果：stderr `_meta.total` = 总数。
- 空结果（0 条）：stderr 无 total、stdout 空 → **exit 0 即代表 0 条**（新版错误可读到 stderr 且 exit≠0）。
- 鉴权（cookie + org/user/endpoint）由 `auth.d/` + `env.d/demo.env` 自动加载，无需 export。

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

## EasyOps AutoOps 工具管理（tool_service）

三层体系 + 两配套层（16 verb）：`tool`（工具 CRUD：list/get/create/update/delete）· `tool_version`（list；新建版本走 tool.update）· `tool_lib`（库 create/update/delete）· `tool_execution`（run + get_result/get_table/get_status 轮询）· `tool_package`（export_check + export/import，后两者走 Python SDK）。
工具包格式（`.tar.gz` = dat/config/script/libs）+ 内置变量（`EASYOPS_*`，⚠️不存在 `__instance__`/`${cmdb.xxx}`）详见 `objects.yaml#autoops_tool.api_behavior`。Python SDK `sdk/easyops_client.py`（**自包含** py2/3，双模式 openapi AK/SK 签名 + 内网直连，补 api-cli multipart/binary 缺口）——【编排侧库，非 agent 工具脚本依赖，属 platform_conventions.code 例外】；agent 工具脚本须自包含调 cmdb（py2 stdlib）。

### autoops e2e 场景 → resource.verb 映射（6 场景全通，org 18832008，2026-08-10）

| 场景 | 挡位 | 流程 |
|---|---|---|
| ① ITSM 分类查 cmdb 工具 | 直通 | `tool.list`（category=ITSM, name=cmdb；前端 q=name 别名）→ flows/search-tool.yaml |
| ② 建 CMDB 清理脚本工具 | 规划（跨系统）| `tool.create`（脚本须【自包含】调 cmdb，py2 stdlib，不引用 sdk——见 platform_conventions）→ flows/build-cleanup-tool.yaml |
| ③ 加版本+强制删除入参 | 确认 | `tool.get` → **flat** body 改 inputs/content → `tool.update`（派生 development）→ version.list 复查 → flows/add-tool-version.yaml |
| ④ run_cmd 查主机内存 | 规划 | `tool.list` 找 run_cmd → `tool_execution.run`（inputs **map**，具体 vId）→ 轮询 get_table → flows/execute-run-cmd.yaml |
| ⑤ 导出工具 | 确认 | `tool_package.export_check` → `tool_package.export`（GET+versionId，走 SDK）→ flows/export-tool.yaml |
| ⑥ 删工具 | 确认 | `tool.delete`（软删；force/versionId 可选）→ flows/delete-tool.yaml |

⚠️ e2e 实测坑（详见 `systems.yaml#easyops-autoops.runtime.e2e_findings`）：① list NDJSON 流式（非 wrapper）；② update body flat（非 `{tool:{}}`，否则假成功）；③ run inputs 是 map（非数组）；④ run vId 对 development 工具用具体/$latest_development；⑤ update 响应只返 toolId（派生须 version.list 复查）；⑥ 直连后端 cookie 非必需（org+user 够）。

## 数据来源

**cmdb**：契约 `data/api-doc/cmdb-object.json`（4 EAML，模型层）+ `cmdb-instance.json`（3 有效契约，实例层；剔除 csv/json/excel 文件上传噪声）+ 后端 `CMDB/cmdb_service`（object + instance(_extend)，补全端点并修正批量删路径笔误 `instance_batch`）。
**autoops**：契约 `data/api-doc/autoops-tool.json`（10 端点，压扁）+ 后端 `AutoOps/tool_service`（源码补全 list/delete/版本/执行/lib）。
**itsm**：契约 `data/api-doc/itsm-form.json`（8 EAML）+ 后端 `ITSM/flowable_service/form_schema_version`（12 路由，补 ListVersion/V2get/V2upd/Category）+ `internal/form/definition`（容器/控件/脚本权威结构体）。

---

## EasyOps ITSM（flowable_service）—— 表单 + 流程定义

**表单域**（8 verb）：`form`（list/save/delete）· `form_version`（list/get[V2]/update[V2]/delete/set_main）· `formDefinition`（版本内容 JSON 字符串 = []Container，非端点）。内容模型（5 容器 / 23 控件 / 5 生命周期脚本 / 条件显示 / 数据继承）详见 `objects.yaml#itsm_form_definition`。

**流程定义域**（11 verb）：`process_definition`（list/create/edit/delete）· `process_version`（list/get[V2]/create/edit/delete/set_main）· `process_form`（set 节点绑表单）。版本内容 = bpmnXML（标准 BPMN 2.0 XML + flowable:扩展）+ processSetting（节点配置 JSON）。内容模型（BPMN/节点配置/审批人体系/前后置脚本+orderInfo/表单决定流转/自动化节点）详见 `objects.yaml#itsm_process_bpmn` / `itsm_process_node_setting` / `itsm_process_form_flow`。
⚠️流程关键：建版本不部署 Flowable，须 set_main 才生效；表单决定流转用 `${pass==1}`+govaluate（后端求值），与表单 displayCondition `#{...}`（前端求值）不同套。

### itsm 表单 e2e 场景 → resource.verb 映射

| 场景 | 挡位 | 流程 |
|---|---|---|
| ① 看 easyops 建了哪些表单 | 直通 | `form.list` → flows/list-forms-and-versions.yaml |
| ② 看 test 有几个版本 | 直通 | `form.list` 找 formId → `form_version.list` 读 `data.total` |
| ③ 新建主机申请表单（多机/VM配置/物理机选实例）| 规划 | `form.save`（formDefinition 构造）→ flows/build-form.yaml |
| ④ 加版本+主机类型多选+条件显示 | 规划 | `form_version.get` → 改 → `form_version.update`（done 版派生新草稿）→ flows/add-version.yaml |
| ⑤ 删 test 表单 | 规划 | `form_version.delete` 清版本（末版本级联删 form）→ `form.delete` → flows/delete-form.yaml |
