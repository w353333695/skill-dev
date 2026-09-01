# SPEC: fintech-report Go 版未对齐项全量修复

> 依据：`GO_PYTHON_DIFF.md` 审计 + 本轮数据实测修正。目标：一次修复所有**影响上报**的未对齐项。
> 每项含验收自检（与 Go 版行为比对）。

## 范围修正（实测后收敛）

审计清单中 #19 instance_rules / #20 relation_rules 降级为**不修**：
Go 版是实例变更时的旁路持久化填充（写回 CMDB），实测当前 CMDB 数据已是填充后状态
（brandLand 全填、facilityCategory 推导完成、relation 字段已 32 位 hex）。
上报路径只需读现值——无需在 Python 里复刻填充引擎。
11 个模型 brandLand/facilityCategory "空值"经查是**模型定义无此字段**（各有对应 PK 字段），非数据缺失。

## 待修项（按影响排序）

### T1. struct/structs 空值 → 生成全空结构（P0）
- Go `transformStructValue`：值空 → `{sub1:"", sub2:"", ...}`（全子字段空串）
- Go `transformStructs`：值空 → `[{sub1:"", ...}]`（**单元素**数组，非空数组）
- Python 现状：空 → 跳过整个字段
- 修改点：`Converter.convert()` 空值分支 + `_struct_obj`
- **验收**：空 struct 实例转换后字段存在且为全空串 dict；空 structs 为单元素数组。与 Go 行为逐字段一致。

### T2. datetime 去秒（P1）
- Go `transformTimeValue`：`Split(":")` 去掉最后一段 → `"10:33:00"`→`"10:33"`
- Python 现状：`str[:19]` 保留秒
- 修改点：`_transform` datetime 分支
- **验收**：`"2021-03-15 10:33:00"` → `"2021-03-15 10:33"`；`"10:33"`（无秒）→ 原样。

### T3. date 原样透传（P2）
- Go `transformDateValue`：非空原样返回（无 [:10] 截断）
- Python 现状：`str(value)[:10]`
- 修改点：`_transform` date 分支改原样
- **验收**：带时间后缀的 date 值不再被截断（与 Go 一致传原值）。

### T4. RecoverValueChange（P2，防御性）
- Go `transformStringValue`：对 selfEffectedIds 字段做 `name[32hex]`→`32hex` 还原
- Python 现状：无
- 修改点：`_transform` str 分支，对**所有 str 字段**做该正则还原（Go 限定 selfEffectedIds 是因为
  它知道哪些字段被 relation fill 改过；Python 读的是已还原的 CMDB 值，但防御性处理
  `xxx[32hex]` 残留形态更安全——Go 的正则只对特定格式生效，误伤面为零）
- **验收**：`"sha[e4ad...]"` → `"e4ad..."`；普通字符串原样。

### T5. Audit 审核流程（P1，条件性）
- Go `CreateAuditTask`：`autoRequestCheck=true` 时上报成功后 POST requestCheck
  （gzip branchIdList），得 groupId 记入 branch
- 实测当前 **0 个规则开启** autoRequestCheck → 不修引擎，但在 check 轮询拿到
  WL-10004/pendingCheck 时**记录 branchId 列表到任务**（已有），Audit 留 TODO 注释。
- **验收**：代码含注释说明触发条件；当前行为与 Go（autoRequestCheck=false 跳过）一致。

## 不修项（记录原因）

| 项 | 原因 |
|---|---|
| #19 instance_rules | CMDB 数据已填充（实测），Go 在变更时旁路写库，上报只读现值 |
| #20 relation_rules | 同上，localDb/deployDb 等已是 32 位 hex |
| #22 增量采集机制差异 | confirmed 台账语义等价（漏报风险已用 pendingCheck 不确认覆盖） |
| #26 重试机制 | pendingCheck/未确认实例下次当 new 重报，变相覆盖 |
| #27 任务状态机简化 | 不影响上报正确性，只影响展示粒度 |

## 实现顺序

T1→T2→T3→T4 一次提交（都在 Converter），T5 注释随同。
全部完成后：跑比对自检脚本（对 19 条 dataCenter + 抽样模型重建报文，逐字段断言
与 Go 语义一致），通过后打包 v1.0.16 发布。
