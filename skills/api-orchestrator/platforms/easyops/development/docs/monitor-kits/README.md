# 监控套件开发知识

本目录只存监控套件专属知识，例如指标、指标集、监控任务、套件激活、监控结果和监控前端验收。

涉及 ZIP 结构、文件权限、导入失败、版本递增、Hub 成品管理等公共问题，先读取 `../common/README.md` 和其中的公共文档，不在本目录重复维护。

## 双平台本地采集强制要求

本地部署中间件监控套件立项时必须先核对产品官方支持平台。IBM MQ等官方同时支持Windows和Linux的产品，套件必须同时实现并测试两个平台：命令定位、可执行扩展名、进程资源采集、readme、plugin memo、Hub索引和离线回归缺一不可。确有单平台限制时必须在所有交付说明中显式写“仅支持XX”，并说明另一平台的阻塞原因。

## 本地采集日志与缺失指标排障强制要求

本地命令行监控套件必须提供 `logLevel` 参数，默认 `ERROR`，可选 `DEBUG/INFO/WARN/ERROR`。非DEBUG模式成功路径stdout必须保持纯JSON数组，不输出过程日志；致命异常仍走`COLLECT_ERROR:`。DEBUG诊断模式的日志直接进stdout：按 `COLLECT_ERROR:` 协议输出（前端把stdout全文当错误正文展示，免登执行主机取日志），诊断行在前、指标JSON放在末尾 `METRICS:` 标记之后可提取复验；不写文件、不写stderr。DEBUG输出会让自动指标解析按错误处理，这正是前端可见日志的手段，仅用于一次性排障，排障完成后必须恢复ERROR。默认ERROR只输出命令失败、致命异常和缺失指标摘要（缺失经 error_count/collect_complete 等数值指标可见）；DEBUG必须独立定位问题，至少包含命令路径与参数、输入命令、返回码和原始输出、目录探测候选、资源解析/过滤原因、每个分类对象的计数、最终输出指标清单，以及未出现指标名清单。日志不得输出凭证、Cookie、密钥或数据库连接串。新增或优化指标时，离线测试必须覆盖日志默认级别静默、DEBUG的COLLECT_ERROR协议输出与METRICS尾部JSON可解析、指标缺失摘要。参照实现：vcenter-monitoring（DebugLog 内存缓冲 + main() 末尾统一输出）。

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

局部指标或可选资源失败只记录 WARN 并继续；只有无法进入采集的异常才进入顶层 `COLLECT_ERROR`。`logLevel!=DEBUG` 的正常采集输出必须仍是纯 JSON 数组；不要把 traceback 写到 stderr 后直接 `exit(1)`，否则前端可能看不到错误。

EasyOps 旧执行环境可能使用 Python 2.7。脚本源码或采集数据包含中文时，`ensure_ascii=False` 会让 Python 2 的 JSON encoder 先按 ASCII 解码字节串并抛出 `UnicodeDecodeError`。监控脚本统一使用默认 `ensure_ascii=True`：输出为 `\\uXXXX`，JSON 语义不变，且 Python 2/3 均稳定。打包校验器必须阻断 Python 采集脚本中的 `ensure_ascii=False`。

Python 2 的 `/proc`、OpenAPI 或命令输出解码后可能得到 `unicode`。通用文本归一函数不能对它直接执行 `str(value)`：Python 2 会按 ASCII 编码并在中文字符处抛出 `UnicodeEncodeError`。应显式保留 `unicode` 值，仅字节串按 UTF-8 解码；JSON 输出继续使用默认 ASCII escape。

Windows Python 2的`traceback.format_exc()`可能返回GBK等本地编码字节串，直接进入`json.dumps`会按UTF-8解码并抛`UnicodeDecodeError`，进而掩盖原始采集异常。监控脚本输出DEBUG/ERROR诊断行前必须归一化文本：字节按系统编码解码、非ASCII转escape、数值/布尔保持原类型，最终每行保持ASCII安全且JSON合法。

### 本次错误暴露实现（2026-11-05）

监控套件脚本必须在 `__main__` 顶层捕获无法进入采集的异常：先使用带函数标记和 `traceback.format_exc()` 的 ERROR 事件，再向 stdout 输出固定前缀 `COLLECT_ERROR:` 和完整诊断，并以退出码 0 结束。这样 `metric_sampler` 前端可以直接展示实际异常正文；不能只写 stderr 或只依赖非零退出码。`logLevel!=DEBUG` 成功路径 stdout 只能输出 JSON 数组；DEBUG成功路径按上述stdout协议输出，局部可选资源失败使用ERROR/DEBUG事件并继续。

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
- Python 采集脚本包含 `debugLogPath`、`.debug.log` 或 `logging.FileHandler`，把诊断日志写到主机侧文件，破坏前端直接复制调试正文的目标。

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

## IBM MQ监控（2026-11-16）

新增 `IBM MQ监控` 0.4.10：绑定现网内置中间件实例模型 `IBMMQ@ONEMODEL`（继承 `ARTIFACT_INST@ONEMODEL`），同时支持Linux和Windows执行节点。采集读取真实CMDB `processList` structs契约（元素字段`cwd/cmdline/pname/confPath/logPaths/ports/user`）；0.4.8复核collector_service与easy_metric_sampler源码后使用`$.processList`让平台按进程展开为单dict JSON字符串，脚本从cmdline解析队列管理器并保留user关联。禁止`$.processList.cmdline.join()`/`$.processList.user.join()`作为simple-script动态参数：join产物是原生数组，违反Agent `ParamGroups []map[string]string`契约，0.4.6因此出现任务无脚本输出。Linux按队列管理器用`su - <user>`执行`dspmq/runmqsc`，Windows保持Agent当前用户执行，字段缺失或非法时回退`dspmq`全量自动发现。再调用 `runmqsc` 采集队列管理器、监听器、通道、本地/传输/死信队列、GET/PUT、通道收发字节数和进程资源；不再暴露 `qmgrName/mqBinPath` 任务参数，模型与进程/cmdline 自动发现规律见 `IBM_MQ监控模型与自动发现_2026-11-16.md`。45个别名指标均已配置中文名。已按Zabbix导出模板对齐队列占用率80%/90%、死信队列深度连续2点Critical、队列管理器/监听器单点异常等阈值；GET/PUT异常按Zabbix禁用触发器处理为仅采集展示。0.2.0曾导入插件`6605ad8dec33d`并激活成功，回读`enabled`、9个指标集、30个别名指标与维度映射、1条资源发现配置均正确。0.4.10完成双平台离线模拟回归、目录/ZIP校验、34项专项单测和两段真实DEBUG日志回放，修复MQSC属性换行、中文运行状态、中文成功回显解析及Python 2 ASCII解码异常；保留0.4.7的IBM MQ 7.5通道/监听器MQSC语法修复，采集脚本不依赖`from __future__ import`，支持默认ERROR与DEBUG前端直读排障日志，尚未导入线上，未创建正式采集任务，也未连接真实 IBM MQ 实例执行采集。

## 主机部署实例监控（2026-11-12）

当前版本 `主机部署实例监控` 0.1.18：绑定 HOST，读取本地缓存，缓存缺失或超过7天时通过 OpenAPI search 刷新 `ARTIFACT_INST@ONEMODEL` 中 `isMonitor=是` 的部署实例；目标定位使用uuid/ip/instanceId单条件，agent配置发现的OpenAPI地址默认使用HTTPS。采集进程、端口、CPU、内存和句柄指标。数据结构、抽象模型更新坑位和导入验收见 `主机部署实例监控_数据结构与离线交付_2026-11-12.md`。

## vCenter监控（2026-11-19）

新增 `vCenter监控` 0.1.0：关联 `CLOUD_PROVIDER@ONEMODEL`（模型零修改），地址默认动态参数 `$.url`（模型已有url属性），username/password 任务参数手填。采集脚本依赖 agent py2 内置 pyVim/pyVmomi（无需 vendor）；一次 SmartConnect 完成认证预检+采集（复用连接，认证失败即跳过本轮）；按数据中心分批 PropertyCollector 拉 ComputeResource/HostSystem/VirtualMachine/Datastore 属性，再分批 QueryPerf（intervalId=20 实时）取数据存储 totalRead/WriteLatency 与宿主机 net.received/transmitted；perf 缺失按实体跳过不伪造。35 个别名指标/5 指标集，维度 vc→datacenter→cluster→datastore/host/vm 名称动态枚举。指标与告警对齐 zabbix54 导出现网（3394项/1362触发器提取归并，见套件 sources.md）：存储空间 usage>85/95%、读写延迟≥1000ms、宿主机重启 uptime≤600s、集群红/黄、电源状态 diff。验收：导入 instanceId=6609e070e86b5 status=available，v1 `/api/v1/plugin/metrics/list` 35/35 别名落库中文名全覆盖（该环境无 v2 collector-metric-names 端点），激活 totalStatus=success 且 metricSet 资源 35 项逐条 success，回读 aliasDims 逐层继承正确；真机采集待部署方建云平台实例后验证。

`vCenter监控` 0.1.1（2026-11-19）：logLevel=DEBUG 的诊断日志统一为**内存缓冲后按 `COLLECT_ERROR:` 协议整体输出到 stdout**——前端把 stdout 全文当错误正文直接展示，跨环境排障免登执行主机取日志；指标 JSON 保留在末尾 `METRICS:` 标记之后可提取复验；cacheDir 参数随之删除（paramDefine 收敛为 address/username/password/timeout/logLevel 5 个）。已 import_update 升级导入（instanceId 不变，回读 version=0.1.1、status=enabled、5 参数）并重新激活 totalStatus=success。该口径已提升为本目录「本地采集日志与缺失指标排障强制要求」的通用规则。

`vCenter监控` 0.1.2（2026-11-19）：排查目标环境手填密码报 `illegal base64 data at input byte 4`，当时误判为形态问题改出 passwordText 明文形态（string+两标志false）——该结论已废弃。

`vCenter监控` 0.1.3（2026-11-20）：**真根因修正**——对比线上 DM监控套件（65dc3d3488b19，密码加密输入且正常工作）：其 password 为 `string + isFromSecret:true + isEncrypt:true` 且**配套隐藏 `secretName` 参数**（display=false、use=collectorParams）；illegal base64 data 的真根因是**缺 secretName 配套参数**导致平台 Secret 解密链路异常，而非两标志为 true 本身。0.1.3 完全对齐 DM 形态：恢复参数名 `password`（string+true+true）+ 新增隐藏 `secretName`，与 DM 套件参数定义同构；demo 环境 import_update 回读 version=0.1.3/enabled、password(string,True,True)+secretName、激活 totalStatus=success。目标环境 password 同名继承（已手工改成 DM 形态，继承值与包定义一致）升级无缝，已填密码值保留。加密口径已更新为唯一权威规范（`../common/套件开发_导入权限与打包规范.md`），validate_monitor_kit 阻断「isFromSecret=true 无 secretName 配套」与「非Secret引用却isEncrypt=true」两类坏形态。0.1.2 的 passwordText 明文形态废弃（参数已从包内移除，升级后任务需重填 password）。

`vCenter监控` 0.1.4（2026-11-20）：目标环境 11.66.19.194 debug-collector-job 实测两项修复。① TLS：目标 pyVim 旧版无 `disableSslCertValidation` 参数（TypeError 后裸调），且该版本默认校验证书报 CERTIFICATE_VERIFY_FAILED——traceback 实证其 SmartConnect 支持 `sslContext` 参数，脚本改为三级降级（①disableSslCertValidation→②sslContext=CERT_NONE→③裸调）。② 密码：读平台源码 `collector_service/agent_job/job_generator.go` 的 `decrypt` 证实——`IsEncrypt` 参数解密失败时 **WARN 后保原值注入**（不报错）；前端 debug 弹窗对加密参数只做轻混淆（`1234Asd!`→base64(`1234.Asd!`)=`MTIzNC5Bc2Qh`），不是平台密文格式 → debug 注入的是未解密混淆值；**正式任务创建链路前端用平台算法加密，decrypt 正常**（DM 套件即此链路）。脚本加密码候选兜底：注入值可 base64 解码为可打印文本时优先用解码值连接、认证失败回退原值；正式任务明文不受影响。排障口径：**验证加密参数链路必须建正式采集任务，debug-collector-job 弹窗对 isEncrypt 参数的注入不代表正式任务**。

### pyVmomi 版本兼容三连坑（2026-11-20~24 目标环境真机三轮回归）

目标环境（vCenter 6.7.0 + 较新 pyVim/pyVmomi 的 py2）真机回归实证三处版本差异，链路逐级打通：
① TLS：旧 pyVim 无 `disableSslCertValidation` 参数但支持 `sslContext`，默认校验证书报
CERTIFICATE_VERIFY_FAILED——三级降级（①disableSslCertValidation→②sslContext=CERT_NONE→③裸调）；
② PropertyCollector 请求侧：较新 pyVmomi 的 TraversalSpec/PropertySpec `type` 字段
CheckField 要求 ManagedObject **类对象**，字符串报 For "type" expected type type——类对象优先、字符串兜底；
③ 响应侧：pyVmomi 对象是托管类实例，**类型名只在 `obj.__class__.__name__` 上**
（`_type`/`type` 实例属性都不存在——社区代码用 isinstance(vim.HostSystem) 判型的原因），
类名即 API 类型名；识别失败的 unknown 按**类名**聚合展示（单条日志，诊断价值高）。
排障口径：真机版本差异只能靠 DEBUG 日志一轮轮收敛，`connect.ok`（含版本号）→
`inventory.datacenters` → `inventory.dc_batch`（各层计数）三级日志足以定位挂点。

### 激活请求经网关被 301 降级 GET 的坑（2026-11-19）

api-cli 经前端网关调 `kit.activate`（合约路径 `@1.0.19`）时，网关对合约路径返回重定向，POST 被降级为 GET，后端报「register: POST ... req: GET ... Matching route not found」——降级与 http/https 入口无关（https+insecure 复现同样错误）。已验证可用配方即 `systems.yaml#collector_service.runtime.gateway_monitor_lifecycle.internal_activation`：curl 直连 `EASYOPS_COLLECTOR_SERVICE_BACKEND_URL`（:12000）POST `/api/v1/collector/kit/activate`，headers 带 Host/org/user + `giraffe-contract-name: easyops.api.collector_service.job.ActivateCollectorKit`（无@版本），body 不变，返回 code=0/totalStatus=success。api-cli `--insecure` 用于跳过自签证书校验（网关 HTTPS 需要）；导入手感是 curl -F 直连 8151。
