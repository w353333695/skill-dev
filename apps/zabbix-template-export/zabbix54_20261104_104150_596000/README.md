# 操作系统 SNMP 监控套件（Zabbix 5.4）

本目录包含从 Zabbix 5.4.5 导出的官方 Linux/Windows SNMP 模板，以及一套增强告警模板：

- `os-snmp-monitoring-suite.json`：可直接导入 Zabbix 5.4 的增强模板。
- `templates.json`：原始模板导出，包含 `Linux SNMP`、`Windows SNMP` 及其模块。
- `alert-rules.json`：原始监控项、预处理和告警规则导出。

增强模板通过模板链接复用官方模板：

- `OS Linux SNMP Enhanced` → `Linux SNMP`
- `OS Windows SNMP Enhanced` → `Windows SNMP`

官方模板负责 CPU、内存、Swap、文件系统、磁盘、网卡、系统信息和低层发现（LLD）；增强模板补充按阈值告警。

## 一、Linux 配置 SNMP

以下示例以 Debian/Ubuntu 为例，CentOS/RHEL 使用 `dnf` 或 `yum` 替换安装命令。

### 1. 安装并启动 snmpd

```bash
sudo apt-get update
sudo apt-get install -y snmpd snmp
sudo systemctl enable --now snmpd
```

### 2. 配置只读 SNMPv2c

编辑 `/etc/snmp/snmpd.conf`，建议只允许 Zabbix Server/Proxy 的地址访问：

```conf
agentAddress udp:161
rocommunity CHANGE_ME_COMMUNITY 192.0.2.10/32
sysLocation CHANGE_ME_LOCATION
sysContact CHANGE_ME_CONTACT
```

将 `CHANGE_ME_COMMUNITY` 换成实际只读团体字；不要在工单、日志或聊天中公开团体字。生产环境优先使用 SNMPv3。

重启并验证：

```bash
sudo systemctl restart snmpd
snmpwalk -v2c -c CHANGE_ME_COMMUNITY 127.0.0.1 1.3.6.1.2.1.1
```

### 3. 放行防火墙

仅放行 Zabbix Server/Proxy 到主机 UDP/161：

```bash
sudo ufw allow from 192.0.2.10 to any port 161 proto udp
# firewalld 示例：
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.0.2.10/32" port protocol="udp" port="161" accept'
sudo firewall-cmd --reload
```

### 4. Linux 指标说明

- CPU：load average（1/5/15 分钟）、CPU 数、上下文切换、中断、按核 CPU 统计。
- 内存：总量、可用、空闲、缓存、buffer、使用率。
- Swap：总量、可用、使用率。
- 文件系统：容量、已用、使用率、inode 使用率。
- 块设备：读写速率、I/O 利用率。
- 网络：接口发现、流量、速率、状态、入/出错包和丢弃包。

## 二、Windows 配置 SNMP

适用于 Windows Server 2012 R2/2016/2019/2022 等仍提供 SNMP Service 的版本。Windows 10/11 或较新版本若没有系统 SNMP 服务，应改用 Zabbix Agent 2、Windows Exporter 或厂商 SNMP Agent。

### 1. 安装 SNMP Service

管理员 PowerShell：

```powershell
# Windows Server
Install-WindowsFeature -Name SNMP-Service,SNMP-WMI-Provider -IncludeManagementTools

# Windows 客户端（可选，按系统版本支持情况执行）
Add-WindowsCapability -Online -Name "SNMP.Client~~~~0.0.1.0"
```

### 2. 设置团体字和允许来源

打开 `services.msc` → **SNMP Service** → **属性**：

1. **Security / 安全**：添加只读团体字（Read Only）。
2. 选择 **Accept SNMP packets from these hosts**，只加入 Zabbix Server/Proxy 地址。
3. **Agent**：填写联系人、位置，并勾选 Physical、Applications、Internet、End-to-End 等需要的服务类型。
4. 启动并设置 **SNMP Service** 为自动。

PowerShell 验证服务：

```powershell
Get-Service SNMP
Restart-Service SNMP
```

### 3. 放行 Windows 防火墙

```powershell
New-NetFirewallRule -DisplayName "Zabbix SNMP UDP 161" -Direction Inbound -Protocol UDP -LocalPort 161 -RemoteAddress 192.0.2.10 -Action Allow
```

### 4. Windows 指标说明

- HOST-RESOURCES-MIB：CPU、内存、磁盘/文件系统、设备资源发现。
- IF-MIB：接口状态、速率、流量、错误和丢弃包。
- Generic SNMP：系统描述、名称、位置、联系人、运行时间及 SNMP 可用性。
- 注意：Windows SNMP Agent 通常不提供 Linux UCD-SNMP-MIB 的 load average、Swap 和完整 64 位接口计数器；模板会根据代理实际返回的 OID 建立项目。

## 三、在 Zabbix 5.4 添加主机

1. 导入 `os-snmp-monitoring-suite.json`：**Configuration → Templates → Import**。
2. 新建主机，添加 **SNMP interface**，填写目标 IP、端口 `161`。
3. SNMPv2c 填写只读团体字；SNMPv3 填写安全级别、用户名、认证/隐私参数。
4. 关联以下模板之一：
   - Linux：`OS Linux SNMP Enhanced`
   - Windows：`OS Windows SNMP Enhanced`
5. 等待 LLD 完成后检查 **Latest data** 和 **Problems**。
6. 使用 **Test** 或 `snmpwalk` 确认 Server/Proxy 到目标 UDP/161 可达。

不要同时关联同一操作系统的 Agent 模板和 SNMP 模板，除非明确需要双通道采集；否则会出现重复指标和重复告警。

## 四、阈值宏（与 Zabbix 告警口径一致）

在主机或模板宏中覆盖默认值。数值均为百分比，load 为平均值：

### Linux

| 宏 | 默认值 | 含义 |
|---|---:|---|
| `{$CPU_LOAD_WARN}` | `4` | 5 分钟 load 告警 |
| `{$CPU_LOAD_CRIT}` | `8` | 5 分钟 load 严重 |
| `{$MEMORY_WARN}` | `80` | 内存使用率告警 |
| `{$MEMORY_CRIT}` | `90` | 内存使用率严重（可按需增加自定义触发器） |
| `{$SWAP_WARN}` | `50` | Swap 使用率告警 |
| `{$FS_WARN}` | `80` | 文件系统使用率告警 |
| `{$FS_CRIT}` | `90` | 文件系统使用率严重 |
| `{$IF_ERRORS_WARN}` | `10` | 接口错误包变化告警 |

### Windows

| 宏 | 默认值 | 含义 |
|---|---:|---|
| `{$CPU_WARN}` | `80` | CPU 使用率告警 |
| `{$CPU_CRIT}` | `95` | CPU 使用率严重（可按需增加自定义触发器） |
| `{$MEMORY_WARN}` | `80` | 内存使用率告警 |
| `{$MEMORY_CRIT}` | `90` | 内存使用率严重（可按需增加自定义触发器） |
| `{$FS_WARN}` | `80` | 磁盘使用率告警 |
| `{$FS_CRIT}` | `90` | 磁盘使用率严重 |
| `{$IF_ERRORS_WARN}` | `10` | 接口错误包变化告警 |

告警优先级按 Zabbix 口径使用 `WARNING`、`HIGH`；恢复表达式回到阈值以下后自动恢复。阈值应结合 CPU 核数、内存容量、磁盘用途和业务低峰期校准。

## 五、排障清单

- `Timeout while connecting to 161/udp`：检查路由、防火墙、SNMP 服务绑定地址和 ACL。
- `No Such Object`：目标系统未实现该 MIB/OID；检查代理版本和模板模块。
- 只有系统信息没有磁盘/网卡：检查 SNMP View、Windows Agent 的服务类型及 Linux `rocommunity` 访问范围。
- LLD 无发现：先在 Server/Proxy 上用 `snmpwalk` 验证对应表 OID，再检查主机使用的 SNMP 接口和凭证。
