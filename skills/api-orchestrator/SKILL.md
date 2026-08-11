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
- **执行 = bash 调 scripts/run.sh**：统一执行入口（读 manifest.sh 自动定位 binary，Go/Python 通用），每个系统是一份 api-cli 清单（spec）。
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

统一执行入口 `scripts/run.sh`（读 manifest.sh 自动定位 binary，skill 不感知环境）：
```bash
scripts/run.sh --spec <spec-path> <resource> <verb> [args] [--print-curl|--dry-run]
# 例：scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
```
`scripts/run.sh` 读 `manifest.sh` 获取 binary name，按序查找：① `bin/<name>`（预编译，零环境依赖）→ ② PATH → ③ go build（开发态）。通用模板，Go/Python skill 共用。

分发打包：`scripts/pack-go.sh --skill <name> --target <os/arch> [--dist]` 读 manifest 编译到 `bin/` + 可选打 tar.gz。**无 setup**——Go 预编译二进制随 skill 打包，不需要安装 runtime、不配 PATH、不要 go。

**安全调用**：读操作直接调；写操作先展示影响面（要建/改/删什么），用户确认后执行。`--print-curl`/`--dry-run` 是排查工具（首次用某 verb / 请求报错时用），非常规步骤——真正的安全来自确认，不是预览 curl。

**调用姿势（防污染）**：`scripts/run.sh` 用**绝对路径**调，cwd 保持用户工作目录——勿 `cd` 进 skill 再用相对路径，否则临时产物会写进 skill 目录（见「关键纪律」状态持久化）。body 优先用 `--body '<json>'`（inline，api-cli UX 改造后支持，零落盘），其次进程替换 `--body-file <(printf '%s' '<json>')`，避免任何临时文件。

**api-cli UX 改造后行为要点**（2026-08-11，`worktree-api-cli-ux` 落地）。
当前 `bin/api-cli` 已是该版本（`go build` 自 `projects/api-cli`）——下列行为均已生效：
- **错误默认人类可读到 stderr**（`error: <code>: <msg>`）——`--q` 等未知 flag 不再静默，会清晰报错。`--format=json` 时错误输出 JSON。
- **分页 total 在 stderr**（`{"_meta":{"total":N}}`），stdout 仍是纯 NDJSON（读 stdout 的脚本不受影响；要 total 读 stderr）。⚠️ 空结果（total=0）时 stderr 无输出、stdout 也空——total 绑定首条 item，无 item 即不输出；此时 **exit 0 即代表 0 条**（错误走 exit≠0 且可读），计数配方见 `systems.yaml` 中声明了 `common_models` 的 system 段（`count_recipe`）。
- **`--all` 触顶 exit 4**（硬上限 10000 条/1000 页，结果可能不完整，stderr 有 warning）。
- **`--print-curl` 默认遮蔽 auth**（Cookie/Authorization 显示 `<redacted>`，加 `--reveal-auth` 显真值）；curl 现含 Host/Content-Type/query（完整可复现）。
- **`--help` 列 path/query/body 参数分类**（不再只列 global flag）。

## 模式与写保护（防 platforms 污染）

skill 两种模式，决定能否写 `platforms/`：

| 模式 | 触发 | platforms/ | 用途 |
|---|---|---|---|
| **orchestration**（默认）| `/api-orchestrator`（不带 onboarding）| **只读** | 自然语言 → 编排执行；非专业人员 |
| **onboarding** | `/api-orchestrator onboarding <input>` | **可写** | 接入/更新资料；开发者 |

**写保护纪律**：
- **orchestration 模式下 platforms/ 只读**：禁止 Write/Edit platforms 任何文件、禁止跑 onboarding 流程。只读 systems/objects/entities/flows 做编排，写只发生在远端系统 API（且写操作必确认）。
- **onboarding 模式才写 platforms**：且必须 ① 过输入门禁（契约/文档/源码 ≥1）、② 改完跑 lint（0 ERR）。详见 `references/onboarding.md`。
- **分发加固**：`pack-go.sh --skill <name> --target <os/arch> --dist` 读 manifest 编译到 bin/ + 打 tar.gz → 随 skill 分发。零 setup——Go 预编译二进制随包走，不需要安装 runtime。onboarding 改 platforms 前先 `chmod -R u+w`，改完锁回。

## 关键纪律

- **不硬编码任何系统/格式**：所有"调什么/字段怎么接/怎么校验"查 platforms 资料。
- **写操作/复杂操作必确认**：展示 plan 或影响面，用户确认后执行。
- **状态持久化（tmp 落点纪律）**：复杂编排的中间产物跨 bash 步传递时——① **优先不落盘**：body 用进程替换喂 `--body-file <(printf '%s' '<json>')`，能用内联/stdin 就不写文件；② **必须落盘时**用绝对路径锚定**调用方 cwd**（`$PWD/.api-orchestrator/tmp/<task>/` 或 `mktemp -d`），**严禁写 skill 目录**——勿 `cd` 进 skill 再用相对 `tmp/`，那会把运行时垃圾写进分发物，且顶层 `.gitignore` 的 `tmp/` 会让 git 静默、污染隐形。
- **失败回滚**：记录已执行步骤，失败时反向调 remove/delete。
- **platforms 只读（orchestration 模式）**：非 onboarding 不得 Write/Edit platforms 文件（防资料污染）；onboarding 改完必 lint。
- **onboarding 输入门禁**：契约 / API 文档 / 后端源码至少一个才开工；缺则停下问用户（详见 `references/onboarding.md` 步 1）。
- **产物用 lint 自检**：onboarding 或更新 platforms 后跑 `scripts/lint-platforms.py <deployment>`，**0 ERR 才合格**（校验 schema + 引用闭合；详见 onboarding.md 步 7）。
