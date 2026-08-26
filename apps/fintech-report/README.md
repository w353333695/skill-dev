# fintech-report — 人行金融科技信息报送（单文件）

把 EasyOps CMDB 的 `@FINTECHDATA` 实例按人行口径转换后通过 HTTP 推送到 FICS 报送中心。**单文件可执行、零外挂配置、纯标准库**；元数据与历史全部存 CMDB。

由 `fintech_data` Go 微服务（178 文件）迁移而来，P0 上报管线 + P1 历史台账能力，剔除微服务形态（gin API / redis 锁 / notify 订阅 / 定时器）。

## 三种能力

| 命令 | 能力 | 对应 Go 模块 |
|---|---|---|
| `report` | 全量/增量上报：拉配置+规则 → CMDB 实例 → 转换（枚举码/bool/精度/omitempty/PK翻译/structs）→ gzip+base64+OAuth → FICS → 任务历史入 CMDB + 原文落磁盘 | report_rule.Converter + report_center.Service + report_task.ReportService + history |
| `rollback` | 仅回滚本地状态：任务标记 `rolledBack`（不动人行侧），下次上报当全量 new 重报 | Go 版无对应（新增，按需求） |
| `cleanup` | 历史清理：按规则（条数 AND 天数同时超出才清）删任务+原文+回滚记录；默认不清理 | Go 版无对应（新增） |

```bash
python3 fintech_report.py report                                  # 全量（所有 enable 规则）
python3 fintech_report.py report --scope "switches@FINTECHDATA"    # 指定模型
python3 fintech_report.py report --full                           # 忽略增量直接全量 new
python3 fintech_report.py rollback --task <taskId>                # 回滚本地状态
python3 fintech_report.py cleanup                                 # 按启用规则清理
python3 fintech_report.py cleanup --dry-run                       # 只列不删
```

## CMDB 模型（全部数据载体）

| 模型 | 角色 | 内容 |
|---|---|---|
| `FINTECH_REPORT_CONFIG@EASYOPS` | 全局配置（复用现有） | clientId/clientSecret/ip/port/facilityOwnerAgency |
| `FINTECH_REPORT_OBJ@EASYOPS` | 上报规则（复用现有） | objectId/crontab/enable/batchNum/source/objectDefine/mappingRule |
| `FINTECH_REPORT_TASK@EASYOPS` | 任务历史（新建，task+branch 合并） | taskId/status/branchId/统计/checkCode/dataFile（原文路径）/rolledBack |
| `FINTECH_REPORT_ROLLBACK@EASYOPS` | 回滚记录（新建） | rollbackId/taskId/status/deleteCount |
| `FINTECH_REPORT_CLEANUP@EASYOPS` | 清理规则（新建） | name/enabled/scope/maxCount/maxAgeDays（AND 语义，默认不启用=不清理） |

**无 Mongo / SQLite / 外挂配置文件**：脚本启动时从 CMDB `FINTECH_REPORT_CONFIG` 拉连接信息、从 `FINTECH_REPORT_OBJ` 拉规则清单；上报数据原文落磁盘（`./fintech-report-data/<日期>/<taskId>.json`），任务记录只存路径。

## 增量上报机制（P1 替代 Go 版台账）

```
report_one_model:
  1. CMDB 拉实例 + Converter 转换（人行口径）
  2. 取该 objectId 最近一次 success 且未回滚的任务 → 读 dataFile 原文
  3. content_hash 对比 → new / update / delete 三类
     · 无历史任务 或 --full → 全部 new
     · 已回滚的任务自动跳过（→下次该模型无基准→全量重报）
  4. 原文落盘（含 hash + 主键类目，下次 diff 基石）
  5. 分批 POST FICS → 查批次结果 → 任务记录入 CMDB
```

回滚 = 把任务标 `rolledBack`（增量基准自动跳过它 → 下次全量重报）；不动人行侧、不删原文（可追溯）。

## 转换器行为（对齐 Go report_rule.Converter）

- **枚举**：`00-设施在用` → `00`；纯码原样；多选 `[00-中国电信, 02-中国移动]` → `00,02`
- **bool**：`True`/`False`
- **float**：默认 2 位（`FLOAT_PREC_RULE` 特例 3 位）
- **date/datetime**：`2021-03-15` / `2021-03-15 10:33:00`
- **struct/structs**：递归转换，空值省略；CMDB struct 存单元素数组自动取首元素
- **omitempty**：`%_operationsManagement` 模糊匹配，为空则整段省略
- **空值**：人行要求传 `""`（复合类型除外）
- **PK 翻译**：`PK_TRANSLATE` 表（如 `application@FINTECHDATA` 的 facilityDescriptor→applySystemIdentifiers）

## 配置区（脚本顶部，仅环境连接 + 内嵌策略）

```python
CMDB_API = {...}            # base_url/org/user/timeout
DATA_DIR = "./fintech-report-data"
DEBUG = False
PK_TRANSLATE = {...}       # 内嵌（行数少，对应 Go conf.default.yaml）
IGNORE_INST_ATTR / IGNORE_ATTR_CATEGORY / OMITEMPTY_FIELDS / FLOAT_PREC_RULE
```

业务配置（clientId/ip/机构号/规则清单）**全部从 CMDB 拉**，脚本内只存“人行口径策略”（PK 翻译/忽略规则/精度）——这些是 Go 版 conf.default.yaml 里就 10 行的内嵌策略，不值得外挂。

## 上报中心（report_center）

- **默认 variant=pboc**：OAuth client_credentials 取 token（缓存到过期前 10s）+ gzip+base64 + `X-Access-Token`
- 端点（agollo 默认值）：`webproxy/fig2fics/conn/.../reportData` / `/requestCheck` / `/selectUploadData`
- **zhongxin 变体**：免 token，`itsm/httpclient/reportData.action`，状态码 `1`/`0`

切换 variant 改 `cmd_report` 里 `variant` 参数（当前硬编码 pboc，行数少可按需）。

## 验证记录

- 转换器单元测试：枚举/bool/float/int/enums/struct/structs/date/omitempty/PK翻译 全对齐 Go
- 真实链路：CMDB 407 台交换机 → 转换 → 原文落盘（407 实例，663KB）→ 人行侧 127.0.0.1 不可达时任务记录正确标 fail
- rollback：任务标 `rolledBack` + 回滚记录入库（deleteCount=实例数）
- cleanup AND 语义：只超量未超龄 → 0 清理；同时超量超龄 → 清理候选正确

## 已知边界

- 人行侧地址需可达；当前用测试配置指向 127.0.0.1，正式环境改 `FINTECH_REPORT_CONFIG` 实例的 ip/port 即可
- `FINTECH_REPORT_OBJ.source` 合法值 `direct`（自身模型直读）/`mapping`（映射模型，配 mappingRule）
- 触发由外部集成方案负责（本脚本不内置定时）
