---
name: itsm-service-dev-workflow
kind: module
module: itsm_service_dev
tags:
- ITSM
- 服务开发
- 工作流
- 流程
- 表单
- 脚本
- 服务目录
- 编排指南
completeness: partial
gaps:
- 工作流各阶段基于主机申请场景实战沉淀，其他 ITSM 场景（如问题/变更/发布管理）的特有节点/角色未覆盖
- 验收点 URL 模板基于当前前端路由，前端版本升级后路由可能变
- ✅ 已补（2026-07-28）：阶段三新增「表单按需绑定」原则——节点是否绑表单取决于有无数据填写/回填需求（申请/实施按需绑，纯审批节点不绑）；并补解绑接口 `DELETE /v1/process/form/relation/{relationId}`（setFormVersion 只能绑不能解绑）。阶段一同步加「哪些节点需要绑表单」决策点。来源：网络策略申请服务踩坑（曾把申请表绑全节点）+ host-apply 真实流程印证。
- ✅ 已补（2026-07-28）：阶段四新增「脚本按需配置」原则——前/后置脚本非每节点必配，只在该节点有自动化需求时配。两类用途：①自动化动作（回填 CMDB/调外部）；②动态指定下个节点处理人（表单值需组合/匹配/查表算处理人→**前置+同步**；表单值能直接当处理人用 assignee={{.formValue}} 无需脚本）。同步更新阶段一「自动化点」拆解 + process_development §4.5 选型表。
last_verified: '2026-07-28'
scope: EasyOps ITSM 服务开发端到端工作流（流程建模 + 表单设计 + 自动化脚本 + 服务挂载 + 迭代优化 + 导出闭环），LLM 按自然语言需求自主完成
related:
- modules/process_development/process-definition-v2-dev.md
- modules/form_development/form-schema-v2-dev.md
- modules/form_development/form-advanced.md
- modules/form_design/form-design-spec.md
- modules/autoops_tool/tool-package-dev.md
- concepts/cmdb-instance.md
- concepts/order-info.md
- registry/process
- registry/form
note: EasyOps ITSM 服务开发端到端工作流（场景知识，归平台包不进 skill）：7 阶段（需求拆解→流程建模→表单设计→脚本开发→服务挂载→迭代优化→导出闭环），每阶段含目标/call_card
  步骤/知识引用/验收点。是「编排指南」——不重复领域知识细节，各操作原理/字段/坑见附录B知识引用地图（唯一来源）。API 优先用 skill call_card
  单步调（缺卡先查 sources/backend/parsed/contracts.yaml 契约，不推断）。阶段七导出 tar.gz 兼容生产离线上传。源自主机申请流程实战沉淀，已去环境特定产物（跨环境无意义）。
---

# ITSM 服务开发工作流（LLM 参考）

> 目标：LLM 根据用户自然语言需求，**端到端完成 ITSM 服务开发**（流程建模 + 表单设计 + 自动化脚本 + 服务挂载），并支持细节迭代优化，**摆脱人为单步引导**。
>
> **定位**：本文是 **EasyOps 平台的场景知识**（归 `platforms/easyops/knowledge/`），非通用 skill 能力——描述的是 EasyOps ITSM 的工作流，不耦合到 skill 主干。工作流是「编排指南」，**不重复领域知识细节**——各操作的原理/字段/坑见「知识引用地图」指向的已有知识（唯一来源）。API 操作优先用 skill 的 `call_card` 单步调试能力（见 §0 API 操作约定）。

---

## 0. 前置：环境与鉴权

| 项         | 值/来源                                                                                              |
| ---------- | ---------------------------------------------------------------------------------------------------- |
| 平台 host  | `manifest.yaml` 的 `host`（当前 172.30.5.20）                                                    |
| 调用模式   | **内网直连**（`easyops_internal`，user/org 头，免 cookie）——优先；网关模式仅 cookie 类操作 |
| 各服务端口 | flowable_service=8134 / cmdb.service=8079 / tool_service=8181（见`concepts/api-calling`）          |
| 鉴权头     | `user`/`org`（manifest 的 `auth.internal`）                                                    |

> API 操作约定：**优先 `call_card` 单步调**（`bash run.sh call_card.py --platform easyops --card <name> --param k=v`），缺卡片的 API 先补注册（见附录 A）。仅在需要复杂逻辑（循环/聚合/翻页）时才写独立脚本，且复用 `concepts/api-calling` 客户端基座。

---

## 阶段一：需求拆解与方案设计

**目标**：把自然语言需求拆成「流程拓扑 + 节点角色 + 表单字段 + 自动化点」。

**步骤**：

1. **流程拓扑**：识别节点（申请/审批/实施/验收）+ 串并行（并行用 `parallelGateway` 成对）+ 驳回路径。知识→`process_development` §3（bpmnXML）、§1（三层结构/驳回规则）。⚠️ **驳回不画 bpmn 连线**——靠 `nodeSettings.rejectNodes` 配置（运行时动态跳转），bpmnXML 只画前进流向，详见 `process_development` §5.4 驳回机制实证。
2. **节点处理人**：映射 userType（提单人 `{{.loginUser}}`/直属领导 `{{.historyExecLeader}}`+`assigneeValue=申请节点`/指定人/值班组/用户组）。知识→`process_development` §3.3（处理人三件套）。
3. **表单字段（按需）**：**先判断哪些节点需要表单**（见阶段三「表单按需绑定」——有数据填写/回填需求的节点才绑，纯审批节点不绑）。只给需要表单的节点设计字段，对照 CMDB 模型字段（若回写 CMDB）。**回写 CMDB 的字段必须先 GET 模型核对约束**（值类型/枚举/必填/正则）。知识→`form_development` §3（控件枚举）、`cmdb-instance` §一（查模型约束）、`cmdb-model` §2-§4（字段约束细节）。
4. **自动化点（按需）**：**只给有自动化需求的节点配脚本**（见阶段四「脚本按需配置」——非每节点必配）。识别两类需求：①自动化动作（回填 CMDB/调外部）；②动态指定下个节点处理人（表单值需组合/匹配/查表算处理人，表单值能直接当处理人的不用脚本）。脚本副作用是否影响数据准确性/是否决定处理人 → 决定前置+同步 或 后置+异步。知识→`process_development` §4.5（脚本选型原则）。

**关键决策点（需与用户确认）**：

- 多实例数据（如多主机）用 `table` 容器还是多字段？
- 实施节点数据是否继承申请节点（容器 `default` 继承）？
- 哪些节点要回写 CMDB（决定脚本 + 同步策略）？
- **哪些节点需要绑表单**（按需绑定原则，见阶段三——只给有数据填写/回填需求的节点设计表单，纯审批节点不绑）？

**产出**：流程节点清单 + **按需的表单清单**（标注各表单绑哪个节点）+ 脚本清单（位置/触发/同步异步）。

---

## 阶段二：流程建模

**目标**：创建流程定义 + 版本（bpmnXML + processSetting），定稿设主。

**API（call_card 单步）**：

| 步骤          | 卡片                                 | 说明                                                            |
| ------------- | ------------------------------------ | --------------------------------------------------------------- |
| 建流程定义    | `createProcessDefinition`          | 建 definition（name/category/memo）                             |
| 建流程版本    | `createProcessDefinitionVersionV2` | bpmnXML+processSetting+state；改已done版本用 baseVersionId 克隆 |
| 取版本详情    | `getProcessDefinitionVersionV2`    | 拿 taskInfo/bpmnXML（改版本前先 GET 全量）                      |
| 编辑/定稿版本 | `editProcessDefinitionVersionV2`   | 全量覆盖；state=done 定稿（仅改 unfinished）                    |
| 设主版本      | `setProcessDefinitionMainVersion`  | 触发部署（超时 120s）；⚠️`/v1/definition/` 非 `/v2/`      |

**知识引用**：`process_development`（§2 接口契约、§3 bpmnXML、§4 processSetting、§1 设主/克隆规则、§4.4 节点脚本配置）。

**关键坑**（已在卡片 description + process_development 标注）：

- 已 done 版本不能直接改→用 baseVersionId 克隆新版本
- 设主 path 是 `/v1/definition/{did}/version/{vid}`（非 /v2/），定义列表层 isMain 有延迟（以版本层为准）
- bpmnXML 用 `bpmn2:` 前缀 + `flowable:` 命名空间属性格式

### ✅ 验收点 1：流程逻辑是否正确

**新增版本页**（前端流程设计器，可视化核对拓扑/节点/脚本配置）：

```
http://<host>/next/itsc-process-manage/<definitionId>/versionCreate-v2/<versionId>?activeTab=0
```

- 核对：节点拓扑、处理人、`scriptSettings`（preScript/postScript + operations + isAsync）、表单绑定。

---

## 阶段三：表单设计与绑定

**目标**：创建表单（formDefinition）+ 绑定到流程节点。

**API（call_card 单步）**：

| 步骤           | 卡片                          | 说明                                            |
| -------------- | ----------------------------- | ----------------------------------------------- |
| 建表单+首版本  | `saveFormSchemaV2`          | 自动 isMain；formDefinition 是 string           |
| 改表单版本     | `updateFormSchemaVersionV2` | done→新建版本，草稿→原地改                    |
| 取表单版本     | `getFormVersionV2`          | 拿 formDefinition                               |
| 设表单主版本   | `setFormMainVersion`        | POST 到版本 URL（非 /setMain）                  |
| 流程节点绑表单 | `setFormVersion`            | versionId=流程版本，formId=表单ID，自动取主版本 |
| 解绑节点表单   | `DELETE /v1/process/form/relation/{relationId}` | relationId 从 `getProcessDefinitionVersionV2` 的 `taskInfo[].formInfo.relationId` 取 |

### ⚠️ 表单按需绑定（重要原则，勿全节点绑同一张表）

**节点是否绑表单，取决于该节点有没有「数据填写/回填」需求**——不是所有节点都绑表单，更不是全绑同一张申请表。按节点角色决策：

| 节点角色 | 是否绑表单 | 说明 |
| --- | --- | --- |
| 申请节点（提单人填业务数据） | ✅ **绑** | 申请人填申请明细，需表单 |
| 实施节点（填实施结果/回填数据） | ✅ **绑**（若有数据回填） | 实施表单可用 `default` 继承申请数据 + 实施字段（如执行回执）。**若实施是脚本自动下发、无数据回填需求 → 不绑** |
| 纯审批节点（直属领导/审核/领导审批） | ❌ **不绑** | 审批人只填审批意见（靠 `nodeSettings.memoLevel` 控制），不需要业务表单 |

**反例（已踩）**：把申请表绑给所有节点（申请+审批+实施）→ 审批/验收节点也被迫填申请表，不合理。host-apply 真实流程的正确做法：`Task_apply` 绑申请表、`Task_impl_*` 绑实施表（继承申请数据）、3 个审批节点**完全不绑**表单。

**绑定关系是独立资源**（`_ITSC_PROCESS_FORM_RELATION`，有 relationId）。解绑单个节点用 `DELETE /api/flowable_service/v1/process/form/relation/{relationId}`（relationId 从版本详情的 `taskInfo[].formInfo.relationId` 取）。`setFormVersion` 只能绑/覆盖，不能解绑。

**知识引用**：

- 表单结构合规→`form_design`（§容器/控件清单、§七条件显示/继承/脚本、§八生产红线、**§八.五前端渲染必需字段**）
- 接口契约/字段→`form_development/form-schema-v2-dev`（§2 接口、§3 formDefinition 字段表）
- 进阶（数据继承/条件显示/生命周期脚本）→`form_development/form-advanced`

**formDefinition 构造必读**（踩过的坑，都在 `form_design` §八.五 + §五）：

- 容器必填 `layout`/`layoutConfig`/`modelField`/`condition`；row 容器**不要带** options/tabPanes/extraProps（只 cmdb 容器有 options）
- 控件 `options` 必填 `layout`/`layoutSpan`/`rules`/`question`/`remoteFunc` 等（前端 `.map` 无兜底，缺了崩 `reading 'map'`）
- **选择类候选字段名**：SELECT/MULTIPLESELECT/CHECKBOX 用 `extraProps.items`；RADIO/CASCADER 用 `extraProps.options`（错位必崩）
- **工具 inputs 的 type 不要用 json**（前端不渲染），JSON 字符串入参用 string
- 校验：产出后跑 `check_form_design.py`（但通过 ≠ 前端能渲染，前端必需字段看 §八.五）

**数据继承**（实施节点看申请数据）：容器 `default.{userTaskId, sectionKey}` 声明继承；**继承容器可加额外控件**（如继承主机清单 + 加 ip 列，只 ip 可编辑）。知识→`form-advanced` §1.1。

### ✅ 验收点 2：表单逻辑是否正确

**新增版本页**（前端表单设计器，可视化核对控件/布局/继承）：

```
http://<host>/next/itsc-form-management/<formId>/<versionId>/versionCreate
```

- 核对：控件类型/字段、布局、`default` 继承配置、SELECT 候选（items/options）。

---

## 阶段四：自动化脚本开发与绑定

**目标**：开发节点前后置脚本工具 + 绑到流程节点。

### ⚠️ 脚本按需配置（重要原则，勿给所有节点都配脚本）

**节点的前/后置脚本是按需配置，不是每个节点都要脚本**——只在该节点有「自动化动作」需求时才配。脚本的两类用途：

| 用途 | 举例 | 选型（位置×执行方式） |
| --- | --- | --- |
| **执行自动化动作** | 回填 CMDB（创建/更新实例）、调外部接口（下发策略/发通知）、扣库存 | 影响数据准确性→**前置+同步**（失败阻塞节点动作）；通知/日志→后置+异步 |
| **动态指定下个节点处理人** | 根据本节点表单值做组合/匹配/查表，**算出下个节点的处理人**（表单值不能直接当处理人时，如按申请系统→查负责人映射） | **前置+同步**（必须在节点 pass 前算出并设好处理人；同步失败阻断，避免工单流到下个节点却无人处理） |

**反例（勿犯）**：给每个节点都配脚本（申请/审批/实施全挂）→ 无自动化需求的节点挂空脚本纯属冗余、增加维护负担。
**判断标准**：节点处理人能直接由 `assignee` 三件套（提单人/领导/指定人/值班组/`formValue` 直取）或 `nextAssigneeSetting`（人工 UI 指定）解决的，**不用脚本**；需要复杂规则计算处理人、或需要副作用（写 CMDB/调外部）时，才配脚本。

> 💡 **动态指定处理人 vs 处理人三件套**：表单字段值能直接当处理人（如处理人字段就是用户名）用 `assignee="{{.formValue}}"`；需要「按表单值查映射/组合条件算出处理人」才用前置脚本。脚本如何把计算结果设为下个节点处理人的机制见 `process_development` §4.5（配合 `nextAssigneeSetting` 或流程变量）。

**API（call_card 单步）**：

| 步骤               | 卡片                               | 说明                                                        |
| ------------------ | ---------------------------------- | ----------------------------------------------------------- |
| 创建工具           | `tool_create`                    | POST /tools（type=python+content+sandboxRun:true，免打包）  |
| 更新工具           | `tool_update`                    | 改 content 后必须同步（PUT /tools/{toolId}）                |
| 绑到流程节点       | `editProcessDefinitionVersionV2` | 改 nodeSettings.scriptSettings.scriptIdList（要克隆新版本） |
| 取 HOST 等模型约束 | `model_get_detail`（cmdb_model） | 写 CMDB 前必查                                              |

**知识引用**：

- 脚本选型（前置/后置 + 同步/异步）→`process_development` §4.5
- 脚本入参 orderInfo 结构→`concepts/order-info`（⚠️ formData 是 list[{key,values}]，SELECT 值是 {key,label,value}）
- CMDB 回写规范（查约束→写→failed_count 判定）→`concepts/cmdb-instance`
- 工具包/沙箱/EASYOPS_ 变量→`autoops_tool`（§4.1 免打包创建、附录 C 变量、§2.2.1 inputs type）

**脚本开发规范**（`process_development` §4.5）：

1. **选型**：影响数据准确性（回写 CMDB）/ 动态指定下个节点处理人 → **前置+同步**（失败阻塞）；通知/日志 → 后置+异步。详见上方「脚本按需配置」表
2. **inputs 声明**：显式声明入参（orderInfo/action/scriptType/loginUser，type 全 string，**别用 json**），便于调试
3. **可迁移**：host 用 `EASYOPS_LOCAL_IP`、org 用 `EASYOPS_ORG`（沙箱注入，直接引用不要 getenv），禁硬编码
4. **迭代同步**：改脚本 content 后必须 `tool_update`（本地改 ≠ 工具库更新）
5. **失败判定**：CMDB 写入看 `failed_count`（code=0 也可能部分行失败）

### ✅ 验收点 3：脚本执行 + CMDB 写入

- 发起工单走完流程到脚本节点，看 `ProcessInstanceToolExecRecord`（脚本执行记录）+ CMDB 实例是否创建。
- 失败看 `raise` 字段（前端弹错误）或执行记录的错误堆栈。

---

## 阶段五：服务挂载

**目标**：把流程配置成 ITSM 服务，用户能在服务目录发起。

**API（call_card 单步）**：

| 步骤       | 卡片                      | 说明                            |
| ---------- | ------------------------- | ------------------------------- |
| 建服务目录 | `createServiceCatalog`  | 父目录下建分类（parentID 必填） |
| 建服务     | `createServiceInstance` | 关联流程（associatedProcess）   |
| 查目录树   | `getServiceCatalogTree` | 找挂载点 + 验证                 |

**知识引用**：卡片 description（createServiceInstance/createServiceCatalog 已补实测坑）。

**关键坑**（卡片 description 已标）：

- `category` 必填（卡片原漏列，传流程分类名）
- `catalogId` 不能是内置根目录（"服务请求"等是内置，报"禁止新建"）→ 先建用户子目录再挂服务

### ✅ 验收点 4：服务详情 + 发起工单

**服务详情页**：

```
http://<host>/next/itsc-service-management/setting-list/<serviceInstanceId>
```

- 核对：关联流程、目录位置、负责人。点"发起"测试端到端。

---

## 阶段六：迭代优化（贯穿）

**目标**：用户反馈后优化任一环节（流程/表单/脚本/服务）。

**优化决策树**：

| 反馈                   | 改什么       | 怎么改（避免破坏已发布）                                                           |
| ---------------------- | ------------ | ---------------------------------------------------------------------------------- |
| 流程拓扑/节点/脚本配置 | 流程版本     | 已done→baseVersionId 克隆新版本→改→定稿→设主                                   |
| 表单字段/布局/继承     | 表单版本     | 对 done 主版本调 update（自动新建版本）→设主→重绑流程节点（setFormVersion 刷新） |
| 脚本逻辑               | 工具 content | tool_update（生成新版本，流程自动取最新）                                          |
| 服务位置/分类          | 服务实例     | 删旧重建或 update（挪目录）                                                        |

**每次优化的闭环**：改→校验（check_form_design.py / 语法）→推→设主→刷新绑定→**验收点复核**。

**迭代同步纪律**：

- 改表单 formDefinition → 推新版本 + 设主 + 流程节点重绑（表单主版本切换后 setFormVersion 刷新）
- 改脚本 content → tool_update 同步工具库
- 改流程 nodeSettings → 克隆新版本（已done不可原地改）

---

## 阶段七：导出闭环（离线迁移）

**目标**：导出服务 tar.gz，兼容生产环境无法联网、只能上传服务包的场景。

**API（call_card / 二进制下载）**：
| 步骤 | 卡片 | 说明 |
|---|---|---|
| 导出服务 | `exportServiceInstance` | GET，instanceIds=服务ID，isMain=true，返回 tar.gz |

**导出内容**（tar.gz 含服务关联的全套资源，按 CMDB 关系图深度遍历）：
- `cmdb_service_instance.json`：`{version, data:[{ObjectID, Depth, RelationList, Result}]}`，按 CMDB 模型分组：
  - `_ITSC_SERVICE_INSTANCE`（服务）/ `_ITSC_PROCESS`（流程定义）/ `_ITSC_PROCESS_VERSION`（流程版本含 bpmnXML+processSetting+scriptSettings）
  - `_ITSC_FORM_SCHEMA`+`_ITSC_FORM_VERSION`（表单定义+版本含 formDefinition）/ `_ITSC_PROCESS_FORM_RELATION`（节点-表单绑定）
  - `_ITSC_TRIGGER`/`_ITSC_STANDARD_FIELD`/`_ITSC_SLA_RULE` 等关联资源（有则导出）
- `tools/<toolId>.tar.gz`：脚本工具（每个工具一个，含 content）

**导入（生产环境）**：`importServiceInstance`（POST `/service_catalog/{catalogId}/import`），上传 tar.gz 到目标目录。

**关键点**：
- `isMain=true` 只导出流程主版本（生产用主版本即可）；要全版本传 false
- 导出是**快照**——导出后源环境继续迭代不影响已导出的包；生产导入后是独立副本
- 服务迁移到生产后，脚本里的 `EASYOPS_LOCAL_IP`/`EASYOPS_ORG` 自动适配新环境（前提：脚本没硬编码，见阶段四 §可迁移）

### ✅ 验收点 5：导出包完整
```bash
# 导出后核对 tar.gz 内容（应含服务/流程/表单/绑定/脚本）
tar tzf <service>.tar.gz
# 含 cmdb_service_instance.json + tools/<toolId>.tar.gz
# 解压 cmdb_service_instance.json 看 data[] 各 ObjectID 的 Result 非空（服务/流程/表单/绑定都有）
```

---

## 附录 A：ITSM 服务开发核心 V2 API 卡片

ITSM 服务开发核心 API（已注册入库 `registry/process` + `registry/form` + `registry/service_catalog`）：

**流程**（4 张）：`createProcessDefinitionVersionV2` / `editProcessDefinitionVersionV2` / `getProcessDefinitionVersionV2` / `setProcessDefinitionMainVersion`
**表单**（4 张）：`saveFormSchemaV2` / `updateFormSchemaVersionV2` / `setFormMainVersion` / `setFormVersion`
**服务**（导出闭环）：`exportServiceInstance`（导出 tar.gz）/ `importServiceInstance`（导入）

> 这些卡片覆盖工作流各阶段的 call_card 操作（建/改/取/设主/绑定/导出），endpoint.mode=`easyops_internal`（内网直连实测 path）。后续若发现新的缺卡，按 `references/card-schema.md` 补卡片 → `register_cards.py rebuild_index` 重建索引。

**⚠️ 缺卡补注册的操作习惯（重要）**：

发现某 API 没卡片时，**先去后端契约查真实接口，不要推断**：
1. **查契约**：`platforms/easyops/sources/backend/parsed/contracts.yaml`（5800+ 契约，含 path/method/service/port/request/response）。按 path 关键词或 operation_key 搜（如 `grep` export/service_instance）。
2. **按契约写卡片**：path/method/service/port 来自契约（`path_source: backend_contract`），request/response 字段来自契约的 request.fields/response.fields。
3. **实测验证**：内网 call_card 或 httpx 调一次确认 path 可达 + 返回结构。
4. **入库**：卡片写 `registry/<module>/<name>.yaml` → `register_cards.py rebuild_index`。

> 禁止：凭语义猜 path（如 `/service_instance/{id}/export`）—— EasyOps 的实际 path 可能不规则（如真实导出是 `/export/service_instance`，query 传 instanceIds），猜错浪费往返。**契约是 path 真相源**。

卡片字段见 `references/card-schema.md`。本次 8 张卡片已按 schema 写好（endpoint.mode=easyops_internal，实测 path）。

---

## 附录 B：知识引用地图（唯一来源，不重复）

| 领域                                         | 唯一来源                                                                 | 涵盖                                                                 |
| -------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| 流程开发（接口/bpmnXML/processSetting/脚本） | `modules/process_development/process-definition-v2-dev.md`             | §2接口 §3bpmnXML §4processSetting/脚本 §4.5脚本规范 §8真调记录  |
| 流程设计态合规（BPMN 静态规则）              | `modules/process_design/compliance-rules.md` + `check_compliance.py` | 27 条 bpmnlint                                                       |
| 表单设计态结构（formDefinition 合规）        | `modules/form_design/form-design-spec.md` + `check_form_design.py`   | §容器/控件 §五选择类候选 §八红线**§八.五前端渲染必需字段** |
| 表单开发态接口/字段                          | `modules/form_development/form-schema-v2-dev.md`                       | §2接口 §3 formDefinition 字段表 §4绑定                            |
| 表单进阶（继承/条件显示/生命周期脚本）       | `modules/form_development/form-advanced.md`                            | §1数据继承(含继承+扩展) §2条件显示 §3生命周期脚本                 |
| 标准字段                                     | `modules/standard_field/standard-field-types.md`                       | kind枚举/接口/ITSC_前缀                                              |
| 工具包/沙箱/变量                             | `modules/autoops_tool/tool-package-dev.md`                             | §4.1免打包创建 附录C变量 §2.2.1 inputs type                        |
| CMDB 模型定义（字段约束）                    | `concepts/cmdb-model.md`                                               | §2值类型 §3属性结构 §4填写细则                                    |
| CMDB 实例操作（写规范）                      | `concepts/cmdb-instance.md`                                            | 查约束→写→failed_count判定                                         |
| orderInfo（脚本入参结构）                    | `concepts/order-info.md`                                               | formData是list[{key,values}] SELECT值是对象                          |
| API 调用（鉴权/翻页/客户端基座）             | `concepts/api-calling/api-calling.md` + `api-samples.py`             | 内网/网关/OpenAPI 三模式                                             |
| instanceId 规则                              | `concepts/instance-id.md`                                              | ID生成                                                               |

**引用原则**：本工作流只讲「阶段/步骤/验收点/坑提示」，细节（字段名/取值/原理）一律指向上表的唯一来源，**不在工作流里重复**。

---

## 附录 C：迭代同步纪律（贯穿阶段六）

> 改任一环节都要同步关联资源，避免"改了 A 但 B 还是旧版"导致不一致：

| 改动 | 必须同步 |
|---|---|
| 改表单 formDefinition | 推新版本 → 设表单主版本 → 流程节点重绑（`setFormVersion` 刷新，表单主版本切换后流程要重新绑） |
| 改脚本 content | `tool_update` 同步工具库（流程执行取工具库 content，本地改 ≠ 工具库更新） |
| 改流程 nodeSettings/scriptSettings | 已 done 版本不可原地改 → `baseVersionId` 克隆新版本 → 改 → 定稿 → 设主 |
| 改服务位置/分类 | 删旧重建（或 `updateServiceInstance` 改 catalogId） |

> ⚠️ 迁移纪律：所有脚本/调用禁硬编码 host/org/IP——用 `EASYOPS_LOCAL_IP`/`EASYOPS_ORG` 等内置变量（脚本）或 manifest 的 host（调用），保证跨环境可迁移。

