# vCenter监控 指标/告警来源与 Zabbix 对齐

来源：`/workspace/apps/zabbix-template-export/zabbix54_20261112_144121_866000`（Zabbix 5.4 全量导出，
2026-11-12 快照）。提取时间 2026-11-19。

## 一、现网规模

- vmware.* 监控项 3394 个；触发器 1362 条（Info 557 / Average 556 / Warning 237 / High 12）。
- 层级：vCenter 平台层（vmware.fullname/version/eventlog、vmware.cluster.status、vmware.datastore.*）、
  宿主机层 vmware.hv.*（现网 17 台 ESXi：业务网 11.66.17.202~207、DMZ 9.132.63.105~107 等）、
  虚拟机层 vmware.vm.*（逐 VM 实例化，每 VM ~109 项，总数 2000+）。
- VM 层项多的原因：官方 VMware Guest 模板静态项少，逐 VM 项由 LLD 原型实例化
  （导出含 272 个 vmware.vm.* 原型 × 每 VM + fs/nic/disk 二级发现）。
  本套件不依赖发现机制：指标元数据固定 35 个，实例由 dims 动态扩展。

## 二、现网阈值宏（templates-api.json 模板级）

| 宏 | 值 | 含义 |
|---|---|---|
| {$VMDATASTOWAR} | 8~15（分模板） | 数据存储可用空间告警阈值（百分比，free%） |
| {$VMDATASTOALARM} | 5 | 数据存储可用空间紧急阈值（free%） |
| {$VMWAREREADLATENCY} | 1000 | 数据存储平均读延迟告警阈值（毫秒） |
| {$VMWAREWRITELATENCY} | 1000 | 数据存储平均写延迟告警阈值（毫秒） |

## 三、触发器对齐（去重 537 模式归并）

| 现网规则 | 现网表达式语义 | 现网严重度 | 本套件告警模板设计 |
|---|---|---|---|
| 集群健康红色 | item>=3（自定义 0-3 值） | High 2 / Average 20 | red(2)→Critical、yellow(1)→Warning |
| 存储读延迟>=宏 | >= {$VMWAREREADLATENCY} | Info 254 | >=1000ms Warning（现网 Info 偏弱，模板默认 Warning 可调） |
| 存储写延迟>=宏 | >= {$VMWAREWRITELATENCY} | Info 254 | 同上 |
| 存储可用空间 | free%<15/8 Warning、<5 Average | Warning/Average | usage_pct>=85 Warning、>=95 Critical（等价换算） |
| 宿主机重启 | uptime<10m | Warning 42 | uptime<=600s Warning |
| 宿主机连接断开 | 连接状态变化 | Average 12 / Info 12 | connection_state>=1 Average |
| VM 电源状态变化 | diff（开/关/挂起） | Info 32 / Average 16 | power_state diff Warning |
| 多路径条数改变 | diff 且 <8 | Average 432 | 不采集（Zabbix LLD 专属，收益低） |
| Zabbix collector busy | >75% | Warning | 不适用（Zabbix 自身进程指标） |

## 四、指标映射表（本套件 35 项 ← Zabbix 源项）

| 本套件指标 | Zabbix 源 key | 说明 |
|---|---|---|
| vcenter_available | （无直接对应；hv.status 平台化） | SDK 会话可用性 |
| vcenter_collect_complete / error_count / duration_seconds | — | 采集自监控（平台惯例） |
| vcenter_cluster_status | vmware.cluster.status | green/yellow/red → 0/1/2（3=未知） |
| vcenter_cluster_host_total / vm_total / powered_on/off/suspended | vmware.hv.cluster.name + vm.powerstate 聚合 | 集群级汇总 |
| vcenter_cluster_cpu_usage_pct / mem_usage_pct | （vCenter UI 聚合口径） | Σhost usage / effective capacity |
| vcenter_datastore_accessible | vmware.datastore.size 附带语义 | summary.accessible |
| vcenter_datastore_capacity_gb / free_gb / usage_pct | vmware.datastore.size[...size/pfree] | pfree 换算为 usage_pct |
| vcenter_datastore_read_latency_ms / write_latency_ms | vmware.datastore.read/write[latency] | perf counter totalRead/WriteLatency |
| vcenter_host_connection_state | vmware.hv.status | connectionState 枚举 |
| vcenter_host_power_state | vmware.hv.power（standby） | runtime.powerState |
| vcenter_host_overall_status | vmware.hv.sensor.health.state（等价语义） | overallStatus green/yellow/red |
| vcenter_host_cpu_usage_pct | vmware.hv.cpu.usage / .utilization | usage/(cores×mhz) |
| vcenter_host_mem_usage_pct | vmware.hv.memory.used | usage/total |
| vcenter_host_mem_ballooned_pct | vmware.hv.memory.size.ballooned | 绝对 MB → 占比 % |
| vcenter_host_net_in_kbps / out_kbps | vmware.hv.network.in / out | net.received/transmitted |
| vcenter_host_uptime_seconds | vmware.hv.uptime | quickStats.uptime |
| vcenter_host_vm_count | vmware.hv.vm.num | 宿主机 VM 数 |
| vcenter_vm_power_state | vmware.vm.powerstate | 枚举数值化 |
| vcenter_vm_cpu_usage_pct | vmware.vm.cpu.usage（MHz）| usage/max 换算 % |
| vcenter_vm_mem_usage_pct | vmware.vm.memory.usage | guestMemoryUsage/max |
| vcenter_vm_storage_committed_gb / usage_pct | vmware.vm.storage.committed / uncommitted | 换算 |
| vcenter_vm_tools_status | vmware.vm.tools（模板内置） | toolsStatus 枚举 |
| vcenter_vm_uptime_seconds | vmware.vm.uptime | bootTime 差值 |

不采集（含理由）：vmware.fullname/version（字符串，无法进数值指标，DEBUG 日志可见）；
vmware.eventlog（日志项，metric_sampler 无告警联动价值）；vmware.buffer.pused（Zabbix collector
内部缓存水位，非 vCenter 指标）；vmware.vm.guest.*、vm.cpu.ready/swapwait/latency 等逐 VM 细分项
（用户确认只保留关键状态与使用率）；vmware.hv.datastore.multipath（LLD 专属）。

## 五、维度设计

vc（地址:端口）→ datacenter → cluster → datastore/host/vm（全部采集时动态枚举）。
对应关系：Zabbix 主机（每 vCenter/每 ESXi/每 VM 一台 Zabbix host）→ 本套件全部收敛为
一个关联 CLOUD_PROVIDER@ONEMODEL 实例的采集任务，实例维度由 dims 表达。
