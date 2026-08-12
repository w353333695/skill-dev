#!/usr/bin/env bash
# xray-manage.sh — Xray (VLESS + Reality) 一键部署与多用户管理
#
# 子命令:
#   install  [--port N] [--dest HOST:443]   安装 Xray、生成 Reality 配置、起 systemd 服务、放行防火墙
#   add      <name>                          添加用户，输出 vless:// + 二维码 + 客户端 JSON
#   remove   <name>                          删除用户
#   list                                    列出所有用户
#   show     <name>                          重新打印某用户的接入凭据
#   status                                  服务/端口/公网IP/用户数 一览
#   uninstall                               停服务、删二进制与配置（保留 users.json 备份）
#
# 以 root 运行。仅支持 VLESS-Reality（无域名无证书）。
set -euo pipefail

# ============ 常量 / 路径 ============
XRAY_BIN="/usr/local/bin/xray"
XRAY_SHARE="/usr/local/share/xray"
CONF_DIR="/etc/xray-manage"
CONFIG_JSON="$CONF_DIR/config.json"
TEMPLATE_JSON="$CONF_DIR/config.template.json"
USERS_JSON="$CONF_DIR/users.json"
SERVER_JSON="$CONF_DIR/server.json"
META_CONF="$CONF_DIR/meta.conf"
UNIT_FILE="/etc/systemd/system/xray.service"

DEFAULT_PORT=443
DEFAULT_DEST="www.yahoo.com:443"
XRAY_REPO="XTLS/Xray-core"   # GitHub release 源

# 颜色（非交互时关闭）
if [[ -t 1 ]]; then
    C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_C=$'\033[36m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
    C_G=''; C_Y=''; C_R=''; C_C=''; C_B=''; C_0=''
fi

# ============ 工具函数 ============
_ok()   { printf "%s[OK]%s   %s\n"  "$C_G" "$C_0" "$*"; }
_warn() { printf "%s[WARN]%s %s\n" "$C_Y" "$C_0" "$*" >&2; }
_err()  { printf "%s[ERR]%s  %s\n"  "$C_R" "$C_0" "$*" >&2; }
_step() { printf "\n%s==>%s %s\n"  "$C_C" "$C_0" "$*"; }

die() { _err "$*"; exit 1; }

need_root() {
    [[ $EUID -eq 0 ]] || die "请用 root 运行（或加 sudo）."
}

# 探测架构 -> 返回 Xray release 资产关键字
arch_tag() {
    local m
    m="$(uname -m)"
    case "$m" in
        x86_64)         echo "Xray-linux-64" ;;
        aarch64|arm64)  echo "Xray-linux-arm64-v8a" ;;
        armv7l|armhf)   echo "Xray-linux-arm32-v7a" ;;
        *) die "不支持的架构: $m" ;;
    esac
}

# 确保命令存在，否则按发行版提示安装
ensure_cmd() {
    local cmd="$1" pkg="$2"
    if command -v "$cmd" >/dev/null 2>&1; then return 0; fi
    _warn "缺少依赖: $cmd（包名 $pkg），尝试自动安装..."
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y "$pkg"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y "$pkg"
    else
        die "无法自动安装 $pkg，请手动安装后重试."
    fi
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd 安装失败."
}

# 公网 IP 探测
detect_public_ip() {
    local ip=""
    for url in "https://ifconfig.me" "https://api.ip.sb/ip" "https://ipv4.icanhazip.com"; do
        ip="$(curl -s4 --max-time 8 "$url" 2>/dev/null | tr -d '[:space:]')" || true
        [[ -n "$ip" ]] && { echo "$ip"; return 0; }
    done
    echo ""
}

# 防火墙放行端口
open_firewall() {
    local port="$1"
    if command -v ufw >/dev/null 2>&1; then
        ufw allow "${port}/tcp" >/dev/null 2>&1 && _ok "ufw 已放行 ${port}/tcp"
    elif command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 \
            && firewall-cmd --reload >/dev/null 2>&1 \
            && _ok "firewalld 已放行 ${port}/tcp"
    elif command -v iptables >/dev/null 2>&1; then
        iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
            || iptables -I INPUT -p tcp --dport "$port" -j ACCEPT >/dev/null 2>&1 \
            && _ok "iptables 已放行 ${port}/tcp（注意：重启可能失效，建议用 ufw/firewalld）"
    else
        _warn "未检测到防火墙工具，请手动放行端口 ${port}/tcp."
    fi
}

# 用 users.json 渲染 config.json（模板的 __CLIENTS__ 占位符替换为 clients 数组）
render_config() {
    [[ -f "$TEMPLATE_JSON" && -f "$USERS_JSON" ]] || die "模板或用户清单缺失."
    local tmp
    tmp="$(mktemp)"
    # clients 数组（从 users.json 构建，字段顺序与 Xray 一致）
    local clients
    clients="$(jq -c 'to_entries | map({
        name:    .key,
        uuid:    .value.uuid,
        flow:    (.value.flow // "xtls-rprx-vision")
    })' "$USERS_JSON")"
    # 用 jq 把 clients 注入模板的 inbounds[0].clients
    jq --argjson clients "$clients" \
       '(.inbounds[0].settings.clients) = $clients' \
       "$TEMPLATE_JSON" > "$tmp" \
        || die "渲染 config.json 失败."
    mv "$tmp" "$CONFIG_JSON"
}

# 重载服务（reload 失败回退 restart）
reload_service() {
    if systemctl reload xray 2>/dev/null; then
        _ok "已 reload xray."
    else
        _warn "reload 失败，尝试 restart..."
        systemctl restart xray || die "xray restart 失败，请用 'journalctl -u xray -e' 排查."
    fi
}

# ============ 读取服务端元数据（供 add/show 用）============
load_server_meta() {
    [[ -f "$SERVER_JSON" ]] || die "未安装或 server.json 丢失，请先 install."
    # shellcheck disable=SC1090
    SRV_PORT="$(jq -r '.port' "$SERVER_JSON")"
    SRV_SNI="$(jq -r '.sni' "$SERVER_JSON")"
    SRV_PBK="$(jq -r '.public_key' "$SERVER_JSON")"
    SRV_SID="$(jq -r '.short_id' "$SERVER_JSON")"
    SRV_DEST="$(jq -r '.dest' "$SERVER_JSON")"
}

load_meta_conf() {
    SRV_PUBLIC_IP=""
    [[ -f "$META_CONF" ]] && SRV_PUBLIC_IP="$(awk -F= '/^PUBLIC_IP=/ {print $2}' "$META_CONF")"
}

# ============ 凭据输出 ============
build_vless_link() {
    local name="$1" uuid="$2" flow="${3:-xtls-rprx-vision}"
    # URL-encode name 作为 remark
    local remark
    remark="$(jq -rn --arg s "$name" '$s|@uri')"
    printf "vless://%s@%s:%s?encryption=none&flow=%s&security=reality&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp#%s" \
        "$uuid" "$SRV_PUBLIC_IP" "$SRV_PORT" "$flow" "$SRV_SNI" "$SRV_PBK" "$SRV_SID" "$remark"
}

print_credential() {
    local name="$1" uuid="$2" flow="${3:-xtls-rprx-vision}"
    local link
    link="$(build_vless_link "$name" "$uuid" "$flow")"

    echo
    _ok "用户 [$name] 接入凭据"
    echo "  ── vless:// 分享链接 ──"
    printf "  %s%s%s\n" "$C_B" "$link" "$C_0"

    echo "  ── 二维码 ──"
    if command -v qrencode >/dev/null 2>&1; then
        qrencode -t ANSIUTF8 "$link" 2>/dev/null | sed 's/^/  /' || _warn "二维码渲染失败."
    else
        _warn "未安装 qrencode，跳过二维码。安装: apt-get install -y qrencode"
    fi

    echo "  ── 客户端 outbound JSON ──"
    jq -n --arg addr "$SRV_PUBLIC_IP" --argjson port "$SRV_PORT" \
          --arg uuid "$uuid" --arg sni "$SRV_SNI" --arg pbk "$SRV_PBK" \
          --arg sid "$SRV_SID" --arg flow "$flow" '{
        protocol: "vless",
        settings: { vnext: [{ address: $addr, port: $port, users: [{ id: $uuid, flow: $flow, encryption: "none" }] }] },
        streamSettings: {
            network: "tcp", security: "reality",
            realitySettings: { serverName: $sni, fingerprint: "chrome", publicKey: $pbk, shortId: $sid }
        }
    }' | sed 's/^/  /'
    echo
}

# ============ 子命令: install ============
cmd_install() {
    need_root
    local port="$DEFAULT_PORT" dest="$DEFAULT_DEST"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port) port="$2"; shift 2 ;;
            --dest) dest="$2"; shift 2 ;;
            *) die "install 未知参数: $1" ;;
        esac
    done

    # 校验 dest 形如 host:443
    [[ "$dest" == *:443 ]] || die "--dest 必须形如 host:443（Reality 借用站必须用 443 TLS）."
    local sni="${dest%:*}"

    _step "环境检查"
    ensure_cmd curl curl
    ensure_cmd jq jq
    ensure_cmd openssl openssl
    ensure_cmd tar tar
    [[ $port =~ ^[0-9]+$ ]] || die "--port 必须是数字."

    _step "下载并安装 Xray-core"
    local asset arch download_url latest version
    arch="$(arch_tag)"
    latest="$(curl -fsSL "https://api.github.com/repos/${XRAY_REPO}/releases/latest" \
                | jq -r '.tag_name // empty')"
    [[ -n "$latest" ]] || die "无法获取 Xray 最新版本（网络/GitHub API 限流？）."
    version="${latest#v}"
    asset="${arch}.zip"
    download_url="https://github.com/${XRAY_REPO}/releases/download/${latest}/${asset}"
    _ok "最新版本: $latest（架构 $arch）"

    local workdir
    workdir="$(mktemp -d)"
    trap 'rm -rf "$workdir"' RETURN
    _step "下载 $asset"
    if ! curl -fL --retry 3 -o "$workdir/xray.zip" "$download_url"; then
        die "下载失败: $download_url"
    fi
    ( cd "$workdir" && unzip -o -q xray.zip xray geoip.dat geosite.dat 2>/dev/null \
        || unzip -o -q xray.zip 2>/dev/null || true )
    [[ -f "$workdir/xray" ]] || die "解压后未找到 xray 二进制."
    chmod +x "$workdir/xray"

    install -d "$XRAY_SHARE"
    install -m 0755 "$workdir/xray" "$XRAY_BIN"
    [[ -f "$workdir/geoip.dat" ]]   && install -m 0644 "$workdir/geoip.dat"   "$XRAY_SHARE/geoip.dat"
    [[ -f "$workdir/geosite.dat" ]] && install -m 0644 "$workdir/geosite.dat" "$XRAY_SHARE/geosite.dat"
    _ok "二进制: $XRAY_BIN ; geo: $XRAY_SHARE"

    _step "生成 Reality 密钥对"
    local keypair priv pub sid
    keypair="$("$XRAY_BIN" x25519)"
    # 不同版本输出标签/空格各异，统一按「含 private/public 的行取最后一列」解析，
    # 覆盖旧版 "Private key: X / Public key: Y" 与新版 "PrivateKey: X / Password (PublicKey): Y"。
    priv="$(printf '%s\n' "$keypair" | awk 'tolower($0)~/private/{print $NF}')"
    pub="$(printf '%s\n'  "$keypair" | awk 'tolower($0)~/public/{print $NF}')"
    sid="$(openssl rand -hex 8)"
    if [[ -z "$priv" || -z "$pub" ]]; then
        _err "x25519 输出与预期不符，原始内容如下（供诊断）："
        printf '%s\n' "$keypair" | sed 's/^/    /' >&2
        die "x25519 密钥解析失败."
    fi
    _ok "私钥(服务端) / 公钥(客户端) 已生成；shortId=$sid"

    _step "写入配置"
    install -d -m 0700 "$CONF_DIR"

    # server.json：服务端机密元数据
    jq -n --argjson port "$port" --arg dest "$dest" --arg sni "$sni" \
          --arg priv "$priv" --arg pub "$pub" --arg sid "$sid" '{
        port: $port, dest: $dest, sni: $sni,
        private_key: $priv, public_key: $pub, short_id: $sid
    }' > "$SERVER_JSON"
    chmod 600 "$SERVER_JSON"

    # users.json：真相源，初始空
    if [[ ! -f "$USERS_JSON" ]]; then
        echo '{}' > "$USERS_JSON"
    fi
    chmod 600 "$USERS_JSON"

    # 模板（含 clients 占位，渲染时被覆盖）
    cat > "$TEMPLATE_JSON" <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "vless-reality",
      "listen": "0.0.0.0",
      "port": ${port},
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "${dest}",
          "xver": 0,
          "serverNames": ["${sni}"],
          "privateKey": "${priv}",
          "shortIds": ["${sid}"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
    }
  ],
  "outbounds": [
    { "tag": "direct",  "protocol": "freedom" },
    { "tag": "block",   "protocol": "blackhole" }
  ]
}
EOF
    chmod 600 "$TEMPLATE_JSON"

    render_config
    chmod 600 "$CONFIG_JSON"

    _step "安装 systemd 服务"
    # 清理可能存在的 drop-in（官方 Xray-install 会留下
    # /etc/systemd/system/xray.service.d/10-donot_touch_single_conf.conf，
    # 它用 ExecStart= 覆盖主 unit，把 xray 强制指向 /usr/local/etc/xray/config.json，
    # 导致本脚本写的 config 路径不生效）。install 前必须先移除，否则 ExecStart 被劫持。
    local dropin_dir="/etc/systemd/system/xray.service.d"
    if [[ -d "$dropin_dir" ]]; then
        _warn "检测到 systemd drop-in 目录 $dropin_dir（残留自官方安装脚本），将移除以免劫持 ExecStart."
        rm -rf "$dropin_dir"
    fi
    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Xray Service (VLESS-Reality)
Documentation=https://xtls.github.io
After=network.target nss-lookup.target

[Service]
Type=simple
User=root
ExecStart=${XRAY_BIN} run -config ${CONFIG_JSON}
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now xray >/dev/null 2>&1
    sleep 1
    if systemctl is-active --quiet xray; then
        _ok "xray 服务已启动"
    else
        _err "xray 启动失败，日志："
        journalctl -u xray -n 20 --no-pager || true
        _warn "提示：systemd 实际用的 ExecStart 可用以下命令确认："
        _warn "  systemctl cat xray  （若仍有 drop-in 覆盖，会看到多段 ExecStart）"
        die "请检查配置后 'systemctl start xray'."
    fi

    _step "探测公网 IP"
    local pubip
    pubip="$(detect_public_ip)"
    if [[ -n "$pubip" ]]; then
        printf "PUBLIC_IP=%s\n" "$pubip" > "$META_CONF"
        _ok "公网 IP: $pubip"
    else
        : > "$META_CONF"
        _warn "公网 IP 探测失败，后续凭据地址需手动改 meta.conf 的 PUBLIC_IP=."
    fi

    _step "防火墙放行"
    open_firewall "$port"

    _step "安装完成"
    cat <<EOF

  ${C_B}服务端已就绪${C_0}（Xray $latest / VLESS-Reality）
    端口        : ${port}/tcp
    借用 SNI    : ${sni}
    公网 IP     : ${pubip:-<未探测到，请改 ${META_CONF}>}

  ${C_C}下一步${C_0}：添加首个用户
    ${C_B}$(realpath "$0") add alice${C_0}
EOF
}

# ============ 子命令: add ============
cmd_add() {
    need_root
    [[ $# -ge 1 ]] || die "用法: add <name>"
    local name="$1"
    load_server_meta
    load_meta_conf
    [[ -n "$SRV_PUBLIC_IP" ]] || _warn "公网 IP 为空，凭据里的地址无效，请先修 $META_CONF."

    [[ -f "$USERS_JSON" ]] || die "未安装，请先 install."

    # 名称查重
    if jq -e --arg n "$name" 'has($n)' "$USERS_JSON" >/dev/null 2>&1; then
        die "用户 [$name] 已存在. 用 show $name 查看凭据，或换名."
    fi

    local uuid flow="xtls-rprx-vision"
    uuid="$(cat /proc/sys/kernel/random/uuid)"

    # 备份 config.json 便于回滚
    [[ -f "$CONFIG_JSON" ]] && cp -a "$CONFIG_JSON" "${CONFIG_JSON}.bak"

    # 写入 users.json
    local tmp; tmp="$(mktemp)"
    jq --arg n "$name" --arg u "$uuid" --arg f "$flow" \
       '.[$n] = {uuid: $u, flow: $f}' "$USERS_JSON" > "$tmp"
    mv "$tmp" "$USERS_JSON"

    render_config
    reload_service

    _ok "已添加用户 [$name]"
    print_credential "$name" "$uuid" "$flow"
}

# ============ 子命令: remove ============
cmd_remove() {
    need_root
    [[ $# -ge 1 ]] || die "用法: remove <name>"
    local name="$1"
    [[ -f "$USERS_JSON" ]] || die "未安装，请先 install."

    if ! jq -e --arg n "$name" 'has($n)' "$USERS_JSON" >/dev/null 2>&1; then
        die "用户 [$name] 不存在."
    fi

    [[ -f "$CONFIG_JSON" ]] && cp -a "$CONFIG_JSON" "${CONFIG_JSON}.bak"

    local tmp; tmp="$(mktemp)"
    jq --arg n "$name" 'del(.[$n])' "$USERS_JSON" > "$tmp"
    mv "$tmp" "$USERS_JSON"

    render_config
    reload_service

    _ok "已删除用户 [$name]"
}

# ============ 子命令: list ============
cmd_list() {
    [[ -f "$USERS_JSON" ]] || die "未安装，请先 install."
    local count
    count="$(jq 'keys | length' "$USERS_JSON")"
    if [[ "$count" -eq 0 ]]; then
        _warn "暂无用户。用 'add <name>' 添加."
        return 0
    fi
    printf "%-20s %-40s %-20s\n" "NAME" "UUID" "FLOW"
    printf -- "--------------------------------------------------------------------------------\n"
    jq -r 'to_entries[] | "\(.key)\t\(.value.uuid)\t\(.value.flow // "xtls-rprx-vision")"' "$USERS_JSON" \
        | awk -F'\t' '{printf "%-20s %-40s %-20s\n", $1, $2, $3}'
    _ok "共 $count 个用户."
}

# ============ 子命令: show ============
cmd_show() {
    [[ $# -ge 1 ]] || die "用法: show <name>"
    local name="$1"
    [[ -f "$USERS_JSON" ]] || die "未安装，请先 install."
    load_server_meta
    load_meta_conf

    if ! jq -e --arg n "$name" 'has($n)' "$USERS_JSON" >/dev/null 2>&1; then
        die "用户 [$name] 不存在."
    fi
    local uuid flow
    uuid="$(jq -r --arg n "$name" '.[$n].uuid' "$USERS_JSON")"
    flow="$(jq -r --arg n "$name" '.[$n].flow // "xtls-rprx-vision"' "$USERS_JSON")"
    print_credential "$name" "$uuid" "$flow"
}

# ============ 子命令: status ============
cmd_status() {
    _step "Xray 服务"
    if systemctl is-active --quiet xray 2>/dev/null; then
        _ok "xray: active (running)"
    else
        _err "xray: 未运行或未安装"
    fi

    if [[ -f "$CONFIG_JSON" ]]; then
        local port
        port="$(jq -r '.inbounds[0].port' "$CONFIG_JSON" 2>/dev/null || echo '?')"
        _step "监听端口 ($port)"
        ss -tlnp 2>/dev/null | (grep -E ":${port}\b" || _warn "未抓到 ${port} 监听（可能需要 sudo）") | sed 's/^/  /'
    fi

    if [[ -f "$META_CONF" ]]; then
        _step "公网 IP"
        awk -F= '/^PUBLIC_IP=/ {print "  "$0}' "$META_CONF"
    fi

    if [[ -f "$USERS_JSON" ]]; then
        _step "用户"
        local count; count="$(jq 'keys | length' "$USERS_JSON")"
        echo "  共 $count 个用户（list 查看）"
    fi
}

# ============ 子命令: uninstall ============
cmd_uninstall() {
    need_root
    _warn "将停止并删除 xray 服务、二进制、配置（users.json 会备份）."
    read -r -p "确认卸载? 输入 yes 继续: " ans
    [[ "$ans" == "yes" ]] || { echo "已取消."; exit 0; }

    _step "停止并移除服务"
    systemctl stop xray 2>/dev/null || true
    systemctl disable xray 2>/dev/null || true
    rm -f "$UNIT_FILE"
    # 同步移除 drop-in 目录（官方安装脚本残留），否则下次 install 仍会被劫持
    rm -rf "/etc/systemd/system/xray.service.d"
    systemctl daemon-reload 2>/dev/null || true

    _step "备份 users.json"
    if [[ -f "$USERS_JSON" ]]; then
        local bak="/etc/xray-manage.bak.$(date +%Y%m%d-%H%M%S)"
        cp -a "$CONF_DIR" "$bak"
        _ok "配置已备份到 $bak"
    fi

    _step "删除二进制与配置"
    rm -f "$XRAY_BIN"
    rm -rf "$XRAY_SHARE"
    rm -rf "$CONF_DIR"
    _ok "卸载完成."
}

# ============ 帮助 ============
usage() {
    cat <<'EOF'
xray-manage.sh — Xray (VLESS-Reality) 部署管理

用法:
  xray-manage.sh install  [--port 443] [--dest www.yahoo.com:443]
                          安装 Xray、生成 Reality 配置、起 systemd、放行防火墙
  xray-manage.sh add      <name>          添加用户（输出 vless:// + QR + JSON）
  xray-manage.sh remove   <name>          删除用户
  xray-manage.sh list                     列出用户
  xray-manage.sh show     <name>          重显某用户凭据
  xray-manage.sh status                   服务/端口/IP/用户数 一览
  xray-manage.sh uninstall                卸载（保留 users.json 备份）

install 参数:
  --port N         监听端口，默认 443
  --dest HOST:443  Reality 借用站，默认 www.yahoo.com:443
EOF
}

# ============ 入口 ============
main() {
    [[ $# -ge 1 ]] || { usage; exit 1; }
    local sub="$1"; shift
    case "$sub" in
        install)   cmd_install   "$@" ;;
        add)       cmd_add       "$@" ;;
        remove)    cmd_remove    "$@" ;;
        list)      cmd_list      "$@" ;;
        show)      cmd_show      "$@" ;;
        status)    cmd_status    "$@" ;;
        uninstall) cmd_uninstall "$@" ;;
        -h|--help|help) usage ;;
        *) die "未知子命令: $sub（用 --help 查看）" ;;
    esac
}

main "$@"
