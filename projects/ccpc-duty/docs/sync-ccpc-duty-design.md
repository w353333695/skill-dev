# 同步CCPC值班表 设计文档

- 日期：2026-09-15
- 作者：wwh（设计澄清）+ Claude
- 状态：已批准

## 需求

开发 EasyOps autoops 定时工具：把 CCPC 的值班表同步到 EasyOps ITSM 值班组（日历配置）。

**入参**（平台注入变量，同 alert2ticket 模式）：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| ccpc_ip | string | 127.0.0.1 | CCPC 地址（端口固定 8880） |
| ccpc_group_id | string | 8882eec490c54bacb382c5e859f20f05 | CCPC 值班组 id |
| duty_group_name | string | 告警值班组 | EasyOps 侧值班组名称 |
| sync_days | int | 30 | 同步今天起 N 天 |

## 澄清结论

- 账号映射：CCPC uids 与 easyops username **一致，直接用**
- 运行形态：**autoops 定时工具**（agent py2 / 编排侧 py3，单文件自包含）
- 幂等：**upsert** —— 该日已有配置且人员一致→跳过；不一致→PUT 更新；无→POST 新建
- dutyCycle：**未来一百年**（`{今年}-01~{今年+100}-12`），首次建组用；已存在且新范围超出旧周期才更新
- 班次：**动态分析**，不写死白/夜班；发现班次定义变更 → 自动 PUT 更新 dutyShift（值班人配置不受影响）
- 角色映射：`dutys`(值班人员)→`users`；`maintainer`(技术值班)+`leader`(带班主任)→`leader`
- 起始日期：今天起 N 天（滚动同步）

## 数据源契约

### CCPC 拉取

`GET http://{ccpc_ip}:8880/api/dutys/schedule/public?groupId={ccpc_group_id}&startDate={YYYY-MM-DD}&endDate={YYYY-MM-DD}`

响应体（样例 `tmp/ccpc-dutys.txt`）：每日一条，`shifts[]` 每班含 `shiftName/startTime/endTime` 与 `members[]`（`field`: dutys/maintainer/leader，`uids[]`）。

### EasyOps duty_group_config（本轮从源码挖出，onboarding 沉淀进 platforms）

| 端点（8134 flowable_service） | 契约 |
|---|---|
| `POST /v2/duty_group_config/search` | `{groupName|groupId, date}`；date 支持 YYYY / YYYY-MM / YYYY-MM-DD；**组必须按 name/instanceId 恰好命中 1 个，否则 500 "查询值班日历信息失败"**（SearchDutyGroupConfig 内 QueryDutyGroup total!=1 即报错）；dutyCycle 结束月 < 查询月 → 返回空 list |
| `POST /v1/duty_group_config` | `{groupId, date, status:int, dutyShiftConf:[{name, users[], leader[]}]}`（validator 仅强校验 groupId/date/status；dutyShiftConf 按需）；创建后后端自动 SyncDutyDays 同步值班数据；config 名 = `groupId_date` |
| `PUT /v1/duty_group_config/{configId}` | 更新当日配置；若原配置 date ≠ 请求 date，后端自动转新建 |

duty_group CRUD 已在 platforms（`easyops-itsm.yaml` duty_group 资源），无需补。

`status`(int) 语义（疑似 0=工作日配置）：端到端实测校准，默认 0。

## 工具流程

```
1. 拉 CCPC（今天起 N 天）
2. 动态班次分析：扫全量 shifts[]，按 shiftName 归纳 {name → startTime~endTime}
   （同名不同时段以最新出现为准；跨天班次 endTime < startTime 保持原样拼接）
3. ensure 值班组：
   GET /v1/duty_group?name={duty_group_name}
   ├─ 无 → POST /v1/duty_group {name, dutyCycle: 未来一百年, status:enabled, dutyShift: 归纳班次}
   └─ 有 → 对比 dutyShift（名称+时段集合）；不一致 → PUT /v1/duty_group/{groupId} 更新 dutyShift（保留原 dutyCycle/name）
4. 逐日 upsert（date = 今天..今天+N-1）：
   POST /v2/duty_group_config/search {groupName, date}
   ├─ 有该日配置：人员一致 → skip；不一致 → PUT /v1/duty_group_config/{configId} {configId, date, status, dutyShiftConf}
   └─ 无 → POST /v1/duty_group_config {groupId, date, status:0, dutyShiftConf}
   dutyShiftConf = CCPC 当日 shifts 顺序映射：[{name: shiftName, users: dutys.uids, leader: maintainer.uids + leader.uids}]
5. 输出 PutStr 统计：created/updated/skipped/failed + 失败明细
```

## 错误处理

- CCPC 不可达/非 200：直接退出非 0，报错清晰（agent 可见）
- 单日 upsert 失败：记录，继续后续日期（不让一天失败拖垮整轮）
- easyops 响应 code≠0：抛出 code+error 文本
- CCPC 某日无数据：跳过该日（不删已有配置）

## 测试策略

- **fixture 模式**：脚本内置 `--fixture <file>`，CCPC 拉取层可替换为读 `tmp/ccpc-dutys.txt` 样例（当前 CCPC 不可达，开发/回归都靠它）
- **单元**（py3 本机跑）：班次归纳、角色映射、日期序列、upsert 决策（mock http 层）
- **端到端**（.26 真环境）：建组→同步→验证 v2 search 结果→模拟 CCPC 换班再同步→验证 upsert/班次自动更新→清理测试组

## 交付物

1. platforms 沉淀：`easyops-itsm.yaml` 补 duty_group_config 资源（v2 search/create/update）+ `objects.yaml` 补 itsm_duty_group_config 对象 + lint 0 ERR
2. 工具脚本：`hub/scripts/tools/sync_ccpc_duty.py`（py2/3 兼容、自包含）
3. 注册 autoops 工具 + 导出 `同步CCPC值班表.tool.tar.gz`
4. hub INDEX.yaml 回流登记 + commit

## 明确不做（YAGNI）

- 不做 CCPC→easyops 账号映射表（已确认同名直用）
- 不做值班组删除/禁用
- 不做多 CCPC 组批量同步（一次一个组）
- 不做同步范围外的历史数据回填
