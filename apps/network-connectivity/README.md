# 网络连通性检查工具

单文件 Python CLI，支持本地或 SSH 远程源主机、IPv4 与端口范围、CSV 批量任务、默认终端打印及可选 CSV 结果导出。只用于已获得授权的地址和服务。

## 环境与依赖

- 本机 Python **3.9+**；纯标准库，**不需要 pip 安装第三方 Python 包**。
- SSH 模式：本机已有系统 OpenSSH 客户端 `ssh`；每台源主机已有 Python 3.9+，默认命令为 `python3`。
- 源为空时，不依赖 SSH；不向目标机器 SSH，不检查或修改防火墙，也不安装远程软件。
- 同一个 `.py` 文件可在具备上述环境的 **x86_64 和 ARM64 / aarch64** 上使用，无需按 CPU 架构分别安装 Python 扩展包。
- 未附带 Python 或 OpenSSH 系统安装包；它们属于环境前置条件，离线安装包需要匹配目标操作系统、版本及架构，不能仅按 x86/ARM64 通用分发。

直接复制 `network_connectivity.py` 即可运行，无需复制项目其余文件。

```sh
python3 network_connectivity.py -h
python3 network_connectivity.py --version
```

项目开发使用 `.python-version` 固定 Python 3.9，可独立打包为 Python CLI。直接运行脚本不需要构建安装；构建所需 setuptools 不是运行时依赖。

## 直接传参

```sh
# 单条任务：源为空，从运行脚本的机器发起
python3 network_connectivity.py -d 192.168.0.13 -p tcp80

# 批量任务；建议先 --dry-run 校验展开结果，不建立任何网络连接
python3 network_connectivity.py \
  -d '192.168.0.13/14/29-100' \
  -p 'tcp80/443-500/10034' --dry-run

# 指定源主机：SSH 到 192.168.1.10，以该主机为源进行检查
python3 network_connectivity.py \
  -s 192.168.1.10 -d '192.168.0.13/14' -p 'tcp80/443'

# 同时打印到终端，并写 CSV 文件（覆盖同名文件）
python3 network_connectivity.py \
  -d '192.168.0.13/14' -p 'tcp80/443' -o results.csv

# 多源、多目标、多端口，按笛卡尔积展开
python3 network_connectivity.py \
  -s '192.168.1.10/11' -d '192.168.0.13/14' -p 'tcp80/443'
```

**源 IP 不是本机网卡绑定地址**：非空即通过 SSH 到该主机执行。最终数据包的具体源地址由源主机路由决定。

### IP 表达式

支持完整 IPv4、末段数字缩写、末段闭区间和完整 IPv4 闭区间，例如：

```text
192.168.0.13/14/29-100
11.1.1.1-18/23/45
192.168.1.254-192.168.2.2
```

多个值可以用 `/`、逗号、中文逗号、分号、中文分号、空格或换行分隔。缩写继承前一个 IP 的前三段；完整范围之后继承范围终点的前三段。重复值去重并保留首次出现顺序。

**斜杠只表示分隔符，不支持 CIDR 子网**：`192.168.0.13/24` 表示两台主机 `.13` 和 `.24`，不是 `/24` 网段。目前仅支持 IPv4，不支持域名和 IPv6。

命令行多行表达式需放在同一对引号内：

```sh
python3 network_connectivity.py -d '192.168.0.13/14
192.168.1.1-3' -p 'tcp80
udp161'
```

### 端口表达式

```text
tcp80/443-500/10034
udp161/162
tcp10-14/25,udp161
```

端口范围为 1–65535，闭区间。未写协议则继承前一个协议，表达式开头默认 TCP，例如 `80/443` 等价于 `tcp80/tcp443`。

默认最多 10000 项任务，数量为“源主机数 × 目标地址数 × 协议端口数”；CSV 各行合并后全局去重。单个 IP/端口表达式和单行任务也受此上限限制。可用 `--max-tasks N` 显式调整，超限在连接之前拒绝执行。

## CSV 批量任务

```sh
# 只校验并打印计划，不进行网络连接或 SSH 登录
python3 network_connectivity.py --csv examples/tasks.csv --dry-run

# 实际执行并同时导出 CSV
python3 network_connectivity.py --csv tasks.csv --output results.csv
```

任务 CSV 使用 UTF-8（可带 BOM）：

```csv
source_ip,target_ip,target_ports
,192.168.0.13/14,tcp80/443
192.168.1.10,192.168.0.29-31,udp161
"192.168.1.10
192.168.1.11","192.168.2.1
192.168.2.2","tcp80
udp161"
```

- 一行可包含多个源、多个目标、多个端口，独立进行笛卡尔积展开。
- 单元格内的换行或逗号必须用 CSV 双引号包围。源单元格为空从本地执行，`source_ip` 整列也可省略。
- 表头也支持 `源IP,目标IP,目标端口` 或 `source,target,ports`；未知列、重复列、缺少必填值、列数错误均拒绝执行。
- `--csv` 不与 `-s/-d/-p` 混用。整份文件验证通过后才开始执行，不接受输入与输出指向同一文件。
- 为减少重复认证，任务按源主机分组执行；同源任务保持出现顺序。没有并行探测。

## SSH 认证与安全

- 默认用户 `root`，默认端口 22。可用 `--ssh-user`、`--ssh-port` 修改。
- 先使用 `BatchMode=yes` 尝试免密（支持系统 SSH 配置、SSH agent、密钥）。
- 免密认证失败时，**仅在交互终端**重试交互认证；由系统 SSH 直接提示输入密码。脚本不获取、不记录密码，也不把密码放到参数、环境变量或文件里。输入重定向、定时任务等无交互终端环境需事先配置免密。
- 首次连接同样需要交互确认主机指纹；须自行核对。主机密钥不一致时不会自动接受或删除旧记录。不会设置 `StrictHostKeyChecking=no`。
- 默认将主机密钥保存在脚本旁的 `.local/known_hosts`，不写用户家目录。也可用 `--known-hosts FILE` 选择已有的主机密钥文件；此文件不保存密码。
- Python 工作代码只通过 SSH 命令和标准输入传给源主机，不向源主机写入脚本或安装依赖；可以用 `--ssh-python /path/to/python3` 指定解释器。
- 单次 SSH 会处理该源下全部任务，完成后统一打印该源结果；其他源继续执行，不因一个源认证失败而跳过后续源。
- SSH 建连超时默认 10 秒，可用 `--ssh-timeout` 调整。`--timeout` 默认 2 秒，为每项 socket 操作的超时。

## 输出与结果语义

默认逐条打印：

```text
本机 -> 192.168.0.13 tcp/80 REACHABLE 1.230ms TCP 连接成功
```

`-o / --output` 在打印的同时写出带 UTF-8 BOM 的 CSV，方便 Excel 打开。字段：

```text
source_ip,target_ip,protocol,target_port,status,elapsed_ms,detail
```

`source_ip` 为空表示本地。输出文件的父目录需事先存在。每行写入后刷新；Ctrl+C 中断时已写出的行保留，但正在远程执行且尚未回传的一组结果不能保留。

| 状态 | 含义 |
| --- | --- |
| `REACHABLE` | TCP 连接成功，或收到 UDP 回应；不代表应用层业务正常 |
| `REFUSED` | 连接收到明确拒绝，通常为 TCP RST 或 UDP ICMP 端口不可达 |
| `TIMEOUT` | TCP 连接超时，不能据此区分服务关闭、防火墙过滤或链路丢包 |
| `UNKNOWN` | UDP 无响应，无法确认可达性或端口是否开放 |
| `NETWORK_ERROR` | 路由、权限等网络异常，详情包含函数标记及 traceback |
| `SSH_ERROR` | 无法登录源主机或远程解释器执行失败；**不代表目标不通** |
| `PLANNED` | `--dry-run` 展开的任务，未实际执行 |

UDP 默认发送空报文。很多服务会丢弃不符合协议的请求，即使服务正常也不会应答。可用 `--udp-payload-hex` 提供符合目标协议的请求内容，但本工具不内置 SNMP/DNS 等协议解析，也不能仅凭发送成功判定连通。

退出码：`0` 全部确认可达或仅预览；`1` 存在失败/不确定项；`2` 参数、输入或输出文件错误；`130` 用户中断。

## 开发与测试

开发测试仅用标准库 `unittest`，不安装测试框架。所有 socket 与 SSH 测试均为 mock，不发起真实连接。

```sh
cd apps/network-connectivity
uv venv --python 3.9 .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python network_connectivity.py --csv examples/tasks.csv --dry-run
```

`.venv`、`.local` 为项目内运行态目录，不纳入版本控制。
