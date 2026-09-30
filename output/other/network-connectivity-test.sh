#!/usr/bin/env bash
# 网络连通性探测工具：支持从本机或指定源主机探测多个目标 IP/端口。
set -u
readonly VERSION="1.0.0"
readonly RED=$'\033[31m'
readonly RESET=$'\033[0m'

usage() {
  cat <<'EOF'
用法：network-connectivity-test.sh -d 目标IP[,目标IP...] -p 端口[,端口...] [选项]

先通过 SSH 打印目标主机的监听端口、iptables 和 firewalld 状态，
再按“源 IP × 目标 IP × 目标端口”逐项探测并输出最终 ASCII 表。

必填参数：
  -d, --dest        目标 IP/主机名，多个值用逗号分隔
  -p, --ports       目标端口，多个值用逗号分隔
可选参数：
  -s, --source      源 IP/主机名，多个值用逗号分隔；不填时从本机发起
  -P, --protocol    协议：tcp 或 udp，默认 tcp
  -t, --timeout     探测超时（秒），默认 1
  -u, --user        SSH 用户，默认当前登录用户
      --ssh-port    SSH 端口，默认 22
      --no-color    不使用 ANSI 颜色
  -V, --version     打印版本
  -h, --help        打印帮助

默认使用 SSH 免密密钥访问目标和远程源主机，不读取或保存密码。
依赖：bash、ssh、nc（或 netcat）；远端需有 ss（无 ss 时尝试 netstat）。

示例：
  network-connectivity-test.sh -d 10.0.0.10,10.0.0.11 -p 80,443
  network-connectivity-test.sh -s 10.0.1.20,10.0.1.21 -d 10.0.0.10 -p 53 -P udp -t 2
EOF
}

die() { printf '错误：%s\n' "$*" >&2; exit 2; }
log_section() { printf '\n===== %s =====\n' "$*"; }

run_and_show() {
  local label=$1; shift; local out err rc
  printf '\n[%s]\n$' "$label"; printf ' %q' "$@"; printf '\n'
  out=$(mktemp); err=$(mktemp)
  "$@" >"$out" 2>"$err"; rc=$?
  printf '%s\n' '--- 标准输出 ---'; [[ -s $out ]] && cat "$out" || printf '(空)\n'
  printf '%s\n' '--- 标准错误 ---'; [[ -s $err ]] && cat "$err" || printf '(空)\n'
  printf '%s\n' "--- 退出码：$rc ---"
  rm -f "$out" "$err"; return "$rc"
}

ssh_run_and_show() {
  local label=$1 host=$2 command=$3
  run_and_show "$label" ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" \
    -p "$SSH_PORT" "$SSH_USER@$host" "$command"
}

validate_csv() {
  local value=$1 name=$2 item
  [[ -n $value ]] || die "$name 不能为空"
  IFS=',' read -r -a _items <<< "$value"
  for item in "${_items[@]}"; do [[ -n $item ]] || die "$name 包含空值：$value"; done
}

validate_ports() {
  local value=$1 port
  IFS=',' read -r -a _ports <<< "$value"
  for port in "${_ports[@]}"; do
    [[ $port =~ ^[0-9]+$ ]] || die "端口必须是数字：$port"
    (( port >= 1 && port <= 65535 )) || die "端口范围必须是 1-65535：$port"
  done
}

validate_timeout() {
  [[ $1 =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]] || die "超时必须是正数秒：$1"
  awk -v value="$1" 'BEGIN { exit !(value > 0) }' || die "超时必须大于 0：$1"
}

split_csv() { IFS=',' read -r -a SPLIT_RESULT <<< "$1"; }

print_target_inspection() {
  local target=$1
  log_section "目标 $target：端口监听与防火墙状态"
  ssh_run_and_show "${target} 监听端口（ss -lntup）" "$target" \
    'if command -v ss >/dev/null 2>&1; then ss -lntup; elif command -v netstat >/dev/null 2>&1; then netstat -lntup; else echo "未找到 ss/netstat" >&2; exit 127; fi' || true
  ssh_run_and_show "${target} iptables" "$target" \
    'if command -v iptables >/dev/null 2>&1; then iptables -L -n -v --line-numbers; else echo "未找到 iptables" >&2; exit 127; fi' || true
  ssh_run_and_show "${target} firewalld" "$target" \
    'if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --state; firewall-cmd --list-all; else echo "未找到 firewall-cmd" >&2; exit 127; fi' || true
}

probe_one() {
  local source=$1 target=$2 port=$3 out err rc detail command_string
  local -a command
  if [[ $PROTOCOL == tcp ]]; then command=("$NC_BIN" -zv -w "$TIMEOUT" "$target" "$port"); else command=("$NC_BIN" -u -zv -w "$TIMEOUT" "$target" "$port"); fi
  printf '\n[%s -> %s:%s/%s]\n' "${source:-本机}" "$target" "$port" "$PROTOCOL"
  out=$(mktemp); err=$(mktemp)
  if [[ -n $source ]]; then
    command_string=$(printf '%q ' "${command[@]}")
    printf '$ ssh -o BatchMode=yes -p %q %q %q\n' "$SSH_PORT" "$SSH_USER@$source" "$command_string"
    ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -p "$SSH_PORT" \
      "$SSH_USER@$source" "$command_string" >"$out" 2>"$err"; rc=$?
  else
    printf '$'; printf ' %q' "${command[@]}"; printf '\n'
    "${command[@]}" >"$out" 2>"$err"; rc=$?
  fi
  printf '%s\n' '--- 标准输出 ---'; [[ -s $out ]] && cat "$out" || printf '(空)\n'
  printf '%s\n' '--- 标准错误 ---'; [[ -s $err ]] && cat "$err" || printf '(空)\n'
  printf '%s\n' "--- 退出码：$rc ---"
  detail=$(tr '\n' ' ' < "$err" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')
  [[ -n $detail ]] || detail=$(tr '\n' ' ' < "$out" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')
  [[ -n $detail ]] || detail='无输出'
  detail=${detail//|/\/}
  if (( rc == 0 )); then status='通'; else status='不通'; fi
  RESULTS+=("${source:-本机}|$target|$port|$PROTOCOL|$status|$detail")
  rm -f "$out" "$err"
}

print_results() {
  local row source target port protocol status detail
  log_section '最终探测结果'
  printf '+%-18s+%-18s+%-8s+%-8s+%-10s+%-48s+\n' '源' '目标' '端口' '协议' '结果' '说明'
  printf '+%-18s+%-18s+%-8s+%-8s+%-10s+%-48s+\n' '------------------' '------------------' '--------' '--------' '----------' '------------------------------------------------'
  for row in "${RESULTS[@]}"; do
    IFS='|' read -r source target port protocol status detail <<< "$row"; detail=${detail:0:48}
    if [[ $status == '不通' && $COLOR == 1 ]]; then
      printf '|%-18s|%-18s|%-8s|%-8s|\033[31m%-10s\033[0m|%-48s|\n' "$source" "$target" "$port" "$protocol" "$status" "$detail"
    else
      printf '|%-18s|%-18s|%-8s|%-8s|%-10s|%-48s|\n' "$source" "$target" "$port" "$protocol" "$status" "$detail"
    fi
  done
  printf '+%-18s+%-18s+%-8s+%-8s+%-10s+%-48s+\n' '------------------' '------------------' '--------' '--------' '----------' '------------------------------------------------'
}

DESTS=''; PORTS=''; SOURCES=''; PROTOCOL=tcp; TIMEOUT=1
SSH_USER=${USER:-$(id -un)}; SSH_PORT=22; SSH_CONNECT_TIMEOUT=5; COLOR=1
while (($#)); do
  case $1 in
    -d|--dest) [[ $# -ge 2 ]] || die "$1 需要参数"; DESTS=$2; shift 2;;
    -p|--ports) [[ $# -ge 2 ]] || die "$1 需要参数"; PORTS=$2; shift 2;;
    -s|--source) [[ $# -ge 2 ]] || die "$1 需要参数"; SOURCES=$2; shift 2;;
    -P|--protocol) [[ $# -ge 2 ]] || die "$1 需要参数"; PROTOCOL=${2,,}; shift 2;;
    -t|--timeout) [[ $# -ge 2 ]] || die "$1 需要参数"; TIMEOUT=$2; shift 2;;
    -u|--user) [[ $# -ge 2 ]] || die "$1 需要参数"; SSH_USER=$2; shift 2;;
    --ssh-port) [[ $# -ge 2 ]] || die "$1 需要参数"; SSH_PORT=$2; shift 2;;
    --no-color) COLOR=0; shift;;
    -V|--version) printf '%s\n' "$VERSION"; exit 0;;
    -h|--help) usage; exit 0;;
    *) die "未知参数：$1（使用 -h 查看帮助）";;
  esac
done

validate_csv "$DESTS" '目标 IP'; validate_csv "$PORTS" '目标端口'; validate_ports "$PORTS"
[[ $PROTOCOL == tcp || $PROTOCOL == udp ]] || die '协议只能是 tcp 或 udp'
validate_timeout "$TIMEOUT"
[[ $SSH_PORT =~ ^[0-9]+$ && $SSH_PORT -ge 1 && $SSH_PORT -le 65535 ]] || die "SSH 端口无效：$SSH_PORT"
command -v ssh >/dev/null 2>&1 || die '本机未找到 ssh'
NC_BIN=$(command -v nc || command -v netcat || true)
[[ -n $NC_BIN ]] || die '本机未找到 nc/netcat'
split_csv "$DESTS"; DEST_ARRAY=("${SPLIT_RESULT[@]}"); split_csv "$PORTS"; PORT_ARRAY=("${SPLIT_RESULT[@]}")
if [[ -n $SOURCES ]]; then split_csv "$SOURCES"; SOURCE_ARRAY=("${SPLIT_RESULT[@]}"); else SOURCE_ARRAY=(''); fi
RESULTS=()
for target in "${DEST_ARRAY[@]}"; do print_target_inspection "$target"; done
for source in "${SOURCE_ARRAY[@]}"; do for target in "${DEST_ARRAY[@]}"; do for port in "${PORT_ARRAY[@]}"; do probe_one "$source" "$target" "$port"; done; done; done
print_results
for row in "${RESULTS[@]}"; do [[ $row == *'|不通|'* ]] && exit 1; done
exit 0
