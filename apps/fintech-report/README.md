# fintech-report — 人行金融科技信息报送

把 EasyOps CMDB 的 `@FINTECHDATA` 实例按人行口径转换后通过 HTTP 推送到 FICS 报送中心。**单文件可执行、零外挂配置、纯标准库**；元数据与历史全部存 CMDB。

当前版本 **v1.0.35**（工具包 tarball：`人行金融数据上报/script`，py2/py3 兼容；本地开发版：`fintech_report.py`）。由 `fintech_data` Go 微服务迁移而来，并在 py 版上完成状态闭环、双基准防重、失败明细等演进。

## 两种模式（工具入参 action）

| action | 能力 |
|---|---|
| `report` | 增量上报：结算在途组 → diff → 上报 → 检核 → 任务落库；**完成后自动按清理规则收尾清理** |
| `cleanup` | 不上报，只按清理规则清理历史（任务+原文 json+失败明细级联） |

入参 `scope` 选模型实例（CMDB_MODEL），留空 = 全部启用规则。

```bash
# 工具平台: action=report, scope 留空
# 本地 CLI（开发版等价能力）:
python3 fintech_report.py report                                   # 全部启用规则
python3 fintech_report.py report --scope "switches@FINTECHDATA"    # 指定模型
python3 fintech_report.py cleanup [--dry-run]                      # 独立清理 / 只预览
python3 fintech_report.py rollback --task <taskId>                 # 回滚（代码保留，工具入口已去除）
```

> 全量上报模式（--full）已移除；无成功台账（首次接入/全部回滚后）自动全量 new。

## 任务状态生命周期（状态闭环 v1.0.29+）

```
reporting ──► pendingCheck ──► inFlight ──► success / partialSuccess
                (检核中)      (40001等人工入库)    │
                                                   └──► fail (组终态失败/驳回)
noReport（无上报项）   rolledBack（人工回滚）
```

- **单次运行不等待人工**：组到 WL-40001/40002（等待入库申请/入库中）立即返回，任务标 `inFlight`
- **下次运行开头结算**（`_settle_inflight_groups`）：查组现状一次——
  - 40003/40004/40006 入库成功 → 实例 confirmed、任务 success/partialSuccess
  - 40005/40007 终态失败 → 任务 fail + 行级明细补拉
  - 仍在途 → 保持 inFlight，实例冻结
- 组状态分类：`_GROUP_PENDING`(40000) / `_GROUP_INFLIGHT`(40001,40002) / `_GROUP_STORED`(40003,40004,40006) / `_GROUP_FAIL`(40005,40007)

## 增量 diff：三道比对基准

```
CMDB 现值 vs ┬─ confirmed 台账（人行确认入库过）     → 未变不报；变了 update；CMDB 删了 delete
             ├─ alreadyExists 基准（人行声明"已存在"） → 数据未变跳过（重报必撞）；变了恢复上报
             └─ inflight_map（在途实例+冻结时hash）   → 原样重发冻结；变了就报（v1.0.33）
```

- **变了就报**：在途期间实例内容变更 → hash 失配 → 不冻结，照常 new/update
- **删除覆盖在途**（v1.0.35）：inFlight 实例被 CMDB 删除也发 delete（从在途原文快照取字段）——组后续入库则生效，未入库则失败明细暴露、结算后重删（幂等兜底）
- 台账来源：扫 success/partialSuccess/inFlight 任务原文 dataFile 的实例级 `_confirmed` 标记（跨任务合并，新覆盖旧）；settle 回写直达原路径（v1.0.34，不产生孤儿 json）

## 失败明细（FINTECH_REPORT_INSTANCE）

行级失败逐条落库：detailId=`<facilityDescriptor>_<branchId尾>`，含错误码/msg/批次/任务号。捕获时机：

1. 批次轮询期间 data[] 里的终态失败行
2. 组到 40001/40003 时行级补拉（`_collect_branch_row_fails`，同实例跨批去重）——组 OK ≠ 行级全过，检核慢的行级失败码在批次轮询超时后才出现
3. settle 结算时补拉（含组失败路径）

**WL-20003 双义处理**（人行现场用它返回"数据已存在"）：按 msg 判别——含"失败/不可重复/已存在"按失败计（进明细），否则按规范"成功带警告"计。失败明细随实例重报成功自动清除（按 objectId+descriptor）。

## 清理（FINTECH_REPORT_CLEANUP 规则控制，默认不清理）

- 触发：report 完成后自动 + action=cleanup 独立执行
- 删除内容：任务记录 + dataFile 原文 json + **级联失败明细**（按 taskId）+ 回滚记录
- 规则语义：maxCount/maxAgeDays **双正数 = AND**（同时超出条数和天数才清）；**双 0 = 全清**；任一为 0 跳过（防半配置误删）
- 两个保护（全清模式同样生效）：
  - **基准保护**：每模型最新 success/partialSuccess 任务永不删（diff 基准来源）
  - **活动保护**：pendingCheck/inFlight 任务不删（组还可能结算）

## 转换器（对齐 Go report_rule.Converter + py 版增强）

- **枚举**：type=enum 时 `00-设施在用`→`00`（按 `-`/`:`/`：` 截断）；多选逐项转换逗号连接；type=str 原样（**字段类型定义在 FINTECH_REPORT_OBJ 的 objectDefine 里**，现场改枚举要改这里，改 CMDB 模型库无效）
- **FIELD_BLACKLIST**：`importId` 等 CMDB 系统字段强制剔除（tag 过滤失效时兜底，防"属性数量过多"拒收）
- **bool/float/date/struct/omitempty/空值/PK翻译**：与 Go 版一致（详见代码注释）

## CMDB 模型（全部数据载体）

| 模型 | 角色 |
|---|---|
| `FINTECH_REPORT_CONFIG@EASYOPS` | 全局连接（clientId/Secret/ip/port/facilityOwnerAgency） |
| `FINTECH_REPORT_OBJ@EASYOPS` | 上报规则（objectId/enable/batchNum/objectDefine/mappingRule）——**objectDefine 是转换字段的类型来源** |
| `FINTECH_REPORT_TASK@EASYOPS` | 任务历史（status 含 inFlight 枚举/branchId/统计/checkCode/dataFile/rolledBack） |
| `FINTECH_REPORT_INSTANCE@EASYOPS` | 失败明细（detailId/objectId/descriptor/code/msg/branchId/taskId） |
| `FINTECH_REPORT_ROLLBACK@EASYOPS` | 回滚记录 |
| `FINTECH_REPORT_CLEANUP@EASYOPS` | 清理规则（name/enabled/scope/maxCount/maxAgeDays） |

无 Mongo/SQLite/外挂配置。原文落 `DATA_DIR/<日期>/<taskId>.json`（settle 回写直达原路径）；工具版 DATA_DIR 优先级：`FTECH_DATA_DIR` 环境变量 → agent `/data` → easyops 目录 → `/tmp`。

## 人行接口链（report_center）

受理 `reportData` → 轮询批次 `selectUploadData`（5×10s）→ 检核请求 `requestCheck` → 组状态 `getGroupStatus`（遇 INFLIGHT 立即返回）。OAuth client_credentials + gzip+base64 + X-Access-Token；zhongxin 变体代码保留未启用。组轮询行级补拉用 `check_result_once`（单次不轮询）。

## 已知边界

- 人行侧组停在 40001 期间任务持续 inFlight——入库申请是人行平台人工环节，工具不等待，靠下次运行结算
- settle 结算晚于本地删除时，实例会先确认进台账再幂等删一次（delete 幂等，多一轮请求）
- 引用字段值为纯名称（无 32 位标识符）时无法转换，失败明细如实记录（需源数据治理）
- 触发由外部集成负责（不内置定时）；工具超时 3600s
