# 杜绝 LLM 猜环境拼凑——设计

- **日期**: 2026-08-12
- **范围**: api-orchestrator skill（`/workspace/skills/api-orchestrator/`）
- **目标**: 杜绝 LLM 在环境未初始化时读旧位置（`~/.api-cli/`）+ 读 systems.yaml 的 `env:` 段默认值 + 自行 export 凑数。让环境初始化成为编排强制前置，platforms 数据去默认值但留事实知识（端口），用 lint 把纪律变成可执行闸。
- **状态**: 已批准（brainstorming），待写实施计划
- **前置**: platforms 解耦到部署根（`2026-08-12-platforms-decouple-design.md`）已落地（commits `da193e4..c24d4b3`）

---

## 1. 背景与问题

### 1.1 实测失败模式（用户在 mac 环境实测抓到）

LLM 在空环境编排时输出（节选）：
> "密钥放 `~/.api-cli/auth.d/easyops-cookie.yaml`"
> "若建项目级部署根，按 onboarding 约定**可复制一份**"（把部署根降级成可选）
> "当前项目级部署根不存在，所以我直接显式传了 systems.yaml 里声明的默认值：EASYOPS_ORG=18832008 ..."

三种降级行为，每一种都违背解耦设计。

### 1.2 根因：3 个洞叠加

| 洞 | 表现 | 根因 |
|---|---|---|
| **洞 ①** 缺环境初始化入口 | LLM 从"识别意图"直接跳"执行"，遇空环境自行降级 | SKILL.md 决策树无"环境就绪吗"前置步；onboarding「首写门禁」只管写 platforms，不管读时缺环境 |
| **洞 ②** env: 段语义危险 | LLM 把 systems.yaml 的 `env:` 段（`EASYOPS_*_URL: "http://172.30.0.232:8079"`）当运行时 fallback 值用 | `env:` 段注释只写"供 api-cli/shell 注入"，未声明是文档性契约；且值是具体 IP，正是拼凑根源 |
| **洞 ③** platforms 数据旧引用 | LLM 认 `~/.api-cli/auth.d/` 是主位置 | 解耦只改了 skill 侧文档（SKILL.md/orchestration/onboarding），**漏改 platforms 数据**——systems.yaml/spec/README 里 5 处 `~/.api-cli/auth.d/` 仍在 |

### 1.3 技术约束（决定方案）

- spec 里 `endpoints.backend.base_url: ${EASYOPS_CMDB_BACKEND_URL}` 把**整个 URL（IP+端口）绑在一个变量**。无法"只留端口去 IP"——插值粒度是完整 URL。
- 但**端口事实不依赖 env: 段**：systems.yaml `runtime.ports:` 段单独存端口（`cmdb_backend: 8079` 等），env: 段即使全删值，端口事实仍在 ports 段。
- 故"事实留、配置去"可实现：端口留 `runtime.ports`，URL 值从 `env:` 段去除。

---

## 2. 设计决策

| 维度 | 决策 | 理由 |
|---|---|---|
| 信息分类 | A 事实（端口/host/服务名）留 systems.yaml；B 环境配置（IP/org/user/URL）只在部署根 env.d；C 变量契约留 systems.yaml env: 段（去值留 key） | 用户原则"事实留、配置去、告知配置方法"；端口是源码定义的事实，IP 是部署时才知道的配置 |
| env: 段 | 保留变量名清单，**值全置空**（`EASYOPS_X: ""` + 注释指向 env.d） | 断 LLM 复用值的可能；保留 key 让 LLM 知道"需要哪些变量" |
| 环境就绪门禁 | **三项全查**：platforms 可达（部署根 or skill 内置 fallback）+ env.d 存在 + auth.d 有密钥；任缺即停 | 堵降级行为；platforms 这项不查部署根存在性（fallback 合法），env/auth 必须从部署根 |
| 降级行为 | **显式禁止 3 种**：读 env: 段值、用 ~/.api-cli/ 旧位置、自行 export 默认值；唯一正确动作=停下问用户 | 对症用户实测的 3 句话 |
| 决策树步位 | 环境就绪门禁放**最前（步 0）**，先于"是 onboarding 吗" | 环境就绪是一切编排前提，比模式判断更基础 |
| lint 可执行闸 | 加 2 条 lint 规则：① platforms 数据禁 `~/.api-cli/` 字样；② env: 段值禁非空 URL/IP | 把纪律变闸，防回潮 |
| 向后兼容 | 不加（开发阶段） | 与解耦设计一致 |

---

## 3. §1 落地——systems.yaml 信息分类与 env: 段去值

### 3.1 env: 段改写（4 系统，cmdb 示例，其余同构）

**现状**（systems.yaml cmdb 段 L71-74）：
```yaml
env:                                 # 部署所需环境变量（供 api-cli / shell 注入）
  EASYOPS_CMDB_BACKEND_URL: "http://172.30.0.232:8079"  # cmdb_service 后端（实测）
  EASYOPS_CMDB_FRONTEND_URL: "https://172.30.0.232"      # 前端页面/网关
  EASYOPS_USER_SERVICE_URL: "http://172.30.0.232:8111"      # user_service（org 查询等）
```

**改为**（去值留 key + 指向 env.d）：
```yaml
env:                                 # 环境变量契约（仅声明需要哪些变量 + 用途；【值在部署根 env.d/<dep>.env，勿从此处取】）
  EASYOPS_CMDB_BACKEND_URL: ""       # cmdb_service 后端完整 URL（含 IP+端口）；端口事实见 runtime.ports.cmdb_backend
  EASYOPS_CMDB_FRONTEND_URL: ""      # 前端页面/网关完整 URL
  EASYOPS_USER_SERVICE_URL: ""       # user_service（org 查询）完整 URL；端口见 runtime.ports.user_service
```

itsm/autoops/sys-setting 4 段 env 同构改写（去值、注释指向 env.d + 端口指向 runtime.ports）。

### 3.2 端口事实保留（runtime.ports，不动）

现状已是事实知识，保留：
```yaml
ports: { cmdb_backend: 8079, user_service: 8111, frontend: 232 }   # 事实知识（服务源码定义），留
```

### 3.3 spec 注释去 IP（easyops-cmdb.yaml 等）

**现状**（easyops-cmdb.yaml L39）：
```yaml
base_url: ${EASYOPS_CMDB_BACKEND_URL}        # http://172.30.0.232:8079
```
**改为**：
```yaml
base_url: ${EASYOPS_CMDB_BACKEND_URL}        # 值在部署根 env.d/demo.env（含 IP+端口）；端口事实见 systems.yaml runtime.ports
```

org/user 注释同理去具体值：
```yaml
# 现状
org: ${EASYOPS_ORG}    # ...测试用 18832008。export EASYOPS_ORG=<值>
# 改为
org: ${EASYOPS_ORG}    # 值在部署根 env.d/demo.env
```

---

## 4. §2 落地——决策树环境就绪门禁（步 0）

### 4.1 SKILL.md 决策树最前加步 0

```
需求进来
│
├─[0] 环境就绪检查（所有编排前置，强制）
│      echo 确认：
│        · platforms 可达：$API_CLI_PLATFORMS_DIR/<dep>/ 存在，或 fallback skill 内置 platforms/<dep>/
│        · env.d：$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env 存在
│        · auth.d：$API_CLI_AUTH_D/ 有密钥文件
│      ├─ 三项俱全 → 继续
│      └─ 缺任一 → 【停下，打印缺失项 + 配置方法，问用户】
│
├─[1] 是"接入新系统/加能力域"吗？
│      ...
```

### 4.2 显式禁止降级行为（SKILL.md 步 0 段）

> **环境未就绪时禁止的降级行为**（实测踩坑）：
> - ❌ 读 `systems.yaml` 的 `env:` 段当运行时值用（env: 段是变量契约，值已置空）
> - ❌ 用 `~/.api-cli/` 旧位置（已废弃，干净切换）
> - ❌ 自行 `export EASYOPS_*=默认值` 凑数
> - ✅ 唯一正确动作：停下，打印缺失项 + 指向 onboarding.md「初始化部署根」，问用户

### 4.3 三项精确语义

- **platforms 可达**：部署根 `$PLATFORMS_ROOT/<dep>/` 存在 → 用项目级；**不存在 → fallback skill 内置**（合法，不算缺失）。查的是"能否定位到任一存在的 platforms 目录"。
- **env.d 存在**：`$API_CLI_DEPLOYMENT_ROOT/env.d/<dep>.env` 必须存在（skill 内置不提供业务变量）。
- **auth.d 有密钥**：`$API_CLI_AUTH_D/` 下有 `*.yaml` 密钥文件（skill 内置不提供密钥）。

---

## 5. §3 落地——platforms 数据旧引用改写 + lint 闸

### 5.1 5 处 ~/.api-cli 旧引用改写

| 文件:行 | 现状 | 改为 |
|---|---|---|
| systems.yaml:69 | `auth: easyops-cookie # ~/.api-cli/auth.d/easyops-cookie.yaml：...` | `auth: easyops-cookie # 部署根 auth.d/easyops-cookie.yaml（API_CLI_AUTH_D 指向；原 home 目录位置已废弃）` |
| systems.yaml:220 | 同构（autoops） | 同构 |
| systems.yaml:304 | 同构（itsm） | 同构 |
| systems.yaml:466 | 同构（sys-setting） | 同构 |
| easyops-cmdb.yaml:24,54 | spec 注释 `~/.api-cli/auth.d/...` | `部署根 auth.d/...（API_CLI_AUTH_D）；原 home 目录位置已废弃` |
| easyops-autoops.yaml:30 | 同上 | 同上 |
| README.md:32 | `cookie@~/.api-cli/auth.d/ + env@~/.api-cli/env.d/` | `cookie@部署根 auth.d/ + env@部署根 env.d/（部署根默认 $PWD/.api-orchestrator；原 home 目录位置已废弃）` |

> 注：lint 规则① 完全禁 `~/.api-cli/` 字面字符串，故所有"提旧位置"的措辞改用「原 home 目录位置」等不含该串的表述。改写前全量 grep 定位，确保 0 残留。

### 5.2 lint 加 2 条规则（lint-platforms.py）

**规则 ①**：platforms 数据禁 `~/.api-cli/` 字样（**完全禁，无豁免**——连"已废弃"说明也改用不含该字符串的表述，如「原 home 目录位置已废弃」）。
```python
# 扫描所有 platforms/<dep>/ 下的 .yaml/.md，出现 ~/.api-cli/ 即 ERR
# 无豁免关键字：要提旧位置就改写措辞（"原 home 目录位置"等），不出现字面 ~/.api-cli/
```

**规则 ②**：env: 段值禁非空 URL/IP。
```python
# systems.yaml 的 systems.<sys>.env 段，每个 value 必须为空字符串 ""
# 出现 http:// / 数字 IP（正则 \d+\.\d+\.\d+\.\d+）即 ERR
```

### 5.3 lint 测试（lint-platforms.test.py）

加 2 个 bad fixture：
- `test-bad-stale-path`：objects/systems 里写 `~/.api-cli/auth.d/`（非"已废弃"语境）→ ERR
- `test-bad-env-value`：env 段写 `EASYOPS_X: "http://1.2.3.4"` → ERR

---

## 6. 落地清单

| # | 文件 | 改动 | 性质 |
|---|---|---|---|
| 1 | `platforms/demo/systems.yaml` | env: 段 4 系统去值留 key + 指向 env.d；auth 注释 4 处去 ~/.api-cli | 数据 |
| 2 | `platforms/demo/easyops-cmdb.yaml` | base_url/org/user 注释去 IP + 指向 env.d；auth 注释去 ~/.api-cli | 数据 |
| 3 | `platforms/demo/easyops-autoops.yaml` | 同构（base_url/auth 注释） | 数据 |
| 4 | `platforms/demo/easyops-itsm.yaml` | 同构 | 数据 |
| 5 | `platforms/demo/easyops-sys-setting.yaml` | 同构 | 数据 |
| 6 | `platforms/demo/README.md` | L32 鉴权位置说明改部署根 | 数据 |
| 7 | `SKILL.md` | 决策树加步 0 环境就绪门禁 + 禁止降级行为 | 文档 |
| 8 | `scripts/lint-platforms.py` | 加 2 条规则（禁 ~/.api-cli + env 值禁非空） | 代码 |
| 9 | `scripts/lint-platforms.test.py` | 加 2 bad fixture | 代码 |
| 10 | 全量 grep 验收 | platforms 数据 0 残留 ~/.api-cli（除"已废弃"语境） | 验收 |

---

## 7. 风险与排除

| 风险 | 排除动作 | 类型 |
|---|---|---|
| **R1 env: 去值破坏 demo fallback** | 改后跑 `scripts/lint-platforms.py demo` exit 0 + run.sh 用 skill 内置 demo 跑通（env.d 仍要外部提供） | 硬验收 |
| **R2 lint 规则①误伤** | 规则①完全禁 `~/.api-cli/` 字面串、无豁免；提旧位置一律改「原 home 目录位置」措辞；test fixture 覆盖（写 ~/.api-cli/ → ERR） | 硬验收 |
| **R3 LLM 仍读 spec 注释里的 IP** | spec 注释全去 IP（§3.3）；lint 规则②覆盖 spec 的 env 段（若 spec 也有 env 段） | grep 验收 |
| **R4 步 0 门禁太严，demo fallback 被拦** | 三项语义明确：platforms 可达含 fallback；只有 env.d/auth.d 缺才停 | 设计已定 |

---

## 8. 验收标准

1. **grep 验收**：`grep -rn "~/.api-cli" platforms/demo/` 剩余命中**只在"已废弃"语境**（或 0 命中）。
2. **env: 值验收**：`grep -A5 "env:" systems.yaml` 所有 env 段值为 `""`。
3. **lint 通过**：`scripts/lint-platforms.py demo` exit 0；新 bad fixture 被 2 条规则抓出。
4. **行为验收**：模拟空环境（无部署根 env.d/auth.d），LLM 读 SKILL.md 步 0 → 应停下问用户，不拼凑（人工/场景验收）。
5. **demo 可用**：有部署根 env.d/auth.d 时，skill 内置 platforms/demo 仍能编排（fallback 不破）。
