# 监控套件开发知识

本目录只存监控套件专属知识，例如指标、指标集、监控任务、套件激活、监控结果和监控前端验收。

涉及 ZIP 结构、文件权限、导入失败、版本递增、Hub 成品管理等公共问题，先读取 `../common/README.md` 和其中的公共文档，不在本目录重复维护。

## 告警规则随套件导入

仓库中的后端契约资料（`package-format.yaml`、`objects.yaml`、`easyops-collector-plugin.yaml`）只说明 `alertRule/*.json` 会被解析并交给 `importOther` 尝试导入，未证明目标落库模型就是 `ALERT_RULE_TEMPLATE`。

- 目前不能把“解析 `alertRule/`”表述为“必然在 `ALERT_RULE_TEMPLATE` 生成实例”；目标模型、字段映射和落库结果必须通过实际导入后的 CMDB 查询确认。
- JSON 是导入时的输入快照。即便导入成功，平台侧修改规则也不会自动回写原 ZIP；要把平台修改沉淀回包，必须重新导出/读取现规则并更新 `alertRule/*.json` 后再打包。
- 重新导入/升级同一套件是否覆盖既有告警模板，也必须以目标环境实测结果为准，不能仅凭 `importOther` 名称推断；发布前应完整保留 `alertConditionStrategy`、`cmdbInstanceStrategy`、`objectId`、`priority` 等字段，避免用残缺 JSON 覆盖现有策略。
- `alertRule/*.json` 与配套告警规则模板 `.xlsx` 是两种交付形态：JSON 随套件自动导入，xlsx 用于管理端“事件中心 → 告警规则 → Excel 导入”。两者若同时维护，必须以同一 `objectId` 和 `multiConditions` 为真源，避免阈值漂移。

### 本次核对与打包

当前 Hub 中的物理服务器 Redfish 包已含 `alertRule/【物理服务器】通用告警.json`；现网 Redfish 套件详情的 `alertRules` 仍为空。现网 BCS（instanceId=`65f6851a511ad`，packageVersion=`1.1.1`）详情的 `alertRules` 和 `metricThresholdRules` 也为空；对 `ALERT_RULE_TEMPLATE` 的查询未得到可用实例结果。因此本次没有完成“导入后生成 ALERT_RULE_TEMPLATE”的实测确认。

本次已将 Hub 中已有的 BCS、BWS、SVC、光纤交换机、深信服 AD 负载均衡器、路由器监控套件的配套 `.xlsx` 规则转换为包内 `alertRule/*.json`。转换保留资源模型、优先级、生效时间、事件过滤器、复合条件及全部指标阈值；每个包只新增对应规则文件，不改变采集脚本和指标定义。
