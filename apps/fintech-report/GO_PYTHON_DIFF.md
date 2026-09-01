# Go(fintech_data) ↔ Python(fintech_report) 全链路逐项比对清单

> 生成方式：完整通读 Go 版 `internal/report_rule/rule.go`、`internal/report_task/task.go`、
> `internal/report_task/report_check.go`、`internal/report_instance/service.go`、
> `internal/fill_instance/*.go`、`internal/report_center/types.go`，与 Python 版逐函数比对。
> 置信度标记：高=源码直读可证 / 中=源码间接推断 / 低=需运行时验证。

---

## 一、报文协议层（决定上报是否被受理）

| # | 项 | Go 行为 | Python 行为 | 结论 | 置信度 |
|---|---|---|---|---|---|
| 1 | 外层 `dataType` | `getReportDataType(objectId)` = 模型名去 `@命名空间`（`dataCenter`/`switches`…） | v1.0.15b 已改 `_data_type()` | ✅ 已对齐 | 高 |
| 2 | 行内 `reportDataType` | `genReportData` 写入 `ReportType`（`new`/`update`/`delete`） | v1.0.13 已加 | ✅ 已对齐 | 高 |
| 3 | 报文 gzip 压缩 | `json.Marshal`（中文转义）→ gzip → base64 StdEncoding | 同款（已改 Go 风格 ascii 转义） | ✅ 已对齐 | 高 |
| 4 | 批次号 | 响应 `resp.BranchId`（人行真批次号 BA 系列）回填 branch | v1.0.12 已改 | ✅ 已对齐 | 高 |
| 5 | 信封 `facilityOwnerAgency` | CONFIG 的 `facilityOwnerAgency`，空则 agollo 兜底 | `_agency()` CONFIG 唯一来源，空报错 | ✅ 已对齐（语义略严） | 高 |

## 二、字段转换层（决定数据正确性）

| # | 项 | Go 行为 | Python 行为 | 结论 | 置信度 |
|---|---|---|---|---|---|
| 6 | 枚举 `enum` | `00-在用`→`00`（前缀 `-`/`:`/`：` 任一命中截断） | `_enum_code` 同款三分隔符 | ✅ 对齐 | 高 |
| 7 | 多选 `enums` | 逐项 enum 转换后逗号连接，空项跳过 | 同款 | ✅ 对齐 | 高 |
| 8 | 布尔 `bool` | `True`→`"True"`、`False`→`"False"` | 同款 | ✅ 对齐 | 高 |
| 9 | 整型 `int` | `FormatFloat(f,0,64)` 转整数字符串 | `str(int())` | ✅ 对齐 | 高 |
| 10 | 浮点 `float` | 默认 2 位精度，`floatPrecRule` 可覆盖 | 同款 `_prec` | ✅ 对齐 | 高 |
| 11 | 日期 `date` | 原样返回 | `str(value)[:10]` | ⚠️ **差异**（见下） | 中 |
| 12 | 时间 `datetime` | **去掉秒**：`"2021-03-15 10:33:00"`→`"2021-03-15 10:33"` | `str[:19]` **保留秒** | ❌ **未对齐** | 高 |
| 13 | 非复合空值 | 统一 `emptyStr ""` | `out[aid]=""` | ✅ 对齐 | 高 |
| 14 | `struct` 空值 | **生成全空子字段对象** `{sub1:"",sub2:""…}` | **直接跳过整个字段** | ❌ **未对齐** | 高 |
| 15 | `structs` 空值 | **生成单元素数组** `[{sub1:"",sub2:""…}]` | **直接跳过整个字段** | ❌ **未对齐** | 高 |
| 16 | `struct` 子字段空值 | 空→`""`（struct/structs 子类型除外） | `_struct_obj` 空→`""`、子复合跳过 | ✅ 基本对齐 | 中 |
| 17 | `RecoverValueChange` | 对 selfEffectedIds 字段做 `xxx[32位hex]`→`32位hex` 还原 | **无此逻辑** | ❌ **缺失** | 高 |
| 18 | 编码翻译（nationalArea 等） | 无（Go 靠 instance_rules 预填编码） | v1.0.14 加硬编码表 | ⚠️ 语义不同（见三） | 中 |

## 三、字段填充层（Go 有、Python 完全没有 —— 最大遗漏）

| # | 项 | Go 行为 | Python 行为 | 结论 | 置信度 |
|---|---|---|---|---|---|
| 19 | **instance_rules** | `instance_fill.rules.yaml` 用 JSONPath 从实例取字段，按 case 条件推导填充（如 fireProtection 的 `facilityCategory` 由多个子系统组合推导 `FAXFBJS000` 等） | **完全缺失**，直接用 CMDB 存的值 | ❌ **缺失** | 高 |
| 20 | **relation_rules** | `relation_fill.rules.yaml` 把关系字段（如 `dataCenterSpacing.localDb`）经关联对象映射到 `facilityDescriptor`（名称→hex 转换） | **完全缺失**，直接用 CMDB 值 | ❌ **缺失** | 高 |
| 21 | selfEffectedIds | relation fill 会改的字段集合，转换时做 RecoverValueChange | 无 | ❌ 缺失（同 #17） | 高 |

## 四、流程层

| # | 项 | Go 行为 | Python 行为 | 结论 | 置信度 |
|---|---|---|---|---|---|
| 22 | 增量采集 | `_ts` 时间窗（LastReportTime~StartTime）+ 删除事件查询 + 归档事件 | confirmed 台账 hash diff | ⚠️ 语义等价但实现不同 | 中 |
| 23 | 检核状态机 | WL-10005/06→处理中轮询；10009/10013→成功；10007/10008/10004→失败/部分 | 同款（v1.0.12 起） | ✅ 对齐 | 高 |
| 24 | 单条判定 | WL-20000/20003 成功；20001/20002 失败 | 同款 | ✅ 对齐 | 高 |
| 25 | **Audit 审核流程** | `autoRequestCheck=true` 时上报成功后 POST `requestCheck`（gzip branchIdList）→ 得 groupId（G 系列批次组） | **完全缺失**，只查 selectUploadData | ❌ **缺失** | 高 |
| 26 | **重试机制** | `searchRetryInstance` 拉上次任务 `retryable=true` 的失败实例重报 | 无（confirmed 台账天然让未确认实例下次当 new 重报） | ⚠️ 已变相覆盖 | 中 |
| 27 | 任务状态机 | initial→reporting→pendingCheck→resulting→success/fail/partialSuccess/warn | 简化版（reporting/pendingCheck/success/fail/partialSuccess/noReport） | ⚠️ 简化（缺 resulting/warn 中间态） | 中 |

## 五、已确认一致项（无遗漏）

- `PK_TRANSLATE` 7 模型唯一键翻译 ✅
- `ignoreReport` 实例级过滤 + tag 分类忽略 ✅
- `omitempty`（`%_operationsManagement`）✅
- 机构号 14 位格式、枚举码值域（靠校验规则表而非代码）✅
- 检核轮询间隔/超时（Go 靠 check_job 定时器，Python 同步轮询 5×10s）⚠️ 实现不同但语义一致

---

## 结论汇总

### 已发现并修复（本轮之前）
1. 外层 dataType 用错（v1.0.15b）— **正是 50011/传输标识错误的根因**
2. 行内 reportDataType 缺失（v1.0.13）
3. 批次号用人行真号（v1.0.12）
4. nationalArea/administrativeArea 编码（v1.0.14）— 真实规则但非根因

### 未对齐遗漏（按影响排序，需修）
| 优先级 | 项 | 影响 |
|---|---|---|
| **P0** | #14/15 struct/structs 空值→全空结构 | 其他模型有空 struct 时整字段缺失，完整性校验挂 |
| **P0** | #19 instance_rules 字段推导 | facilityCategory 等推导字段，CMDB 未预填时送空 |
| **P1** | #12 datetime 去秒 | 含 datetime 字段的模型格式不符 |
| **P1** | #25 Audit 审核流程 | autoRequestCheck 开启时缺审核环节 |
| **P2** | #20 relation_rules / #17 RecoverValueChange | relation 类模型名称→hex 映射，CMDB 已存 hex 则影响小 |
| **P2** | #11 date [:10] 截断 | CMDB 存纯日期则等价，存带时间则差异 |

### 当前 dataCenter 上报失败的真因判断
v1.0.14 日志仍报"传输标识错误"且 19/19 全挂 → **外层 dataType 仍是 `new`（v1.0.14 未含此修复，v1.0.15b 才修）**。用 v1.0.15b 跑应能过协议层进入字段级检核。之后的失败会由 data[] 给出具体字段错误。
