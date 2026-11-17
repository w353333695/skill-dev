# 监控套件开发知识

本目录只存监控套件专属知识，例如指标、指标集、监控任务、套件激活、监控结果和监控前端验收。

涉及 ZIP 结构、文件权限、导入失败、版本递增、Hub 成品管理等公共问题，先读取 `../common/README.md` 和其中的公共文档，不在本目录重复维护。

## 告警规则模板

告警规则模板统一使用 Hub 成品采用的 `.xlsx` 格式，通过事件中心的告警规则 Excel 导入入口使用；不再维护其他告警规则交付格式。

打包监控套件时，告警模板应随套件或作为同版本配套文件提供，并在交付说明中列出模板文件名、资源模型、规则名称格式、告警条件和指标清单。模板中的状态类指标通常使用 `diff`，阈值类指标按实际业务阈值配置。

## 服务器 SNMP 品牌与解析

见 `物理服务器SNMP_Zabbix品牌映射.md`：品牌来源、协议边界、温度/容量/风扇单位、实机验收边界及证据文件。


## metric_sampler 失败输出与退出码

监控前端依赖采集脚本的 stdout 展示错误，不能用非零退出码代替错误正文。simple-script + `metric_sampler` 统一使用以下入口：

```python
def main():
    result = collect()
    print(json.dumps(result))
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

EasyOps 旧执行环境可能使用 Python 2.7。脚本源码或采集数据包含中文时，`ensure_ascii=False` 会让 Python 2 的 JSON encoder 先按 ASCII 解码字节串并抛出 `UnicodeDecodeError`。监控脚本统一使用默认 `ensure_ascii=True`：输出为 `\\uXXXX`，JSON 语义不变，且 Python 2/3 均稳定。打包校验器必须阻断 Python 采集脚本中的 `ensure_ascii=False`。

Python 2 的 `/proc`、OpenAPI 或命令输出解码后可能得到 `unicode`。通用文本归一函数不能对它直接执行 `str(value)`：Python 2 会按 ASCII 编码并在中文字符处抛出 `UnicodeEncodeError`。应显式保留 `unicode` 值，仅字节串按 UTF-8 解码；JSON 输出继续使用默认 ASCII escape。

`debug-collector-job` 可能把脚本 stderr 合并进 `resultList[].data`。DEBUG/局部 ERROR 结构化日志不能写 stdout 或 stderr，否则会与最终 JSON 数组拼成多段文本并触发 `json unmarshal data failed`。诊断应写入缓存目录侧车文件（如 `<cacheDir>/<hostInstanceId>.debug.log`），并做大小轮转；stdout 仅保留指标 JSON 数组，顶层致命异常仍按 `COLLECT_ERROR:` 协议输出。


### 本次错误暴露实现（2026-11-05）

监控套件脚本必须在 `__main__` 顶层捕获无法进入采集的异常：先使用带函数标记和 `traceback.format_exc()` 的 ERROR 日志记录，再向 stdout 输出固定前缀 `COLLECT_ERROR:`、完整 traceback，并以退出码 0 结束。这样 `metric_sampler` 前端可以直接展示实际异常正文；不能只写 stderr 或只依赖非零退出码。正常成功路径 stdout 仍只能输出 JSON 数组，局部 OID/可选组件失败使用 WARNING 并继续。

## 监控套件发布前契约校验（强制）

监控套件不能只做 JSON 语法校验；EasyOps 的 `importOther` 会按后端结构反序列化附属文件，数组/对象类型错误会在导入阶段才暴露。每次打包前必须执行：

```bash
python3 skills/api-orchestrator/platforms/easyops/development/scripts/validate_monitor_kit.py <套件目录>
python3 skills/api-orchestrator/platforms/easyops/development/scripts/validate_monitor_kit.py <套件.zip>
```

校验器必须阻断以下问题：

- 告警 `metricName` 不存在于 `origin_metric.json`，导致规则导入后无法绑定指标。
- `resource_discovery_define.json` 顶层不是数组，或条目缺少 `objectId`、`category`、`type`。
- ZIP 顶层目录超过一个、缺少 `plugin.yaml`、版本号为空。
- Python 采集脚本包含 `ensure_ascii=False`，在 Python 2.7 环境遇到中文字节串时触发 `UnicodeDecodeError`。

### 当前环境导入验收

离线校验通过后，必须使用新版本 ZIP 调用 `POST /api/v1/plugin/import`；不得把 HTTP 200 单独当作完整验收。至少记录：

1. 响应 `code=0`、`data.instanceId`、`agentType`。
2. `GET /api/v1/plugin/detail/{instanceId}` 返回 `status=available`、套件名称和版本正确。
3. 查询 `_COLLECTOR_EASYOPS_PLUGIN` 的 `pluginResConfig`，确认资源发现配置实际写入。
4. 在事件中心的告警规则页面通过对应 XLSX 模板导入，并确认规则、资源模型、指标条件和通知策略。
5. 失败时保留后端原始错误，并修复后递增版本号重新导入；禁止覆盖同版本号包继续重试。

### 契约真源与变更规则

- 优先复制当前环境已经成功导入的监控套件结构，再替换指标和阈值，不从字段名猜测数组/对象类型。
- 平台后端契约、`formats/collector-kit/package-format.yaml` 和已验证套件是结构真源；README 只能解释用法，不能替代结构校验。

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

见 `交换机与光纤交换机监控_2026-11-09.md`：通用交换机 1.1.9 已在配置环境升级并回读；地址保持 `$.ip`、空/null 端口默认 161。光交后续已修复为1.0.17，完成24项离线回归、配置环境导入和导出核验，详情见 `光纤交换机监控修复验收_2026-11-09.md`。未激活或启动任务，不能把 `exit status 1` 直接归因到某个OID，也不能声称CSV设备已恢复。
## 主机Ping监控（2026-11-10）

新增 `主机Ping监控` 0.1.0：关联 `HOST` 模型，地址取 `$.ip`，执行节点通过系统 `ping` 命令采集可达状态、丢包率和最小/平均/最大往返时延，默认3次、单次超时2秒。套件只代表ICMP可达性，不替代TCP端口或业务协议探测；成品包见 Hub 索引，尚未导入配置环境或执行真实设备Ping。


## 华为存储实测样本校准

见 `华为存储SNMP校准_2026-11-11.md`：身份树与数据树分离、ASN.1类型保留、完整SNMPINDEX、容量MiB到字节换算、硬件字段和用户walk回放。新版套件0.1.7已走导入并重新导出验证；未宣称激活/真机验收。

## 网关启用、同步与立即采集（2026-11-11）

- [请求示例、用户验收与排障结论纠正](监控套件网关启用与立即采集_2026-11-11.md)
- 接口权威：`../../../easyops-collector-service.yaml`；流程：`../../../flows/activate-and-test-monitor-kit.yaml`。

## 主机部署实例监控（2026-11-12）

当前版本 `主机部署实例监控` 0.1.14：绑定 HOST，读取本地缓存，缓存缺失或超过7天时通过 OpenAPI search 刷新 `ARTIFACT_INST@ONEMODEL` 中 `isMonitor=是` 的部署实例；目标定位使用uuid/ip/instanceId单条件，agent配置发现的OpenAPI地址默认使用HTTPS。采集进程、端口、CPU、内存和句柄指标。数据结构、抽象模型更新坑位和导入验收见 `主机部署实例监控_数据结构与离线交付_2026-11-12.md`。
