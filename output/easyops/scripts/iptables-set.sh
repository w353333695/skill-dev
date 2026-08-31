#!/bin/bash
set -e

# 用法：
#   bash ip.sh 172.30.0.232 172.30.0.233 172.30.0.234
#
# 也可以传入任意多个 IP

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
iptables -P OUTPUT DROP

# ====== 本地回环 ======
iptables -A INPUT  -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# ====== 已建立/相关连接 ======
iptables -A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# ====== 参数传入的 IP 之间互访无限制 ======
for ip in "${IP_LIST[@]}"; do
  iptables -A INPUT  -s "$ip" -j ACCEPT
  iptables -A OUTPUT -d "$ip" -j ACCEPT
done

# ====== 其他来源只允许访问本机这些 TCP 端口 ======
iptables -A INPUT -p tcp -m multiport --dports "$PORTS" -j ACCEPT
