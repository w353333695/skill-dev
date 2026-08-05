# 批量注册已录制模块

当需要一次注册多个已录制的前端模块（`platforms/<platform>/sources/frontend/openapi/*-openapi.yaml`）时，LLM 按本流程编排现有的 `api-console register-cards extract/commit` 命令。

**这是 skill 驱动（非新脚本）**：复用现有命令 + LLM 的语义补全能力，主体逻辑在本文件，SKILL.md 只做入口指引。

## 前置

- 已跑过 `api-console parse-backend`（`sources/backend/parsed/contracts.yaml` 存在，供 path 对齐）
- `sources/frontend/openapi/` 下有待注册的模块

## 模式参数

批量注册由两个维度组合：

### 范围维度（选哪些模块）

| 模式 | 说明 | 示例 |
|---|---|---|
| **全量** | 遍历 `sources/frontend/openapi/*-openapi.yaml` 所有模块 | "把录制过的都注册了" |
| **范围** | 按 glob 匹配模块名（去 `-openapi.yaml` 后缀） | "ITSM-系统管理-*"、"工单*" |
| **单个** | 指定一个模块名 | "ITSM-领域模型管理" |

模块名 = openapi 文件名去掉 `-openapi.yaml`（如 `ITSM-领域模型管理-openapi.yaml` → `ITSM-领域模型管理`）。

### 策略维度（已注册的怎么办）

| 模式 | 说明 |
|---|---|
| **增量**（默认） | 对比 openapi 内容 hash：卡片记录的 `source.openapi_hash` 与当前 openapi 文件 hash 相同 → 跳过；不同（录制更新了）→ 重注 |
| **覆盖** | 已注册也重跑（extract 覆盖 _draft，commit 覆盖卡片文件 + 更新 _index） |

**增量判断的数据基础**（每张卡片 commit 时记录）：
- `source.openapi_file`：来源 openapi 文件名
- `source.openapi_hash`：openapi 内容 SHA256（变了→接口可能变→需重注）
- `source.recorded_at`：openapi 录制时间（`x-recorded-at` 字段，无则回退文件 mtime）
- `registered_at`：卡片注册时间

判断逻辑（LLM 用 Bash + python 实现）：
```python
import hashlib, yaml
from pathlib import Path
# 当前 openapi 的 hash
cur_hash = hashlib.sha256(open("openapi.yaml","rb").read()).hexdigest()
# 卡片记录的 hash
card = yaml.safe_load(open("registry/<module>/<name>.yaml"))
old_hash = card.get("source", {}).get("openapi_hash")
needs_reregister = (cur_hash != old_hash)  # hash 变了→重注
```

> 旧卡片（无 source 字段）按"需重注"处理（补全来源追踪）。`recorded_at` 是辅助参考（人读），程序判断以 hash 为准——hash 比 mtime 准（改标点会更新 mtime 但内容 hash 不一定大变，反之 hash 一定反映内容）。
>
> **module 名 vs openapi 文件名**：判断"已注册"要看 openapi 对应的卡片是否在 registry/。一个 openapi 可能跨多个 module。简化：增量模式下，对每个 openapi，检查它上次 extract 出的卡片（按 `source.openapi_file` 反查 registry/）是否都存在且 hash 匹配。

## LLM 编排流程

### 步骤 1：确定目标模块清单

按用户指定的范围 + 策略，列出要处理的模块。LLM 用 Bash 扫描：

```bash
# 全量
ls platforms/<platform>/sources/frontend/openapi/*-openapi.yaml | sed 's/-openapi.yaml//;s|.*/||'

# 增量过滤：对比 registry/ 已有 module（需先 extract 才知道 module 归属，
# 所以增量判断放在 extract 后、commit 前，见步骤 4）
```

向用户确认清单（尤其是覆盖模式，会重写已有卡片）。

### 步骤 2：批量 extract（逐个模块）

对清单里每个模块跑 extract，产出各自的 `_draft.yaml`：

```bash
api-console register-cards extract \
  --platform <platform> \
  --openapi platforms/<platform>/sources/frontend/openapi/<模块名>-openapi.yaml \
  --backend-contracts platforms/<platform>/sources/backend/parsed/contracts.yaml \
  --out tmp/orchestrate/register/<模块名>/_draft.yaml
```

每个模块的 `_draft` 含骨架卡片（path 已对齐）+ **outputs 锚点骨架（命中契约时 extract 已确定性生成）** + 低置信的待补字段（tags/summary/requires/rollback 等）。

### 步骤 3：LLM 批量补语义

LLM 读每个 `_draft.yaml` + 对应 openapi 的 response schema（契约命中的优先看 `_contracts_hits` 里的 response.fields），按 `card-schema.md` 的"LLM 补语义要点"补全：

- **module**（功能域名，snake_case）
- **tags**（3-5 个关键词）
- **summary**（一句话用途）
- **outputs 锚点**（精修 extract 生成的骨架：确认主列表字段、补 desc；契约未命中的从 description 推断）
- **requires**（前置条件）
- **rollback**（同模块找 delete）
- **confidence**（各字段评级）

批量处理的优化策略（多个模块时）：
- **先 extract 全部，再统一补语义**：避免频繁切换上下文。LLM 一次读多个 _draft，集中补。
- **按 module 分组补**：同一 module 的卡片语义关联强（如 domain_model 的 CRUD），一起补更一致。
- **outputs 锚点是质量关键**：extract 已从契约 `response.fields` 生成骨架（`type`含`[]`→list_full/list_ids、instanceId/total），LLM 主要做精修而非从零推断；契约未命中的才需重点判断。锚点错则编排断链。

补完覆盖写回各自 `_draft.yaml`，用 `Card.validate()` 批量校验：

```python
import yaml
from api_console.schema.card import Card
for draft in <所有 _draft 路径>:
    cards = yaml.safe_load(open(draft).read())
    for c in cards:
        errs = Card.from_dict(c).validate()
        if errs: print(draft, c["name"], errs)
```

### 步骤 4：增量过滤 + 用户 review

- **增量模式**：对每个 _draft 对应的 openapi，按 `source.openapi_hash` 对比 registry/ 已注册卡片的 hash。hash 相同 → 跳过 commit；hash 不同（录制更新了）→ 标记需重注。无 source 字段的旧卡片按"需重注"处理。
- **review**：把各 _draft 的低置信字段（requires/rollback 等）汇总展示给用户，重点确认。高置信（request/outputs/path）扫一眼即可。

### 步骤 5：批量 commit

对通过 review 的模块逐个 commit：

```bash
api-console register-cards commit \
  --platform <platform> \
  --in tmp/orchestrate/register/<模块名>/_draft.yaml
```

commit 会校验、拆单卡片、更新 `_index.yaml`（按 module 归并）。多模块 commit 后 `_index.yaml` 累积所有 module。

### 步骤 6：汇报

汇报每个模块：注册了几张卡片、归属哪些 module、path_source 分布（多少 backend_contract 高置信 / 多少 gateway_strip）、低置信待补项。

## 监测录制更新（动态决定是否重注）

当 recorder 重新录制了某模块（openapi 文件内容变了），可通过 hash 对比自动识别"哪些模块需要重新注册"，不必全量重跑。

### 判断流程

LLM 扫描 `sources/frontend/openapi/` 每个文件，对比 registry/ 卡片记录的 hash：

```python
import hashlib, yaml
from pathlib import Path

OPENAPI_DIR = Path("platforms/<platform>/sources/frontend/openapi")
REGISTRY = Path("platforms/<platform>/registry")

# 1. 收集已注册卡片记录的 (openapi_file → hash)
registered = {}  # {openapi_file: set(hashes)}
for card_file in REGISTRY.glob("*/*.yaml"):
    if card_file.name == "_index.yaml":
        continue
    c = yaml.safe_load(card_file.read_text())
    src = c.get("source") or {}
    f = src.get("openapi_file")
    if f:
        registered.setdefault(f, set()).add(src.get("openapi_hash"))

# 2. 对比当前 openapi hash
needs_update = []
for op in OPENAPI_DIR.glob("*-openapi.yaml"):
    cur_hash = hashlib.sha256(op.read_bytes()).hexdigest()
    old_hashes = registered.get(op.name, set())
    if cur_hash not in old_hashes:
        needs_update.append(op.name)  # 录制更新了 或 从未注册

print("需重新注册:", needs_update)
```

### 三种结果

| 情况 | 判断 | 动作 |
|---|---|---|
| openapi 从未注册 | `registered` 无该文件 | 注册（新模块） |
| hash 变了 | 当前 hash ∉ 已记录 hash | 重注（录制更新） |
| hash 不变 | 当前 hash ∈ 已记录 hash | 跳过（无变化） |

### 时间戳的辅助作用

`recorded_at`（openapi 录制时间）+ `registered_at`（卡片注册时间）供人读参考：
- `recorded_at > registered_at`：录制后没重注，提示用户"有更新未注册"
- 但**程序判断以 hash 为准**——hash 比 mtime 准（mtime 受任意修改影响，hash 只反映内容）

### 典型用法

> "检查哪些录制模块更新了，需要重新注册"
→ LLM 跑上面的 hash 对比 → 列出 needs_update → 用户确认后批量重注这些模块

## 注意事项

- **path 对齐依赖 contracts.yaml**：extract 前确保 `api-console parse-backend` 已跑过且 contracts.yaml 最新（后端资料更新后要重跑 parse）。
- **一个 openapi 可能跨多个 module**：如"系统管理"openapi 可能含领域模型 + 用户管理。commit 按 module 归并到不同目录，正常。
- **覆盖模式风险**：会重写已注册卡片，丢失之前手工补的语义。覆盖前确认或备份。
- **_index.yaml 并发**：多模块 commit 各自更新 _index，串行 commit（不要并行，避免 _index 写冲突）。
- **_index 增量合并**：commit 按 card name 增量合并进各 module（同名覆盖、未涉及保留），多 draft 共享同一 module 时不互相清掉。若确需整体替换某 module，先删该 module 目录再 commit。索引与文件不一致时跑 `rebuild_index` 子命令兜底。
- **重复接口去重**：多个录制场景常捕获同一真实接口（如 `getTaskDetail` 在工单发起 + 工单搜索各录一份），commit 会落多份卡片（不同 module 或不同 name）。批量注册后建议扫 `同 (method,path) 多卡片` 去重——每接口留一张语义最优的（优先 operationId 语义名），删其余并 `rebuild_index`。去重是破坏性操作，删前确认。
- **失败可续**：某模块 extract/补语义/commit 失败，不影响其他模块。失败的单独重跑即可（_draft 在 tmp/，重跑 extract 会覆盖）。

## 典型用法示例

**全量增量注册**（首次批量注册所有录制模块）：
> "把该平台已录制的模块都注册了，已注册的跳过"
→ LLM 全量 extract → 统一补语义 → 增量过滤（已注册的 domain_model/standard_field 跳过）→ 批量 commit 其余 11 个

**范围覆盖注册**（重注册系统管理类）：
> "重新注册 ITSM-系统管理-* 这几个模块"
→ LLM glob 匹配 8 个 → extract（覆盖 _draft）→ 补语义 → 覆盖 commit

**单个模块注册**：
> "注册 ITSM-工单发起"
→ 单个 extract → 补语义 → commit
