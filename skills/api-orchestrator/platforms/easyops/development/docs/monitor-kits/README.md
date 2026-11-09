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

## 监控套件发布前契约校验（强制）

监控套件不能只做 JSON 语法校验；EasyOps 的 `importOther` 会按后端结构反序列化附属文件，数组/对象类型错误会在导入阶段才暴露。每次打包前必须执行：

```bash
python3 skills/api-orchestrator/platforms/easyops/development/scripts/validate_monitor_kit.py <套件目录>
python3 skills/api-orchestrator/platforms/easyops/development/scripts/validate_monitor_kit.py <套件.zip>
```

校验器必须阻断以下问题：

- `alertRule/*.json` 根对象缺少 `name`、`objectId`、`priority`、`_rule_name_format`、`alertConditionStrategy` 或 `cmdbInstanceStrategy`。
- `alertConditionStrategy`、`multiConditions`、`cmdbInstanceStrategy` 误写为对象；这三个位置按平台契约分别要求数组。
- `cmdbInstanceStrategy[]` 缺少 `instanceId`、`objectId` 或 `instances.objectId/type`。
- 告警 `metricName` 不存在于 `origin_metric.json`，导致规则导入后无法绑定指标。
- `resource_discovery_define.json` 顶层不是数组，或条目缺少 `objectId`、`category`、`type`。
- ZIP 顶层目录超过一个、缺少 `plugin.yaml`、版本号为空。

### 当前环境导入验收

离线校验通过后，必须使用新版本 ZIP 调用 `POST /api/v1/plugin/import`；不得把 HTTP 200 单独当作完整验收。至少记录：

1. 响应 `code=0`、`data.instanceId`、`agentType`。
2. `GET /api/v1/plugin/detail/{instanceId}` 返回 `status=available`、套件名称和版本正确。
3. 查询 `_COLLECTOR_EASYOPS_PLUGIN` 的 `pluginResConfig`，确认资源发现配置实际写入。
4. 在事件中心/告警规则页面或对应 CMDB 模型查询，确认 `alertRule/*.json` 是否真正落库；详情接口中的 `alertRules=[]` 不能直接证明“未导入”，也不能直接证明“已落库”。
5. 失败时保留后端原始错误，并修复后递增版本号重新导入；禁止覆盖同版本号包继续重试。

### 契约真源与变更规则

- 优先复制当前环境已经成功导入的监控套件结构，再替换指标和阈值，不从字段名猜测数组/对象类型。
- 平台后端契约、`formats/collector-kit/package-format.yaml` 和已验证套件是结构真源；README 只能解释用法，不能替代结构校验。
- JSON 告警与 XLSX 告警模板必须共享同一 `objectId`、指标名和阈值；任一方修改后重新执行校验并递增版本。

### 激活时报 `search originMetric` / `page_size validate failed`

该错误不能直接归因于 SNMP 采集脚本。优先按以下顺序排查：

1. 查询 `/api/v1/plugin/metrics/list/{instanceId}`，确认原始指标数量大于 0。
2. 通过 legacy 指标接口 `POST /api/v2/collector-metric-names`（`page=1,pageSize>=1,pluginId=...`）确认别名指标已生成；不能只看 `plugin.detail`，其 `aliasMetrics`/`metricSets` 可能为空或不返回附属资源。
3. 检查 `alias_metric.json` 是否使用完整字段：`name`、`objectId`、`dataType`、`type`、`dims`、`metricSet`、`originalMetrics`、`unit`、`expression`；不能使用自定义的 `metricId` 代替 `name/originalMetrics`。
4. 确认 `metricSet` 中的名称都存在于 `metric_set.json`，`originalMetrics` 都存在于 `origin_metric.json`。
5. 若套件已用错误版本导入，不能只重试激活；必须递增版本并用 `import_update` 重新导入附属指标，再重新查询指标元数据。
6. 若原始指标和别名指标都正常而仍报 `page_size`，再核对激活接口的请求分页参数；`page_size=0`、缺失分页字段或调用了错误端口/旧 contract 都属于平台调用问题，不应修改 OID 或采集脚本掩盖。

## 关联模型迁移与动态参数核对

2026-11-09，当前 demo 环境存储套件实测：`import_update` 将 `relateObjectId` 从 `HOST` 改为 `STORAGE@ONEMODEL` 返回 `100010`，内部原因为“不支持修改适用监控资源，请修改后重新上传”。不能把换模型当成普通升级，也不能用 `upsert` 绕过校验；应新名称导入，保留旧套件和旧任务，由使用者迁移采集目标。

- 存储设备使用 `STORAGE@ONEMODEL`；`HOST-RESOURCES-MIB` 是协议名称，不决定 CMDB 模型归属。
- `plugin.yaml.relateObjectId`、别名指标、告警规则（含嵌套策略）、Excel 和资源发现的模型引用必须一致；资源发现 `type` 按目标环境契约核对。
- 导入前读取目标模型，逐项核对 `$.ip`、`$.snmp_conf.*`。缺失属性只能在明确授权后新增，不迁移任何真实凭证。模型更新须保留保护标记、继承、已有属性、视图及权限；视图中的 `attr_authorizers` 可能为 null，合并前按空对象处理。
- 当前环境已为存储模型新增 `snmp_conf` struct，含 snmpVersion/snmpPort/community/securityLevel/securityName/authProtocol/authKey/privProtocol/privKey/contextName；读取权限为 easyops 及平台管理员，字段权限不等于加密。
- 新实例 `65fcf03206da9`，名称“存储设备SNMP监控-存储模型”，版本 `0.1.6`，回读关联模型为存储模型、状态 available。这只证明导入和定义回读，不证明激活、告警落库或真机采集成功。

## 通用交换机与光纤交换机排查（2026-11-09）

见 `交换机与光纤交换机监控_2026-11-09.md`：通用交换机 1.1.9 已在配置环境升级并回读；地址保持 `$.ip`、空/null 端口默认 161。光交仅完成 CSV、Hub 包审计与离线故障复现，尚未修改或发布光交套件，不能把 `exit status 1` 直接归因到某个 OID。
