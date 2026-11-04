# 物理服务器 SNMP 采集解析校准

## Zabbix 对照结论

- CPU 使用率使用 `HOST-RESOURCES-MIB` 的 `1.3.6.1.2.1.25.3.3.1.2`，Zabbix 对发现到的每个 CPU 值执行 `avg()`；套件按所有有效核心值计算平均百分比。
- 内存和磁盘使用率来自 `HOST-RESOURCES-MIB` storage 表。`hrStorageType` 的 `2` 为 RAM，`4` 为固定磁盘；`hrSize`、`hrUsed` 与 `hrAllocUnits` 配对。Zabbix 对 size/used 都乘分配单元，比例计算时分配单元抵消。
- Dell iDRAC 温度 `1.3.6.1.4.1.674.10892.5.4.700.20.1.6` 使用 `MULTIPLIER 0.1`。
- Huawei PCServer 温度 `1.3.6.1.4.1.2011.2.235.1.1.26.50.1.3` 使用 `MULTIPLIER .1`。
- 通用 `ENTITY-SENSOR-MIB` 温度必须结合 `sensorScale` 换算，不能把原始整数直接当摄氏度。

## 解析约束

- 单个 OID 无响应、值为空或不在合理范围时记录 WARNING 并继续；基础 `sysDescr/sysObjectID` 都无响应才失败。
- 私有 CPU 表语义不统一，仅在通用 CPU 表完全不可用时作为兜底，避免把状态/计数器误报为利用率。
- 使用率输出限制在 `0..100`，温度按来源应用预处理，不在公共 `value()` 中盲目除以 10。
