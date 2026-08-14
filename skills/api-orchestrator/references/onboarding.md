# onboarding.md —— 接入新系统 / 录入 platforms

> onboarding 的目标：把「系统资料」（契约/抓包/源码/场景）整理录入 **`$PLATFORMS_ROOT/<deployment>/`**（PLATFORMS_ROOT 解析见 orchestration.md「步骤 0」；符合 `asset-schema.md`），让 skill + platforms 能分发到**任意系统、任意 LLM**，读资料即能编排用户需求。**首次接入须先初始化部署根（见下「初始化部署根」）。**
>
> 本文件是 skill 本体，**零系统耦合**——流程通用；完整实战范例见 `platforms/demo/`（一个配置管理系统的 onboarding 产物，含全部坑）。

---

## 证据纪律（防臆测，最高优先——适用全程）

> 实战教训：itsm 表单 onboarding 时，把 `options.extraProps`（Go 端 `map[string]interface{}`）的字段内容、`displayCondition` 表达式语法**凭字段名/直觉臆测**写进 platforms，结果前端渲染崩、条件显示不生效，用户多次推回后才靠深挖 `testdata/definition.json` 纠正。根因不是检索深度，是没守下面三条——**onboarding 全程、所有步骤适用**。

1. **动态/透传字段的权威源是「真实样例」，不是 Go struct、更不是字段名**。
   - 凡字段在源码里是 `map[string]interface{}` / `interface{}` / `string`(JSON blob) 等弱类型（后端透传不解析），其【字段 schema】Go struct 看不到——权威源是：① 仓库 `testdata/` 的真实样例；② `get` 一个现成实例/记录捕获；③ 前端 designer 生成的产物。
   - 不许从字段名推断结构（反例：见 `foreignObjectId` 就猜填模型 id、见 `name` 就猜是默认显示字段——itsm 实测两者都错）。
   - 实操：派子代理时明确要求「扫 testdata 抽该字段每类型真实值」；没 testdata 就 get 现成实例；都没有→走规则 3。

2. **「前端解释型内容」的 e2e ≠ save 返回 200**。
   - 后端透传、前端解释的 blob（如 formDefinition / businessRules / 模板字符串 / 自定义 DSL），后端【不校验结构】——save/update 返回 code=0 只表「存下了」，**不代表前端能渲染/逻辑能跑**。把 API 200 当「配置正确」是假阳性。
   - 这类内容的正确性必须：① 前端渲染/执行验证（用户看或截图）；或 ② 从 designer / 现成实例捕获的【已知能跑】结构仿写。
   - 实操：e2e 报告对这类内容明确标「API 已落库，前端渲染待验证」，别默认成功。

3. **无证据不臆测——查不到就标 gap，不许编**。
   - 某字段/语法/枚举值查不到权威源时，写「未知—待捕获（建议 designer 配置后 get 回流）」，**不许**凭「看起来合理」编一个（反例：编 `field 含 value` 这种不存在的表达式语法）。
   - gap 标注也是有效产出——它告诉下一个 LLM/用户这里缺证据，比错误信息危害小得多。
   - 实操：写 platforms 时自检「这条有 file:line / 真实样例 / 实测证据吗？」没有就降级为 gap 标注，并记到对应文件的 constraints / api_behavior 里。

4. **platforms/ 知识必须自包含——不引用 platforms/ 以外的文件**。
   - `platforms/<deployment>/` 是唯一真相来源，换环境/换 LLM 只读这些文件。引用外部文件（尤其 `tmp/` 临时文件、`knowledge/modules/` 等）= 知识依赖了随时会删的东西，分发即断。
   - `source:` 字段（如 `data/sources/backend/.../*.go:line`）仅标**溯源**（这条知识从哪段源码归纳的），不是「详见此处获取知识」——知识必须**内联**在 platforms 文件里。
   - 发现自己写「详见 tmp/xxx.md」「参考 knowledge/modules/xxx」时 → **停**，把那个文件里的关键知识提取内联到 platforms 对应文件，然后删掉引用。
   - ⚠️**范围限定**：「内联」只针对**禁止依赖 platforms 外部文件**（tmp/knowledge/源码副本）。platforms **内部**文件之间**不**内联——遵守 asset-schema.md 设计原则④「单一真相源（文件间）」：同一规则全文只写在一处权威文件，其余用指针（如 `见 objects.yaml#X.side_effects`）。两者方向不同：对外拒绝指针（怕断），对内强制指针（防散落/防改漏）。
   - 实操：onboarding 完成时 grep `platforms/` 目录，确认零 `tmp/` 引用、零 `详见/参见/参考 + 外部路径`；`source:` 和 YAML 头注释里的 `data/` 路径是溯源 OK 的（不是知识依赖）。

---

## 1. 输入启动包（引导用户按最佳实践提供）

onboarding 的速度和质量取决于输入完整度。**开工前按此清单核对，缺什么先问用户要什么**——不要在缺关键输入时硬猜。

### 必提供（缺一不开工）

| # | 输入 | 为什么需要 | 形式 |
|---|---|---|---|
| 1 | **API 真相来源**（至少一种）| 端点/method/请求/响应的权威定义 | OpenAPI/Swagger、EAML/契约 JSON、抓包（HAR/curl）、接口文档 URL |
| 2 | **鉴权凭证 + 用法** | 真调验证必备 | cookie/token/AK-SK；哪个 header 或 cookie 字段承载 |
| 3 | **有效账号（有写权限）** | 写路径 e2e 验证 | 管理员级账号标识 |
| 4 | **e2e 场景** | 编排覆盖的标尺 | 3-5 条自然语言「我想能做什么」（含查/建/改/删）|

### 强推荐（大幅提速提质，缺失会踩坑）

| # | 输入 | 为什么 |
|---|---|---|
| 5 | **后端源码位置** | 契约常不完整——源码补全缺失端点 + 拿到**权威结构体/校验规则**（契约里的字段类型常是弱描述）|
| 6 | **测试环境 / 隔离租户** | 写路径要落库验证，**绝不能动生产/系统自带数据**。要一个可写的测试空间（org/namespace/project）|
| 7 | **验收方式** | 确认编排结果可见 | 前端 URL、校验命令、或查询语句 |

### 可选（增量更新 / 特殊约束）

| # | 输入 | 场景 |
|---|---|---|
| 8 | 已有 platforms 资料 | 更新而非新建（先读现状，按 schema 增量）|
| 9 | 特殊约束 | 多租户隔离、命名空间约定、权限模型、声明式语义（upsert？）|

> **输入引导话术**：用户若只甩一句「接入 X 系统」，用上表反问——尤其 1/2/3/6（API 来源、凭证、有效账号、测试空间）缺了就停下来问，别空跑。

---

## 2. onboarding 流程（7 步）

> **实战补充**：每步的操作清单、产物范例、踩坑 checklist 见 `references/onboarding-playbook.md`（从 collector_plugin_service 接入提炼，发起新模块接入时配合本文件用）。

对应 SKILL.md 决策树 [1]。每步产出可校验。

### 步 1：核对输入 + 门禁 + 识别系统形态
- **硬门禁（缺则停下问，不开工）**：API 真相来源——契约 / API 文档 / 后端源码，**至少一个**。三者皆无从知道端点/字段，直接拒跑，向用户索要。
- **软门禁（缺则 warn，能录资料但 e2e 闭环不了）**：凭证、有效账号、测试空间、e2e 场景。缺凭证/测试空间 → 可完成步 1-5（录资料），步 6（e2e 真调）做不了。
- **单一来源提醒**：只有契约/文档（无源码）时，warn「端点/副作用可能漏，有源码最佳」。
- 识别形态：契约格式（OpenAPI? EAML? 抓包?）、鉴权模型（cookie? token? AK/SK? 是否多租户?）、数据模型（CRUD? 声明式 upsert?）。

### 步 2：理解 API 面（契约 → 端点表）
- 从契约抽：每个端点的 method/path/请求体/响应。
- **关键意识：契约常不完整**。把场景需要、契约没有的端点列出来（典型：delete/get-detail），留到步 3 用源码补。

### 步 3：探源码补全 + 拿权威结构（若有源码）
- **补端点**：找路由注册（gin/echo/http router `.GET/.POST/...` 或路由表），补全契约缺的端点。
- **权威结构体**：找契约里引用的模型（如 `<ModelType>[]`）的 Go/源码定义——拿到**全部字段 + json tag + 校验 tag**（required/regex/enum），比契约的字段描述准。
- **校验/约束**：找 validator + service 层的运行时检查（重复、依赖、副作用）。
- **枚举/变量语法优先找集中源**：先找 `fixtures/`（如 notify_policy 的 `rawSetting` 全量枚举）、testdata、枚举接口（route.go 里的 `ListEnums`/`GetXxxEnums`）——这些是值空间的权威全量源，比 grep 字面量散点全。找不到再 grep validator 正则 + service switch case。
- 派 `Explore` 子代理大面积扫，要结论 + `file:line` 引证，别 dump 全文。
- ⚠️**这一步不可跳**：步 7 的 lint 门禁会校验每个 object 块有 `source:`（file:line / 枚举接口 / 契约）。跳了步 3 → 没 source → lint ERR → 产物不合格。不止步于契约描述 + 1~2 个样例值——那是「没查」不是「gap」，gap 是查过源码后仍无约束才标。
- ⚠️**load-bearing 真相别托付给 background agent**：本步的结论会被后续步骤依赖（写 spec/objects），用 inline bounded grep 查、查完立即内联进 platforms + commit——session 退出会 kill background agent，已提交到 platforms 的事实不丢。

### 步 4：写 api-cli 清单（`<system>.yaml`）
- 按 api-cli spec 格式（见 api-cli USAGE）：`service/endpoints` + `resources/<resource>/operations`。
- 写作纪律（踩过的坑，见 api-cli USAGE「清单编写要点」）：
  - **无 `$ref`**——body/response schema 全部**内联**；多 operation 共用结构只能重复。
  - **`required` 双义**——`params.required` 是 bool；schema 的 `required` 是 `[]string`（父列必填子字段名）。在 schema 属性上写 `required: true` 会解析报错。
  - **资源级 `path:` 一律留空 `""`，完整 path 只在 operation 级写**——api-cli 会把 resource.path 和 operation.path **拼接**，资源级非空 + 操作级写完整路径 = URL 双倍（实测 `/metric-groups/api/v1/inspection/.../metric-groups` → 404）。无论路由 disparate 还是统一，资源级都留空，统一在每 operation 写完整路径。修复/自查：`explain R V` 的 path 字段应只有一份完整路径；`R V --dry-run` 的 URL 不含重复段。
  - **每个 resource/operation 写 `description`**——它进 MCP tool description，决定 LLM 抉择准不准。
- 验证：`scripts/run.sh --spec X --help`（resource/verb 渲染）+ `scripts/run.sh --spec X explain R V`（schema 透传）+ `scripts/run.sh --spec X R V --dry-run`（URL/body 构造）。

### 步 5：录入 platforms（按 asset-schema 归位）
知识分文件，**别堆 README**：

| 知识 | 归位 |
|---|---|
| 接入面/鉴权/端口/租户/用户/环境变量 | `systems.yaml`（endpoints + `runtime:` 段）|
| 对象结构/字段/关系/约束/**操作副作用**/**接口行为** | `objects.yaml`（`fields`/`relations`/`constraints`/`side_effects`/`api_behavior`）|
| 主键/关键字段格式 + 跨实体、跨 step 接力 | `entities.yaml`（`anchor`/`transitions`）|
| build/change 端到端步骤 | `flows/*.yaml`（`steps`/`dataflow`/`rollback`）|
| 命令树 + body schema | `<system>.yaml`（api-cli 清单）|
| 资料地图导航 | `README.md`（**只索引，不承载知识**）|

> 副作用规则（upsert、删除依赖、级联、分页格式、必填 query）是**真相来源核心**——这些最容易被契约漏掉、最值得记进 `objects.yaml.side_effects`。

### 步 6：e2e 真调验证（阶梯式，踩坑即时回流）
1. **连通 + 鉴权**：一个只读 GET 真调。失败先查鉴权（凭证？额外 header？租户/用户？）。
2. **读路径**：list/detail/search 真调，确认返回结构（wrapper? 流式 NDJSON? 字段?）。
3. **写路径**（用户授权 + 测试空间）：预检 → 建 → 改 → 删（清理）。每个失败都回溯源码/问用户，**坑即时写进 objects.yaml/systems.yaml**。
- 读通了再写；写要在可丢弃的测试空间，全程可回滚。
- ⚠️ **e2e 必须全走 scripts/run.sh（api-cli），禁用 curl**。curl 绕过清单验证，等于没验证 manifest 能用——onboarding 的核心产出（api-cli 清单）未经 api-cli 自身验证，交付即断。正确做法：`scripts/run.sh --spec <spec> <resource> <verb> [args]`，每个 e2e 场景逐条走 api-cli 命令树。

### 步 7：交付 + 自检
- **跑 lint**：`scripts/lint-platforms.py <deployment>`——校验 platforms 符合 asset-schema + 引用闭合（spec 文件存在 / api 指向 resource / ref 指向 object / flows 的 op 在 spec verbs 里）+ **source 证据门禁**（每个有 `api:` 的 object 必须有非空 `source:`，防步 3 被跳）。**0 ERR 才算产物合格**；WARN 逐条确认是否可接受。可加 `--api-cli <bin>` 额外校验 spec 能被 api-cli 解析。
- README 作资料地图索引（指向各文件）。
- e2e 场景逐条标注用哪个 resource.verb（覆盖标尺）。
- 验收 URL / 校验命令记录在 systems.yaml。
- 提交；坑已回流 platforms（**不进记忆**——platforms 是唯一真相来源；本 skill 的所有知识落在 skill 本体，遵守 AGENTS.md §8 skill 自包含纪律）。

## 初始化部署根（首次配置，一次即可）

首次接入新项目/新部署，建部署根 + 三子目录骨架：

```bash
mkdir -p $PWD/.api-orchestrator/{platforms,auth.d,env.d}
```

env.d/<dep>.env 只放业务变量（**不放路径变量**——`API_CLI_DEPLOYMENT_ROOT` 由 run.sh 从 $PWD 推导，自举会死循环）：

```bash
cat > $PWD/.api-orchestrator/env.d/demo.env <<'EOF'
export EASYOPS_ORG=18832008
export EASYOPS_USER=easyops
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
# ... 其它 EASYOPS_* 业务变量
EOF
```

auth.d 放密钥（cookie 等），格式同原 `~/.api-cli/auth.d/`（api-cli 私有约定，不改格式）。

## 首写门禁（onboarding 写 platforms 前置，强制）

onboarding 是唯一能写 platforms 的模式。**写 platforms 前**必须先验证部署根解析后的**绝对路径**已存在：

- 部署根存在 → 正常写 `$PLATFORMS_ROOT/<dep>/`
- 部署根**不存在** → **停下，打印解析后的绝对路径问用户确认**，禁止隐式 mkdir 到意外 cwd：

```bash
# onboarding 写入前自检
PLATFORMS_DIR="${API_CLI_PLATFORMS_DIR:-$PWD/.api-orchestrator/platforms}"
if [ ! -d "$PLATFORMS_DIR" ]; then
  echo "⚠️ 部署根 platforms 目录不存在: $PLATFORMS_DIR"
  echo "   初始化请运行: mkdir -p $PWD/.api-orchestrator/{platforms,auth.d,env.d}"
  echo "   确认在此 cwd ($PWD) 落地接入资料吗？请用户确认后再继续。"
  # 停下，不自动 mkdir
fi
```

---

## 3. 产物核对表（onboarding 完成应具备）

部署根 `$API_CLI_DEPLOYMENT_ROOT`（默认 `$PWD/.api-orchestrator`）下分 4 类（隔离，禁交叉写入）：
```
$API_CLI_DEPLOYMENT_ROOT/
├── platforms/<deployment>/   ← 领域知识（onboarding 产物，本目录树聚焦此）
│   ├── README.md         索引（资料地图），无知识主体
│   ├── systems.yaml      接入：endpoints/auth/runtime(端口/租户/用户/env)/capabilities/acceptance
│   ├── objects.yaml      对象：fields/relations/constraints/side_effects/api_behavior
│   ├── entities.yaml     字段：anchor/transitions
│   ├── flows/*.yaml      流程：build/change 步骤序列
│   ├── <system>.yaml     api-cli 清单：resource/verb/body schema
│   └── formats/<fmt>/    （有跨部署格式才需要）
├── auth.d/                  ← 密钥（api-cli 读，env API_CLI_AUTH_D 指此；不入 git）
├── env.d/<dep>.env          ← 非密配置（run.sh 读；只放业务变量 EASYOPS_*，不放路径变量）
└── tmp/                     ← 编排中间产物（与前三者同级隔离）
```
自检：换个 LLM 只读这些文件，能否无坑接上系统、复现场景？能 → onboarding 合格。

---

## 4. 常见盲点（实战归纳，通用）

这些是契约/文档常漏、e2e 才暴露的坑——onboarding 时主动查，别等用户撞上：

1. **契约不完整**：常只覆盖部分端点（缺 delete/detail/batch）。→ 用源码路由表补。
2. **鉴权有隐藏要求**：cookie/token 之外，常还要**租户/用户 header**（多租户系统几乎必有）。契约不写，要 e2e + 源码（grep `Header.Get`）。缺了报「empty org/user」「unauthorized」。
3. **凭证 ≠ 全部**：光有 token 不够，还要**租户号 + 有效用户标识 + 测试空间**。这些要问用户。
4. **写操作有副作用约束**：删除可能依赖「先删子/关系」、导入可能是 upsert、有 protected 不可删。→ 源码 validator/service + e2e。
5. **系统自带数据绝不能动**：生产库、系统内置租户/命名空间。→ 要用户指测试空间，或查「查租户」接口找非系统空间。
6. **声明式 vs CRUD**：有的系统建/改走「声明式导入」（一次提交整体定义，upsert），不是逐字段 CRUD。→ 影响编排设计（建模型 = import 整体，不是 N 个 create-attr）。
7. **响应格式不定**：分页可能是流式 NDJSON（非 `{data:{list}}`）、单对象可能是 wrapper、必填 query（如 `fields`）。→ e2e 确认，记进 `objects.yaml.api_behavior`。
8. **默认值在配置中心**：默认租户/org/namespace 常在运行时配置（agollo/apollo/env），源码只看到 fallback。→ 实测扫描或问用户。

---

## 5. 需要用户进一步提供的输入（优化 onboarding）

onboarding 卡住或质量不足时，按缺失向用户要：

| 症状 | 向用户要 |
|---|---|
| 端点不全 / 字段类型弱 | 后端源码位置（或更全的契约）|
| 鉴权报 empty/unauthorized | 多租户 header 名 + 租户号 + 有效账号 |
| 不知在哪测写操作 | 可写测试空间（org/namespace/project）|
| 不知默认租户/命名空间 | 默认 org/namespace 值，或「查租户」接口 |
| 场景覆盖存疑 | 补充 e2e 场景 + 验收方式 |
| 副作用不明（删/改行为）| 确认级联/依赖/protected 规则 |

---

## 6. 完整实战范例

`platforms/demo/` 是一次完整 onboarding 的产物（一个配置管理系统），覆盖：契约解析、源码补全端点、权威结构体、声明式导入、多租户鉴权、e2e 读写全路径、副作用规则、流程模板。**遇到具体问题时，参照它对应文件怎么写的**。
