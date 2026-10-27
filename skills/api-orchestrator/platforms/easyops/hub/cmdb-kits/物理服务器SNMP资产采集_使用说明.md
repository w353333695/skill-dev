# 物理服务器SNMP资产采集：EasyOps原生套件

版本：0.1.7；套件instanceId：65ecd570203d1。

## 本版修正

- 采集参数默认全部使用$.attr动态表达式。community/authKey/privKey/credentialBundle/logLevel分别绑定$.snmp_conf.<参数名>；完整配置绑定$.snmp_conf。
- 包内增加平台原生识别的PHYSICAL_SERVER@ONEMODEL.json，内容为原生模型数组，包含现有物理服务器模型及扩展后的snmp_conf。注意不是API请求的object_list包装对象。原先只有snmp_conf.attribute.json，不会作为关联模型自动导入；现在两份均提供。
- snmp_conf字段权限位于模型view.attr_authorizers.snmp_conf.authorizers，设置为["easyops"]。不是限制整个物理服务器模型。平台系统管理员保留内置访问权，不能承诺对管理员隐藏。
- 品牌产品族与私有OID规则已直接内嵌src/server_snmp_collect.py，不读取oid-dictionary.json或外部品牌配置。该JSON仅供查阅。复制单个.py即可运行，但协议执行仍依赖已有Net-SNMP命令。

## 导入与模型范围

在已有套件的升级入口导入ZIP，保留原instanceId；新环境通过CMDB采集套件导入入口上传。
平台识别根目录PHYSICAL_SERVER@ONEMODEL.json并导入关联模型。该文件为当前环境完整模型快照，包含现有继承、属性、关系、视图及其他字段权限；只对snmp_conf定义和该字段授权作修改。
跨环境必须先备份并比较目标模型，尤其是继承BASE_ASSET@ONEMODEL、RESOURCE@ONEMODEL及关系对端模型是否存在；不要把快照无条件覆盖到不同模型体系的环境。
若只需在已有模型上增量修改，可使用snmp_conf.attribute.json更新单个属性，并在保留现有view及其他attr_authorizers的前提下只更新snmp_conf授权；不要设置整个模型readAuthorizers=["easyops"]。
导入/升级可能更新模型和套件，但不等于agent已启用新版本。本次不激活、不建任务、不修改任务或实例凭证、不执行设备采集。

## 默认动态参数

|套件参数|默认值|任务paramType|
|---|---|---|
|instanceId|$.instanceId|cmdb|
|ip|$.ip|cmdb|
|snmp_conf|$.snmp_conf|cmdb|
|community|$.snmp_conf.community|cmdb|
|authKey|$.snmp_conf.authKey|cmdb|
|privKey|$.snmp_conf.privKey|cmdb|
|credentialBundle|$.snmp_conf.credentialBundle|cmdb|
|logLevel|$.snmp_conf.logLevel|cmdb|
|old_cpuInfo等原有资产|$.cpuInfo等相应属性|cmdb|

关键：创建/编辑任务时$.表达式必须配paramType=cmdb，不能当常量字符串。脚本不解析$.表达式，解析发生在collector_service。旧任务不会因为套件升级而自动替换已保存参数，须核对并重新选择动态参数。
凭证参数仍为password、isEncrypt=true；如覆盖成任务加密常量，应使用paramType=const，不把真实密码混在普通字符串参数。

## snmp_conf示例与默认值

```json
{"enabled":false,"target":"","version":"3","port":161,
 "username":"inventory-user","securityLevel":"authPriv",
 "authProtocol":"SHA","privProtocol":"AES","contextName":"",
 "timeoutSec":3,"retries":0,"budgetSec":90,"vendorProfile":"auto",
 "updateIdentity":false,"logLevel":"ERROR"}
```

- v1/v2c填写community；v3按安全级别填写authKey/privKey。示例不包含真实凭证或默认团体名，不尝试默认密码。
- 默认从每台实例的snmp_conf读取；也支持只注入完整snmp_conf结构时由脚本拆出凭证。显式非空的独立参数优先于结构内对应字段。用于连接和上下文日志的配置会移除凭证字段，所有已知凭证参与日志脱敏。
- credentialRef可选：只有使用凭证组时才填写。它精确匹配credentialBundle中组名，未匹配不回退到其他凭证。credentialBundle为JSON字符串，不是未经验证的平台密钥库ID；也可将凭证组放在平台加密常量参数中。
- CMDB的str结构体子字段未声明存储加密；字段可见权限、套件password参数和isEncrypt均不能证明CMDB实例数据已加密。若不允许CMDB保存凭证，请留空敏感子字段，使用平台加密常量/凭证组方案。不要把实例导出、备份、日志当作可公开数据。
- target为空时用实例ip；未配置、null、enabled=false时静默输出空数组，不发设备请求。结构体默认值不一定由平台保存，脚本自行兜底非密默认值。
- 总预算1–300秒（默认90），单请求0.1–10秒（默认3），重试0–2（默认0）；前置基础GET仍为3秒、零重试。无SNMP版本或算法自动降级。

## 品牌与CMDB范围

采集顺序：sysObjectID/sysDescr识别→通用表→产品族私有表，不依赖设备型号白名单。
Dell iDRAC、IBM IMM、联想XCC、华为iBMC已有私有资产映射；百信、浪潮暂仅通用回退，不承诺全型号实测。IBM Power不套用IMM树。
主模型PHYSICAL_SERVER@ONEMODEL；网口NETDPORT@ONEMODEL；FC口FIBER_CHANNEL_PORT@ONEMODEL，子记录通过physicalServer关联。
ENTITY/INTERFACE/FC_PORT为标准表入口，不是所有BMC必备实现。用WALK而非GET表根，v2c/v3调用snmpbulkwalk。IF可能仅含管理口，FC卡存在不保证BMC暴露FC表。No Response不等于OID不支持。
缺失资产不清除旧值，不把HOST-RESOURCES逻辑资源伪装物理资产；无介质证据时不猜光口。详细范围见compatibility.md与sources.md。

## DEBUG及导出

默认在实例snmp_conf中设置logLevel=ERROR；单台复现时改DEBUG，任务logLevel参数保持$.snmp_conf.logLevel、paramType=cmdb。
也可临时把任务logLevel覆盖为常量DEBUG。优先级：独立任务logLevel参数→结构内logLevel→EASYOPS_LOG_LEVEL→LOG_LEVEL→ERROR。
日志写stderr，stdout只输出GATHERING DATA协议。保留同trace的context、phase、snmp.begin/output/end、Traceback与summary，导出完整stderr和stdout协议块。
日志先脱敏再限长；超时回收子进程后仍记录已产生的受限输出。单个输出超过8MiB时省略正文，否则最多记录脱敏后的末尾32768字符。外部SIGKILL/主机断电不保证有结束日志。
不要提供真实凭证、snmp.conf或完整环境；资产日志仍含IP/SN/MAC/用户名，分享前人工复核。详细状态与导出方法见《诊断日志导出.md》。

## 独立运行与验证

单文件.py/.orig内容一致，品牌映射内嵌，无独立项目、CLI、wheel或外部配置JSON依赖。独立运行通过EASYOPS_COLLECTOR_snmp_conf、EASYOPS_COLLECTOR_instanceId及可选独立参数环境变量传入配置，不把凭证放命令行。
需要已有Python2.7或3、snmpget/snmpwalk/snmpbulkwalk；本套件不安装系统依赖，不增加扫描。stdout协议退出0不是资产采集成功标志。
本版79项离线回归通过，含动态参数、字段权限及模型保留检查，并在隔离目录仅复制.py、模拟Net-SNMP命令执行完整流程；这是离线模拟，不是真实BMC或真实Net-SNMP验收。Python2仅做语法检查。

## 回滚与验收

先备份目标模型和套件；升级后核对snmp_conf结构、字段授权、动态参数表达式、任务paramType和agent实际脚本版本。模型导入不是事务，套件更新成功不保证模型也成功，必须分别回读。
回滚时保留已有实例配置与资产，使用备份恢复需要回退的snmp_conf定义及view中的对应授权；不要删除正在被引用的整个物理服务器模型或既有采集任务。
验收页面：http://192.168.110.24/next/monitor-kit/kit/easyops/65ecd570203d1/detail
