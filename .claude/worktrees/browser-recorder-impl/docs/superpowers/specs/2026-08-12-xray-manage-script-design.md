# Xray VLESS-Reality 部署管理脚本 设计

- 日期: 2026-08-12
- 状态: 已确认
- 范围: 单文件 Bash 脚本，封装 Xray-core + VLESS-Reality 的安装、多用户管理、凭据分发、卸载

## 目标

在任意 Linux（Debian/Ubuntu 系优先，兼容 RHEL 系）上一条命令装好 Xray 服务端（VLESS + Reality），并通过子命令增删用户、输出客户端凭据。无需域名、无需证书。

## 非目标 (YAGNI)

- 不做订阅 URL 托管（多用户通过 `add/show` 逐个分发即可）
- 不做流量统计 / 套餐到期（无面板诉求）
- 不做多入站协议切换（仅 VLESS-Reality）
- 不自动续期证书（Reality 不需要）

## 子命令

```
xray-manage.sh install   [--port 443] [--dest www.yahoo.com:443]
xray-manage.sh add       <name>
xray-manage.sh remove    <name>
xray-manage.sh list
xray-manage.sh show      <name>
xray-manage.sh status
xray-manage.sh uninstall
```

以 root 运行。

## 核心设计：配置渲染分离

inbound 的 `clients` 数组每次增删都要改，直接 jq 改 config.json 易出错。采用 **模板 + 用户清单分离渲染**：

- `users.json` —— 用户清单，唯一真相源。结构：
  ```json
  { "alice": {"uuid": "...", "flow": "xtls-rprx-vision"}, "bob": {...} }
  ```
- `config.template.json` —— 含 `__CLIENTS__` 占位符的完整模板。
- `config.json` —— 渲染产物，xray 实际读取。

`add/remove` 改 users.json → jq 把 users 渲染成 clients 数组 → 注入模板 → 写 config.json → `systemctl reload`（失败回退 restart）。幂等、可从 users.json 完全重建。

## 路径约定

```
/usr/local/bin/xray                      二进制
/usr/local/share/xray/{geoip,geosite}.dat
/etc/xray-manage/
  ├── config.json                        渲染产物
  ├── config.template.json               模板
  ├── users.json                         真相源
  ├── server.json                        私钥/公钥/端口/sni/shortId
  └── meta.conf                          公网IP 等
/etc/systemd/system/xray.service
```

密钥文件 `chmod 600`。

## install 流程

1. 校验 root；探测架构（`uname -m` → amd64/arm64/armv7）。
2. 检测并提示安装依赖：`jq`、`curl`、`openssl`、`qrencode`（可选，缺则跳过 QR）。
3. `curl` 拉 Xray 最新 release（GitHub API 取 latest tag），按架构解压；二进制装到 `/usr/local/bin/xray`，geo 数据装到 `/usr/local/share/xray/`。
4. `xray x25519` 生成 Reality 密钥对 → 私钥入 `server.json`，公钥留给客户端。
5. 生成 `shortId`（`openssl rand -hex 8`）。
6. Reality `dest`/`serverNames` 默认 `www.yahoo.com:443`，可 `--dest` 覆盖。
7. 写 config.template.json + 空 users.json + 渲染 config.json。
8. 写 systemd unit，`enable --now`。
9. 探测公网 IP（`curl -s4 ifconfig.me`，失败回退 `ip.sb`），存 `meta.conf`。
10. 防火墙放行：探测顺序 `ufw` → `firewall-cmd` → `iptables`；都没有则提示手动放行。
11. 打印摘要，提示 `add <name>` 加首个用户。

## add `<name>` 流程

1. 名称查重（users.json 已存在则报错退出）。
2. 生成 UUID（`cat /proc/sys/kernel/random/uuid`）。
3. 写 users.json（`flow: xtls-rprx-vision`），重渲染 config.json，reload。
4. 输出：
   - **vless:// 分享链接**（`security=reality`，含 pbk/sid/sni/fp=chrome，默认 flow=xtls-rprx-vision）
   - **二维码**（有 qrencode 则终端打印 `-t ANSIUTF8`，否则提示安装命令）
   - **客户端 outbound JSON 片段**

## 其他子命令

- `remove <name>`：从 users.json 删，重渲染，reload。删除后打印确认。
- `list`：表格输出 name / uuid / flow。
- `show <name>`：复用 add 的三件套输出函数。
- `status`：服务 active? + 监听端口（`ss -tlnp`）+ 公网IP + 用户数。
- `uninstall`：二次确认 → stop+disable → 删二进制/配置/systemd unit → `users.json` 备份到 `/etc/xray-manage.bak.<时间>`。

## vless:// 链接格式

```
vless://<uuid>@<public_ip>:<port>?encryption=none&flow=xtls-rprx-vision&security=reality&sni=<sni>&fp=chrome&pbk=<pubkey>&sid=<shortid>&type=tcp#<name>
```

## 健壮性

- 所有外部命令（systemctl/curl/jq/xray）调用后检查退出码，失败即中止并打印中文提示。
- `set -euo pipefail`；`trap` 捕获异常退出。
- 颜色输出（`_ok`/`_warn`/`_err`），非交互环境自动关闭颜色。
- reload 失败回退 restart，restart 失败回滚 config.json 到 `.bak` 并报错。
- 防火墙探测不可用时只 warn 不 fail。
