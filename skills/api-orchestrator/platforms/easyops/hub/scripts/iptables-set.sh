#!/bin/bash
set -e

# 用法：
#   bash iptables-set.sh 172.30.0.232 172.30.0.233 172.30.0.234
#
# 传入任意多个 IP（目标 ip 列表）
#
# 目标（2026-10-21 调整）：
#   · 目标 ip 之间：互访不限制（入出双向全通）
#   · 目标 ip 对外：只对外开放这些 TCP 端口（PORTS）
#   · 出站：不限制（OUTPUT 全通——服务端主动出站访问任意地址任意端口）

IP_LIST=("$@")
PORTS="80,443,5511,8820,1888"

if [ "${#IP_LIST[@]}" -eq 0 ]; then
  echo "Usage: $0 ip1 [ip2 ip3 ...]"
  exit 1
fi

# ====== 清理旧规则 ======
iptables -F
iptables -X
iptables -Z

# ====== 默认策略 ======
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# ====== 本地回环 ======
iptables -A INPUT  -i lo -j ACCEPT

# ====== 已建立/相关连接 ======
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# ====== 目标 ip 之间互访无限制（其余目标 ip 进来的流量全放行）======
for ip in "${IP_LIST[@]}"; do
  iptables -A INPUT -s "$ip" -j ACCEPT
done

# ====== 其他来源只允许访问本机这些 TCP 端口 ======
iptables -A INPUT -p tcp -m multiport --dports "$PORTS" -j ACCEPT
