# 杜绝 LLM 猜环境拼凑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 杜绝 LLM 在环境未初始化时读旧位置（`~/.api-cli/`）+ 读 systems.yaml env 段默认值 + 自行 export 凑数；环境初始化成编排强制前置，platforms 数据去环境性配置（IP/org/URL 值）但留事实知识（端口），lint 把纪律变成可执行闸。

**Architecture:** 三类信息分流：事实（端口/host/服务名）留 systems.yaml `runtime.ports`；环境配置（IP/org/user/完整 URL）只在部署根 env.d，systems.yaml 的 `env:`/`env_required:` 段去值留 key；变量契约（key+用途）留 systems.yaml。决策树加步 0 环境就绪门禁（三项全查+显式禁降级行为）。lint 加 2 规则（禁 `~/.api-cli/` 字面串、env 段值禁非空 URL/IP）防回潮。

**Tech Stack:** YAML（platforms 数据）、Python3（lint + test）、Markdown（SKILL.md）。

**设计 spec:** `docs/superpowers/specs/2026-08-12-env-init-discipline-design.md`

> **范围说明（spec undercount 修正）**：spec §5 说"5 处 ~/.api-cli"，实测全量 grep 是 **7 处**；spec §3 只提 `env:` map 段，实测还有 **`env_required:` list 段**（4 系统 × 含 URL+ORG 值）也是同类硬编码问题。本 plan 覆盖真实全量（env 段 + env_required 段 + spec base_url 注释 + org/user 注释），不只 spec 列的 10 项。

## Global Constraints

- **信息分类**：A 事实（端口/host/服务名）留 systems.yaml；B 环境配置（IP/org/user/URL）只在部署根 env.d，systems.yaml 不留值；C 变量契约（key+用途）留 systems.yaml env 段。
- **env: 段（map 形式）**：值全置空字符串 `""`，注释指向 env.d + 端口指向 runtime.ports。
- **env_required: 段（list 形式）**：值同样去——改为只列变量名 + 用途注释，不带 `=值`。如 `- "EASYOPS_CMDB_BACKEND_URL"  # 完整 URL（含 IP+端口），值见 env.d`。
- **org/user 注释**：spec 文件里 `测试用 18832008` 等具体值去除，改为 `值在部署根 env.d`。
- **spec base_url 注释**：`# http://172.30.0.232:8079` 去具体 URL，改为 `# 值在部署根 env.d（含 IP+端口）；端口见 systems.yaml runtime.ports`。
- **`~/.api-cli/` 字面字符串**：platforms 数据完全禁（lint 规则①）；提旧位置改「原 home 目录位置已废弃」措辞。
- **lint 规则②**：env 段值禁非空 URL/IP（正则匹配 `http://` 或 `\d+\.\d+\.\d+\.\d+` 即 ERR）。
- **决策树步 0**：三项全查（platforms 可达含 fallback / env.d 存在 / auth.d 有密钥），任缺即停；显式禁 3 种降级行为。
- **向后兼容**：不加（开发阶段，与解耦设计一致）。
- **每 task 改完即 commit**。
- **tmp 落点**：验证脚本写 mktemp -d，严禁写 skill 目录。

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `platforms/demo/systems.yaml` | env: + env_required: 段去值；auth 注释 3 处去 ~/.api-cli | 改（数据） |
| `platforms/demo/easyops-cmdb.yaml` | base_url 注释去 IP；org/user 注释去值；auth 注释去 ~/.api-cli | 改（数据） |
| `platforms/demo/easyops-autoops.yaml` | 同构 | 改（数据） |
| `platforms/demo/easyops-itsm.yaml` | base_url/org/user 注释去值 | 改（数据） |
| `platforms/demo/easyops-sys-setting.yaml` | 同构 | 改（数据） |
| `platforms/demo/README.md` | L32 鉴权位置说明改部署根 | 改（数据） |
| `SKILL.md` | 决策树加步 0 + 禁降级行为 | 改（文档） |
| `scripts/lint-platforms.py` | 加规则①（禁 ~/.api-cli）+ 规则②（env 值禁非空） | 改（代码） |
| `scripts/lint-platforms.test.py` | 加 2 bad fixture | 改（代码） |

---

## Task 1: lint 加 2 条规则 + 测试（先做闸，后续 task 用它验收）

**Files:**
- Modify: `/workspace/skills/api-orchestrator/scripts/lint-platforms.py`（在 section 6 flows 之后加 section 7、8）
- Modify: `/workspace/skills/api-orchestrator/scripts/lint-platforms.test.py`（加 2 bad fixture）

**Interfaces:**
- Consumes: 现有 lint 的 `base`（部署目录路径）、`err()/warn()/ok()` helper、YAML 加载
- Produces: 2 条新校验规则，被后续 Task 2-6 的 grep 验收替代为 lint 验收

**为什么先做：** lint 是闸，先建好，后续 platforms 数据改写时每个 task 都能跑 lint 自检，比 grep 更可靠（grep 会漏 YAML 结构化字段）。

- [ ] **Step 1: 写失败测试——加 2 bad fixture 到 lint-platforms.test.py**

在 `lint-platforms.test.py` 的 `# ============ resolve_base 解析链 case` **之前**（即原 `# ============ bad fixtures` 块之后、resolve_base 块之前）插入 2 个新 bad fixture。先读取该位置确认锚点：

```bash
grep -n "resolve_base 解析链\|bad fixtures" /workspace/skills/api-orchestrator/scripts/lint-platforms.test.py
```

在 `# ============ resolve_base 解析链 case` 那行**之前**插入：

```python
        # ============ 规则①②：禁 ~/.api-cli 字面串 + env 段值禁非空 URL/IP ============
        s1 = os.path.join(base, "test-stale-path")
        write(os.path.join(s1, "README.md"), "# x\n")
        write(os.path.join(s1, "systems.yaml"), """
            deployment: test-stale-path
            systems:
              sys:
                description: ok
                spec: sys.yaml
                auth: easyops-cookie     # 原 ~/.api-cli/auth.d/ 位置（应禁字面串）
        """)
        write(os.path.join(s1, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(s1, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        rc, out = run(base, "test-stale-path")
        if rc == 0:
            fails.append(f"[stale-path] 期望 exit 1（含 ~/.api-cli 字面串），实际 {rc}\n{out}")
        elif "~/.api-cli" not in out:
            fails.append(f"[stale-path] 期望输出含「~/.api-cli」ERR\n{out}")

        s2 = os.path.join(base, "test-env-value")
        write(os.path.join(s2, "README.md"), "# x\n")
        write(os.path.join(s2, "systems.yaml"), """
            deployment: test-env-value
            systems:
              sys:
                description: ok
                spec: sys.yaml
                env:
                  EASYOPS_X_BACKEND_URL: "http://172.30.0.232:8079"   # 非空 URL（应禁）
        """)
        write(os.path.join(s2, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(s2, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        rc, out = run(base, "test-env-value")
        if rc == 0:
            fails.append(f"[env-value] 期望 exit 1（env 段含非空 URL），实际 {rc}\n{out}")
        elif "EASYOPS_X_BACKEND_URL" not in out:
            fails.append(f"[env-value] 期望输出含「EASYOPS_X_BACKEND_URL」ERR\n{out}")

```

- [ ] **Step 2: 跑测试，确认 FAIL（规则还没实现，fixture 不报错→exit 0→fails 触发）**

Run: `cd /workspace/skills/api-orchestrator && python3 scripts/lint-platforms.test.py`
Expected: FAIL，`[stale-path] 期望 exit 1` 和 `[env-value] 期望 exit 1` 两条 fail（因为新规则还没加，这些 bad fixture 没被拦）。

- [ ] **Step 3: 实现 2 条 lint 规则（lint-platforms.py）**

先读 section 6 结尾位置找锚点：

```bash
grep -n "# ---- 6\.\|# ---- 7\.\|return" /workspace/skills/api-orchestrator/scripts/lint-platforms.py | head
```

在 `# ---- 6. flows/*.yaml ...` 段**之后**、main 函数 `return` 之前（或现有最后一段校验之后）插入 section 7+8。先读 main 末尾确认 return 位置（约 L200+）。

把 lint-platforms.py main 函数末尾（`# ---- 报告 ----` 之前）插入：

```python
    # ---- 7. 规则①：platforms 数据禁 ~/.api-cli/ 字面串（干净切换，防回潮）----
    import re as _re
    _STALE = "~/.api-cli/"
    for root, dirs, files in os.walk(base):
        # 跳过 __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if not (fn.endswith(".yaml") or fn.endswith(".yml") or fn.endswith(".md")):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            if _STALE in content:
                rel = os.path.relpath(fp, base)
                err(f"{rel}: 含「{_STALE}」字面串（已废弃旧位置）—— 改「原 home 目录位置已废弃」措辞，密钥/env 统一走部署根")

    # ---- 8. 规则②：systems.yaml 的 env: 段值禁非空 URL/IP（防 LLM 复用默认值）----
    _URL_OR_IP = _re.compile(r"(https?://|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    if os.path.isfile(sys_path):
        d2, e2 = load_yaml(sys_path)
        if d2 and isinstance(d2.get("systems"), dict):
            for sname, s in d2["systems"].items():
                if not isinstance(s, dict):
                    continue
                env = s.get("env")
                if isinstance(env, dict):
                    for k, v in env.items():
                        if isinstance(v, str) and v and _URL_OR_IP.search(v):
                            err(f"systems.{sname}.env.{k}: 值「{v}」含 URL/IP（环境配置只在部署根 env.d，systems.yaml 只留变量契约 key）")

```

> 注：`sys_path` 是 systems.yaml 路径，在 section 2 已定义（`sys_path = os.path.join(base, "systems.yaml")`）。若变量名不同，先 grep 确认：`grep -n "sys_path\|systems.yaml" /workspace/skills/api-orchestrator/scripts/lint-platforms.py | head`。

- [ ] **Step 4: 跑测试，确认 PASS（2 新 bad fixture 被抓 + 原 good/bad/resolve_base 不回归）**

Run: `cd /workspace/skills/api-orchestrator && python3 scripts/lint-platforms.test.py`
Expected: `✓ lint 自测通过...`（无 fail）。

- [ ] **Step 5: 验证现有 demo 数据会触发新规则（确认闸有效，后续 task 要修）**

Run: `cd /tmp && unset API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT && python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo 2>&1 | grep -E "\.api-cli|env\.|ERR" | head`
Expected: 输出多条 ERR（demo 的 README/easyops-cmdb/easyops-autoops/systems.yaml 含 ~/.api-cli，systems.yaml env 段含 URL）—— 证明闸生效，**这正是后续 task 要修的**。

- [ ] **Step 5b: 实测确认 demo 现在会 lint 失败（基线记录）**

Run:
```bash
cd /tmp && python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo >/dev/null 2>&1; echo "demo lint exit=$?"
```
Expected: `exit=1`（有 ERR）。记下这个基线——后续 task 修完数据后应回到 `exit=0`。

- [ ] **Step 6: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/scripts/lint-platforms.py skills/api-orchestrator/scripts/lint-platforms.test.py
git commit -m "feat(api-orchestrator): lint 加规则①禁 ~/.api-cli 字面串 + 规则②env 值禁非空 URL/IP

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: systems.yaml env:/env_required: 段去值 + auth 注释去 ~/.api-cli

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/systems.yaml`

**Interfaces:**
- Consumes: Task 1 的 lint 规则（改完跑 lint 自检）
- Produces: systems.yaml env 段为变量契约（值空），env_required 段只列变量名

**范围**：4 个系统（cmdb/autoops/itsm/sys-setting）的 env: map 段 + env_required: list 段 + 3 处 auth 注释。

- [ ] **Step 1: cmdb 的 env: 段（L71-74）去值留 key**

把 systems.yaml cmdb 段（`  easyops-cmdb:` 下）的：
```yaml
    env:                                 # 部署所需环境变量（供 api-cli / shell 注入）
      EASYOPS_CMDB_BACKEND_URL: "http://172.30.0.232:8079"  # cmdb_service 后端（实测）
      EASYOPS_CMDB_FRONTEND_URL: "https://172.30.0.232"      # 前端页面/网关
      EASYOPS_USER_SERVICE_URL: "http://172.30.0.232:8111"      # user_service（org 查询等）
```
改为：
```yaml
    env:                                 # 环境变量契约（仅声明需要哪些变量 + 用途；【值在部署根 env.d/<dep>.env，勿从此处取】）
      EASYOPS_CMDB_BACKEND_URL: ""       # cmdb_service 后端完整 URL（含 IP+端口）；端口事实见 runtime.ports.cmdb_backend
      EASYOPS_CMDB_FRONTEND_URL: ""      # 前端页面/网关完整 URL
      EASYOPS_USER_SERVICE_URL: ""       # user_service（org 查询）完整 URL；端口见 runtime.ports.user_service
```

- [ ] **Step 2: cmdb 的 auth 注释（L69）去 ~/.api-cli**

把：
```yaml
    auth: easyops-cookie                 # ~/.api-cli/auth.d/easyops-cookie.yaml：provider=cookie，持 PHPSESSID
```
改为：
```yaml
    auth: easyops-cookie                 # 部署根 auth.d/easyops-cookie.yaml（API_CLI_AUTH_D 指向；原 home 目录位置已废弃）：provider=cookie，持 PHPSESSID
```

- [ ] **Step 3: cmdb 的 env_required: 段（L148-150）去值**

把：
```yaml
      env_required:                    # 调用前 export
        - "EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079"
        - "EASYOPS_ORG=18832008"       # 测试 org（0/1/2 禁动）
        - "EASYOPS_USER=easyops"
```
改为：
```yaml
      env_required:                    # 调用前 export（仅列变量名；值在部署根 env.d/<dep>.env）
        - "EASYOPS_CMDB_BACKEND_URL"   # 完整 URL（含 IP+端口）；端口事实见本 system runtime.ports.cmdb_backend
        - "EASYOPS_ORG"                # EasyOps 租户 org（系统自带 0/1/2 禁动）
        - "EASYOPS_USER"               # 用户标识（模型系统管理员=easyops）
```

> 注：`- "EASYOPS_USER=easyops"` 这行原值是 `easyops`，是稳定事实（管理员用户名）还是环境配置？——属环境配置（不同部署用户名可能不同），故去值留 key。注释保留"管理员=easyops"作事实提示。

- [ ] **Step 4: autoops 的 env:/env_required:/auth（L222-224, L253-255, L220）同构改写**

autoops env: 段（L222-224）：
```yaml
    env:                                 # 部署所需环境变量（ORG/USER 复用 cmdb 那套）
      EASYOPS_AUTOOPS_BACKEND_URL: "http://172.30.0.232:8181"   # tool_service 后端（实测）
      EASYOPS_AUTOOPS_FRONTEND_URL: "https://172.30.0.232"      # 前端页面/网关
```
改为：
```yaml
    env:                                 # 环境变量契约（值在部署根 env.d/<dep>.env，勿从此处取）
      EASYOPS_AUTOOPS_BACKEND_URL: ""   # tool_service 后端完整 URL；端口见 runtime.ports.autoops_backend
      EASYOPS_AUTOOPS_FRONTEND_URL: ""  # 前端页面/网关完整 URL
```

autoops env_required: 段（L253-255）：
```yaml
      env_required:                    # 调用前 export
        - "EASYOPS_AUTOOPS_BACKEND_URL=http://172.30.0.232:8181"
        - "EASYOPS_ORG=18832008"       # 测试 org（0/1/2 禁动，与 cmdb 共用）
        - "EASYOPS_USER=easyops"
```
改为：
```yaml
      env_required:                    # 调用前 export（值在部署根 env.d/<dep>.env）
        - "EASYOPS_AUTOOPS_BACKEND_URL"   # 完整 URL；端口见 runtime.ports.autoops_backend
        - "EASYOPS_ORG"                   # 与 cmdb 共用
        - "EASYOPS_USER"                  # 与 cmdb 共用
```

autoops auth 注释（L220）：
```yaml
    auth: easyops-cookie                    # 与 cmdb 同一 cookie（~/.api-cli/auth.d/easyops-cookie.yaml：PHPSESSID）
```
改为：
```yaml
    auth: easyops-cookie                    # 与 cmdb 同一 cookie（部署根 auth.d/easyops-cookie.yaml，API_CLI_AUTH_D；原 home 目录位置已废弃）
```

- [ ] **Step 5: itsm 的 env:/env_required:/auth（L307-308, L394-396, L304）同构改写**

itsm env: 段（L307-308）：
```yaml
    env:                                     # 部署所需环境变量（ORG/USER 复用 cmdb 那套）
      EASYOPS_ITSM_BACKEND_URL: "http://172.30.0.232:8134"   # flowable_service 后端（实测）
      EASYOPS_CMDB_FRONTEND_URL: "https://172.30.0.232"      # 前端页面（表单列表/详情）
```
改为：
```yaml
    env:                                     # 环境变量契约（值在部署根 env.d/<dep>.env，勿从此处取）
      EASYOPS_ITSM_BACKEND_URL: ""          # flowable_service 后端完整 URL；端口见 runtime.ports.itsm_backend
      EASYOPS_CMDB_FRONTEND_URL: ""         # 前端页面（表单列表/详情）完整 URL
```

itsm env_required: 段（L394-396）：
```yaml
      env_required:                    # 调用前 export
        - "EASYOPS_ITSM_BACKEND_URL=http://172.30.0.232:8134"
        - "EASYOPS_ORG=18832008"       # 测试 org（0/1/2 禁动，与 cmdb 共用）
        - "EASYOPS_USER=easyops"
```
改为：
```yaml
      env_required:                    # 调用前 export（值在部署根 env.d/<dep>.env）
        - "EASYOPS_ITSM_BACKEND_URL"   # 完整 URL；端口见 runtime.ports.itsm_backend
        - "EASYOPS_ORG"                # 与 cmdb 共用
        - "EASYOPS_USER"               # 与 cmdb 共用
```

itsm auth 注释（L304）：
```yaml
    auth: easyops-cookie                     # 与 cmdb/autoops 同一 cookie（~/.api-cli/auth.d/easyops-cookie.yaml：PHPSESSID）
```
改为：
```yaml
    auth: easyops-cookie                     # 与 cmdb/autoops 同一 cookie（部署根 auth.d/easyops-cookie.yaml，API_CLI_AUTH_D；原 home 目录位置已废弃）
```

- [ ] **Step 6: sys-setting 的 env:/env_required:（L466-468, L480-482）同构改写**

sys-setting env: 段（L466-468）：
```yaml
    env:                                    # 部署所需环境变量（ORG/USER 复用 itsm 那套）
      EASYOPS_SYS_SETTING_BACKEND_URL: "http://172.30.0.232:8271"   # sys_setting 后端（实测 200）
      EASYOPS_CMDB_FRONTEND_URL: "https://172.30.0.232"             # 前端页面（工作日历列表/详情）
```
改为：
```yaml
    env:                                    # 环境变量契约（值在部署根 env.d/<dep>.env，勿从此处取）
      EASYOPS_SYS_SETTING_BACKEND_URL: ""  # sys_setting 后端完整 URL；端口见 runtime.ports.sys_setting_backend
      EASYOPS_CMDB_FRONTEND_URL: ""        # 前端页面完整 URL
```

sys-setting env_required: 段（L480-482）：
```yaml
      env_required:
        - "EASYOPS_SYS_SETTING_BACKEND_URL=http://172.30.0.232:8271"
        - "EASYOPS_ORG=18832008"
        - "EASYOPS_USER=easyops"
```
改为：
```yaml
      env_required:                    # 调用前 export（值在部署根 env.d/<dep>.env）
        - "EASYOPS_SYS_SETTING_BACKEND_URL"   # 完整 URL；端口见 runtime.ports.sys_setting_backend
        - "EASYOPS_ORG"                       # 与 itsm 共用
        - "EASYOPS_USER"                      # 与 itsm 共用
```

- [ ] **Step 7: 跑 lint 验收 systems.yaml（规则② env 值应过；规则① ~/.api-cli 应过）**

Run:
```bash
cd /tmp && unset API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo 2>&1 | grep -E "systems\.yaml|env\." | head
```
Expected: systems.yaml 相关的 ERR 应**消失**（env 段已去值、auth 注释已去 ~/.api-cli）。剩余 ERR 应来自其它文件（easyops-cmdb.yaml 等，Task 3 修）。

- [ ] **Step 8: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/platforms/demo/systems.yaml
git commit -m "fix(api-orchestrator): systems.yaml env/env_required 段去值留 key + auth 注释去 ~/.api-cli

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: easyops-cmdb.yaml base_url/org/user 注释去值 + auth 注释去 ~/.api-cli

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/easyops-cmdb.yaml`

**Interfaces:**
- Consumes: Task 1 lint 规则
- Produces: cmdb spec 文件 ~/.api-cli 清零、base_url/org/user 注释无具体值

- [ ] **Step 1: base_url 注释去 IP（L39, L47）**

L39：
```yaml
      base_url: ${EASYOPS_CMDB_BACKEND_URL}        # http://172.30.0.232:8079
```
改为：
```yaml
      base_url: ${EASYOPS_CMDB_BACKEND_URL}        # 值在部署根 env.d/demo.env（含 IP+端口）；端口事实见 systems.yaml runtime.ports.cmdb_backend
```

L47：
```yaml
      base_url: ${EASYOPS_CMDB_FRONTEND_URL}        # https://172.30.0.90
```
改为：
```yaml
      base_url: ${EASYOPS_CMDB_FRONTEND_URL}        # 值在部署根 env.d/demo.env（前端页面/网关完整 URL）
```

- [ ] **Step 2: org/user header 注释去具体值（L44-45）**

```yaml
        org: ${EASYOPS_ORG}                         # EasyOps 租户 org。系统自带 0/1/2 禁动（业务库）；测试用 18832008。export EASYOPS_ORG=<值>
        user: ${EASYOPS_USER}                       # EasyOps 用户标识。模型系统管理员=easyops（有 ObjectImport 权限）。export EASYOPS_USER=easyops
```
改为：
```yaml
        org: ${EASYOPS_ORG}                         # EasyOps 租户 org（系统自带 0/1/2 禁动）；值在部署根 env.d/demo.env
        user: ${EASYOPS_USER}                       # EasyOps 用户标识（模型系统管理员=easyops 有 ObjectImport 权限）；值在部署根 env.d/demo.env
```

- [ ] **Step 3: 鉴权注释去 ~/.api-cli（L24）**

```yaml
# 鉴权：auth: easyops-cookie（~/.api-cli/auth.d/easyops-cookie.yaml，provider=cookie，
```
改为：
```yaml
# 鉴权：auth: easyops-cookie（部署根 auth.d/easyops-cookie.yaml，API_CLI_AUTH_D 指向；原 home 目录位置已废弃；provider=cookie，
```

- [ ] **Step 4: openapi auth 注释去 ~/.api-cli（L54）**

```yaml
      auth: easyops-openapi                          # ~/.api-cli/auth.d/easyops-openapi.yaml（host=openapi.easyops-only.com 作签名 Host 头，网关按 Host 路由）
```
改为：
```yaml
      auth: easyops-openapi                          # 部署根 auth.d/easyops-openapi.yaml（API_CLI_AUTH_D；原 home 目录位置已废弃；host=openapi.easyops-only.com 作签名 Host 头，网关按 Host 路由）
```

- [ ] **Step 5: 跑 lint 验收 easyops-cmdb.yaml 的 ~/.api-cli 清零**

Run:
```bash
cd /tmp && python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo 2>&1 | grep "easyops-cmdb" | head
```
Expected: 无 easyops-cmdb.yaml 相关 ERR。

- [ ] **Step 6: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/platforms/demo/easyops-cmdb.yaml
git commit -m "fix(api-orchestrator): easyops-cmdb.yaml base_url/org/user 注释去值 + auth 去 ~/.api-cli

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: easyops-autoops.yaml 同构改写

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/easyops-autoops.yaml`

**Interfaces:** Task 1 lint 规则

- [ ] **Step 1: 读 autoops spec 当前 base_url/org/user/auth 注释行**

Run:
```bash
grep -n "base_url\|org: \${\|user: \${\|auth: easyops-cookie\|~/.api-cli" /workspace/skills/api-orchestrator/platforms/demo/easyops-autoops.yaml | head
```

- [ ] **Step 2: base_url 注释去 IP（L55, L63）**

L55：
```yaml
      base_url: ${EASYOPS_AUTOOPS_BACKEND_URL}        # http://172.30.0.232:8181
```
改为：
```yaml
      base_url: ${EASYOPS_AUTOOPS_BACKEND_URL}        # 值在部署根 env.d/demo.env（含 IP+端口）；端口事实见 systems.yaml runtime.ports.autoops_backend
```

L63：
```yaml
      base_url: ${EASYOPS_AUTOOPS_FRONTEND_URL}        # https://172.30.0.232（前端网关）
```
改为：
```yaml
      base_url: ${EASYOPS_AUTOOPS_FRONTEND_URL}        # 值在部署根 env.d/demo.env（前端网关完整 URL）
```

- [ ] **Step 3: org/user header 注释去值（L60-61）**

```yaml
        org: ${EASYOPS_ORG}                            # EasyOps 租户 org。系统自带 0/1/2 禁动；测试用 18832008。export EASYOPS_ORG=<值>
        user: ${EASYOPS_USER}                          # EasyOps 用户标识。模型系统管理员=easyops。export EASYOPS_USER=easyops
```
改为：
```yaml
        org: ${EASYOPS_ORG}                            # EasyOps 租户 org（系统自带 0/1/2 禁动）；值在部署根 env.d/demo.env
        user: ${EASYOPS_USER}                          # EasyOps 用户标识（模型系统管理员=easyops）；值在部署根 env.d/demo.env
```

- [ ] **Step 4: 鉴权注释去 ~/.api-cli（L30）**

```yaml
# 鉴权：auth: easyops-cookie（~/.api-cli/auth.d/easyops-cookie.yaml，provider=cookie，
```
改为：
```yaml
# 鉴权：auth: easyops-cookie（部署根 auth.d/easyops-cookie.yaml，API_CLI_AUTH_D；原 home 目录位置已废弃；provider=cookie，
```

- [ ] **Step 5: 跑 lint 验收 + 提交**

Run:
```bash
cd /tmp && python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo 2>&1 | grep "easyops-autoops" | head
```
Expected: 无 easyops-autoops.yaml 相关 ERR。

```bash
cd /workspace
git add skills/api-orchestrator/platforms/demo/easyops-autoops.yaml
git commit -m "fix(api-orchestrator): easyops-autoops.yaml base_url/org/user 注释去值 + auth 去 ~/.api-cli

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: easyops-itsm.yaml + easyops-sys-setting.yaml base_url/org 注释去值

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/easyops-itsm.yaml`
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/easyops-sys-setting.yaml`

**Interfaces:** Task 1 lint 规则

> 注：itsm/sys-setting spec 文件**无 ~/.api-cli 引用**（grep 已确认），故只需改 base_url/org 注释去值。但 lint 规则②不扫 spec 文件的 base_url 注释（规则②只扫 systems.yaml 的 env: 段）——spec 注释里的 IP 是**注释**非结构化值，lint 不拦。故这俩文件的注释清理靠人工 + grep 验收（不留 IP 让 LLM 无从拼凑）。

- [ ] **Step 1: itsm base_url 注释去 IP（L49）**

```yaml
      base_url: ${EASYOPS_ITSM_BACKEND_URL}          # http://172.30.0.232:8134
```
改为：
```yaml
      base_url: ${EASYOPS_ITSM_BACKEND_URL}          # 值在部署根 env.d/demo.env（含 IP+端口）；端口事实见 systems.yaml runtime.ports.itsm_backend
```

- [ ] **Step 2: itsm org/user header 注释去值（L54-55）**

读当前：
```bash
sed -n '54,56p' /workspace/skills/api-orchestrator/platforms/demo/easyops-itsm.yaml
```
把含 `测试 18832008` / `export EASYOPS_USER=easyops` 的 org/user 注释改为：
```yaml
        org: ${EASYOPS_ORG}                           # EasyOps 租户 org（系统自带 0/1/2 禁动）；值在部署根 env.d/demo.env
        user: ${EASYOPS_USER}                         # EasyOps 用户标识；值在部署根 env.d/demo.env
```

- [ ] **Step 3: sys-setting base_url 注释去 IP（L37）**

```yaml
      base_url: ${EASYOPS_SYS_SETTING_BACKEND_URL}   # http://172.30.0.232:8271
```
改为：
```yaml
      base_url: ${EASYOPS_SYS_SETTING_BACKEND_URL}   # 值在部署根 env.d/demo.env（含 IP+端口）；端口事实见 systems.yaml runtime.ports.sys_setting_backend
```

- [ ] **Step 4: sys-setting org/user header 注释去值（L42-43）**

读当前：
```bash
sed -n '42,44p' /workspace/skills/api-orchestrator/platforms/demo/easyops-sys-setting.yaml
```
把含 `测试 18832008` 的 org 注释改为：
```yaml
        org: ${EASYOPS_ORG}                           # EasyOps 租户 org（系统自带 0/1/2 禁动）；值在部署根 env.d/demo.env
        user: ${EASYOPS_USER}                         # EasyOps 用户标识；值在部署根 env.d/demo.env
```

- [ ] **Step 5: grep 验收 spec 文件无残留 IP（base_url/org/user 注释）**

Run:
```bash
grep -rn "172\.30\.0\.\|18832008" /workspace/skills/api-orchestrator/platforms/demo/easyops-*.yaml | grep -v "__pycache__"
```
Expected: **0 命中**（所有 spec 文件的 IP/org 值已清）。systems.yaml 里的 `18832008` 可能还在 `test_org:`/`e2e_findings` 等事实记录段（那些是历史记录非运行时值，Task 2 不改，这里 grep 它们无妨——只验 spec 文件）。

- [ ] **Step 6: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/platforms/demo/easyops-itsm.yaml skills/api-orchestrator/platforms/demo/easyops-sys-setting.yaml
git commit -m "fix(api-orchestrator): easyops-itsm/sys-setting.yaml base_url/org 注释去值

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: README.md 鉴权位置说明改部署根

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/demo/README.md`

**Interfaces:** Task 1 lint 规则①（禁 ~/.api-cli 字面串）

- [ ] **Step 1: L32 鉴权位置说明改写**

```markdown
# 鉴权已统一：cookie@~/.api-cli/auth.d/（密钥）+ 非密 env@~/.api-cli/env.d/demo.env（run.sh 自动 source）
```
改为：
```markdown
# 鉴权已统一：cookie@部署根 auth.d/（密钥，API_CLI_AUTH_D 指向）+ 非密 env@部署根 env.d/demo.env（run.sh 自动 source）。部署根默认 $PWD/.api-orchestrator；原 home 目录位置已废弃。
```

- [ ] **Step 2: README 其它段检查有无 ~/.api-cli 残留**

Run:
```bash
grep -n "\.api-cli" /workspace/skills/api-orchestrator/platforms/demo/README.md
```
Expected: 0 命中（若有其它行，同构改写为「部署根」+「原 home 目录位置已废弃」）。

- [ ] **Step 3: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/platforms/demo/README.md
git commit -m "fix(api-orchestrator): README.md 鉴权位置说明改部署根（去 ~/.api-cli）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: SKILL.md 决策树加步 0 环境就绪门禁 + 禁降级行为

**Files:**
- Modify: `/workspace/skills/api-orchestrator/SKILL.md`（决策树段 L23-41 + 步 0 详情）

**Interfaces:** 无（纯文档，但引用 platforms 解耦设计的 env 变量名）

- [ ] **Step 1: 读决策树当前结构确认锚点**

Run:
```bash
sed -n '23,42p' /workspace/skills/api-orchestrator/SKILL.md
```
确认决策树是 ```` ``` ```` 代码块，第一个分支是 `[1] 是"接入新系统/加能力域"吗？`。

- [ ] **Step 2: 决策树代码块最前插入步 0**

在决策树 ```` ``` ```` 代码块内，`需求进来` 之后、`├─[1]` 之前插入：
```
需求进来
│
├─[0] 环境就绪检查（所有编排前置，强制）
│      echo 确认：
│        · platforms 可达：$API_CLI_PLATFORMS_DIR/<dep>/ 存在，或 fallback skill 内置 platforms/<dep>/
│        · env.d：$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env 存在
│        · auth.d：$API_CLI_AUTH_D/ 下有 *.yaml 密钥文件
│      ├─ 三项俱全 → 继续 [1]
│      └─ 缺任一 → 【停下，打印缺失项 + 配置方法，问用户】
│
├─[1] 是"接入新系统/加能力域"吗？
│      ...
```

- [ ] **Step 3: 决策树代码块后加「步 0 禁降级行为」说明段**

在决策树 ```` ``` ```` 代码块**之后**、`## 资料` 段之前插入新小节：

```markdown
### 步 0 详解：环境就绪门禁（防 LLM 猜环境拼凑）

环境未就绪时，**禁止三种降级行为**（实测踩坑）：
- ❌ 读 `systems.yaml` 的 `env:` 段当运行时值用——env: 段是变量契约（值已置空），端口事实在 `runtime.ports`。
- ❌ 用 `~/.api-cli/`（原 home 目录位置）旧位置——已废弃，密钥/env 统一走部署根。
- ❌ 自行 `export EASYOPS_*=默认值` 凑数——IP/org/user 是部署时才知道的环境配置，不能猜。
- ✅ 唯一正确动作：停下，打印缺失项 + 指向 `references/onboarding.md`「初始化部署根」，问用户。

三项语义：
- **platforms 可达**：部署根 `$PLATFORMS_ROOT/<dep>/` 存在用项目级；不存在 fallback skill 内置（合法，不算缺失）。
- **env.d 存在**：`$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env` 必须存在（skill 内置不提供业务变量）。
- **auth.d 有密钥**：`$API_CLI_AUTH_D/` 下有 `*.yaml`（skill 内置不提供密钥）。
```

- [ ] **Step 4: 验收——SKILL.md 步 0 在位、决策树无语法破损**

Run:
```bash
grep -n "环境就绪检查\|禁止三种降级\|步 0 详解" /workspace/skills/api-orchestrator/SKILL.md
```
Expected: 3 条命中。

- [ ] **Step 5: 提交**

```bash
cd /workspace
git add skills/api-orchestrator/SKILL.md
git commit -m "docs(api-orchestrator): SKILL.md 决策树加步0 环境就绪门禁 + 禁降级行为

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 全量验收（lint 0 ERR + grep 双零 + 行为验证）

**Files:** 无改动；纯验收（spec §8 全部验收标准）

**Interfaces:** Task 1-7 全部产出

- [ ] **Step 1: lint 全量验收——demo 应 exit 0（Task 1 的基线 exit=1 现应回 0）**

Run:
```bash
cd /tmp && unset API_CLI_PLATFORMS_DIR API_CLI_DEPLOYMENT_ROOT
python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py demo; echo "demo lint exit=$?"
```
Expected: `exit=0`（0 ERR）。若有 ERR，看是哪个文件漏改，回对应 task 修。

- [ ] **Step 2: lint 自测全通过（含新 2 bad fixture + 原 good/bad/resolve_base）**

Run: `cd /workspace/skills/api-orchestrator && python3 scripts/lint-platforms.test.py`
Expected: `✓ lint 自测通过...`。

- [ ] **Step 3: grep 验收①——platforms 数据 0 个 ~/.api-cli 字面串**

Run:
```bash
grep -rn "\.api-cli" /workspace/skills/api-orchestrator/platforms/demo/ | grep -v "__pycache__"
```
Expected: **0 命中**。

- [ ] **Step 4: grep 验收②——systems.yaml env 段值全空**

Run:
```bash
grep -A1 "env:" /workspace/skills/api-orchestrator/platforms/demo/systems.yaml | grep "EASYOPS_" | grep -v '""'
```
Expected: **0 命中**（所有 EASYOPS_ 行值都是 `""`）。注意：env_required 段是 list（`- "EASYOPS_X"`），不含 `:`，不会被这条 grep 命中——单独验：

```bash
grep "EASYOPS_.*=" /workspace/skills/api-orchestrator/platforms/demo/systems.yaml
```
Expected: **0 命中**（env_required 段不再有 `=值`）。

- [ ] **Step 5: 行为验收——空环境下 LLM 读 SKILL.md 应停下（场景自检）**

人工/场景验收：模拟空环境（无部署根 env.d/auth.d），按 SKILL.md 步 0 的 echo 检查应发现 env.d/auth.d 缺失 → 按纪律应停下问用户。验收点：SKILL.md 步 0 文字 + 禁降级行为段是否清晰到 LLM 不会自行拼凑。

Run（人工核读）:
```bash
sed -n '/步 0 详解/,/auth.d 有密钥/p' /workspace/skills/api-orchestrator/SKILL.md
```
确认：① 三项检查可执行；② 三种禁令明确；③ 唯一正确动作（停下问用户）清晰。

- [ ] **Step 6: demo 可用性验收——有部署根 env.d/auth.d 时仍能编排（fallback 不破）**

Run（静态等价，不真调）:
```bash
SMOKE=$(mktemp -d) && mkdir -p "$SMOKE/.api-orchestrator"/{platforms/demo,auth.d,env.d}
cat > "$SMOKE/.api-orchestrator/env.d/demo.env" <<'EOF'
export EASYOPS_ORG=18832008
export EASYOPS_USER=easyops
export EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
EOF
cd "$SMOKE" && /workspace/skills/api-orchestrator/scripts/run.sh \
  --spec "$SMOKE/.api-orchestrator/platforms/demo/easyops-cmdb.yaml" object_instance search HOST \
  --body '{"fields":["instanceId"],"page":1,"page_size":1}' --print-curl 2>&1 | head -3
rm -rf "$SMOKE"; cd /workspace
```
> 注：smoke root 里 platforms/demo 是空的（没拷 spec）。若要真跑，需先 `cp` skill 内置 demo 的 spec 过去——此 step 只验 run.sh 解析链不破，spec 缺失报错属预期。

Expected: run.sh 正常解析部署根 + 透传 env（不因本次改动崩溃）。curl 拼出或报 spec 缺失（都说明 run.sh 链路通）。

- [ ] **Step 7: 全通过 → 记录验收**

```bash
echo "✅ 验收全过：lint demo exit 0 / lint 自测通过 / grep ~/.api-cli=0 / grep env 值=0 / 步0纪律清晰 / run.sh 链路通"
git log --oneline e5e2f54..HEAD
```

---

## Self-Review（写计划后自查）

**1. Spec coverage:**
- §3.1 env: 段去值 → Task 2 Step 1/4/5/6（4 系统）✓
- §3.2 端口事实保留 → 不改（runtime.ports 已是事实，Task 2 注释指向它）✓
- §3.3 spec 注释去 IP → Task 3/4/5 ✓
- §4.1-4.3 决策树步 0 + 禁降级 + 三项语义 → Task 7 ✓
- §5.1 ~/.api-cli 改写（7 处实际）→ Task 2(auth×3)/3(cmdb×2)/4(autoops×1)/6(README) ✓
- §5.2 lint 2 规则 → Task 1 ✓
- §5.3 lint 测试 → Task 1 Step 1 ✓
- §6 落地清单 10 项 → 全覆盖（且修正了 spec undercount：env_required 段 + itsm/sys-setting spec 注释）✓
- §7 R1-R4 → Task 8 验收 ✓
- §8 验收 1-5 → Task 8 Step 1-6 ✓
- spec 漏列的 `env_required:` list 段（实测发现）→ Task 2 Step 3/4/5/6 覆盖 ✓
- 无遗漏。

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 有完整代码/精确 old_string；lint 规则有完整 Python 实现。

**3. Type consistency:** lint 规则①扫 `.yaml/.yml/.md`、规则②扫 systems.yaml `env:` dict；test fixture 的 bad systems.yaml 含 `auth:` 注释（规则①）+ `env:` dict（规则②）与实现一致；变量名 `sys_path`/`base`/`err()` 在 lint 内一致。
