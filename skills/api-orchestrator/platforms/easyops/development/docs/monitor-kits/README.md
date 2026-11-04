# 监控套件开发知识

本目录只存监控套件专属知识，例如指标、指标集、监控任务、套件激活、监控结果和监控前端验收。

涉及 ZIP 结构、文件权限、导入失败、版本递增、Hub 成品管理等公共问题，先读取 `../common/README.md` 和其中的公共文档，不在本目录重复维护。

## 告警规则随套件导入

经 `collector_plugin_service` 导入/升级链路及 demo 部署（org=1888，2026-11-04）核对：

- 套件 ZIP 顶层（或导出包保持的套件目录）下的 `alertRule/*.json` 会被 `importOther` 自动读取，经过告警规则校验后写入 CMDB 的告警规则、条件策略和监控目标策略；不需要另行先导入 Excel。
- JSON 是导入时的输入快照。导入后在 CMDB/事件中心修改规则，不会回写原 ZIP；要把平台修改沉淀回包，必须重新导出/读取现规则并更新 `alertRule/*.json` 后再打包。
- 重新导入/升级同一套件时，告警规则按新包重新导入覆盖，不是字段级 merge；因此发布前应完整保留 `alertConditionStrategy`、`cmdbInstanceStrategy`、`objectId`、`priority` 等字段，避免用残缺 JSON 覆盖现有策略。
- `alertRule/*.json` 与配套告警规则模板 `.xlsx` 是两种交付形态：JSON 随套件自动导入，xlsx 用于管理端“事件中心 → 告警规则 → Excel 导入”。两者若同时维护，必须以同一 `objectId` 和 `multiConditions` 为真源，避免阈值漂移。

### 本次核对与打包

当前 Hub 中的物理服务器 Redfish 包已含 `alertRule/【物理服务器】通用告警.json`；在现网套件详情中 `alertRules` 仍为空，说明该规则尚未随包导入现网，不能把离线包内容当成远端已生效状态。

本次已将 Hub 中已有的 BCS、BWS、SVC、光纤交换机、深信服 AD 负载均衡器、路由器监控套件的配套 `.xlsx` 规则转换为包内 `alertRule/*.json`。转换保留资源模型、优先级、生效时间、事件过滤器、复合条件及全部指标阈值；每个包只新增对应规则文件，不改变采集脚本和指标定义。
