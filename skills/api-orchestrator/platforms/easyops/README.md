# EasyOps demo 部署（platforms/demo）

外接 EasyOps 的接入资料——**唯一真相来源**，换环境/换 LLM 从这里读。按 SKILL.md 设计的 5 类位置组织，知识分门别类，不堆 README。

## 接入的系统（4 个，同 cookie/org/user，不同 service/端口）

| 系统 | service:端口 | spec | 三层 + verb |
|---|---|---|---|
| **easyops-cmdb** | cmdb_service:8079 | easyops-cmdb.yaml | 模型/关系/实例（19 verb）|
| **easyops-autoops** | tool_service:8181 | easyops-autoops.yaml | 工具/版本/库 + 执行/导入导出 |
| **easyops-itsm** | flowable_service:8134 | easyops-itsm.yaml | 表单/流程/服务/工单 + 触发器/通知/SLA/值班组（2026-08-11）+ sso-adapter provider 交付知识（2026-08-13）|
| **easyops-sys-setting** | sys_setting:8271 | easyops-sys-setting.yaml | 工作日历 work_calendar（2026-08-11）|

> ⚠️ itsm 的 notify_policy 前缀是 `/api/itsc_trigger/v1`（非 flowable_service）但仍走 8134。
> ⚠️ sys-setting 独立 spec：sys_setting:8271 ≠ flowable_service:8134，api-cli endpoint 是 service 级不支持 per-resource 绑端口，故 work_calendar 另起 spec。work_calendar 被 itsm 的 sla（workingCalendarId, 24hex）跨 system 引用。

## 资料地图（知识在哪，按需查）

| 文件 | 装什么 | 何时查 |
|---|---|---|
| **systems.yaml** | 4 系统接入：鉴权三件套（+ itsc 权限 for itsm）/ 端口 / org / user / capabilities | 「怎么连」「用哪个 org/user」|
| **objects.yaml** | 4 系统对象模型 + 副作用：cmdb(模型/实例) + autoops(工具/内置变量/工具包) + itsm(表单/版本/容器/控件/脚本/继承/条件显示 + 触发器/通知/SLA/值班组 + sso_provider 交付契约) + sys-setting(工作日历) | 「对象规则」「接口行为」|
| **entities.yaml** | 字段锚 + 转换：4 系统主键格式 + 跨实体/跨 system step 接力（含 work_calendar 24hex → sla） | 「字段格式」「编排接线」|
| **flows/*.yaml** | e2e 流程模板：cmdb(模型/实例/链路) + autoops(工具) + itsm(表单 build/add-version/delete/list + sso-adapter provider 交付 build-sso-provider) | 「规划挡 build/change」「直通挡 读/链路」|
| **easyops-{cmdb,autoops,itsm,sys-setting}.yaml** | 各系统 api-cli 清单：命令树 + body schema | 「实际调用」|
| **sdk/** | 编排侧 Python SDK（api-cli 缺口补丁）：`easyops_client.py`（自包含 py2/3，双模式 openapi AK/SK 签名 + 内网直连，补 multipart/binary 缺口）。【编排侧 tool_package 导入导出/openapi 用；非 agent 工具脚本依赖，属 platform_conventions 例外】| 「编排侧 tool_package 导入导出」「外网 AK/SK 调用」|
| formats/ | 跨部署复用的格式包：collector-kit（采集器插件 schema）+ sso-provider（sso-adapter 标准 provider 实物范本 oauth2/cas，交付新 provider 直接仿写） | 「格式范本」「sso provider 实物」|

## 快速调用

```bash
# 鉴权已统一：cookie@部署根 auth.d/（密钥，API_CLI_AUTH_D 指向）+ 非密 env@部署根 env.d/demo.env（run.sh 自动 source）。部署根默认 $PWD/.api-orchestrator；原 home 目录位置已废弃。
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
# objectId 速查 systems.yaml#easyops-cmdb.common_models（物理机=PHYSICAL_SERVER@ONEMODEL、主机=HOST）
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

---

# 采集套件域（collector_plugin_service + collector_service）

> 原 collector deployment 于 2026-08-13 合并入 demo（同一套 EasyOps 系统，迁移场景）。
> 真调环境 172.30.0.90 / org 8888（collector 域已就绪；cmdb/autoops/itsm/sys-setting 暂在 .232 待迁）。

## 两个系统

- **collector_plugin_service:8151** —— 采集套件管理（CRUD/导入导出/指标导入）。spec: `easyops-collector-plugin.yaml`
- **collector_service kit:12000** —— 套件激活/列表（⚠️8125 是旧版无 kit 模块，kit 端点在 12000，需 giraffe-contract-name header）。spec: `easyops-collector-service.yaml`

## 关键认知（collector 域）

1. **无启用/禁用端点** —— collector_plugin_service 无 enable/disable/activate。激活在 collector_service.kit.activate（:12000）。
2. **激活机制** —— activate 触发 AssignJobs（CMDB事件驱动+600s兜底）。成功判定 totalStatus!=fail。
3. **multipart 走 SDK** —— plugin_package.export/import/import_update 是 multipart/binary，api-cli 仅 --print-curl，真调走 curl -F / Python SDK。
4. **list 计数坑** —— plugin.list 的 total 在 data.total（body内），非 stderr _meta.total。
5. **采集脚本 py2.7** —— print 语句/requests/subprocess 无 timeout（详见 formats/collector-kit/sampler-types.yaml）。
6. **两种 samplerType** —— metric_sampler 输出 [{dims,vals}]（监控）/ process_sampler 输出 GATHERING DATA 标记（CMDB采集，解析在 agent 端，proxy 纯转发）。
7. **$.attr 取参** —— `$.` 开头配 paramType=cmdb，取值对象=采集目标实例（详见 formats/collector-kit/param-mechanism.yaml）。

## 套件开发能力（formats/collector-kit/）

跨部署复用的套件包格式知识（在 `formats/collector-kit/`）：plugin-yaml-schema / sampler-types / param-mechanism / package-format。
e2e 流程：`flows/develop-and-import-kit.yaml` / `upgrade-plugin.yaml` / `delete-plugin.yaml`。

## e2e 真调状态（2026-08-13）

- ✅ collector_plugin_service:8151 完整验证（import/export/import_update/delete/metricbeat_list）—— 真调结论已回流各 runtime/api_behavior 字段
- ⚠️ collector_service kit:12000 activate contract gap（ActivateCollectorKit@1.0.19 穷尽排查 not found，详见 systems.yaml runtime.contract_version_gap，需前端抓包）
- e2e 测试套件A『主机端口可达性监控套件』instanceId=658e73a176ad1 已导入保留（供后续 activate 验证）
- 待解 gap：kit.activate contract 版本（需前端抓包）/ 采集脚本 py2 实际执行（.90 HOST 未装 agent）/ process_sampler GATHERING DATA 解析（在 agent 端源码不在本地）

---

# 巡检域（inspection:8103，v1 体系）

> 2026-08-13 接入。实测定调：.90 平台用 **v1 体系**（INSPECTION_INFO 20 套件）；v2（INSP_SUITE 0 套件）仅兼容索引。

## 巡检套件 = 4 对象组装（区别于采集套件单模型）

```
巡检套件（pluginId 串联）
├── INSPECTION_INFO          元信息（id=pluginId/objectId/keys/method）
├── INSPECTION_COLLECTOR     脚本（py2 + args 含 password 类型）
├── INSPECTION_METRIC_GROUP  指标组（vals + conditions 阈值，平台判分）
└── INSPECTION_REPORT_TEMPLATE 报告模板（可选）
```

## 关键认知

1. **包格式 tar.gz**（5 文件：info.yaml/metrics.yaml/collectors/script.py[内容是YAML!]/reports_temp/detail.yaml/models.json）——详见 formats/inspection-kit/suite-package.yaml
2. **脚本协议不同**：参数注入脚本头（非环境变量）；必须输出 INSTANCE ID + start/end 两组标记——详见 formats/inspection-kit/script-protocol.yaml
3. **阈值平台判**：脚本只出原始值，按 conditions 的 comparator/level（0/5/10→80/50/20分）判分——详见 formats/inspection-kit/metric-threshold.yaml
4. **args 密码规范**：password 类型（手填也要 password 禁 text 明文）——详见 formats/inspection-kit/args-design.yaml
5. **导入不幂等**：重复 pluginId 直接报错（先删旧或改 id）
6. **category 两级点分**：指标组分类必须正好 1 个点（如 整体状态.连接数）
7. **无内置 cron**：任务定时委托外部 scheduler（once 绝对时间 / crontab cron 表达式）

## e2e 链路

```
CMDB 确认模型 → 开发套件包(tar.gz) → import → 建4对象 → insp_task.create(建任务)
→ 调度执行产生 jobId → insp_history.list/get(评分/异常) → export_excel/word(报告)
```

# Dashboard 域（cmdb:_DASHBOARD + collector_service:metric + data_exchange，2026-08-14 二次接入）

> 仪表盘 = CMDB _DASHBOARD 实例。CRUD 走 easyops-cmdb.yaml#dashboard（create/update 镜像前端 v2
> 保存行为——⚠️非 import upsert，前次接入的误判已纠正）；指标元数据查 collector_service
> collector_metric（tags-list 是空桩勿用）；数据试查 data_exchange olap_metric。

## 关键认知

1. **CRUD 端点**：create=POST /v2/object/_DASHBOARD/instance / update=PUT .../instance/:id（全量覆盖！先 search 取现配）/ delete=DELETE /object/.../instance/:id
2. **配置三件套**：panels（brickConf 须 JSON.stringify 字符串）+ context（8 种内置数据源类型，不只监控）+ variables（QUERY.{id} 引用，级联靠 selectorQuery 内表达式）
3. **指标查证链**：collector_metric.list（objectId 过滤）→ olap_metric.query_v3 试查活性（空=勿建图）——指标名错图表静默空白，后端不报错
4. **数据源 8 种**：cmdb-list/detail/count/count-multi/group（CMDB 系）+ cmdb-olap（监控指标）+ cmdb-columndb（历史数据统计，18 张 @EASYOPS 历史表）+ http/static
5. **前端渲染 ≠ API 200**：brickConf/context 是前端解释型内容，落库后须用户开 URL 验收

## 资料地图

- 配置结构/构件选型/变量 → `formats/dashboard-kit/dashboard-config.yaml`
- 数据源类型/args DSL/指标查证 → `formats/dashboard-kit/providers-context.yaml`
- 建盘流程（9 步）→ `flows/build-dashboard.yaml`
- 对象结构/副作用 → `objects.yaml#dashboard_instance` `#dashboard_metric_query` `#collector_metric`

## e2e 链路

```
object_model.list(查证objectId) → collector_metric.list(查证指标名) → olap_metric.query_v3(试查活性)
→ 组装配置(context+variables+panels) → dashboard.create → 前端 URL 验收 → update 迭代 → delete 清理
```
