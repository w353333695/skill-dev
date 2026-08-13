# 模块接入需求 Prompt 模板

> 复制下方模板，填入 `{{...}}` 占位符，作为 onboarding 需求发给 LLM。
> 模板约束 LLM 严格走探索→规划→确认→接入→真调→汇报流程，禁止猜测/够用就行。
> 模板沉淀自 collector_plugin_service 接入实战，已内化所有踩坑教训。

---

## 模板正文（复制此行以下）

```
@api-orchestrator onboarding 接入 {{模块名}}

## 源码/契约位置
{{后端源码路径 或 API文档URL 或 抓包文件}}，{{是否有官方 CLI/contracts（若有给路径）}}

## 接入目标
接入该模块的 {{列出要接的能力，如 CRUD/启用/导出/导入/升级/执行...}} 能力。
另外搞清该模块的 {{所有对象类型/子类型}} 的能力、文件结构、每个配置项的
意义|值类型|枚举|正则|约束，录入，让系统能 {{根据需求开发/生成/交付什么}}。
所有细节探索清楚，不允许猜测，不允许够用就行的思维。

## 接入前必答（LLM 先问清这些再动手，缺关键项停下问用户）
1. 真调环境可达性（host/org/cookie/user/端口），缺失则只能离线交付
2. deployment 归属：并入现有（同套系统不同实例/迁移场景）还是新建独立 deployment
3. 真调范围：离线交付 or 全程真调（含写操作）
4. 运行时约束：{{脚本语言版本/特殊环境/已装的库/平台公约}}（以实际运行时为准，不信文档默认）
5. 跨实例关系：多环境是同系统不同实例，还是独立系统
6. 业务前置门禁：开发/生成产物前，业务上该先确认什么（如查现有资源、设计需客户拍板的属性）

## 流程约束（LLM 必须严格遵守）
### 探索阶段
- 派多个同步 Explore agent 并行深挖源码（禁用 background agent，session 退出会丢结果）
- load-bearing 事实（端点存在性/端口/字段/枚举）必须自己 grep 实锤，不全信 agent 结论
- 找权威契约源（OpenAPI/官方 CLI contracts/源码路由表），区分源码版本 vs 实际部署（源码可能落后）
- 双源交叉验证：过时文档 vs 源码冲突时，以实际运行时为准；查不到的标 gap，不编
- 每个结论带 file:line 引证

### 规划阶段
- 探索完成后先列分阶段规划给我确认，不直接开干
- 规划要覆盖：探索→权威源→api-cli清单→objects/systems/entities→flows→真调→lint 全链路

### 接入阶段（产物落 platforms/<deployment>/）
- 套用 api-orchestrator 的 onboarding 流程（references/onboarding.md + onboarding-playbook.md）
- api-cli 清单：body schema 内联无 $ref；required 双义（params.bool / schema.父级[]string，不在 property 写 required:true）；property 用 description 非 desc；multipart 端点标「走 SDK」
- 每对象/字段/副作用带 source:file:line（lint source 证据门禁）
- 知识自包含：不引用 tmp/ 或 platforms 外文件；source 仅溯源非知识依赖

### 业务前置门禁（生成产物类流程必加，易漏）
- 生成产物前必须先走：需求确认（向客户对齐）→ 现有资源确认（系统查是否已有）→ 设计+客户确认（无则设计，必须客户拍板）
- 禁止跳过直接生成

### 真调阶段
- 读路径 api-cli 直接调；multipart/binary 走 curl -F 或 SDK；写操作测试空间
- 坑即时回流 systems/objects（不进 memory，platforms 是唯一真相来源）
- list 计数坑/响应 wrapper 格式实测确认记 runtime

### 汇报阶段
- 每阶段 checkpoint 汇报进度
- gap 如实标注（查不到标「未知-待捕获」，不硬填）
- 最终交付：lint 0 ERR + 真调回归通过 + gap 清单 + 遗留风险

## 验证门禁（交付前必过）
- lint-platforms.py <deployment> --api-cli bin/api-cli → 0 ERR
- api-cli --spec X --help / explain / --dry-run 三验通过
- 真调回归（读路径必过，写路径按真调范围）

先完成探索、规划，列规划给我确认后再接入。
```

---

## 用法说明

1. **填占位符**：`{{模块名}}` / `{{源码路径}}` / `{{要接的能力}}` / `{{运行时约束}}`（运行时约束不填就让 LLM 第一步问你）
2. **复制模板正文**（两个 ``` 之间）发给 LLM
3. LLM 会：先问「接入前必答 6 项」→ 探索 → 列规划给你确认 → 接入 → 真调 → lint → 汇报

## 这次 collector 接入若用此模板，填法示范

```
@api-orchestrator onboarding 接入 collector_plugin_service

## 源码/契约位置
@data/sources/backend/HyperInsight/collector_plugin_service
（另有官方 CLI：/workspace/tmp/easyops-cli 含权威 contracts）

## 接入目标
接入套件的 curd、启用、导出、导入、升级能力。
另外搞清所有类型套件的能力、文件结构、每个配置项的意义|值类型|枚举|正则，
录入，让系统有根据需求开发套件、交付套件压缩包的能力。

## 接入前必答
1. 真调环境：host 172.30.0.90 / org 8888 / user easyops / cookie PHPSESSID=...
2. deployment：与现有 demo 同一套 EasyOps 系统（迁移场景），合并到 demo
3. 真调范围：全程真调，所有都做
4. 运行时约束：采集脚本用 Python2.7（agent 默认），print语句/requests/subprocess不用timeout，
   不能用 __future__ print_function（运行时注入破坏顶部）
5. 跨实例：.90 和 .232 同一套系统不同实例
6. 业务前置门禁：开发套件应先在 CMDB 确认是否有模型并向客户确认；没有才设计模型，
   模型属性、关系向客户确认
...
```
