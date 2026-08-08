---
name: monitor-kit
description: 开发 EasyOps simple-script 类型监控采集插件，生成完整插件包（配置文件、采集脚本、指标定义、告警规则模板），支持采集测试、导入/更新到平台和自动打包。
version: 0.1.0
---
# EasyOps 监控插件开发指南

本 skill 用于指导开发 EasyOps 平台的监控采集插件（simple-script 类型）。

## 插件结构

```
插件名称/
├── plugin.yaml                    # 插件主配置（必需）
├── package.conf.yaml              # 部署配置（必需）
├── <MODEL_ID>.json                # 关联CMDB模型定义（必需）
├── origin_metric.json             # 原始指标定义（必需）
├── alias_metric.json              # 告警指标定义（必需）
├── metric_set.json                # 指标集定义（必需）
├── readme                         # 使用说明（必需）
├── src/                           # 采集脚本目录（必需）
│   ├── <插件名>.orig              # 源代码（不含环境变量）
│   └── <插件名>.py                # 运行代码（含环境变量）
├── alertRule/                     # 告警规则（可选）
├── dashboard/                     # 监控面板（可选）
└── pic/                           # 图标资源（可选）
```

## 开发流程

### 1. 确定监控需求

收集以下信息：

- 监控对象类型（设备、服务、应用等）
- 采集方式（SNMP、HTTP API、命令行、数据库等）
- 需要采集的指标列表
- 采集参数（IP、端口、认证信息等）

### 2. 获取或创建 CMDB 模型

向用户确认模型是否在cmdb以及模型ID

查询现有模型：

```bash
python scripts/get_model.py --model-id MODEL_ID --host <easyops_host> --org <org_id>
```

如果模型不存在，根据需求设计模型属性并创建。

### 3. 生成插件文件

按照 `references/` 中的模板生成各配置文件。

## 配置文件说明

### plugin.yaml 核心字段

字段格式**须**遵循 `references/config-templates.md` 中 `plugin.yaml` 模板

| 字段            | 说明         | 示例                                  |
| --------------- | ------------ | ------------------------------------- |
| type            | 插件类型     | `simple-script`                     |
| name            | 插件名称     | `动环监控`                          |
| version         | 版本号       | `"1769673511"`                      |
| command.collect | 采集配置     | scriptPath、type、interpreter         |
| params          | 参数列表     | `[ip, port, community]`             |
| paramDefine     | 参数定义     | 类型、默认值、是否必填等              |
| relateObjectId  | 关联CMDB模型 | `ENV_MONITOR_SYSTEM_MONITOR_POINTS` |
| category        | 分类         | `硬件相关`                          |
| agentType       | Agent类型    | `easyops`                           |

### 采集脚本规范

采集脚本通过环境变量获取参数，输出 JSON 格式数据：

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os
import json

# 从环境变量获取参数
ip = os.environ.get("EASYOPS_COLLECTOR_ip")
port = os.environ.get("EASYOPS_COLLECTOR_port")

# 采集逻辑...

# 输出格式
info = [{
    "dims": {"dim1": "value1", "dim2": "value2"},
    "vals": {"metric1": 100, "metric2": "string_value"}
}]
print(json.dumps(info, ensure_ascii=False))
```

### 指标定义规范

**重要约束：指标 ID（key/name）不能与关联 CMDB 模型的属性 ID 或关系 ID 相同，否则激活套件会失败。**

命名建议：

- 为指标添加前缀，如 `metric_`、`mon_`、`m_`
- 或使用更具体的命名，如 `cpu_usage` 而非 `cpu`
- 在定义指标前，先查询模型属性列表进行比对

origin_metric.json 定义原始指标：

```json
[{
    "agentType": "easyops",
    "dataType": "double",        // double 或 string
    "key": "metric_name",
    "metricType": "gauge",       // gauge 或 counter
    "tagDefine": [{"name": "dim1", "readOnly": false}]
}]
```

alias_metric.json 定义告警指标：

```json
[{
    "name": "metric_name",
    "displayName": "指标显示名",
    "dataType": "double",
    "objectId": "MODEL_ID",
    "originalMetrics": ["metric_name"],
    "dims": [{"dimName": "dim1", "originDimName": "dim1"}],
    "metricSet": ["默认指标集"]
}]
```

## 采集脚本模板

详见 `references/collect-templates.md`：

- SNMP 采集模板
- HTTP API 采集模板
- 命令行采集模板
- 数据库查询模板

## 示例文件

`examples/` 目录包含完整的监控插件示例：

- `snmp-monitor/` - SNMP 采集插件示例

## 插件命名规范

- **中文**：`XXX监控套件`，如 `动环监控套件`、`数据库监控套件`
- **英文**：大驼峰 + `监控套件`，如 `Tomcat监控套件`、`Redis监控套件`
- **zip 文件名**：`{插件名称}_v{版本号}.zip`，如 `Tomcat监控套件_v1.0.2.zip`

## 采集测试（压缩前）

在打包插件前，询问用户是否需要进行采集测试：

**提示用户：** "是否需要进行采集测试？如需测试请提供环境参数（如 IP、端口、认证信息等），或选择跳过。"

如果用户提供参数，执行采集脚本测试：

```bash
# 设置环境变量并执行采集脚本
EASYOPS_COLLECTOR_ip="192.168.1.100" EASYOPS_COLLECTOR_port="161" python src/采集脚本.py
```

验证输出格式是否正确（JSON 数组，包含 dims 和 vals）。

## 打包插件（带版本号）

测试通过或跳过后，使用打包脚本生成带版本号的 zip 文件：

```bash
.venv/bin/python3 ../resource-collector-kit/scripts/pack_plugin.py output/插件名称
```

脚本自动执行：

1. 读取 `插件名称/.version` 获取当前版本号（不存在则默认 `1.0.0`）
2. 递增 patch 版本号（`1.0.3` → `1.0.4`）
3. 生成 `插件名称_v1.0.4.zip`
4. 更新 `.version` 文件为新版本号

可选参数：`--no-increment` 不递增版本号（重新打包同版本）。

## 导入或更新插件

打包完成后，询问用户是否需要导入或更新到 EasyOps 平台。

### 流程

1. **查询是否存在同名插件**：

```bash
python scripts/search_instance.py --model-id _COLLECTOR_EASYOPS_PLUGIN --query '{"name":"插件名称"}' --host <easyops_host> --org <org_id>
```

2. **根据查询结果处理**：

**如果插件不存在** → 导入新插件：

```bash
# 导入插件
python scripts/plugin_manage.py import --file /path/to/插件名称.zip --name 插件名称 --host <easyops_host> --org <org_id>

# 获取返回的 instanceId，启用插件
python scripts/plugin_manage.py activate --plugin-id <返回的instanceId> --host <easyops_host> --org <org_id>
```

**如果插件已存在** → 更新插件：

```bash
# 从查询结果获取 instanceId 和 packageVersion
# 版本号递增规则：1.0.0 → 1.0.1 → 1.0.2 ...

python scripts/plugin_manage.py update --file /path/to/插件名称.zip --plugin-id <查询到的instanceId> --version <递增后的版本号> --host <easyops_host> --org <org_id>
```

## 生成告警规则模板

插件开发完成后，生成告警规则模板 Excel（用于导入 `ALERT_RULE_TEMPLATE` 模型）。

### 职责划分

| 职责               | 执行者         | 说明                                                              |
| ------------------ | -------------- | ----------------------------------------------------------------- |
| Excel 框架生成     | **脚本** | 表头、合并单元格、固定策略字段                                    |
| 条件骨架生成       | **脚本** | 生成 bigger_than/unequal 骨架（无阈值），携带 metricType 辅助信息 |
| 指标筛选与阈值确定 | **LLM**  | 分析采集脚本语义，判断哪些指标需要告警、确定阈值和比较类型        |

阈值必须由 LLM 分析采集脚本确定，不能硬编码。原因是：指标名称无法准确反映语义（如 `m_mem_fragmentation_ratio` 不是百分比而是比值，`m_connected_clients` 的合理阈值取决于业务规模）。

**哪些指标需要告警也由 LLM 判断**：条件骨架中的 `metricType` 辅助字段标识了指标类型（`gauge` / `counter`），LLM 需据此判断指标是否适合配置告警，不适合的指标应直接从 conditions 数组中删除（而非留空阈值）。典型场景：

- `counter` 类型（如 `request_count`、`error_count`）：累加型指标，值只增不减，静态阈值告警无意义，应删除
- 累计最大值（如 `max_processing_time`）：单调递增，静态阈值同样不适用

### 生成流程

**Step 1 — 生成骨架**

```bash
.venv/bin/python3 scripts/generate_alert_rule_template.py <插件目录>
```

脚本输出：

- `<插件名>_告警规则模板_conditions.json` — 条件骨架，包含指标列表但无阈值
- `<插件名>_告警规则模板.xlsx` — Excel 框架（此时阈值为空）

**Step 2 — LLM 分析采集脚本，筛选指标并填写阈值**

读取采集脚本 `src/<插件名>.orig` 和 `origin_metric.json`，理解每个指标的实际含义，然后编辑 `conditions.json`：

1. **筛选指标**：根据 `metricType` 和指标语义判断是否需要告警，不适合的指标直接从数组中删除
2. **填写阈值**：为每个 `comparators` 项补充 `threshold` 和 `displayThreshold` 字段
3. 根据指标语义调整比较类型（如存活时间应用 `smaller_than`）
4. 根据指标特点设置 `alertCount`、`detectWindow`、`recoverCount`

阈值配置示例：

```json
{
  "metricName": "m_memory_usage_pct",
  "comparators": [
    {"level": "info", "threshold": 0.8, "displayThreshold": 0.8, "tolerance": 0, "type": "bigger_than"},
    {"level": "warning", "threshold": 0.9, "displayThreshold": 0.9, "tolerance": 0, "type": "bigger_than"},
    {"level": "critical", "threshold": 0.95, "displayThreshold": 0.95, "tolerance": 0, "type": "bigger_than"}
  ]
}
```

**Step 3 — 用已填阈值的 JSON 重新生成 Excel**

```bash
.venv/bin/python3 scripts/generate_alert_rule_template.py <插件目录> --conditions-json <已填阈值的conditions.json>
```

### 导入平台

通过 Excel 导入工具将文件导入 `ALERT_RULE_TEMPLATE` 模型即可创建告警规则模板。

## 完成输出

操作完成后，输出以下信息：

1. **套件路径**：`/path/to/插件名称.zip`
2. **套件 URL**（如果已导入/更新）：

   ```
   http://<host>/next/monitor-kit/kit/easyops/<instanceId>/detail?tab=readme
   ```

   示例：`http://172.30.0.90/next/monitor-kit/kit/easyops/6496b82f510f9/detail?tab=readme`

## 常见问题

### 参数传递

- 参数通过 `EASYOPS_COLLECTOR_<param_name>` 环境变量传递
- `$.field_name` 格式表示从 CMDB 实例获取字段值

### 指标维度

- dims 用于区分不同监控对象
- 维度值应与 CMDB 实例属性对应

### 数据类型

- 数值型指标用 `double`，可用于告警阈值判断
- 文本型指标用 `string`，用于状态展示

### 密码类型参数

涉及密码、密钥等敏感信息的入参，`valueType` 设为 `password`，并配合 `isFromSecret: true` 和 `isEncrypt: true`：

```yaml
- name: password
  valueType: password
  defaultValue: ""
  display: true
  displayName: "密码"
  description: "认证密码"
  use: collectParams
  optional: false
  isFromSecret: true
  isEncrypt: true
  extraArgs: null
```

### zip 打包中文文件名编码问题

macOS 系统 `zip` 命令默认不设置 UTF-8 flag（bit 11），中文文件名以 CP437 编码存储。平台服务端使用 Go 的 `archive/zip` 解压时，未设置 UTF-8 flag 的条目会被当作 CP437 解码，导致中文文件名乱码，脚本文件无法匹配 `plugin.yaml` 中的 `scriptPath`，激活时报 `illegal base64 data at input byte 0`。

**解决方案**：使用 Python `zipfile` 模块打包，强制设置 UTF-8 flag：

```python
import zipfile, os

plugin_dir = '/path/to/插件目录'
output_dir = os.path.dirname(plugin_dir)
zip_path = os.path.join(output_dir, '插件名称_v1.0.0.zip')

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(plugin_dir):
        if '.version' in files:
            files.remove('.version')
        for d in sorted(dirs):
            full_d = os.path.join(root, d)
            arc_d = os.path.relpath(full_d, output_dir) + '/'
            info = zipfile.ZipInfo(arc_d)
            info.flag_bits |= 0x800  # UTF-8 flag
            info.external_attr = 0o40755 << 16
            zf.writestr(info, b'')
        for fname in sorted(files):
            full_path = os.path.join(root, fname)
            arc_name = os.path.relpath(full_path, output_dir)
            info = zipfile.ZipInfo(arc_name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800  # UTF-8 flag
            info.external_attr = 0o100644 << 16
            with open(full_path, 'rb') as f:
                data = f.read()
            zf.writestr(info, data)
```

**注意**：此方式打的包可能被平台 update_plugin 接口拒绝（报 `not a valid zip file`），但 import_plugin 接口可正常使用。若更新时遇到此问题，可先删除旧插件再重新导入。

### 替换关联 CMDB 模型

当套件需要从自定义模型切换到 CMDB 已有模型时，**只修改 `objectId`**，其他字段保持不变。用户未要求的情况下不得私自改动 `name`、`memo`、`category` 等属性。

修改范围：

| 文件                                         | 修改内容                                            |
| -------------------------------------------- | --------------------------------------------------- |
| `plugin.yaml`                              | `relateObjectId` → 新模型 ID                     |
| `<OLD_MODEL>.json` → `<NEW_MODEL>.json` | 重命名文件，`objectId` → 新模型 ID，其余字段保留 |
| `alias_metric.json`                        | 所有 `objectId` → 新模型 ID                      |

```bash
# 确认无残留引用
grep -r "旧模型ID" 插件目录/
```

### Python 2 兼容性

监控套件运行环境为 **Python 2.7.18**，开发脚本时需注意包版本

### .orig 调试参数写法

`.orig` 源码文件中的调试参数应使用 `os.environ.get()` 并以默认值作为调试参数，而非硬编码赋值。这样既能本地调试（未设置环境变量时使用默认值），又不会覆盖线上实际入参：

```python
import os

# 正确写法：环境变量未设置时使用默认值（用于本地调试）
ip = os.environ.get("EASYOPS_COLLECTOR_ip", "127.0.0.1")
port = os.environ.get("EASYOPS_COLLECTOR_port", "80")

# 错误写法：硬编码会覆盖实际入参
# ip = "127.0.0.1"
# port = "80"
```
