#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
用法:
  sudo ./register-service.sh --name NAME --command 'COMMAND [ARGS...]' [选项]

选项:
  --name NAME       服务名（仅允许字母、数字、点、下划线、短横线）
  --command CMD     要执行的命令字符串（由 bash -lc 执行，支持管道和重定向）
  --user USER       服务运行用户，默认 root
  --group GROUP     服务运行用户组，默认不指定
  --workdir DIR     工作目录，默认 /
  --env KEY=VALUE   设置环境变量，可重复指定
  --interactive     使用 tmux/screen 后台会话运行交互式命令
  --no-start        只注册并启用，不立即启动
  --remove          删除指定服务并取消开机自启（不需要 --command）
                  也会删除自动生成的 runner 脚本
  -h, --help        显示帮助

示例:
  # 注册、启动并设置开机自启
  sudo ./register-service.sh \
    --name my-worker \
    --command '/opt/my-worker --config /etc/my-worker.yml' \
    --user app \
    --workdir /opt/my-worker \
    --env APP_ENV=prod

  # 注册需要终端输入的交互式命令
  sudo ./register-service.sh \
    --name console-app \
    --command 'python3 /opt/app/app.py' \
    --interactive

  # 设置开机自启，但暂不启动
  sudo ./register-service.sh \
    --name my-worker \
    --command '/opt/my-worker' \
    --no-start

  # 删除服务并取消开机自启
  sudo ./register-service.sh --name my-worker --remove

  # 查看服务状态和实时日志
  systemctl status my-worker
  journalctl -u my-worker -f
EOF
}

die() { printf '错误: %s\n' "$*" >&2; exit 1; }
if [[ ${1:-} == '-h' || ${1:-} == '--help' ]]; then usage; exit 0; fi
[[ ${EUID} -eq 0 ]] || die '请使用 root 权限运行（例如 sudo）。'

name=''; command=''; user='root'; group=''; workdir='/'; interactive=0; no_start=0; remove=0
declare -a envs=()
while (($#)); do
  case $1 in
    --name) (($# >= 2)) || die '--name 缺少参数'; name=$2; shift 2 ;;
    --command) (($# >= 2)) || die '--command 缺少参数'; command=$2; shift 2 ;;
    --user) (($# >= 2)) || die '--user 缺少参数'; user=$2; shift 2 ;;
    --group) (($# >= 2)) || die '--group 缺少参数'; group=$2; shift 2 ;;
    --workdir) (($# >= 2)) || die '--workdir 缺少参数'; workdir=$2; shift 2 ;;
    --env) (($# >= 2)) || die '--env 缺少参数'; [[ $2 == *=* ]] || die "环境变量必须是 KEY=VALUE: $2"; envs+=("$2"); shift 2 ;;
    --interactive) interactive=1; shift ;;
    --no-start) no_start=1; shift ;;
    --remove) remove=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

[[ -n $name ]] || die '必须指定 --name。'
[[ $name =~ ^[a-zA-Z0-9_.@-]+$ ]] || die '服务名包含非法字符。'
unit="/etc/systemd/system/${name}.service"
if ((remove)); then
  systemctl disable --now "${name}.service" 2>/dev/null || true
  rm -f -- "/usr/local/sbin/${name}-service-runner"
  rm -f -- "$unit"
  systemctl daemon-reload
  printf '已删除服务: %s\n' "$name"
  exit 0
fi
[[ -n $command ]] || die '必须指定 --command。'
[[ -d $workdir ]] || die "工作目录不存在: $workdir"
getent passwd "$user" >/dev/null || die "用户不存在: $user"
if [[ -n $group ]]; then getent group "$group" >/dev/null || die "用户组不存在: $group"; fi

quote_shell() { local value=$1; printf "'%s'" "${value//\'/\'\\\'\'}"; }
session_name="svc_${name}"

if [[ ${#envs[@]} -gt 0 ]]; then
  for env in "${envs[@]}"; do
    env_key=${env%%=*}
    [[ $env_key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "环境变量名非法: $env_key"
    [[ $env != *$'\n'* ]] || die "环境变量不能包含换行符: $env_key"
  done
fi
[[ $command != *$'\n'* && $workdir != *$'\n'* ]] || die '命令和工作目录不能包含换行符。'
[[ $workdir == /* ]] || die '工作目录必须是绝对路径。'

runner="/usr/local/sbin/${name}-service-runner"
mkdir -p /usr/local/sbin
runner_tmp=$(mktemp "${runner}.tmp.XXXXXX")
trap 'rm -f -- "$runner_tmp"' EXIT
{
  printf '%s\n' '#!/usr/bin/env bash' 'set -u' ''
  printf 'cd %s || exit 1\n' "$(quote_shell "$workdir")"
  if [[ ${#envs[@]} -gt 0 ]]; then
    for env in "${envs[@]}"; do
      env_key=${env%%=*}; env_value=${env#*=}
      printf 'export %s=%s\n' "$env_key" "$(quote_shell "$env_value")"
    done
  fi
  printf 'command=%s\n' "$(quote_shell "$command")"
  printf 'session_name=%s\n' "$(quote_shell "$session_name")"
  printf '%s\n' '' 'if [[ ${1:-} == --stop ]]; then' \
    '  if command -v tmux >/dev/null 2>&1; then tmux kill-session -t "$session_name" 2>/dev/null || true; fi' \
    '  if command -v screen >/dev/null 2>&1; then screen -S "$session_name" -X quit 2>/dev/null || true; fi' \
    '  exit 0' 'fi' ''
  if ((interactive)); then
    printf '%s\n' \
      'if command -v tmux >/dev/null 2>&1; then' \
      '  tmux kill-session -t "$session_name" 2>/dev/null || true' \
      '  printf -v escaped_command "%q" "$command"' \
      '  tmux new-session -d -s "$session_name" "/bin/bash -lc $escaped_command"' \
      '  while tmux has-session -t "$session_name" 2>/dev/null; do sleep 2; done' \
      'elif command -v screen >/dev/null 2>&1; then' \
      '  screen -S "$session_name" -X quit 2>/dev/null || true' \
      '  screen -DmS "$session_name" /bin/bash -lc "$command"' \
      '  while screen -list 2>/dev/null | grep -Fq -- "$session_name"; do sleep 2; done' \
      'else' \
      "  echo '需要安装 tmux 或 screen' >&2" \
      '  exit 1' \
      'fi' \
      'exit 1'
  else
    printf '%s\n' 'exec /bin/bash -lc "$command"'
  fi
} >"$runner_tmp"
chown "$user" "$runner_tmp"
[[ -n $group ]] && chown "${user}:${group}" "$runner_tmp"
chmod 700 "$runner_tmp"
mv -f -- "$runner_tmp" "$runner"
trap - EXIT

{
  printf '%s\n' '[Unit]' "Description=Managed service: $name" 'After=network-online.target' 'Wants=network-online.target' '' '[Service]' 'Type=simple'
  printf 'User=%s\n' "$user"
  [[ -n $group ]] && printf 'Group=%s\n' "$group"
  systemd_workdir=${workdir//\\/\\\\}
  systemd_workdir=${systemd_workdir//%/%%}
  printf 'WorkingDirectory=%s\n' "$systemd_workdir"
  printf '%s\n' 'StandardOutput=journal' 'StandardError=journal'
  printf 'ExecStart=%s\n' "$runner"
  printf 'ExecStopPost=%s --stop\n' "$runner"
  printf '%s\n' 'Restart=on-failure' 'RestartSec=5' '' '[Install]' 'WantedBy=multi-user.target'
} >"$unit"
systemctl daemon-reload
systemctl enable "${name}.service" >/dev/null
if ((no_start == 0)); then systemctl restart "${name}.service"; fi
printf '服务已注册: %s\n' "$unit"
if ((no_start)); then printf '已设置开机自启，当前未启动。\n'; else printf '已启动并设置开机自启。查看日志: journalctl -u %s -f\n' "$name"; fi
