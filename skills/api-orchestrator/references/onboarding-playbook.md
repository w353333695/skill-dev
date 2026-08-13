# onboarding-playbook.md —— 模块接入实战 Playbook

> `onboarding.md` 是通用 7 步流程；本文件是其**实战补充**——从 collector_plugin_service 接入实战提炼的
> 操作清单、产物范例、踩坑 checklist。**发起任何新模块接入，按本文件走一遍**，配合 onboarding.md 用。

---

## 一、接入标准流程（每步的产出 + 验证）

| 阶段 | 做什么 | 产出 | 验证 |
|---|---|---|---|
| **0. 探索** | 派多个 Explore agent 同步并行深挖源码（**禁用 background，会丢**）；load-bearing 事实自己 grep 实锤，**不全信 agent** | 端点表/数据模型/副作用/运行时拓扑 | 每结论带 file:line |
| **1. 找权威源** | 优先找权威契约（OpenAPI/源码/官方 CLI contracts），区分「源码版本」vs「实际部署」（源码可能落后） | 权威源清单 | 双源交叉验证 |
| **2. 产 api-cli 清单** | `<system>.yaml`：service/endpoints + resources/operations，body schema **内联** | `<system>.yaml` | `api-cli --spec X --help`/`explain`/`--dry-run` 三验 |
| **3. 产 objects/systems/entities** | 对象模型+副作用 / 接入面+runtime坑 / 字段锚+接力 | 3 个 yaml | grep 定位能读懂 |
| **4. 写 flows** | e2e 流程模板，非 API 步骤 `op:` 留空 | flows/*.yaml | lint 校验 op 在 spec verbs |
| **5. 真调** | 读路径 api-cli 直接调；multipart/binary 走 curl -F 或 SDK；写操作测试 org | 真调结果回流 systems/objects | HTTP code + 响应字段 |
| **6. lint + 收尾** | `lint-platforms.py <dep> --api-cli <bin>` | 0 ERR | 0 ERR 才合格 |

---

## 二、产物结构（platforms/<deployment>/ 范例）

```
platforms/<deployment>/
├── README.md                    索引（资料地图 + 关键认知 + 真调状态），不承载知识主体
├── systems.yaml                  接入面（端口/鉴权/org/user）+ capabilities + runtime坑 + e2e_verified
├── objects.yaml                  对象结构（fields/relations/constraints）+ side_effects + api_behavior
├── entities.yaml                 字段锚（主键格式/正则）+ transitions（跨 step 接力）
├── <system>.yaml                 api-cli 清单（resource/verb/body schema 内联）
├── flows/*.yaml                  e2e 流程模板
├── formats/<fmt>/                跨部署复用格式包（如有，如 collector-kit）
└── sdk/                          编排侧补丁（api-cli 不支持的 multipart/签名，如 easyops_client.py）
```

**填写范例的尺度**（这次 collector 接入）：
- systems.yaml：每 system 含 description/spec/endpoints/auth/env/capabilities/runtime/acceptance_urls，runtime 段是坑的真相来源
- objects.yaml：核心对象 40+ 字段（真调 detail 实锤），side_effects 每条带 op+rule+source
- 每个 side_effect/field 必带 `source: file:line`（lint source 证据门禁）

---

## 三、关键纪律（踩坑 → checklist）

### 探索阶段
- [ ] **background agent 会丢**（session 退出 kill）→ 用同步 agent（`run_in_background: false`）
- [ ] **agent 结论不可全信** → load-bearing 事实（端点存在性/端口/字段）自己 grep 实锤。反例：agent 说 activate 端点不存在，实测在另一端口存在（源码是旧版）
- [ ] **过时资料会误导** → 双源交叉验证；过时文档 vs 源码冲突时，以**实际运行时**为准（如 py2 vs py3 文档）
- [ ] **找权威契约源** → 优先 OpenAPI/官方 CLI contracts/源码路由表，不全信 agent 的源码副本（可能是旧版）

### 部署根/deployment
- [ ] **步0 门禁**：部署根 + env.d/<dep>.env + auth.d/<name>.yaml 三件，缺即停问用户
- [ ] **deployment 隔离 vs 合并**：同一套系统（不同实例，迁移场景）→ 合并；独立系统 → 新 deployment。org 环境变量是 deployment 级单一文件
- [ ] **env 变量名隔离**：合并时不同实例的 org 用独立变量名（`${X_ORG}`），或迁移场景共用（老系统暂调不通待迁）
- [ ] **auth.d 平铺共享**：靠 `endpoint.auth: <name>` 选 cookie 文件，多实例按文件名区分
- [ ] **部署根不入 git**（含密钥）；platforms/ 入 git（接入资料可分发）

### api-cli 清单
- [ ] **body schema 内联**，无 `$ref`
- [ ] **`required` 双义**：`params.required` 是 bool；schema 的 `required` 是父级 `[]string`（字段名列表）。**不**在单个 property 写 `required: true`
- [ ] property 字段：用 `description`（非 `desc`），支持 `type/items/properties/enum/pattern/additional_properties`，**不**支持 `default/minimum/`属性级 required
- [ ] multipart/binary 端点：description 标「api-cli 仅 --print-curl，真调走 SDK/curl」，不声明 JSON body schema
- [ ] 每端点写 `description`（进 MCP tool description，决定 LLM 抉择）

### 真调
- [ ] 读路径 api-cli 直接调；写操作先确认门（`--yes` 跳过）
- [ ] **list 计数坑**：total 可能在 `data.total`（body 内）非 stderr `_meta.total`，实测确认记 runtime
- [ ] 响应 wrapper 格式实测确认（`{code,message,error,data}` vs `{code,codeExplain,error,data}`）
- [ ] 坑即时回流 systems/objects（**不进 memory**，platforms 是唯一真相来源）

### skill 自包含
- [ ] platforms/ 知识自包含，**不引用 tmp/ 或 platforms 外文件**（分发即断）
- [ ] `source:` 是溯源（非知识依赖），知识内联
- [ ] gap 如实标注（查不到标「未知-待捕获」，不编）

---

## 四、接入前必问用户清单

| # | 问题 | 为什么 |
|---|---|---|
| 1 | **环境可达性**（host/org/cookie/user） | 真调必备；缺失只能离线交付 |
| 2 | **deployment 归属**（并入现有 or 新建） | 决定文件落点 + env/auth 怎么配 |
| 3 | **真调范围**（离线交付 or 全程真调） | 决定是否含写操作 e2e |
| 4 | **运行时约束**（脚本语言版本、特殊环境） | collector 实例：py2.7 vs 文档 py3，必须问清 |
| 5 | **跨实例关系**（多环境是同系统不同实例，还是独立系统） | 决定 deployment 合并/隔离 |
| 6 | **业务前置门禁**（如套件的 CMDB 模型确认+客户确认） | 容易漏，需主动问业务流程 |

---

## 五、流程模板的硬前置门禁（业务类，易漏）

套件开发的教训：**生成产物前，必须先走业务前置门禁**。其他模块同理，先问「这步业务上该先确认什么」。

范例（套件开发的 CMDB 模型门禁，见 flows/develop-and-import-kit.yaml step 1-3）：
1. **需求确认**：向客户对齐对象/内容/方式
2. **现有资源确认**：在系统查是否已有合适资源（CMDB 查模型）
3. **设计+客户确认**：无则设计（属性/关系），**必须客户拍板**，影响下游参数

→ 模板：任何「生成产物」类 flow，第 1-3 步应是「需求→查现有→设计+确认」，禁止跳到生成。

---

## 六、验证门禁

```bash
# 1. lint（必过，0 ERR 才合格）
python3 scripts/lint-platforms.py <deployment> --api-cli bin/api-cli

# 2. api-cli spec 可解析
bin/api-cli --spec <system>.yaml --help              # resource 树渲染
bin/api-cli --spec <system>.yaml explain <R> <V>     # schema 透传
bin/api-cli --spec <system>.yaml <R> <V> --dry-run   # URL/body 构造

# 3. 真调回归（读路径）
scripts/run.sh --spec <system>.yaml <resource> <verb> [args]

# 4. 真调写路径（multipart 走 curl -F / SDK）
curl -F "attachment=@<file>" -H "org: ..." -H "user: ..." http://<host>:<port>/<path>
```

---

## 七、实战数字（collector 接入，供规模参照）

- 探索：4 个同步 Explore agent，每个读 5-10 个源码文件
- 产物：2 spec（25 端点）+ systems(690行) + objects(54对象) + entities(25锚) + 3 flows + formats(4文件1110行)
- 真调：8151 端点 7 操作全验证（import/export/import_update/delete/list/detail/metricbeat_list）
- gap：activate contract（环境未部署）+ 协议解析（在 agent 端源码不在本地）—— 如实标 gap 不硬填
- lint：41 OK / 0 ERR / 3 WARN（WARN 是已知端点 gap + lint 误报，逐条确认可接受）

---

## 八、合并/隔离决策树

```
新模块接入
├─ 同一套系统（不同实例/迁移场景）？
│   ├─ 是 → 合并到现有 deployment
│   │       env：org 用独立变量名 OR 迁移场景共用（老系统暂调不通）
│   │       auth：cookie 文件按实例命名，endpoint.auth 指向
│   └─ 否 → 新 deployment（platforms/<new>/）
│           env.d/<new>.env + 独立 README/systems/objects/entities
└─ 跨部署复用的格式知识（如套件包格式）？
    └─ 放 formats/<fmt>/（任一 deployment 下，跨部署复用）
```
