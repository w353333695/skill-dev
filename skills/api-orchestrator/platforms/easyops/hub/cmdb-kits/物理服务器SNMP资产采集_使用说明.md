# 物理服务器SNMP资产采集：EasyOps原生套件

版本：0.1.3；开发与导入方式：api-orchestrator编排现有EasyOps能力。

## 交付与维护边界

本交付物只有原生CMDB采集套件ZIP及本文档，不单独建立能力项目，不要求安装CLI、uv、Python包或wheel。
采集逻辑、产品族字典及OID定义直接随EasyOps套件下发给agent；运行单文件src/server_snmp_collect.py。
源码在ZIP和平台套件源码中维护；修改后同步.py/.orig、更新版本，再通过套件升级入口导入。

沿用的EasyOps现有知识：

- formats/collector-kit/plugin-yaml-schema.yaml：simple-script、agentType=easyops、samplerType=process_sampler。
- formats/collector-kit/sampler-types.yaml：GATHERING DATA输出及Python2单文件约束。
- formats/collector-kit/param-mechanism.yaml：CMDB动态参数、环境注入与凭证参数加密。
- formats/collector-kit/package-format.yaml：原生ZIP目录、两份脚本一致、ZIP_STORED与multipart导入/升级。
- hub既有路由器和光纤交换机SNMP套件：复用原生套件形态，不从零建立平台或执行引擎项目。

## 平台与模型

- 套件：物理服务器SNMP资产采集，instanceId=65ecd570203d1。
- 主模型：PHYSICAL_SERVER@ONEMODEL；网口：NETDPORT@ONEMODEL；FC口：FIBER_CHANNEL_PORT@ONEMODEL。
- 子记录通过physicalServer关联父实例；不新增磁盘模型、不更改既有关联定义。
- snmp_conf已增量新增，既有属性未覆盖；本次不重复建模。
- snmp_conf保存版本、目标、端口、用户名、算法、credentialRef等非密信息；community/authKey/privKey/credentialBundle走平台加密参数。
- 采集顺序为基础识别→通用MIB→有原始定义证据的私有MIB，不按服务器型号白名单卡死。

## 兼容范围

|产品族|当前实现|
|---|---|
|Dell iDRAC|私有整机/CPU/内存/物理盘/逻辑盘/业务网口映射|
|IBM IMM|私有整机/CPU/内存等映射；Power不冒用IMM树|
|联想XCC|私有整机/CPU/内存/磁盘/网卡及融合以太网/FC口映射|
|华为iBMC|私有CPU/内存/磁盘/逻辑盘/网卡及业务口映射|
|百信、浪潮|暂为通用MIB回退；私有MIB原件证据不足，未虚构支持|

物理端口可见性取决于BMC实际暴露内容；FC口按WWPN关联，不把以太网SFP口误当FC。没有介质证据时不猜isOpticalPort。
容量单位、身份覆盖、缺失值保旧和不同固件边界见包内compatibility.md。

## 导入与使用

平台“采集套件/CMDB采集套件”直接上传ZIP；已存在的套件通过升级入口上传新版，保留原instanceId。
执行节点使用已有EasyOps agent和Net-SNMP命令；不安装本地新项目，不自动安装系统依赖。
配置采集目标范围、代理节点及加密凭证参数后，再给待验收实例设置snmp_conf.enabled=true。
$.路径参数须按CMDB动态参数处理；proxyIp为空时显式选代理，不默认把物理机当agent。

本次保持未激活、未建任务、未进行真实设备采集；没有设备清单不影响先交付套件。
直接加载包内脚本的53项离线回归通过，另做Python2.7语法及远端导出一致性核对；不能替代设备与agent实机验收。

验收页面：http://192.168.110.24/next/monitor-kit/kit/easyops/65ecd570203d1/detail

API回执、模型备份和开发回归临时材料留在既有api-cli项目的.local/native-server-kit目录，不随采集套件分发。
