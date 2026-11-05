# 物理服务器 SNMP 告警规则模板

## 来源

基于 `apps/zabbix-template-export/zabbix54_20261104_104150_596000/alert-rules.json` 中 Zabbix 5.4.5 服务器模板的触发器和触发器原型整理，覆盖 Dell iDRAC、Lenovo XCC、Huawei PCServer、Inspur BMC、IBM IMM、H3C HDM 及黄河候选模板中的通用硬件告警思路。

## 当前规则

- CPU 使用率：Zabbix `HOST-RESOURCES-MIB CPU SNMP` 明确为 90% 告警阈值，仅生成 warning 级阈值。
- 内存使用率：Zabbix storage 模板宏为 80% warning、90% critical。
- 温度：Dell 通用温度为 50℃ warning、60℃ critical；CPU 温度为 70/75℃、Ambient 为 30/35℃，因套件当前未按传感器位置拆分维度，位置阈值只保留在 JSON 来源证据。
- 磁盘利用率：Zabbix storage 模板宏为 80% warning、90% critical。
- 风扇、电源、整机健康、网口、光口状态：状态值不等于 1 时告警。

规则名称、监控目标和通知策略沿用 EasyOps 现有监控告警模板格式，目标模型为 `PHYSICAL_SERVER@ONEMODEL`，指标名使用物理服务器 SNMP 监控套件的 alias metric 名称。

## 注意

厂商私有 MIB 的状态枚举并不完全一致；当前套件输出原始状态值，没有把各品牌状态强行转换为统一枚举。因此状态类规则导入后必须结合实际设备返回值和值映射复核，“不等于 1”是通用初始策略，不是所有型号的最终故障判断。

Zabbix 中仅有但当前 EasyOps 套件尚未输出的规则（如 SNMP 可用性、系统重启、磁盘 SMART、RAID 控制器/虚拟盘、内存/CPU 明细状态）未写入本模板，避免产生永远无数据的告警。


## 0.1.13 规则产物

- 套件包内 `alertRule/物理服务器SNMP告警.json`：按 EasyOps 告警契约生成，目标模型为 `PHYSICAL_SERVER@ONEMODEL`。
- `物理服务器SNMP监控_告警规则模板_0.1.13.xlsx`：与 JSON 的四个数值条件保持一致。
- 状态类触发器的 Zabbix 枚举值随 Dell/IBM/HP/Huawei 等品牌不同，且当前脚本输出原始状态值，未自动写入通用状态阈值，避免跨品牌误报。
