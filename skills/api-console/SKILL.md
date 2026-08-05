---
name: api-console
description: 用于任意已对接平台的 API 资产建设与编排执行（平台可拔插：主干通用，按 adapter 接入新平台）。两大主线——(1)建库：把后端契约/swagger + 前端 openapi 半自动注册成标准化"API 卡片"库；(2)编排：按自然语言需求生成调用 DAG（支持读查询聚合与写操作创建/更新/回滚），确定性校验后真调执行。覆盖「跨接口编排 API 调用」「注册/补全 API 卡片」「解析后端 API 资料/swagger」「按自然语言查数据/串联多个接口」「单步调一个接口探查」「问平台业务知识（字段类型/ID规则/配置约束）」「生成平台制品（表单/流程等）并校验合规」。务必在用户提到 API 编排/卡片库/跨接口串联/写操作自动化，或某已对接平台（工单/流程/CMDB/领域模型/表单设计等）时使用本 skill，即便没明说"编排"或"卡片"。
version: 0.1.0
---
# api-console

平台中性的 **API 资产建设 + 调用编排** 工具（对接的系统可拔插，按 adapter 接入）。两大主线：先把散乱的后端资料/前端 openapi 沉淀成可调的**卡片库**，再按自然语言需求把卡片**编排成调用链**并真调执行。配套**领域知识库**（字段/规则/校验脚本）保证产出有据、合规可验。

沿用 `browser-recorder` 范式：**脚本做确定性脏活，LLM 做语义**——LLM 只在「补卡片语义」「生成 DAG」两处介入，不直接发 HTTP（它出 DAG，`execute_dag.py` 按 DAG 发请求，确定性、可审计、挡幻觉）。

## 你要做什么？→ 选路径

动手前先判断需求属于哪类，走对应能力（不必通读全文）：

| 用户需求                                                                      | 走哪条                   | 入口                                                       |
| ----------------------------------------------------------------------------- | ------------------------ | ---------------------------------------------------------- |
| 把后端契约/swagger/前端 openapi 整理成可调接口库                              | **建库**           | §1 后端解析 + §2 卡片注册                                |
| 用自然语言查数据 / 串联多个接口（读）                                         | **编排（读）**     | §4 DAG                                                    |
| 用自然语言做创建/更新/删除（写）                                              | **编排（写）**     | §4 DAG（含确认闸 + 回滚）                                 |
| 只调一个接口看看 / 探查 / "查到就继续查不到换路"                              | **单步真调**       | §5`call_card`                                           |
| 问业务知识（字段类型/ID规则/配置约束/流程合规）                               | **知识库问答**     | §6 +`references/knowledge.md`                           |
| 生成 ITSM 表单/流程/**工具包/巡检套件**等平台制品                       | **知识库产出前置** | §6（先找规则/样例/校验脚本，产出后跑校验）                |
| 开发独立调用脚本（脱离 skill 编排、直接发 HTTP 的程序，如导出/汇总/定时集成） | **调用脚本开发**   | §6「脚本开发铁律」（必先复用`api-calling/` 客户端样例） |

> 不确定走哪条？读 §7「能力边界与选型」的 call_card vs DAG 冻结线。

> ⚠️ **「开发/做一个 X」意图分流（高频误判，已踩过）**：「开发个<平台>工具 / 做个工具包 / 做个巡检套件」先判**产物形态**——
>
> - 产物是**平台制品**（AutoOps 工具包 `.tool.tar.gz`、巡检套件 `inspector_*.tar.gz`、表单、流程……要导入平台的）→ **知识库产出前置**：扫 `_index.yaml` 的 **`modules.*` 各条目**（`xxx-package-dev` / `xxx-suite-dev` 这类"制品构造/开发态"知识）拿结构规则与配套脚本，**不是**走调用脚本开发；
> - 产物是**独立脚本**（直接发 HTTP、在脚本里调平台 API、不导入平台）→ 才走**调用脚本开发**（api-calling 基座）。
>   **误判样本**：「开发个 easyops 工具（下载文件分发文件包）」= 产物是工具包制品，应命中 `modules/autoops_tool/tool-package-dev`（tags 含"工具包"），而非只扫 concepts 找 api-calling。检索时 **concepts 与 modules 全量扫**，别只扫 concepts。

## 意图识别铁律（贯穿所有任务，最高优先）

**「平台里有多少 X / 查 X 列表 / 找一下 X」这类问法，X 指的是平台业务实体（如工具、用户、工单、模型），问的是运行时数据——必须走 §4 编排或 §5 单步真调拿真实返回，禁止用 `find|wc -l` 数 `registry/` 卡片文件。**

- 数卡片文件只回答一种问题：「skill 当前对接了多少个接口/某模块几张卡」——即问 **skill 资产清单**时才用。
- 二者混淆是最高频误判：问「平台里有多少个工具」≠「卡片库里有多少张工具接口」。前者真调对应列表接口看 `data.total`；后者才数文件。
- 判不准时默认按**业务实体数据查询**处理（真调），而非数资产——查不到数据是正常信息，数错资产是真错。

## 知识前置铁律（贯穿所有任务）

凡涉当前平台实体的任务（问答/编排/注册/产出物设计/**开发调用脚本**），**动手前先扫 `platforms/<platform>/knowledge/_index.yaml` 找规则与配套校验脚本**；系统相关的问答与需求**必须有数据来源**（引用知识文件 + 是否经真实系统核对），不清楚不猜测、明说"不能确定"。详见 `references/knowledge.md`「总原则」。

> ⚠️ **扫索引 = concepts + modules 全量扫**（已踩过）：`_index.yaml` 分 `concepts`（全局概念，如 api-calling）和 `modules.<模块>`（模块知识，如 `autoops_tool/tool-package-dev`）两段——只扫 concepts 会漏掉模块制品知识。检索时两段都要按「需求关键词 ↔ tags/name/scope/note」匹配；「做工具包/套件/表单」类需求重点看 `modules.*` 下的 `*-dev` 条目（制品构造态知识）。

> **脚本开发铁律（易漏，单列）**：要写任何**直接发 HTTP 的平台调用脚本**（导出/汇总/定时集成等脱离 skill DAG 编排的独立程序），**必须先读 `platforms/<platform>/knowledge/concepts/api-calling/` 的客户端样例并复用其通用基座**——鉴权头、URL 拼接、`code` 判定、**翻页**都继承样例验证过的实现，**不得从头重写**（自己重写必然漏翻页/鉴权细节，已踩过）。列表数据必须翻页（`page` 递增直到 `len(items) < page_size`），禁止靠"当前数量小"猜一个 `pageSize` 上限交差。
>
> ⚠️ **复用边界（防耦合）**：客户端样例是「平台 API 调用方式」的**通用基座**（鉴权 + 翻页 + 签名机制），**只复用它的机制，不得把具体业务接口/实体逻辑塞进去**。即——调用脚本自己写"调哪个 path、取哪个字段、版本怎么选"这类**业务特定**逻辑，借客户端发请求；**禁止**给客户端基座加 `list_xxx`/`export_xxx` 之类业务方法污染通用样例。通用机制 vs 业务逻辑必须分离。

## 能力一览

1. **建库**（`parse_backend.py` + `register_cards.py`）：后端资料 → adapter 标准化 `contracts.yaml` → 抽骨架卡片 → LLM 补语义 → 入库 `registry/`。这是编排的前置——没卡片就没法编排。
2. **编排**（`verify_dag.py` + `execute_dag.py`）：自然语言 → LLM 出 DAG → 确定性校验 → 真调执行。支持读（查询聚合）与写（创建/更新/回滚）。
3. **单步真调**（`call_card.py`）：反应式场景直接调单卡片拿原始 `body.data`，在对话里自主决策下一步。
4. **知识库**（`knowledge/`）：领域知识与平台产出物的合规规则，与卡片分离。问答检索 + 产出前置两类消费。

## 完整工作流

### 0. 环境准备（首次）

```bash
bash skills/api-console/scripts/setup.sh
```

装到 `~/.local`（隔离工具环境），`api-console` 进 `~/.local/bin`。需 uv（或 pipx/pip）+ Python>=3.9。开发态免装可用 `bash skills/api-console/scripts/run.sh api-console <子命令> ...`（dev 壳，转发 `uv run --project`，不污染全局）。

> ⚠️ **调用前 `cd` 到用户工作目录（项目根）**——`api-console` 把调用 cwd 钉为产物根（`API_CONSOLE_WORKDIR`），`tmp/orchestrate/` 和 `platforms/` 落此 cwd 下。

#### manifest 初始化（多环境）

每个平台维护 `platforms/<platform>/manifest.yaml`，结构为 `default_env` + `environments: { <env>: {...} }`（详见 `references/output-format.md`）。真实 manifest 含 cookie / aksk 凭证故**不入库**（`.gitignore` 忽略 `platforms/*/manifest.yaml`），仓库只留 `manifest.example.yaml` 模板。首次接入：

```bash
cd <用户工作目录>
cp platforms/<platform>/manifest.example.yaml platforms/<platform>/manifest.yaml
# 编辑 manifest.yaml：填 host / gateway_base / 鉴权块（org/user/aksk 等，按平台 adapter 需要）
api-console extract-auth --platform <platform> --env <env>
# → 自动从浏览器 profile 提 cookie，写回 environments.<env>.auth.session_cookie.cookie
```

`--env` 不传时用 manifest 的 `default_env`。多环境（prod/dev/test…）在 `environments` 下并列结构相同的块，按需切换。

### 1. 后端资料解析

把后端 API 资料归集到 `platforms/<platform>/sources/raw/backend/`（raw/ 为全端原始资料，backend/ 为后端资料子目录），然后解析：

```bash
cd <用户工作目录>
api-console parse-backend \
  --platform <platform> \
  --in platforms/<platform>/sources/raw/backend \
  --out platforms/<platform>/sources/backend/parsed/contracts.yaml
```

- 主干按目录约定 `<workdir>/platforms/<platform>/sources/backend/adapters/` 发现 adapter
- 由该平台的契约 adapter 解析其契约格式（如 JSON + 路由表），输出标准化 `contracts.yaml`
- **诚实反馈**：资料格式无 adapter 能识别（detect 置信度 0）→ 报"不支持的格式 + 需提供什么"

> adapter 在 `platforms/<platform>/sources/backend/adapters/`（平台数据，不随 skill 分发）。新增平台 = 加新 adapter 文件，skill 主干不改。详见 `references/adapter-interface.md`。

### 2. 卡片注册（两阶段 + LLM 补语义 + review）

**阶段 a：extract 抽骨架 + path 对齐**

```bash
api-console register-cards extract \
  --platform <platform> \
  --openapi platforms/<platform>/sources/frontend/openapi/<某模块>-openapi.yaml \
  --backend-contracts platforms/<platform>/sources/backend/parsed/contracts.yaml \
  --out tmp/orchestrate/register/<module>/_draft.yaml
```

- 以前端 openapi 为基准遍历接口，抽骨架卡片（name/method/path/request/examples）
- **path 多来源对齐**（见 `references/card-schema.md`）：后端契约（backend_contract/high）> gateway 剥离（gateway_strip/medium）> 前端原样（frontend_raw/low）
- **outputs 锚点骨架自动生成**：命中后端契约时从其 `response.fields` 确定性生成（`type` 含 `[]`→`list_full`/`list_ids`，`instanceId`/`total` 等通用判定，**不依赖业务字段名**），标 `confidence.outputs=high`；未命中则留空待 LLM 推断（low）
- requires/rollback/tags 留空，标低置信（待 LLM 补）

**阶段 b：LLM 补语义**

读 `_draft.yaml` + 前端 openapi + 后端 contracts.yaml，为每张卡片补：`module` / `tags` / `summary` / `description` / `outputs`（精修骨架）/ `requires` / `rollback` / `confidence`。补语义的 prompt 模板与字段规则见 `references/card-schema.md`，覆盖写回 `_draft.yaml`。

**阶段 c：用户 review（人）**

按 confidence 分组展示：高置信扫一眼，低置信（requires/outputs 等）重点补，特别关注 `path_source=frontend_raw`（未经后端印证）的卡片。

**阶段 d：commit 入库**

```bash
api-console register-cards commit \
  --platform <platform> \
  --in tmp/orchestrate/register/<module>/_draft.yaml
```

校验 `_draft.yaml` + 卡片 `validate()` → 拆分单卡片文件 → `registry/<module>/<name>.yaml` → 更新 `_index.yaml`。

**`_index.yaml` 重建（兜底）**：手工删卡/误改索引/索引与文件不一致时，从落盘卡片重建（保留旧 module 的 desc/tags）：`api-console register-cards rebuild_index --platform <platform>`。

**批量注册已录制模块**（非常用）：一次注册多个前端模块，LLM 编排现有 extract/commit 命令，支持全量/范围/单个 + 覆盖/增量。详见 `references/batch-register.md`。

### 3. 鉴权准备

执行编排/单步真调前，从 recorder 持久化 profile 提取 cookie 写回 manifest：

```bash
api-console extract-auth --platform <platform> [--env <env>]
```

- `--env` 选环境（多环境 manifest）；不传用 `default_env`。详见 §0 manifest 初始化。
- 读 manifest 的 `auth_source` 指向的 `tmp/profiles/<host>/Default/Cookies`（Chromium SQLite，pycookiecheat 解密）
- 新形态（`environments`）：cookie 文本级定点写回 `environments.<env>.auth.session_cookie.cookie`，保留其他环境块 / 注释 / 键顺序
- 旧形态（无 `environments`）：维持原 `auth/cookies.json` + `meta.json` 落盘行为
- cookie 失效（执行时 401/302）→ 重新跑此命令重提

> cookie / aksk 明文存于 `manifest.yaml`（因 manifest 已 gitignore，不入库）。`auth/`（旧形态落盘）亦在 `.gitignore`（敏感，分发时剔除）。

### 4. 编排执行（LLM 出 DAG → verify → execute）

skill 的核心用法。**LLM 读本节 + `references/dag-schema.md`，按以下流程驱动**：

**步骤 a：LLM 生成 DAG**

读用户自然语言需求 + `registry/_index.yaml`，输出结构化 DAG（JSON）：

```json
{
  "goal": "找出关联处理人字段的领域模型",
  "steps": [
    {"id": "s1", "card": "searchStandardField",
     "params": {"q": "处理人"},
     "output": {"bind": "fields", "from": "list_full"},
     "assert": {"fields.length > 0": "未找到处理人字段"}},
    {"id": "s2", "card": "searchDomainModel", "depends": ["s1"],
     "params": {"standard_field": "${join(s1.fields.instanceId, ',')}"},
     "output": {"bind": "model_ids", "from": "list_ids"}},
    {"id": "s3", "card": "getDomainModel", "depends": ["s2"],
     "foreach": "${s2.model_ids}", "params": {"modelId": "${item}"},
     "output": {"bind": "details", "from": "detail"}}
  ],
  "result": "${s3.details}"
}
```

DAG 语法（4 种 `${}` 表达式、depends、foreach、assert、when、output.bind/from）见 `references/dag-schema.md`。

**步骤 b：verify_dag 校验（确定性，挡幻觉）**

LLM 调用 `verify_dag.verify(dag, cards)`，返回 `VerifyReport`。**关键：`VerifyReport.has_write` 必须透传给 execute**（含写卡片时 execute 据此开确认闸）。校验失败 → 错误回传 LLM 修正 DAG（上限 2 次）。12 条规则（卡片存在/依赖闭环/参数引用/必填/写标记/assert/foreach/锚点/bind重名/when语法/rollback引用）详见 `references/dag-schema.md`。

**步骤 c：execute_dag 执行（确定性）**

调用方在执行前先 `load_manifest(platform, env)` 选定环境并扁平化（`env` 在加载层消化，`execute_dag` 签名不变），再把扁平后的 manifest 传给 execute：

LLM 调用 `execute_dag.execute(dag, cards, adapter, manifest, contracts=..., has_write=<verify.has_write>, yes=<用户授权>, input_fn=input)`：

- **写确认闸**：`has_write=True` 且 `yes` 非 True 时，execute 先打印写计划 + 回滚预案等用户输 `y`（非 `y` 返回 `None` 取消；`yes=True` 跳过闸）。写操作有副作用，必须人工把关。
- **when 分支 / 回滚**：`step.when` 为假则跳过该步（互补 when 做"存在则更新/不存在则新建"）；写步骤失败时按卡片 `rollback` 声明逆序回滚已成功步骤（best-effort，未声明 rollback 则跳过）。
- 其余执行机制（拓扑序 / foreach 并发 / 锚点提取 / HTTP 重试 / 错误分类）详见 `references/dag-schema.md`。

execute 返回 `ExecutionResult`（result + context + log + skipped + rollback_log），取消时返回 `None`。LLM 把 result 格式化呈现给用户。

> 编排执行产物落 `tmp/orchestrate/<时间戳>/`（plan.json / execution.json / result.json）。详见 `references/output-format.md`。

### 5. 单步真调（call_card）

简单/探查/反应式场景，直接调单卡片拿原始 `body.data`，不必提前声明整个 DAG：

```bash
cd <用户工作目录>
api-console call-card \
  --platform <platform> --card <name> [--param k=v]... [--allow-write] [--env <env>]
```

- `--env` 选环境（多环境 manifest）；不传用 `default_env`（详见 §0 manifest 初始化）
- 输出原始 `body.data`（不做 outputs 锚点提取）+ `meta`（含 `biz_code`/`biz_message`/`url`/`http_status`）
- `--param` 是 `key=value` 字面量，**不解析 `${}`**（单步无上游 step；要 join/投影 LLM 在对话里算）
- 默认只读；`--allow-write` 受控放行 write 卡片
- **业务码非 0 不报错**：`code != 0` 时 meta 透出 code/message，交 LLM 判断（探查场景"查不到"是正常信息）

> 鉴权同编排：执行前 `api-console extract-auth --env <env>` 提 cookie；401/302 重提。

### 6. 知识库（问答 + 产出前置）

领域知识（字段类型/配置约束/跨模块概念/平台产出物合规规则）放 `platforms/<platform>/knowledge/`，与卡片分离。两类消费：

- **问答**：用户直接问业务知识 → 扫 `_index.yaml` 检索 → 读正文 → 按 `completeness`/`last_verified` 决定可信回答还是明说"不能确定"。
- **产出前置**：设计/生成平台制品（BPMN 流程/表单/配置/**调用脚本**）前，先扫 `_index` 找规则、样例、**配套校验脚本**（如流程的 `check_compliance.py`、表单的 `check_form_design.py`、**调用脚本的 `concepts/api-calling/api-samples.py`**），产出后跑校验自证合规。**写调用脚本时 `api-samples.py` 是必复用的客户端基座**（见上文「脚本开发铁律」的复用边界：只继承鉴权/翻页通用机制，业务接口逻辑写进脚本自身，不污染基座）。

缺口治理（`_gaps.yaml` 登记/追踪/关闭/对照接口发现）见 `references/knowledge.md`「缺口治理」。

## 7. 能力边界与选型

**call_card vs DAG 冻结线**：

- 单接口查询 / 临时验证卡片 / "查到就继续、查不到就换路"的反应式决策 → **call_card**
- 多步跨接口、要 foreach/assert/when 分支/写回滚的确定性编排 → **DAG**

**编排边界**：

- **断言非 if/else**：assert 是"条件必须满足否则停"（终止语义）；分支用 `step.when`（条件为真才执行，互补 when 做"存在则更新/不存在则新建"）
- **表达式限 4 种**：`${step.bind}` / `${step.bind.field}` / `${item}` / `${join(...)}`，其余拒绝（挡幻觉）。完整语法表 + when 四形式 + 写确认闸/回滚机制见 `references/dag-schema.md`
- **path 参数名差异**：前端 `{modelId}` vs 后端 `{instanceId}`，占位符按位置通配对齐（不阻塞真调）

**call_card 单步**：默认只读；write 卡片需 `--allow-write` 显式放行（单步、不进 DAG 编排）。

## 输出位置

```
platforms/<platform>/                  # 平台包（长期资产，可分发，auth/ + manifest.yaml 不入库）
├── manifest.yaml                      # 多环境（含 cookie/aksk 凭证，gitignore）
├── manifest.example.yaml              # 模板（入库，占位符）
├── sources/{frontend,backend}/        # 前端 openapi + 后端 contracts + adapter
├── registry/<module>/*.yaml           # 卡片库（接口怎么调）
├── knowledge/                         # 领域知识（业务语义 + 合规规则 + 校验脚本）
│   ├── concepts/                      # 全局概念（instanceId/值类型/CMDB模型）
│   └── modules/<module>/              # 模块内字段细节 + 配套校验脚本
└── auth/cookies.json                  # 旧形态鉴权落盘（gitignore）；新形态 cookie 在 manifest

tmp/orchestrate/<时间戳>/              # 编排执行临时产物（可清理）
tmp/orchestrate/register/<module>/     # 卡片注册草稿区
```

> venv 属于能力 project（`projects/api-console/.venv`），与产物分离。

## 额外资源

### Reference Files

- **`references/card-schema.md`** — 卡片字段定义、confidence 评级、path_source 三级、字段来源分工、LLM 补语义 prompt 要点
- **`references/dag-schema.md`** — DAG 结构、step 字段、4 种表达式语法表、assert/when/foreach、写编排与回滚、错误分类表
- **`references/adapter-interface.md`** — detect/parse 契约、Confidence 分流、新增 adapter 步骤
- **`references/batch-register.md`** — 批量注册已录制模块（全量/范围/单个、覆盖/增量模式）
- **`references/knowledge.md`** — 领域知识库（问答规则、产出前置、缺口治理，与卡片分离管理）
- **`references/usage.md`** — 详细使用、FAQ、cookie 失效排查、常见错误定位
- **`references/output-format.md`** — tmp/orchestrate/ 与 registry/ 产物结构、_index.yaml 一致性约束

### 相关 skill

- `browser-recorder`：录制前端操作产出 openapi + 持久化登录态（本 skill 的上游）
