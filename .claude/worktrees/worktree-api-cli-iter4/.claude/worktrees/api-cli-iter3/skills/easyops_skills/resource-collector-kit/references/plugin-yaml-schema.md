# plugin.yaml 完整字段说明

## 顶层字段

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `type` | string | 是 | 插件类型，固定为 `simple-script` | `simple-script` |
| `name` | string | 是 | 插件名称 | `交换机SNMP信息采集` |
| `version` | string | 是 | 版本号，使用时间戳字符串 | `"1767146446"` |
| `command` | object | 是 | 采集命令配置 | 见下方 |
| `params` | list | 是 | 参数名列表 | `["ip", "port"]` |
| `paramDefine` | list | 是 | 参数详细定义 | 见下方 |
| `agentType` | string | 是 | Agent 类型 | `easyops` |
| `category` | string | 是 | 插件分类 | `计算资源` |
| `scriptType` | string | 是 | 脚本类型 | `python` |
| `interpreter` | string | 是 | 解释器路径，通常为空 | `""` |
| `memo` | string | 是 | 插件描述 | `通过SNMP采集交换机信息` |
| `icon` | null | 是 | 图标，通常为 null | `null` |
| `relateObjectId` | string | 是 | 关联的 CMDB 模型 ID | `PHYSICAL_SERVER@ONEMODEL` |
| `installPath` | string | 是 | 安装路径 | `physical_server_snmp_config` |
| `samplerType` | string | 是 | 采样器类型 | `process_sampler` |
| `jobFilter` | null | 是 | 任务过滤，通常为 null | `null` |
| `protected` | bool | 是 | 是否受保护 | `false` |
| `noPackage` | bool | 是 | 是否无包 | `false` |
| `collectType` | list | 是 | 采集类型列表 | `[]` |
| `collectAgent` | string | 是 | 采集 Agent 字段 | `$.ip` |
| `group` | list | 是 | 分组标签 | `["remoteScan"]` |
| `rating` | int | 是 | 评分 | `0` |
| `metricbeatName` | string | 是 | Metricbeat 名称 | `""` |
| `processors` | list | 是 | 处理器列表 | `[]` |
| `extInfo` | null | 是 | 扩展信息 | `null` |

## command.collect 字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `interpreter` | string | 解释器路径，通常为空 | `""` |
| `scriptPath` | list | 脚本路径分段 | `["src", "ScriptName.py"]` |
| `type` | string | 脚本类型 | `python` |
| `user` | string | 运行用户，通常为空 | `""` |

## paramDefine 字段

每个参数定义包含以下字段：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `name` | string | 参数名，与 params 列表对应 | `ip` |
| `valueType` | string | 值类型 | `string` / `password` |
| `defaultValue` | string | 默认值 | `$.ip` / `""` |
| `display` | bool | 是否在 UI 显示 | `true` / `false` |
| `displayName` | string | 显示名称 | `目标IP` |
| `description` | string | 参数描述 | `采集目标的IP地址` |
| `use` | string | 用途，固定为 `collectParams` | `collectParams` |
| `optional` | bool | 是否可选 | `false` |
| `isFromSecret` | bool | 是否从密钥管理获取 | `true` / `false` |
| `isEncrypt` | bool | 是否加密 | `true` / `false` |
| `extraArgs` | null | 额外参数 | `null` |

## defaultValue 引用语法

`defaultValue` 支持 `$.xxx` 格式，表示从 CMDB 实例的对应字段自动获取值。

| 写法 | 含义 | 典型场景 |
|------|------|---------|
| `$.instanceId` | 获取实例 ID | 采集时自动传入当前实例 ID |
| `$.ip` | 获取 IP 字段 | 采集目标 IP 从 CMDB 实例获取 |
| `$.port` | 获取端口字段 | 端口从 CMDB 实例获取 |
| `$.community` | 获取 SNMP 团体字 | 从 CMDB 实例获取 SNMP 参数 |
| `""` | 空字符串，需要用户手动填写 | 用户名、密码等认证信息 |

> **⚠️ 强制约束：`$.xxx` 的 `xxx` 必须是关联模型（`relateObjectId`，含继承链）真实存在的属性。**
>
> 平台导入时会校验 `$.field` 引用的 `field` 是否存在于模型 `attrList`。引用了不存在的字段会报错：
>
> ```
> $.类型的参数要来源于cmdb模型且有应用场景
> ```
>
> 常见误用：把 **agent 运行环境相关的东西**（CLI 命令路径、工具目录、`installPath` 等）当成设备属性用 `$.installPath` 引用——这些不是被采集设备的属性，模型中没有，必然报错。处理方式：作为普通自定义入参（`defaultValue: ""`，`display: true`，用户手动填写），或直接在脚本里依赖系统 PATH 不设为参数。
>
> 拿不准字段是否存在时，用 `scripts/get_model.py --model-id <relateObjectId>` 查 `attrList` 确认后再引用。

## isFromSecret / isEncrypt 使用场景

| 场景 | isFromSecret | isEncrypt | valueType | 示例 |
|------|-------------|-----------|-----------|------|
| CMDB 实例自动获取 | false | false | string | ip, instanceId, port |
| 密钥管理获取（用户名） | true | false | string | user, username |
| 密钥管理获取（密码） | true | true | password | password, secret |
| 用户手动填写 | false | false | string | 自定义配置参数 |
| 隐藏参数（不在 UI 显示） | false | false | string | display: false 的参数 |

## samplerType 取值

| 取值 | 说明 |
|------|------|
| `process_sampler` | 进程采样器（资源采集常用） |
| `metric_sampler` | 指标采样器（监控插件常用） |

## agentType 取值

| 取值 | 说明 |
|------|------|
| `easyops` | EasyOps Agent |

## group 分组标签可选值

| 取值 | 说明 |
|------|------|
| `remoteScan` | 远程扫描 |
| `cloudTypePrivateCloud` | 私有云 |
| `cloudTypePublicCloud` | 公有云 |
| `cloudTypeHybridCloud` | 混合云 |
| `collectContentResourceInfo` | 资源信息采集 |

## category 常用分类

| 分类 | 说明 |
|------|------|
| `计算资源` | 服务器、虚拟机等 |
| `网络资源` | 交换机、路由器等 |
| `存储资源` | 存储设备等 |
| `自定义` | 其他类型 |
