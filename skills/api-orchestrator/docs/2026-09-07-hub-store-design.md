# hub 平台商店设计（api-orchestrator）

- 日期：2026-09-07
- 状态：已批准（方案 B：集中式 hub reference）
- 范围：`skills/api-orchestrator/`（机制挂载）+ `platforms/easyops/hub/`（存量清理 + 索引）

## 1. 背景与目标

`skills/api-orchestrator/platforms/easyops/hub/`（8.4M）是套件/脚本成品的堆放目录，现状问题：

1. **零元数据**——除文件名外无任何索引，查重只能 `ls` + 人肉记忆；
2. **机制缺失**——SKILL.md / orchestration.md / onboarding.md 均未提及 hub，"开发前查重、产物回流" 无机制承载；
3. **存量污染**——`__pycache__`、migration 运行输出混在成品里。

目标：把 hub 打造成**平台商店**——开发任务开始前先到这里查是否已有可复用的套件/脚本；开发过程的成品交付物统一回流到这里。机制与 skill 既有范式同构：**调度靠 LLM 读文档（语义查重），质量靠 lint 硬门禁（索引一致性），零新运行时代码**。

### 已确认的决策

| 决策点 | 结论 |
|---|---|
| 使用者 | api-orchestrator skill 本身（决策树/references 挂载，agent 自动执行） |
| 收录范围 | 仅成品交付物（可导入/可部署的套件包、脚本、模板等） |
| 查重载体 | hub 根下单 `INDEX.yaml`，每件商品一条记录 |
| 存量处理 | 本次一并清理（__pycache__、运行输出）+ 全量补索引 |
| 回流时机 | 交付时自动回流（agent 落文件 + 更新索引 + commit），用户事后审 |

### 架构定位

hub 是 **deployment 级开发态资产库**（`platforms/<deployment>/hub/`，随 skill 分发），不是运行时部署根（`$PWD/.api-orchestrator/`）。机制定义在 `references/hub.md`（通用、零系统耦合——任何 deployment 都可有 hub），`platforms/easyops/hub/` 只是 easyops 实例。orchestration 模式 platforms 只读纪律不变；**规划挡开发交付场景**（做出成品）视为开发态延伸，回流是交付动作的一部分。

## 2. 静态结构

### 2.1 目录分类规范（类目 = hub/ 一级子目录）

沿用现有 9 个子目录，每个在 `references/hub.md` 中明确定义：

| 类目 | 放什么 |
|---|---|
| `cmdb-kits/` | CMDB 采集套件包 + 配套参考文档 |
| `inspection-kits/` | 巡检套件包（tar.gz） |
| `monitor-kits/` | 监控套件包 + 配套告警规则模板（xlsx） |
| `scripts/` | 可交付脚本，按域分子目录（cmdb/ itsm/ platform/ …） |
| `tools/` | 注册到 autoops 的工具脚本成品 |
| `sso-adapter-providers/` | sso-adapter 标准 provider 成品 |
| `itsm-service/` | ITSM 服务/流程交付包 |
| `custom-msg-sender/` | 自定义消息发送器成品 |
| `other/` | 未归类交付物 |

类目集合是 **deployment 级约定**（easyops 实例在 INDEX.yaml 头注释声明语义），机制层（references/hub.md）只定义"hub = 类目子目录 + INDEX.yaml"的通用结构——不硬编码任何具体类目，保持 skill 零系统耦合。

**命名规范**（增量遵守，存量不改名）：`<名称>_v<版本>.<ext>`；同商品新版本出 → 删旧版文件（git rm），目录只留最新版，历史靠 git 追溯（对齐 AGENTS.md §6）。

### 2.2 INDEX.yaml schema

`hub/INDEX.yaml`：头部注释声明类目语义（人读导航），正文每件商品一条：

```yaml
# 类目语义: cmdb-kits=CMDB采集套件包 monitor-kits=监控套件包 ...
items:
  - id: fc-switch-monitor-kit            # 唯一 id，kebab-case
    name: 光纤交换机监控套件
    category: monitor-kits               # 必须是 hub/ 实际子目录（lint ERR）
    files: [光纤交换机监控套件_v1.0.13.zip, 光纤交换机监控_告警规则模板.xlsx]
    version: 1.0.13                      # 包内读不出则留空
    scenario: 光纤交换机(Brocade/华为OEM) SNMP 指标监控接入   # ★语义查重核心
    notes: 导入后需按配套 xlsx 配置告警规则
    added: 2026-08-29
```

7 字段。`scenario` 是查重匹配的关键载体（对象 + 场景关键词）。刻意不设 type/source 等字段——category 已承载类型，YAGNI。

### 2.3 存量清理清单

| 动作 | 对象 | 依据 |
|---|---|---|
| 删 | `hub/scripts/cmdb/__pycache__/`、`hub/scripts/platform/easyops-migration/__pycache__/` | 运行时垃圾 |
| 删 | `hub/scripts/platform/easyops-migration/output/`（export/import_report.json + instances/） | 某次迁移的运行输出，非成品 |
| 移 | `hub/scripts/day.py` → `/workspace/output/other/` | 个人调试脚本，非交付物；output/other 是既有非交付物暂存区 |
| 保留 | `hub/scripts/itsm/pillow-*.whl` | itsm_process_doc.py 的离线依赖，属交付配套 |
| 保留 | scripts/ 下 6 散脚本 + 2 zip | 均为成品 |
| 补索引 | 全部存量 ≈35 件商品 | 版本号批量从包内 info.yaml 读，读不出留空 |

## 3. 动态机制

### 3.1 查重流程（开发前必查）

挂载点：`references/orchestration.md` 规划挡流程，步 1"解析需求"之后、生成 plan 之前。

**触发条件**：需求涉及**开发/交付新套件、脚本、工具**（而非纯查询编排）。

1. **读 INDEX**：`Read $PLATFORMS_ROOT/<dep>/hub/INDEX.yaml`（单文件一次读全）。
2. **语义匹配**：拿需求的对象/场景关键词对 `scenario` + `name` 匹配。
3. **三分支**：
   - **命中** → 报告用户"hub 已有 `<name>` v<version>，位于 `<category>/<file>`"，给出复用/改造/重做建议，用户选向后再继续；
   - **近似命中**（同类设备不同型号、同域不同对象）→ 报告差异，建议作为改造基底（版本 +1），用户决定；
   - **未命中** → 正常开发，交付时走回流。
4. 查重结论写进 `tmp/<task>/plan.md`（如"hub 查重：未命中"/"复用 fc-switch-monitor-kit"），留审计痕。

查重不改变挡位判定，只是规划挡内的前置步骤；直通/确认挡的纯查询、简单写不触发。

### 3.2 回流流程（交付时自动）

**触发条件**：规划挡任务交付，产物含可导入/可部署成品（套件包/脚本/工具/provider/服务包）。

1. **归位**：成品落 `hub/<category>/`，命名 `<名称>_v<版本>.<ext>`；旧版本文件同目录删除（git rm）。
2. **登记**：INDEX.yaml `items` 追加/更新一条（id 已存在则更新 version/files/added 保持不动）。
3. **commit**：回流后立即 commit（防工作区自动提交机制打包垃圾 message）。
4. 配套文档（告警规则 xlsx、MIB 参考 md 等）跟主件同 `files` 登记，不单独成商品。

**权限口径**：hub 写入属开发态动作；orchestration 模式 platforms 只读纪律不变，但规划挡开发交付场景视为开发态延伸，回流是交付动作的一部分。此口径写进 SKILL.md「模式与写保护」表格备注。

### 3.3 lint 扩展（索引一致性硬门禁）

`scripts/lint-platforms.py` 加第 11 段校验（hub/ 存在才跑，不存在跳过不报错——hub 是可选资产）：

| 校验 | 级别 | 说明 |
|---|---|---|
| INDEX 文件存在 | WARN | hub/ 存在但无 INDEX.yaml |
| category 合法 | ERR | 指向不存在的一级子目录 |
| files 双向一致 | ERR | 索引文件必须存在；hub 成品文件（按扩展名 zip/tar.gz/gz/xlsx/whl/sh/py/md/json 识别）必须在索引（.gitkeep 除外） |
| id 唯一 | ERR | 重复 id |
| scenario 非空 | WARN | 查重核心字段缺失 |
| 版本单份 | ERR | 同 id/name 多版本文件并存（`_v1.0.1` 与 `_v1.0.2` 同存） |

### 3.4 文档挂载点（改动清单）

| 文件 | 改动 |
|---|---|
| 新建 `references/hub.md`（~100 行） | 集中定义：目录分类规范 / INDEX schema / 查重流程 / 回流流程。通用零系统耦合 |
| `SKILL.md` | 决策树 [2] 加一行（涉及套件/脚本开发 → 先查 hub）；「模式与写保护」表格加回流口径备注；「关键纪律」加一条 |
| `references/orchestration.md` | 规划挡流程步 1 后插 hub 查重步（~4 行） |
| `references/onboarding.md` | 步 7 交付清单加"成品回流 hub"项 |
| `platforms/easyops/README.md` | 资料地图表加 hub → INDEX.yaml 一行 |
| `platforms/easyops/hub/INDEX.yaml` | 存量 35 件全量登记 |

### 3.5 测试与验收

- `scripts/lint-platforms.test.py` 补 5 用例：INDEX 缺失 / 文件双向不一致 / id 重复 / 多版本并存 / 正常通过。
- 查重/回流是 LLM 纪律，无法单测——靠 lint 兜底索引质量 + SKILL.md 挂载保证触发；验收走一次人工演练（模拟"要做 XX 监控套件"需求，验证查重命中既有商品）。

## 4. 明确不做（YAGNI）

- 不做 hub 管理命令脚本（`hub.sh search/add`）——查重是语义匹配，LLM 读索引比关键词 grep 准；与"调度靠 LLM、无代码引擎"范式相悖。
- 不建 per-目录 README——单一 INDEX 已够，分目录读 9 个文件费 token。
- 存量文件不改名对齐命名规范——只管增量。
- 不做 hub 版本历史/变更日志——git 历史即变更日志。
- 不把 hub 机制写进 AGENTS.md——使用者已定为 skill 本身，非所有会话。
