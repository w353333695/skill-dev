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

## DM 监控套件账密错误核对（2026-11-05）

现网套件：`DM监控套件`，instanceId=`65dc3d3488b19`，版本 `1.1.4`，脚本为导出包中的 `src/dm_db_monitor.py`。

实测错误输出：

```text
dmdb_tablespace_total_size: json unmarshal data failed : invalid character 'C' looking for begining of value;
data:[CODE:-2501]用户名或密码错误
```

原因链路：

1. 脚本从 `EASYOPS_COLLECTOR_username/password/ip/port` 读取参数。
2. `DMDB_Connection.__init__` 直接调用 `dmPython.connect(...)`；账密错误会抛出异常，异常内容包含 `[CODE:-2501]用户名或密码错误`。
3. 顶层 `except Exception as e` 只执行 `print(e)`，没有输出 JSON、`COLLECT_ERROR:` 或 traceback，也没有显式 `sys.exit(0)`。
4. `metric_sampler` 仍按正常指标 JSON 解析 stdout，于是把 `data:[CODE:-2501]...` 当 JSON 解析，产生 `json unmarshal data failed`。前缀 `dmdb_tablespace_total_size` 是指标解析阶段附加的上下文，不是脚本主动打印的指标错误。

与本目录统一规范的差异：

- **不一致**：规范要求顶层异常写入 stdout 的 `COLLECT_ERROR:` + traceback，并以 `exit(0)` 结束；DM 套件实际只 `print(e)`。
- **不一致**：规范要求正常 stdout 为纯 JSON 数组；DM 账密异常时 stdout 是纯文本。
- **不一致**：脚本仍保留 `exit()`（缺少依赖文件时），且未显式保证异常路径退出码为 0。
- **一致点**：错误正文确实走 stdout，因此前端能看到错误；但当前展示是二次 JSON 解析错误，原始账密错误只作为 `data:` 内容保留。

因此不能把 DM 套件当前表现描述为已遵循 `COLLECT_ERROR` 协议；它属于“旧脚本 stdout 透传 + sampler JSON 解析失败”的兼容行为。后续若修 DM 套件，应把顶层入口改成统一异常协议，并将连接失败归为不可采集条件，保留 `[CODE:-2501]用户名或密码错误` 的 traceback/错误正文。
