# 示例：物理服务器 Redfish 信息采集

本示例展示了一个完整的资源采集插件，通过 Redfish API 采集物理服务器的硬件配置信息。

## 示例路径

```
output/物理服务器Redfish信息采集/
```

## 插件概述

- **采集目标**：物理服务器（PHYSICAL_SERVER@ONEMODEL）
- **采集方式**：Redfish API（HTTPS）
- **关联模型**：
  - PHYSICAL_SERVER@ONEMODEL（主模型 - 物理服务器）
  - NETDPORT@ONEMODEL（关联模型 - 网络端口）
  - FIBERCHANNEL_SWITCH_PORT@ONEMODEL（关联模型 - 光纤交换机端口）

## 关键文件说明

| 文件 | 说明 |
|------|------|
| `plugin.yaml` | 插件配置，含 6 个采集参数（instanceId, ip, user, password, secretName, ignoreFields） |
| `resource_discovery_define.json` | 资源发现定义，3 个模型的发现规则 |
| `PHYSICAL_SERVER@ONEMODEL.json` | CMDB 模型定义，含丰富属性（CPU/内存/磁盘/电源等） |
| `src/Physical_Server_Config_Info.orig` | 采集脚本源码（不含环境变量） |
| `src/Physical_Server_Config_Info.py` | 运行时脚本（含环境变量获取） |
| `readme` | 使用说明，含前置配置和问题排查 |

## 参数设计参考

| 参数 | defaultValue | isFromSecret | 说明 |
|------|-------------|-------------|------|
| instanceId | `$.instanceId` | false | 从 CMDB 实例自动获取 |
| ip | `$.ip` | false | 从 CMDB 实例自动获取 BMC IP |
| user | `""` | true | 从密钥管理获取用户名 |
| password | `""` | true | 从密钥管理获取密码（加密） |
| secretName | `""` | false | 密钥实例名称（隐藏参数） |
| ignoreFields | `""` | false | 忽略上报的字段（隐藏参数） |

## 品牌适配模式

该采集脚本使用了策略模式适配不同品牌服务器：

- `BRAND` 基类 → `H3C`, `HPE`, `HUAWEI`, `Dell`, `XFUSION`, `Inspur`, `VxMESH`
- 通过 `initBrand()` 根据 Manufacturer 字段自动选择适配类
