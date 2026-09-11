# fintech-report — 人行金融科技信息报送操作与实施手册

> 版本 v1.0.35 · 工具包「人行金融数据上报」（EasyOps 平台）· 单文件脚本、零外挂配置、纯标准库
>
> 本手册覆盖：系统定位、平台入口、日常维护场景操作流程、上报任务生命周期、增量比对机制、失败明细、清理策略、CMDB 配置模型、人行接口链、常见问题。

---

## 1. 系统定位

把 EasyOps CMDB 的 `@FINTECHDATA` 命名空间实例（交换机、服务器、机房、供配电、应用系统等 60+ 数据元）按人行《金融信息基础设施管理平台接入规范》口径转换后，通过 HTTPS 推送到 FICS 报送中心（金融信息基础设施管理平台）。

- **源数据**：EasyOps CMDB（`数据管理` → CMDB 资源管理）
- **执行**：EasyOps 平台定时任务/工具执行（`自动上报管理` → 进入定时任务）
- **落点**：人行金融信息基础设施管理平台（检核 → 入库申请 → 入库）
- **本地记录**：任务历史、失败明细、数据原文全部回存 CMDB 与磁盘，全程可追溯

由 `fintech_data` Go 微服务迁移而来，py 版在此基础上完成**组级状态闭环、双基准防重报、行级失败明细捕获**等演进。

## 2. 平台入口

| 入口 | 路径 | 用途 |
|---|---|---|
| 自动上报管理 | 平台 → 定时任务 | 配置/触发上报任务（action=report） |
| 数据管理 | 平台 → CMDB 资源管理 | 维护上报数据源实例（人行上报相实例列表入口） |
| 人行管理平台 | 浏览器访问 FICS | 查看上报批次组、提交报送入库申请、确认上报结果 |

![平台入口-自动上报管理](docs/images/entry-1.png)

![平台入口-定时任务](docs/images/entry-2.png)

![平台入口-数据管理](docs/images/entry-3.png)

![人行上报实例列表入口](docs/images/entry-4.png)

## 3. 两种运行模式（工具入参）

| action | 能力 | 触发方式 |
|---|---|---|
| `report` | 增量上报：结算在途组 → diff 比对 → 分批上报 → 批次/组检核 → 任务落库；**完成后自动按清理规则收尾** | 定时任务 / 手动执行 |
| `cleanup` | **不上报**，只按清理规则清理历史（任务记录 + 原文 json + 失败明细级联） | 手动执行 |

入参 `scope` 选择上报范围（CMDB_MODEL 实例选择器，只列 `@FINTECHDATA` 模型），**留空 = 全部启用规则**。

```bash
# 本地 CLI（开发版等价能力）
python3 fintech_report.py report                                   # 全部启用规则
python3 fintech_report.py report --scope "switches@FINTECHDATA"    # 指定模型（逗号分隔）
python3 fintech_report.py cleanup [--dry-run]                      # 独立清理 / 只预览不删
```

> 全量上报模式（--full）与回滚（rollback）的工具入口已移除；回滚逻辑保留在 CLI 子命令（`rollback --task <taskId>`）。无成功台账时（首次接入/全部回滚后）自动全量 new。

## 4. 日常维护场景操作流程

### 4.1 新增实例

```
实例列表新增（数据管理 → 对应模型 → 新增）
    ↓
等待定时任务触发（或自动上报管理中立即执行）
    ↓
进入人行管理平台，查看对应上报批次组
    ↓
提交报送入库申请（人行平台人工环节）
    ↓
等待批次组处理完成，即可确认上报结果
```

![新增-实例列表新增](docs/images/add-list.png)

![新增-填写信息保存](docs/images/add-form.png)

![新增-填写信息保存（续）](docs/images/add-form2.png)

![新增-保存成功](docs/images/add-save.png)

![新增-填写信息保存（续2）](docs/images/add-save2.png)

![新增-定时任务列表](docs/images/add-task.png)

![新增-立即执行](docs/images/add-trigger.png)

**人行管理平台侧**——查看上报批次组、提交报送入库申请、确认结果：

![人行平台-上报批次组](docs/images/pbc-group.png)

![人行平台-批次组详情](docs/images/pbc-group2.png)

![人行平台-提交入库申请](docs/images/pbc-apply.png)

![人行平台-提交入库申请（续）](docs/images/pbc-apply2.png)

![人行平台-处理结果](docs/images/pbc-result.png)

![人行平台-确认上报结果](docs/images/pbc-result2.png)

### 4.2 修改实例

```
实例列表编辑（改字段保存）
    ↓
等待定时任务触发 —— 增量 diff 检测内容 hash 变化 → 生成 update 报文
    ↓
审批、查看结果（人行平台批次组）
```

![修改-实例编辑](docs/images/edit-list.png)

![修改-审批查看结果](docs/images/edit-result.png)

**注意**：修改只改「上报字段集内」的业务字段才触发（系统字段如 mtime/creator 不在转换范围）；实例若处于在途（检核已过、等人工入库），内容变更同样会触发重报（v1.0.33「变了就报」）。

### 4.3 删除实例

```
实例列表选择实例，批量删除
    ↓
等待定时任务触发 —— 生成 delete 报文（携带该实例上次成功快照的完整字段）
    ↓
审批、查看结果
```

![删除-选择实例批量删除](docs/images/del-list.png)

![删除-确认删除](docs/images/del-confirm.png)

![删除-审批查看结果](docs/images/del-result.png)

删除触发条件：该实例曾被人行确认入库（在 confirmed 台账），或在途任务的原文里（v1.0.35：在途实例删除也发 delete——组后续入库则人行侧生效，未入库则失败明细暴露、结算后重删）。**从未成功上报过的实例删除是静默的**（人行库没有它，无需删除请求）。

## 5. 上报任务生命周期（状态闭环）

```
reporting ──► pendingCheck ──► inFlight ──► success / partialSuccess
  运行中        检核未出结果      等人工入库        入库终态（组 40003/40004/40006）
                  │                │
                  │                └──► fail（组终态失败 40005/40007，含驳回）
                  └── 下次运行续查
noReport（本次无上报项）    rolledBack（人工回滚，CLI）
```

关键设计：

- **单次运行不等待人工环节**：组到 WL-40001「等待入库申请」立即返回，任务标 `inFlight`，绝不死等——这就是为什么要去人行平台「提交报送入库申请」
- **下次运行开头自动结算**（settle）：逐个在途任务查组现状一次（不轮询）——组入库成功 → 实例 confirmed、任务 success；组终态失败/驳回 → 任务 fail + 行级明细补拉；仍在途 → 保持冻结
- **在途冻结（hash 精判）**：在途实例内容未变 → 跳过（防重复报送制造「数据已存在」）；**内容变了 → 照常 new/update**

| 组状态码 | 分类 | 行为 |
|---|---|---|
| WL-40000 | PENDING 检核中 | 轮询等待（最多 30×10s） |
| WL-40001/40002 | **INFLIGHT 在途** | 立即返回，任务 inFlight，实例冻结 |
| WL-40003/40004/40006 | STORED 入库成功 | confirmed + 行级补拉 + 计数 |
| WL-40005/40007 | FAIL 终态失败 | 任务 fail + 行级明细 |

## 6. 增量比对：三道基准

```
CMDB 现值 vs ┬─ confirmed 台账    （人行确认入库过）→ 未变不报；变了 update；CMDB删了 delete
             ├─ alreadyExists 基准（人行声明已存在） → 数据未变跳过；变了恢复上报
             └─ inflight_map     （在途实例+冻结hash）→ 原样重发冻结；变了就报
```

| 场景 | 行为 |
|---|---|
| 新实例（台账没有） | new |
| 内容变更（hash 失配） | update |
| CMDB 删除（台账/inFlight 有） | delete（带完整快照字段） |
| 已存在实例、数据未变 | 跳过（重报必撞「数据已存在」） |
| 在途实例、数据未变 | 冻结跳过 |
| 已存在/在途实例、数据变了 | 恢复上报（新内容人行库没有） |

台账来源：扫全部 success/partialSuccess/inFlight 任务原文（dataFile json）的实例级 `_confirmed` 标记，跨任务合并、新覆盖旧。settle 结算回写**直达原路径**（v1.0.34，不产生孤儿 json 文件）。

## 7. 失败明细（FINTECH_REPORT_INSTANCE）

每条实例级行失败逐条落库，detailId = `<设施标识符>_<批次号尾>`，含：模型、任务号、批次号、错误码、分类标识符、设施标识符、错误信息。在 CMDB 实例列表按 facilityDescriptor 过滤即知哪个实例、什么问题。

**捕获时机**（三处，全部同实例跨批次去重）：

1. 批次轮询期间 data[] 里的终态失败行
2. 组到 40001/40003 时的行级补拉——**组 OK ≠ 行级全过**，人行检核慢，行级失败码（如产品序列号重复、数据已存在）常在批次轮询超时后才出现
3. settle 结算时（含组失败路径）

**常见错误语义**：

| 错误 | 含义 | 处理 |
|---|---|---|
| WL-20001【产品序列号】数据重复异常 | 同序列号实例重复上报 | 治理源数据 |
| WL-20003【数据已存在】不可重复报送 | 人行库已有该实例 | 数据未变自动跳过重报；变了会 update 刷新 |
| WL-20001 数据元属性数量过多 | 报文携带人行定义外的字段（如 importId） | 工具已内置 FIELD_BLACKLIST 剔除；若再出现检查 objectDefine |
| 枚举异常 | 值不是合法数字码 | 检查字段类型定义与源数据（见 §9 常见问题） |

实例重报成功后其失败明细自动清除（按 objectId+descriptor 匹配）。

## 8. 清理策略（FINTECH_REPORT_CLEANUP）

规则字段：规则名、启用、适用模型（scope，空=全部）、保留条数（maxCount）、保留天数（maxAgeDays）。

| 配置 | 语义 |
|---|---|
| 双正数（如 5/365） | **AND**：每模型保留最近 N 条 **且** N 天内，同时超出条数**和**天数才清 |
| 双 0（0/0） | **全清**：scope 内全部删（保护仍然生效） |
| 任一为 0（如 1/0） | ❌ 不合法，规则跳过（防半配置误删） |

删除内容：任务记录 + dataFile 原文 json + **级联失败明细**（按 taskId）+ 回滚记录。

**两个内置保护（全清模式同样生效）**：

- **基准保护**：每模型最新一条 success/partialSuccess 任务永不删——它是增量 diff 的基准来源，删了会导致全量重报风暴
- **活动保护**：pendingCheck / inFlight 任务不删——组还可能结算，dataFile 是冻结/结算依据

触发：report 模式完成后自动执行 + cleanup 模式独立执行。

## 9. CMDB 配置模型

| 模型 | 角色 | 关键字段 |
|---|---|---|
| `FINTECH_REPORT_CONFIG@EASYOPS` | 全局连接 | 名称/客户端ID/客户端密钥/平台ip/端口/金融机构编码/上报路径 |
| `FINTECH_REPORT_OBJ@EASYOPS` | 上报规则（每模型一条） | 模型id/名称/二级分类/映射模型/实例数据来源(direct或mapping)/**模型定义(objectDefine)**/映射规则 |
| `FINTECH_REPORT_TASK@EASYOPS` | 任务历史 | taskId/status(**含 inFlight 枚举**)/branchId/统计/checkCode/dataFile/rolledBack |
| `FINTECH_REPORT_INSTANCE@EASYOPS` | 失败明细 | detailId/objectId/设施标识符/错误码/错误信息/批次号/任务号 |
| `FINTECH_REPORT_ROLLBACK@EASYOPS` | 回滚记录 | rollbackId/taskId/status/deleteCount |
| `FINTECH_REPORT_CLEANUP@EASYOPS` | 清理规则 | 见 §8 |

**⚠️ objectDefine 是转换字段的类型来源**：枚举转换（`00-在用`→`00`）只对 `value.type == "enum"` 的字段生效。现场改字段枚举必须改 FINTECH_REPORT_OBJ 规则实例的 objectDefine——**改 CMDB 模型库的主定义无效**（工具只读规则实例）。

转换器其他行为：bool/float（默认 2 位）/date/struct 递归/omitempty（空维保段省略）/空值传 `""`/PK 翻译（关系模型 relationalIdentifier 等）/FIELD_BLACKLIST 强制剔除 importId 等系统字段。

数据原文落盘：`DATA_DIR/<日期>/<taskId>.json`（工具版优先级：`FTECH_DATA_DIR` 环境变量 → agent `/data` → easyops 目录 → `/tmp`）。无 Mongo/SQLite/外挂配置。

## 10. 人行接口链

```
reportData（受理，得批次号 BA…）
  → selectUploadData 轮询批次（5×10s）
  → requestCheck 发起组检核（得组号 GA…）
  → getGroupStatus 轮询组状态（遇 40001/40002 立即返回，任务 inFlight）
  → [组分支/结算时] check_result_once 单次补拉行级明细
```

认证：OAuth client_credentials 取 token（缓存至过期前 10s）+ 报文 gzip+base64 + X-Access-Token。组轮询遇 INFLIGHT 立即返回是「单次生命周期不变」的保证——等待人工的环节永远不进入轮询。

## 11. 常见问题

**Q: 改了实例为什么没触发上报（noReport）？**
① 改的是非上报字段（系统字段/辅助信息 tag）；② 实例在途且内容未变（冻结，正常）；③ 已存在基准且数据未变（防重报，正常）。改业务字段后下轮必触发（变了就报）。

**Q: 任务一直是 inFlight？**
组停在 WL-40001 = 人行等待入库申请——**需要去人行管理平台提交报送入库申请**（人工环节）。工具不等待，下次运行会自动结算。

**Q: 明细表数据和任务失败数对不上？**
明细表语义是「当前仍未成功的实例清单」：实例重报成功后明细即清除；任务 failedCount 是当时快照。清理任务时其明细随任务级联删除。

**Q: 枚举改了还是报枚举异常？**
确认改的是 FINTECH_REPORT_OBJ 规则实例的 objectDefine（value.type 改为 enum），不是 CMDB 模型库；`00-名称` 格式的值转换时会截断为 `00`，纯中文名（如「共享支持类」）需要值域映射或源数据改成 `码-名` 形态。

**Q: 引用字段报「长度异常/未找到」？**
引用字段（部署数据中心/所属机柜/供电设施等）必须填 32 位设施标识符。源数据是 `名称[32位标识符]` 形态的需提取标识符（治理建议）；纯名称的无法自动处理，失败明细如实记录。

**Q: 怎么全部清理？**
清理规则配 双 0（保留条数=0、保留天数=0）+ 启用，跑 cleanup 模式。基准任务（每模型最新 success）和在途任务受保护不会删——这是防全量重报风暴与断生命周期的设计。

## 12. 已知边界

- 人行组停在 40001 期间任务持续 inFlight——入库申请是人行平台人工环节，工具不等待，靠下次运行结算；若人行驳回后组状态永不变化，任务会停在 inFlight（可 CLI rollback 触发重报）
- settle 结算晚于本地删除时，实例先确认进台账再幂等删一次（delete 幂等，多一轮请求）
- 引用字段值为纯名称（无 32 位标识符）无法转换，失败明细如实记录（需源数据治理）
- 品牌产地（brandLand）等枚举字段为空时不能填「未知」（非合法枚举），需源数据补
- 触发由外部定时集成负责（工具不内置定时）；工具超时 3600s

---

*历史版本细节见 git log（v1.0.24 组码修正 → v1.0.26~28 明细/闭环演进 → v1.0.29 状态闭环+清理内联 → v1.0.30 双基准 → v1.0.31 FIELD_BLACKLIST → v1.0.32 模式调整 → v1.0.33 变了就报 → v1.0.34 回写原路径 → v1.0.35 在途删除）。*
