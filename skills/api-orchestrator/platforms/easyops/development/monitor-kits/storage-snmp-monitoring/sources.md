# 来源与边界

- Zabbix 5.4 导出：`apps/zabbix-template-export/zabbix54_20261104_104150_596000/templates.json`，2026-11-05。
- 标准 HOST-RESOURCES-MIB、Huawei OceanStor、NetApp FAS3220、XSKY SDS、EMC DD2500、Dell iDRAC OID 均来自该导出中的模板定义。
- 本套件只实现 SNMP 采集；NetApp AFF HTTP、XSKY XMS HTTP、EMC Unity API、IBM V7000 SSH 需要分别接入对应 API/SSH 套件，不在本包伪装成 SNMP。
- 未在导出中确认的厂商私有 OID 不纳入画像；未知品牌统一使用标准 MIB 兜底。
