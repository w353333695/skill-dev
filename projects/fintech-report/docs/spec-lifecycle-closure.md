# fintech-report 状态闭环 + 清理内联 spec（v1.0.29）

> 2026-09-08 · 基于 v1.0.28（commit 77d9695）迭代
> 前置讨论结论：做组级状态闭环；单次上报生命周期不变（不死等人工）；放弃实例级状态记录；
> 清理内联进上报流程并级联清理失败明细；工具入参去掉 cleanup 枚举。

## 1. 背景与问题

### 1.1 「上报成功」判定失真（本次核心）

当前 `_GROUP_OK = (40001, 40002, 40003, 40004, 40006, 10009, 10013)`——把 **WL-40001 等待入库申请 / WL-40002 入库处理中** 当成功终点。这是 v1.0.24 时的简化（入库申请是人行平台人工环节，代码等不到）。

后果：人行侧**入库申请被驳回**时，实例在我们台账里已是 confirmed（成功），实际根本没入库。语义断链引发连锁：

- v1.0.27：组 OK 分支全量 confirmed（含失败实例）→ 台账写脏
- v1.0.28：脏台账导致 8 模型 diff 归零 → 无上报 → success/数量 0/无回执码/无错误信息（现场实报）
- 失败明细漏捕 / 落库后被 clear 误删（已在 v1.0.28 修，但根治依赖状态闭环）

### 1.2 清理功能现状问题

- `cleanup` 是独立工具操作（工具入参 action 枚举含 `report/rollback/cleanup`），依赖人工触发，实际没人跑 → 任务/明细无限堆积
- 只删任务记录 + dataFile + 回滚记录，**不删 FINTECH_REPORT_INSTANCE 失败明细** → 明细孤儿残留
- 清理删掉 diff 基准依赖的 success 任务 dataFile → `_last_success_data` 基准归零 → 下次全量重报 → 「数据已存在」风暴（潜伏 bug）

## 2. 目标

1. **状态闭环**：批次组生命周期完整结算——40001/40002 改判「在途」，40003/40004/40006 才是入库终态成功，40005/40007 失败；在途组每次运行开头结算，落终态后实例才 confirmed
2. **单次上报生命周期不变**：一次运行 = 上报 + 短轮询 + 组检核 + 结算已终态的在途组；**不等待**人工环节（40001/40002 在途返回，不阻塞）
3. **清理内联**：上报完成后自动执行清理（规则仍由 FINTECH_REPORT_CLEANUP 控制，默认不清理）；级联删除失败明细；工具入参去掉 `cleanup` 枚举
4. 放弃实例级状态记录（用户决策），台账仍为 dataFile 内 `_confirmed` 标记

## 3. 状态闭环设计

### 3.1 组状态码重分类

```
_GROUP_PENDING   = (WL-40000, WL-10005, WL-10006)          # 检核中（不变）
_GROUP_INFLIGHT  = (WL-40001, WL-40002)                     # 新增：入库申请/入库中——在途
_GROUP_STORED    = (WL-40003, WL-40004, WL-40006, WL-10009, WL-10013)  # 入库终态成功
_GROUP_FAIL      = (WL-40005, WL-40007)                     # 入库终态失败（40007 组ID不存在）
```

- `group_status(wait_terminal=True)` 的终止条件改为 `code not in PENDING ∪ INFLIGHT`——即 40001/40002 也继续轮询？**否**。单次生命周期不变：轮询到 PENDING ∪ INFLIGHT 之外才返回，但 40001/40002 到达后**只再轮询至组到终态或超时**（GROUP_POLL_MAX 不变）……
  **修正**（简化，符合"不死等"）：`wait_terminal=True` 遇 INFLIGHT 立即返回（与现行对 40001 的行为一致，只是语义从「成功」变「在途」）。等待人工的环节永远不进入轮询。
- 语义：任务收到 40001/40002 → status=`inFlight`（新值）；40003/40004/40006 → confirmed 结算；40005/40007 → fail 结算 + 行级明细补拉。

### 3.2 新任务状态 `inFlight`

`FINTECH_REPORT_TASK.status` 增加枚举值 `inFlight`（介于 pendingCheck 与 success 之间）：

| status | 含义 | 进入条件 | 后续 |
|---|---|---|---|
| reporting | 运行中 | 本次上报开始 | — |
| pendingCheck | 检核未出结果 | 批次轮询超时 / 组仍在 40000 | 下次运行续查 |
| **inFlight** | 检核通过、入库申请中（人行人工） | 组到 40001/40002 | 下次运行结算 |
| success | 入库终态成功 | 组 40003/40004/40006 或批次 10009/10013 | 终态 |
| partialSuccess | 入库终态成功但有行级失败 | 同上 + fail_details 非空 | 终态 |
| fail | 终态失败 | 组 40005/40007 或全批失败 | 可 rollback 重报 |
| noReport | 无上报项 | diff 归零 | — |

- `_resync_pending_group` 扩展为 `_settle_inflight_groups`：扫 `status ∈ (pendingCheck, inFlight)` 且带 groupId 的任务，查组现状一次（不轮询）：
  - 组到 STORED → 实例 confirmed、任务 success/partialSuccess
  - 组到 FAIL → 任务 fail、行级明细补拉（`_collect_branch_row_fails`）
  - 组仍在 PENDING/INFLIGHT → 保持不动，本次正常增量上报（**在途实例冻结**：不重发——见 3.3）
- `_last_success_data` 的 statuses 查询从 `(success, partialSuccess)` 扩为 `(success, partialSuccess, inFlight)`——在途实例视为"人行已收"（检核已过），diff 跳过；但 inFlight 原文的 `_confirmed` 仍为 False，若最终结算失败，实例自然回到 new 重报。
  **修正**：这样 inFlight 任务的实例既不重发（当成功用）也不标 confirmed（当未成功用）——正是「冻结」语义。结算成功时由 settle 把 `_confirmed` 置 True 落盘。

### 3.3 在途冻结

diff 时若实例出现在任何 inFlight 任务的原文中 → 本次跳过（不发 new/update），防止入库申请期间重复报送制造「数据已存在」。实现：`_last_success_data` 返回值增加 `inflight_descs` 集合，diff 循环跳过其中的 desc（CMDB 实例被删除的也不生成 delete 行——人行库里行还没落地，不能删）。

### 3.4 单次运行流程（整合后）

```
cmd_report:
  for rule in rules:
    settle_inflight_groups(objectId)      # 0) 结算在途组（一次现状查询/组）
    diff（冻结在途实例）
    上报 → 批次短轮询 → requestCheck → group_status（遇 INFLIGHT 立即返回）
    组 STORED → confirmed + 行级补拉
    组 FAIL  → fail + 行级补拉
    组 INFLIGHT → 任务 inFlight
    组 PENDING 超时 → pendingCheck
  cleanup_after_report()                  # 新增：上报完成后统一清理（见 §4）
```

### 3.5 驳回语义

规范无独立「驳回」码。若人行驳回映射到 40005 → 结算 fail，行级补拉拿到失败原因，用户在任务表/明细表可见；若人行驳回后组状态停在 40001 永不变化 → 任务永久 inFlight（可人工 rollback 触发重报）。首次现场部署后验证一次（拿被驳回的 groupId 查 getGroupStatus），结论补进本文档 §7。

## 4. 清理内联设计

### 4.1 触发时机

`cmd_report` 所有模型跑完（含失败）后调用 `cleanup_after_report()`；独立 `cmd_cleanup`（CLI 子命令）保留，dryRun 仍可用（工具入参去掉的是枚举入口，不是函数）。

### 4.2 清理范围（新增级联）

现行：任务记录 + dataFile + 回滚记录。新增：

- **失败明细级联**：按被删任务的 `taskId` 删 `FINTECH_REPORT_INSTANCE` 明细行（明细表 detailId 含 desc+branch，不含 taskId 键——按 `taskId` 字段 v2 查询后批量删）
- **diff 基准保护**：被删任务若是某模型「最近一条 success 任务」→ 跳过删除（保基准）；只有存在更新的 success 任务（更新的基准）时才允许删。全清模式（maxCount=maxAge=0）加同样保护：每模型至少保留最近一条 success。

### 4.3 工具入参变更（config）

`action` 枚举：`["report", "rollback", "cleanup"]` → `["report", "rollback"]`；memo 同步改。`dryRun` 入参删除（cleanup 已无入口；保留 CLI `--dry-run`）。script 的 main 分支同步收窄。

### 4.4 输出参数（outputDefs）

保留 `cleanedCount`（每次上报都会输出，语义变为「本次级联清理数」）。

## 5. 修改文件清单

| 文件 | 改动 |
|---|---|
| `apps/fintech-report/fintech_report.py` | §3 组码重分类 + `_settle_inflight_groups` + inFlight 状态 + 冻结 + §4 清理内联/级联/保护 + CLI 收窄 |
| `.local/tool-pkg/人行金融数据上报/script` | 同步以上（py2 语法） |
| `.local/tool-pkg/人行金融数据上报/config` | action 枚举去 cleanup、dryRun 删除 |
| `fintech_report_tool-1.0.29-*.tar.gz` | 新包替换 1.0.28 |

## 6. 验证

1. **单测**：组码分类（40001→inFlight、40003→stored、40005→fail）；settle 三分支；冻结跳过；清理级联与基准保护
2. **端到端 mock**：上报→40001→(下次运行)settle→40003→confirmed；驳回路径 40005→fail+明细；清理删任务+明细且保基准
3. **回归**：v1.0.28 已修的行为不破（20003 msg 判别、组 OK 行级补拉、clear 防误删）
4. py3/py2 双份代码全过 + tarball 解包 diff

## 7. 待现场验证

- 驳回在 getGroupStatus 的实际返回码（拿到真实驳回 groupId 后补记）
- 40001→40003 的实际时长（决定 settle 查询是否需要退避——初版不加，每次运行查一次开销可忽略）
