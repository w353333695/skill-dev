# platforms 解耦到部署根——设计

- **日期**: 2026-08-12
- **范围**: api-orchestrator skill（`/workspace/.claude/skills/api-orchestrator/`）
- **目标**: 把 `platforms/` 从 skill 目录解耦到「部署根」，鉴权/auth/env 三者归一到同一部署根下统一管理；一次配置，后续直读。
- **状态**: 已批准（brainstorming），待写实施计划

---

## 1. 背景与问题

### 1.1 现状耦合点

api-orchestrator skill 的 platforms 路径定位**几乎全是自然语言约定，非代码硬编码**。共 4 个触点：

| 触点 | 类型 | 现状 |
|---|---|---|
| `SKILL.md` L13/45/59 | 纯文字约定 | 告诉 LLM 「查 `platforms/<deployment>/`（默认 demo）」 |
| `references/orchestration.md` L11/25 | 纯文字约定 | `grep ... platforms/demo/objects.yaml` |
| `references/onboarding.md` L3/133 | 纯文字约定 | onboarding 往 `platforms/<dep>/` 写 |
| `scripts/lint-platforms.py` `--base` | 真代码 | **已支持 `--base` 覆盖**，默认 fallback 到 skill 目录 |
| `scripts/run.sh` | 真代码 | **零耦合**——`--spec <path>` 透传给 api-cli，路径随传 |

### 1.2 鉴权三件套的所有者现状

三条路径分属两个所有者，机制不对称：

| 路径 | 所有者 | 谁读它 | 能否重定向 |
|---|---|---|---|
| `~/.api-cli/auth.d/` | **api-cli（Go 工具）** | api-cli 二进制（`internal/auth/loader.go:104`） | ✅ 已支持 `API_CLI_AUTH_D` |
| `~/.api-cli/env.d/` | **api-orchestrator（skill）** | run.sh L25（非 api-cli） | ✅ 已支持 `API_CLI_ENV_FILE` |
| `platforms/<dep>/` | **api-orchestrator（skill）** | LLM 读约定 + lint | ⚠️ 文字约定，待加 |

### 1.3 核心问题

1. platforms 耦合在 skill 包内——skill 更新/重装可能覆盖或丢失接入资料；接入数据无法独立 git 管理。
2. 鉴权（auth.d/env.d）散在 `~/.api-cli/`，platforms 在 skill 内，三者分散，一处配置多处寻找。
3. 已有钩子（`API_CLI_AUTH_D`/`API_CLI_ENV_FILE`/`--base`）skill 从未透传利用。

---

## 2. 设计决策

| 维度 | 决策 | 理由 |
|---|---|---|
| 方案 | A——环境变量驱动 | 照搬现有 env.d 自动 source 机制，认知负担零；改动面最小 |
| 默认部署根 | `$PWD/.api-orchestrator`（随调用方 cwd 项目走） | 项目级私有数据模型；换项目=换数据 |
| 三子目录归一 | `platforms/` + `auth.d/` + `env.d/` 同属部署根 | 一次配置管全局；所有者边界保留（子目录隔离） |
| fallback 语义 | 无部署根 → 回退 skill 内置 `platforms/demo` | 现有 demo 数据零迁移、零丢失；env 变量始终最高优先 |
| onboarding 首写 | 部署根不存在 → **停下打印绝对路径问用户**，禁止隐式 mkdir | onboarding 是重操作，明确落点；防数据写意外 cwd |
| 向后兼容 | **干净切换，不加**（开发阶段无老用户） | 无历史包袱；spec 明记决策防日后加回 |
| 概念位置触点 | 保留不改（asset-schema/schema 约定） | 改了反损语义；只改物理读取路径 |

---

## 3. 核心机制——部署根 + 三子目录 + 解析链

### 3.1 部署根目录结构

```
$API_CLI_DEPLOYMENT_ROOT/            ← 默认 $PWD/.api-orchestrator
├── platforms/                       ← 领域知识（skill 读）
│   └── <deployment>/                ← API_CLI_DEPLOYMENT，默认 demo
│       ├── systems.yaml
│       ├── objects.yaml / entities.yaml / README.md
│       ├── flows/ / sdk/ / formats/
│       └── <system>.yaml            ← api-cli spec
├── auth.d/                          ← 密钥（api-cli 读，env API_CLI_AUTH_D 指此）
│   └── easyops-cookie.yaml
├── env.d/                           ← 非密配置（run.sh 读）
│   └── <deployment>.env             ← EASYOPS_ORG / *_BACKEND_URL 等
└── tmp/                             ← 编排中间产物（与前三者同级隔离）
```

部署根内**只允许 4 类内容**：`platforms/`（领域知识）、`auth.d/`（密钥）、`env.d/`（非密配置）、`tmp/`（编排中间产物）。禁止交叉写入。

### 3.2 环境变量解析链

| 变量 | 谁读 | 解析优先级（高→低） |
|---|---|---|
| `API_CLI_AUTH_D` | api-cli 二进制 | 已支持；env 显式 > 派生自部署根 |
| `API_CLI_ENV_FILE` | run.sh | 已支持；env 显式 > 派生自部署根 |
| `API_CLI_PLATFORMS_DIR` | LLM 约定 + lint | **新增**；env 显式 > 派生自部署根 |
| `API_CLI_DEPLOYMENT_ROOT` | run.sh 派生用 | env 显式 > `$PWD/.api-orchestrator` |
| `API_CLI_DEPLOYMENT` | 各处 | 已支持；默认 `demo` |

### 3.3 run.sh 默认根解析（新增 ~6 行）

在 run.sh 现有 `_ENV_FILE` 解析段（L20-26）前置：

```bash
# --- 部署根解析（platforms/auth/env 三者归一）---
# 默认随调用方 cwd 项目走；无则 fallback skill 内置 platforms（LLM/lint 侧）。
# ⚠️ env 变量始终最高优先级覆盖；env.d/<dep>.env 里只放业务变量，不放路径变量（不自举）。
_APIORCH_ROOT="${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
: "${API_CLI_AUTH_D:=$_APIORCH_ROOT/auth.d}"
: "${API_CLI_ENV_FILE:=$_APIORCH_ROOT/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
: "${API_CLI_PLATFORMS_DIR:=$_APIORCH_ROOT/platforms}"
export API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
```

**bootstrap 自举原则**：`API_CLI_DEPLOYMENT_ROOT` 由 `$PWD` 推导，**不需任何地方先 export**；用户想固定根（不随 cwd 漂移）则在 shell rc 里 export 一次。

---

## 4. 读取路径改动

### 4.1 LLM 定位 platforms 根（orchestration.md 新增「步 0」）

每次编排前置强制 echo 求值当前根，拿到绝对路径后所有后续 grep/Read 都基于它：

```markdown
### 步骤 0：先定位 platforms 根（所有读取前置，强制）

platforms 根不是固定路径，每次编排先求值：
  echo "根=$API_CLI_PLATFORMS_DIR / dep=$API_CLI_DEPLOYMENT / 实际=${API_CLI_PLATFORMS_DIR:-<skill>/platforms}/${API_CLI_DEPLOYMENT:-demo}"
规则（最高优先在前）：
  1. $API_CLI_PLATFORMS_DIR 显式设 → 直接用
  2. $PWD/.api-orchestrator/platforms/<dep>/ 存在 → 用项目级（随 cwd 走）
  3. fallback → skill 内置 platforms/<dep>/
确认实际目录存在后，后续 grep/Read 全用【该绝对路径】。
```

### 4.2 文字触点改法

| 触点 | 改法 |
|---|---|
| 指代**概念位置**（SKILL.md L13、asset-schema L3 等描述 schema 结构的） | **保留不改** |
| 指代**物理读取路径**（orchestration.md L11 `grep platforms/demo/objects.yaml`、SKILL.md L59 `--spec platforms/<dep>/<sys>.yaml`、onboarding.md L3/L133） | 改为 `${PLATFORMS_ROOT}/<dep>/...`，上下文标注「PLATFORMS_ROOT 见 orchestration.md 步 0」 |

### 4.3 lint-platforms.py 默认根解析（改造 `--base` 默认值）

```python
def resolve_base(deployment):
    # 1. 显式 --base 最高优先（保留，自测用）
    # 2. $API_CLI_PLATFORMS_DIR
    if os.getenv("API_CLI_PLATFORMS_DIR"):
        return os.path.join(os.getenv("API_CLI_PLATFORMS_DIR"), deployment)
    # 3. 部署根派生
    root = os.getenv("API_CLI_DEPLOYMENT_ROOT", os.path.join(os.getcwd(), ".api-orchestrator"))
    candidate = os.path.join(root, "platforms", deployment)
    if os.path.isdir(candidate):
        return candidate
    # 4. fallback skill 内置
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(skill_dir, "platforms", deployment)
```

`--base` 仍保留（显式最高优先），默认值从「硬 skill 目录」改为「解析链」。

---

## 5. 写入路径改动

### 5.1 onboarding 首写门禁

onboarding 是唯一能写 platforms 的模式。写入前**必须**先验证部署根解析后的**绝对路径**已存在：

- 部署根存在 → 正常写 `${PLATFORMS_ROOT}/<dep>/`
- 部署根**不存在** → **停下，打印解析后的绝对路径问用户**，禁止隐式 mkdir 到意外 cwd

### 5.2 onboarding.md 改动

> 注：onboarding.md L3/L133 的物理路径改动在 §4.2 已列（读取/写入同一批触点）；本节聚焦写入特有的门禁与初始化。

- L3「录入 `platforms/<deployment>/`」→ 录入 `${PLATFORMS_ROOT}/<deployment>/`，加注「PLATFORMS_ROOT 见 orchestration.md 步 0；首次接入须先 init 部署根」
- L133 目录树结构 → 改为部署根下三子目录结构（见本 spec §3.1）
- 新增「初始化部署根」节：

```markdown
## 初始化部署根（首次配置，一次即可）

首次接入新项目/新部署：
  mkdir -p $PWD/.api-orchestrator/{platforms,auth.d,env.d}

env.d/<dep>.env 只放业务变量（不放路径变量，不自举）：
  cat > $PWD/.api-orchestrator/env.d/<dep>.env <<'EOF'
  export EASYOPS_ORG=18832008
  export EASYOPS_USER=easyops
  export EASYOPS_*_BACKEND_URL=...
  EOF
```

---

## 6. 纪律衔接

### 6.1 写保护纪律补充（SKILL.md「模式与写保护」段）

> - **部署根位置明确化**：onboarding/orchestration 写 platforms 前，先 echo 确认 `API_CLI_PLATFORMS_DIR` 解析到的**绝对路径**；部署根不存在则停下打印路径问用户。禁止隐式 mkdir 到意外 cwd。

### 6.2 状态持久化纪律衔接（SKILL.md「关键纪律」段）

部署根本身叫 `.api-orchestrator`，与现有 tmp 落点纪律（`$PWD/.api-orchestrator/tmp/<task>/`）天然统一。升级为：

> - **部署根内目录隔离**：`$PWD/.api-orchestrator/` 下只允许 4 类内容——`platforms/`、`auth.d/`、`env.d/`、`tmp/`。tmp 与前三者同级，禁止交叉写入。

### 6.3 $PWD 漂移说明（SKILL.md「核心范式」段显眼标注）

> **部署根默认 `$PWD/.api-orchestrator`——随调用时 cwd 走；想固定则在 shell rc 里 `export API_CLI_DEPLOYMENT_ROOT=/abs/path`。**

---

## 7. 迁移策略：零迁移

现有 `skill/platforms/demo/` **原地保留**作 fallback：
- 用户没建 `$PWD/.api-orchestrator/` → LLM/lint 自动回退 skill 内置 demo，行为完全不变。
- 用户想用自己的部署根 → 自己 init（§5.2），skill 内置 demo 仍兜底/参照。

**不存在搬迁现有 demo 数据的破坏性操作**，回滚成本为零（删新代码即恢复原状）。

---

## 8. 落地清单

| # | 文件 | 改动 | 性质 |
|---|---|---|---|
| 1 | `scripts/run.sh` L20-26 | 默认根解析 + 三子目录派生（~6 行 bash） | 代码 |
| 2 | `scripts/lint-platforms.py` `resolve_base()` | 环境变量 + 部署根感知默认值（~8 行 py） | 代码 |
| 3 | `SKILL.md` L45/59 + 「核心范式」$PWD 说明 + 「写保护」「状态持久化」纪律补 | 文字约定 | 文字 |
| 4 | `references/orchestration.md` 新增「步 0 定位根」+ L11/25 改物理路径 | 文字约定 | 文字 |
| 5 | `references/onboarding.md` L3/L133 改路径 + 新增「初始化部署根」节 + 停下确认纪律 | 文字约定 | 文字 |
| 6 | `references/asset-schema.md` L3 | 保留（概念位置，不改） | 不改 |

---

## 9. 风险与排除

| 风险 | 排除动作（验收门槛） | 类型 |
|---|---|---|
| **R1 文字残留** | 改完后 `grep -rn "platforms/demo" SKILL.md references/ scripts/` 剩余命中**只允许是** fallback 语义处 / asset-schema 概念位置。非预期残留 = 0。 | 硬验收（脚本） |
| **R2 API_CLI_AUTH_D 未实测** | 落地后 smoke：建 `$PWD/.api-orchestrator/auth.d/easyops-cookie.yaml` → `scripts/run.sh --spec ... object_instance search HOST --print-curl --reveal-auth` → 确认 curl 带 cookie 且 **200**。不通过阻塞。 | 硬验收（实测） |
| **R3 $PWD 漂移困惑** | SKILL.md「核心范式」段显眼写明默认根随 cwd + 固定方式。 | 文档动作 |
| **R4 向后兼容** | **不加**（干净切换）。spec 明记决策+理由，防日后加回。 | 决策记录 |

---

## 10. 验收标准

落地完成判据（全部满足）：

1. **R1 通过**：grep 验收非预期残留 = 0。
2. **R2 通过**：smoke 测 cookie 从新部署根加载且 200。
3. **lint 联动**：`scripts/lint-platforms.py demo` 在无部署根时仍 fallback 校验 skill 内置 demo（行为不变）；有部署根时校验部署根。
4. **run.sh 联动**：无 `API_CLI_*` env 时，`echo` 确认三变量派生自 `$PWD/.api-orchestrator`；设了 env 则按 env。
5. **零行为回归**：现有 orchestration 流程（不建部署根）与改造前完全一致（fallback 生效）。
