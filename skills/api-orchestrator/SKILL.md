---
name: api-orchestrator
description: 通用 API 编排 skill——自然语言需求 → 跨系统调用编排。两个模式：onboarding（从 API 文档/抓包/源码/场景 生成 platforms 资料，接入新能力域）+ orchestration（用已有资料把需求编排成调用执行）。调度靠 LLM 读本 SKILL 的决策树，执行靠 bash 调 api-cli，领域知识靠 platforms/ 资料。当用户要做跨系统 API 串联/对接新系统/批量编排/流程开发与迭代时使用，即便没明说"编排"。
---

# api-orchestrator（通用 API 编排）

把自然语言需求翻译成跨系统调用编排。**通用**——不知道任何具体系统/格式，全靠 `platforms/` 资料驱动。

## 定位：与任意系统解耦（勿过拟合到单一系统）

- **api-orchestrator = 基于 api-cli 的「系统知识整理 + 自动化调度」层**：执行能力来自 api-cli（声明式清单→命令树），调度能力来自 LLM 读本 SKILL 决策树，领域知识来自 `platforms/`。
- **和 api-cli 一样，与任意系统解耦**：本 skill 自身（`SKILL.md` / `references/` / `scripts/`）**零系统知识**——不含任何具体系统的字段、鉴权、端口、副作用。所有系统特定内容只活在 `platforms/<deployment>/` 实例里（可替换）。
- **接入新系统 = 加 platforms 资料，不改 skill**：onboarding 产出的资料归位到 systems/objects/entities/flows（schema 见 `references/asset-schema.md`），skill 代码/文档不变。因此不会对任何单一系统过拟合。
- **结论**：换系统、换部署，只换 `platforms/`；skill 本体复用。

## 核心范式

- **调度器 = 你（LLM）**：读本 SKILL 的决策树，对每个需求推理分派。没有代码调度引擎。
- **执行 = bash 调 scripts/run.sh**：统一执行入口（自动检测 PATH/build），每个系统是一份 api-cli 清单（spec）。
- **知识 = platforms/ 资料**：系统目录/实体映射/对象关系/流程模板/格式包，全部可替换。

## 调度决策树（拿到需求先走这个）

```
需求进来
│
├─[1] 是"接入新系统/加能力域"吗？
│      是 → onboarding 模式（见 references/onboarding.md）—— 从输入生成 platforms 资料
│      否 ↓
│
├─[2] 识别意图 + 复杂度——【读取纪律：先读 systems.yaml 的 capabilities 粗筛可达性 → 命中 verb 后按需读 spec/objects 段（grep+offset，禁 Read 全文）；详见 orchestration.md「读取纪律」】
│      · 读查询（单系统、单步）           → 直通挡
│      · 写操作（单系统、1-2 步）          → 确认挡
│      · 跨系统/多步/build/change/插件     → 规划挡
│
└─[3] 按挡位走（详见 references/orchestration.md）
       · 直通挡：查 systems.yaml → 调 api-cli → 后处理 → 答
       · 确认挡：查资料 → (search) → 展示确认 → 写 → 答
       · 规划挡：解析需求 → 查 entities/objects/flows → 生成 plan → 确认 → 分步执行 → 接线 → 校验 → (失败)回滚
```

## 资料（platforms/，可替换）

查 `platforms/<deployment>/`（默认 `demo`）：
- `systems.yaml` — 接入的系统 + 各自 api-cli spec 路径 + 流程格式声明
- `entities.yaml` — 跨系统实体映射（字段锚 + 转换）
- `objects.yaml` — 对象关系 + 副作用规则
- `flows/` — 流程模板（build 用）
- `formats/<fmt>/` — 格式包（BPMN/插件 等，跨部署复用）

资料 schema 详见 `references/asset-schema.md`（通用约定，零系统知识——适用于任何外接系统）。

## 执行

统一执行入口 `scripts/run.sh`（自动查找，skill 不感知环境）：
```bash
scripts/run.sh --spec <spec-path> <resource> <verb> [args] [--print-curl|--dry-run]
# 例：scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
```
`scripts/run.sh` 按序查找：① skill 自带预编译二进制 `bin/api-cli`（分发态，随 skill 打包，零环境依赖）→ ② PATH 上的 api-cli → ③ go build 增量编译（开发态）。

**先用 `--print-curl` 或 `--dry-run` 预览请求**，确认无误再真调（写操作尤其）。

## 模式与写保护（防 platforms 污染）

skill 两种模式，决定能否写 `platforms/`：

| 模式 | 触发 | platforms/ | 用途 |
|---|---|---|---|
| **orchestration**（默认）| `/api-orchestrator`（不带 onboarding）| **只读** | 自然语言 → 编排执行；非专业人员 |
| **onboarding** | `/api-orchestrator onboarding <input>` | **可写** | 接入/更新资料；开发者 |

**写保护纪律**：
- **orchestration 模式下 platforms/ 只读**：禁止 Write/Edit platforms 任何文件、禁止跑 onboarding 流程。只读 systems/objects/entities/flows 做编排，写只发生在远端系统 API（且写操作必确认）。
- **onboarding 模式才写 platforms**：且必须 ① 过输入门禁（契约/文档/源码 ≥1）、② 改完跑 lint（0 ERR）。详见 `references/onboarding.md`。
- **分发加固**：分发后跑 `scripts/setup.sh`——确认 bin/api-cli 就绪 + `chmod -R a-w platforms/` 锁只读 + lint 自检。onboarding 改 platforms 前先 `chmod -R u+w`，改完锁回。Go skill 零环境依赖：bin/api-cli 预编译二进制随 skill 打包，不需要 setup 装 runtime。

## 关键纪律

- **不硬编码任何系统/格式**：所有"调什么/字段怎么接/怎么校验"查 platforms 资料。
- **写操作/复杂操作必确认**：展示 plan 或影响面，用户确认后执行。
- **状态持久化**：复杂编排的中间产物写 `tmp/<task>/`，跨 bash 步传递。
- **失败回滚**：记录已执行步骤，失败时反向调 remove/delete。
- **platforms 只读（orchestration 模式）**：非 onboarding 不得 Write/Edit platforms 文件（防资料污染）；onboarding 改完必 lint。
- **onboarding 输入门禁**：契约 / API 文档 / 后端源码至少一个才开工；缺则停下问用户（详见 `references/onboarding.md` 步 1）。
- **产物用 lint 自检**：onboarding 或更新 platforms 后跑 `scripts/lint-platforms.py <deployment>`，**0 ERR 才合格**（校验 schema + 引用闭合；详见 onboarding.md 步 7）。
