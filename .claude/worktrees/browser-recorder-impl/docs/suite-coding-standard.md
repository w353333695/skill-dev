# EasyOps 套件编码规范

> 适用范围：平台 CMDB 采集套件、监控套件（含告警通知、监控大盘）、巡检套件、ITSM 流程（表单 + BPMN 流程）的开发。
> 内容来源：全部事实萃取自 `api-orchestrator` skill 的 `platforms/demo/` 沉淀资料（systems/objects/entities/flows/formats），无臆造；资料未覆盖处明确标注「资料未覆盖」。
> 配套定位：本规范是「套件开发者」的操作手册；编排/接入侧纪律见 `api-orchestrator` skill 的 `references/onboarding.md`。

---

## 0. 总则

### 0.1 平台服务总览

| 系统 | 服务:端口 | 能力域 |
|---|---|---|
| easyops-cmdb | cmdb_service:8079 | 模型/属性/关系/实例/dashboard |
| easyops-autoops | tool_service:8181 | 工具/版本/库 + 执行/导入导出 |
| easyops-itsm | flowable_service:8134 | 表单/流程/服务/工单 + 触发器/通知/SLA/值班组 |
| easyops-sys-setting | sys_setting:8271 | work_calendar（被 SLA 引用，跨系统接力） |
| collector_plugin_service | :8151 | 套件定义 CRUD + 导入/导出/升级 + 指标导入 |
| collector_service | kit:12000（旧 8125） | 套件运行态：激活/更新/列表 |
| inspection | logic.inspection:8103 | insp_info/metric_group/collector/template/task/history |
| msgsender | logic.msgsender:8095 | notify_method/config/message/alert |
| data_exchange | :8152 | olap_metric/column_history（监控大盘数据源后端） |

### 0.2 平台级代码公约（适用于所有 agent 端运行的套件脚本）

**默认运行环境：Python 2**，解释器 `/usr/local/easyops/python/bin/python`（agent 默认 py2.7，非 py3）。

| 规则 | 要求 | 原因 |
|---|---|---|
| 独立运行 | 单文件即可跑，不得 `import` 项目内其他 `.py` | agent 无 pip / 无项目目录 |
| print 语句 | py2 print 语句 `print x`，**不用** `print()` 函数形式 | 不能用 `__future__ print_function`——agent 运行时会在脚本顶部注入内容，导致 `__future__` 不在顶部而报错 |
| print 多参数 | 避免 `print(a, b)` | py2 会输出元组 `(a, b)` |
| HTTP 请求 | 用 `requests`（py2 环境已装），不用 urllib2/urllib3 | 用户确认 agent py2 环境有 requests |
| subprocess | `Popen.communicate()` **不传 timeout**，不捕获 `TimeoutExpired` | timeout/TimeoutExpired 是 py3.3+ 才有；需超时用 `signal.alarm` |
| 新式类 | `class Foo(object):` | py2 |
| 字符串格式化 | `.format()` 或 `%`，不用 f-string | py3.6+ |
| 编码声明 | 首行 `# -*- coding: utf-8 -*-` | py2 默认 ASCII，含中文必须声明，否则 `SyntaxError Non-ASCII character` |
| 异常 | `except Exception as e:`（py2 也支持，不用 `except Exception, e:`） | — |
| JSON 输出 | `json.dumps(result, ensure_ascii=False)` 保留中文 | py2 默认 ensure_ascii=True 会转义中文为 `\uXXXX` |
| 环境变量 | `os.environ.get('EASYOPS_<param>', '')`，大小写敏感；数值需 `int(...)` 转换 | 环境变量都是字符串；struct 参数传 JSON 字符串需 `json.loads` |

**领域例外（须声明，不可泛化）**：编排侧 `sdk/easyops_client.py`（api-cli 缺口补丁，multipart/binary + openapi AK/SK 签名）仅在编排侧/开发机运行，**不进 agent、不作为工具脚本依赖**。EasyOps 工具脚本须自包含调 cmdb/easyops（py2 stdlib urllib2 + `EASYOPS_*` 环境变量）。

### 0.3 鉴权公约

- **直连后端（backend endpoint）免 cookie**：org + user + Host 三件 header 即够。机制锚点：`engine/execute.go:135`（auth=none 跳过 auth.Apply）+ `engine/request.go:40-43`（org/user 在 resolve 阶段独立注入）。所有 backend spec 的 `endpoint.auth` 已设 `none`。
- **反向结论**：不要为直连探测/记录登录 API（前端是 SPA，登录 API 经 nginx 网关放行，实测 `/next/auth/api/login` POST 直接 405）；网关面要 cookie 时从已登录浏览器复制 PHPSESSID，不要程序化登录。
- **写操作用户**：统一用 `easyops`（具备 `itsc:form_management_{access,create,update,delete}` 等写权限）。
- **测试 org**：cmdb/autoops/itsm/sys-setting 用 `18832008`；collector 域用 `8888`。系统自带 org `[0, 1, 2]` **禁动**。
- **Host 头**：IP 直连时带 `admin.easyops.local`。

### 0.4 套件类型对照（开发前先认准你要做的是哪一类）

| 维度 | CMDB 采集套件 | 巡检套件 | 监控套件（指标采集） | ITSM 流程 |
|---|---|---|---|---|
| 本质 | 1 套件 = 套件类型 + 关联 CMDB 模型 + 参数 + 指标 | 1 套件 = 4 个 CMDB 模型实例组装 | 复用 metricbeat/exporter/prometheus | 表单 + BPMN 流程版本 |
| 包格式 | zip（plugin.yaml） | tar.gz（5 个 yaml/json） | 同采集套件 | 无包，API 建 |
| 存储模型 | `_COLLECTOR_EASYOPS_PLUGIN` | INSPECTION_INFO + COLLECTOR + METRIC_GROUP + REPORT_TEMPLATE | 同采集 | ITSC_PROCESS / ITSC_FORM |
| 参数传递 | 环境变量 `EASYOPS_COLLECTOR_*` | 脚本头部变量注入（`EASYOPS_` 前缀 / 同名） | 同采集 | 流程变量 `${}` |
| 脚本输出 | metric：`[{dims,vals}]`；process：GATHERING DATA 标记包裹 | start/end 标记包裹的指标组数组 | 同采集 metric | — |
| 执行用户 | 按任务 | root（硬编码） | 按任务 | — |
| 阈值判定 | 资料未覆盖 | 平台层判分 | 资料未覆盖 | — |
| 服务端口 | 8151（定义）/12000（激活） | 8103 | 8151/12000 | 8134 |

---

## 1. CMDB 采集套件（collector-kit）

### 1.1 定位与采集链路

采集套件（collector_plugin）= **套件类型**（simple-script/metricbeat/exporter/prometheus）+ **关联 CMDB 模型**（relateObjectId）+ **采集参数**（paramDefine）+ **指标定义**（origin_metric/alias_metric/metric_set）+ 可选（dashboard/alertRule）。

**三个服务的职责分工（常被混淆，开发前必辨）：**

| 服务 | 端口 | 职责 |
|---|---|---|
| collector_plugin_service | 8151 | 套件**定义**的 CRUD（plugin 10 端点）+ 导入/导出/升级（plugin_package 3 端点）+ 指标导入。**无 enable/disable/activate 端点** |
| collector_service | 12000（kit） | 套件**运行态**：激活/更新/列表。activate 不直接建任务，触发 AssignJobs（CMDB 事件驱动 + 600s 兜底）。成功判定：HTTP 200 且 `totalStatus != "fail"` |
| CMDB | 8079 | 存储：套件实例模型 `_COLLECTOR_EASYOPS_PLUGIN`、采集任务 `_COLLECTOR_JOB`、自动发现策略 `COLLECTOR_CMDB_AUTO_STRATEGY@EASYOPS`。采集数据归属模型由 `relateObjectId` 指定 |

**链路**：套件定义(import/create) → 拿 instanceId → kit.activate(instanceId) → collector_service 的 AssignJobs → 生成 `_COLLECTOR_JOB` 下发 collector_proxy_server → agent 运行脚本 → 脚本 stdout 写回 CMDB 实例（process_sampler）/ 推指标（metric_sampler）。

### 1.2 包结构

zip 内部目录布局：

```
{套件名}.zip
└── {套件名}/                   # ⚠️顶层目录名必须 = plugin.yaml 的 name，否则上传失败
    ├── plugin.yaml             # 核心配置（必填，所有类型）
    ├── metric_set.json         # 指标集定义（监控必填，CMDB 采集可空 []）
    ├── origin_metric.json      # 原始指标定义（监控必填，CMDB 采集为 []）
    ├── alias_metric.json       # 别名指标定义（监控必填）
    ├── config.template.yaml    # metricbeat 类型必填（Go template）
    ├── resource_discovery_define.json  # 资源发现配置（CMDB 采集套件用）
    ├── readme                  # 使用说明（注意：无扩展名，可选）
    ├── image.png               # 套件图标（可选）
    ├── src/                    # 采集脚本目录（simple-script 必填）
    │   ├── <脚本名>.py
    │   └── <脚本名>.orig        # 原始脚本（不含环境变量注入，改名时用）
    ├── dashboard/              # 仪表盘 JSON（可选，多文件，自动导入）
    ├── alertRule/              # 告警规则 JSON（可选，自动导入，过 checkAlertRules 严格校验）
    ├── deploy/                 # 部署脚本（exporter 类型必填）
    │   ├── start_script.sh
    │   ├── stop_script.sh
    │   ├── monitor_script.sh
    │   └── package.conf.yaml
    └── bin/                    # 二进制（exporter 类型必填）
```

**各类型必带文件：**
- **simple-script**：`[plugin.yaml, src/<script>.py, origin_metric.json, alias_metric.json, metric_set.json, readme]`
- **metricbeat**：`[plugin.yaml, config.template.yaml, origin_metric.json, alias_metric.json, metric_set.json]`（noPackage=true）
- **exporter**：`[plugin.yaml, deploy/*, bin/*, origin_metric.json, alias_metric.json, metric_set.json]`
- **prometheus（直接抓取）**：`[plugin.yaml, origin_metric.json, alias_metric.json, metric_set.json]`（noPackage=true，最简）

**import 时被特殊识别的可选文件（importOther）：**
- `origin_metric.json` → ImportMetricFromFile 导入指标
- `alias_metric.json` → ParsePluginAliasMetrics
- `<relateObjectId>.json` → 关联 CMDB 模型定义（object_list 数组，ImportV3）
- `auto_discovery_strategy.json` → 自动发现策略数组，注入 collectorPlugin，ImportInstance 到 `COLLECTOR_CMDB_AUTO_STRATEGY@EASYOPS`
- `resource_discovery_define.json` → 资源发现配置数组
- `readme` → 升级时从包内 readme 读文本（无扩展名）
- `dashboard/` → 有 JSON 自动导入
- `alertRule/` → 自动导入（过 checkAlertRules 严格校验）

**打包格式（关键坑，已真调验证）：**
- 格式：`ZIP_STORED` + UTF-8 flag (bit 11)。平台端解压服务不支持 ZIP_DEFLATED，用压缩模式会导致 permission denied。
- 文件 mode：目录条目 mode 755，文件 mode 664，否则上传后报 permission denied。
- 中文文件名：`command.collect.scriptPath` 必须与 zip 内实际路径匹配；中文文件名编码不一致会导致匹配失败报 `illegal base64 data at input byte 0`。
- 必须排除：`.easyops-cli/`（凭据 license）、`.git/`、`__pycache__/`、`*.pyc`、`.DS_Store`、`*.zip`、`.version`。

**版本号管理：**
- 语义化版本号（如 1.0.4），维护在套件目录 `.version` 文件（**不打包进 zip**）。
- 打包时递增 patch（1.0.3→1.0.4）；`--no-increment` 不递增。
- zip 命名：`{套件名}_v{版本号}.zip`。
- 定制内置套件改名后，version 从 1.0.0 起独立版本线，不继承原内置版本号。

### 1.3 plugin.yaml 字段字典

**套件类型 4 种（顶层 `type` 取值，prometheus 复用 exporter）：**

| 类型 type | agentType | samplerType | 必填字段 | 特性 |
|---|---|---|---|---|
| `simple-script` | `easyops` | metric_sampler（CMDB 变体用 process_sampler） | type,name,version,agentType,samplerType,relateObjectId,scriptType,command.collect.scriptPath,paramDefine | 最灵活，自定义 py2/Shell 脚本 |
| `metricbeat` | `metricbeat` | metric_sampler | type,name,version,agentType,samplerType,relateObjectId,noPackage,metricbeatName,processors | 复用 metricbeat 内置模块；noPackage 固定 true；config.template.yaml 必填 |
| `exporter` | `prometheus` | metric_sampler | type,name,version,agentType,samplerType,relateObjectId,paramDefine | 自带二进制；需 deploy/+bin/ |
| `exporter`(prometheus 直接抓取) | `prometheus` | metric_sampler | type,name,version,agentType,samplerType,relateObjectId,noPackage,paramDefine | ⚠️type 仍填 `exporter`，靠 agentType=prometheus+noPackage=true 区分；uri 参数指定端点 |

**顶层字段：**

| 字段 | 类型 | 必填 | 枚举/默认 | 含义与规范 |
|---|---|---|---|---|
| `type` | string | 条件必填 | `[simple-script, metricbeat, exporter]` | 套件包类型。prometheus 直接抓取也填 `exporter` |
| `name` | string | ✅ | — | 套件名（中文）。⚠️zip 顶层目录名 + 上传 API name 参数必须与此完全一致。命名建议「XXX监控套件」(监控)/「XXX信息采集」(CMDB 采集) |
| `version` | string | ✅ | — | 版本号。⚠️上传 API version 参数必须一致；升级时必须唯一（重复报『已存在同名版本』）；导入空则用 `time.Now().Unix()` |
| `agentType` | string | ✅ | 见枚举 | 采集器类型（运行态身份）。⚠️升级时不可变（报『更新套件时不允许变更套件类型』） |
| `samplerType` | string | ✅ | `[metric_sampler, process_sampler, event_sampler, trace_sampler, log_sampler, detect_sampler, pipeline_sampler]`；默认 metric_sampler | 采样器。监控用 metric_sampler；CMDB 采集用 process_sampler。空值按 metric_sampler 处理 |
| `relateObjectId` | string | ✅ | pattern `^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$` | 关联 CMDB 模型 ID（数据归属）。如 `HOST@ONEMODEL`、`REDIS@ONEMODEL`。⚠️$.attr 引用的字段必须属于此模型（含继承链）；开发前必须先确认此模型存在 |
| `category` | string | ❌ | — | 套件分类。常用：计算资源/网络资源/存储资源/数据库/中间件/自定义；点分多级如「平台资源.应用容器」 |
| `scriptType` | string | 条件必填（仅 simple-script） | `[python, shell, json]`（json 是 log_plugin 用） | 脚本类型。⚠️采集脚本用 Python2.7（agent 默认，非 py3） |
| `samplerInterval` | integer | ❌ | — | 采集间隔（秒），覆盖平台默认。如 30/60/3600 |
| `memo` | string | ❌ | — | 备注 |
| `icon` | object\|null | ❌ | default null | 图标 `{prefix,icon,lib,category,color}` |
| `noPackage` | bool | ❌ | default false | 是否无独立程序包。metricbeat 固定 true，prometheus 变体 true |
| `metricbeatName` | string | 条件必填（仅 metricbeat） | — | metricbeat 模块名（redis/mysql/nginx 等） |
| `processors` | array | ❌ | default [] | 后处理函数链。metricbeat 几乎必用，simple-script 通常不需要。元素 `{name,action{func,param},output,parents}` |
| `installPath` | string | ❌ | — | 安装路径。Create 时服务端默认用 name 赋值 |
| `jobFilter` | null | ❌ | default null | 采集范围过滤，通常 null |
| `protected` | bool | ❌ | default false | 是否受保护（内置 true，自定义 false）。⚠️true 的套件禁止覆盖上传（需改名） |
| `rating` | integer | ❌ | default 0 | 评分 |
| `extInfo` | object\|null | ❌ | default null | 扩展信息 |
| `collectAgent` | string | ❌ | — | 执行采集的 Agent 取值，常用动态参数从 CMDB 实例获取 IP。常用值 `$.ip` |
| `group` | array<string> | ❌ | default [] | 分组标签。导入时按 4 类白名单拆解：collectMethod/cloudType/collectContent/其他 |
| `params` | array<string> | ✅ | — | 参数名列表（与 paramDefine.name 一一对应） |

**command.collect 结构（仅 simple-script 使用，其他类型为 null）：**

| 字段 | 类型 | 必填 | 默认/枚举 | 含义 |
|---|---|---|---|---|
| `interpreter` | string | ❌ | default `""` | 脚本解释器路径。空=平台内置 Python（py2.7） |
| `scriptPath` | array<string> | ✅ | — | 脚本路径（相对套件根目录）。列表第一个=目录，第二个=脚本文件名。如 `[src, tomcat_monitor.py]`。⚠️zip 内路径必须与此匹配 |
| `type` | string | ✅ | `[python, shell]` | 命令类型，必须与 scriptType 一致 |
| `user` | string | ❌ | default `""` | 执行用户，通常为空 |

**paramDefine 字段（每元素一个参数）：**

| 字段 | 类型 | 必填 | 枚举/默认 | 含义 |
|---|---|---|---|---|
| `name` | string | ✅ | — | 参数名。运行时注入环境变量 `EASYOPS_COLLECTOR_<name>`（大小写敏感）。与 params 列表对应 |
| `valueType` | string | ✅ | `[string, int, boolean, password]` | 数据类型。password 用于敏感字段（配合 isEncrypt） |
| `defaultValue` | string | ❌ | — | 默认值。三种语义见 1.4 |
| `display` | bool | ❌ | default true | 是否界面展示。secretName 等隐藏参数 display=false |
| `displayName` | string | ❌ | — | 界面显示名（中文） |
| `description` | string | ❌ | — | 参数描述 |
| `use` | string | ✅ | `[collectorParams, instanceMapping]` | 参数用途。collectorParams=连接参数(IP/端口/密码)；instanceMapping=实例映射参数 |
| `optional` | bool | ❌ | — | 是否可选。false=必填 |
| `isEncrypt` | bool | ❌ | — | 是否加密存储。密码/凭证类字段必须 true。⚠️Update 时对已存在参数强制保留旧值（不可改） |
| `isFromSecret` | bool | ❌ | — | 是否从密钥管理获取。true 时平台从密钥库引用。⚠️Update 时强制保留旧值 |
| `secretName` | string | ❌ | — | 密钥实例名（isFromSecret=true 时由平台填充） |
| `extraArgs` | object\|null | ❌ | — | 额外参数 `{isSingleChoice,srcObjectId,isDisplayLink,linkText,query}` |

### 1.4 采集参数机制（$.attr）

**识别规则**：字符串以 `$.` 开头即为 cmdb 动态参数（`paramType=cmdb`）；否则 const 常量（`paramType=const`）。

| 形式 | 语法示例 | 机制 |
|---|---|---|
| 纯字段名 | `$.ip` / `$.instanceId` / `$.hostname` | 去 `$.` 前缀，从采集目标实例 struct 取该 key 的值 |
| 嵌套 struct 字段（点号多级） | `$.auth.community` / `$.kubernetesCluster.serviceSets.instanceId` | 按 `.` split 递归进入子 struct 逐层取值。⚠️是 struct 字段嵌套，**不是** CMDB relation 跳转 |
| 数组过滤表达式（JSONPath 风格） | `$.netdports[?(@.isMonitor == 是)].ifName` | `[?(@...)]` 成对识别为过滤段；支持 9 种操作符：`==, !=, <=, <, >=, >, in, nin, like`（转 MongoDB 风格 `$eq/$in/$like` 等）。不满足则丢弃整组 |
| 末尾 join 函数 | `$.netdports[?(@.isMonitor == 是)].ifName.join()` | 通过 `(` 定位函数名；join 把同一 paramName 的多组结果合并成数组去重排序 |
| 跨实例关系 | 靠 SearchAllPaths 在 CMDB 端做关联查询 | 本地只走 struct 字段递归；跨实例关联靠 CMDB 的 PathSearchV3 查 |

**取值对象 = 采集目标实例**（`_COLLECTOR_JOB` 采集范围内的那个实例），**不是套件实例**。

**paramType 铁律（最常见的坑）：**
- value 以 `$.` 开头 → 必须 `paramType="cmdb"`；否则 `paramType="const"`。
- collector_service 信任存储字段，**不自动推断**。若 `value="$.ip"` 但 `paramType="const"`，会把 `$.ip` 当字面字符串塞进脚本，脚本拿到 `EASYOPS_COLLECTOR_ip="$.ip"`（拿不到真实 IP）。
- `paramType=cmdb` 且 value 为 nil 时，参数被丢弃。

**defaultValue 三种语义：**
1. 以 `$.` 开头 = 动态参数（平台从 CMDB 实例自动注入，paramType=cmdb）
2. 非空非 `$.` = 普通参数（界面展示用户确认，paramType=const）
3. 空串 = 必填参数（用户启用时填）

**值类型序列化（struct/list 如何变成环境变量字符串）：**
- StringValue: 原字符串
- NumberValue: `fmt.Sprintf("%v")`
- BoolValue: `fmt.Sprintf("%v")`
- ListValue: marshal 成 JSON，trimListJson 剥掉 `{"values":...}` 包裹得纯数组 JSON
- StructValue: 直接 marshal 成 JSON 字符串
- other: `"null"`

**关键**：struct 类型参数（如 auth）经环境变量传【JSON 字符串】，脚本必须 `json.loads` 解析。示例：
```python
EASYOPS_COLLECTOR_auth='{"community":"public","snmpVersion":"2c"}'
# 脚本里：
auth = json.loads(os.environ.get('EASYOPS_COLLECTOR_auth', '{}'))
```

**secretName 自动注入机制：**
- 条件：params 中至少一个 `IsFromSecret=true`，且不存在 `name=="secretName"` 的参数 → 自动注入 secretName 参数。
- 注入定义：name=`secretName`，valueType=`string`，defaultValue=`""`，display=false，use=继承首个 isFromSecret 参数的 use，optional=false，isEncrypt=false，isFromSecret=false。
- 运行时消费：secretName 的值=密钥实例名，创建任务时 paramType=const。agent 拿到后去密钥库取真实 user/password。

**HOST 模型常用 $. 引用字段：**
- `$.ip`：采集目标 IP，最常用。HOST 默认 collectAgent 就是 `$.ip`。
- `$.instanceId`：实例唯一标识，常用于 instanceMapping / process_sampler 写回主键。
- `$.hostname`：主机名，典型 dims。
- 其他字段开发前用 `easyops-cli cmdb model get --object_id HOST` 查 attrList 确认再引用。

**$.field 通用约束：**
- `$.field` 的 field 必须是关联模型（relateObjectId，含继承链）真实存在的属性。引用不存在字段报错：`$.类型的参数要来源于cmdb模型且有应用场景`。
- 常见误用：把 agent 运行环境相关的东西（CLI 命令路径/installPath/工具目录）当成设备属性用 `$.installPath` 引用——这些不是被采集设备属性，模型中没有，必报错。正确处理：作为普通自定义入参（`defaultValue=""`, display=true 用户填），或脚本内依赖系统 PATH 不设为参数。

### 1.5 采样器类型与脚本输出协议

**samplerType 路由表：**

| samplerType | 描述 | 子路由 |
|---|---|---|
| `metric_sampler` | 指标采样器。采集监控指标（时序数据），脚本输出 dims/vals JSON | prometheus/metricbeat/easyops/sql 子路由 |
| `process_sampler` | 进程/资源采样器。采集 CMDB 配置信息（写入 CMDB 实例），脚本输出 GATHERING DATA 标记包裹的 JSON | process/easyops/cmdbCollect/default |
| `event_sampler` | 事件采样 | 通用 Template 渲染 |
| `trace_sampler` | 调用链采样 | — |
| `log_sampler` | 日志采样（仅 filebeat） | — |
| `detect_sampler` | 拨测采样（仅 NewCollectorFromAgentType 支持） | — |
| `pipeline_sampler` | 日志流水线（log_plugin 类型） | — |

**输出协议 1：metric_sampler（监控指标）**
- 格式：JSON 数组，直接 print 到 stdout。
- **不需要** BEGIN/END GATHERING DATA 标记。
- 示例：
```json
[
  {"dims": {"hostname": "www.baidu.com", "port": 443}, "vals": {"left_days": 103.0}},
  {"dims": {"db": "testdb"}, "vals": {"query_time": 12.5, "rows": 1000}, "time": 1739797799}
]
```
- 字段：`dims`（object，必填，维度标签，值为字符串/数字，键名推荐 snake_case）；`vals`（object，必填，⚠️所有值必须数值型 int/float，不能是字符串）；`time`（integer，可选，Unix 秒时间戳）。
- 规则：必须是 JSON 数组（非单对象）；每条记录必须含 dims 和 vals；vals 值必须数值型；错误信息输出 stderr（`print >> sys.stderr, ...`），不污染 stdout；异常时输出空数组 `[]` 确保 stdout 始终合法 JSON。

**输出协议 2：process_sampler（CMDB 采集）**
- 格式：stdout 用标记包裹 JSON 数组。**需要** BEGIN/END GATHERING DATA 标记。
- 标记：`-----BEGIN GATHERING DATA-----` / `-----END GATHERING DATA-----`
- 示例：
```python
print "-----BEGIN GATHERING DATA-----"
print json.dumps([
  {
    "dims": {"object_id": "HOST", "pks": ["instanceId"], "upsert": true},
    "vals": {"instanceId": "...", "name": "..."}
  }
], ensure_ascii=False)
print "-----END GATHERING DATA-----"
```
- **dims 子字段**：
  - `object_id`（string，必填）：目标 CMDB 模型 ID（如 HOST）
  - `pks`（array<string>，必填）：主键字段名。采集对象（主模型）用 `["instanceId"]`（平台按 instanceId 定位更新，避免 name 变更产生重复实例）；子模型用业务主键（如 wwpn/name）
  - `upsert`（bool，必填）：是否 upsert（true=存在则更新不存在则新建）
- **vals**：CMDB 实例属性值。主模型写 instanceId（`$.instanceId` 填充）+ 其他字段；子模型写业务主键 + 关系字段。
- **多模型关系**：写在子模型 vals 里——键=子模型 relation_list 中指向父模型的 left_id，值=`[{"_object_id":"父模型ID","instanceId":"<父instanceId>"}]`（数组）。父实例 instanceId 通常通过 `$.instanceId` 入参传入。⚠️不要用 `dims.set_relation_ids`（旧用法，方向易错）。
- **人工管理字段**：CMDB 资产字段（brand/mdl/sn 等）人工录入，采集脚本不应覆盖。约定：采集字段用 c* 前缀（cBrand/cMdl/cSn），资产字段无前缀。脚本输出前维护 HUMAN_MANAGED_FIELDS 集合剔除这些字段。
- **协议解析位置**：collector_proxy_server 是纯字节转发网关（反向隧道），对 GATHERING DATA 标记完全不解析——把脚本 stdout 原样经 easy_tunnel 隧道透传给调用方。解析 GATHERING DATA + 写回 CMDB 的逻辑在 agent 端 sampler runtime。开发套件时协议契约的对手方是 agent runtime，不是 proxy。

### 1.6 与 CMDB 模型/实例的关系

- `relateObjectId`（pattern `^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$`）= 关联 CMDB 模型 ID，决定采集数据归属。如 `HOST@ONEMODEL`、`REDIS@ONEMODEL`。
- $.attr 引用的字段必须属于此模型（含继承链）的真实属性，否则导入报错。

**CMDB 中的采集相关模型：**

| CMDB 模型 | 含义 |
|---|---|
| `_COLLECTOR_EASYOPS_PLUGIN` | 套件实例（主键 instanceId）。protected/status 字段在此 |
| `_COLLECTOR_JOB` | 采集任务（激活产物）。plugins 字段存 pluginInstanceId 列表。collectorParams/params 含 paramType |
| `COLLECTOR_LOG_JOB@EASYOPS` | 日志采集任务（log_plugin 删除前置检查此） |
| `COLLECTOR_CMDB_AUTO_STRATEGY@EASYOPS` | 自动发现策略 |
| `CollectorAliasMetric` | 别名指标 |
| `MetricObjectId` | 指标实例（删套件时级联清空，分页 500 批量删） |

**采集任务（_COLLECTOR_JOB）字段：**
- `instanceId`（anchor，13hex）、`objectId`（监控目标模型）、`jobName`、`filter`、`enabled`（AssignJobs 前置：enabled=true 才下发，false 则 RemoveJobs）、`interval`（秒）、`timeout`（秒）、`agentType`（enum: `[zabbix-agent, prometheus, easyops, custom, detect, log, snmp]`）、`plugins`（关联套件 `[{instanceId,...}]`，AssignJobs 取 `Plugins[0].InstanceId` 作 kitId）、`collectorParams`/`params`（`[{key,value,paramType:const|cmdb}]`）。
- 约束：AssignJobs 前置三件——EnableAgentJob=true、Plugins 非空、Enabled=true（任一不满足静默失败）；paramType 铁律同 1.4。

### 1.7 开发与导入流程

**硬前置门禁（禁止跳过直接生成套件）：**
1. **需求确认**：向客户对齐采集对象/内容/方式/参数来源，明确套件类型 + 目标模型预期。
2. **CMDB 模型确认**（`object_model.list`/`detail`）：在 CMDB 查是否已有合适的采集目标模型。判断标准：模型 attrList 含采集目标字段；relation_list 能挂采集结果。找到合适模型 → 记下 objectId，跳到 step 4；没找到 → step 3。
3. **模型设计 + 客户确认**（仅当 step 2 未找到）：设计新模型（objectId 正则同上、属性清单 attrList、关系 relation_list）。⚠️**必须向客户确认**——属性是否齐全、字段类型、关系方向。确认后用 `object_model.import`（upsert）建。设计错了套件激活会失败（影响 $.attr 引用 + vals 字段对应）。

**套件开发三要素（step 4 起）：**
4. 生成 `plugin.yaml` + `src/<script>.py` + `origin_metric.json` + `alias_metric.json` + `metric_set.json` + `readme`。⚠️plugin.yaml 的 relateObjectId 必须填 step 2/3 确认的 objectId。
   - 类型选择：simple-script→easyops；metricbeat→metricbeat+noPackage=true；exporter→prometheus+deploy/+bin/；prometheus 直接抓取→type=exporter+agentType=prometheus+noPackage=true
   - samplerType：监控→metric_sampler；CMDB 采集→process_sampler
   - 参数设计：设备属性(ip/instanceId/hostname)→`defaultValue: $.field`+paramType=cmdb；用户填写→`defaultValue: ""`+paramType=const；密钥→isFromSecret:true+isEncrypt:true（自动注入 secretName）。⚠️密码/凭证类入参**即使是用户自己手填**(isFromSecret:false)也必须 isEncrypt:true（+valueType:password），禁止当普通 string 明文存储。
5. 本地模拟环境变量跑脚本，验证输出格式（metric 检查 `[{dims,vals}]`；process 检查 GATHERING DATA 标记）。
6. 用 pack_kit.py 打 zip（ZIP_STORED + UTF-8 flag，排除 .version/.git/__pycache__）。
7. 查 cmdb `_COLLECTOR_EASYOPS_PLUGIN` by name 确定走新建/覆盖/拒绝：`protected` total>0 → 改名。
8. 导入套件 zip（`plugin_package.import`，multipart）。api-cli 不支持 multipart，走 curl -F 或 SDK。期望：code:0，data.instanceId(13hex)+agentType。
9. 验证套件已导入（`plugin.detail`），确认 status=available(自定义)/enabled(内置)。
10. (可选) 激活套件（`kit.activate`，需 giraffe-contract-name header）。期望：HTTP 200 且 totalStatus!=fail。

**升级流程**：detail 确认现状 → export 旧包 → 改 version/script/指标重打（顶层目录名=name 不变）→ `import_update` 上传（PUT，path instanceId + version 必填）。version 重复报 code:100007。

**删除流程**：detail 确认非 protected → `plugin.delete` → cmdb 查确认 total=0。删除前置：套件不能被采集任务引用，否则报『此套件关联有采集任务不允许删除』。非软删（物理删）。

### 1.8 注意事项 / 踩坑

**打包与编码：**
1. zip 顶层目录名必须与 plugin.yaml 的 name **完全一致**，否则上传失败。
2. 目录条目 mode 755，文件 mode 664，否则上传后报 permission denied。
3. 用 ZIP_STORED + UTF-8 flag（bit 11）。不支持 ZIP_DEFLATED。
4. 中文文件名编码不一致会导致匹配失败报 `illegal base64 data at input byte 0`。
5. 打包必须排除：`.easyops-cli/`、`.git/`、`__pycache__/`、`*.pyc`、`.DS_Store`、`*.zip`、`.version`。

**plugin.yaml 字段纪律：**
6. `name` 必须与 zip 顶层目录名 + 上传 API name 参数三处完全一致。
7. `version` 升级时必须唯一（重复报『已存在同名版本』）；无 semver 比较，仅存在性检查。
8. `agentType` 升级时**不可变**（报『更新套件时不允许变更套件类型』）。
9. `relateObjectId` 开发前必须先在 CMDB 确认模型存在。
10. `samplerType` 空值按 metric_sampler 处理。
11. `scriptType` 采集脚本用 Python2.7。
12. prometheus 直接抓取：type 填 `exporter`，靠 agentType=prometheus + noPackage=true 区分，uri 参数用 `{{ip}}/{{port}}` 占位符。

**参数设计纪律：**
13. `$.field` 的 field 必须是关联模型真实存在的属性，否则报错。
14. 不要把 agent 运行环境相关的东西（CLI 命令路径/installPath/工具目录）当设备属性用 `$.installPath` 引用。
15. 密码/凭证类入参**即使手填**也必须 isEncrypt:true，禁止明文 string。
16. paramType 铁律：value 以 `$.` 开头必须 paramType=cmdb，否则 const。
17. Update 时对已存在参数的 isEncrypt/isFromSecret 强制保留旧值（不可修改）。

**导入/升级/删除：**
18. 同名冲突默认报错，upsert=true 覆盖。
19. protected=true 的内置套件禁止上传覆盖（需改名，version 从 1.0.0 起独立版本线）。
20. 升级时 agentType 不可变；version 必须唯一；参数 IsFromSecret/IsEncrypt 从旧实例同名参数继承；其他字段一律按新包覆盖，无字段级 merge。
21. 升级无显式回滚——UpsertPlugin 成功但 importOther 失败时，部分失败无补偿。
22. 删除前置：套件不能被采集任务引用。删除级联清空 MetricObjectId 下所有指标实例（分页 500 批量删）。
23. import 文件名校验是子串包含（filename 必含 `zip` 子串，非扩展名校验）——xxx.zip/zip.tar/backup_zip 都过；无 MIME/Content-Type 校验、无签名/校验和、无大小限制。

**采集脚本规范（py2）：**（见 0.2 平台级代码公约，此处不再重复）

**别名指标：**
24. 别名指标 name 不能与 CMDB 模型属性 ID/关系 ID 同名（否则激活失败），建议加前缀 m_/mon_/metric_；displayName 在同 objectId 内不能重复。

---

## 2. 监控套件（autoops 工具 + msgsender 告警通知 + dashboard 监控大盘）

### 2.1 定位

- **autoops（tool_service:8181）**：自动化脚本/工具的管理与执行平台，三层体系 + 两配套层：
  - ① `tool` 工具配置层（ToolConfig）：name/category/权限/通知等配置 CRUD（basic 模块）
  - ② `tool_version` 工具版本层（ToolVersion）：版本是 Tool 子结构，**无独立写端点**（新建版本 = `tool.update` 改 version 字段触发派生，返回新 vId）
  - ③ `tool_lib` 工具库层（ToolLib）：动态库 CRUD（lib 模块，**仅 python 脚本类型**）
  - ④ `tool_execution` 执行层：`run_cmd` 类工具异步执行 + 结果轮询（execute 模块）
  - ⑤ `tool_package` 导入导出层：工具包 `.tar.gz`
  - **核心范式**：工具 = 配置 + 版本聚合；新建版本走 update；删除软删；执行异步。
  - 监控链路角色：autoops 本身**不直接定义监控对象/指标/阈值/告警规则**（资料未覆盖此类 resource）。其作用是 **ad-hoc 采集/执行**——`run_cmd` 是预置工具（type=python，content=`os.system(cmd)`），可执行采集命令异步轮询取表格结果。真正的指标/告警链路在 collector_service / data_exchange / msgsender。
- **msgsender（logic.msgsender:8095）**：告警通知出口 + 第三方告警源接入。通知方式 = CMDB 实例（`_MSGSENDER_NOTIFY_CONFIG@EASYOPS`）+ `notify_scripts/<plugin>.py` 脚本。msgsender 本身无独立数据库，是 CMDB 的 CRUD 代理 + 脚本加载器。
- **dashboard（监控大盘）**：仪表盘 = CMDB `_DASHBOARD` 模型实例。CRUD 走 `easyops-cmdb.yaml#dashboard`。data_exchange（:8152）是 dashboard 数据源（cmdb-olap / cmdb-columndb）的执行后端。8 种内置数据源类型中 `cmdb-olap`（监控指标）与 `cmdb-columndb`（告警历史等 18 张历史表）承载监控数据。

### 2.2 autoops 的 resource / verb

> autoops.yaml 中**没有**监控对象/指标/阈值/告警规则相关 resource。指标在 `collector_service.collector_metric`，阈值/告警规则资料未在本批文件详述。

#### 2.2.1 resource: tool（工具配置层 CRUD，path 留空，每个 op 持完整路径）

| verb | method | path | 关键字段/枚举 |
|---|---|---|---|
| `list` | GET | `/tools` | query: `name`(string,$like 模糊匹配 name+memo，前端 `q` 是其别名)、`category`、`type`、`page`/`pageSize`。响应 `{code,codeExplain,error,data:{list,total,page,pageSize}}` |
| `get` | GET | `/tools/{toolId}` | path `toolId`(32 位 hex md5，服务端生成，≠CMDB instanceId)；query `vId` 支持别名 `$latest_version`/`$latest_development`/`$latest_production`，不填=最新生产版 |
| `create` | POST | `/tools` | body 必填 `[name,type,category,content]`；详见 2.2.2 |
| `update` | PUT | `/tools/{toolId}` | body **flat**（顶层直接是工具字段，**不要套 `{tool:{}}`**）；改 ToolVersion 字段派生新版本，改 ToolConfig 字段仅改配置。响应 data 只含 `{toolId}`（派生是否成功须 `tool_version.list` 复查） |
| `delete` | DELETE | `/tools/{toolId}` | query `force`(string enum `["true","false"]`，"true" 才绕 ReadOnly)、`versionId`(不填=删整个工具；填=只删该版本)。软删（置 `delete_me=true`） |

#### 2.2.2 tool.create body 字段全集（ToolConfig + ToolVersion 聚合）

ToolConfig 基础：
- `name`(string，同 org 内不可重复)
- `category`(string，如 ITSM、CMDB；点分多级如 `运维.监控`)
- `memo`/`icon`/`tags`(array<string>)
- `listVisible`(boolean，默认 true)、`disable`(boolean)、`level`(integer)
- 权限白名单：`readAuthorizers`/`updateAuthorizers`/`deleteAuthorizers`/`executeAuthorizers`(array<string>，用户/角色)

ToolVersion 脚本与执行：
- `vName`(string，如 v1)、`vDesc`(string)
- `type`(string，**enum: [shell, python, perl, powershell, batch, Ansible-PlayBook]**；决定运行时注入哪个 SDK 库 + 默认解释器)
- `content`(string，脚本正文；可调平台 SDK 函数 `PutStr(name,val)` 出标量、`PutRow(table,row)`/`PutFormRows(table,rows)` 出表格行，行格式 `k1=v1;k2=v2`；函数由平台按 type 自动注入)
- `timeout`(integer，默认 86400；0=不限)、`defaultExecUser`(string，如 root)
- `envLinux`/`envWindows`(array<{name,value}>，进程环境变量)
- `forceShutdown`(boolean，超时强杀)、`sandboxRun`(boolean，沙箱执行)

输入参数：`inputs`(array，ToolInput[]；脚本里通过保留 key/环境变量取值；type=cmdbInstance(s) 的参数由平台按执行目标注入实例)

输出定义：
- `outputDefs`(array<{id,name}>，标量输出；脚本 `PutStr(id,val)` 回吐)
- `tableDefs`(array<{id,name,dimensions[],columns[]}>，表格输出；脚本 `PutRow`/`PutFormRows` 回吐多行)

绑定工具库：`toolLibs`(array<{name,packageId,versionId,scriptType(仅python),description,custom}>)

#### 2.2.3 其他 resource

- **tool_version**：`list` GET `/tools/{toolId}/versions`：列所有版本。版本无独立写端点。
- **tool_lib**（动态库 CRUD，仅 python，无独立 list 端点）：`create` POST `/tools/lib`（multipart）/ `update` PUT `/tools/lib/{id}` / `delete` DELETE `/tools/lib/{id}`。
- **tool_execution**（异步执行 + 轮询）：

| verb | method | path | 关键字段 |
|---|---|---|---|
| `run` | POST | `/tools/execution` | body 必填 `[toolId]`；`vId`(别名，默认 `$latest_production`；⚠️工具只有 development 版本时 `$latest_production` 报『工具版本不存在 100005』)；`inputs`(**object map** `{key:value}`，如 `{"cmd":"free -m"}`，**不是 [{name,value}] 数组**)；`agents`(array<string> IP)；`execUser`；`needNotify`(string enum `["true","false"]`，默认 true)；`timeout`。响应含 `execId`/`taskId` |
| `get_result` | GET | `/tools/execution/result/{execId}` | data = `{execId, agentData:{<ip>:{outputs,status,exitStatus,msg}}}` |
| `get_table` | GET | `/tools/execution/table/{execId}` | 仅当工具声明 tableDefs 才有表格 |
| `get_status` | GET | `/tools/execution/status/{execId}` | 轮询用，状态 `running`/`success`/`failed` 等 |

- **tool_package**（导入导出）：
  - `export_check` POST `/tools/{toolId}/export/check`（JSON）：body `versionId`(32 hex)；响应 `{toolLibExportCheckResults:[{result: success|libNotFound}]}`。
  - `export` **GET** `/tools/{toolId}/export`：query `versionId`(required, pattern `^[a-fA-F0-9]{32}$`，⚠️参数名是 `versionId` 不是 `vId`)、`compatibility`。响应 `application/x-gzip` 二进制流。
  - `import` POST `/tools/import`（multipart）：query `systemImport`(boolean)；upsert（存在→新增版本，不存在→新建）；响应 `{tools:[{versionId,versionName,importType: create|update, result}]}`。

#### 2.2.4 autoops runtime 事实

- 端口：`autoops_backend: 8181`、`frontend: 80`
- `run_cmd` 预置工具 toolId：`e292a31864662200d85a6a72ec89854a`，type=python，content=`os.system(cmd)`，只有 development 版本
- 标准响应 wrapper：`{code, codeExplain, error, data}`，code=0 成功（与 cmdb 的 `{code,message,error,data}` 不同——autoops 多 `codeExplain`）
- 后端原始注册单数 `/tool/:toolId`，rewrite 中间件改写复数 `/tools/:toolId`——直连用复数即可
- 工具脚本运行时用 `EASYOPS_*` 环境变量（`EASYOPS_LOCAL_IP`/`EASYOPS_ORG`/`EASYOPS_USER`/`EASYOPS_AUTHORIZATION_TOKEN`/`EASYOPS_CMDB_HOST`...），**不存在 `__instance__`/`${cmdb.xxx}` 这类写法**
- agent 默认 python：`/usr/local/easyops/python/bin/python`（py2）
- tool.list 后端响应是 `{data:{list}}` wrapper；api-cli 流式输出 NDJSON 是其分页输出特性

### 2.3 告警通知脚本协议（notify-kit）

#### 2.3.1 核心模型

一个"通知方式" = 两部分：
1. config 实例（CMDB `_MSGSENDER_NOTIFY_CONFIG@EASYOPS`）：name/msgType/pluginName/scriptContent/enable/serverConfig/configFields/cmdbUserObjectColName
2. 脚本 `notify_scripts/<pluginName>.py`：实现 `run(msg_data, users, ...)` 函数

**builtin vs custom：**
- **builtin**：msgType ∈ {email, wework, dingding, dingding_robot}；pluginName 由映射决定；脚本是 git 预置的 `notify_scripts/*.py`，不落盘、不需要 scriptContent
- **custom**：msgType=custom（或任何非内置值）→ pluginName **强制 = name**（服务端覆写）；脚本来自 config.scriptContent，加载时写到 `notify_scripts/<name>.py` 再动态 import（按 mtime 判断是否重载，缓存 key 是 pluginName）

#### 2.3.2 脚本契约

**签名**：
```python
def run(msg_data, users, cmdb_object_key='user_email', server_config={}, **kwargs)
```

| 参数 | 含义 |
|---|---|
| `msg_data` | dict。send_message 时=请求里的 `data.msg_data`（自由 dict，常含 content/subject）；alert_adapter 时=整个告警 payload |
| `users` | dict `{username: user_obj}`。user_obj 是 CMDB USER 实例；用 `user_obj[cmdb_object_key]` 取该通知方式要的字段值 |
| `cmdb_object_key` | str = config.cmdbUserObjectColName；**为空串时（send_message 分支）不传此参**，脚本收不到这个位置参数 |
| `server_config` | dict = config.serverConfig（脚本自己的服务端配置，如 api_key/url） |
| `kwargs` | 平台附加：`topic`（send_message 顶层 topic）、`logger`（logging 模块） |

**返回**：建议 list（成功送达的标识列表，如 mail 返回 to_addrs、wework 返回 userids）。返回值进 API 响应 data。

**runtime**：**python2**（`.iteritems()` 语法），可用 requests。

#### 2.3.3 脚本开发红线

1. 🔴编码声明：脚本含任何非 ASCII（中文注释/字符串）必须首行 `# -*- coding: utf-8 -*-`，否则 py2 加载报 `SyntaxError Non-ASCII character`
2. `run` 必须模块级可调用（`def run(...)`，非类方法），平台 `dynamic_imp_fun('<module>:run')` 取函数
3. `users` 是 `{username: user_obj}`；`user_obj[cmdb_object_key]` 取值，缺字段用 `.get` 跳过（勿直接索引报 KeyError）
4. `server_config` 的敏感字段（type=password）已由平台解码（base64→明文），脚本直接用，无需自己解
5. 异常处理：脚本内 try/except + log；未捕获异常 → send 时该 method 置 `'error'`（整体仍 200），debug 时整体 500 `'debug send msg plugin error: <异常>'`
6. `cmdb_object_key` 为空串时（send_message 的空 key 分支）run 收不到此位置参——若依赖它取值，config.cmdbUserObjectColName 必须非空

#### 2.3.4 范本示例（minimal_robot）

```python
# -*- coding: utf-8 -*-
def run(msg_data, users, cmdb_object_key='dingding_userid', **kwargs):
    userids = [info[cmdb_object_key] for info in users.values() if cmdb_object_key in info]
    for userid in userids:
        requests.post(WEBHOOK.format(access_token=userid),
            json={"msgtype": "markdown", "markdown": {"title": msg_data.get('subject', u'通知'), "text": msg_data['content']}},
            timeout=(10, 60))
    return userids
```

#### 2.3.5 config 字段字典（CMDB `_MSGSENDER_NOTIFY_CONFIG@EASYOPS`）

| 字段 | 含义 |
|---|---|
| `name` | 通知方式名（=inform_type=发送时的 method）。唯一，409 冲突报『通知方式名称重复』 |
| `msgType` | enum: email / wework / dingding / dingding_robot / custom（三方脚本用 custom） |
| `pluginName` | 脚本模块名。内置=映射；custom 强制=name（勿手填错，post 时服务端会覆写） |
| `scriptContent` | custom 类型的脚本源码字符串（内置留空） |
| `enable` | bool。false 时发送返回 `'disable'` 且 /method 不列出 |
| `serverConfig` | dict，脚本的服务端配置。敏感字段值须 base64 传输 |
| `configFields` | `[{name, type}]`，serverConfig 的字段元数据；`type=password` 的字段走脱敏/base64 协议 |
| `cmdbUserObjectColName` | CMDB USER 模型（objectId=裸 `USER`，无 @后缀）上的取值字段名。内置约定：mail→`user_email` / wework→`wework_userid` / dingding*→`dingding_userid`。custom 自定，必须 USER 模型有此属性。实测可用字段：`user_tel`(手机号)/`user_email`/`dingding_userid`/`wework_userid`/`name`；⚠️**无 telephone 字段** |
| `description` | 描述 |
| `instanceId/ctime/mtime/org` | CMDB 注入。mtime 被 load_plugins 用于判断脚本是否重载 |

#### 2.3.6 敏感字段协议（v2 专属）

- 规则：configFields 中 `type=password` 的 serverConfig 字段
  - 出站（v2 GET list / POST/PUT 响应）：值强制替换 `'********'`（`mask_sensitive_fields`）
  - 入站（v2 POST/PUT/debug）：值=`'********'` 表示未改（服务端用 CMDB 原值替换）；值非 `'********'` → 当作 base64 解码（失败报『敏感字段 %s base64解码失败』）
  - 即：新建/改密码字段必须 base64 编码传输；表单回显 `********` 不改就原样回传
- v1 vs v2：
  - v1：GET list/detail 明文返回密码——**禁止用 v1 读 config**
  - v2：GET list / POST/PUT / debug 全走脱敏+解码。**v2 无单条 GET/DELETE 路由**，这两个退回 v1（DELETE 也脱敏；单条 GET 避免读敏感值）

#### 2.3.7 API 面与端点

- base：`http://<host>:8095`，header org/user（默认 header 模式；`CHECK_AUTH_TOKEN_ENABLE=true` 时走 Bearer JWT）
- 端点：
  - `GET /api/v1/message_sender/method`：当前 enable 的通知方式列表（snake_case 字段）
  - `POST /api/v1/message_sender/send_message`：正式发。body `{topic?, data:{receivers:[{user|user_group|email_addr, method}], msg_data:{content,...}}}`。method=config.name。响应 `{code:0, data:{method: 脚本返回值|'not support'|'disable'|'error'}}`
  - `POST /api/v2/message_sender/send_message_debug`：调试。body 直接是 config 字段 + receivers。不需先建 config；一次一种方式；msg_data 内容被固定覆盖为测试文本；`receivers[].method` 必须=msgType
  - `POST /api/v1/alert_adapter/receive`：告警源接入。`data.alert_receivers=[{name(用户名), method}]`，整个 data 作为 msg_data 透传脚本。⚠️仅支持 cmdbUserObjectColName 非空的通知方式
  - `POST/GET /api/v2/message_sender/configs`（list 脱敏）；`PUT /api/v2/message_sender/configs/{id}`（解码+脱敏）
  - `GET/DELETE /api/v1/message_sender/configs/{id}`（v2 无此二路由；GET 明文敏感值慎用，DELETE 脱敏）

#### 2.3.8 权限矩阵

- 需系统管理员（`validate_is_admin`，header user 必须有『系统管理员』角色）：config 的 POST/PUT/DELETE
- 无鉴权：GET method/configs、send_message、debug、alert_adapter

#### 2.3.9 内置通知方式 pluginName 映射 + serverConfig 字段

| msgType | pluginName | serverConfig 字段 |
|---|---|---|
| email | mail | `smtp_server`/`smtp_port`/`encrypt_type`(enum ssl\|tsl\|plain)/`login_user`/`login_password`/`msg_from`/`from_name` |
| wework | wework | `corpid`/`corpsecret`/`agentid` |
| dingding_robot | dingding_robot | webhook；users 按 cmdb_object_key(默认 `dingding_userid`) 取 access_token |
| dingding | dingding_easyops | `agentid`/`appkey`/`appsecret` |

#### 2.3.10 三方告警通知脚本开发流程

1. 写脚本：首行 `# -*- coding: utf-8 -*-`（含中文必填）+ `def run(msg_data, users, cmdb_object_key, server_config={}, **kwargs)`，py2。确定 cmdbUserObjectColName（USER 模型真实字段：user_tel/user_email/dingding_userid/wework_userid/name，⚠️无 telephone）
2. 设计 serverConfig + configFields：普通字段 type=text；密码/密钥 type=password（值 base64 传输，脚本侧拿到的是已解码明文）
3. `POST /api/v2/message_sender/configs`（admin user header，api-cli 加 `--yes` 跳确认挡）建 config：`{name, msgType:'custom', scriptContent, serverConfig, configFields, cmdbUserObjectColName, enable:true}`。pluginName 服务端强制=name
4. `POST /api/v2/message_sender/send_message_debug` 调试（原地试跑，msg 内容被覆盖为测试文本）
5. `POST /api/v1/message_sender/send_message` 正式发：`receivers=[{user, method:<config.name>}]`，`msg_data={content,...}`
- 验证：`/api/v1/message_sender/method` 应列出新建方式（enable=true 时）；send 响应 `data[method]=脚返回的 list` 而非 `'not support'`/`'disable'`/`'error'`

### 2.4 监控大盘（dashboard-kit）

#### 2.4.1 _DASHBOARD 实例骨架

CRUD：`easyops-cmdb.yaml#dashboard`：create（POST `/v2/object/_DASHBOARD/instance`）/ update（PUT `.../instance/:id`，全量覆盖）/ delete + object_instance search。⚠️前端不用 import upsert——import 仅本地 JSON 导入页。

`required_core`: `[name, category, panels, context]`（+默认 dashboardVersion/template）

| 字段 | 含义 |
|---|---|
| `name` | 仪表盘名（必填） |
| `category` | 分类（必填） |
| `dashboardVersion` | 固定 `"v2"` |
| `template` | enum: `normal`(普通网格) / `bigScreen`(大屏；新建默认 size 1920x1080+黑底) |
| `timerange` | 默认时间范围（如 `now-1h`），注入 `QUERY.from`/`to` |
| `namespace` | 命名空间（新建默认 `QUERY._namespace_ ?? "dashboard"`） |
| `adaptive` | bool 自适应（bigScreen 默认 false，其余 true） |
| `context` | 数据源数组（见 2.4.3）；保存时 omit `dataSource`/`formData.dataSource`/`formData.data` 三调试字段 |
| `panels` | 构件数组（见 2.4.2）；brickConf 落库前 JSON.stringify |
| `variables` | 变量数组（见 2.4.4） |
| `hiddenTimeRange` | bool 隐藏时间选择器 |
| `messages` | 消息订阅（通常 `[]`） |
| `type` | 前端固定注入 `"builtIn"`——API 直建保持一致传 builtIn |
| `background` | `{backgroundColor, backgroundImage: images[]}`（bigScreen 用） |
| `size` | `{width,height,gap}`（大屏画布） |
| `readAuthorizers`/`updateAuthorizers`/`deleteAuthorizers` | 权限数组；user 前缀、`:group` 开头的是 userGroup |

新建 URL：`/next/dashboard/dashboard/v2/_new_/edit?_template_=normal`；`_new_` 是纯前端哨兵，首次点保存才 create。

#### 2.4.2 panel（构件实例）结构

| 字段 | 含义 |
|---|---|
| `brickId` | 构件 ID（如 `chart-v2.line-chart`） |
| `brickConf` | ⚠️**JSON 字符串**（落库前 JSON.stringify）：`{brick:"构件运行时名", properties:{...含 data 数据绑定}, slots:{}}`。编辑器读回时 JSON.parse |
| `x`/`y`/`width`/`height` | 网格坐标（24 列网格，宽常用 8/12/24） |
| `formData` | 表单结构化镜像（编辑器 UI 用） |
| `source` | 固定 `"brick"` |
| `mode` | enum: `default` / `yaml`（yaml=直接写 brickConf.properties） |
| `wrapped` | bool 白卡片容器 |
| `wrappedConf` | 卡片样式（背景/边框/内边距） |
| `title` | 面板标题；`titleStyle:{color,fontSize}` |
| `toolbarConf` | 工具栏配置（有则 JSON.stringify） |
| `tools` | 工具配置 |

**数据绑定**：构件绑数据源唯一方式 `brickConf.properties.data = "<% CTX.DS.<context项name> %>"`。表格类是对象形式：`dataSource: {list: "<% CTX.DS.<context名> %>", pageSize: 10}`。

#### 2.4.3 context 项结构 + 8 种内置数据源类型

context 项字段：

| 字段 | 含义 |
|---|---|
| `id` | 内部 ID（`data_{N}_{name}`，编辑器生成） |
| `name` | ⚠️数据源名——被构件 `<% CTX.DS.{name} %>` 引用，全 dashboard 唯一（http 类型 pattern `^(?!\d)[一-龥A-Za-z0-9_]+$`） |
| `type` | enum: `cmdb-list` / `cmdb-detail` / `cmdb-count` / `cmdb-count-multi` / `cmdb-group` / `cmdb-olap` / `cmdb-columndb` / `http` / `static` / `dynamic`(废弃) |
| `provider` | 运行时 Provider 全名（如 `easyops.api.data_exchange.olap@Query:1.0.0`） |
| `dataType` | enum: `array` / `object` |
| `args` | 查询 DSL 的 YAML 字符串（结构因 type 而异） |
| `formData` | 表单结构化数据（落库 omit `formData.dataSource`/`formData.data`） |
| `outputFields` | `[{key, alisa}]` 输出字段声明 |
| `transform` | 转换表达式（如 `"<% DATA?.list ?? [] %>"`，DATA 是接口原始返回） |

`save_omit`：保存时 omit `dataSource`/`formData.dataSource`/`formData.data` 三个调试字段。

8 种类型官方语义 + backend 端点 + 默认 transform：

| type | 官方语义 | backend 端点 | 默认 transform |
|---|---|---|---|
| `cmdb-list` | CMDB实例列表 | POST `/v3/object/{objectId}/instance/_search` | `<% DATA?.list ?? [] %>` |
| `cmdb-detail` | CMDB实例详情 | CMDB 实例详情端点（GET） | 留空 |
| `cmdb-count` | CMDB单模型实例总数 | 同 cmdb-list 结构 | 留空 |
| `cmdb-count-multi` | CMDB多模型实例总数 | POST `/v1/batch/instance/count` | `<% DATA?.objectInfo ?? [] %>` |
| `cmdb-group` | CMDB实例聚合 | — | `<% DATA?.list ?? [] %>` |
| `cmdb-olap` | **监控指标** | POST `/api/v1/data_exchange/olap` | `<% DATA?.list ?? [] %>` |
| `cmdb-columndb` | **历史数据统计** | POST `/api/v1/data_exchange/tsdb_column/aggregate` | `<% DATA?.data ?? [] %>` |
| `http` | HTTP 请求 | basic.http-request | `<% DATA?.data?.list ?? [] %>` |
| `static` | 静态数据 | provider=null | — |

#### 2.4.4 cmdb-olap（监控指标，核心）args DSL 模板

```yaml
- model: easyops.HOST                    # easyops.<objectId>
  fillEmptyData: true
  dims: [time, instanceId]               # time=自动时间粒度；可加分组维度
  filters:
    - {name: time, operator: ">=", value: "<% QUERY.from ?? \"now-1h\" %>"}
    - {name: time, operator: "<=", value: "<% QUERY.to ?? \"now-1s\" %>"}
  measures:
    - name: CPU使用率                    # 输出列名
      function: {expression: avg, args: [host_cpu_used_total]}   # 🔴指标名必查证
  query: {instances: {query: {}, type: all}}
```

- args = YAML[单元素数组{model, fillEmptyData, dims, filters, measures, translate, query}]
- dims 时间维度前端真实写法 `time(auto)`（time 后缀 `(auto)` 表自动粒度）；API 直调 `time` 亦可
- **measures DSL**：`measures[] = {name, function: {expression: 聚合算子, args: [指标名]}}`。🔴**function 字段名是 `expression`，不是 `operator`**（直调传 Go struct 名 operator 报 `not valid measure operator`）
- **聚合算子全表**：`count`/`min`/`max`/`sum`/`avg`/`topK`/`last`/`divide`/`increase`/`rate`/`irate`/`quantile`
- **filters DSL**：`filters[] = {name, operator, value}`；前端自动 concat 默认 time>=from/time<=to。**比较算子**：`==` `!=` `<=` `<` `>=` `>` `=~` `!~` `in` `has` `nin` `and` `like` `nlike` `exists`。时间过滤 name=time 支持 `now-1h` 相对时间
- **response_shape**：🔴前端 cmdb-olap 走 v1 端点 → transform DATA?.list 后是**平铺点数组** `[{time, <measure名>: 值, _object_id, objectId}, ...]`。❌不是 v3 的 series 结构 `[{name,dims,values:[{value,time}]}]`。图表 xField/yField 按字段消费平铺点；统计卡取当前值用末位 `[measure名]`
- **metric_verification**：🔴指标名权威查证：① `collector_metric list`（POST `/api/v2/collector-metric-names`，body `{page,pageSize,objectId:"HOST"}`）→ data.list[].metricName/unit/dims；② `collector_metric get`（objectId+metricName）；③ 活性试查 `olap_metric query_v3`（dims=["time"]+time>=now-1h+limit 1）。⚠️v3 与前端实际用的 v1 行为可能不同（实测 v3 某些指标 30d total=0 而 v1 now-1h 有数据），存疑时用 v1 同参数复核

#### 2.4.5 cmdb-columndb（历史数据统计）args DSL

```yaml
- database: "<% String(SYS.org) %>"      # org 号
  filter: <JSON字符串，默认 "{}">
  group_by: [分组字段]                    # 支持按天/小时分组模板
  measures: [{field, op: count|sum|max|min, alias}]
  object_ids: [<历史表>]                  # 单元素数组
  start_time/end_time: 秒级时间戳（followTimeRange 时由 QUERY.from/to 注入）
```

**18 张历史表全清单**（object_ids 候选）：
`monitor_event@EASYOPS`(告警历史) / `monitor_event_last@EASYOPS`(当前告警) / `cmdb_change_history@EASYOPS`(CMDB变更) / `tool_oplog@EASYOPS`(工具任务) / `flow_oplog@EASYOPS`(流程任务) / `deploy_oplog@EASYOPS`(发布任务) / `scheduler_oplog@EASYOPS`(定时任务) / `database_delivery_oplog@EASYOPS`(数据库变更) / `agent_management_oplog@EASYOPS`(Agent管理) / `ops_automation_job_task@EASYOPS`(运维自动化) / `app_pipeline_oplog@EASYOPS`(流水线) / `inspection_history@EASYOPS`(巡检自动化) / `pipeline_build@EASYOPS`(CI任务) / `itsm_ticket@EASYOPS`(ITSM工单) / `itsm_ticket_standard_field@EASYOPS` / `itsm_ticket_operation@EASYOPS`(ITSM工单操作)

#### 2.4.6 变量（variables）

变量 = dashboard 级 URL query 参数声明 + 选择器。值经 `QUERY.{id}` 被 context/panel 表达式引用。

| 字段 | 含义 |
|---|---|
| `id` | 变量 ID（=URL query 参数名，被 `QUERY.{id}` 引用） |
| `name` | 显示名 |
| `multiSelect` | bool 多选（默认 false；QUERY 值为逗号分隔串，消费端 `.split(',')`+`$in`） |
| `showSelector` | bool 显示选择器 UI（默认 true） |
| `selectorObjectId` | CMDB 模型 ID（type=cmdb） |
| `selectorQuery` | 🔴必须是**纯 JSON 字符串**（前端 JSON.parse 它）；级联引用用 `${QUERY.<其他变量id>|string}` 占位符嵌在 JSON 值里；🔴**禁用 `<% %>` 表达式**（整段表达式会 JSON.parse 崩 `SyntaxError: Unexpected token '<'`） |
| `selectorBrick` | 选择器构件（默认 `forms.general-select`） |
| `selectorDefaultValue` | 默认值（保存后 URL 自动带上） |
| `fieldsLabel` | 选项显示字段（🔴object_model 查证真实属性；HOST 无 name 是 hostname/ip） |
| `fieldsValue` | 选项值字段（不配=默认 instanceId。🔴监控指标过滤必用 instanceId——OLAP 数据一定有 instanceId 不一定有 ip/hostname） |
| `placeholder` | 占位文案 |

`type` enum: `constant`(自定义列表) / `cmdb-model`(从模型选) / `cmdb`(从模型实例选) / `custom`(自定义数据源) / `comparator`(比较器)

builtin vars: `QUERY.from`/`to`(timerange 注入) / `QUERY.instanceId` / `QUERY.sort`|`order`|`page`(表格)

#### 2.4.7 表达式框架

- 语法：`"<% " + 单个JS表达式 + " %>"`（求值）。⚠️与 `${QUERY.x|string}` 占位符是**两套语法**，适用字段不同：
  - 📌 `<% %>` 表达式（JS 求值）：`brickConf.properties` 值、`context.transform`、cmdb-olap args 内的 query/filters value、http formData
  - 📌 `${QUERY.x|string}` 占位符（JSON 内插值）：`variables[].selectorQuery`（该字段被前端 JSON.parse，只能是纯 JSON + 值内占位符）
- builtin 对象：`QUERY`(URL query)、`CTX`(上下文，数据源专用 `CTX.DS.{context名}`)、`DATA`(转换用原始数据，`DATA?.list ?? []`)、`SYS`(系统，cmdb-columndb args 用 `SYS.org` 拼 database)、`PIPES`(管道字典：`parseTimeRange`/`yamlStringify`/`yaml`)、`_`(Lodash)、`moment`(Moment)
- JS 子集：✅箭头函数/三元/`?.`/`??`/模板字符串/展开；❌if 语句/var/赋值/类（必须单表达式）；对象 key 是中文/数字开头须用 `["..."]` 下标语法（.点语法取不到）
- 常用模式：取列表空兜底 `<% DATA?.list ?? [] %>`；带默认值取参 `<% QUERY.from ?? "now-1h" %>`；条件注入过滤 `<% { ...(QUERY.ns ? {"ns": {"$in": QUERY.ns.split(",")}} : {}) } %>`

#### 2.4.8 CMDB 过滤比较器（区别于 OLAP 比较算子）

`$like`(包含) / `$nlike` / `$eq` / `$ne` / `$exists:false`(为空) / `$exists:true` / `$in` / `$gte` / `$lte` —— MongoDB 风格（object_instance search 同款语法）

#### 2.4.9 构件选型（数据形态→构件）

- 趋势/时序 → `chart-v2.time-series-chart` / `line-chart` / `area-chart`
- 当前值统计卡 → `general-charts.statistic-card` / `statistic-item`；大屏：`dashboard-v2.horizontal-indicator-card` / `vertical-indicator-card` / `tech-style-indicator-card-with-base`
- 对比 → `chart-v2.bar-chart` / `horizontal-bar-chart`
- 占比/分布 → `chart-v2.pie-chart` / `donut-chart` / `treemap-chart`
- 仪表/雷达 → `chart-v2.gauge-chart` / `radar-chart`
- 表格 → `presentational-bricks.brick-table`（columns/dataSource.list 绑定）；大屏滚动表：`dashboard-v2.scroll-table` / `modern-scroll-table`
- 文本/说明 → `presentational-bricks.markdown-display` / `code-display`

**统计卡陷阱：**
- 🔴统计卡 value 必须单值——用表达式从数据源提取，**禁止直接绑整个数据源**（绑数组 → 显示 NaN%）
- 🔴🔴先确认数据源结构再写取值表达式（取决于 olap 版本）：
  - 前端 cmdb-olap context 实际走 v1 端点 → transform 后是平铺点数组 `[{time, <measure名>: 值}, ...]`，取当前值 = 末位点的 measure 字段：
    `"value": "<% CTX.DS.cpuTrend?.length ? (CTX.DS.cpuTrend[CTX.DS.cpuTrend.length-1]?.[\"CPU使用率\"] ?? 0) : 0 %>"`
    （measure 名做 key，中文/含数字须用 `["..."]` 下标语法，不能点语法）
  - 仅当数据源是 v3 series 结构 `[{name,dims,values:[{value,time}]}]` 才用 `?.values?.[...]?.value`
  - 数据源出单值时直接 `"value": "<% CTX.DS.系统数量[\"data\"] %>"`
- format：`{precision:1, unit:"percent(1)"}`；icon：`{category,icon,lib:"easyops"}`；iconPosition:"right"；showCard:false
- ⚠️值太小+precision:0 会显示 0%（数据真实非 bug）

#### 2.4.10 data_exchange 后端

- 端口：`data_exchange: 8152`（直连全通，org+user+Host 免 cookie）
- capabilities：
  - `olap_metric.query_v3`：监控指标聚合查询 v3（series 分组）；兼指标活性试查
  - `olap_metric.select_raw`：原始时序点直查（分页）——指标是否有数据的权威试查
  - `column_history.aggregate`：历史数据统计聚合（18 张 @EASYOPS 历史表）
- 🔴measures[].function JSON 字段名是 `expression`（传 Go struct 名 operator 报 `not valid measure operator`）
- 🔴columndb filter 直调传对象（args YAML 里的 JSON 字符串是前端序列化格式）
- 网关面 `/next/api/gateway/logic.data_exchange/*` 需有效会话 cookie（过期报 `ERR_UNAUTHENTICATED`）——编排走 :8152 直连
- org 隔离：db 名=org 号，SQL 层自动 org 过滤

### 2.5 监控套件注意事项 / 踩坑

**autoops：**
1. 🔴 `tool.update` body 必须 **flat**（顶层直接是工具字段，不要套 `{tool:{...}}`）。套了则 `updateFields=[tool]` 命中"仅改 config"短路分支，**假成功不生效**。
2. 🔴 `tool_execution.run` 的 `inputs` 是 **map**（`{key:value}`，如 `{"cmd":"free -m"}`），**不是 [{name,value}] 数组**——数组报 json 解析失败 100000。
3. 🔴 `run` 默认 `vId=$latest_production` 对只有 development 版本的工具（如 run_cmd）报『工具版本不存在 100005』——用具体 vId 或 `$latest_development`。
4. 🔴 `tool.update` 响应 data 只含 `{toolId}`（无 vId/vName）——派生是否成功须 `tool_version.list` 复查。
5. 🔴 `tool_package.export` 是 **GET**（非 POST）；query 参数名是 **`versionId`**（不是 `vId`）；返回 tar.gz 二进制流——api-cli 无法存文件，走 Python SDK 流式下载或 `--print-curl`。
6. 🔴 `tool_package.import` 是 multipart——api-cli 不支持 formData，真调走 Python SDK `import_tool` 或 `curl -F`。
7. 删除是软删（置 `delete_me=true`）；`force=true`（query 字符串 "true"）仅绕 ReadOnly；`versionId` 不填=删整个工具，填=只删该版本。
8. 工具脚本运行时用 `EASYOPS_*` 环境变量调 cmdb/easyops；**不存在 `__instance__`/`${cmdb.xxx}` 写法**。
9. 工具脚本须【自包含】，不得 import 外部 .py（agent 无 pip / 无项目目录）；默认 py2。
10. 后端原始注册单数 `/tool/:toolId`，rewrite 改写复数 `/tools/:toolId`——直连用复数即可命中。
11. 直连 backend（auth=none）只需 org+user header（缺一报 empty org/user）；cookie 非必需。
12. tool.list 后端响应是 `{data:{list}}` wrapper（取 data.list）；api-cli 流式输出 NDJSON 是其分页输出特性非后端格式。

**msgsender / notify-script：** 见 2.3.3 开发红线 + 2.3.6 敏感字段协议 + 2.3.8 权限矩阵。

**dashboard-kit：**
13. 🔴 dashboard.create body 是**平铺配置字段**（勿包 `instance` 包装！包了 code=0 但字段静默丢失——后端 validator 直接吃整个 body）。
14. 🔴 `panel.brickConf` 落库前须 **JSON.stringify 成字符串**（不是对象）；编辑器读回时 JSON.parse。
15. 🔴 证据纪律：指标名（`collector_metric.list` 查证）和 objectId（`object_model.list` 查证）**勿编造**——错了后端不报错、图表静默空白。
16. 🔴 监控指标过滤**必用 instanceId**——OLAP 数据一定有 instanceId 不一定有 ip/hostname；variables.fieldsValue 不配=默认 instanceId。
17. 🔴 统计卡 value 必须单值表达式，禁止直接绑整个数据源（绑数组 → 显示 NaN%）；先确认数据源结构再写取值表达式（v1 平铺点数组 vs v3 series 结构，取值表达式不同）。
18. 🔴 measure 名做 key 时中文/含数字须用 `["..."]` 下标语法，不能点语法。
19. 🔴 `variables[].selectorQuery` 必须是**纯 JSON 字符串**，级联引用用 `${QUERY.<id>|string}` 占位符；**禁用 `<% %>` 表达式**。
20. 🔴 `<% %>` 表达式 vs `${QUERY.x|string}` 占位符是**两套语法**，适用字段不同，用错即崩/失效。
21. 🔴 `context` 保存时 omit `dataSource`/`formData.dataSource`/`formData.data` 三个调试字段。
22. dashboard.update 是**全量覆盖**——先 `object_instance search` 取完整现配 → 本地改 → PUT 回，漏传字段会被清掉。
23. 🔴 cmdb-olap 的 `measures[].function` JSON 字段名是 **`expression`**（不是 `operator`）。
24. 🔴 cmdb-columndb filter 直调传对象（args YAML 里的 JSON 字符串是前端序列化格式）。
25. dims 时间维度前端真实写法 `time(auto)`（API 直调 `time` 亦可）。
26. cmdb-olap 前端走 v1 端点 → transform 后是平铺点数组（不是 v3 series）；存疑时 v1 同参数复核。
27. API 落库 code=0 ≠ 前端渲染正确（前端解释型内容）——须用户开页面确认图表渲染/数据/变量选择器。
28. 不要用 import upsert 建盘（那是本地 JSON 导入页路径，缺前端注入的 type=builtIn 等默认字段）。
29. 大屏（bigScreen）：`template=bigScreen` + `size{width:1920,height:1080}` + `background`，新建自带 page-title/date-indicator 默认面板。
30. dashboard 验收 URL：`${EASYOPS_CMDB_FRONTEND_URL}/next/dashboard/dashboard/v2/<instanceId>?from=<timerange>&_namespace_=<namespace>`。

---

## 3. 巡检套件（inspection-kit）

### 3.1 定位、巡检链路角色、与监控/采集的区别

**服务定位**：EasyOps 巡检服务 `logic.inspection:8103`。平台当前实测用 **v1 体系**（INSPECTION_INFO，.90 环境 20 套件）；v2（INSP_SUITE）0 套件未启用。

**套件本质**：1 个巡检套件 = **4 个 CMDB 模型实例组装**（区别于采集套件的单模型），共享 `pluginId`（=info.id）串联：
- `INSPECTION_INFO@EASYOPS` — 套件元信息（pluginId 主键）
- `INSPECTION_COLLECTOR@EASYOPS` — 采集脚本（1 套件通常 1 脚本）
- `INSPECTION_METRIC_GROUP@EASYOPS` — 指标组（含 vals+阈值 conditions，1 套件多组）
- `INSPECTION_REPORT_TEMPLATE@EASYOPS` — 报告模板（详情+总览，1 套件多模板，可选）

**e2e 链路角色**：建套件(4对象) → 建任务(task) → 调度执行产生 jobId → history 按 jobId 查结果/报告。任务调度委托外部 scheduler（`taskType=once` 绝对时间 `2006-01-02 15:04:05` / `crontab` cron 表达式），inspection **不内置 cron**。

**与采集套件（collector-kit）的区别（系统对照表）：**

| 维度 | 巡检套件 | 采集套件 |
|---|---|---|
| 存储 | 4 个 CMDB 模型组装 | 1 个 CMDB 模型 |
| 包格式 | tar.gz（5 个 yaml/json） | zip（plugin.yaml） |
| 参数传递 | 脚本头部注入变量赋值（非环境变量） | 环境变量 `EASYOPS_COLLECTOR_*` |
| 输出格式 | start/end 标记包裹的指标组数组 | 直接输出 `[{dims,vals}]` |
| instanceId | 必须 输出 INSTANCE ID 标记 | 不需要 |
| dims 角色 | 维度列（可空） | 维度标签 |
| 指标 id | 必须 ↔ metrics.yaml 的 id 精确对应 | 自由（origin_metric 定义） |
| 执行用户 | root 硬编码 | 按任务 |
| 阈值判定 | 平台层判分 | 资料未覆盖 |

### 3.2 套件包结构

**包格式**：tar.gz（gzip over tar）。**顶层目录名** = `info.id`（pluginId），如 `weblogic`/`mysql`。目录布局（5 文件）：

```
<pluginId>/
├── info.yaml              # 套件元信息（必需）
├── metrics.yaml           # 指标组列表（数组）
├── collectors/
│   ├── __init__.py        # 空文件（Python 包标记占位）
│   └── script.py          # ⚠️文件名误导：内容是 YAML 非 Python 源码
├── reports_temp/
│   └── detail.yaml        # 报告模板列表（可选）
└── models.json            # 关联 CMDB 模型定义（可选，仅导出第一个模型）
```

**文件名常量**（源码 `import_export_service.go:94-100`）：`infoYaml=info.yaml` / `metricsYaml=metrics.yaml` / `collectorScript=script.py` / `reportsTempDetail=detail.yaml` / `modelsJson=models.json`。

**必填 vs 可选：**
- 必填：`info.yaml`（无则报『导入的文件数据格式有误』）
- 可选：`metrics.yaml`、`collectors/script.py`、`reports_temp/detail.yaml`、`models.json`（缺失不报错，switch 默认忽略）

**pluginId 一致性强校验**：所有文件的 pluginId 必须相同，不一致报『套件信息中,pluginId存在不同值』。

### 3.3 info.yaml 字段

源码 `info/message.go:10-54`；实测 weblogic 套件：

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `instanceid` | string | 新建留空 | 平台生成 |
| `internalid` | string | - | 内部 id |
| `id` | string | ✅ | pluginId，套件唯一标识（英文小写，如 mysql）；顶层目录名=此值 |
| `name` | string | ✅ | 套件显示名（中文） |
| `isapp` | bool | - | 是否应用类 |
| `issystem` | bool | - | 是否内置套件（自定义应为 false） |
| `memo` | string | - | 备注 |
| `index` | int | - | 排序 |
| `objectid` | string | ✅ | 巡检目标 CMDB 模型 id（开发前必须确认模型存在） |
| `objectname` | string | - | 目标对象显示名 |
| `method` | string | ✅ | 巡检方式，`agent`=远程主机执行（默认 agent） |
| `keys` | array<string> | ✅ | 唯一键列表（CMDB 属性 id，定位巡检实例）；DB 类常用 `[serverName]`/`[instanceName]` |
| `countersideid` | string | - | 对端模型（DB/中间件类常用 HOST；⚠️create-only 见 3.9） |
| `relationid` | string | - | 与对端模型的关系 id（可空） |
| `relationidwithhost` | string | ✅ | 与 HOST 的关系 id（CMDB relation 三段式） |
| `status` | string | - | 状态（`ok`/`object_deleted`/`keys_deleted`/...，平台维护） |
| `subplugins` | array | - | 子插件（组合套件用） |
| `creator` | string | - | 创建人（平台填） |

**关联主机字段（host_relation_patterns，19 套件归纳规律）：**
规则：`relationIdWithHost = {中间模型}@ONEMODEL_{counterSideId}_{relationId}_HOST`，按中间模型分 4 类：
- **artifact_inst_class**（最常见，DB/中间件/应用）：`counterSideId=host`、`relationId=artifactInsts`、`relationIdWithHost=ARTIFACT_INST@ONEMODEL_host_artifactInsts_HOST`
- **service_class**（服务部署类，redis/ibmq）：`counterSideId=relatedHost|inspectionHost`
- **direct_host_class**（直连主机，weblogic/oracle）：`counterSideId=HOST`、`relationId=INSPEC_WEBLOGIC|INSPEC_ORACLE`
- **node_class**（节点类，kafka/nginx）：`counterSideId=HOST`、`relationId=""`、`relationIdWithHost=KAFKA_SERVICE_NODE_HOST_KAFKA_SERVICE_NODE_HOST`

### 3.4 metrics.yaml 字段

源码 `metrics/message.go:13-89`，实测 weblogic 8 组：

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `id` | string | ✅ | 指标组业务 id（套件内唯一，创建时查重） |
| `pluginid` | string | ✅ | 必须与 info.id 一致 |
| `name` | string | ✅ | 指标组显示名 |
| `category` | string | ✅ | 两级分类点分（如 `整体状态.连接数`），**正好 1 个点**，否则报『分类格式错误』 |
| `memo` | string | - | 备注 |
| `dims` | array<{id,name}> | - | 维度列 |
| `vals` | array | ✅ | 指标值列表，至少 1 个 |
| `vals[].id` | string | ✅ | 指标 id（脚本输出 `vals[].id` 要对应） |
| `vals[].name` | string | ✅ | 指标显示名 |
| `vals[].type` | string | ✅ | ⚠️仅 `string`|`num`（真实数据用 num；源码注释 int 实为 num） |
| `vals[].unit` | string | - | 单位 |
| `vals[].weight` | int | - | 权重 0-100（MaxWeight=100） |
| `vals[].conditions` | array | - | 阈值条件数组（套件定义时常空 `[]`，阈值在任务里配） |

### 3.5 collectors/script.py（⚠️YAML 格式，文件名误导）

源码 `collector/message.go:9-46`；`import_export_service.go:680-702`。文件名叫 `script.py` 但内容是 `yaml.Marshal(Collector)` 序列化的 struct，**不是 Python 源码**。真正的 Python 源码在 `content` 字段（多行字符串）。v1 只导出第一个脚本。

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `instanceid` | string | - | 新建留空 |
| `collectorid` | string | - | 平台生成 |
| `pluginid` | string | ✅ | 与 info.id 一致 |
| `name` | string | ✅ | 脚本名（如 `script`） |
| `script` | string | ✅ | `python`|`shell`（默认 python，py2.7） |
| `args` | array | ✅ | 参数定义数组（见 3.7） |
| `content` | string | ✅ | Python/Shell 源码（py2 语法，见 3.6） |

### 3.6 巡检脚本协议

#### 3.6.1 运行时
- **语言**：Python 2（默认）或 Shell(bash)
- **Python 解释器**：默认 `/usr/local/easyops/python/bin/python`；脚本首行 shebang 可覆盖（正则 `^#!\s?[^ ](.*)python(.*)\n`，支持 `#!/usr/bin/python` / `#!/usr/bin/env python3`）
- **Shell 解释器**：默认 `/bin/bash`；shebang 正则 `^#!\s?[^ ](.*)bash(.*)\n`
- **执行用户**：root（硬编码）

#### 3.6.2 参数传递（与采集套件最大不同：脚本头部注入变量赋值）
- **机制**：执行时平台构造 `cmd = 参数赋值头 + instanceId 标记打印 + 脚本源码`，整体交给解释器。参数不是环境变量、不是命令行参数——是源码级注入的变量赋值。
- **注入规则表**（只看 args 的 source 字段）：

| source | 注入格式 |
|---|---|
| `attr_id`（CMDB属性，含唯一键） | `EASYOPS_<key>=<value>`（加前缀） |
| `custom`（用户填） | `<key>=<value>`（无前缀） |
| instanceId（平台内置） | `EASYOPS_instanceId=...`（加前缀） |

- **空字符串参数**：转 `None`（Python 字面量）
- **踩坑**：attr_id 的参数（如 ip）在脚本里要读 `EASYOPS_ip`，不是读 `ip`！否则取不到值（None），是巡检脚本 failed 的常见原因。
- **password 类型**：source:custom 的 password 解密后注入，无前缀 `password='secret123'`
- **Shell 变体**：等价 bash 语法 `EASYOPS_instanceId="..."/key=value`，instanceId 标记用 `echo $EASYOPS_instanceId`

#### 3.6.3 命令路径规范（脚本设计红线）
- **问题**：脚本写死 `/usr/local/easyops/mysql/bin/mysqladmin` 报 OSError [Errno 2] No such file or directory——目标主机没有这个路径
- **禁止**：硬编码绝对路径（如 `/usr/local/easyops/mysql/bin/mysqladmin`、`/opt/xxx/bin/cli`）
- **三选一方案（按可靠性排序）**：
  1. 【首选】用 Python 客户端库直连，不调外部命令——无路径问题。真实套件范式：mongodb=pymongo / mssql=pymssql / redis=redis-py / oracle=cx_Oracle。DB 类巡检一律走客户端库
  2. 客户端路径从实例属性拼：`installPath(attr_id) → EASYOPS_installPath`，脚本 `os.path.join(install_path,'bin','mysqladmin')`；无 installPath 则 fallback `'mysqladmin'` 走 PATH
  3. 直接用命令名（`'mysqladmin'`），靠目标主机 PATH 解析（适用 ping/df/cat 通用命令）

#### 3.6.4 脚本必须输出的两组标记（协议核心）
平台用正则从 stdout 解析（`msg_parser.go:11-46`，正则大小写不敏感）。缺了无法归属结果。

**标记1：instanceId 标记（必须，结果归属）**
```
print ("-------INSTANCE ID START---------")
print (EASYOPS_instanceId)
print ("-------INSTANCE ID END---------")
```
Shell 版用 `echo`。规则：取第一个匹配，去除非字母数字字符。不输出此标记→结果无法归属到巡检实例。

**标记2：指标输出标记（核心，指标数据）**
```
print ("-------start-------")
print (json.dumps(metric_groups))
print ("-------end--------")
```
- 标记之间是**指标组数组** JSON：
```json
[
  {"id": "<指标组id>",           // ↔ metrics.yaml 指标组 id
   "vals": [
     {"id": "<指标id>", "value": 45.5}    // ↔ 组内 vals[].id；value 数值或字符串
   ],
   "dims": [
     {"id": "hostname", "value": "srv-01"}   // 可选维度
   ]
  }
]
```
- **id 对应关系（最关键约束）**：`payload[].id ↔ metrics.yaml 指标组的 id`；`payload[].vals[].id ↔ metrics.yaml 组内 vals[].id`
- 脚本输出的 id 若在 metrics.yaml 没定义→该值被丢弃（CleanMetricGroup 清洗）；metrics.yaml 定义了但脚本没输出→该指标无数据
- value 类型：`interface{}`，数值（float32/int）或字符串（对应 vals[].type）

#### 3.6.5 阈值判定（在平台层，不在脚本里）
脚本只输出原始值，平台按 metrics.yaml 的 conditions 判定等级+算分。判定规则见 3.8。

#### 3.6.6 退出码契约
资料未明确列退出码语义（如 0=成功/非0=失败的具体映射），但明确：脚本执行失败（status!=ok）→ Score=MinScore(0)，target 状态=failed。

#### 3.6.7 真实脚本范式（weblogic 实测）
- shebang `#!/usr/local/easyops/python/bin/python` + `reload(sys); sys.setdefaultencoding('utf-8')`（py2）
- import psutil/subprocess/re/json（可用 psutil）
- single_command 封装 `subprocess.check_output(shell=True)`
- 非 root 用户自动 sudo 前缀

### 3.7 参数设计（args）

参数定义在 `collectors/script.py` 的 `args` 字段（YAML 数组）。

**arg 字段定义**（源码 `collector/message.go:21-46`）：

| 字段 | 类型 | 必填 | 枚举/默认 | 含义 |
|---|---|---|---|---|
| `key` | string | ✅ | - | 参数键名。注入为脚本变量名（custom 时直接用 key；attr_id 时注入 `EASYOPS_<key>`） |
| `alias` | string | ✅ | - | 参数显示名（中文，如『用户名』『密码』） |
| `type` | string | ✅ | `text`\|`password` | 参数类型。text=普通文本；password=密码（加密存储） |
| `require` | bool | ❌ | default `false` | 是否必填 |
| `source` | string | ✅ | `custom`\|`attr_id` | 参数来源。custom=用户填写；attr_id=从 CMDB 实例属性自动取 |
| `default` | string | ❌ | - | 默认值。custom 适用；attr_id 忽略 |
| `memo` | string | ❌ | - | 参数说明 |

**source 取值规则：**

**custom（用户填写）**：
- 注入无前缀变量 `key=value`，空转 None
- example_key：`username`/`password`/`port`/`db_name`
- 适用：连接参数（用户名/密码/端口/库名）等用户每次巡检可能不同的值

**attr_id（从 CMDB 实例属性自动取）**：
- 注入 `EASYOPS_<key>` 前缀变量
- example_key：`ip`/`hostname`/`connectInfo`/`homePath`
- ⚠️脚本里读 attr_id 参数必须用 `EASYOPS_<key>`，不是 `key`！
- 对照表（按 source 决定脚本变量名）：
  - `source:attr_id` → `globals().get("EASYOPS_" + key)`（ip/hostname 等）
  - `source:custom` → `globals().get(key)`（username/password/port/db_name）
  - 内置 → `globals().get("EASYOPS_instanceId")`
- 约束：attr_id 的 key 必须 info.objectid 指向的 CMDB 模型有此属性，否则取不到值（None）

**设计原则（instance_driven_design）**：能用 CMDB 实例属性的尽量用 attr_id，减少用户每次填参负担：
- 连接地址/IP/端口 → attr_id（ip/ports/connectInfo）
- 安装路径/home目录 → attr_id（installPath/homePath），用于定位客户端命令
- 凭证（用户名/密码）→ 实例 connectInfo 里有就 attr_id；否则 custom + type:password
- 业务参数（库名/实例名）→ custom
- 开发前先 `object_model.detail` 看目标模型有哪些属性可用

**type 类型规则（password 安全规范）：**
- **text**：普通文本参数，明文存储与传输。用于用户名/端口/库名/路径等非敏感参数
- **password**：密码参数，加密存储，运行时解密后注入脚本（脚本侧用 key 取值，无感知加密）。用于密码/凭证/token
- ⚠️**密码安全规范（必守）**：密码/凭证类入参**即使是用户自己手填**（source:custom），也必须 `type:password`，禁止当 text 明文存储——明文密码会在 detail 回显/任务参数/日志中泄漏。判定：参数值是凭证内容（password/secret/token/passphrase）→ `type:password`，无论 source 是 custom 还是 attr_id。

**MySQL 巡检 args 范例：**
```yaml
args:
  - {key: ip, alias: IP地址, type: text, require: true, source: attr_id, default: ""}
  - {key: port, alias: 端口, type: text, require: false, source: custom, default: "3306"}
  - {key: username, alias: 用户名, type: text, require: true, source: custom, default: ""}
  - {key: password, alias: 密码, type: password, require: true, source: custom, default: ""}  # ⚠️password 类型
  - {key: db_name, alias: 数据库名, type: text, require: false, source: custom, default: "mysql"}
  - {key: charset, alias: 字符集, type: text, require: false, source: custom, default: "utf8mb4"}
  - {key: slow_query_threshold, alias: 慢查询阈值(秒), type: text, require: false, source: custom, default: "2"}
```

### 3.8 指标与阈值

阈值定义在 `metrics.yaml` 的 `vals[].conditions`，平台执行后比对判分。源码 `task/message.go:130-151`（Condition 结构）、`constants.go:36-99`（level/score 常量）、`metrics/message.go:393-431`（导入校验）、`history/parse_result.go:129-227`（v1 判定+评分）。

#### 3.8.1 Condition 字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `comparators` | string | 比较器。枚举：`between`/`gt`/`lt`/`eq`/`neq`/`in`/`nin`。int/num 型用 between/gt/lt/eq/neq；string 型用 in/nin/eq/neq |
| `level` | integer | 告警等级。⚠️仅 `0`/`5`/`10`，分别对应 notice（提示）/warning（警告）/emergency（紧急） |
| `value` | string | 阈值。仅为 type==string 服务（in/nin 包含串、eq/neq 比较串） |
| `maxValue` | float32 | 区间上限。仅为 type==int 的 between 服务 |
| `minValue` | float32 | 区间下限。仅为 type==int 服务（between 区间/gt 触发下限） |

#### 3.8.2 EmergencyLevel 枚举与评分常量

| level | name | 中文 | score |
|---|---|---|---|
| -1 | normal | 正常 | 100（level_to_score） |
| 0 | notice | 提示 | 80 |
| 5 | warning | 警告 | 50 |
| 10 | emergency | 紧急 | 20 |

- 评分常量：`MaxScore=100`、`MinScore=0`、`NoticeScore=80`、`WarningScore=50`、`EmergencyScore=20`
- 权重常量：`MaxWeight=100`、`MinWeight=0`

#### 3.8.3 指标类型与 comparator 约束（导入强校验）

⚠️e2e 实锤（2026-08-13 .90 建 mysql 套件）要点：
1. **conditions 可空**：套件定义时 conditions 留空数组 `[]` 是常态（真实 20 套件的指标 conditions 全空）——阈值通常在【任务】里配（task.vals 覆盖），套件定义只定指标结构。源码校验仅在 conditions 非空时逐条检查。
2. **type 实际值是 num**：真实数据的数值型指标 `type="num"`（非源码注释的 int）——string/num 两种。
3. **validator 必填**：建指标组必填 id/name/category/vals（category 两级点分）。

**string 类型**：
- 允许 comparator：`in`/`nin`/`eq`/`neq`
- 禁用：`between`/`gt`/`lt`
- 禁用字段：maxValue/minValue（值非 0 也拒）
- 报错：『string型指标不能指定between/gt/lt的int类型』『string类型指标不能设置maxValue和minValue』

**num 类型**：
- 允许 comparator：`between`/`gt`/`lt`
- conditions 非空时必须 between/gt/lt 之一
- 约束：
  - `between`：maxValue >= minValue
  - `gt`：maxValue 应为 0（无值）
  - `lt`：minValue 应为 0（无值）

#### 3.8.4 判定逻辑（平台执行后比对）

**数值型**：
- `gt`：采集值 >= minValue → 触发该 level
- `lt`：采集值 < maxValue → 触发
- `between`：minValue <= 采集值 < maxValue → 触发

**字符串型**：
- `in`：condition.value 包含 采集值 → 触发
- `nin`：不包含 → 触发
- `eq`：相等 → 触发
- `neq`：不等 → 触发

**多 conditions**：一个 val 可配多个 conditions（不同 level 各一条），取触发的**最高 level** 为该指标等级。

#### 3.8.5 评分算法（v1）

1. 假设所有指标满分：`total = Σ(MaxScore × weight)`
2. 对每个异常指标扣分：`numerator -= (MaxScore - levelScore) × weight`（levelScore：notice=80/warning=50/emergency=20）
3. `score = numerator / Σweight`，保留 2 位小数
4. `total<=0` 时返回 MinScore(0)
- 例：2 个指标（weight 各 50）——A normal(100分)、B emergency(20分)。total=10000；numerator=10000-(100-20)×50=6000；score=6000/100=60 分

#### 3.8.6 target 状态判定

| target 状态 | 规则 |
|---|---|
| failed | 脚本执行失败（status!=ok）→ Score=MinScore(0) |
| abnormal | 脚本成功 + 有异常指标（level>=0 至少一条触发） |
| normal | 脚本成功 + 无异常指标 |

**job 状态**：
- `ok`：只要有 1 个 target 正常执行（normal/abnormal）
- `failed`：全部 target 失败
- `passingRate`：`passingCount(normal+abnormal) / totalTargets`

#### 3.8.7 metrics.yaml 阈值配置范例（MySQL 巡检）

```yaml
- id: connection_status
  name: 连接状态
  category: 连接状态.基础              # 两级点分，正好 1 个点
  pluginid: mysql
  dims: [{id: hostname, name: 主机名}]
  vals:
    - id: alive
      name: 存活状态
      type: int                         # ⚠️实测应用 num
      unit: ""
      weight: 30
      conditions:
        - {comparators: lt, level: 10, maxValue: 1, minValue: 0}    # 采集值<1（挂了）→ emergency
    - id: threads_connected
      name: 当前连接数
      type: int
      unit: ""
      weight: 20
      conditions:
        - {comparators: gt, level: 5, maxValue: 0, minValue: 500}    # >500 → warning
        - {comparators: gt, level: 10, maxValue: 0, minValue: 1000}   # >1000 → emergency
- id: version_info
  name: 版本信息
  category: 整体状态.版本
  pluginid: mysql
  vals:
    - id: version
      name: MySQL版本
      type: string
      unit: ""
      weight: 5
      conditions:
        - {comparators: eq, level: 0, value: ""}    # string 型用 eq/in/nin
```
设计原则：category 两级点分；关键指标 weight 高（存活 30），信息类 weight 低（版本 5）；数值型多 level 分层配置；脚本输出 vals[].id 必须与此处 id 一一对应。

### 3.9 导入流程与冲突策略

**导入顺序**：`ImportModels`（CMDB 模型，失败忽略）→ `ImportInfo`（套件，失败返回）→ `ImportMetrics`（指标组，失败回退删套件）→ `ImportCollector`（脚本，失败回退删套件+指标组）→ `ImportReport`（模板，失败忽略）。

**冲突策略（不幂等）：**
- `INSPECTION_INFO` 唯一键 = `id` 和 `name`。重复导入 id 或 name 已存在的套件直接报 `E11000`『已存在重复的实例』（mongo 重复键）
- 重复导入须先 DELETE 旧套件（级联删全部对象）再导，或改 pluginId+name
- 报错对照：`code=100006 ERR_ABORTED「已存在重复的实例」` = id/name 唯一键冲突；`「数据写入部分失败」` = instanceId 等必填字段空/格式错
- 「数据写入部分失败」触发条件：info.yaml 的 instanceid 空（CMDB 要求非空，需填 13hex）；各对象残留旧 instanceid/internalid 导致冲突。修复：每个对象 instanceid 都换新（13hex 时间戳格式，参考真实导出包 `606133b8ac335`）
- **回退**：metric 失败删 info；collector 失败删 info+metrics；model/report 失败不回退

**counterSideId 写入限制（import_only_caveat，重要踩坑）：**
- API `create`（POST /api/v1/inspection）：service 层 `info_service.go:127` 把 `CounterSideId` 赋值注释掉了，API 建的套件 counterSideId **永远空**
- API `update`（PUT /api/v1/inspection/{pluginId}）：`fieldsToSet` 白名单不含 counterSideId
- **import 包导入**：走 manager 层 CreateInfo，Convert2Struct 全字段写入，**唯一能写 counterSideId 的路径**
- 结论：要 counterSideId 有值（关联主机生效），必须用 import 包导入

**导出流程**：拉套件信息→拉指标组→拉报告模板→拉脚本（硬编码 limit 3000）→拉关联 CMDB 模型→CreateTar 组装。响应 `application/octet-stream`，`Content-Disposition: attachment;filename=<pluginId>.tar.gz`。api-cli 二进制契约：下载 `response.format: binary`（非 `type: file`）；上传 `content_type: multipart-form-data` + `params.file: {in: formData, format: binary}`。

### 3.10 开发流程（develop-inspection-kit）

`name: develop-inspection-kit`，intent：根据巡检需求开发巡检套件（4对象：info+collector+metric_group+template）→ API 逐对象建 → 建任务执行 → 查结果。trigger：`["开发巡检套件","做个巡检插件","开发MySQL巡检","巡检套件开发","新增巡检"]`。guard：规划挡。

#### 3.10.1 硬前置门禁（禁止跳过）
1. **需求确认**：向客户对齐巡检对象/指标/参数来源/阈值
2. **CMDB 模型确认**：`object_model.list`/`detail` 查巡检目标模型是否存在（如 `MYSQL@ONEMODEL`），detail 看 attrList 是否够（如 ip/ports）。有→记 objectId；无→step 3
3. **模型设计+客户确认**（仅 step 2 无模型时）：设计 objectId/属性/关系，客户确认后 `object_model.import` 建。影响套件 keys + collector args 的 attr_id

prerequisites env：`EASYOPS_INSPECTION_BACKEND_URL`/`EASYOPS_CMDB_BACKEND_URL`/`EASYOPS_ORG`/`EASYOPS_USER`。

#### 3.10.2 关键步骤（12 步）
- **step 4 建 info**：必填 `id/name/index/objectId/relationIdWithHost/method`。id=pluginId（英文唯一）；isSystem:false。⚠️counterSideId 此时传了也不入库——正式建走 step 7 import。
  - dataflow：`POST /api/v1/inspection body {id,name,objectId,objectName,method:"agent",keys:["ip"],isSystem:false,isApp:false,index:0,relationIdWithHost:"ARTIFACT_INST@ONEMODEL_host_artifactInsts_HOST"}`
- **step 5 建 collector**：body 含 script(python)/args(参数定义)/content(py2源码)。
- **step 6 建 metric_group**（循环）：type 用 num；category 两级点分；vals[].id 必须与脚本输出精确对应；conditions 常空 `[]`。
  - dataflow：循环 `POST /api/v1/inspection/{pluginId}/metric-groups body {id,name,pluginid,category:"整体状态.版本",dims:[{id:"hostname"}],vals:[{id,name,type:"num",weight,conditions:[]}]}`
- **step 7 【🔴关键】正式建套件**：把 4 对象打成 tar.gz 包走 import（`POST /api/v1/inspection-import`）。唯一能写入 counterSideId+报告模板的可靠路径。包结构根目录=`<pluginId>/`。⚠️导入前先删旧套件（DELETE 级联删全部对象）；每个对象 instanceid/internalid 填新值(13hex)。
  - expect：code:0。随后 `insp_info.get` 验证 counterSideId=host 已写入、report-templates 有模板
- **step 8 本地验证脚本**：设参数变量跑脚本，确认输出 INSTANCE ID 标记 + start/end 标记包裹的指标组 JSON。
- **step 9 建 task**（触发执行）：必填 `pluginId/name/performanceTargets/specifyHostPolicyInstanceId/targets/templateId/taskType/taskScheduler`。args 填连接参数。
  - dataflow：`POST /api/v1/inspection/{pluginId}/task body {name,performanceTargets:"specifyHost",specifyHostPolicyInstanceId:"",targets:[{instanceId}],templateId:"",taskType:"once",taskScheduler:"<时间>",args:[{key,value}]}`
- **step 10 查 history**：list 返回 jobId/status(failed|ok)/score/passingRate
- **step 11 查 history 详情**：`targets[].status: normal/abnormal/failed`。脚本执行失败→failed(0分)，但证明下发链路通
- **step 12（可选）导出 Excel**：二进制流走 `curl -o` / SDK

#### 3.10.3 关键注意
- 🔴**正式建套件走 import 包（step 7），不走 API create**——因为 counterSideId 只有 import 能写入（关联主机必需）。API create/update 路径（step 4-6）用于：① 验证各对象端点可用 ② 理解各对象字段 ③ 单独建 collector/metric_group（这俩 API 可写入）。import 包适合「正式建套件」「从其他环境搬迁完整套件」场景。
- script 协议关键：参数是脚本头部变量注入（attr_id 来源注入 `EASYOPS_` 前缀，custom 来源注入同名变量），不是环境变量；必须输出 INSTANCE ID 标记（结果归属）+ start/end（指标数据）。
- side_effects：`insp_template.delete` 被任务引用拒删；`insp_metric_group.update` 删 val 级联。
- rollback：逐对象删 `insp_collector.delete → insp_metric_group.delete → insp_info.delete`。
- acceptance：前端 `${EASYOPS_CMDB_FRONTEND_URL}/next/automatic-inspection/suite`；API `insp_info.get <pluginId>` 验证套件、`insp_history.list` 验证执行。

### 3.11 巡检套件注意事项 / 踩坑

**套件结构/导入：**
1. **巡检套件 ≠ 采集套件**！存储/包格式/脚本协议全不同，勿混用。
2. **pluginId 一致性强校验**：所有文件 pluginId 必须相同=info.id，不一致报『套件信息中,pluginId存在不同值』。
3. **counterSideId 写入限制**：API create/update 写不进，**只有 import 包导入能写入**。要关联主机生效必须走 import。
4. **导入不幂等**：重复 pluginId/name 报 E11000『已存在重复的实例』，需先 DELETE 旧套件（级联删全部对象）再导。
5. **instanceId 格式坑**：每个对象的 instanceid 都必须填新值（13hex 时间戳格式，参考 `606133b8ac335`）；残留旧 instanceid/internalid 会触发『数据写入部分失败』。
6. **回退有限**：metric 失败删 info；collector 失败删 info+metrics；但 model/template 失败**不回退**。
7. **正式建套件走 import（step 7），不走 API create**——counterSideId+报告模板只有 import 能写入。
8. `script.py` 文件名误导：内容是 YAML，不是 Python 源码；Python 源码在 content 字段。
9. v1 只导出第一个脚本。

**指标组/阈值：**
10. **category 必须两级点分**（如 `整体状态.连接数`），**正好 1 个点**，否则报『分类格式错误』。
11. **vals 必填，至少 1 个**。Update 时 vals 也必填。
12. **vals[].type 仅 string|num**（真实数据用 num，非源码注释的 int）。
13. **conditions 可空**：套件定义时常空 `[]`，阈值通常在任务里配。
14. **string 型禁用 between/gt/lt，禁用 maxValue/minValue**（值非 0 也拒）。
15. **num 型 conditions 非空时必须 between/gt/lt 之一**；between 要求 maxValue>=minValue；gt 时 maxValue 应为 0；lt 时 minValue 应为 0。
16. **删 val 级联**：更新时删掉的 val 会同步从 task 和 report_template 删除引用；删组级联删模板和任务中的引用。
17. **level 仅 0/5/10**（notice/warning/emergency），对应 80/50/20 分；多 conditions 取最高 level。
18. **vals[].weight 0-100**。

**脚本协议：**
19. **参数是脚本头部变量注入，不是环境变量**：source:attr_id 注入 `EASYOPS_<key>`（加前缀），source:custom 注入 `<key>`（无前缀）。
20. **attr_id 参数在脚本里必须读 `EASYOPS_<key>`**，不是 `key`！否则取不到值（None）——巡检脚本 failed 的常见原因。
21. **必须输出两组标记**：INSTANCE ID START/END（结果归属）+ start/end（指标组数组 JSON）。缺了无法归属结果。
22. **id 精确对应**：脚本输出 `payload[].id ↔ metrics.yaml 指标组 id`，`payload[].vals[].id ↔ 组内 vals[].id`。
23. **命令路径严禁硬编码**，三选一：首选 Python 客户端库直连；次选 installPath 拼路径；最后用命令名靠 PATH。
24. **py2.7 语法**：默认解释器；shebang 可覆盖。py2 规范：`reload(sys); sys.setdefaultencoding('utf-8')`；subprocess 不用 timeout 参数；print 语句风格。
25. **执行用户 root 硬编码**；非 root 用户自动 sudo 前缀。
26. **阈值在平台层判分，不在脚本里**——脚本只输出原始值。

**参数设计：**
27. **密码/凭证类入参必须 type:password**，即使 source:custom 用户手填，禁止 text 明文。
28. **attr_id 的 key 必须 info.objectid 指向的 CMDB 模型有此属性**，否则取不到值（None）。
29. **设计原则**：能用 CMDB 实例属性的尽量用 attr_id（ip/ports/connectInfo/installPath/homePath），减少用户每次填参；凭证视情况 connectInfo 里有就 attr_id 否则 custom+password；业务参数（库名/实例名）custom。
30. key 用英文，alias 中文（界面显示）。

**任务/调度：**
31. **task 8 必填**：pluginId/name/performanceTargets(specifyHost)/specifyHostPolicyInstanceId(空串)/targets(巡检目标 instanceId)/templateId(空串)/taskType(once|crontab)/taskScheduler(once=`2006-01-02 15:04:05`)。
32. **inspection 不内置 cron**，定时委托外部 scheduler 服务（到点回调 inspection 的 callback URL）。
33. **vals 阈值覆盖**：task.vals 用 valSet=false 时用自定义 conditions，否则用套件默认。

**删除副作用：**
34. **insp_template.delete**：被巡检任务引用时拒删（『已关联巡检任务，不可删除』）。
35. **insp_metric_group.delete**：级联删除 report_template 和 task 中的引用。
36. **insp_info.delete**：建议先删关联对象（metric_group/collector/template）或用导入导出对账，避免孤儿数据。
37. **insp_task.delete**：同步删外部 scheduler 注册。

**二进制/导入导出：**
38. **api-cli 二进制契约**：下载 `response.format: binary`（非 `type: file``）；上传 `content_type: multipart-form-data` + `params.file: {in: formData, format: binary}`。

**v1/v2 体系：**
39. .90 平台当前用 v1（INSPECTION_INFO 20 套件）；v2（INSP_SUITE 0 套件）未启用。开发新套件仍走 v1。v2 包格式 `suite.json`（单文件组合式）+ `tools/<toolId>.tar.gz`，是未来方向但当前无数据。

---

## 4. ITSM 流程开发（表单 + BPMN 流程）

### 4.1 定位

- **后端服务**：`flowable_service` 微服务，端口 **8134**（HTTP，无 path 前缀，每 operation 持完整路径 `/api/flowable_service/...`）。流程引擎为 **Flowable**（BPMN 2.0 引擎，set_main 才把 BPMN 部署到引擎，回填 deploymentId）。
- **鉴权**：直连后端 `endpoint.auth: none`，但必须带 endpoint 级固定 header `org`（`${EASYOPS_ORG}`）+ `user`（`${EASYOPS_USER}`），由 orguser 中间件校验（缺一报"org、user获取失败"）。此外每端点校验 `itsc:form_management_{access,create,update,delete}` 4 个 action 权限（缺报 403）。写操作用户 `easyops` 具备这 4 权限。cookie 仅网关面需要，直连非必需。
- **流程（process）三层体系**（与表单同构）：
  1. `process_definition`（ITSC_PROCESS）—— 流程定义层，list/create/edit/delete
  2. `process_version`（ITSC_PROCESS_VERSION）—— 版本层，list/get[V2]/create/edit/delete/set_main
  3. `process_form`（ITSC_PROCESS_FORM_RELATION）—— 表单绑定层，set（绑/解/换节点表单）
- **版本内容**：`bpmnXML`（标准 BPMN 2.0 XML + flowable:扩展）+ `processSetting`（`{nodeSettings, lineSettings}` 节点配置 JSON，存为 JSON 字符串）+ `stageSetting`（阶段）。
- **流程与表单的关系**：表单绑到【节点】（`userTaskId`）非整个版本；一个版本每个节点一条表单关系。`useFormBuilder=false`（老表单）时后端默认取表单主版本绑定。
- **版本机制**：一个 def 多版本 1:N，同时仅一版 `isMain=true`（由 set_main 保证，旧主自动降级）。状态机两态：`unfinished`(草稿)/`done`(完成)，**无 draft/published 叫法**。`done` 版可被引用/可设主版本；**done 版本不可编辑**（报"当前版本已完成，不可修改！"），要改须 create + baseVersionId 派生新版本。**只有 set_main 才把 BPMN 部署到 Flowable**（建/改版本都不部署）。
- **sys-setting 关系**：工作日历 `work_calendar` 在独立微服务 `sys_setting:8271`（id 24hex MongoDB ObjectId，≠ flowable_service 的 13hex）。被 SLA 的 `slaConfig[].levelConfig[].workingCalendarId` 引用——跨 system 接力。因 api-cli 不支持 per-resource 绑不同端口，必须独立 spec + system。

### 4.2 流程定义（BPMN）

#### 4.2.1 BPMN 包结构（7 要素，缺一致命错）

1. `<bpmn2:definitions>` 含 xmlns: `bpmn2`/`xsi`/`bpmndi`/`dc`/`di`/`flowable` + `id` + `targetNamespace="http://bpmn.io/schema/bpmn"` + `xsi:schemaLocation="...BPMN20.xsd"`（后两个缺→140200 部署失败）
2. `<bpmn2:process id="ITSC-PROCESS-ID" name="ITSC-PROCESS-NAME" isExecutable="true">`（占位符 + isExecutable 必须有，缺→复杂流程部署失败）
3. `<bpmn2:userTask>` V2 只保留核心 flowable:属性（见 4.2.3），老属性全集→复杂流程部署失败
4. 条件表达式：整体在 `${}` 内——非表单决策 `${pass==1}`；表单决策 `${resourceType=='pm'}`（全在 `${}` 内，字符串用单引号）。缺 `${}` 包裹→140501 表达式错误
5. `formExpressionName` = `变量名:userTaskId.containId.index.componentId.valueField`（jsonPath，如 `resourceType:Task_leader.c_base.0.hostType.value`）
6. `processSetting.nodeSettings` 配 `rejectNodes`/`allowedOps`/`scriptSettings` 等（驳回靠 rejectNodes，不画反向 sequenceFlow）
7. BPMN 合规要点：节点名 ≤20 字不重名 / 网关不直连网关 / userTaskId 正则 / 全连通

#### 4.2.2 节点类型枚举

容器：`bpmn:Process`、`bpmn:SubProcess`。
Task 族：`bpmn:Task`(裸 task 报错)、`bpmn:UserTask`、`bpmn:ServiceTask`、`bpmn:SendTask`、`bpmn:ReceiveTask`、`bpmn:ManualTask`、`bpmn:BusinessRuleTask`、`bpmn:ScriptTask`。
其它 Activity：`bpmn:CallActivity`（子流程，`calledElement=ITSC+defId`）。
事件：`bpmn:StartEvent`、`bpmn:EndEvent`、`bpmn:IntermediateCatchEvent`、`bpmn:IntermediateThrowEvent`、`bpmn:BoundaryEvent`。
网关：`bpmn:ExclusiveGateway`(排他)、`bpmn:ParallelGateway`(并行)、`bpmn:InclusiveGateway`(包容，**被禁用**)、`bpmn:ComplexGateway`(复杂，**被禁用**)、`bpmn:EventBasedGateway`。
连线：`bpmn:SequenceFlow`、`bpmn:MessageFlow`。

#### 4.2.3 userTask flowable 扩展属性（V2 核心，opsAllowed 等放 nodeSettings）

- `flowable:assignee`（占位符 `{{.loginUser}}` 提单人 / `{{.lastExecLeader}}` 上一步领导 / 指定用户名 / `{{.formValue}}` 表单动态）
- `flowable:assigneeValue` / `flowable:assigneeType` / `flowable:assigneeList` / `flowable:assigneeGroup`
- `flowable:strategy`（如 `emptyAssign` 空/跳过策略）
- `flowable:handling`（如 `directly`）
- `flowable:isFormDecision`（`1`=表单决定流转触发节点）
- `flowable:formExpressionName`（变量映射 DSL）

#### 4.2.4 连线/网关/条件

- `<bpmn2:sequenceFlow sourceRef="..." targetRef="...">` 内嵌 `<bpmn2:conditionExpression xsi:type="bpmn2:tFormalExpression">${变量=='值'}</bpmn2:conditionExpression>`
- 网关 `default` 属性指向默认流；出边 >1 时无条件且非默认的流报错
- 驳回：`nodeSettings.rejectNodes=["节点id:线名"]`（不画反向 sequenceFlow）
- 会签：`multiInstanceLoopCharacteristics`

#### 4.2.5 processSetting 结构

`{"lineSettings":[], "nodeSettings":[{...}]}`。nodeSettings 每节点一条，按 `userTaskId` 关联 BPMN 节点。NodeSetting 字段示例：
```json
{"userTaskId":"Task_leader","memoLevel":1,"allowedOps":["assignee","distribute","cc"],
 "rejectNodes":["Task_review:驳回技术复核"],
 "nextAssigneeSetting":{"enabled":false,"nextAssignees":[]},
 "scriptSettings":{"preScript":{},"postScript":{}},
 "suspendSetting":{"isAutoActivate":false,"activateTime":-1}}
```

### 4.3 BPMN 合规校验规则（check_compliance.py，共 32 条全 error）

> 等级定案：宁可误报不可漏检，全部 error，无永久关闭。

1. **conditional-flows**：网关有 default 或任一出边有条件时，出边 >1 且某条既无条件又非 default → "序列流缺少条件"。
2. **end-event-required**：Process/SubProcess 缺 EndEvent。
3. **event-sub-process-typed-start-event**：triggeredByEvent 的 SubProcess 内 StartEvent 缺 eventDefinition。
4. **no-complex-gateway**：禁用 ComplexGateway。
5. **no-disconnected**：Task/Gateway/SubProcess/Event/CallActivity（非 triggeredByEvent）无入/出边 → "进程有未连接的元素"；StartEvent 无出边、EndEvent 无入边也报。
6. **no-duplicate-sequence-flows**：相同 src#dst#conditionBody 的重复序列流。
7. **no-gateway-join-fork**：网关同时 incoming>1 且 outgoing>1 → "网关不能同时合并和分叉"。
8. **branch-gateway-only**（EasyOps 扩展）：Task/Event/CallActivity/SubProcess 出边 >1 → "分支点必须在网关上"，应插排他网关再分叉。比 no-implicit-split 严，不看条件只看出边数。
9. **no-implicit-split**：Task/Event 出边中无条件且非 default 的 >1 → "流程隐式分裂"。
10. **no-inclusive-gateway**：禁用 InclusiveGateway。
11. **single-blank-start-event**：容器内多个无 eventDefinition 的 StartEvent。
12. **single-event-definition**：Event 有 >1 个 eventDefinition。
13. **start-event-required**：Process/SubProcess 缺 StartEvent。
14. **sub-process-blank-start-event**：非 triggeredByEvent 的 SubProcess 内 StartEvent 有 eventDefinition → "子流程开始事件必须为空事件"。
15. **superfluous-gateway**：网关 incoming==1 且 outgoing==1 → "网关多余"。
16. **inclusive-gateway-appear-in-pairs**：容器内 InclusiveGateway 数为奇。
17. **parallel-gateway-appear-in-pairs**：容器内 ParallelGateway 数为奇。
18. **gateway-cannot-be-directly-connected**：Inclusive/Exclusive/ParallelGateway 与同类网关直连。
19. **gateway-cannot-be-directly-connected-to-end**：Inclusive/ExclusiveGateway 直连 StartEvent 或 EndEvent。
20. **form-decision-vars-consistent**（EasyOps 扩展）：网关出边表达式变量必须存在于紧邻上游节点的 `flowable:formExpressionName` 声明变量集；声明未用仅 warn；R3 运行时取值路径存在性（段数<4/节点不存在/无绑定表单/容器不存在/控件不存在五类全拦）。
21. **flow-conditional-error**：Inclusive/Exclusive/ParallelGateway 出口 >1 时每条流须 `${...}` 包裹条件，否则报；上游是表单决定流转节点时校验变量名一致。
22. **inclusive-gateway**：InclusiveGateway（incoming<=1）前节点必须设 isFormDecision=1。
23. **form-flow**：网关前节点非表单决定流转时表达式符号必须用 `==`。布尔语义：不报 当且仅当 body 含 `==`；空/纯标识符/含 `>` `>=` `<=` `<` `!=` `!==` 一律报。
24. **auto-pass**：UserTask strategy 非 emptyAssign 且非表单决定流转时，后接 Inclusive/ExclusiveGateway 报错。
25. **sub-process-start**：StartEvent 直连 CallActivity 报"开始节点不能直接连接子流程"；CallActivity 后接 Inclusive/ExclusiveGateway 报错。
26. **sub-process-quote**：Parallel/InclusiveGateway 后多个 CallActivity 引用同一 calledElement 报错。
27. **name-required**：UserTask/CallActivity 名称重复、名称 >20 字、名称空/空白。
28. **flow-elements-length**：Process/SubProcess 无 UserTask → "进程缺少用户任务"。
29. **is-empty-element**：裸 `bpmn:Task`（非子类型）→ "节点类型错误"。
30. **diagram-required**（EasyOps 扩展）：缺 `<bpmndi:BPMNDiagram>` → 设计器报 "no diagram to display"（图形层，与流转逻辑无关）。
31. **diagram-element-missing**：BPMNDiagram 存在但 BPMNShape/BPMNEdge 全空。
32. **form-expression-path-resolvable**（EasyOps 扩展）：`formExpressionName` 运行时取值路径存在性。格式 `var:userTaskId.containId.<row>.componentId[.valueField]`：段数<4 / userTaskId 非流程节点 / 无绑定表单 / containId 不在容器集 / componentId 不在控件集 全拦。需 `--form-bindings` 启用；不传仅做格式层校验。前端 bpmnlint 无此规则（前端靠级联选择器结构性规避），直调 API 时这里是唯一防线。

**表达式变量提取**：去 `${}`、`&&`→and、`||`→or，剔除字符串字面量（`'pm'`/`"vm"` 是比较值非变量），排除保留字（and/or/not/true/false/null/undefined/True/False/None/in/is）与函数名（标识符紧跟 `(`）。

入口：`python3 check_compliance.py <file|XML|-> [--json] [--include-off] [--no-exit-code] [--form-bindings <json|@file>]`。有 error 且无 `--no-exit-code` 则退出码 1。

### 4.4 流程布局（relayout）

- **作用**：读入 bpmnXML（含烂 DI 或纯语义无 DI），重算全部节点坐标 + 正交连线，流程语义零改动（只重写 `BPMNDiagram` 的 `dc:Bounds`/`di:waypoint`）。语义元素树逐项等价。
- **算法四步**：① 长边虚拟节点化（跨层 span>1 的边拆虚拟链）② 排序以零逆序为收敛判据（median 双向 sweep + transpose + 固定 seed 随机重启）③ 坐标保序落位 ④ 列间通道轨道 x 分配（消除共线重叠；出入口一律边沿中点）。
- **布局常量（px）**：`MARGIN_X=60, MARGIN_Y=60`、`COL_GAP=120`、`ROW_GAP=40`、`EPS=1e-9`。
- **节点标准尺寸**（bpmn.io 约定）：Gateway 50x50；Event 36x36；其它（task/callActivity/subProcess）100x80。
- **命名空间**：前缀统一用 `bpmn`（而非源文件的 `bpmn2`）——URI 不变，语义等价。
- **几何校验器**（CLI 内置）：节点重叠 / 连线穿节点 / 边-边交叉 三主指标非零 → exit 1（`--no-strict` 降级）。
- **入口**：CLI `python3 relayout.py <in> [-o out] [--svg out.svg] [--no-strict]`；库 `from relayout import relayout_xml`（XML 串进出）。
- **坐标纪律**：**BPMNDI 不手写**——LLM 只产纯语义 XML（7 要素，不含 BPMNDiagram），组装完调 `relayout_xml()` 自动算 DI。生成即优化，勿事后补救。存量烂图补救见 `flows/relayout-process-diagram.yaml`。

### 4.5 表单（form-kit）

#### 4.5.1 表单结构

- `formDefinition` 是 **JSON 字符串**（wire 层 string），= `[]Container`（容器平铺列表）。save/update 传 `JSON.stringify([]Container)`；get 返回需二次 `JSON.parse`。
- 容器类型：`row`、`tabs`（控件在 `tabPanes[].propertys`）、`table`、`business_table`、`CMDB_INSTANCE_OPERATE_CONTAINER`（cmdb 实例操作容器，前端跳过该容器控件校验）。
- 容器字段：`key`/`modelField`（容器 id）、`name`（标题）、`type`、`propertys`（控件数组，**少 y**）、`options`（`condition`/`layout`/`layoutConfig`/`listenStart`/`listenEvents`/`enableSlaCale`/`slaCaleFields`/`frontKey`/`cmdbInstanceChangeModel`）、`tabPanes`、`extraProps`。
- 控件字段：`key`/`modelField`（控件 id）、`label`（标题）、`type`、`options`（`required`/`defaultValue`/`disabled`/`pattern`/`placeholder`/`layout`/`layoutSpan`/`labelCol`/`remoteFunc{toolId,scriptInputs}`/`rules`/`extraProps`/`dataType`/`displayCondition`/`belongToSection` 等）、`cmdbProps`（CMDBINSTANCESELECT 用：`class`/`foreignObjectId`）。

#### 4.5.2 控件类型枚举

INPUT、TEXTAREA、RICHTEXT、NUMBERINPUT、RADIO、CHECKBOX、SELECT、MULTIPLESELECT、SWITCH、UPLOAD、LARGEFILE_UPLOAD、SLIDER、TIME、DATE、COMMONDATE、TIMERANGE、DATERANGE、LINK、MODALSELECT、CASCADER、ARRATINPUT、CMDBINSTANCESELECT、CMDBCASCADER、USER_SELECTOR、USER_GROUP_SELECTOR、DEPARTMENT_SELECTOR（源 `internal/enums/field_kind/enum.go:7-34`）。

老平台映射：input→INPUT/textarea→TEXTAREA/radio→RADIO/checkboxes→CHECKBOX/select→SELECT(静态)或 CMDBINSTANCESELECT(CMDB)/date→DATE/dateRange→DATERANGE/uploadComponent→UPLOAD/multiSelect→SELECT(多选)；html/button/placeHolder 跳过。

#### 4.5.3 枚举类数据源字段路径（关键，迁移极易错位）

- `SELECT` / `MULTIPLESELECT` / `CHECKBOX` → `extraProps.items`
- `RADIO` / `CASCADER` / `MODALSELECT` → `extraProps.options`

（迁移踩坑：RADIO 选项写成 items 前端保存报"的数据源未配置，请添加"）

#### 4.5.4 layout 坐标语义

`y=行号`，同 `y` 挤一行。逐控件 `y` 必须递增（enumerate 序号）：一行一控件 `y=i w=12`；一行两列同 `y`、`x=0/6`、`w=6` 且 `layoutSpan` 同 `w`。**全写 `y=0` 会导致所有控件挤一行**。前端 form-renderer Lm 组件 `groupBy(y)→Row` 佐证。

#### 4.5.5 form-validator.py 校验规则

**A 表单元信息**（新建/编辑弹窗）：
- A1 `FORM_NAME_REQUIRED`：名称必填
- A2 `FORM_NAME_LENGTH`：`^[\s\S]{1,20}$`（≤20 任意字符）
- A3 `CATEGORY_REQUIRED`：分类必填
- A4 `FORM_ID_PATTERN`：`^[a-zA-Z]\w{0,29}$`（字母开头，字母数字下划线 ≤30）
- A5 `FORM_DESCRIPTION_MAX`：说明 ≤500 字符

**B 标准字段**：
- B1 `FIELD_KEY_REQUIRED`：唯一标识必填
- B2 `FIELD_KEY_PATTERN`：`^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$`（字母数字开头，可含 `.` `_` `-`，≤35）

**C 数据源**：
- C1 `DS_NAME_PATTERN`：`^(?![0-9])[一-龥A-Za-z0-9_]+$`（中英文数字下划线，数字不在首位）
- C2 `DS_NAME_UNIQUE`：名称不与 dataList 重名
- C3 `DS_ARGS_VALID`：按 9 种 type 校验 provider 参数
- C4 `DEBUG_RESULT_TYPE`：转换结果必须是对象或数组

数据源 type 枚举（9 种）：`cmdb-detail`(a,b 必填)、`cmdb-count`(a,b 必填)、`cmdb-count-multi`(a.objectList 每项含 objectId)、`cmdb-list`(b.fields 必填)、`cmdb-group`(b.group_fields+b.funcs 必填)、`cmdb-columndb`(a.database+measures+group_by+object_ids 必填)、`cmdb-olap`(a.model+measures+dims+filters 必填)、`http`(a+b.method 必填)、`dynamic`(args 非空)。`static` 无分支放行。

**D 版本发布**：
- D1 `VERSION_REQUIRED`：版本号必填
- D2 `VERSION_PATTERN`：`^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$`（三段式 x.y.z，每段 1-3 位数字）
- D3 `VERSION_MEMO_PATTERN`：`^[^\s]{1,20}$`（说明 ≤20 且不含空白字符）

**E 设计器保存链**（getFormData 三层）：
- **E-S1~S12 容器**：S1 非空 / S2 标题必填非空白 / S3 标题 ≤20 / S4 id 必填 / S5 id 格式 `^(?![0-9]+$)[a-zA-Z0-9_@]+$`（非纯数字）/ S6 id 唯一（跨容器 Set 查重）/ S7 事件触发对象非空（listenStart 时）/ S8 事件脚本非空（listenEvents[0].remoteFunc.toolId）/ S9 SLA 计算字段非空（enableSlaCale 时）/ S10 table 禁多模型 / S11 cmdb操作容器须模型（cmdbInstanceChangeModel.objectId）/ S12 cmdb操作容器须展示列（options.frontKey 非空）
- **E-F1~F9 控件**：F1 标题必填 / F2 标题 ≤20 / F3 id 必填 / F4 id 格式（同 S5）/ F5 id 唯一（同容器内 Set 查重，按容器分桶不跨容器）/ F6 MODALSELECT 须事件脚本 / F7 脚本必填入参有值 / F8 CMDBINSTANCESELECT 排序字段至多 1 个 / F9 单排序须选字段
- **E-P2~P9 属性面板**：P2 Tab 页签 ≥1 个 / P3 页签标题 `^\S{1,128}$` / P4 枚举类数据源已配置 / P5 每项 label+value trim 非空 / P6 value 无重复 / P7 numberSetting 数值顺序（step≥0 / min≤default≤max）
- 前端 validateAllForm 跳过：`BUSINESS_TABLE`、`BUSINESS_CMDB_INSTANCE_CHANGE_TABLE`、`CMDB_INSTANCE_OPERATE_CONTAINER` 三种容器。
- 字段/容器 id 正则 `ID_RE`：`^(?![0-9]+$)[a-zA-Z0-9_@]+$`；Tab 页签标题 `TAB_PANE_RE`：`^\S{1,128}$`。
- **关键：后端不拦任何设计器规则**（实测：label>20 / modelField 重复/空 / 枚举无数据源等 update 全部 code=0 放行）——绕过前端直调 API 须自跑本校验器兜底，否则带病数据落库但前端打不开/保存不了。
- 入口：CLI `check-form|check-field|check-datasource|check-debug-result|check-version|check-controls`。

#### 4.5.6 控件 options 权威字段（缺了前端 t.map 渲染崩）

- SELECT/RADIO：`dataIndex='label'`
- UPLOAD：`dataType='filearray'` + `defaultValue=[]` + `dataIndex='fileName'` + extraProps 按钮配置
- CHECKBOX：`defaultValue=[]`
- 全部控件：`extraProps.fieldAttr=[]`

### 4.6 流程/表单的 resource+verb

#### 4.6.1 process_definition
- `list` GET `/v1/process_definition`：params `name`/`category`/`creator`/`Q`(模糊)/`isMain`(boolean)/`page`/`pageSize`。不返 bpmnXML/processSetting。
- `create` POST `/v2/process_definition`：body required `[name, category]`；可选 `memo`/`triggerIdList`/`useFormBuilder`(默认 false)。**name 全局防重**——同名报 409 ERR_ALREADY_EXISTS"已存在同名流程"。
- `edit` PUT `/v2/process_definition/{definitionId}`：非 upsert，须传已存在 definitionId。改 name 防重（排除自己）。required `[name, category]`。
- `delete` DELETE `/v1/process_definition/{definitionId}`：有版本拒绝"存在流程定义版本，不允许删除"；须先清版本；幂等；末版本级联删 def。

#### 4.6.2 process_version
- `list` GET `/v1/definition/{definitionId}/version`：`versionId` 支持 `"lastest"` 别名取最新。不返 bpmnXML/processSetting。
- `get` GET `/v2/definition/{definitionId}/version/{versionId}`：返回 bpmnXML + taskInfo + lineSettings + stageSetting。
- `create` POST `/v2/process_definition/{definitionId}`：body required `[bpmnXML, versionName, state, processSetting]`；可选 `memo`/`baseVersionId`(克隆表单关系+阶段，不克隆 bpmnXML/processSetting)。**建版本不部署 Flowable**。
- `edit` PUT `/v2/process_definition/{definitionId}/version/{versionId}`：仅 unfinished 可改。required `[bpmnXML, versionName, state, processSetting]`。
- `delete` DELETE `/v1/definition/{definitionId}/version/{versionIds}`：路径参数 versionIds（复数分号）但只删第一个。约束任一即拒(HTTP 412)：①绑表单 ②关联工单 ③主版本+绑服务 ④被父/子流程引用。末版本级联删 def。
- `set_main` PUT `/v1/definition/{definitionId}/version/{versionId}`：须 state==done。旧主自动降级。运行中工单不受影响（仍走旧 deploymentId）。偶发 140500→重试。已主版本幂等。
- `state` 枚举：`unfinished` / `done`

#### 4.6.3 process_form
- `set` POST `/v1/process/version/{versionId}`：body required `[userTaskId]`；`useFormBuilder`(boolean，默认 false)/`formRelationInstanceId`/`formId`/`fbFormId`/`fbFormInstanceId`/`formDisplayMode`/`isDesensitization`。
- 动作组合：①都空=无操作 ②formRelationInstanceId空+formId非空=绑定 ③formRelationInstanceId非空+formId空=解绑 ④都非空=换绑。

#### 4.6.4 form
- `list` GET `/v1/form`：`state` 枚举 `[unfinished, done]`（过滤的是版本状态）；`isMain`(boolean)。返回字段 `lastestMainVersion`/`lastestVersion`（拼写少 t，API 如此）。
- `save` POST `/v2/form`：required `[name, category, formDefinition, state]`；`state` 枚举 `[unfinished, done]`；`versionName` pattern `^\d+\.\d+\.\d+$`。**非 upsert，永远新建 form + 首版本 isMain=true，formId/versionId 不可指定**。可选 `memo`/`versionMemo`/`businessRules`/`domainModelId[]`/`dataSourceIdList[]`。
- `delete` DELETE `/v1/form/{formId}`：有版本拒绝"表单存在版本,无法删除"；须先清版本；幂等；末版本隐式级联删 form。

#### 4.6.5 form_version
- `list` GET `/v1/form/{formId}/version`：`name` 实为 versionName 精确匹配；`state` 枚举 `[unfinished, done]`。返回 `versionInfo` + `processVersions`。
- `get` GET `/v2/form/{formId}/version/{versionId}`：返回 formDefinition(字符串)+businessRules+formSchema+domainModel[]+standardFields[]+formDataSources[]+userDisplayMap。V2 比 V1 多返 businessRules/domainModel[]/formDataSources[]。
- `update` PUT `/v2/form/{formId}/version/{versionId}`：required `[name, category, formDefinition, state]`。**upsert 非对称**：done 版→新建 isMain=false 草稿；unfinished→就地改。同时改 form.name/category/memo。versionName 唯一（重复报"重复的表单版本号"）。
- `delete` DELETE `/v1/form/{formId}/version/{versionIds}`：路径参数 versionIds（复数分号）但只删第一个。被流程节点引用拒绝"表单已绑定节点，不可删除!"。末版本隐式级联删 form。
- `set_main` POST `/v1/form/{formId}/version/{versionId}`：须 state==done。旧主自动降级。旧主被流程绑定时触发 ITSC_PROCESS_FORM_RELATION 换绑。已主版本幂等。

#### 4.6.6 id 格式
- flowable_service 资源 instanceId：**13 hex**（微秒时间戳）。definitionId/versionId/formId/triggerId/notifyPolicyId/slaId/groupId 均 13hex。
- triggerId 正则 `^[0-9a-z]{13}$`。
- work_calendar id：**24 hex**（MongoDB ObjectId）。

### 4.7 开发流程

#### 4.7.1 build-process（建流程定义+版本+绑表单+审批+表单决定流转）

步骤链：`process_definition.create` → 构造纯语义 BPMN + processSetting（本地，守 7 要素，坐标勿手写）→ `relayout_xml()` 自动算 DI → `process_version.create` → `process_form.set`（显式绑表单，不靠 baseVersionId 克隆——克隆不可靠）→ `check_compliance.py`（0 error 门禁，含 `--form-bindings` 取值路径校验，formId 绑定后才能查故在绑表单之后）→ 用户前端验收 → `process_version.set_main`（部署生效）。

错误码：140501 表达式错误→查 `${}` 包裹；140200 部署失败→查 7 要素；140500 set_main 偶发→重试，仍败核对 state==done。

驳回：`nodeSettings.rejectNodes=["Task_review:驳回技术复核"]`（格式 `节点id:线名`），不画反向 sequenceFlow。

#### 4.7.2 migrate-legacy-process（老平台 modelInfo.txt 迁移）

输入：modelInfo.txt（结构化 JSON，含 `workflowModelNodeList`(type:2子流程/3网关/4审批 + userSelectType/distributeType/处理人)、`workflowModelSequenceList`(sourceNodeCode/targetNodeCode/name/sequenceRule 条件)、`formInfos[0].configs`(表单控件树)）+ 流程 md。start/end 是序列表虚拟 code（节点表里没有）。

四类映射决策表：
1. 加签回路（独立加签节点+回环边）→ 剔除节点，父节点 `nodeSettings.allowedOps` 含 `'add'`
2. 子流程（type=2）→ 先建占位子流程 def（start→userTask→end 最小版）再 callActivity 引用（`calledElement=ITSC+defId`）
3. 处理人：静态部门/角色→'easyops' 占位；userSelectType=3 表单动态→`flowable:assignee="{{.formValue}}"` + assigneeValue=表单字段；取发起人→`"{{.loginUser}}"`
4. 条件自动路由：`sequenceRule{conditionFilter all/any, subItems[keyField eq/ne valueCode]}` → 上游决策节点 isFormDecision=1 + formExpressionName + 网关出边 `${变量=='值'}`（变量名必须=决策节点声明变量——form-decision-vars-consistent 规则查）
5. 网关直连网关（老平台常见）→ 合并消除：GW_a-[cond_a]->GW_b 删边，对 GW_b 每出边在 GW_a 复制 `(cond_a && cond_b)` 合并边
6. 节点名繁体→简体
7. 表单按阶段拆分绑定（老平台一张大表单绑全部节点=设计不合理）：拆分边界=老表单 row/分组结构；每张阶段表单独立 form.save→update(done)→set_main，再 process_form.set 绑到对应节点；字段一一对应零丢失（拆分前后 modelField 计数核对）；枚举数据源路径按类型区分。

字段名保真：modelField 用 `configs.dataSource.methods` 里 `children[].ctrid↔ctrCode` 映射（流程 formExpressionName 引用它，不可重造）。

#### 4.7.3 relayout-process-diagram（存量重排）

步骤：`process_version.list` 选源版本 → `process_version.get` 拉 BPMN + processSetting（get 参数 definitionId 在前）→ 本地 `relayout.py` 重排 → done 版须 create 派生新版本（**done 不可 edit**），unfinished 草稿可 edit 覆盖 → 前端验收 → edit 改 state="done" → set_main 发布。

坑：①processSetting 传对象非字符串（API 请求须传对象，传字符串报 `readObjectStart: expect { or n`）②done 不可 edit ③get 参数 definitionId 在前 ④算法前缀重写 `bpmn2:→bpmn:` 属正常（URI 等价）。

#### 4.7.4 build-form（新建表单）

步骤：构造归一化 formDefinition（本地，必须补全前端字段，否则白屏崩）→ `form-validator.py` 门禁（check-controls + check-form + check-version，0 fail）→ `form.save` → `form_version.get` 回读确认。

归一化必补：容器加 `condition/layout/layoutConfig/modelField/displayCondition`；控件加 `belongToSection` + 完整 options（`layout/layoutSpan/labelCol/defaultValue/disabled/enabled/highLight/isMore/only/pattern/placeholder/note/question/displayCondition/remoteFunc{toolId,scriptInputs}/rules/extraProps/dataType/required`）。最稳：get 一个正常表单的 formDefinition 作模板，改 type/label/modelField/extraProps.items。

### 4.8 ITSM 注意事项 / 踩坑

**鉴权/接入：**
1. 直连 flowable_service:8134 必须 `org`+`user` header（orguser 中间件），缺一报"org、user获取失败"。cookie 非必需。
2. 写操作还需 `itsc:form_management_{access,create,update,delete}` 4 权限，缺报 403"鉴权失败"。写用户用 `easyops`。
3. sys_setting:8271 与 flowable_service:8134 不同端口，必须独立 spec+system，CLI `--spec` 切换。

**表单（连环坑）：**
4. `form.save` 非 upsert，永远新建 form + 首版本，formId/versionId 不可指定。
5. 无单 form 详情端点（GET /form/:formId 不存在），取元信息走 list 或 form_version.get 的 formSchema 子对象。
6. `form_version.update` 非对称：done 版→派生新草稿，unfinished→就地改。done 版上更新版本号要 +1（如 1.0.0→1.0.1），否则"重复的表单版本号"。
7. update 全量覆盖——必带完整 formDefinition + name/category + versionName。
8. set_main 须 state==done；done 版 update 会派生新草稿，须 form_version.list 找到新 versionId 再 set_main。
9. 验证：form list 看 `lastestMainVersion.formDefinition` 非空（空=白屏/t.map 崩）。
10. `form_version.list` 的 `name` 参数是 versionName 精确匹配（非 form 名），别用它找表单。
11. 删 form 须先清所有版本；删最后一个版本隐式级联删 form。
12. `form_version.delete` 路径参数 versionIds（复数分号）但只删第一个——批量是壳。被流程节点引用拒绝。
13. 字段名 `lastestMainVersion`/`lastestVersion` 拼写少 t（API 如此）。
14. formDefinition/businessRules 在 wire 层是 JSON 字符串，save 传 `JSON.stringify([]Container)`，get 需二次 parse。

**流程（连环坑）：**
15. `process_definition.name` 全局防重——撞名报 409。迁移场景先 list 查名，撞名加后缀。
16. 建版本不部署 Flowable——须 set_main 才生效。set_main 须 state==done。
17. done 版本不可编辑（"当前版本已完成，不可修改！"）——要改须 create + baseVersionId 派生。
18. baseVersionId 克隆表单关系+阶段，但**不克隆 bpmnXML/processSetting**（仍须 request 给）。克隆不可靠——build-process 显式 process_form.set 绑表单。
19. `process_version.delete` 路径 versionIds（复数分号）但只删第一个。4 约束任一即拒(HTTP 412)。
20. `process_version.list` 的 `versionId` 支持 `"lastest"` 别名。
21. list/get/delete/set_main 走 `/definition/:definitionId/...`；create/edit 走 `/process_definition/:definitionId[/version/:versionId]`——路径 disparate，resource.path 留空，每 op 持完整路径。
22. processSetting 传**对象**非字符串（传字符串报 `readObjectStart: expect { or n`）。
23. set_main 偶发 140500→重试即好。

**BPMN/布局纪律：**
24. BPMNDI 不手写——LLM 只产纯语义 XML，调 `relayout_xml()` 自动算 DI。
25. V2 userTask XML 只保留核心 flowable 属性（opsAllowed/setAssignee 等全放 nodeSettings）。
26. 条件表达式整体在 `${}` 内，字符串用单引号。
27. 节点名 ≤20 字、不重名、不空白；userTaskId 正则；全连通；网关不直连网关；分支点必须上网关。
28. 表单决定流转：触发节点 isFormDecision=1 + formExpressionName(jsonPath) + 网关出边 `${变量=='值'}`。变量名必须=决策节点声明变量。
29. 驳回靠 nodeSettings.rejectNodes，不画反向 sequenceFlow。
30. 子流程占位也应 set_main，否则主流程 callActivity 部署可能解析失败。
31. StartEvent 不能直连 CallActivity；CallActivity 后不能接 Inclusive/ExclusiveGateway。
32. `displayUserTaskId`（监听节点）只在跨节点条件显示填（displayCondition 引用别的流程节点表单控件时）；引用本节点控件不填。
33. 表单决定流转（后端 govaluate 求值决定走线）与表单 displayCondition（前端求值决定显隐）是**不同套**机制。

**表单设计器纪律：**
34. 后端不拦任何设计器规则——本地 form-validator 是唯一防线。落库前必过 check-controls + check-form + check-version。
35. 控件标题/容器标题 ≤20 字。
36. 控件/容器 id 正则 `^(?![0-9]+$)[a-zA-Z0-9_@]+$`（非纯数字）。
37. 字段 id 唯一（按容器分桶，不跨容器查）。
38. 枚举类数据源路径严格按控件类型：SELECT/MULTIPLESELECT/CHECKBOX→`extraProps.items`；RADIO/CASCADER/MODALSELECT→`extraProps.options`。
39. layout.y 必须逐控件递增，全写 y=0 会挤一行。
40. versionName 三段式 `^\d+\.\d+\.\d+$`；versionMemo ≤20 无空白。
41. formDefinition 归一化：缺 options.layout/belongToSection/remoteFunc/rules 等会白屏崩。

**通用：**
42. 系统自带（builtin）触发器/通知策略/日历/服务目录勿动勿删。
43. delete 路径参数批量是壳（versionIds/triggerIds/ruleIds/groupIds 分号但只删第一个）；notify_policy.delete 例外——instanceIds 走 query 非 path。
44. SLA list 是 POST `_search`（GET 返 404），分页参数在 body。
45. notify_policy 前缀是 `/api/itsc_trigger/v1`（≠ 其它 flowable_service 前缀），但仍 8134 端口。
46. work_calendar id 24hex（≠ flowable_service 13hex），印证不同存储。

---

## 5. 跨系统骨架与 platforms 资料规范

> 本节面向「维护/扩展套件知识的开发者」——即 `api-orchestrator` 的 onboarding 模式。orchestration（编排执行）模式下 platforms/ 只读，不涉及本节。

### 5.1 platforms 资料总体架构

5 类位置各司其职：

| 文件 | 职责 | 装什么 |
|---|---|---|
| `systems.yaml` | 接入 | 系统清单、api-cli spec 路径、接入面（endpoints）、鉴权、运行时知识（租户/用户/端口/env）、capabilities |
| `objects.yaml` | 对象关系 + 副作用 | 对象结构（fields/relations/constraints）+ 操作副作用（side_effects）+ 接口级行为（api_behavior） |
| `entities.yaml` | 字段锚 + 转换 | 主键/关键字段格式（anchor/format/pattern/used_by）+ 跨实体/跨 step 字段接力（transitions） |
| `flows/*.yaml` | 流程模板 | build/change 类端到端步骤序列（含 dataflow/expect/on_fail/rollback） |
| `formats/<fmt>/` | 格式包 | 跨部署复用的格式知识（BPMN/插件/表单/巡检等） |
| `<system>.yaml` | api-cli 清单 | 命令树 + body/response schema |
| `README.md` | 索引 | 资料地图导航，**不承载知识主体** |

### 5.2 单一真相源（文件间，禁全文复述）

同一事实在 platforms 内**只在一个权威文件写全文**，其余仅放一句话 + 指针。权威层级表（低→高）：

| 知识类型 | 唯一权威文件 | 下游文件只能放指针 |
|---|---|---|
| 格式/协议/机制/真实套件范式（跨部署） | `formats/<fmt>/*.yaml` | objects/flows/spec/README |
| 对象副作用/接口行为（本部署） | `objects.yaml.side_effects` / `api_behavior` | flows/README |
| 接入/端口/鉴权/运行时坑 | `systems.yaml.runtime` | objects/flows/README |
| 字段格式/主键 | `entities.yaml` | objects/flows |
| 端到端步骤 | `flows/*.yaml`（步骤本身，非规则） | — |

判定：写到某字段时自问「这句话的全文是否已在更权威的文件里存在？」是 → 删成本文换成指针。flow 的步骤值（API 请求体示例、要填字段）是步骤操作的一部分，不算复述，保留。

### 5.3 systems.yaml 字段

顶层骨架：
```yaml
deployment: <deployment-name>      # 如 demo
platform_conventions:                # 平台级公约（deployment 级，跨所有系统）
  code:
    rule: |                          # 平台涉及代码的默认规则（见 0.2）
    exceptions:                      # 领域例外清单 {domain, why, scope}
  auth: |                            # 平台级鉴权公约（见 0.3）
systems:
  <system>:
    description: ...
    spec: <system>.yaml
    default_endpoint: <endpoint-name>
    endpoints: {...}
    auth: <auth-name>
    env: {...}
    capabilities: {...}
    common_models: {...}             # 仅 cmdb
    runtime: {...}
    acceptance_urls: {...}
```

- **`deployment`**（必填）：部署名，如 `demo`。
- **`platform_conventions`**：平台级公约。`code.rule`（默认 py2/自包含/py2-3 兼容）、`code.exceptions`（领域例外，如 sdk/easyops_client.py）、`auth.rule`（直连后端免 cookie）。
- **`systems.<system>`** 字段：
  - `description`（必填）：系统职能概述。
  - `spec`（必填）：api-cli 清单文件名。
  - `default_endpoint`（必填）：默认 endpoint 名（通常 `backend`）。
  - `endpoints`（必填）：接入面清单。每 endpoint 含 `base_url`（支持 `${ENV_VAR}`）、`host`、`auth`、`headers`。三种形态：`backend`（直连后端，auth=none）/ `frontend`（前端网关 HTTPS，需 cookie）/ `openapi`（AK/SK 签名，`path_prefix: /cmdbservice`）。
  - `auth`（system 级）：指向部署根 `auth.d/<auth-name>.yaml`。demo 值：`easyops-cookie` / `collector-cookie` / `easyops-openapi` / `none`。
  - `env`（契约字段，仅声明变量名 + 用途，值在部署根 `env.d/<dep>.env`，**勿从此处取**）。
  - `capabilities`（必填）：能力清单 `resource.verb → 用途描述`。编排挡据此判断意图可达性。
  - `common_models`（仅 cmdb）：常用模型速查表 + `count_recipe`（计数配方）。
  - `runtime`（必填，接入知识，真相来源，自由扩展键）：`admin_user`/`env_required`/`ports`/`host_header`/`auth`/`cookie_optional_direct` + 各系统特有键。
  - `acceptance_urls`（可选）：前端验收 URL，支持 `${ENV_VAR}` 与 `{placeholder}`。

### 5.4 objects.yaml：对象关系 + 副作用规则

对象块字段：
```yaml
<object>:
  description: ...
  source: <后端源码路径>            # 溯源（file:line / 枚举接口 / 契约），非"详见此处"
  api: <resource>                  # 对应 api-cli resource
  fields:
    <field>:
      type: string|integer|bool|array|object|any
      required: true               # ⚠️schema 属性级 required 是 bool 单字段；schema 父级 required 是 []string
      anchor: true                 # 是否主键/锚（entities.yaml 详述）
      ref: <other-object>          # 引用另一对象
      items: <type-or-object>      # array 时
      enum: [a, b]
      pattern: '<regex>'
      default: <value>
      desc: "..."
  relations:
    - to: <other-object>
      type: composition|reference|association
      cardinality: "1:N|N:M|1:1"
      via: <field>
      desc: "..."
  constraints:                     # 不变式
    - "..."
  side_effects:                    # 操作副作用规则（实测，真相来源核心）
    - op: <resource.verb>
      rule: "..."
      source: "..."（可选，溯源）
api_behavior:                      # 接口级行为（跨对象，文件末尾汇总）
  <behavior-name>:
    rule: "..."
    source: "..."（可选）
```

- **字段类型枚举**：`string` / `integer` / `bool` / `array` / `object` / `any` / `"object|null"` / `method`。
- **relations.type 枚举**：`composition` / `reference` / `association`。`cardinality` 字符串如 `"1:N"` / `"N:M"` / `"N:1"` / `"1:1"`。
- **side_effects 写法**：`- op: <resource.verb>`（可加细分，如 `object_model.import（新增属性）`），`rule:` 全文，可选 `source:`。副作用规则（upsert、删除依赖、级联、分页格式、必填 query）最容易被契约漏掉、最值得记。
- **`source` 必填**：lint 门禁校验每个有 `api:` 的 object 必须有非空 `source:`，防探源码步被跳。

### 5.5 entities.yaml：实体映射 + 字段锚 + 转换

```yaml
<field>:
  description: ...
  format: "..."                # 格式约定
  anchor: true|false           # 主键锚
  pattern: '<regex>'           # 可选正则
  rules: ["..."]               # 可选规则列表
  state_machine: "..."         # 可选状态机说明
  trap: "..."                  # 可选易错点提示
  used_by: [<resource>.<verb>] # 哪些操作用它
  namespaces: [...]            # 可选命名空间枚举
  convention: "..."            # 可选约定说明
```

**关键锚 pattern 总表：**
- 13hex 实例 id（cmdb/autoops execute/itsm 全域/collector/inspection task/history/dashboard）：`^[0-9a-z]{13}$`。
- tool_id / tool_vId / tool_version_id / package_version_id：`^[a-fA-F0-9]{32}$`（32hex）。
- package_id：UUID pattern。
- work_calendar_id：`^[0-9a-fA-F]{24}$`（24hex MongoDB ObjectId）。
- insp_plugin_id：`^[a-zA-Z_][0-9a-zA-Z_]{0,31}$`（英文标识符，如 mysql/weblogic）。
- relateObjectId（collector）：`^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$`。
- object_id 格式：`NAME@NAMESPACE`，namespaces `[EASYOPS, ONEMODEL]`。
- trigger_id/notify_policy_id/sla_rule_id/duty_group_id：`^[0-9a-z]{13}$`。

**transitions 写法**：列表，每项 `- from: <resource.verb>` / `pick: <field>` / `to: [<resource.verb>]` / `how: "..."`；多步接力用 `name`/`desc`/`steps:` 子列表。

### 5.6 flows 模板结构

```yaml
name: <flow-name>
intent: ...                              # 这个流程达成什么
trigger: ["自然语言触发短语"]             # 什么时候用
guard: 直通|确认|规划                     # 对应三挡

prerequisites:                           # 前置
  env: [VAR]                             # 需要的环境变量
  base: "..."                            # 前置条件
  payload: "..."                         # 可选

steps:                                   # 步骤序列
  - n: 1
    op: <resource.verb>                  # 该步操作；纯本地变换用 transform 代替 op
    args: [...]                          # 调用参数（含 --insecure / --body-file / --yes 等 flag）
    desc: ...                            # 步骤说明
    dataflow: "..."                      # 字段怎么从上一步来 / 给下一步
    body_hint: |                         # 可选：请求体示例（属步骤操作一部分，不算复述）
      { ... }
    note: "..."                          # 可选
    expect: "..."                        # 成功标志
    on_fail: "..."                       # 失败处理
  - n: 2
    transform: <本地变换名>               # 纯本地变换步骤（无 op）
    desc: |

key_rule: |                              # 可选：关键规则提示（只能指针，不复述全文）
  ...规则概述 + "见 objects.yaml#X.side_effects"
side_effects: <objects.yaml#object.side_effects>   # 回指，不重复
rollback: "..."                          # 失败回滚步骤
acceptance: "..."                         # 验收方式（URL 或命令）
```

**关键纪律**：`side_effects` / `key_rule` / `note` / `desc` / `expect` 等字段**不得全文复述** objects/api_behavior/systems.runtime 里的规则，只能放一句话 + 指针。`body_hint`/`args` 是步骤操作一部分保留。

### 5.7 formats 格式包结构

`formats/<fmt>/` 跨部署复用的格式知识，与具体系统无关。demo 实测 7 个 kit：`bpmn-kit/`、`collector-kit/`、`dashboard-kit/`、`form-kit/`、`inspection-kit/`、`notify-kit/`、`sso-provider/`。

**组织约定**：formats 是"格式/协议/机制/真实套件范式"的**唯一权威文件**，objects/flows/spec/README 只能指针引用。可含代码（.py，如 bpmn-kit 的 relayout/check 工具）与 yaml schema 并存。sso-provider 这种"实物范本"直接随 skill 包分发，让 LLM/人仿写。

### 5.8 onboarding 纪律（接入新套件/系统）

#### 5.8.1 证据纪律（最高优先）
1. **动态/透传字段的权威源是「真实样例」**，不是 Go struct、更不是字段名。凡字段是 `map[string]interface{}`/`interface{}`/`string`(JSON blob) 弱类型，权威源是：① 仓库 `testdata/` 真实样例；② `get` 一个现成实例捕获；③ 前端 designer 生成产物。不许从字段名推断结构。
2. **「前端解释型内容」的 e2e ≠ save 返回 200**。后端透传、前端解释的 blob（formDefinition / businessRules / 模板字符串 / 自定义 DSL），后端不校验结构——save/update 返回 code=0 只表"存下了"，不代表前端能渲染。须前端渲染验证或从现成实例仿写。e2e 报告明确标"API 已落库，前端渲染待验证"。
3. **无证据不臆测——查不到就标 gap，不许编**。某字段/语法/枚举值查不到权威源时写"未知—待捕获"，不许凭"看起来合理"编。
4. **platforms/ 知识必须自包含——不引用 platforms 以外的文件**。引用外部文件（尤其 `tmp/` 临时、`knowledge/modules/`）= 知识依赖了随时会删的东西，分发即断。`source:` 字段仅标溯源，不是"详见此处获取知识"。

#### 5.8.2 onboarding 流程（7 步）
1. **核对输入 + 门禁 + 识别系统形态**：硬门禁（API 真相来源 ≥1，缺则停下问）；软门禁（凭证/有效账号/测试空间/e2e 场景，缺则 warn）。
2. **理解 API 面（契约 → 端点表）**。
3. **探源码补全 + 拿权威结构**：补端点、权威结构体、校验约束、枚举。⚠️不可跳——步 7 lint 门禁会校验每个 object 块有 `source:`。⚠️load-bearing 真相别托付给 background agent——用 inline bounded grep 查、查完立即内联进 platforms + commit。
4. **写 api-cli 清单**：写作纪律：① 无 `$ref` 全内联；② `required` 双义；③ 资源级 `path:` 留空 `""`，完整 path 只在 operation 级写；④ 每 resource/operation 写 `description`；⑤ 二进制用声明式三字段（上传 `content_type: multipart-form-data` + `params.<name>: {in: formData, format: binary}`；下载 `response: {format: binary}`），别写 `type: file`。
5. **录入 platforms（按 asset-schema 归位）**：知识分文件别堆 README。
6. **e2e 真调验证（阶梯式）**：① 连通+鉴权（只读 GET）② 读路径（list/detail/search）③ 写路径（预检→建→改→删清理）。⚠️**e2e 必须全走 `scripts/run.sh`（api-cli），禁用 curl**——curl 绕过清单验证，等于没验证。
7. **交付 + 自检**：跑 `scripts/lint-platforms.py <deployment>`——校验 asset-schema + 引用闭合 + source 证据门禁。**0 ERR 才算产物合格**。坑即时回流 platforms（**不进记忆**——platforms 是唯一真相来源）。

#### 5.8.3 初始化部署根与首写门禁
- 初始化：`mkdir -p $PWD/.api-orchestrator/{platforms,auth.d,env.d}`。tmp 不在部署根（编排中间产物落项目根 `tmp/`）。`env.d/<dep>.env` 只放业务变量（不放路径变量）。`auth.d` 放密钥。
- **首写门禁**：onboarding 写 platforms 前必须先验证部署根解析后的绝对路径已存在；部署根**不存在** → **停下，打印解析后的绝对路径问用户确认**，禁止隐式 mkdir 到意外 cwd。

### 5.9 常见盲点（实战归纳）

8 条：① 契约不完整（常缺 delete/detail/batch，用源码路由表补）；② 鉴权有隐藏要求（cookie/token 之外常还要租户/用户 header，要 e2e + 源码 grep `Header.Get`）；③ 凭证 ≠ 全部（光有 token 不够，还要租户号 + 有效用户标识 + 测试空间）；④ 写操作有副作用约束（删除可能依赖先删子、导入可能是 upsert、有 protected 不可删）；⑤ 系统自带数据绝不能动（生产库、系统内置租户/命名空间）；⑥ 声明式 vs CRUD（有的系统建/改走声明式导入 upsert，不是逐字段 CRUD）；⑦ 响应格式不定（分页可能流式 NDJSON 非 `{data:{list}}`、单对象可能 wrapper、必填 query 如 `fields`）；⑧ 默认值在配置中心（默认租户/org/namespace 常在运行时配置，源码只看到 fallback）。

---

## 6. 枚举总表

### 6.1 CMDB 采集套件枚举

| 字段 | 枚举值 |
|---|---|
| `type`（套件包类型） | `simple-script`, `metricbeat`, `exporter`（prometheus 直接抓取也填 exporter） |
| `agentType` | `easyops, metricbeat, prometheus, log, zabbix-agent, sql, filebeat, cloudScript, detect, process, cloudSdk, remoteScan, kubernetesClusterAgent, ipCollect, kubernetesScan, localScan, eBPFCollect` |
| `samplerType` | `metric_sampler, process_sampler, event_sampler, trace_sampler, log_sampler, detect_sampler, pipeline_sampler` |
| `scriptType` | `python, shell, json`（json 是 log_plugin 用） |
| `command.collect.type` | `python, shell` |
| `valueType`（paramDefine） | `string, int, boolean, password` |
| `use`（paramDefine） | `collectorParams, instanceMapping` |
| `paramType`（_COLLECTOR_JOB 参数） | `const, cmdb`（仅两个值） |
| `status`（套件状态，只读） | `enabled`(内置/protected 禁覆盖), `available`(自定义/可覆盖) |
| `group` 4 类白名单 | collectMethod: `localScan/remoteScan/cloudSdk`；cloudType: `cloudTypePrivateCloud/...`；collectContent: `collectContentResourceInfo/...` |
| `$.attr` 过滤操作符 | `==, !=, <=, <, >=, >, in, nin, like` |
| `kit.update.dashboardStrategy` | `overwrite, rename` |
| 激活 totalStatus | `success, fail` |
| `dataType`（别名指标） | `double, string, long` |

### 6.2 监控套件枚举

| 字段 | 枚举值 |
|---|---|
| `tool.type`（脚本类型） | `shell, python, perl, powershell, batch, Ansible-PlayBook` |
| `tool.delete.force` | `"true", "false"`（字符串） |
| `tool_execution.run.needNotify` | `"true", "false"`（字符串，默认 true） |
| `vId` 别名 | `$latest_version, $latest_development, $latest_production`（不填=最新生产版） |
| `tool_package.export_check.result` | `success, libNotFound` |
| `tool_package.import.importType` | `create, update` |
| `tool_execution` 状态 | `running, success, failed` 等 |
| `notify_config.msgType` | `email, wework, dingding, dingding_robot, custom` |
| `notify_config.configFields[].type` | `text, password` |
| send 响应 data[method] | 脚本返回值 \| `not support` \| `disable` \| `error` |
| builtin msgType→pluginName | email→`mail`, wework→`wework`, dingding→`dingding_easyops`, dingding_robot→`dingding_robot` |
| `email.serverConfig.encrypt_type` | `ssl, tsl, plain` |
| cmdbUserObjectColName 内置约定 | mail→`user_email`, wework→`wework_userid`, dingding*→`dingding_userid`（实测可用：`user_tel`/`user_email`/`dingding_userid`/`wework_userid`/`name`；⚠️无 `telephone`） |
| `dashboard.dashboardVersion` | `"v2"`（固定） |
| `dashboard.template` | `normal, bigScreen` |
| `dashboard.type` | `"builtIn"`（固定注入） |
| `panel.source` | `"brick"`（固定） |
| `panel.mode` | `default, yaml` |
| `variable.type` | `constant, cmdb-model, cmdb, custom, comparator` |
| `context.type` | `cmdb-list, cmdb-detail, cmdb-count, cmdb-count-multi, cmdb-group, cmdb-olap, cmdb-columndb, http, static, dynamic`(废弃) |
| `context.dataType` | `array, object` |
| http context `method` | `GET, POST` |
| OLAP 聚合算子（`measures[].function.expression`） | `count, min, max, sum, avg, topK, last, divide, increase, rate, irate, quantile` |
| OLAP 过滤算子（`filters[].operator`） | `==, !=, <=, <, >=, >, =~, !~, in, has, nin, and, like, nlike, exists` |
| cmdb-columndb `measures[].op` | `count, sum, max, min` |
| CMDB 比较器（cmdb 系 query.instances.query） | `$like, $nlike, $eq, $ne, $exists:false, $exists:true, $in, $gte, $lte` |

### 6.3 巡检套件枚举

| 字段 | 枚举值 |
|---|---|
| `info.method` | `agent`（远程主机执行，默认） |
| `info.isapp`/`issystem` | `true` / `false` |
| `info.status` | `ok` / `object_deleted` / `keys_deleted` / ...（平台维护） |
| `collector.script` | `python`（默认，py2.7）/ `shell` |
| `arg.type` | `text` / `password` |
| `arg.source` | `custom` / `attr_id` |
| `arg.require` | `true` / `false`（default `false`） |
| `metric_group.vals[].type` | `string` / `num`（⚠️真实数据用 num） |
| `condition.comparators` | `between` / `gt` / `lt` / `eq` / `neq` / `in` / `nin` |
| `condition.level` | `0`(notice) / `5`(warning) / `10`(emergency)；隐含 `-1`(normal) |
| EmergencyLevel name | `normal`(-1) / `notice`(0) / `warning`(5) / `emergency`(10) |
| string 型允许 comparator | `in` / `nin` / `eq` / `neq` |
| string 型禁用 comparator | `between` / `gt` / `lt` |
| num 型允许 comparator | `between` / `gt` / `lt` |
| report_template `displaytype` | `Form` / `Card` / `BasicInfo` / `LineChart` / `BarChart` / `DoughnutChart` / `CycleChart` |
| `task.taskType` | `once`（单次绝对时间）/ `crontab`（cron 表达式） |
| `task.notifyMethod` | `email`（资料仅列此一值） |
| target status | `normal` / `abnormal` / `failed` |
| job status | `ok` / `failed` |

### 6.4 ITSM 流程枚举

| 字段 | 枚举值 |
|---|---|
| form/form_version `state` | `unfinished, done` |
| process_version `state` | `unfinished, done` |
| ticket `status` | `running, done, closed` |
| ticket `action` (set_state) | `suspend`(仅running), `activate`(仅suspended), `cancel`(仅running) |
| service_instance `status` | `enabled, disabled` |
| sla `basicInfo.type` / `scope` | `inst`(工单级，只许1个), `step`(任务节点级) |
| sla `levelConfig.levelName` | `plan, common, priority, emergency` |
| trigger `status` | `enabled, disabled` |
| trigger `scope` | `process_task, process_instance, service_instance, scheduler_ticket, process_instance_sla, process_task_sla` |
| trigger `config.actionList[].name` | `send_message, update_process_instance_status, update_priority, update_service_status, update_process_task_status, exec_tool` |
| notify_policy `notifyType` | `process_instance, process_task, service_instance, duty_shift_change` |
| sla `slaConfig[].notifyPolicy[].notifyType` | `warning, timeout` |
| duty_group `status` | `enabled, disabled` |
| filter `operator` (ticket) | `==, !==, ~, !~` |
| ticket `serviceCategory` | `change, event, req, question, release` |
| 数据源 type (9种) | `cmdb-detail, cmdb-count, cmdb-count-multi, cmdb-list, cmdb-group, cmdb-columndb, cmdb-olap, http, dynamic`（+`static` 无分支放行） |
| BPMN 节点类型 | 见 4.2.2（容器/Task族/Activity/事件/网关/连线） |
| 布局节点尺寸 | Gateway 50x50, Event 36x36, task/callActivity/subProcess 100x80 |
| itsm_form_container.type | `row, tabs, table, business_table, business_cmdb_instance_change_table` |
| itsm_lifecycle_script.hook | `afterDataLoad, preSubmitCheck, onValueChange, componentLoad, instSelect` |
| itsm_process_node_setting.handling | `directly, send_directly, claim_directly, send_claim_directly` |
| itsm_process_node_setting.memoLevel | `-1`(隐藏), `0`(非必填), `1`(必填) |
| itsm_process_node_setting.isFormDecision | `"0", "1"`（字符串） |
| itsm_process_assignee.userType | `loginUser, lastExec, lastExecLeader, historyExec, historyExecLeader, dutyGroup, dutyGroupV2, formValue, userRule, userTree, department, specifyUser` |
| itsm_process_script.hook | `pre, rear, afterDataLoad, preSubmitCheck, onValueChange, componentLoad, instSelect` |
| itsm_process_script.opMode | `sync, async` |
| itsm_process_script.operations | `pass, reject, withdraw, claim, jump, assignee, distribute, cc, add, add_reject`（⚠️"通过时触发脚本"配 `["pass"]` 不是 `["done"]`） |

### 6.5 平台/骨架枚举

| 字段 | 枚举值 |
|---|---|
| `default_endpoint` | `backend`（全系统） |
| endpoint 名 | `backend` / `frontend` / `openapi` |
| `auth` 值 | `easyops-cookie` / `collector-cookie` / `easyops-openapi` / `none` |
| runtime.ports | `8079`(cmdb) / `8111`(user_service) / `8181`(autoops) / `8134`(itsm) / `8271`(sys_setting) / `8151`(collector_plugin) / `8125`(collector_legacy) / `12000`(collector_kit) / `8103`(inspection) / `8095`(msgsender) / `8152`(data_exchange) / `80`(frontend) |
| runtime.protected_orgs | `[0, 1, 2]`（禁动） |
| runtime.test_org | `18832008`(cmdb/autoops/itsm) / `8888`(collector) |
| runtime.admin_user | `easyops` |
| runtime.host_header | `admin.easyops.local` |
| relations.type | `composition` / `reference` / `association` |
| relations.cardinality | `"1:N"` / `"N:M"` / `"N:1"` / `"1:1"` |
| fields.type | `string` / `integer` / `bool` / `array` / `object` / `any` / `"object|null"` / `method` |
| cmdb_attr_value.type | `[int, enum, str, arr, date, datetime, struct, structs, ip, bool, float, json, enums, attachment]`（enum=单选，enums=多选） |
| cmdb_attr_value.default_type | `[value, function, auto-increment-id, series-number]` |

---

## 7. 踩坑 / 填写纪律总集（速查）

> 各套件详细踩坑见对应章节末尾的「注意事项/踩坑」。此处只收**横跨多套件、易被忽视**的通用红线。

### 7.1 编码红线（所有 agent 端脚本）

1. **Python2 运行时**：默认 `/usr/local/easyops/python/bin/python`，py2.7 语法（print 语句、不用 f-string、新式类、编码声明）。
2. **自包含**：单文件即可跑，不得 `import` 项目内其他 `.py`（agent 无 pip / 无项目目录）。
3. **不用 `__future__`**：agent 运行时会在脚本顶部注入内容，`__future__` 不在顶部而报错。
4. **subprocess 不用 timeout 参数**（py3.3+ 才有）；需超时用 `signal.alarm`。
5. **JSON 输出 `ensure_ascii=False`** 保留中文。
6. **HTTP 用 `requests`**（py2 环境已装）。

### 7.2 密码/凭证红线（采集 + 巡检 + 通知）

7. **密码类入参必须加密类型**：采集套件 `valueType:password` + `isEncrypt:true`（即使手填 isFromSecret:false）；巡检套件 `type:password`；通知 serverConfig `configFields[].type=password`（值 base64 传输）。禁止任何形式明文存储凭证。

### 7.3 命令路径红线（采集 + 巡检脚本）

8. **严禁硬编码绝对路径**（如 `/usr/local/easyops/mysql/bin/mysqladmin`）——目标主机没有会 OSError。三选一：首选 Python 客户端库直连；次选 installPath 拼路径；最后用命令名靠 PATH。

### 7.4 参数取值红线（采集 $.attr + 巡检 source）

9. **采集 paramType 铁律**：value 以 `$.` 开头必须 `paramType=cmdb`，否则 const。collector_service 不自动推断。
10. **采集 $.field 必须 relateObjectId 模型真实属性**，否则报错；勿把 agent 环境路径当设备属性。
11. **巡检 attr_id 参数在脚本里必须读 `EASYOPS_<key>`**（加前缀），不是 `key`；custom 来源读同名变量。

### 7.5 前端解释型内容红线（表单 + 大盘 + 告警脚本）

12. **后端不校验设计器规则**：ITSM 表单/流程的 formDefinition、BPMN 结构、dashboard 的 brickConf/selectorQuery、notify 脚本——后端 save code=0 只表"存下了"，不代表前端能渲染/逻辑能跑。须本地校验器（form-validator/check_compliance）兜底 + 前端验收。
13. **dashboard 两套表达式语法**：`<% %>`（JS 求值，用于 brickConf.properties/context.transform/olap args）vs `${QUERY.x|string}`（JSON 内插值，仅用于 variables.selectorQuery）。用错即崩。
14. **dashboard 统计卡 value 必须单值表达式**，禁止直接绑整个数据源（绑数组 → NaN%）。
15. **dashboard 监控指标过滤必用 instanceId**——OLAP 数据一定有 instanceId 不一定有 ip/hostname。
16. **告警脚本含非 ASCII 必须首行编码声明**，否则 py2 加载报 SyntaxError。

### 7.6 导入/版本红线

17. **采集套件 zip 顶层目录名 = plugin.yaml name = 上传 API name**，三处完全一致；ZIP_STORED + UTF-8 flag；mode 755/664。
18. **采集套件 protected 内置套件禁止覆盖**，需改名 + version 从 1.0.0 起独立版本线。
19. **采集套件升级 agentType 不可变**；version 必须唯一。
20. **巡检套件正式建走 import 包**，不走 API create——counterSideId + 报告模板只有 import 能写入。
21. **巡检套件导入不幂等**：重复 pluginId/name 报 E11000，须先 DELETE 旧套件级联删再导；每个对象 instanceid 填新 13hex。
22. **ITSM 表单 form.save 非 upsert**，永远新建 form + 首版本 isMain=true；done 版 update 派生新草稿；set_main 须 state==done。
23. **ITSM 流程建版本不部署 Flowable**，须 set_main 才生效；done 版本不可编辑，要改须 create + baseVersionId 派生。
24. **ITSM processSetting 传对象非字符串**（传字符串报 `readObjectStart: expect { or n`）。
25. **删除路径参数批量是壳**：versionIds/triggerIds/ruleIds/groupIds 分号但只删第一个；notify_policy.delete 例外（query instanceIds）。

### 7.7 二进制/api-cli 边界

26. **api-cli 不支持 multipart/binary 真调**：采集 plugin_package.import/export/import_update、巡检 import/export、autoops tool_package.import/export、msgsender config 多端点——仅 `--print-curl` 预览，真调走 `curl -F` 或 Python SDK（`sdk/easyops_client.py`）。
27. **二进制 spec 声明**：下载 `response.format: binary`（非 `type: file`）；上传 `content_type: multipart-form-data` + `params.file: {in: formData, format: binary}`。
28. **autoops tool.update body 必须 flat**（不套 `{tool:{}}`），否则假成功；inputs 是 map 不是数组；export 是 GET + query `versionId`（非 vId）。
29. **collector_metric 端点在 legacy 进程 :8125**（直 200 免 contract header；:12000 报 giraffe-contract-name 错）——勿用 data_exchange 的 tags-list 查指标元数据（那是空实现桩）。
30. **kit.list 双源合并**：collector_service 返基本信息 + CMDB `_COLLECTOR_EASYOPS_PLUGIN` search 补 status/params/metricSets/collectAgent。

### 7.8 证据纪律（onboarding）

31. **指标名/objectId 勿编造**：dashboard 用 `collector_metric.list` + `object_model.list` 查证；错了后端不报错、图表静默空白。
32. **e2e 必须全走 `scripts/run.sh`（api-cli），禁用 curl**——curl 绕过清单验证，等于没验证。
33. **lint 0 ERR 才算产物合格**：`scripts/lint-platforms.py <deployment>` 校验 schema + 引用闭合 + source 证据门禁。
34. **platforms 知识自包含**：不引用 platforms 以外的文件（tmp/knowledge/源码副本），内部用指针；坑回流 platforms 不进记忆。

### 7.9 鉴权/部署红线

35. **直连后端免 cookie**，org+user+Host 三件 header 即够；不要程序化登录。
36. **写操作用户用 `easyops`**（具备写权限）；系统自带 org `[0,1,2]` 禁动。
37. **部署根不存在则停下问用户**，禁止隐式 mkdir 到意外 cwd；禁止读 skill 自带 platforms/demo 兜底（那是开发样例）。
38. **sys_setting(:8271) 与 flowable_service(:8134) 不同端口**，必须独立 spec+system；work_calendar id 24hex ≠ flowable 13hex。

---

## 附录 A：套件开发速查决策树

```
拿到需求
│
├─ 是采集/监控指标数据？（数据要进 CMDB 或时序库）
│    ├─ 写回 CMDB 实例配置 → 采集套件 + process_sampler（GATHERING DATA 标记）
│    └─ 推时序指标 → 采集套件 + metric_sampler（[{dims,vals}]）
│         └─ 类型选型：自定义脚本→simple-script；复用模块→metricbeat；自带二进制→exporter；直接抓→prometheus 变体
│
├─ 是周期性"体检"巡检对象健康度、产出评分/报告？
│    → 巡检套件（4 对象：info+collector+metric_group+template）
│         └─ 正式建走 import 包（counterSideId/报告模板只有 import 能写）
│
├─ 是告警通知出口 / 第三方告警源接入？
│    → msgsender 通知方式（builtin: email/wework/dingding*；custom: 三方脚本）
│         └─ 写 config 须系统管理员；敏感字段 base64
│
├─ 是监控大盘可视化？
│    → dashboard（_DASHBOARD 实例 + context 数据源 + panels 构件 + variables）
│         └─ 监控数据走 cmdb-olap（v1 平铺点数组）；历史数据走 cmdb-columndb（18 张表）
│
└─ 是 ITSM 流程/工单流转？
     ├─ 表单 → form + form_version（formDefinition JSON 字符串，本地必过 form-validator）
     └─ 流程 → process_definition + process_version（BPMN 语义 XML + relayout 算 DI + check_compliance 0 error）+ process_form 绑表单 + set_main 部署
```

## 附录 B：脚本输出协议对照

| 套件 | sampler/类型 | stdout 格式 | 标记 | 阈值判定位置 |
|---|---|---|---|---|
| 采集（监控） | metric_sampler | JSON 数组 `[{dims,vals,time?}]` | 无 | 资料未覆盖 |
| 采集（CMDB） | process_sampler | 标记包裹 JSON 数组 | `-----BEGIN/END GATHERING DATA-----` | agent 端写回 CMDB |
| 巡检 | script(python/shell) | 标记包裹指标组数组 | `-------INSTANCE ID START/END-------` + `-------start/end-------` | 平台层（conditions） |
| 告警通知 | notify script | run() 返回 list | — | — |

## 附录 C：资料未覆盖（gap，待捕获）

- 采集套件 metric 指标的阈值/告警规则 CRUD 端点（autoops.yaml 无此类 resource）。
- 巡检脚本退出码语义具体映射（0/非0 仅推断）。
- ITSM trigger.action 各 args 完整字段、notify_policy notifyMode 完整渠道、sla levelName/agreementType 完整值域、work_calendar config.mode 值域。
- ITSM 完整 23 控件的 options 权威字段全集（部分从校验器反推）。
- ITSM 5 生命周期脚本完整契约、orderInfo、displayUserTaskId 联动深层结构（objects.yaml#itsm_form_definition / itsm_process_* 未逐字实锤）。
- collector_job 端点 spec（本 deployment 暂未录，kit 能力优先）。
- kit.activate 的 giraffe-contract-name 真实 contract 版本号（待 e2e 探测）。
- ZIP_DEFLATED 格式未真调验证（STORED 已够）。

---

> 文档版本：v1.0（2026-08-25），萃取自 `api-orchestrator` skill `platforms/demo/`。各套件字段/枚举以 platforms 资料为唯一真相来源；本规范是其人读汇总，遇分歧以 platforms 原文为准。
