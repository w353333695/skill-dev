# VMWare扫描 0.1.2

基于现网套件 65dc3d92b51dd（1762419597）导出改造。

## 行为

- 物理机以 `businessIp` 匹配，保持 `upsert=false`，只维护已有资产，不自动新增。
- 从 `config.virtualNicManagerInfo.netConfig` 的 management / selectedVnic 选择 VMkernel IP；未提供 Management 配置时，仅一个有效 VMkernel IP 才回退，多候选跳过。明确配置 Management 但未选择网卡时不回退。
- 同次采集中重复 IP 的宿主机全部跳过；IPv4/IPv6 规范化，缺失、回环、链路本地和组播地址不使用。
- SN 优先尝试 systemInfo.serialNumber、ServiceTag、SerialNumberTag；占位值不写入，但仍上报 IP、资源标识及平台关系。
- 云平台、虚拟机、资源池、存储、旧模型宿主机到物理机的关联统一使用 businessIp。无可用物理机时不发送云平台物理机关联清空数据。
- 不修改模型唯一约束，不改变原参数名称和凭证模式。不主动运行采集或同步已有任务。

## 导入与验收

在采集套件管理中导入 ZIP；同名套件使用升级。API 为 `PUT /api/v1/plugin/import_update/{instanceId}`，multipart 字段 `attachment`（ZIP）及 `version=0.1.2`。

跨环境导入前必须备份同名套件及关联模型，比较包内原有 CLOUD_PROVIDER 模型快照后导入；该快照沿用源包，不能无审查覆盖目标环境自定义字段。可从包中移除模型快照后复核目标已有模型满足原套件依赖。

**上线前硬条件：目标物理机台账 businessIp 必须唯一且与 ESXi 管理 IP 一致。** 本次仅检测采集内重复 IP，不查询另一环境台账。IP 地址跨网段复用、地址变更或台账缺失时不可直接用于匹配；缺失台账仍会报找不到实例，应补齐正确台账，禁止改为自动新增来掩盖。

验收地址：`/next/monitor-kit/kit/easyops/<套件instanceId>/detail`。确认套件版本、管理 IP、物理机与虚拟机关系；目标环境用已有采集任务验收并确认原 SN 未被占位值覆盖。

离线回归覆盖日志中的 8 台宿主机、Management 网卡选择、重复 IP、空/多 IP、SN 候选回退和统一关联键。无真实 vCenter 访问，未完成目标环境实采及 Python 2 解释器运行验证。

源码与回归保留在 development，Hub 仅保存可导入 ZIP。原始套件备份保留在本次任务 tmp 目录，可供回滚重打为新版本导入；平台版本不允许直接重复使用旧版本。
