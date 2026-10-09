# Keepalived 配置工具

本目录提供可直接运行的 Python 工具 `ha-configure.py` 和详细注释示例 `ha.sample.yaml`。部署时拷贝这两份文件即可，README 与 tests 用于说明和开发验证。业务服务不需要注册到 systemd；部署 Keepalived 本身使用 Linux 默认 systemd 服务。

## 依赖

- 生成和校验：Python 3.9+、PyYAML。
- 进程检查：目标机器安装 `pgrep`，Linux 通常由 procps/procps-ng 提供。
- TCP、HTTP 检查：生成脚本使用 Python 标准库，无需 nc/curl。
- 应用：Linux、root、已安装的 keepalived、systemctl、ip；使用 `/etc/keepalived/keepalived.conf` 默认配置。

工具不会自动安装软件。可在本目录创建独立环境，避免污染系统 Python：

```bash
cd output/other/keepalived
python3 -m venv .venv
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv pip install --python .venv/bin/python PyYAML
# 使用独立环境时直接通过 .venv/bin/python 调用 ha-configure.py。
```

部署 root 运行时，应使用 root 管理且不可被普通用户写入的 Python 环境。生成配置固定引用生成时的 Python 解释器绝对路径，运行节点上该路径必须持续存在；不要使用随后会删除的临时 venv。

## 使用

```bash
cd output/other/keepalived
cp ha.sample.yaml ha.yaml
# 修改 ha.yaml 中的 VIP、真实地址、网卡和健康检查。
python3 ./ha-configure.py --help
python3 ./ha-configure.py --config ha.yaml --node node-a --dry-run
python3 ./ha-configure.py --config ha.yaml --node node-a --check
sudo python3 ./ha-configure.py --config ha.yaml --node node-a --apply
```

如果使用独立 Python 环境，请直接指定解释器路径：

```bash
sudo /实际/root管理环境/bin/python ./ha-configure.py --config ha.yaml --node node-a --apply
```

另一台机器使用同一 YAML，将 `--node` 改为 `node-b`。每次只作用于本机，不自动通过 SSH 安装其他节点。

## 操作行为

- `--dry-run`：严格校验 YAML，生成文件并打印 Keepalived 配置；不写系统目录，不执行健康请求。
- `--check`：校验、生成，并执行一轮检查；逐项打印结果、异常堆栈及汇总。不需要 Keepalived 已安装。
- `--apply`：确认真实 IP 在指定网卡上，安装健康脚本，运行 Keepalived 配置校验，备份旧配置，再替换并重启。重启失败时恢复旧配置，按原先是否运行恢复/停止服务。
- 配置校验使用兼容旧版本的 `keepalived -t -f <文件>`。如果 Keepalived 自身以 `SIGSEGV`（退出码 139）崩溃，工具不会替换正式配置，会在 `/etc/keepalived/keepalived.conf.config-test-failed-*` 保留失败文件并打印版本信息；此时应升级或更换 Keepalived 二进制，不能跳过校验。
- 生成的 `vrrp_script` 直接执行带绝对 shebang 的健康脚本，不把 Python 解释器拼在 Keepalived 的 `script` 字段中。配置使用 `script_user root`、`enable_script_security` 和 `init_fail`，满足新版 Keepalived 的脚本安全校验；健康脚本安装为 root 所有、权限 `0700`。
- 应用只检查配置和服务启动，不强制要求当前节点业务健康；备用节点业务暂时不健康时可以安装，是否持有 VIP 交给健康检查。生成的 VIP 使用 `IP/掩码` 的保守写法，不在 `virtual_ipaddress` 行追加 `dev`，因为 VRRP 实例已经声明网卡，兼容较老 Keepalived。
- 默认产物目录：脚本目录 `generated/<node>/`；可用 `--output-dir` 修改。配置中记录的是部署路径，不是产物路径，不能直接拿产物配置启动而漏装健康脚本。
- 健康脚本使用内容哈希命名；旧配置备份仍可引用旧脚本。工具不自动删除旧脚本和备份。
- 不修改防火墙、业务服务、Keepalived 开机启动策略；需要自启时自行执行 `sudo systemctl enable keepalived`。
- 应用会重启 Keepalived，VIP 可能短暂释放；建议先部署备用节点，再在变更窗口部署当前持有 VIP 的节点。
- 不自动合并已有多个 VRRP 实例，替换前请查看备份及预览；自定义 systemd 启动参数的环境需要自行适配。

## 检查规则

详见 `ha.sample.yaml` 中逐字段备注。`all` 要求全部成功；`any` 要求至少一项成功；`quorum` 配合 `min_success` 要求至少 N 项成功。检查并行，单项超时和整轮硬超时都视为失败。

进程匹配为 pgrep 正则；TCP 只证明连接可建立；HTTP 可以同时检查状态码和正文子串。优先用本机 readiness 接口，不要用 VIP 检查备用节点业务。HTTP 禁用代理、不跟随重定向、HTTPS 验证证书。

退出码：`0` 操作成功/检查健康；`1` 检查不健康或整轮超时；`2` 配置/依赖/执行错误；`130` 用户中断。`--check` 只是一轮检查，不累计 `fall/rise`，这些由运行中的 Keepalived 管理。

## 验收与回退

应用后通过 `systemctl status keepalived`、`journalctl -u keepalived` 和 `ip address show dev <网卡>` 确认启动及 VIP 所在节点。服务启动成功不代表健康条件成功或 VIP 一定由本机持有。

旧配置保存在 `/etc/keepalived/keepalived.conf.bak-时间-进程号`；手动回退时将对应备份恢复为 `keepalived.conf` 并重启服务，保留它引用的哈希健康脚本。

当前工具已在开发环境做生成与模拟检查验证；真实双机 VRRP、ARP 与网络故障切换需要在目标 Linux 环境验收。
