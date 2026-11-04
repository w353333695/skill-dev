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

## CPU OID 适用范围补充（2026-11-04）

Zabbix 模板中的配置是：

```text
discovery[{#CPU.UTIL},1.3.6.1.2.1.25.3.3.1.2]
JSONPath: $..['{#CPU.UTIL}'].avg()
```

这里的 `discovery[...]` 不是把该 OID 当作单个标量直接读取，而是先按 SNMP LLD 发现多个 `hrProcessorLoad` 行，再由 Zabbix 对发现值求平均。该对象的 MIB 描述是“过去一分钟处理器非空闲时间百分比的平均值”。

该方法的前提是目标 SNMP agent 实现 `HOST-RESOURCES-MIB` 并暴露 `hrProcessorLoad` 表。服务器 BMC（iDRAC、Huawei iBMC、Lenovo XCC 等）通常只暴露硬件清单和传感器私有 MIB，不能据此推断 CPU 实时利用率。Zabbix 导出中的 Dell iDRAC、Lenovo XCC、Huawei PCServer、Inspur BMC 条目也没有对应的通用 BMC CPU 利用率项；其中部分 CPU OID只是型号、核数、状态或温度表。

因此套件只在 HOST-RESOURCES-MIB 有有效行时输出 `snmp.server.cpu.utilization`；未实现时必须 WARN，不得把厂商 CPU 状态/核数/处理器信息当成百分比。
