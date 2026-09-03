# 方案：多模型上报与任务记录重构（v1.0.21）

## 一、1.0.20 日志问题定位（调研结论）

### P0-1 增量台账跨模型污染 → delete 大爆炸（根因实锤）
`cmdb_search_all` 用 v3 `retrieve.expression` 过滤 FINTECH_TASK，**实测该 CMDB 的 v3 expression 完全不生效**
（不可能命中的 expr 也返回全部 11 条）→ 每个模型读到了所有模型的历史任务 →
别的模型 confirmed key 全被本模型判 delete（shieldedCabinet 9 行 → delete 114；
累计 delete 3113）→ 大量伪 delete 上报 → 人行对 delete 行报
"facilityOwnershipAgency归属机构不能为空"（37 个 delete 批次 ↔ 37 条该错误，完全对应）。
**修复**：任务/台账查询改 v2 `_search` 的 `query`（实测 `$and` + 精确值过滤正确命中 9 条）。

### P0-2 delete 行字段不足
Go 版正常路径 `convertDeleteData` 从历史快照读**完整实例数据**做 delete 行；
`RecoverReportInst`（仅两键）只是快照读失败的兜底。我们只实现了兜底形态。
**修复**：delete 行从该实例上次成功上报的 dataFile 快照取完整字段（含 agency），
快照缺失才退两键。

### P1-3 数据转换遗留
- `facilityUpdateDate` 空 13 模型约 1000 行（CMDB 无值）：按 Go 语义空值传 `""`，
  但人行"属性值不能为空"校验拒绝 → 需要兜底"今天"（同 utime 逻辑）
- 个别 struct 里 date 截断问题已修，剩余是数据面问题

## 二、多模型上报逻辑（回答 4 个问题）

### Q1 按模型上报是否合理？
**合理，保持**。理由：
- 人行接口按 dataType（数据元类型）分批，跨模型混批不被接受
- Go 版同样每模型独立任务（CreateTask × N）
- 依赖顺序要求模型间有先后（dataCenter 先于 spacing/设备）

### Q2 批次号多个 → 记录结构升级
现状 branchId 逗号拼接字符串。重构为：
- FINTECH_REPORT_TASK 增加 `branchList`（json 数组：`[{branchId, type, count, status, code, msg}]`）
- 保留 branchId 拼接（兼容）

### Q3 失败数累计 → 计数作用域修正
现状日志里 fail 累计是**多模型叠加**显示（日志排版问题+计数跨流污染观感）。
重构：计数严格 per-task（已是局部变量，修日志输出），汇总行只报本模型。

### Q4 错误信息只有 fail 数 → 失败明细落库
人行两个查询接口都能给到**单条数据的失败原因**：
- `selectUploadData`（批次）→ `data[]: {facilityCategory, facilityDescriptor, code, msg}`
- `getGroupStatus`（批次组）→ `data[]: {branchId, code, msg}`（异常批次）
重构记录链：
1. 新模型 `FINTECH_REPORT_INSTANCE@EASYOPS`（失败明细表）：
   `taskId / objectId / facilityDescriptor / facilityCategory / dataType / code / msg / createTime`
   每个 失败数据 一行（可从 descriptor 反查 CMDB 实例）
2. 任务表 `errorMsg` 改存前 N 条错误摘要 + 失败计数；完整明细查失败明细表
3. `getGroupStatus` 的异常批次逐个再查 `selectUploadData` 拿数据级原因

## 三、实施清单（一次提交）

| # | 项 | 改动 |
|---|---|---|
| T1 | 任务查询 v2 query | `cmdb_search_task(expr)` 新函数，`_last_success_data`/rollback/cleanup 全部改用 |
| T2 | delete 行完整字段 | `_last_success_snapshot(desc)` 从历史 dataFile 取该实例完整数据；缺失退两键 |
| T3 | facilityUpdateDate 空 | 转换层空值兜底"当天"（仅该字段，对齐 Go 语义人行要求） |
| T4 | branchList 记录 | 任务模型加 json 字段；每批次 append {branchId,type,count,status,code,msg} |
| T5 | 失败明细模型 | 建 FINTECH_REPORT_INSTANCE；check/group 拿到 data[] 逐条落库 |
| T6 | 错误摘要 | errorMsg = "fail N: 前3条 descriptor→msg"；日志同步人类可读 |

自检：T1 用不可能 expr 验证过滤生效；T2 构造带快照 delete 验证全字段；
T5 mock 检核响应验证明细行数与字段。
