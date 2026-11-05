# 物理服务器 SNMP：Zabbix 品牌映射与边界

核对时间：2026-11-04。来源：用户提供的 Zabbix 5.4.5 导出 `apps/zabbix-template-export/zabbix54_20261104_104150_596000/templates.json`，不是所有 Zabbix 版本的完整支持清单。

## 本次纳入的 SNMP 服务器模板

| 品牌/管理控制器 | 来源模板 | 本套件私有采集覆盖 |
|---|---|---|
| Dell iDRAC | Dell iDRAC SNMP、TEMP_PBC_PHY_DELL_IDRAC_SNMP | 身份、健康、电源、温度、风扇状态/RPM、物理磁盘状态/容量 |
| IBM IMM | IBM IMM SNMP、TEMP_PBC_PHYI_IBM_IMM-SNMPv2 | 身份、健康、温度、风扇状态/百分比、电源、磁盘状态、内存条状态/容量 |
| Lenovo XCC | Template Server Lenovo XCC SNMPv3 | 健康、整机电源、温度、风扇状态/百分比、电源、磁盘状态、内存条状态/容量 |
| HP/HPE iLO | HP iLO SNMP | 身份、健康、温度、风扇状态、电源、物理磁盘状态/容量 |
| Supermicro Aten | Supermicro Aten SNMP | 共享传感器表按描述过滤温度、风扇百分比 |
| Huawei iBMC | TEMP_PBC_PHY_Huawei_PCServer_2288Hv5 | 身份、健康、电源、温度、风扇、内存条、磁盘、处理器状态 |
| Inspur BMC | Template Server Inspur BMC All Items 4 Zabbix5.0 等 | 温度、风扇、电源、内存条、磁盘、处理器状态 |
| H3C HDM | TEMP_PBC_PHY_H3C-HDM-G3-SNMPV2 | 风扇、电源、磁盘、处理器、内存条状态；有通用温度表才补温度 |
| 黄河模板（iDRAC 映射） | TEMP_PBC_PHY_Huanghe_IDRAC_SNMP | 复用该导出模板的 Dell iDRAC OID；不等于所有黄河机型均兼容 |

百信保留识别及标准 MIB 尝试；本次导出未提供已确认的百信私有服务器 SNMP 模板，不承诺新增私有指标。

Intel SR1530/SR1630、Chassis by IPMI、通用 IPMI 模板是 IPMI 协议，不纳入只用 SNMP 的套件。HP Comware、Huawei VRP 等网络设备模板以及 OceanStor/SVC 存储模板不套用到服务器。

## 解析与单位

- CPU/内存/文件系统使用率仅在设备暴露相应 HOST-RESOURCES-MIB 表时可采；BMC 硬件状态不能替代操作系统利用率。
- Dell/Huawei 温度按模板乘 0.1；HP/IBM/Lenovo 等按模板原值输出，不跨品牌强制除以十。
- IBM/Lenovo/Supermicro 模板的风扇相对最大转速为百分比，输出独立指标 `snmp.server.fan.utilization`，别名单位 `%`。Dell 等 RPM 数据保留 `snmp.server.fan.speed`，单位 `rpm`。
- Dell/HP 原始磁盘容量为 MB。Zabbix 乘 1048576 是为转成 bytes；本套件已有磁盘容量指标单位为 MB，因此保留原始 MB，不重复放大。
- Supermicro 按原模板 `.*Temp.*`、`FAN.*` 和正值过滤，不把同表的电压读数当温度。
- ENTITY-SENSOR-MIB 仅将类型 8（摄氏温度）、运行状态 1 的有效读数输出为温度，使用 `.2` 的 scale 枚举和 `.3` 的 precision 换算，不把其它传感器当温度。
- 品牌识别优先完整 enterprise OID 边界，其次描述；旧 IMM 可能使用 Net-SNMP sysObjectID，需要 sysDescr 中的 IBM/IMM 线索。仅有通用 sysObjectID 且无描述线索时不能保证识别私有品牌。

## 证据与验收

包内 `zabbix-server-template-evidence.json` 保留十三个原始服务器/标准模板的 item、LLD、预处理和 value map，后续无原导出文件时也可复核。配置为脚本内 dict/list，运行无需外部 JSON。

本版实现模板级品牌与指标映射，并非原模板所有指标/告警的一比一转换；HP 阵列控制器、电池、Lenovo RAID/电压等未映射项不声称支持。全品牌实机、固件版本及 SNMP view 尚未验收；无单项 OID只告警并继续。离线验证包含 IBM 无 KeyError、品牌识别闭环、共享传感器分类、单位换算、CPU/内存/磁盘、ZIP/.orig/参数注入。
