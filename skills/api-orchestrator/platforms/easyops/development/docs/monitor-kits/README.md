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

## 服务器 SNMP 品牌与解析

见 `物理服务器SNMP_Zabbix品牌映射.md`：品牌来源、协议边界、温度/容量/风扇单位、实机验收边界及证据文件。


## metric_sampler 失败输出与退出码

监控前端依赖采集脚本的 stdout 展示错误，不能用非零退出码代替错误正文。simple-script + `metric_sampler` 统一使用以下入口：

```python
def main():
    result = collect()
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.stdout.write('COLLECT_ERROR:\n')
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        sys.exit(0)
```

局部指标或可选资源失败只记录 WARN 并继续；只有无法进入采集的异常才进入顶层 `COLLECT_ERROR`。正常采集输出必须仍是纯 JSON 数组；不要把 traceback 写到 stderr 后直接 `exit(1)`，否则前端可能看不到错误。


### 本次错误暴露实现（2026-11-05）

监控套件脚本必须在 `__main__` 顶层捕获无法进入采集的异常：先使用带函数标记和 `traceback.format_exc()` 的 ERROR 日志记录，再向 stdout 输出固定前缀 `COLLECT_ERROR:`、完整 traceback，并以退出码 0 结束。这样 `metric_sampler` 前端可以直接展示实际异常正文；不能只写 stderr 或只依赖非零退出码。正常成功路径 stdout 仍只能输出 JSON 数组，局部 OID/可选组件失败使用 WARNING 并继续。

## 操作系统 SNMP 告警规则构建依据

操作系统 SNMP 套件的 `alertRule/操作系统SNMP告警.json` 按现有 EasyOps 监控套件告警契约构建，不是自定义简化格式：

- 根对象必须有非空 `name`、`objectId`、`priority`、`_rule_name_format`，并包含 `alertConditionStrategy` 与 `cmdbInstanceStrategy`。
- `alertConditionStrategy[]` 每条策略必须有非空 `name`、`instanceId`、`objectId`、`conditionType`、`multiConditions` 和 `upgradeCondition`。
- 阈值类资源使用 `bigger_than` 等阈值条件，`alertCount=3`、`detectWindow=3`、`recoverCount=1`。
- 状态类资源（SNMP 可用性、接口运行状态）使用 `diff`，`alertCount=1`、`detectWindow=1`、`recoverCount=0`；不能用持续 `equal/unequal` 判断状态，否则会造成稳态误报或恢复误报。
- 结构依据：`formats/alert-kit/alert-rule-template.yaml`、现有 Hub 套件 `BCS监控套件/alertRule/BCS监控.json`，以及其中的 `name`、`_rule_name_format`、`cmdbInstanceStrategy` 和 `multiConditions` 实例。
