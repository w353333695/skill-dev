# platforms/ 资料资产 Schema

> **通用约定**。定义 `platforms/<deployment>/` 下各类资料文件的结构。
> 适用于**任何外接系统**——系统特定内容（字段名、副作用、鉴权细节、端口）只活在各 `<deployment>/` 实例里；本文件只定**结构**，零系统知识。任何具体系统名都只是某个 `<deployment>` 下的实例，不是本 schema 的一部分。

## 设计原则

1. **分文件、各司其职**：systems / objects / entities / flows / formats 各装一类知识，不堆进 README（README 只做索引）。大型系统知识庞杂，按文件分才能扩展。
2. **结构化（YAML，机读）+ 可扩展**：新对象/流程/系统直接追加，不改既有结构。
3. **唯一真相来源**：`platforms/` 是外接系统的全部知识载体，换环境/换 LLM 从此读，**不依赖记忆**。
4. **单一真相源（文件间，禁全文复述）**：同一事实/规则在 platforms 内**只在一个权威文件写一次全文**，其余文件**只放一句话 + 指针**（如 `见 objects.yaml#X.side_effects` / `详见 formats/inspection-kit/script-protocol.yaml#command_path_rule`），**不得在 key_rule/note/desc/expect/trigger/side_effects 等任何字段里全文复述**。改规则只改权威文件一处，不会漏。

   **权威层级**（低层指高层，知识「下沉」到能复用/承载机制的最权威处）：
   | 知识类型 | 唯一权威文件 | 下游文件（只能指针） |
   |---|---|---|
   | 格式/协议/机制/真实套件范式（跨部署） | `formats/<fmt>/*.yaml` | objects/flows/spec/README |
   | 对象副作用/接口行为（本部署） | `objects.yaml.side_effects` / `api_behavior` | flows/README |
   | 接入/端口/鉴权/运行时坑 | `systems.yaml.runtime` | objects/flows/README |
   | 字段格式/主键 | `entities.yaml` | objects/flows |
   | 端到端步骤 | `flows/*.yaml`（步骤本身，非规则） | — |

   **判定**：写到某字段时自问「这句话的全文，是否已在更权威的文件里存在？」是 → 删成本文，换成指针。flow 的步骤值（API 请求体示例、要填的字段）是**步骤操作的一部分**，不算复述，保留。

   ⚠️这条与下文「证据纪律 §4 知识内联」不冲突——内联针对的是**禁止引用 platforms 外部文件**（tmp/、knowledge/），不针对 platforms 内部；内部仍守本条，用指针。

## 文件职责（对应 SKILL.md「资料」）

| 文件 | 职责 | 装什么 |
|---|---|---|
| `systems.yaml` | 接入 | 系统清单、api-cli spec 路径、接入面、鉴权、运行时知识（租户/用户/端口/环境变量）、capabilities |
| `objects.yaml` | 对象关系 + 副作用规则 | 对象结构（字段/关系/约束）+ 操作副作用 + 接口级行为 |
| `entities.yaml` | 字段锚 + 转换 | 主键/关键字段格式约定 + 跨实体、跨 step 的字段接力 |
| `flows/*.yaml` | 流程模板 | build/change 类端到端步骤序列（含数据流/回滚/副作用回指）|
| `formats/<fmt>/` | 格式包 | 跨部署复用的格式（BPMN/插件 等）|
| `<system>.yaml` | api-cli 清单 | 命令树 + body/response schema（api-cli spec 格式，见 api-cli USAGE）|
| `README.md` | 索引 | 资料地图导航，**不承载知识主体** |

---

## systems.yaml

```yaml
deployment: <deployment-name>          # 如 demo / prod
systems:
  <system>:                             # 系统名
    description: ...
    spec: <system>.yaml                 # api-cli 清单，相对本目录
    default_endpoint: <endpoint-name>
    endpoints:
      <endpoint-name>:
        base_url: ${ENV_VAR}            # 支持 ${ENV}
        host: <optional-host-header>
        path_prefix: <prefix>
        auth: <auth-name>               # ~/.api-cli/auth.d/<auth-name>.yaml
        headers:                        # endpoint 级固定 header（每个请求自动带）
          <header>: ${ENV_VAR}
    auth: <auth-name>
    env: [VAR1, VAR2]                   # 部署所需环境变量
    capabilities:                       # resource.verb → 用途（编排挡判可达性）
      <resource>:
        <verb>: "..."
    runtime:                            # 接入知识（实测踩坑沉淀）
      env_required: [...]               # 调用前必须 export
      ports: { <svc>: <port> }
      host_header: <host>
      auth: "..."                       # 鉴权要点（什么凭证、缺了报什么）
      <key>: "..."                      # 自由扩展：租户/用户体系、网关说明等
    acceptance_urls: { <name>: "..." }  # 前端验收 URL
```

## objects.yaml

```yaml
objects:
  <object>:                              # 对象名
    description: ...
    source: <后端源码路径>                # 溯源
    api: <resource>                      # 对应 api-cli resource
    fields:
      <field>:
        type: string|integer|bool|array|object|any
        required: true                   # （注意：schema 里 required 是 bool，单个字段）
        anchor: true                     # 是否主键/锚字段（entities.yaml 详述）
        ref: <other-object>              # 引用另一对象
        items: <type-or-object>          # array 时
        enum: [a, b]
        pattern: '<regex>'
        default: <value>
        desc: "..."
    relations:
      - to: <other-object>
        type: composition|reference|association
        cardinality: "1:N|N:M|1:1"
        via: <field>
    constraints:                         # 不变式
      - "..."
    side_effects:                        # 操作副作用规则（实测，真相来源核心）
      - op: <resource.verb>
        rule: "..."
api_behavior:                            # 接口级行为（跨对象）
  <behavior-name>:
    rule: "..."
```

## entities.yaml

```yaml
entities:
  <field>:                               # 字段锚
    description: ...
    format: "..."                        # 格式约定
    anchor: true|false                   # 主键锚
    rules: ["..."]
    used_by: [<resource>.<verb>]         # 哪些操作用它
transitions:                             # 跨实体 / 跨 step 字段接力（编排挡 dataflow 用）
  - from: <resource.verb>
    pick: <field>                        # 从上一步抽哪个字段
    to: [<resource.verb>]               # 喂给哪些下游
    how: "..."                           # 怎么传/转换
```

## flows/*.yaml

每个流程一个文件。

```yaml
name: <flow-name>
intent: ...                              # 这个流程达成什么
trigger: ["自然语言触发短语"]             # 什么时候用
guard: 直通|确认|规划                     # 对应 orchestration.md 三挡
prerequisites:                           # 前置
  env: [VAR]
  payload: "..."
steps:                                   # 步骤序列
  - n: 1
    op: <resource.verb>
    args: [...]
    desc: ...
    dataflow: "..."                      # 字段怎么从上一步来 / 给下一步
    expect: "..."                        # 成功标志
    on_fail: "..."                       # 失败处理
side_effects: <objects.yaml#object.side_effects>   # 回指，不重复（见设计原则④，同适用于 key_rule/note/desc/expect 等所有字段）
rollback: "..."                          # 失败回滚步骤
acceptance: "..."                        # 验收方式
```

## formats/<fmt>/

跨部署复用的格式包（BPMN 流程定义、插件打包等）。与具体系统无关。schema 待具体格式落地时补。

---

## 扩展规则

- **新对象**：`objects.yaml` 加一个 `<object>`。
- **新流程**：`flows/` 加一个 yaml。
- **新系统**：新 `<deployment>/` 目录，或同 deployment 的 `systems.yaml` 加一个 `<system>` + 对应 api-cli 清单。
- **新接入知识（坑）**：归位到对应文件——接入/鉴权→`systems.yaml.runtime`，对象行为/副作用→`objects.yaml.side_effects`/`api_behavior`，字段格式→`entities.yaml`，端到端步骤→`flows/`。**不写进 README，不写进记忆**。
- **schema 字段自由扩展**：各文件的 `<key>` 可按系统需要追加（如 `runtime.<任意key>`），上面只规定最小骨架。
