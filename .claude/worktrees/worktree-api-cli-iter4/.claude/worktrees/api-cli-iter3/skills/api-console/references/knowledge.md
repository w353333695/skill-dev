# 领域知识库（knowledge）

skill 编排不仅需要"接口怎么调"（卡片），还需要"接口背后业务实体的语义"（字段类型、配置约束、ID 规则、跨模块概念）。这些知识放在平台包的 `knowledge/` 目录，与 registry/（卡片）分离管理。

**这不是常用场景**——知识库是渐进积累的，遇到不懂的领域知识才加。本文件只讲结构与消费约定。

## 为什么要和卡片分离

|      | 卡片（registry/）              | 知识（knowledge/）         |
| ---- | ------------------------------ | -------------------------- |
| 描述 | 接口契约（怎么调）             | 业务语义（是什么）         |
| 粒度 | 一个接口一张                   | 一个概念/一组约束一份      |
| 复用 | 接口级                         | 跨模块、跨接口             |
| 结构 | 严格 schema                    | yaml+markdown 混合         |
| 消费 | verify_dag/execute_dag（程序） | LLM（生成 DAG/补卡片时读） |

混在卡片会让卡片臃肿、知识无法跨模块复用。

## 目录结构

```
platforms/<platform>/knowledge/
├── concepts/                  # 类型A：跨场景全局概念（单一真相源）
│   ├── instance-id.md         # instanceId 生成原理/规则/跨模块用法
│   ├── value-types.yaml       # 值类型系统（string/int/array/reference...）
│   ├── cmdb-model.yaml        # CMDB 模型设计（objectId/字段/关系）
│   └── ...
└── modules/                   # 类型B：模块内字段细节（默认与卡片同 module）
    ├── standard_field/
    │   └── standard-field-types.md   # 标准字段 kind 枚举 + sourceConfig 约束
    ├── process_design/               # 流程「设计态」规则（见下"模块命名"约定）
    │   ├── compliance-rules.md       # 领域知识（LLM 读）
    │   ├── check_compliance.py       # 配套可执行脚本（零依赖）
    │   └── sample.bpmn               # 样例
    └── domain_model/
        └── ...
```

- **concepts/**：全局概念（instanceId 规则、值类型、CMDB 模型设计），所有模块引用，改一处全生效
- **modules/<module></module>/**：模块内细节，默认与 `registry/<module>/` 同名就近放

### 模块命名：知识模块 vs 卡片模块

默认知识模块名与卡片模块名**一一对应**（`registry/standard_field` ↔ `knowledge/modules/standard_field`）。
但当知识描述的是卡片的**另一个切面**而非接口本身时，模块名可不同——用命名点明切面差异，
并在两侧 `_index` 的 `desc`/`note` 互指，避免被当成重复资产。

**典型例子**：`registry/process`（流程「运行态」接口：flowable 创建/保存/查询/跳转）与
`knowledge/modules/process_design`（流程「设计态」规则：BPMN XML 的 27 条合规 + 布局）——
同名对象（ITSM 流程）的不同切面，非重复。

### 配套脚本：知识模块内可放可执行工具

知识模块以 `yaml`/`md` 为主（给 LLM 读），但允许放**承载该领域规则的可执行脚本**（如
`check_compliance.py` 把 27 条规则从 markdown 变成可跑的校验器）。约定：

- 仅放**领域规则的可执行配套**（规则即知识，脚本是其运行形态），不放通用工具——通用工具应进能力 project（`projects/<name>`）
- 脚本零依赖或依赖明确，独立可跑，**不接入**卡片/DAG 体系（不进 verify/execute）
- 在模块 `README.md` 列清单 + 用法，`_index.yaml` 的 `note` 注明「同目录有配套脚本」

## 知识文件形式：yaml + markdown 混合

不强求严格 schema。原则：**能结构化的结构化（枚举/表格），难结构化的自由描述（markdown）**。

- 枚举值、字段表、配置结构 → yaml 表格
- 生成原理、使用场景、陷阱 → markdown 段落
- 文件扩展名：结构化为主用 `.yaml`，描述为主用 `.md`

每个知识文件建议含：定义、已知规则、使用场景、相关概念、来源资料（标注哪些是待补的）。

## 知识来源：用户提供资料 + LLM 解析

与后端资料解析同构（adapter 思路）：

1. **用户提供资料**：页面表单截图/导出、后端字段定义代码、示例数据、wiki 文档
2. **LLM 解析**：LLM 读资料 + 现有 openapi/契约，抽取结构化知识写入 knowledge/
3. **人 review**：标注置信度，低置信（推断的）重点确认

资料放在 `tmp/<platform>-knowledge-<topic>/`（临时），解析产物入 `knowledge/`（持久）。

> 当前 MVP-1 不做"知识解析 adapter"自动化——LLM 现场读资料写知识即可。量大时再考虑 adapter 化（与 parse_backend 同思路）。

## 知识文件 frontmatter（结构化元信息）

每个知识文件顶部 YAML frontmatter（`---` 包围），含：

| 字段              | 含义                                                                    |
| ----------------- | ----------------------------------------------------------------------- |
| `name`          | 知识唯一标识                                                            |
| `kind`          | `concept`（全局概念）/ `module`（模块知识）                         |
| `module`        | module 类型必填；concept 留空                                           |
| `tags`          | 跨概念检索关键词（一个知识可多 tag，缓解粒度问题）                      |
| `completeness`  | **`full`（权威完整）/ `partial`（部分）/ `stub`（仅框架）** |
| `gaps`          | partial/stub 时具体缺什么（问答命中必须明说"不能确定"）                 |
| `scope`         | 适用范围（问答定位用）                                                  |
| `related`       | 关联知识（概念网）                                                      |
| `last_verified` | 上次与真实系统核对时间；空=未核对                                       |

`completeness` + `gaps` + `last_verified` 是**问答防幻觉的底线**。

## 知识索引（_index.yaml）

`knowledge/_index.yaml` 是检索入口（类似 registry/_index.yaml）。LLM 找知识时**先扫此文件**，按 tags/module/name 匹配，命中后读对应 file 正文。

```yaml
concepts:
  - {name: instance-id, file: concepts/instance-id.md, tags: [...], completeness: partial, gaps: [...], last_verified: ""}
modules:
  standard_field:
    - {name: standard-field-types, file: modules/.../..., tags: [...], completeness: stub, gaps: [...]}
```

新增知识时同步更新 _index.yaml（completeness/gaps 改了也要同步）。

### 索引更新纪律（防过度维护）

`_index.yaml` 的字段消费方式不同，维护力度要分级（**别一刀切全更新**）：

| 字段 | 消费方 | 维护要求 |
| --- | --- | --- |
| `name` / `file` | 代码（定位文件）+ LLM | **必须**准确同步 |
| `completeness` / `gaps` / `last_verified` | 代码（`knowledge_gaps.py`/`aggregator.py`）+ LLM | **必须**同步——是真数据 |
| `note` / `desc` | 仅 LLM 扫描（一句话定位） | 新增独立主题/检索维度时补一句定位语即可 |
| `tags` | **仅 LLM 扫描**（检索关键词锚点） | **克制加**，见下 |

`tags` 是检索入口的「关键词锚点」，LLM 在目录页靠它判断要不要深入读正文。**但 tag 无代码消费、价值密度低，堆砌反而稀释检索信号**。纪律：

- **不要为「正文的某个细节」加 tag**。正文已写明的内容，靠 `note` 一句话定位语锚定即可，不必再拆成 tag。例：正文新增「交付脚本形态规范」，`note` 补一句定位语就够，**不要**再把"独立可执行"/"不用argparse"等细节拆成 tag。
- **只在「新增独立检索维度」时加 tag**——即一个原本检索不到的、新的主题大类（如原本只有 CMDB 知识，新增了"监控"域，加 `监控` tag 才有意义）。
- 已有 tag 能覆盖检索入口的（如 `API调用`/`脚本开发` 已能命中脚本类知识），**不要再加同义 tag**。
- 单条 tag 总数控制在 ~10 以内；超过说明在把正文细节往 tag 里搬，该回退。

> 原则：**`note` 锚定主题，`tags` 只标大类，细节留在正文**。拿不准要不要加 tag 时，默认不加（改加 `note` 定位语）。


## 消费场景

### ⭐ 总原则：知识前置 + 有据不猜（所有涉平台任务通用）

凡涉及当前平台（`platforms/<platform>/`）实体的任务——问答、API 编排、卡片注册，**或**设计/生成产出物（流程图、表单、模型配置……）——动手前都先扫 `knowledge/_index.yaml`，确认有没有领域知识（规则/约束/样例/配套可执行脚本）。知识库不是“问答专用资料”，是所有产出的合规依据。

**数据来源铁律（系统相关的问答与需求通用，最高优先级）**：

- 任何关于系统的问答或需求处理，**必须有可追溯的数据来源**——引用具体知识文件 / 规则条目 / 配套脚本，并标明该知识是否经真实系统核对（`last_verified`）。**不清楚的不要猜测**，宁可说“知识库无此条 / 未核对 / 不能确定”。
- 命中知识：回答或产出**标注来源**（哪个知识文件、`completeness`、`last_verified`）；命中 `gaps` 的部分明说“待补，不能确定”。
- 找不到知识：明说“知识库无此模块知识”，不编造；产出标注“未经平台规则核对”；**提示用户登记一条知识缺口**（`api-console knowledge-gaps register --source manual`，进 `_gaps.yaml` 追踪闭环、不遗失）。

> 常见误区：把“设计/生成某类平台制品”当纯创作直接动手——但平台常对产出物有静态合规规则、样例、可执行校验器。跳过知识库 = 凭空造，既无数据来源也易不合规。先查规则 → 产出 → 跑校验脚本。

**动手前自检（3 步，通用）**：

1. **定位模块**：产出物涉及哪个知识模块/概念？（扫 `_index.yaml` 的 modules/concepts）
2. **扫索引**：有无对应条目？看 `completeness`/`gaps`/`last_verified`，以及同目录有无**配套可执行脚本**（零依赖校验器等）。
3. **决定动手方式**：
   - 命中规则/样例 → 读规则、参考样例产出，**产出后跑配套校验脚本**自证合规；标注来源
   - 命中但 `partial`/`stub` → 能确定的部分产出（标注来源），命中 `gaps` 的部分明说“待补/待核对，不能确定”
   - 找不到 → 明说“知识库无此模块知识”，标注“未经平台规则核对”；**提示登记缺口**（`register --source manual`）以便追踪补全

下面场景 1–4 是该原则在各流程节点的具体化；场景 5 是它对“生产型需求”的应用。

### 场景1：注册卡片时补字段约束

LLM 先扫 `_index.yaml` 找该 module 的知识 → 读正文 → 补卡片字段约束。

```
注册 standard_field 卡片
  → _index.yaml 找 modules.standard_field
  → 读 standard-field-types.md（注意 completeness=stub）
  → 补能确定的（核心字段）；kind/sourceConfig 因 gap 不确定，标卡片 confidence 低
```

### 场景2：编排涉及领域概念

LLM 生成 DAG 前，按 tags 扫 _index 找相关 concepts → 读正文理解语义。

```
编排涉及 instanceId 跨模块引用
  → _index 按 tag "instanceId" 找到 instance-id 概念
  → 读正文：standardFieldIds 是 standard_field 的 instanceId，modelId=instanceId
```

### 场景3：卡片引用知识

卡片 `requires` 字段可引用知识文件路径（纯文档，verify_dag 不校验引用完整性，MVP）：

```yaml
requires:
  - "instanceId 格式见 knowledge/concepts/instance-id.md"
```

（卡片↔知识的结构化双向绑定 + 引用校验留后续，见"待办"）

### 场景4：回答用户单纯提问（知识问答）⭐

用户直接问业务知识（非编排），LLM 按以下流程，**强制诚实**：

1. **检索**：按问题关键词扫 `_index.yaml`（tags/module/name/scope 匹配）
2. **读正文**：命中后读对应知识文件
3. **检查 completeness + last_verified**，决定回答方式：
   - `full` + `last_verified` 近期 → 可信回答
   - `partial`/`stub` 且命中 `gaps` → **必须明说**"这部分知识待补（缺 X），我不能确定"，**不能猜**
   - `last_verified` 空 → 标注"未经真实系统核对，请以实际为准"
4. **找不到相关知识** → 明说"知识库没有这块知识"，不编造；建议用户提供资料补全

**铁律**：宁可说"不知道/不确定"，也不基于不完整知识编造。问答回答必须标注置信度（基于 completeness/last_verified）。

### 场景5：生产型需求（设计/生成产出物）

用户要产出平台相关制品（流程图、表单、模型配置……），非提问也不走编排，最易跳过知识库直接创作，恰最需先查规则并标注来源。遵循总原则「知识前置 + 有据不猜」：产出须有数据来源（引用规则/样例/校验依据 + 是否经真实系统核对），不清楚的不猜、标注待核对；产出后跑配套校验脚本自证合规。

与场景4（问答）区别：问答"检索→回答"，生产型"检索规则→产出→跑配套脚本校验"。检索入口与诚实原则相同，产出后多一步确定性校验。

## 渐进积累原则

- **不要求一次写全**——遇到不懂的领域知识就加一条
- **诚实标注未知**——frontmatter 的 completeness/gaps 是底线，正文也要标"待补"
- **同步 _index**——新增知识或 completeness 变化时更新 _index.yaml
- **核对机制**——知识用前最好 `last_verified` 与真实系统核对过；未核对的回答要标注

## 待办（知识库能力增强）

已实现：索引 + frontmatter + 问答规则 + **缺口治理**（`_gaps.yaml` 登记/追踪/关闭 + frontmatter 联动，见上文「缺口治理」）。以下留后续：

- **卡片↔知识双向绑定**（缺口 B）：卡片加 `knowledge_refs` 字段 + verify_dag 校验引用存在 + 知识改了反向通知引用它的卡片
- **自动绑定**：register_cards 时 LLM 自动判断卡片需要哪些知识，填 knowledge_refs
- **知识解析 adapter**：知识量大时，把"用户提供资料 → LLM 解析"流程 adapter 化（同 parse_backend）

## 缺口治理（知识缺口生命周期）

知识库的 `completeness`/`gaps`/`last_verified` 散落在各知识文件 frontmatter 里（**知识视角**：这条知识缺什么）。缺口治理把它们归一到平台包级的 `_gaps.yaml`（**管理者视角**：整个平台还有哪些知识债），提供登记、报告、状态追踪与 frontmatter 联动回写。

入口脚本 `api_console/knowledge_gaps.py`（子命令式，经 `api-console knowledge-gaps ...` 调用），全确定性；LLM/人只在登记时预填 `severity`/`suggest`（语义部分）。

### _gaps.yaml 字段

`platforms/<platform>/knowledge/_gaps.yaml`，结构 `{gaps: [Gap, ...]}`，每条 Gap：

| 字段                                               | 含义                                                 |
| -------------------------------------------------- | ---------------------------------------------------- |
| `id`                                             | 稳定 ID（gap-NNN），生命周期不变                     |
| `source`                                         | frontmatter / runtime / manual / diff                |
| `knowledge_file`                                 | 来源知识文件（相对 knowledge/）；runtime/manual 可空 |
| `module`                                         | 归属模块；concept 留空                               |
| `title` / `detail`                             | 一句话描述 / 具体缺什么                              |
| `severity`                                       | high / medium / low（人/LLM 预填，脚本不判）         |
| `suggest`                                        | 治理建议（人/LLM 预填，脚本不生成）                  |
| `status`                                         | open / filling / closed                              |
| `discovered_at` / `updated_at` / `closed_at` | 时间戳                                               |
| `triggered_by`                                   | runtime 时记触发场景（step_id）                      |

### 四类来源

| 来源            | 怎么产生                                                   | 对应入口                                                 |
| --------------- | ---------------------------------------------------------- | -------------------------------------------------------- |
| `frontmatter` | 聚合各知识文件 frontmatter 的`gaps`（partial/stub 条目） | `report`（每次聚合，自动去重）                         |
| `runtime`     | 编排执行失败（assert/业务码错/锚点失败）被动暴露           | `execute_dag.execute(on_error=make_runtime_sink(...))` |
| `manual`      | 人/LLM 主动登记（问答/产出时发现的知识缺口）                    | `register --source manual`                             |
| `diff`        | 对照 registry 卡片发现知识未覆盖的模块                     | `discover`                                             |

### 命令清单

```bash
# 聚合 frontmatter 缺口进 _gaps.yaml，输出表格（--md 另出报告）
api-console knowledge-gaps --platform <platform> report [--status open] [--md tmp/gaps.md]

# 人工/runtime 登记一条
api-console knowledge-gaps --platform <platform> register \
  --title "kind 枚举缺失" --severity high --module standard_field \
  --source manual --detail "仅知 USER_SELECTOR" --suggest "补新建字段表单下拉框"

# 标记补全中 / 关闭缺口（close 回写知识文件 frontmatter）
api-console knowledge-gaps --platform <platform> filling gap-003
api-console knowledge-gaps --platform <platform> close gap-003

# 对照接口发现未覆盖模块（粗粒度）
api-console knowledge-gaps --platform <platform> discover
```

### 生命周期：open → filling → closed

- `open`：刚发现/登记
- `filling`：正在补全（人标记）
- `closed`：已补全。`close` 会**回写知识文件 frontmatter**：从 `gaps` 删掉对应 title；`gaps` 删空则 `completeness` 升级为 `full`，否则保持原级；填 `last_verified`。`_index.yaml` 同名条目同步。这样**管理者视角（_gaps.yaml）与知识视角（frontmatter）联动**——关掉一条缺口，知识文件的完整性也自动更新。

### runtime 被动暴露

编排执行接入可选错误钩子，失败时自动记 `source=runtime` 缺口（不阻断错误传播）：

```python
from runtime_gaps import make_runtime_sink
execute_dag.execute(dag, cards, adapter, manifest, contracts,
                    on_error=make_runtime_sink(workdir, platform))
```

失败信息是否真为"知识缺口"由人/LLM 在 `report` 时复核（severity 默认 medium）。

### 管理者输出

- **CLI 表格**：`report` 直接打印按 module 分组的缺口表
- **md 报告**：`report --md <path>` 产出按 severity 分节的治理报告（含 suggest），供人阅读排期

> 缺口治理是确定性的，LLM 不在其中做语义判断（severity/suggest 由人/LLM 在登记时预填）。

## 当前已有知识

- `concepts/instance-id.md` — instanceId 规则（completeness=partial，生成算法待确认）
- `modules/standard_field/standard-field-types.md` — 标准字段类型与配置约束（completeness=stub，kind 枚举/sourceConfig 结构待补）
- `modules/process_design/compliance-rules.md` — ITSM 流程设计合规规则（27 条 bpmnlint，completeness=full）；同目录 `check_compliance.py`/`check_layout.py` 为配套校验脚本。与 `registry/process`（运行态接口）互补
