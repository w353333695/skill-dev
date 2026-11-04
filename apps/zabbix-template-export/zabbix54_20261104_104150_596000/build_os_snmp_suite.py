import json
import uuid
from pathlib import Path

base = Path(__file__).parent
source = base / 'templates.json'
out = base / 'os-snmp-monitoring-suite.json'
with source.open(encoding='utf-8') as f:
    data = json.load(f)

by_name = {t['template']: t for t in data['zabbix_export']['templates']}

def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, 'wwh-os-snmp-' + name)).replace('-', '')

def macro(macro, value, description):
    return {'macro': macro, 'value': value, 'description': description}

def trigger(description, expression, priority, recovery, tags, name):
    return {
        'uuid': uid(name), 'name': description, 'expression': expression,
        'recovery_mode': '1', 'recovery_expression': recovery,
        'priority': priority, 'manual_close': '0', 'opdata': '',
        'tags': [{'tag': k, 'value': v} for k, v in tags.items()],
    }

def trigger_prototype(description, expression, priority, recovery, tags, name):
    x = trigger(description, expression, priority, recovery, tags, name)
    x['name'] = description
    return x

linux_name = 'OS Linux SNMP Enhanced'
windows_name = 'OS Windows SNMP Enhanced'
linux_macros = [
    macro('{$CPU_LOAD_WARN}', '4', 'Load average 5m 告警阈值；按主机 CPU 核数调整'),
    macro('{$CPU_LOAD_CRIT}', '8', 'Load average 5m 严重阈值；按主机 CPU 核数调整'),
    macro('{$MEMORY_WARN}', '80', '内存使用率告警百分比'),
    macro('{$MEMORY_CRIT}', '90', '内存使用率严重百分比'),
    macro('{$SWAP_WARN}', '50', 'Swap 使用率告警百分比'),
    macro('{$FS_WARN}', '80', '文件系统使用率告警百分比'),
    macro('{$FS_CRIT}', '90', '文件系统使用率严重百分比'),
    macro('{$IF_ERRORS_WARN}', '10', '网卡每秒错误包告警阈值'),
    macro('{$SNMP_TIMEOUT}', '5m', 'SNMP 数据无更新时间窗口'),
]
windows_macros = [
    macro('{$CPU_WARN}', '80', 'CPU 使用率告警百分比'),
    macro('{$CPU_CRIT}', '95', 'CPU 使用率严重百分比'),
    macro('{$MEMORY_WARN}', '80', '内存使用率告警百分比'),
    macro('{$MEMORY_CRIT}', '90', '内存使用率严重百分比'),
    macro('{$FS_WARN}', '80', '磁盘使用率告警百分比'),
    macro('{$FS_CRIT}', '90', '磁盘使用率严重百分比'),
    macro('{$IF_ERRORS_WARN}', '10', '网卡每秒错误包告警阈值'),
    macro('{$SNMP_TIMEOUT}', '5m', 'SNMP 数据无更新时间窗口'),
]

linux_triggers = [
    trigger('SNMP agent unavailable', 'last(/%s/zabbix[host,snmp,available])=0' % linux_name, 'HIGH', 'last(/%s/zabbix[host,snmp,available])=1' % linux_name, {'scope': 'availability', 'component': 'snmp'}, linux_name+'-snmp'),
    trigger('Linux: 5m load average is high', 'avg(/%s/system.cpu.load.avg5[laLoad.2],5m)>{$CPU_LOAD_WARN}' % linux_name, 'WARNING', 'avg(/%s/system.cpu.load.avg5[laLoad.2],5m)<{$CPU_LOAD_WARN}' % linux_name, {'scope': 'performance', 'component': 'cpu'}, linux_name+'-load-warn'),
    trigger('Linux: 5m load average is critical', 'avg(/%s/system.cpu.load.avg5[laLoad.2],5m)>{$CPU_LOAD_CRIT}' % linux_name, 'HIGH', 'avg(/%s/system.cpu.load.avg5[laLoad.2],5m)<{$CPU_LOAD_CRIT}' % linux_name, {'scope': 'performance', 'component': 'cpu'}, linux_name+'-load-crit'),
    trigger('Linux: memory utilization is high', 'avg(/%s/vm.memory.util[snmp],5m)>{$MEMORY_WARN}' % linux_name, 'WARNING', 'avg(/%s/vm.memory.util[snmp],5m)<{$MEMORY_WARN}' % linux_name, {'scope': 'capacity', 'component': 'memory'}, linux_name+'-mem-warn'),
    trigger('Linux: swap utilization is high', 'last(/%s/system.swap.pfree[snmp])<100-{$SWAP_WARN}' % linux_name, 'WARNING', 'last(/%s/system.swap.pfree[snmp])>=100-{$SWAP_WARN}' % linux_name, {'scope': 'capacity', 'component': 'swap'}, linux_name+'-swap-warn'),
]
linux_prototypes = [
    trigger_prototype('{#FSNAME}: filesystem usage is high', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])>{$FS_WARN}' % linux_name, 'WARNING', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])<{$FS_WARN}' % linux_name, {'scope': 'capacity', 'component': 'filesystem'}, linux_name+'-fs-warn'),
    trigger_prototype('{#FSNAME}: filesystem usage is critical', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])>{$FS_CRIT}' % linux_name, 'HIGH', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])<{$FS_CRIT}' % linux_name, {'scope': 'capacity', 'component': 'filesystem'}, linux_name+'-fs-crit'),
    trigger_prototype('{#IFNAME}: inbound errors are high', 'change(/%s/net.if.in.errors[ifInErrors.{#SNMPINDEX}],0)>={$IF_ERRORS_WARN}' % linux_name, 'WARNING', 'change(/%s/net.if.in.errors[ifInErrors.{#SNMPINDEX}],0)<{$IF_ERRORS_WARN}' % linux_name, {'scope': 'network', 'component': 'interface'}, linux_name+'-if-in-errors'),
    trigger_prototype('{#IFNAME}: outbound errors are high', 'change(/%s/net.if.out.errors[ifOutErrors.{#SNMPINDEX}],0)>={$IF_ERRORS_WARN}' % linux_name, 'WARNING', 'change(/%s/net.if.out.errors[ifOutErrors.{#SNMPINDEX}],0)<{$IF_ERRORS_WARN}' % linux_name, {'scope': 'network', 'component': 'interface'}, linux_name+'-if-out-errors'),
]

windows_triggers = [
    trigger('SNMP agent unavailable', 'last(/%s/zabbix[host,snmp,available])=0' % windows_name, 'HIGH', 'last(/%s/zabbix[host,snmp,available])=1' % windows_name, {'scope': 'availability', 'component': 'snmp'}, windows_name+'-snmp'),
    trigger('Windows: CPU utilization is high', 'avg(/%s/system.cpu.util,5m)>={$CPU_WARN}' % windows_name, 'WARNING', 'avg(/%s/system.cpu.util,5m)<{$CPU_WARN}' % windows_name, {'scope': 'performance', 'component': 'cpu'}, windows_name+'-cpu-warn'),
]
windows_prototypes = [
    trigger_prototype('{#FSNAME}: disk usage is high', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])>{$FS_WARN}' % windows_name, 'WARNING', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])<{$FS_WARN}' % windows_name, {'scope': 'capacity', 'component': 'filesystem'}, windows_name+'-fs-warn'),
    trigger_prototype('{#FSNAME}: disk usage is critical', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])>{$FS_CRIT}' % windows_name, 'HIGH', 'last(/%s/vfs.fs.pused[storageUsedPercentage.{#SNMPINDEX}])<{$FS_CRIT}' % windows_name, {'scope': 'capacity', 'component': 'filesystem'}, windows_name+'-fs-crit'),
    trigger_prototype('{#MEMORY}: memory utilization is high', 'last(/%s/vm.memory.util[memoryUsedPercentage.{#SNMPINDEX}])>{$MEMORY_WARN}' % windows_name, 'WARNING', 'last(/%s/vm.memory.util[memoryUsedPercentage.{#SNMPINDEX}])<{$MEMORY_WARN}' % windows_name, {'scope': 'capacity', 'component': 'memory'}, windows_name+'-mem-warn'),
    trigger_prototype('{#IFNAME}: inbound errors are high', 'change(/%s/net.if.in.errors[ifInErrors.{#SNMPINDEX}],0)>={$IF_ERRORS_WARN}' % windows_name, 'WARNING', 'change(/%s/net.if.in.errors[ifInErrors.{#SNMPINDEX}],0)<{$IF_ERRORS_WARN}' % windows_name, {'scope': 'network', 'component': 'interface'}, windows_name+'-if-in-errors'),
    trigger_prototype('{#IFNAME}: outbound errors are high', 'change(/%s/net.if.out.errors[ifOutErrors.{#SNMPINDEX}],0)>={$IF_ERRORS_WARN}' % windows_name, 'WARNING', 'change(/%s/net.if.out.errors[ifOutErrors.{#SNMPINDEX}],0)<{$IF_ERRORS_WARN}' % windows_name, {'scope': 'network', 'component': 'interface'}, windows_name+'-if-out-errors'),
]

def template(name, parent, macros, triggers, prototypes, description):
    return {
        'template': name, 'name': name, 'uuid': uid(name),
        'description': description,
        'groups': [{'name': 'Templates/Operating systems'}],
        'templates': [{'name': parent}], 'macros': macros,
        'triggers': triggers, 'trigger_prototypes': prototypes,
    }

export = {
    'zabbix_export': {
        'version': '5.4', 'date': '2026-11-04T00:00:00Z',
        'groups': [{'name': 'Templates/Operating systems'}],
        'templates': [
            template(linux_name, 'Linux SNMP', linux_macros, linux_triggers, linux_prototypes, 'Enhanced Linux SNMP monitoring suite. Links the official Linux SNMP template and adds threshold triggers.'),
            template(windows_name, 'Windows SNMP', windows_macros, windows_triggers, windows_prototypes, 'Enhanced Windows SNMP monitoring suite. Links the official Windows SNMP template and adds threshold triggers.'),
        ],
    }
}
with out.open('w', encoding='utf-8') as f:
    json.dump(export, f, ensure_ascii=False, indent=2)
    f.write('\n')
print(out)
