#!/usr/bin/env bash
# =============================================================================
# EasyOps 平台集群安全加固脚本（批量版）
#   依据: tmp/安全加固1111.txt 步骤 1~5（步骤 6 proxy_server / 步骤 7 验证 不在范围内）
#
# 覆盖内容:
#   步骤1  iptables 加固: 集群 IP 全放行, 对外仅开 22/80/443/5511/8820(+8823 可选),
#         其余封闭; 并保存规则到 /etc/iptables/rules.ipv4.hardening
#   步骤2  PHP 加固: php.custom.ini 增加 expose_php=Off;
#         ExecShell.php md5 校验(可选替换); tools/src/www 目录只应有两个文件(多余隔离)
#   步骤3  检测工具库/流程库是否已割接 tool_service (仅检测报告, 不做变更)
#   步骤4  nginx tool.conf / cmdb*.conf 增加集群白名单 allow ... deny all
#   步骤5  停用无关 nginx conf (itsm/文件预览/CD 分发相关默认保留), nginx -t 通过才 reload
#
# 特性:
#   - 幂等: 可重复执行, 已满足的项自动跳过
#   - 详细日志: 全部步骤输出到终端 + logs/<mode>_<datetime>.log
#   - 备份: 变更前自动备份到 脚本同级目录/backup/<节点IP>/<执行时间>/, 含 manifest.tsv
#   - 回滚: --rollback 按节点恢复最近一次备份(或 --backup-dt 指定), 含 iptables/nginx/php
#   - 批量: 执行节点需有所有节点的 SSH 免密; 一次覆盖所有节点
#
# 用法:
#   加固:   bash easyops_hardening.sh <ip1> <ip2> ... [选项]
#           bash easyops_hardening.sh --ips 1.1.1.1,1.1.1.2 [选项]
#   回滚:   bash easyops_hardening.sh --rollback <ip1> <ip2> [--backup-dt 20260831-120000]
#
# 选项:
#   --ips list              集群 IP 列表(逗号分隔, 与位置参数等价)
#   --ssh-user user         SSH 用户(默认 root)
#   --ssh-port port         SSH 端口(默认 22)
#   --with-8823             强制对外开放 8823(3.0 监控); 默认按节点是否监听 8823 自动判断
#   --extra-ports p1,p2     额外对外开放的 TCP 端口(如 10050)
#   --extra-allow-ips list  额外全放行的源 IP(如 zabbix/堡垒机)
#   --disable-itsm          停用 itsc_mobile.conf / file_preview.conf(默认保留)
#   --disable-cd            停用 php.deploy.conf / php.deploy_repository.conf(默认保留)
#   --execshell-src PATH    本地正确版本的 ExecShell.php(md5 不符时用于替换并重启组件)
#   --skip-iptables         跳过步骤1
#   --skip-php              跳过步骤2
#   --skip-nginx            跳过步骤4/5
#   --dry-run               只检查并打印将要执行的动作, 不做任何变更
#   --rollback              回滚模式
#   --backup-dt datetime    配合 --rollback 指定备份时间目录(默认取该节点最新一次)
#   -h | --help             帮助
#
# 示例:
#   bash easyops_hardening.sh 172.30.0.232 172.30.0.233 172.30.0.234
#   bash easyops_hardening.sh --ips 172.30.0.232,172.30.0.233 --extra-allow-ips 10.0.0.8
#   bash easyops_hardening.sh --rollback 172.30.0.232 172.30.0.233
# =============================================================================
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BK_ROOT="$SCRIPT_DIR/backup"
LOG_DIR="$SCRIPT_DIR/logs"

# ---------------- 缺省参数 ----------------
MODE="apply"
SSH_USER="root"
SSH_PORT="22"
FORCE_8823=false
DISABLE_ITSM=false
DISABLE_CD=false
DRY_RUN=false
SKIP_IPT=false
SKIP_PHP=false
SKIP_NGINX=false
EXEC_SHELL_SRC=""
BACKUP_DT=""
EXTRA_PORTS=""
EXTRA_ALLOW_IPS=""
NODES=()

# 期望的 md5 值(来自加固文档)
MD5_EXECSHELL="73172d549a5dcdcc9a8ca48f0b045c0d"
MD5_INDEX="cf227920c8c4a93a91434c2ad037e298"
MD5_PHPINFO="32f75843ae5d5e7cfa60e32306bb0120"

# 对外开放的端口(步骤1)
BASE_OPEN_PORTS="22,80,443,5511,8820"

usage() { sed -n '3,57p' "${BASH_SOURCE[0]}"; }

err_exit() { printf '[错误] %s\n' "$*" >&2; exit 1; }

# ---------------- 参数解析 ----------------
while [ $# -gt 0 ]; do
  case "$1" in
    --ips)              IFS=',' read -r -a _tmp_arr <<<"$2"; NODES+=("${_tmp_arr[@]}"); shift 2 ;;
    --ssh-user)         SSH_USER="$2"; shift 2 ;;
    --ssh-port)         SSH_PORT="$2"; shift 2 ;;
    --with-8823)        FORCE_8823=true; shift ;;
    --extra-ports)      EXTRA_PORTS="$2"; shift 2 ;;
    --extra-allow-ips)  EXTRA_ALLOW_IPS="$2"; shift 2 ;;
    --disable-itsm)     DISABLE_ITSM=true; shift ;;
    --disable-cd)       DISABLE_CD=true; shift ;;
    --execshell-src)    EXEC_SHELL_SRC="$2"; shift 2 ;;
    --skip-iptables)    SKIP_IPT=true; shift ;;
    --skip-php)         SKIP_PHP=true; shift ;;
    --skip-nginx)       SKIP_NGINX=true; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --rollback)         MODE="rollback"; shift ;;
    --backup-dt)        BACKUP_DT="$2"; shift 2 ;;
    -h|--help)          usage; exit 0 ;;
    -*)                 err_exit "未知参数: $1 (用法见 --help)" ;;
    *)                  NODES+=("$1"); shift ;;
  esac
done

# IP 去空/去重(保序)
_dedupe=(); _seen=" "
for _n in "${NODES[@]}"; do
  [ -z "$_n" ] && continue
  case " $_seen " in *" $_n "*) ;; *) _dedupe+=("$_n"); _seen="$_seen$_n " ;; esac
done
NODES=("${_dedupe[@]:-}")
[ "${#NODES[@]}" -eq 0 ] && { usage; err_exit "请至少传入一个平台节点 IP"; }

valid_ip() { echo "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; }
for _n in "${NODES[@]}"; do
  valid_ip "$_n" || printf '[警告] %s 不是标准 IPv4 格寸, 将按主机名尝试\n' "$_n"
done

# ---------------- 运行日志 ----------------
RUN_DT=$(date '+%Y%m%d-%H%M%S')
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/${MODE}_${RUN_DT}.log"
: >"$RUN_LOG"

_log() { printf '%s [%s] %s\n' "$(date '+%F %T')" "$1" "$2" | tee -a "$RUN_LOG"; }
log_info() { _log INFO  "$*"; }
log_ok()   { _log "OK " "$*"; }
log_warn() { _log WARN "$*"; }
log_err()  { _log ERR  "$*"; }
step_banner() {
  { echo ""; echo "=============================================================="; \
    printf '%s ===== %s =====\n' "$(date '+%F %T')" "$*"; \
    echo "=============================================================="; } | tee -a "$RUN_LOG"
}

# ---------------- 本机判断 / 远程执行 ----------------
# 本机 IP 集合(用于把"本节点"直接本地执行, 避免 ssh 自连)
LOCAL_IPS=" 127.0.0.1 localhost $(hostname -I 2>/dev/null || ip -4 -o addr 2>/dev/null | awk '{print $4}' | cut -d/ -f1) "
is_local() { case " $LOCAL_IPS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes"

# rn <node> <cmd> : 在节点上执行命令(本地节点用子 shell 执行), 返回命令退出码
rn() {
  local node="$1" cmd="$2"
  if is_local "$node"; then ( eval "$cmd" ); else ssh $SSH_OPTS -p "$SSH_PORT" "${SSH_USER}@${node}" "$cmd"; fi
}

# rn_out <node> <cmd> : 同 rn, 但把输出也记录到日志
rn_out() {
  local node="$1" cmd="$2"
  _log CMD "[$node]# $cmd"
  rn "$node" "$cmd" 2>&1 | tee -a "$RUN_LOG"
  return "${PIPESTATUS[0]}"
}

# fetch <node> <remote_path> <local_path>
fetch() {
  local node="$1" rpath="$2" lpath="$3"
  if is_local "$node"; then cp "$rpath" "$lpath"; else
    scp -q -P "$SSH_PORT" $SSH_OPTS "${SSH_USER}@${node}:${rpath}" "$lpath"
  fi
}

# push <node> <local_path> <remote_path>
push() {
  local node="$1" lpath="$2" rpath="$3"
  if is_local "$node"; then cp "$lpath" "$rpath"; else
    scp -q -P "$SSH_PORT" $SSH_OPTS "$lpath" "${SSH_USER}@${node}:${rpath}"
  fi
}

# ---------------- 备份与清单 ----------------
bk_dir() { echo "$BK_ROOT/$1/$2"; }                       # bk_dir <node> <dt>
_manifest() { printf '%s\t%s\t%s\t%s\n' "$2" "$3" "$4" "$5" >> "$1/manifest.tsv"; }
manifest_add() { _manifest "$(bk_dir "$1" "$RUN_DT")" "$2" "$3" "$4" "$5"; }

# backup_file <node> <remote_path> <标记(FILE/MV/Q)>
#   返回: 0=已备份  1=远端文件不存在(跳过)  2=备份失败
backup_file() {
  local node="$1" rpath="$2" tag="${3:-FILE}" rel bn dst
  rel="/${rpath#/}"
  bn=$(printf '%s' "$rel" | sed 's|^/||; s|/|_|g')
  dst="$(bk_dir "$node" "$RUN_DT")/${tag}_${bn}"
  if ! rn "$node" "test -e '$rpath'"; then return 1; fi
  if ! fetch "$node" "$rpath" "$dst"; then return 2; fi
  manifest_add "$node" "$tag" "$rpath" "${tag}_${bn}" "变更前备份"
  log_info "[$node] 已备份 $rpath -> backup/$node/$RUN_DT/${tag}_${bn}"
  return 0
}

# ---------------- 步骤1: iptables 加固 ----------------
# 说明:
#   - 使用 iptables-restore 整体替换 filter 表 => 天然幂等, 重复执行结果一致
#   - 放行: lo / ESTABLISHED / 集群IP+额外IP 全访问 / 指定端口对外
#   - 应用前先快照当前规则到备份目录, 断连时可恢复
step1_iptables() {
  local node="$1"
  step_banner "[$node] 步骤1: iptables 加固(仅集群IP全放行 + 开放 $BASE_OPEN_PORTS 端口)"

  if ! rn "$node" "command -v iptables >/dev/null 2>&1"; then
    log_warn "[$node] 未安装 iptables, 跳过本步骤"; return 3
  fi

  local pre_dst; pre_dst="$(bk_dir "$node" "$RUN_DT")/iptables_rules.pre"
  if rn "$node" "iptables-save" >"$pre_dst" 2>>"$RUN_LOG"; then
    manifest_add "$node" "IPT" "iptables" "iptables_rules.pre" "变更前规则快照"
    log_info "[$node] 已快照变更前 iptables 规则"
    grep -q 'DOCKER' "$pre_dst" 2>/dev/null && \
      log_warn "[$node] 检测到 DOCKER 链, 本次整体替换 filter 表会将其清除(如有容器业务请知悉)"
  else
    log_warn "[$node] iptables-save 快照失败, 为安全起见跳过本节点 iptables 步骤"; return 3
  fi

  # 8823: 默认按节点是否监听自动判断, 可用 --with-8823 强制
  local ports="$BASE_OPEN_PORTS"
  if $FORCE_8823; then
    ports="$ports,8823"; log_info "[$node] --with-8823 指定, 对外开放 8823"
  elif rn "$node" "(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null) | grep -Eq ':8823[[:space:]]'"; then
    ports="$ports,8823"; log_info "[$node] 检测到节点监听 8823(3.0 监控), 对外开放 8823"
  else
    log_info "[$node] 未监听 8823, 不开放"
  fi
  if [ -n "$EXTRA_PORTS" ]; then ports="$ports,${EXTRA_PORTS// /,}"; log_info "[$node] 额外开放端口: $EXTRA_PORTS"; fi
  # 去重端口
  ports=$(echo "$ports" | tr ',' '\n' | awk 'NF' | sort -u | paste -sd, -)

  # 全放行源: 集群 IP + 额外 IP (SSH 来源不豁免, 仅经 22 端口规则访问)
  local -A _seen_ip=()
  local -a allow_ips=()
  local ip
  for ip in "${NODES[@]}" $(echo "$EXTRA_ALLOW_IPS" | tr ',' ' '); do
    [ -z "$ip" ] && continue
    [ -n "${_seen_ip[$ip]:-}" ] && continue
    _seen_ip[$ip]=1; allow_ips+=("$ip")
  done

  # 生成规则文件(存档于备份目录, 便于审计)
  local rules_dst; rules_dst="$(bk_dir "$node" "$RUN_DT")/iptables_rules.new"
  {
    echo "*filter"
    echo ":INPUT DROP [0:0]"
    echo ":FORWARD DROP [0:0]"
    echo ":OUTPUT ACCEPT [0:0]"
    echo "-A INPUT -i lo -j ACCEPT"
    echo "-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    for ip in "${allow_ips[@]}"; do echo "-A INPUT -s ${ip}/32 -j ACCEPT"; done
    echo "-A INPUT -p tcp -m multiport --dports ${ports} -j ACCEPT"
    echo "COMMIT"
  } >"$rules_dst"
  log_info "[$node] 生成 iptables 规则如下(存档: backup/$node/$RUN_DT/iptables_rules.new):"
  sed 's/^/    /' "$rules_dst" | tee -a "$RUN_LOG"

  if $DRY_RUN; then log_info "[$node] [dry-run] 跳过规则应用与保存"; return 0; fi

  push "$node" "$rules_dst" "/tmp/easyops_ipt_rules.$$" || { log_err "[$node] 规则文件下发失败"; return 3; }
  if ! rn "$node" "iptables-restore < /tmp/easyops_ipt_rules.$$ && rm -f /tmp/easyops_ipt_rules.$$"; then
    log_err "[$node] iptables-restore 执行失败, 尝试恢复变更前快照"
    push "$node" "$pre_dst" "/tmp/easyops_ipt_pre.$$" && rn "$node" "iptables-restore < /tmp/easyops_ipt_pre.$$ && rm -f /tmp/easyops_ipt_pre.$$"
    return 3
  fi

  # 连通性自检(规则误杀会导致这里失败)
  if ! rn "$node" "echo iptables-alive" >/dev/null 2>&1; then
    log_err "[$node] 应用规则后 SSH 失联! 尝试恢复快照"
    push "$node" "$pre_dst" "/tmp/easyops_ipt_pre.$$" && rn "$node" "iptables-restore < /tmp/easyops_ipt_pre.$$" \
      && log_warn "[$node] 已恢复变更前规则" || log_err "[$node] 自动恢复失败, 请通过带外通道手工恢复: iptables-restore < 备份文件"
    return 3
  fi
  log_ok "[$node] iptables 规则已应用, INPUT 当前策略: $(rn "$node" "iptables -S INPUT" 2>/dev/null | head -1)"

  # 保存(文档要求持久化到 /etc/iptables/)
  rn "$node" "mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.ipv4.hardening" \
    && log_ok "[$node] 规则已保存: /etc/iptables/rules.ipv4.hardening" \
    || { log_err "[$node] 规则保存失败"; return 3; }
  return 0
}

# ---------------- 步骤2: PHP 加固 ----------------
# 2.1 php.custom.ini 增加 expose_php=Off (幂等: 已有 expose_php 行则原位改 Off)
step2_php_ini() {
  local node="$1" ini="/usr/local/easyops/php/lib/php.custom.ini"
  step_banner "[$node] 步骤2.1: PHP expose_php=Off ($ini)"

  if ! rn "$node" "test -d /usr/local/easyops/php"; then
    log_warn "[$node] 不存在 /usr/local/easyops/php, 跳过"; return 3
  fi

  if rn "$node" "test -f '$ini' && grep -Eq '^[[:space:]]*expose_php[[:space:]]*=' '$ini'"; then
    if rn "$node" "grep -Eq '^[[:space:]]*expose_php[[:space:]]*=[[:space:]]*Off' '$ini'"; then
      log_ok "[$node] expose_php 已为 Off, 跳过"; return 0
    fi
    backup_file "$node" "$ini" || log_warn "[$node] $ini 备份失败, 继续前请确认"
    if $DRY_RUN; then log_info "[$node] [dry-run] 将把 expose_php 改为 Off"; return 0; fi
    rn "$node" "sed -i 's/^[[:space:]]*expose_php[[:space:]]*=.*/expose_php = Off/' '$ini'" \
      && log_ok "[$node] expose_php 已改为 Off" || return 3
  else
    if $DRY_RUN; then log_info "[$node] [dry-run] 将新建 $ini ([PHP]/expose_php=Off)"; return 0; fi
    backup_file "$node" "$ini" || true   # 通常不存在, 返回1属预期
    rn "$node" "printf '[PHP]\nexpose_php = Off\n' >> '$ini'" \
      && log_ok "[$node] 已新建 $ini 并写入 expose_php=Off" || return 3
    manifest_add "$node" "NEW" "$ini" "-" "本次新建, 回滚时删除"
  fi

  rn "$node" "cd /usr/local/easyops/php/lib && chown -R easyops: ./*"
  if rn "$node" "cd /usr/local/easyops/php && easyops restart"; then
    log_ok "[$node] php 组件已重启"
  else
    log_err "[$node] php 组件重启失败"; return 3
  fi
  return 0
}

# 2.2a ExecShell.php md5 校验, 不符则用 --execshell-src 替换(需重启 php+tools+清 opcache)
step2_execshell() {
  local node="$1" f="/usr/local/easyops/tools/src/common/library/ExecShell.php"
  step_banner "[$node] 步骤2.2: ExecShell.php md5 校验"

  if ! rn "$node" "test -f '$f'"; then
    log_warn "[$node] $f 不存在, 跳过"; return 3
  fi

  local md5; md5=$(rn "$node" "md5sum '$f' 2>/dev/null | awk '{print \$1}'" | tr -d '\r')
  if [ "$md5" = "$MD5_EXECSHELL" ]; then
    log_ok "[$node] ExecShell.php md5 一致($md5), 无需替换"; return 0
  fi
  log_warn "[$node] ExecShell.php md5 不符! 当前=$md5 期望=$MD5_EXECSHELL"

  if [ -z "$EXEC_SHELL_SRC" ]; then
    log_warn "[$node] 未提供 --execshell-src, 只报告不替换(所有节点需统一处理)"; return 1
  fi
  if ! test -f "$EXEC_SHELL_SRC"; then
    log_err "[$node] 本地替换文件不存在: $EXEC_SHELL_SRC"; return 3
  fi
  local src_md5; src_md5=$(md5sum "$EXEC_SHELL_SRC" | awk '{print $1}')
  if [ "$src_md5" != "$MD5_EXECSHELL" ]; then
    log_err "[$node] --execshell-src 文件 md5($src_md5) 与期望不符, 拒绝下发"; return 3
  fi

  backup_file "$node" "$f" || { log_err "[$node] 备份失败, 中止替换"; return 3; }
  if $DRY_RUN; then log_info "[$node] [dry-run] 将替换 $f 并重启 php/tools + 清 opcache"; return 0; fi

  rn "$node" "cp '$f' '${f}.hardening_replaced'"   # 服务器侧留痕, 便于比对
  push "$node" "$EXEC_SHELL_SRC" "$f" || { log_err "[$node] 替换文件下发失败"; return 3; }
  rn "$node" "chown easyops: '$f' && md5sum '$f'"
  step2_restart_php_tools "$node" || return 3
  log_ok "[$node] ExecShell.php 已替换并重启组件"
  return 0
}

# 替换 ExecShell.php 后: 清 opcache + 重启 php + 重启 tools
step2_restart_php_tools() {
  local node="$1"
  log_info "[$node] 清空 opcache 并重启 php/tools ..."
  rn "$node" "mkdir -p /tmp && mv /usr/local/easyops/php_opcache/* /tmp/ 2>/dev/null || true"
  rn "$node" "cd /usr/local/easyops/php && easyops restart" || { log_err "[$node] php 重启失败"; return 1; }
  rn "$node" "cd /usr/local/easyops/tools && easyops restart" || { log_err "[$node] tools 重启失败"; return 1; }
  log_ok "[$node] opcache 已清空, php/tools 已重启"
}

# 2.2c tools/src/www 目录: 应只有 index.php / phpinfo.php, 其他文件隔离到备份
step2_www_check() {
  local node="$1" dir="/usr/local/easyops/tools/src/www"
  step_banner "[$node] 步骤2.2c: tools/src/www 目录检查(应只有 index.php / phpinfo.php)"

  if ! rn "$node" "test -d '$dir'"; then
    log_warn "[$node] $dir 不存在, 跳过"; return 3
  fi

  local extra
  extra=$(rn "$node" "find '$dir' -maxdepth 1 -type f ! -name index.php ! -name phpinfo.php -printf '%f\n' 2>/dev/null \
                   || find '$dir' -maxdepth 1 -type f ! -name index.php ! -name phpinfo.php -exec basename {} \;" | tr -d '\r')
  if [ -z "$extra" ]; then
    log_ok "[$node] 目录干净(仅 index.php / phpinfo.php)";
  else
    log_warn "[$node] 发现多余文件: $(echo "$extra" | tr '\n' ' ')"
    if $DRY_RUN; then log_info "[$node] [dry-run] 将隔离上述文件到 /tmp/hardening_www_quarantine/"; return 1; fi
    rn "$node" "mkdir -p /tmp/hardening_www_quarantine"
    for f in $extra; do
      backup_file "$node" "$dir/$f" || log_warn "[$node] $f 备份失败"
      rn "$node" "mv '$dir/$f' /tmp/hardening_www_quarantine/" \
        && log_ok "[$node] 已隔离 $f -> /tmp/hardening_www_quarantine/" \
        || log_err "[$node] $f 隔离失败"
    done
  fi

  # 两个期望文件的 md5 校验(只报告, 替换需人工用官方包)
  local m
  for f in index.php phpinfo.php; do
    m=$(rn "$node" "md5sum '$dir/$f' 2>/dev/null | awk '{print \$1}'" | tr -d '\r')
    case "$f:$m" in
      index.php:$MD5_INDEX)    log_ok "[$node] index.php md5 一致" ;;
      phpinfo.php:$MD5_PHPINFO) log_ok "[$node] phpinfo.php md5 一致" ;;
      *) log_warn "[$node] $f md5 不符: 当前=${m:-缺失} (index.php应为$MD5_INDEX / phpinfo.php应为$MD5_PHPINFO)" ;;
    esac
  done
  return 0
}

# ---------------- 步骤3: tool_service 割接检测(只读, 不变更) ----------------
step3_tool_service() {
  local node="$1" flag="/usr/local/easyops/tool_service/conf/enable_flow_v2.yaml"
  step_banner "[$node] 步骤3: 检测工具库/流程库是否已割接 tool_service (仅检测)"

  if rn "$node" "test -f '$flag'"; then
    log_ok "[$node] 存在 $flag => 已割接 tool_service (php tool 组件可 stop, 停用前请验证平台功能)"
  else
    log_info "[$node] 不存在 $flag => 未割接, php tool 组件保持运行"
  fi
  log_info "[$node] 建议同时确认配置中心: api-gateway -> feature-switch -> flowRefactor = true"
  return 0
}

# ---------------- 步骤4: nginx 白名单 ----------------
# 向 tool.conf 的每个 server{} 及 cmdb*.conf 注入 allow/deny
# 幂等机制: 标记块(# easyops-hardening-allow), 重跑时先剔除旧标记块再按当前 IP 列表重注入,
#           生成结果与原文件相同则跳过(IP 列表变化时会自动更新)
# 注意: 不能用"文件含 deny all; 则跳过"判断 —— vendor 在 location 级预置的 deny all、
#       或此前人工加过的 allow/deny 都会造成误跳过, 且旧 deny all 在前会屏蔽后注入的集群 IP
step4_nginx_allow() {
  local node="$1" conf_dir="/usr/local/easyops/nginx/conf/conf.d"
  step_banner "[$node] 步骤4: nginx tool.conf / cmdb*.conf 增加集群白名单"

  if ! rn "$node" "test -d '$conf_dir'"; then
    log_warn "[$node] $conf_dir 不存在, 跳过"; return 3
  fi

  # 统一生成 allow 列表(本机回环 + 集群IP + 额外IP), 存本地临时文件供 awk 使用
  local allow_file; allow_file="$(bk_dir "$node" "$RUN_DT")/allow_block.conf"
  {
    echo "allow ::1;"
    echo "allow 127.0.0.1;"
    for ip in "${NODES[@]}" $(echo "$EXTRA_ALLOW_IPS" | tr ',' ' '); do
      [ -n "$ip" ] && echo "allow ${ip};"
    done
    echo "deny all;"
  } >"$allow_file"

  local confs target
  # shellcheck disable=SC2016  # 远端命令中 $ 不做本地展开是有意为之
  confs=$(rn "$node" "ls '$conf_dir'/tool.conf '$conf_dir'/cmdb*.conf 2>/dev/null" | tr -d '\r')
  [ -z "$confs" ] && { log_warn "[$node] 未找到 tool.conf / cmdb*.conf"; return 3; }

  # 顺带分析 cmdb 访问日志中的非集群来源(文档 4-b 注意事项; 日志在 nginx/logs 下)
  local non_cluster
  # shellcheck disable=SC2016
  non_cluster=$(rn "$node" "awk '{print \$1}' /usr/local/easyops/nginx/logs/cmdb_*.access.log 2>/dev/null | sort | uniq -c | sort -nr" | tr -d '\r')
  if [ -n "$non_cluster" ]; then
    log_info "[$node] cmdb 访问日志来源 IP 统计(请确认是否均为集群/合法调用方, 如有外部 IP 请加入 --extra-allow-ips):"
    printf '%s\n' "$non_cluster" | sed 's/^/    /' | tee -a "$RUN_LOG"
  fi

  local changed=false work
  work=$(mktemp -d)
  for target in $confs; do
    # 拉取到本地 -> awk 剔除旧标记块 + 在每个 server{ 行后插入新标记块 -> 与原文件比对
    fetch "$node" "$target" "$work/orig" || { log_err "[$node] 拉取 $(basename "$target") 失败"; return 3; }
    awk -v allow_file="$allow_file" '
      # 旧标记块整段剔除(重跑/IP 变更时按当前列表重建)
      /^[[:space:]]*#[[:space:]]*>>> easyops-hardening-allow/ { inmarker = 1; next }
      inmarker && /^[[:space:]]*#[[:space:]]*<<< easyops-hardening-allow/ { inmarker = 0; next }
      inmarker { next }
      # 注入点紧跟 server{ => allow/deny 位于该 server 最前, 先于任何既有规则生效
      /^[[:space:]]*server[[:space:]]*\{/ {
        print
        print "    # >>> easyops-hardening-allow >>>"
        while ((getline line < allow_file) > 0) print "    " line
        close(allow_file)
        print "    # <<< easyops-hardening-allow <<<"
        injected = 1
        next
      }
      { print }
      END { exit injected ? 0 : 4 }
    ' "$work/orig" >"$work/new"
    local rc=$?
    if [ $rc -ne 0 ]; then
      log_err "[$node] $(basename "$target") 中未找到 server{ 块, 不修改"
      continue
    fi
    if cmp -s "$work/orig" "$work/new"; then
      log_ok "[$node] $(basename "$target") 已包含当前完整白名单, 跳过"
      continue
    fi
    backup_file "$node" "$target" || { log_warn "[$node] $(basename "$target") 备份失败"; }
    if $DRY_RUN; then log_info "[$node] [dry-run] 将向 $(basename "$target") 注入/更新白名单标记块"; continue; fi

    if push "$node" "$work/new" "$target" && rn "$node" "chown easyops: '$target' && grep -q 'easyops-hardening-allow' '$target'"; then
      log_ok "[$node] $(basename "$target") 已注入白名单"
      changed=true
    else
      log_err "[$node] $(basename "$target") 注入失败, 尝试恢复备份"
      push "$node" "$(bk_dir "$node" "$RUN_DT")/FILE_$(printf '/%s' "${target#/}" | sed 's|^/||; s|/|_|g')" "$target"
      return 3
    fi
  done
  rm -rf "$work"
  $changed && NGINX_RELOAD_NEEDED=true
  return 0
}

# ---------------- 步骤5: 停用无关 conf ----------------
# 默认保留: file_preview.conf / itsc_mobile.conf(itsm/移动端), php.deploy*.conf(CD/文件分发)
# 通过 --disable-itsm / --disable-cd 才会一并停用
step5_nginx_disable() {
  local node="$1" conf_dir="/usr/local/easyops/nginx/conf/conf.d"
  step_banner "[$node] 步骤5: 停用无关 nginx conf"

  local disable_list=(
    autodiscovery.conf wiki.conf ui.conf event.conf graph.conf home.conf jobservice.conf
    landing.conf operation_portals.conf system_settings.conf notify.conf easyconf.conf
    php.cmdb.conf easy_core_console.conf cmdb_mobile.conf console-community.conf
    php.openapi.conf easyflow.conf command.conf
  )
  $DISABLE_ITSM && disable_list+=(itsc_mobile.conf file_preview.conf)
  $DISABLE_CD    && disable_list+=(php.deploy.conf php.deploy_repository.conf)

  local c changed=false
  for c in "${disable_list[@]}"; do
    if ! rn "$node" "test -e '$conf_dir/$c'"; then
      log_info "[$node] $c 不存在或已停用, 跳过"; continue
    fi
    backup_file "$node" "$conf_dir/$c" || log_warn "[$node] $c 备份失败"
    if $DRY_RUN; then log_info "[$node] [dry-run] 将 mv $c -> ${c}.bak_hardening"; continue; fi
    if rn "$node" "mv '$conf_dir/$c' '$conf_dir/${c}.bak_hardening'"; then
      log_ok "[$node] 已停用 $c (重命名 ${c}.bak_hardening)"
      changed=true
    else
      log_err "[$node] 停用 $c 失败"
    fi
  done

  if $changed; then
    rn "$node" "cd '$conf_dir' && chown -R easyops: ./*"
    NGINX_RELOAD_NEEDED=true
  fi
  return 0
}

# nginx -t 校验, 通过才 reload(任何节点失败都不 reload 该节点)
nginx_test_reload() {
  local node="$1"
  step_banner "[$node] nginx 配置校验与重载"
  if ! rn "$node" "test -x /usr/local/easyops/nginx/sbin/nginx"; then
    log_warn "[$node] nginx 不存在, 跳过"; return 3
  fi
  local t
  t=$(rn "$node" "cd /usr/local/easyops/nginx && ./sbin/nginx -t 2>&1" | tr -d '\r')
  if echo "$t" | grep -q 'successful'; then
    log_ok "[$node] nginx -t 通过"
    if $DRY_RUN; then log_info "[$node] [dry-run] 跳过 reload"; return 0; fi
    if rn "$node" "cd /usr/local/easyops/nginx && ./sbin/nginx -s reload"; then
      log_ok "[$node] nginx 已 reload"
    else
      log_err "[$node] nginx reload 失败"; return 3
    fi
  else
    log_err "[$node] nginx -t 未通过, 不 reload! 输出如下:"
    printf '%s\n' "$t" | sed 's/^/    /' | tee -a "$RUN_LOG"
    return 3
  fi
  return 0
}

# ---------------- 回滚 ----------------
# 语义:
#   默认(无 --backup-dt) = 完全回滚: 撤销所有历史加固, 每个文件恢复到【最早一次】备份
#     (即首次加固前的原始状态)。不能只看最近一次清单 —— 幂等跳过的文件在最近清单中没有条目,
#      且最近一次的备份可能已含上次注入的标记块, 直接恢复会导致 easyops-hardening-allow 残留)
#   --backup-dt T = 仅撤销 T 那一次的变更(更早批次的效果保留)
# 恢复动作:
#   FILE/MV -> 拷回原路径 (MV 另清理 .bak_hardening 残留)
#   NEW     -> 删除新建文件
#   IPT     -> iptables-restore 恢复快照, 并删除持久化文件(防止重启后加固规则复活)
#   nginx conf 恢复后: chown -> nginx -t -> reload
#   php/tools 文件恢复后: 重启对应组件(opcache 缓存的加固版才会失效)
rollback_plan_build() {  # rollback_plan_build <node> <dir...> -> 关联数组 PLAN[rpath]="tag bkfile dir"
  local node="$1"; shift
  local dt tag rpath bkfile _d
  for dt in "$@"; do
    [ -f "$BK_ROOT/$node/$dt/manifest.tsv" ] || continue
    while IFS=$'\t' read -r tag rpath bkfile _d; do
      [ -z "${tag:-}" ] && continue
      [ "$tag" = "类型" ] && continue
      [ -n "${PLAN[$rpath]:-}" ] && continue   # 最早者优先(目录按时间升序传入)
      PLAN[$rpath]="$tag"$'\t'"$bkfile"$'\t'"$dt"
    done <"$BK_ROOT/$node/$dt/manifest.tsv"
  done
}

rollback_node() {
  local node="$1"
  step_banner "[$node] 回滚开始"

  local -a dirs=()
  if [ -n "$BACKUP_DT" ]; then
    [ -d "$(bk_dir "$node" "$BACKUP_DT")" ] || { log_err "[$node] 指定备份不存在: $BACKUP_DT"; return 3; }
    dirs=("$BACKUP_DT")
    log_info "[$node] 单次回滚模式: backup/$node/$BACKUP_DT (仅撤销该次变更)"
  else
    local d
    while IFS= read -r d; do dirs+=("$d"); done \
      < <(ls -1 "$BK_ROOT/$node" 2>/dev/null | grep -E '^[0-9]{8}-[0-9]{6}$' | sort)
    [ "${#dirs[@]}" -eq 0 ] && { log_err "[$node] 无任何备份目录"; return 3; }
    log_info "[$node] 完全回滚模式: 覆盖 ${#dirs[@]} 次备份(${dirs[0]} ~ ${dirs[-1]}), 每个文件恢复最早(最原始)版本"
  fi

  local -A PLAN=()
  rollback_plan_build "$node" "${dirs[@]}"
  [ "${#PLAN[@]}" -eq 0 ] && { log_err "[$node] 备份清单为空, 无可回滚项"; return 3; }

  local nginx_touched=false php_touched=false tools_touched=false
  local rpath tag bkfile dt bdir
  for rpath in "${!PLAN[@]}"; do
    IFS=$'\t' read -r tag bkfile dt <<<"${PLAN[$rpath]}"
    bdir="$(bk_dir "$node" "$dt")"
    case "$tag" in
      FILE|MV)
        if push "$node" "$bdir/$bkfile" "$rpath"; then
          log_ok "[$node] 已恢复 $rpath (备份: $dt)"
          # MV 类: 清掉加固时 mv 产生的 .bak_hardening 残留, 保证可再次加固
          [ "$tag" = "MV" ] && rn "$node" "rm -f '${rpath}.bak_hardening'"
          case "$rpath" in
            */nginx/conf/conf.d/*) nginx_touched=true ;;
            /usr/local/easyops/php/*)  php_touched=true ;;
            /usr/local/easyops/tools/*)
              tools_touched=true
              # www 隔离文件: 清掉 /tmp 副本, 避免残留
              case "$rpath" in */tools/src/www/*) rn "$node" "rm -f '/tmp/hardening_www_quarantine/$(basename "$rpath")'" ;; esac
              ;;
          esac
        else
          log_err "[$node] 恢复 $rpath 失败"
        fi ;;
      NEW)
        rn "$node" "rm -f '$rpath'" && log_ok "[$node] 已删除新建文件 $rpath"
        case "$rpath" in /usr/local/easyops/php/*) php_touched=true ;; esac ;;
      IPT)
        if rn "$node" "iptables-restore < /dev/stdin" <"$bdir/$bkfile"; then
          log_ok "[$node] iptables 已恢复 (备份: $dt)"
          # 删除加固时落盘的持久化文件, 否则节点重启会重新加载加固规则
          rn "$node" "rm -f /etc/iptables/rules.ipv4.hardening" \
            && log_ok "[$node] 已删除 /etc/iptables/rules.ipv4.hardening (防重启后加固规则复活)"
        else
          log_err "[$node] iptables 恢复失败(备份: $bdir/$bkfile)"
        fi ;;
      *) log_warn "[$node] 未知备份类型: $tag" ;;
    esac
  done

  # 恢复的 conf 文件统一修正属主
  $nginx_touched && rn "$node" "chown -R easyops: /usr/local/easyops/nginx/conf/conf.d/*" >/dev/null 2>&1

  if $nginx_touched; then
    if rn "$node" "cd /usr/local/easyops/nginx && ./sbin/nginx -t 2>&1" | grep -q successful; then
      rn "$node" "cd /usr/local/easyops/nginx && ./sbin/nginx -s reload" \
        && log_ok "[$node] nginx 已回滚并 reload" \
        || log_err "[$node] nginx reload 失败"
    else
      log_err "[$node] nginx -t 未通过, 未 reload, 请手工检查"
    fi
  fi

  # php/tools: 恢复的文件需重启组件才真正生效(opcache 可能仍缓存加固版)
  if $php_touched; then
    rn "$node" "cd /usr/local/easyops/php && easyops restart" \
      && log_ok "[$node] php 已回滚并重启" \
      || log_err "[$node] php 重启失败, 配置已恢复但未生效"
  fi
  if $tools_touched; then
    rn "$node" "cd /usr/local/easyops/tools && easyops restart" \
      && log_ok "[$node] tools 已回滚并重启" \
      || log_err "[$node] tools 重启失败"
    $php_touched || rn "$node" "cd /usr/local/easyops/php && easyops restart" >/dev/null 2>&1
  fi

  log_ok "[$node] 回滚完成"
  return 0
}

# ---------------- 主流程 ----------------
NGINX_RELOAD_NEEDED=false   # 步骤4/5 共享: 有变更的节点才 reload (在 per-node 循环里赋值)

main() {
  step_banner "EasyOps 平台安全加固 (模式: $MODE$( $DRY_RUN && echo ' + dry-run' ))"
  log_info "节点列表: ${NODES[*]}"
  log_info "备份根目录: $BK_ROOT"
  log_info "运行日志: $RUN_LOG"

  # 免密预检: 全部节点可达才继续(批量变更最忌半途节点不通)
  step_banner "阶段0: SSH 免密连通性预检 (user=$SSH_USER port=$SSH_PORT)"
  local unreachable=0 n
  for n in "${NODES[@]}"; do
    if rn "$n" "echo ok" >/dev/null 2>&1; then
      log_ok "[$n] SSH 可达"
    else
      log_err "[$n] SSH 不可达(免密未配置或节点宕机)"; unreachable=$((unreachable+1))
    fi
  done
  [ "$unreachable" -ne 0 ] && err_exit "有 $unreachable 个节点不可达, 中止(避免集群加固不一致)"
  log_ok "全部 ${#NODES[@]} 个节点 SSH 可达"

  mkdir -p "$BK_ROOT"

  if [ "$MODE" = "rollback" ]; then
    for n in "${NODES[@]}"; do rollback_node "$n"; done
    log_info "回滚流程结束, 详情见 $RUN_LOG"
    return 0
  fi

  # ---------- 加固主流程: 逐节点执行 ----------
  # 返回码约定: 0=成功/幂等跳过  1=检查发现异常(需人工介入, 不阻断)  3=执行失败(已尝试恢复)
  local -a fail_nodes=() warn_nodes=()
  for n in "${NODES[@]}"; do
    NGINX_RELOAD_NEEDED=false
    mkdir -p "$(bk_dir "$n" "$RUN_DT")"
    printf '类型\t远程路径\t备份文件\t说明\n' > "$(bk_dir "$n" "$RUN_DT")/manifest.tsv"

    $SKIP_IPT   || { step1_iptables   "$n" || fail_nodes+=("$n"); }
    $SKIP_PHP   || { step2_php_ini    "$n" || fail_nodes+=("$n"); }
    $SKIP_PHP   || { step2_execshell  "$n" || warn_nodes+=("$n"); }   # 无替换源时只报告
    $SKIP_PHP   || { step2_www_check  "$n" || warn_nodes+=("$n"); }
                 { step3_tool_service "$n" || true; }                  # 纯检测
    $SKIP_NGINX || { step4_nginx_allow "$n" || fail_nodes+=("$n"); }
    $SKIP_NGINX || { step5_nginx_disable "$n" || fail_nodes+=("$n"); }
    $SKIP_NGINX || { if $NGINX_RELOAD_NEEDED; then nginx_test_reload "$n" || fail_nodes+=("$n"); fi; }
  done

  # ---------- 汇总 ----------
  step_banner "执行汇总"
  log_info "成功节点: ${NODES[*]}"
  local -a _warn_u=() _fail_u=() ; local _s=" " _n2
  for _n2 in "${warn_nodes[@]:-}"; do case " $_s " in *" $_n2 "*) ;; *) [ -n "$_n2" ] && _warn_u+=("$_n2") && _s=" $_s $_n2 ";; esac; done
  _s=" "
  for _n2 in "${fail_nodes[@]:-}"; do case " $_s " in *" $_n2 "*) ;; *) [ -n "$_n2" ] && _fail_u+=("$_n2") && _s=" $_s $_n2 ";; esac; done
  [ "${#_warn_u[@]}" -gt 0 ] && log_warn "有告警(需人工确认)的节点: $(printf '%s ' "${_warn_u[@]}")"
  if [ "${#_fail_u[@]}" -gt 0 ]; then
    log_err "以下节点有失败/跳过的步骤(可修复后重跑, 脚本幂等): $(printf '%s ' "${_fail_u[@]}")"
    log_info "如需恢复变更前状态: bash $0 --rollback <失败节点IP>"
    exit 1
  fi
  log_ok "全部节点加固完成"
  log_info "后续验证(文档步骤7): 在非集群机器上 curl -v -H 'host: tool.easyops-only.com' http://<节点IP>/ 期望 403; telnet <节点IP> 8079 期望不通"
  return 0
}

main "$@"

