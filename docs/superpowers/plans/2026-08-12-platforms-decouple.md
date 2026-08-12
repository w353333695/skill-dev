# platforms 解耦到部署根 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 api-orchestrator skill 的 `platforms/` + auth + env 三者从分散位置归一到部署根 `$PWD/.api-orchestrator`，环境变量驱动解析 + fallback skill 内置 demo，实现一次配置后续直读。

**Architecture:** 三条路径（`auth.d`/`env.d`/`platforms`）分属两个所有者（api-cli vs skill），统一到部署根下各管子目录。run.sh 加 ~6 行默认根解析（派生三变量），lint 加 `resolve_base()` 解析链，文字约定改 11 处物理读取路径为 `${PLATFORMS_ROOT}`。现有 skill 内置 `platforms/demo` 原地保留作 fallback，零迁移。

**Tech Stack:** Bash（run.sh）、Python3（lint-platforms.py）、Markdown（SKILL.md/references）。

**设计 spec:** `docs/superpowers/specs/2026-08-12-platforms-decouple-design.md`

## Global Constraints

- 默认部署根：`$PWD/.api-orchestrator`（随调用方 cwd 项目走）。
- 三子目录：`platforms/` + `auth.d/` + `env.d/` + `tmp/`（4 类隔离，禁止交叉写入）。
- 环境变量解析优先级（高→低）：`API_CLI_AUTH_D`/`API_CLI_ENV_FILE`/`API_CLI_PLATFORMS_DIR` 显式 > 派生自 `API_CLI_DEPLOYMENT_ROOT` > `$PWD/.api-orchestrator` 推导 > fallback skill 内置 `platforms/<dep>`。
- env 变量始终最高优先级覆盖；`env.d/<dep>.env` 里**只放业务变量**（EASYOPS_*），**不放路径变量**（不自举）。
- `API_CLI_AUTH_D` 已被 api-cli 二进制支持（`internal/auth/loader.go:104`）；`API_CLI_ENV_FILE` 已被 run.sh L25 支持。
- **干净切换，不加向后兼容**（开发阶段无老用户，spec §9 R4）。
- onboarding 首写部署根不存在 → **停下打印绝对路径问用户**，禁止隐式 mkdir。
- 现有 skill 内置 `platforms/demo/` 原地保留作 fallback，**零迁移、零删除**。
- 每个 task 改完即 commit（frequent commits）。
- tmp 落点纪律：本任务所有临时验证脚本写到 `mktemp -d` 或 `$PWD/.api-orchestrator/tmp/`，**严禁写 skill 目录**。

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `scripts/run.sh` L20-26 | 部署根解析 + 三变量派生 | 改（加 ~6 行前置） |
| `scripts/lint-platforms.py` L42-49 | `resolve_base()` 解析链 | 改（重构默认值） |
| `scripts/lint-platforms.test.py` | lint 自测 fixture | 改（加 env 变量解析测试） |
| `SKILL.md` L17-21,45,59,86-99 | 核心范式 $PWD 说明 + 物理路径 + 写保护/纪律补 | 改（文字） |
| `references/orchestration.md` L5-18,25 | 新增「步 0 定位根」+ 物理路径 | 改（文字） |
| `references/onboarding.md` L3,133, +新节 | 物理路径 + 部署根初始化节 + 停下确认 | 改（文字） |
| `references/asset-schema.md` L3 | 概念位置 | **不改** |

---

## Task 1: run.sh 部署根解析

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/scripts/run.sh:20-26`

**Interfaces:**
- Consumes: 现有 `API_CLI_ENV_FILE` / `API_CLI_DEPLOYMENT`（run.sh L23,25）；api-cli 的 `API_CLI_AUTH_D`（loader.go:104）
- Produces: export `API_CLI_DEPLOYMENT_ROOT` / `API_CLI_AUTH_D` / `API_CLI_ENV_FILE` / `API_CLI_PLATFORMS_DIR` 四变量（供 api-cli、run.sh 后续、lint、LLM echo 求值）

**为什么先做这个：** 它是整个解析链的单一来源，后续 task（lint、文字约定）都依赖它定义的变量名。

- [ ] **Step 1: 写验证脚本（手动 TDD——bash 无单测框架，用 expect/actual 断言脚本）**

写到 `$(mktemp -d)/test_runsh_root.sh`（**不写 skill 目录**）：

```bash
#!/usr/bin/env bash
# 验证 run.sh 的部署根解析逻辑（不 exec 真二进制，只 source 解析段）。
set -uo pipefail
SKILL_DIR="/workspace/.claude/skills/api-orchestrator"
fails=0

# 抽取 run.sh 的解析段（L20-26 的升级版）成独立函数，便于测试。
# 由于 run.sh 在解析后立即 exec，无法整体 source——这里复制解析段做行为等价测试。
parse_root() {
    local _APIORCH_ROOT="${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
    : "${API_CLI_AUTH_D:=$_APIORCH_ROOT/auth.d}"
    : "${API_CLI_ENV_FILE:=$_APIORCH_ROOT/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
    : "${API_CLI_PLATFORMS_DIR:=$_APIORCH_ROOT/platforms}"
    export API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
}

# Case 1: 无任何 env → 派生自 $PWD/.api-orchestrator
cd "$(mktemp -d)"  # 干净 cwd，无 .api-orchestrator
unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT
parse_root
EXPECTED="$PWD/.api-orchestrator"
[ "$API_CLI_AUTH_D" = "$EXPECTED/auth.d" ] || { echo "FAIL c1 AUTH_D: got $API_CLI_AUTH_D"; fails=$((fails+1)); }
[ "$API_CLI_ENV_FILE" = "$EXPECTED/env.d/demo.env" ] || { echo "FAIL c1 ENV_FILE: got $API_CLI_ENV_FILE"; fails=$((fails+1)); }
[ "$API_CLI_PLATFORMS_DIR" = "$EXPECTED/platforms" ] || { echo "FAIL c1 PLATFORMS_DIR: got $API_CLI_PLATFORMS_DIR"; fails=$((fails+1)); }

# Case 2: API_CLI_DEPLOYMENT_ROOT 显式 → 三者派生自它
unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR
export API_CLI_DEPLOYMENT_ROOT="/custom/root"
parse_root
[ "$API_CLI_AUTH_D" = "/custom/root/auth.d" ] || { echo "FAIL c2 AUTH_D"; fails=$((fails+1)); }
[ "$API_CLI_PLATFORMS_DIR" = "/custom/root/platforms" ] || { echo "FAIL c2 PLATFORMS_DIR"; fails=$((fails+1)); }

# Case 3: 三变量各自显式 → 最高优先，不被 ROOT 覆盖
unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR
export API_CLI_AUTH_D="/explicit/auth" API_CLI_ENV_FILE="/explicit/e.env" API_CLI_PLATFORMS_DIR="/explicit/plat"
parse_root
[ "$API_CLI_AUTH_D" = "/explicit/auth" ] || { echo "FAIL c3 AUTH_D overridden"; fails=$((fails+1)); }
[ "$API_CLI_PLATFORMS_DIR" = "/explicit/plat" ] || { echo "FAIL c3 PLATFORMS_DIR overridden"; fails=$((fails+1)); }

# Case 4: API_CLI_DEPLOYMENT=prod → env.d 文件名跟着变
unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT
export API_CLI_DEPLOYMENT=prod
parse_root
[[ "$API_CLI_ENV_FILE" == *"/env.d/prod.env" ]] || { echo "FAIL c4 ENV_FILE dep: $API_CLI_ENV_FILE"; fails=$((fails+1)); }

if [ $fails -eq 0 ]; then echo "✓ run.sh 部署根解析：4 case 全通"; else echo "❌ $fails fails"; exit 1; fi
```

- [ ] **Step 2: 跑测试，确认它对【当前未改的 run.sh】暴露 case1 以外的预期**

Run: `bash <path-to>/test_runsh_root.sh`
Expected: PASS（这个测试测的是 `parse_root` 函数本身，即目标逻辑；当前 run.sh 还没改，但测试是自包含的——它复制了解析段做行为验证。**如果 pass 说明解析段逻辑正确，可移植进 run.sh**）。

> 说明：bash 测试无法直接 source run.sh（它会 exec 二进制退出），故测试用等价函数验证逻辑。移植时必须逐字复制 `parse_root` 内部的 5 行到 run.sh。

- [ ] **Step 3: 改 run.sh——在 L20 前插入部署根解析段**

把 run.sh 现有 L20-26：
```bash
# --- 自动加载非密环境变量（密钥仍由 api-cli 走 ~/.api-cli/auth.d）---
# 约定：~/.api-cli/env.d/<deployment>.env 放 org/user/endpoint 等非密值；
#   调用方零传输——初始化一次后 run.sh 自动 source。opt-in：无文件即跳过。
#   API_CLI_ENV_FILE 直指文件；API_CLI_DEPLOYMENT 选部署（默认 demo）。
#   ⚠️ 文件里的值会覆盖 shell 已设的同名 env（set -a 导出）；想临时覆盖，调用前 export。
_ENV_FILE="${API_CLI_ENV_FILE:-$HOME/.api-cli/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
[ -f "$_ENV_FILE" ] && { set -a; . "$_ENV_FILE"; set +a; }
```

改为（在原段前加部署根解析，原段保留但 `_ENV_FILE` 已由解析段派生）：
```bash
# --- 部署根解析（platforms/auth/env 三者归一到 $API_CLI_DEPLOYMENT_ROOT）---
# 默认随调用方 cwd 项目走（$PWD/.api-orchestrator）；想固定则 shell rc 里 export API_CLI_DEPLOYMENT_ROOT。
# ⚠️ env 变量始终最高优先级覆盖；env.d/<dep>.env 里只放业务变量，不放路径变量（不自举）。
_APIORCH_ROOT="${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
: "${API_CLI_AUTH_D:=$_APIORCH_ROOT/auth.d}"
: "${API_CLI_ENV_FILE:=$_APIORCH_ROOT/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
: "${API_CLI_PLATFORMS_DIR:=$_APIORCH_ROOT/platforms}"
export API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT

# --- 自动加载非密环境变量（密钥由 api-cli 走 $API_CLI_AUTH_D，默认部署根/auth.d）---
# 约定：$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env 放 org/user/endpoint 等非密值；
#   调用方零传输——初始化一次后 run.sh 自动 source。opt-in：无文件即跳过。
#   API_CLI_ENV_FILE 直指文件；API_CLI_DEPLOYMENT 选部署（默认 demo）。
#   ⚠️ 文件里的值会覆盖 shell 已设的同名 env（set -a 导出）；想临时覆盖，调用前 export。
[ -f "$API_CLI_ENV_FILE" ] && { set -a; . "$API_CLI_ENV_FILE"; set +a; }
```

关键变化：① 删除原硬编码 `$HOME/.api-cli/...` 默认（干净切换，spec R4）；② `_ENV_FILE` 直接用解析段派生的 `$API_CLI_ENV_FILE`（已被 `:` 赋默认）；③ `export` 三变量供 api-cli/lint 用。

- [ ] **Step 4: 跑解析验证（不 exec 真二进制，确认 run.sh 能 source 到解析段不报错）**

Run:
```bash
cd /tmp  # 干净 cwd
# 提取 run.sh 改后的解析段（到 exec 前）source 它，验证四变量被 export
sed -n '20,30p' /workspace/.claude/skills/api-orchestrator/scripts/run.sh | head -20
# 直接跑一遍 Step1 的测试（它测的就是移植后的逻辑）
bash <path-to>/test_runsh_root.sh
```
Expected: Step1 测试 4 case 全通（`✓ run.sh 部署根解析：4 case 全通`）。

- [ ] **Step 5: 提交**

```bash
cd /workspace
git add .claude/skills/api-orchestrator/scripts/run.sh
git commit -m "feat(api-orchestrator): run.sh 部署根解析（platforms/auth/env 归一）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: lint-platforms.py `resolve_base()` 解析链

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/scripts/lint-platforms.py:42-49`
- Modify: `/workspace/.claude/skills/api-orchestrator/scripts/lint-platforms.test.py`（加 env 变量解析 case）

**Interfaces:**
- Consumes: `API_CLI_PLATFORMS_DIR` / `API_CLI_DEPLOYMENT_ROOT` 环境变量（Task 1 已 export）
- Produces: `lint-platforms.py <dep>` 的 base 解析遵循与 run.sh 一致的链（`--base` 显式 > env > 部署根派生 > skill 内置 fallback）

**为什么这个顺序：** lint 是 onboarding 的质量门（spec §10 验收 3），必须和 run.sh 用同一套解析语义，否则两套路径打架。

- [ ] **Step 1: 写失败测试——加 env 变量解析 case 到 lint-platforms.test.py**

在 `lint-platforms.test.py` 的 `# ============ 报告 ============` 之前（L98 前）插入新 case：

```python
        # ============ resolve_base 解析链 case（env 变量 / 部署根派生）============
        import importlib.util
        spec = importlib.util.spec_from_file_location("lint_mod", LINT)
        lint_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint_mod)

        # Case A: API_CLI_PLATFORMS_DIR 设了 → base = <dir>/<dep>
        os.environ["API_CLI_PLATFORMS_DIR"] = os.path.join(tmp, "ext-platforms")
        os.environ.pop("API_CLI_DEPLOYMENT_ROOT", None)
        write(os.path.join(tmp, "ext-platforms", "envdep", "systems.yaml"), "deployment: envdep\n")
        write(os.path.join(tmp, "ext-platforms", "envdep", "README.md"), "# x\n")
        got = lint_mod.resolve_base("envdep")
        if got != os.path.join(tmp, "ext-platforms", "envdep"):
            fails.append(f"[resolve A] PLATFORMS_DIR: got {got}")

        # Case B: 无 PLATFORMS_DIR，有 DEPLOYMENT_ROOT 且目录存在 → 派生
        del os.environ["API_CLI_PLATFORMS_DIR"]
        os.environ["API_CLI_DEPLOYMENT_ROOT"] = os.path.join(tmp, "myroot")
        write(os.path.join(tmp, "myroot", "platforms", "rdep", "systems.yaml"), "deployment: rdep\n")
        got = lint_mod.resolve_base("rdep")
        if got != os.path.join(tmp, "myroot", "platforms", "rdep"):
            fails.append(f"[resolve B] ROOT派生: got {got}")

        # Case C: 都没设，目录不存在 → fallback skill 内置（含 <skill>/platforms/<dep>）
        del os.environ["API_CLI_DEPLOYMENT_ROOT"]
        got = lint_mod.resolve_base("nonexist_dep_xyz")
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(LINT)))
        expected = os.path.join(skill_dir, "platforms", "nonexist_dep_xyz")
        if got != expected:
            fails.append(f"[resolve C] fallback: got {got}, expected {expected}")

        # 清理环境变量，避免污染后续
        os.environ.pop("API_CLI_PLATFORMS_DIR", None)
        os.environ.pop("API_CLI_DEPLOYMENT_ROOT", None)
```

- [ ] **Step 2: 跑测试，确认它 FAIL（`resolve_base` 还不存在）**

Run: `cd /workspace/.claude/skills/api-orchestrator && python3 scripts/lint-platforms.test.py`
Expected: FAIL，报 `AttributeError: module 'lint_mod' has no attribute 'resolve_base'`（或 `[resolve A]` fail）。

- [ ] **Step 3: 实现 `resolve_base()`——重构 lint-platforms.py 的 base 解析**

把 lint-platforms.py 现有 L42-49（main 函数内的 base 解析）：
```python
    ap.add_argument("--base", help="platforms 根目录覆盖（自测用；默认 <skill>/platforms）")
    args = ap.parse_args()

    if args.base:
        base = os.path.join(args.base, args.deployment)
    else:
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # skills/api-orchestrator/
        base = os.path.join(skill_dir, "platforms", args.deployment)
```

改为（抽出 `resolve_base()` 函数，main 调用它）：

在 `def main():` **之前**（L37 `def main():` 上方）加新函数：
```python
def resolve_base(deployment, override=None):
    """解析 platforms base 目录（与 run.sh 部署根解析同语义）。

    优先级（高→低）：
      1. override（--base 显式，自测用）
      2. $API_CLI_PLATFORMS_DIR/<deployment>
      3. $API_CLI_DEPLOYMENT_ROOT/platforms/<deployment>（目录存在才用）
      4. fallback <skill>/platforms/<deployment>
    """
    if override:
        return os.path.join(override, deployment)
    env_platforms = os.getenv("API_CLI_PLATFORMS_DIR")
    if env_platforms:
        return os.path.join(env_platforms, deployment)
    root = os.getenv("API_CLI_DEPLOYMENT_ROOT", os.path.join(os.getcwd(), ".api-orchestrator"))
    candidate = os.path.join(root, "platforms", deployment)
    if os.path.isdir(candidate):
        return candidate
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # skills/api-orchestrator/
    return os.path.join(skill_dir, "platforms", deployment)
```

把 main 内的 base 解析改为调用：
```python
    ap.add_argument("--base", help="platforms 根目录覆盖（自测用；默认按解析链：API_CLI_PLATFORMS_DIR → 部署根 → skill 内置）")
    args = ap.parse_args()

    base = resolve_base(args.deployment, override=args.base)
```

- [ ] **Step 4: 跑测试，确认 PASS（含新 resolve_base case + 原 good/bad case 不回归）**

Run: `cd /workspace/.claude/skills/api-orchestrator && python3 scripts/lint-platforms.test.py`
Expected: `✓ lint 自测通过：good 放行... / bad 抓错...`（原有）+ 无 `[resolve *]` fail（新增）。

- [ ] **Step 5: 实测 fallback 联动——无部署根时 lint demo 仍校验 skill 内置**

Run:
```bash
cd /tmp  # 干净 cwd，无 .api-orchestrator
unset API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
python3 /workspace/.claude/skills/api-orchestrator/scripts/lint-platforms.py demo 2>&1 | tail -3
```
Expected: 输出 `lint platforms/demo/` 且 exit 0 无 ERR（fallback 到 skill 内置 demo，行为与改造前一致）。验证：`echo $?` 应为 `0`。

- [ ] **Step 6: 提交**

```bash
cd /workspace
git add .claude/skills/api-orchestrator/scripts/lint-platforms.py .claude/skills/api-orchestrator/scripts/lint-platforms.test.py
git commit -m "feat(api-orchestrator): lint resolve_base 解析链（env/部署根/fallback）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: orchestration.md「步 0 定位根」+ 物理路径

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/references/orchestration.md:5-18`（新增步 0）
- Modify: `/workspace/.claude/skills/api-orchestrator/references/orchestration.md:11`（grep 路径）
- Modify: `/workspace/.claude/skills/api-orchestrator/references/orchestration.md:25`（查 systems.yaml 路径）

**Interfaces:**
- Consumes: Task 1/2 的变量名（`API_CLI_PLATFORMS_DIR` / `API_CLI_DEPLOYMENT`）
- Produces: LLM 编排前的「步 0」定位约定——后续所有 task（SKILL.md/onboarding.md）引用此节

**为什么先做文字：** 步 0 是后续 SKILL.md/onboarding.md 物理路径改动的「锚点引用」，先立它。

- [ ] **Step 1: 在 orchestration.md「读取纪律」段最前（L7 后）插入「步 0」**

把现有 L5-7：
```markdown
## 读取纪律（所有挡位前置，强制）

调度靠 LLM 推理、**无代码引擎兜底**——platforms 读取须守此纪律，保证一致 + 省 token：
```

改为（加步 0 子节）：
```markdown
## 读取纪律（所有挡位前置，强制）

调度靠 LLM 推理、**无代码引擎兜底**——platforms 读取须守此纪律，保证一致 + 省 token：

### 步骤 0：先定位 platforms 根（所有读取前置，强制）

platforms 根不是固定路径，每次编排先求值（部署根默认 `$PWD/.api-orchestrator`，随 cwd 走）：

```bash
echo "PLATFORMS_ROOT=${API_CLI_PLATFORMS_DIR:-<未设，按链解析>} dep=${API_CLI_DEPLOYMENT:-demo}"
# 解析规则（最高优先在前）：
#   1. $API_CLI_PLATFORMS_DIR 显式设 → 直接用
#   2. $PWD/.api-orchestrator/platforms/<dep>/ 存在 → 用项目级（随 cwd 走）
#   3. fallback → skill 内置 platforms/<dep>/
```

确认 PLATFORMS_ROOT 实际目录后，后续所有 grep/Read 全用 **`$PLATFORMS_ROOT/<dep>/...` 绝对路径**。
（run.sh 已自动 export `API_CLI_PLATFORMS_DIR`；echo 确认即可。）
```

- [ ] **Step 2: 改 L11 的 grep 物理路径**

把 L11：
```markdown
   - **精准定位**：先 `grep -n "关键词" platforms/demo/objects.yaml` 拿行号 → `Read --offset=<行号> limit=30` 取该段。一步命中，不读全文。
```
改为：
```markdown
   - **精准定位**：先 `grep -n "关键词" $PLATFORMS_ROOT/<dep>/objects.yaml`（PLATFORMS_ROOT 见上「步骤 0」）拿行号 → `Read --offset=<行号> limit=30` 取该段。一步命中，不读全文。
```

- [ ] **Step 3: 改 L25 的 systems.yaml 物理路径**

把 L25（直通挡流程第 1 步）：
```markdown
1. 查 `platforms/<dep>/systems.yaml` → 找到目标系统的 spec + resource/verb。
```
改为：
```markdown
1. 先走「读取纪律·步骤 0」求值 `$PLATFORMS_ROOT`。查 `$PLATFORMS_ROOT/<dep>/systems.yaml` → 找到目标系统的 spec + resource/verb。
```

- [ ] **Step 4: 验收——grep 确认 orchestration.md 物理路径已改，无残留硬编码**

Run:
```bash
grep -n "platforms/demo\|platforms/<dep>" /workspace/.claude/skills/api-orchestrator/references/orchestration.md
```
Expected: 命中应只剩「步骤 0」解析规则里的 `platforms/<dep>/`（那是解析链描述，非硬编码物理路径）+ `skill 内置 platforms/<dep>/`（fallback 语义）。**不应再有** `grep ... platforms/demo/objects.yaml` 这类直接物理读取。

- [ ] **Step 5: 提交**

```bash
cd /workspace
git add .claude/skills/api-orchestrator/references/orchestration.md
git commit -m "docs(api-orchestrator): orchestration 步0定位 platforms 根 + 物理路径改

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: onboarding.md 物理路径 + 初始化节 + 停下确认

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/references/onboarding.md:3`（L3 物理路径）
- Modify: `/workspace/.claude/skills/api-orchestrator/references/onboarding.md:133-141`（目录树结构）
- 新增节：初始化部署根 + 首写门禁

**Interfaces:**
- Consumes: Task 3 的「PLATFORMS_ROOT 见 orchestration.md 步 0」引用
- Produces: onboarding 写入路径约定 + 首写门禁纪律（spec §5.1）

- [ ] **Step 1: 改 L3 物理路径**

把 onboarding.md L3：
```markdown
> onboarding 的目标：把「系统资料」（契约/抓包/源码/场景）整理录入 `platforms/<deployment>/`（符合 `asset-schema.md`），让 skill + platforms 能分发到**任意系统、任意 LLM**，读资料即能编排用户需求。
```
改为：
```markdown
> onboarding 的目标：把「系统资料」（契约/抓包/源码/场景）整理录入 **`$PLATFORMS_ROOT/<deployment>/`**（PLATFORMS_ROOT 解析见 orchestration.md「步骤 0」；符合 `asset-schema.md`），让 skill + platforms 能分发到**任意系统、任意 LLM**，读资料即能编排用户需求。**首次接入须先初始化部署根（见下「初始化部署根」）。**
```

- [ ] **Step 2: 改 L133-141 目录树结构**

把现有目录树（L133-141）：
```markdown
platforms/<deployment>/
├── README.md         索引（资料地图），无知识主体
├── systems.yaml      接入：endpoints/auth/runtime(端口/租户/用户/env)/capabilities/acceptance
├── objects.yaml      对象：fields/relations/constraints/side_effects/api_behavior
├── entities.yaml     字段：anchor/transitions
├── flows/*.yaml      流程：build/change 步骤序列
├── <system>.yaml     api-cli 清单：resource/verb/body schema
└── formats/<fmt>/    （有跨部署格式才需要）
```
改为（在 platforms 前加部署根上下文）：
```markdown
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
```

- [ ] **Step 3: 新增「初始化部署根」+「首写门禁」节**

在 onboarding.md 的「## 3. 产物核对表」**之前**（L128 `---` 之前）插入新节：

```markdown
## 初始化部署根（首次配置，一次即可）

首次接入新项目/新部署，建部署根 + 三子目录骨架：

```bash
mkdir -p $PWD/.api-orchestrator/{platforms,auth.d,env.d}
```

env.d/<dep>.env 只放业务变量（**不放路径变量**——API_CLI_DEPLOYMENT_ROOT 由 run.sh 从 $PWD 推导，自举会死循环）：

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
```

- [ ] **Step 4: 验收——grep 确认 onboarding.md 无残留硬编码 + 新节存在**

Run:
```bash
grep -n "初始化部署根\|首写门禁\|PLATFORMS_ROOT" /workspace/.claude/skills/api-orchestrator/references/onboarding.md | head
```
Expected: 命中「初始化部署根」「首写门禁」节标题 + L3 的 PLATFORMS_ROOT。

- [ ] **Step 5: 提交**

```bash
cd /workspace
git add .claude/skills/api-orchestrator/references/onboarding.md
git commit -m "docs(api-orchestrator): onboarding 部署根初始化 + 首写门禁 + 物理路径

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: SKILL.md 核心范式 $PWD + 物理路径 + 纪律补

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md:17-21`（核心范式加 $PWD 说明）
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md:45`（资料段物理路径）
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md:59`（执行段物理路径）
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md:86-89`（写保护纪律加部署根明确化）
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md:95`（状态持久化纪律升级为目录隔离）

**Interfaces:**
- Consumes: Task 3 步 0、Task 4 初始化/门禁的引用
- Produces: SKILL.md 顶层契约（核心范式 $PWD 说明是 spec §9 R3 的排除动作）

- [ ] **Step 1: 核心范式段加 $PWD 漂移说明（spec §6.3 / R3）**

把 SKILL.md L17-21：
```markdown
## 核心范式

- **调度器 = 你（LLM）**：读本 SKILL 的决策树，对每个需求推理分派。没有代码调度引擎。
- **执行 = bash 调 scripts/run.sh**：统一执行入口（读 manifest.sh 自动定位 binary，Go/Python 通用），每个系统是一份 api-cli 清单（spec）。
- **知识 = platforms/ 资料**：系统目录/实体映射/对象关系/流程模板/格式包，全部可替换。
```
改为：
```markdown
## 核心范式

- **调度器 = 你（LLM）**：读本 SKILL 的决策树，对每个需求推理分派。没有代码调度引擎。
- **执行 = bash 调 scripts/run.sh**：统一执行入口（读 manifest.sh 自动定位 binary，Go/Python 通用），每个系统是一份 api-cli 清单（spec）。
- **知识 = platforms/ 资料**：系统目录/实体映射/对象关系/流程模板/格式包，全部可替换。
- **部署根（platforms/auth/env 归一）**：三者默认归一到 `$PWD/.api-orchestrator`——**随调用时 cwd 走**；想固定则在 shell rc 里 `export API_CLI_DEPLOYMENT_ROOT=/abs/path`。无部署根时 fallback skill 内置 `platforms/demo`（行为不变）。详见 orchestration.md「步骤 0」。
```

- [ ] **Step 2: 改 L45 资料段物理路径**

把 L45：
```markdown
查 `platforms/<deployment>/`（默认 `demo`）：
```
改为：
```markdown
查 `$PLATFORMS_ROOT/<deployment>/`（PLATFORMS_ROOT 解析见 orchestration.md「步骤 0」；默认 `demo`）：
```

- [ ] **Step 3: 改 L59 执行段示例路径**

把 L59（执行示例注释）：
```bash
# 例：scripts/run.sh --spec platforms/<deployment>/<system>.yaml <resource> <verb> --print-curl
```
改为：
```bash
# 例：scripts/run.sh --spec $PLATFORMS_ROOT/<deployment>/<system>.yaml <resource> <verb> --print-curl
#     （PLATFORMS_ROOT 见 orchestration.md「步骤 0」；run.sh 已 export API_CLI_PLATFORMS_DIR）
```

- [ ] **Step 4: 写保护纪律加「部署根明确化」（spec §6.1）**

把 L86-89 写保护纪律段，在现有三条 bullet 后加一条。把：
```markdown
**写保护纪律**：
- **orchestration 模式下 platforms/ 只读**：禁止 Write/Edit platforms 任何文件、禁止跑 onboarding 流程。只读 systems/objects/entities/flows 做编排，写只发生在远端系统 API（且写操作必确认）。
- **onboarding 模式才写 platforms**：且必须 ① 过输入门禁（契约/文档/源码 ≥1）、② 改完跑 lint（0 ERR）。详见 `references/onboarding.md`。
- **分发加固**：`pack-go.sh --skill <name> --target <os/arch> --dist` 读 manifest 编译到 bin/ + 打 tar.gz → 随 skill 分发。零 setup——Go 预编译二进制随包走，不需要安装 runtime。onboarding 改 platforms 前先 `chmod -R u+w`，改完锁回。
```
改为（加第 4 条 bullet）：
```markdown
**写保护纪律**：
- **orchestration 模式下 platforms/ 只读**：禁止 Write/Edit platforms 任何文件、禁止跑 onboarding 流程。只读 systems/objects/entities/flows 做编排，写只发生在远端系统 API（且写操作必确认）。
- **onboarding 模式才写 platforms**：且必须 ① 过输入门禁（契约/文档/源码 ≥1）、② 改完跑 lint（0 ERR）。详见 `references/onboarding.md`。
- **部署根位置明确化**：onboarding 写 platforms 前，先 echo 确认 `API_CLI_PLATFORMS_DIR` 解析到的**绝对路径**；部署根不存在则**停下打印路径问用户**（见 onboarding.md「首写门禁」），禁止隐式 mkdir 到意外 cwd。
- **分发加固**：`pack-go.sh --skill <name> --target <os/arch> --dist` 读 manifest 编译到 bin/ + 打 tar.gz → 随 skill 分发。零 setup——Go 预编译二进制随包走，不需要安装 runtime。onboarding 改 platforms 前先 `chmod -R u+w`，改完锁回。
```

- [ ] **Step 5: 状态持久化纪律升级为目录隔离（spec §6.2）**

把 L95 状态持久化纪律 bullet：
```markdown
- **状态持久化（tmp 落点纪律）**：复杂编排的中间产物跨 bash 步传递时——① **优先不落盘**：body 用进程替换喂 `--body-file <(printf '%s' '<json>')`，能用内联/stdin 就不写文件；② **必须落盘时**用绝对路径锚定**调用方 cwd**（`$PWD/.api-orchestrator/tmp/<task>/` 或 `mktemp -d`），**严禁写 skill 目录**——勿 `cd` 进 skill 再用相对 `tmp/`，那会把运行时垃圾写进分发物，且顶层 `.gitignore` 的 `tmp/` 会让 git 静默、污染隐形。
```
改为（加部署根内目录隔离约束）：
```markdown
- **状态持久化（tmp 落点纪律）**：复杂编排的中间产物跨 bash 步传递时——① **优先不落盘**：body 用进程替换喂 `--body-file <(printf '%s' '<json>')`，能用内联/stdin 就不写文件；② **必须落盘时**用绝对路径锚定**调用方 cwd**（`$PWD/.api-orchestrator/tmp/<task>/` 或 `mktemp -d`），**严禁写 skill 目录**——勿 `cd` 进 skill 再用相对 `tmp/`，那会把运行时垃圾写进分发物，且顶层 `.gitignore` 的 `tmp/` 会让 git 静默、污染隐形。
- **部署根内目录隔离**：`$PWD/.api-orchestrator/` 下只允许 4 类内容——`platforms/`（领域知识）、`auth.d/`（密钥）、`env.d/`（非密配置）、`tmp/`（编排中间产物）。tmp 与前三者同级，禁止交叉写入（如把密钥写进 platforms、或把 tmp 产物写进 auth.d）。
```

- [ ] **Step 6: 验收——grep 确认 SKILL.md 物理路径已改、新纪律在位**

Run:
```bash
echo "=== 应只剩概念位置 L13（不改）==="
grep -n "platforms/<deployment>\|platforms/demo" /workspace/.claude/skills/api-orchestrator/SKILL.md
echo "=== 新内容应在 ==="
grep -n "部署根（platforms/auth/env 归一）\|部署根位置明确化\|部署根内目录隔离" /workspace/.claude/skills/api-orchestrator/SKILL.md
```
Expected: 第一组命中**只剩 L13**（概念位置「只活在 `platforms/<deployment>/` 实例里」——不改）；L45/L59 的物理路径已变为 `$PLATFORMS_ROOT`。第二组命中 3 条新 bullet。

- [ ] **Step 7: 提交**

```bash
cd /workspace
git add .claude/skills/api-orchestrator/SKILL.md
git commit -m "docs(api-orchestrator): SKILL.md 部署根说明 + 物理路径 + 写保护/隔离纪律

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 验收（R1 grep + R2 smoke + 联动）

**Files:**
- 无文件改动；纯验收（spec §9 R1/R2 + §10 全部验收标准）

**Interfaces:**
- Consumes: Task 1-5 的全部产出
- Produces: 验收通过的证据（grep 输出 + smoke 200 + lint/run.sh 联动确认）

- [ ] **Step 1: R1 文字残留验收（硬验收，spec §9 R1）**

Run:
```bash
cd /workspace/.claude/skills/api-orchestrator
echo "=== 全仓 grep platforms/demo（应只剩 fallback 语义 / 概念位置）==="
grep -rn "platforms/demo" SKILL.md references/ scripts/
echo "=== 逐条核对每条命中是否「允许的例外」==="
```
Expected: 每条命中必须归类为以下之一（人工核对）：
- **概念位置**（asset-schema.md L3、SKILL.md L13）——允许
- **fallback 语义**（如 orchestration.md 步 0 解析链里的 `skill 内置 platforms/<dep>/`、README.md 资料地图描述）——允许
- **测试 fixture**（lint-platforms.test.py 里的 demo/test-good/test-bad 是 fixture 名，非物理路径）——允许

任何「直接物理读取 `platforms/demo/xxx` 调用」残留 = **不合格，回对应 task 修**。

- [ ] **Step 2: R2 smoke——cookie 从新部署根加载且 200（硬验收，spec §9 R2）**

> 前置：需要有效的 easyops cookie（当前 `~/.api-cli/auth.d/easyops-cookie.yaml`，若有）。若本环境无 cookie，此 step 标记为「需在有 cookie 的环境补测」，记录到 task 备注。

Run:
```bash
# 1. 建部署根 + 迁 cookie
mkdir -p /tmp/smoke-root/{platforms,auth.d,env.d}
# 复制现有 cookie 到新 auth.d（若有）
cp ~/.api-cli/auth.d/easyops-cookie.yaml /tmp/smoke-root/auth.d/ 2>/dev/null || echo "(本环境无 cookie，标记待补测)"
# 写最小 env.d
cat > /tmp/smoke-root/env.d/demo.env <<'EOF'
export EASYOPS_ORG=18832008
export EASYOPS_USER=easyops
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
EOF

# 2. 指向新部署根跑 smoke（API_CLI_DEPLOYMENT_ROOT 覆盖）
cd /tmp/smoke-root
API_CLI_DEPLOYMENT_ROOT=/tmp/smoke-root \
  /workspace/.claude/skills/api-orchestrator/scripts/run.sh \
  --spec platforms/demo/easyops-cmdb.yaml object_instance search HOST \
  --body '{"fields":["instanceId"],"page":1,"page_size":1}' \
  --print-curl --reveal-auth 2>&1 | head -20
```
Expected: curl 输出含 `Cookie:` 头（非 `<redacted>`，因 `--reveal-auth`）+ 实际调用返回 200（exit 0）。

> 若 `--print-curl` 只输出 curl 不真调，去掉 `--print-curl` 真调一次确认 200。

- [ ] **Step 3: lint 联动验收（spec §10 验收 3）**

Run:
```bash
cd /tmp  # 无部署根
unset API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
echo "=== 无部署根 → fallback skill 内置 demo（应 exit 0）==="
python3 /workspace/.claude/skills/api-orchestrator/scripts/lint-platforms.py demo >/dev/null 2>&1; echo "exit=$?"

echo "=== 有部署根 → 校验部署根（用 Task2 测试的 ext-platforms）==="
export API_CLI_PLATFORMS_DIR=/tmp  # 指向一个有 platforms/ 子目录的根
python3 /workspace/.claude/skills/api-orchestrator/scripts/lint-platforms.py nonexist 2>&1 | tail -2
```
Expected: 第一条 `exit=0`（fallback demo）；第二条指向 `$API_CLI_PLATFORMS_DIR/nonexist`（按 env 走）。

- [ ] **Step 4: run.sh 联动验收（spec §10 验收 4）**

Run:
```bash
cd /tmp && unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR
# 提取 run.sh 解析段验证四变量派生（不 exec）
bash -c '
  _APIORCH_ROOT="${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
  : "${API_CLI_AUTH_D:=$_APIORCH_ROOT/auth.d}"
  : "${API_CLI_ENV_FILE:=$_APIORCH_ROOT/env.d/${API_CLI_DEPLOYMENT:-demo}.env}"
  : "${API_CLI_PLATFORMS_DIR:=$_APIORCH_ROOT/platforms}"
  echo "AUTH_D=$API_CLI_AUTH_D"
  echo "ENV_FILE=$API_CLI_ENV_FILE"
  echo "PLATFORMS_DIR=$API_CLI_PLATFORMS_DIR"
  echo "ROOT=${API_CLI_DEPLOYMENT_ROOT:-$PWD/.api-orchestrator}"
'
```
Expected: 四变量都派生自 `$PWD/.api-orchestrator`（即 `/tmp/.api-orchestrator/...`）。

- [ ] **Step 5: 零行为回归验收（spec §10 验收 5）**

Run:
```bash
cd /tmp && unset API_CLI_DEPLOYMENT_ROOT API_CLI_AUTH_D API_CLI_ENV_FILE API_CLI_PLATFORMS_DIR
# 无部署根时，echo 步0 应 fallback 到 skill 内置 demo（目录存在）
SKILL_DEMO=/workspace/.claude/skills/api-orchestrator/platforms/demo
[ -d "$SKILL_DEMO" ] && echo "✓ skill 内置 demo 仍在（fallback 可用）" || echo "✗ demo 被误删！"
ls "$SKILL_DEMO" | head -5
```
Expected: skill 内置 `platforms/demo/` 仍在（README.md/systems.yaml/objects.yaml 等），fallback 路径可用。

- [ ] **Step 6: 全部通过 → 提交验收记录（如有改动）或收尾**

若 Step 1-5 全通过，无文件改动则无需 commit（验收是只读的）。若有修复，commit 修复。

Run（记录验收通过）:
```bash
echo "✅ 验收全部通过：R1 grep / R2 smoke / lint联动 / run.sh联动 / 零回归"
git log --oneline -6  # 确认 5 个 task 的 commit 都在
```

---

## Self-Review（写计划后自查）

**1. Spec coverage:**
- §3.1 部署根结构 → Task 4 Step 2 目录树 ✓
- §3.2 解析链 → Task 1（run.sh）+ Task 2（lint）✓
- §3.3 run.sh 解析段 → Task 1 ✓
- §4.1 步 0 → Task 3 Step 1 ✓
- §4.2 物理路径触点 → Task 3/4/5 ✓
- §4.3 lint resolve_base → Task 2 ✓
- §5.1 首写门禁 → Task 4 Step 3 ✓
- §5.2 onboarding 改动 → Task 4 ✓
- §6.1 写保护纪律补 → Task 5 Step 4 ✓
- §6.2 状态持久化升级 → Task 5 Step 5 ✓
- §6.3 $PWD 说明 → Task 5 Step 1 ✓
- §7 零迁移 → Task 6 Step 5 验证 demo 仍在 ✓
- §9 R1/R2/R3/R4 → Task 6（R1 Step1/R2 Step2/R3 在 Task5Step1 文档/R4 决策记录在 spec）✓
- §10 验收 1-5 → Task 6 Step 1-5 ✓
- 无遗漏。

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 都有完整代码块；每个 Edit 都有精确 old_string/new_string。

**3. Type consistency:** 变量名 `API_CLI_PLATFORMS_DIR`/`API_CLI_DEPLOYMENT_ROOT`/`API_CLI_AUTH_D`/`API_CLI_ENV_FILE`/`PLATFORMS_ROOT` 在所有 task 一致；`resolve_base(deployment, override=None)` 签名在 Task 2 Step 3 定义、Step 1 测试调用一致。
