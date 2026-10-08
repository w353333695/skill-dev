#!/usr/bin/env python3
"""根据 YAML 生成、检查或应用 Keepalived 配置；不执行 YAML 中的命令。"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from urllib.parse import urlsplit

# 生成的健康脚本仅依赖 Python 标准库，运行时不再读取 YAML 或导入 PyYAML。
HEALTH_PROGRAM = r'''
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request


def check_one(check):
    kind = check["type"]
    timeout = check["timeout"]
    if kind == "process":
        # 用参数数组调用 pgrep，配置内容不交给 shell 执行；排除本检查脚本的 PID。
        args = ["pgrep", "-f" if check["match"] == "cmdline" else "-x", "--", check["pattern"]]
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or "pgrep 执行失败")
        count = sum(pid.isdigit() and int(pid) != os.getpid() for pid in result.stdout.split())
        return count >= check["min_count"], "匹配进程数=%d，要求至少=%d" % (count, check["min_count"])
    if kind == "tcp":
        with socket.create_connection((check["host"], check["port"]), timeout=timeout):
            return True, "TCP 连接成功"
    # 禁用环境代理，避免本机请求意外经由代理；禁止重定向，防止检测落到其他服务。
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(check["url"], headers={"User-Agent": "keepalived-health/1.0"})
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.code
        if status not in check["expected_status"]:
            return False, "HTTP 状态码=%d，不符合期望" % status
        if "body_contains" in check:
            # 正文最多读取 64 KiB；总时限还由独立进程的整轮超时兜底。
            body = response.read(65536).decode("utf-8", errors="replace")
            if check["body_contains"] not in body:
                return False, "HTTP 正文未包含预期文本（检查前 64 KiB）"
        return True, "HTTP 状态码=%d" % status


def worker(check):
    try:
        passed, detail = check_one(check)
        return check["name"], passed, detail
    except Exception:
        import traceback
        return check["name"], False, "[check_one] " + traceback.format_exc()


def main():
    # 检查并行执行，减少多服务检查的总等待时间；限制线程数避免配置过多造成负载。
    checks = SPEC["checks"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(checks), 16)) as executor:
        results = list(executor.map(worker, checks))
    successes = sum(result[1] for result in results)
    policy = SPEC["policy"]
    required = len(checks) if policy == "all" else 1 if policy == "any" else SPEC["min_success"]
    if "--quiet" not in sys.argv:
        for name, passed, detail in results:
            print("[%s] %s: %s" % ("PASS" if passed else "FAIL", name, detail), flush=True)
        print("汇总：%d/%d 成功，要求 %d 项成功" % (successes, len(checks), required), flush=True)
    return 0 if successes >= required else 1


if __name__ == "__main__":
    # 主程序会重入 --worker 子进程；父进程对整轮检查施加硬超时。
    if "--worker" in sys.argv:
        sys.exit(main())
    try:
        result = subprocess.run([sys.executable, os.path.abspath(__file__), "--worker"] +
                                (["--quiet"] if "--quiet" in sys.argv else []),
                                timeout=SPEC["round_timeout"])
        sys.exit(result.returncode if result.returncode in (0, 1) else 1)
    except subprocess.TimeoutExpired:
        if "--quiet" not in sys.argv:
            print("FAIL：整轮健康检查超时", file=sys.stderr)
        sys.exit(1)
'''


def fail(message):
    raise ValueError(message)


def mapping(value, where, allowed):
    if not isinstance(value, dict):
        fail("%s 必须是对象" % where)
    unknown = set(value) - set(allowed)
    if unknown:
        fail("%s 存在未知字段：%s" % (where, sorted(map(str, unknown))))
    return value


def number(value, where, minimum, maximum, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail("%s 必须是有限数字" % where)
    if integer and not isinstance(value, int):
        fail("%s 必须是整数" % where)
    if not minimum <= value <= maximum:
        fail("%s 必须在 %s 到 %s 之间" % (where, minimum, maximum))
    return value


def token(value, where, pattern=r"[A-Za-z0-9_.-]+"):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        fail("%s 格式不合法" % where)
    return value


def load_config(path, node_name):
    try:
        import yaml
    except ImportError:
        fail("需要 PyYAML；请在独立 Python 环境安装，并用 HA_PYTHON 指向该环境的解释器")
    # 拒绝重复键，避免用户以为两条规则生效，实际后面的覆盖前面的。
    class UniqueLoader(yaml.SafeLoader):
        pass
    def unique_mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                fail("YAML 重复字段：%s" % key)
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
    data = mapping(yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader),
                   "根配置", ["version", "vrrp", "nodes", "health"])
    if type(data.get("version")) is not int or data["version"] != 1:
        fail("version 必须是整数 1")
    vrrp = mapping(data.get("vrrp"), "vrrp", ["instance", "router_id", "vip", "preempt", "advert_int"])
    token(vrrp.get("instance"), "vrrp.instance")
    number(vrrp.get("router_id"), "vrrp.router_id", 1, 255, True)
    vip = ipaddress.ip_interface(vrrp.get("vip", ""))
    if vip.version != 4 or vip.ip.is_unspecified or vip.ip.is_multicast or vip.ip.is_loopback:
        fail("vrrp.vip 必须是有效的 IPv4 VIP，包含掩码，例如 192.168.10.100/24")
    if "/" not in vrrp["vip"]:
        fail("vrrp.vip 必须显式包含掩码")
    vrrp.setdefault("preempt", False)
    if type(vrrp["preempt"]) is not bool:
        fail("vrrp.preempt 必须是 true 或 false")
    number(vrrp.setdefault("advert_int", 1), "vrrp.advert_int", 1, 60, True)
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or len(nodes) < 2:
        fail("nodes 至少配置两个节点")
    if node_name not in nodes:
        fail("--node 不在 nodes 中：%s" % node_name)
    addresses = set()
    for name, node in nodes.items():
        token(name, "节点名")
        mapping(node, "nodes." + name, ["address", "interface", "priority"])
        address = ipaddress.ip_address(node.get("address", ""))
        if address.version != 4 or address not in vip.network or address == vip.ip:
            fail("节点 %s 的 IPv4 地址必须与 VIP 同网段且不同于 VIP" % name)
        if address.is_unspecified or address.is_multicast or address.is_loopback:
            fail("节点 %s 地址不合法" % name)
        if str(address) in addresses:
            fail("节点地址不可重复")
        addresses.add(str(address))
        token(node.get("interface"), "节点网卡", r"[A-Za-z0-9_.:-]{1,15}")
        number(node.get("priority"), "节点 priority", 1, 254, True)
    health = mapping(data.get("health"), "health", ["policy", "min_success", "interval", "round_timeout", "fall", "rise", "checks"])
    health.setdefault("policy", "all")
    if health["policy"] not in ("all", "any", "quorum"):
        fail("health.policy 只能为 all、any 或 quorum")
    for field, default in (("interval", 2), ("round_timeout", 5), ("fall", 3), ("rise", 2)):
        number(health.setdefault(field, default), "health." + field, 1, 3600, True)
    checks = health.get("checks")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 16:
        fail("health.checks 必须包含 1 到 16 项检查")
    names = set()
    for check in checks:
        if not isinstance(check, dict):
            fail("每项 checks 必须是对象")
        kind = check.get("type")
        common = ["name", "type", "timeout"]
        fields = {"process": ["match", "pattern", "min_count"], "tcp": ["host", "port"],
                  "http": ["url", "expected_status", "body_contains"]}
        if kind not in fields:
            fail("检查类型只能为 process、tcp、http")
        mapping(check, "检查规则", common + fields[kind])
        token(check.get("name"), "检查名称")
        if check["name"] in names:
            fail("检查名称不可重复")
        names.add(check["name"])
        timeout = number(check.setdefault("timeout", 1), "检查 timeout", 0.1, 3600)
        if timeout >= health["round_timeout"]:
            fail("每项 timeout 必须小于 round_timeout，以预留整轮调度时间")
        if kind == "process":
            check.setdefault("match", "name")
            if check["match"] not in ("name", "cmdline"):
                fail("process.match 只能为 name 或 cmdline")
            if not isinstance(check.get("pattern"), str) or not check["pattern"] or "\x00" in check["pattern"]:
                fail("process.pattern 必须是非空字符串")
            number(check.setdefault("min_count", 1), "process.min_count", 1, 65535, True)
        elif kind == "tcp":
            # 使用 IP 字面量，避免 DNS 解析不受 socket timeout 约束。
            ipaddress.ip_address(check.get("host", "127.0.0.1"))
            check.setdefault("host", "127.0.0.1")
            number(check.get("port"), "tcp.port", 1, 65535, True)
        else:
            url = check.get("url")
            if not isinstance(url, str):
                fail("http.url 必须是字符串")
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                fail("http.url 必须是 HTTP/HTTPS 地址，且不能包含用户名或密码")
            if parsed.fragment or any(char.isspace() for char in url):
                fail("http.url 不能包含空白或 fragment")
            if parsed.port is not None:
                number(parsed.port, "http URL 端口", 1, 65535, True)
            statuses = check.setdefault("expected_status", [200])
            if not isinstance(statuses, list) or not statuses:
                fail("http.expected_status 必须是非空数组")
            for status in statuses:
                number(status, "HTTP 状态码", 100, 599, True)
            if "body_contains" in check and (not isinstance(check["body_contains"], str) or not check["body_contains"]):
                fail("http.body_contains 必须是非空字符串")
    if health["policy"] == "quorum":
        number(health.get("min_success"), "health.min_success", 1, len(checks), True)
    elif "min_success" in health:
        fail("min_success 仅可用于 quorum 策略")
    return data


def render(data, node_name, install_dir):
    health = data["health"]
    spec = {key: health[key] for key in ("policy", "round_timeout", "checks")}
    if "min_success" in health:
        spec["min_success"] = health["min_success"]
    node, vrrp = data["nodes"][node_name], data["vrrp"]
    # 健康脚本由 Keepalived 直接执行；绝对 shebang 避免 daemon 的 PATH 与交互 shell 不同。
    python_path = str(Path(sys.executable).resolve())
    for value in (python_path, str(install_dir)):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            fail("解释器或安装目录路径不支持空格及特殊字符：%s" % value)
    runtime = "#!" + python_path + "\n# 自动生成：本机服务健康检查，修改源 YAML 后重新生成。\nSPEC = " + repr(spec) + "\n" + HEALTH_PROGRAM
    digest = hashlib.sha256(runtime.encode()).hexdigest()[:16]
    script_name = "ha-check-" + digest + ".py"
    peers = "\n".join("        " + item["address"] for name, item in data["nodes"].items() if name != node_name)
    config = f'''# 自动生成：节点 {node_name}。健康脚本 weight 0，失败进入 FAULT。
# 所有节点初始 state BACKUP，便于 nopreempt 生效。
global_defs {{
    router_id {node_name}
    script_user root
    enable_script_security
}}

vrrp_script ha_health {{
    script "{install_dir / script_name} --quiet"
    interval {health['interval']}
    timeout {health['round_timeout'] + 2}
    fall {health['fall']}
    rise {health['rise']}
    weight 0
    init_fail
}}

vrrp_instance {vrrp['instance']} {{
    state BACKUP
    interface {node['interface']}
    virtual_router_id {vrrp['router_id']}
    priority {node['priority']}
    advert_int {vrrp['advert_int']}
    {'# 恢复后允许抢占' if vrrp['preempt'] else 'nopreempt'}
    unicast_src_ip {node['address']}
    unicast_peer {{
{peers}
    }}
    virtual_ipaddress {{
        {vrrp['vip']} dev {node['interface']}
    }}
    track_script {{
        ha_health
    }}
}}
'''
    return config, runtime, script_name


def run(command, **kwargs):
    import shlex
    print("$ " + shlex.join(command), flush=True)
    return subprocess.run(command, check=True, timeout=30, **kwargs)


def apply(config_path, script_path, install_dir, node):
    if install_dir != Path("/etc/keepalived"):
        fail("--apply 仅支持默认 /etc/keepalived；自定义目录请先生成，再按实际服务启动参数手动部署")
    if sys.platform != "linux" or os.geteuid() != 0:
        fail("--apply 需要在 Linux 上以 root 运行；当前环境可以使用 --dry-run")
    for binary in ("keepalived", "systemctl", "ip"):
        if not shutil.which(binary):
            fail("--apply 缺少依赖：%s，请先安装" % binary)
    # 应用前确认配置中的源地址确实绑定在本机指定网卡上。
    addresses = json.loads(run(["ip", "-j", "address", "show", "dev", node["interface"]], capture_output=True, text=True).stdout)
    if not any(item.get("local") == node["address"] for interface in addresses for item in interface.get("addr_info", [])):
        fail("节点 address 未绑定在本机配置的 interface 上")
    if install_dir.exists():
        if install_dir.is_symlink() or install_dir.stat().st_uid != 0 or install_dir.stat().st_mode & 0o022:
            fail("安装目录必须由 root 所有，且不可被组或其他用户写入")
    else:
        install_dir.mkdir(parents=True, mode=0o755)
    # 健康脚本采用内容哈希命名，旧配置始终引用旧脚本；失败恢复时不混用版本。
    installed_script = install_dir / script_path.name
    if installed_script.exists() and installed_script.is_symlink():
        fail("健康脚本路径不可为符号链接")
    shutil.copyfile(script_path, installed_script)
    installed_script.chmod(0o700)
    target = install_dir / "keepalived.conf"
    if target.is_symlink():
        fail("keepalived.conf 不可为符号链接")
    staged = install_dir / (".ha-config-%d.conf" % os.getpid())
    backup = None
    was_active = subprocess.run(["systemctl", "is-active", "--quiet", "keepalived"], timeout=10).returncode == 0
    try:
        shutil.copyfile(config_path, staged)
        staged.chmod(0o600)
        run(["keepalived", "--config-test", "--use-file=" + str(staged)])
        if target.exists():
            backup = install_dir / ("keepalived.conf.bak-%s-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
            shutil.copy2(target, backup)
            print("旧配置备份：%s" % backup)
        os.replace(staged, target)
        try:
            # 重启可完整应用 VRRP 与脚本变化；会短暂释放 VIP，执行前应安排变更窗口。
            run(["systemctl", "restart", "keepalived"])
            run(["systemctl", "is-active", "--quiet", "keepalived"])
        except Exception:
            print("[apply] 启动失败，恢复旧配置：\n" + traceback.format_exc(), file=sys.stderr)
            if backup:
                shutil.copy2(backup, target)
            else:
                target.unlink(missing_ok=True)
            if was_active:
                run(["systemctl", "restart", "keepalived"])
            else:
                run(["systemctl", "stop", "keepalived"])
            raise
    finally:
        staged.unlink(missing_ok=True)
    print("应用完成。未修改开机启动策略；如需自启，请执行 systemctl enable keepalived。")


def main():
    parser = argparse.ArgumentParser(
        description="从 YAML 一键生成/校验/应用 Keepalived。健康检查支持进程、TCP、HTTP。",
        epilog="示例：\n  python3 ./ha-configure.py --config ha.sample.yaml --node node-a --dry-run\n"
               "  python3 ./ha-configure.py --config ha.yaml --node node-a --check\n"
               "  sudo python3 ./ha-configure.py --config ha.yaml --node node-a --apply\n"
               "退出码：0=成功，1=健康检查失败/整轮超时，2=配置或执行错误。\n"
               "--apply 会替换整个 keepalived.conf 并重启服务（VIP 可能短暂释放）；自动备份及失败恢复。\n"
               "依赖：Python 3.9+、PyYAML；应用需 Linux、root、已安装 keepalived 和 systemd。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    parser.add_argument("--config", type=Path, required=True, help="YAML 配置文件（必填）")
    parser.add_argument("--node", required=True, help="当前节点名，必须存在于 nodes 中（必填）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="校验配置并执行一次本机健康检查，不应用系统配置")
    mode.add_argument("--dry-run", action="store_true", help="生成配置与检查脚本并打印配置，不应用系统配置")
    mode.add_argument("--apply", action="store_true", help="校验后备份、安装并重启；不自动安装软件")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "generated", help="生成目录（默认：脚本目录/generated/<node>）")
    parser.add_argument("--install-dir", type=Path, default=Path("/etc/keepalived"), help="生成配置中引用的安装目录（默认：/etc/keepalived；自定义目录仅支持预览/检查）")
    args = parser.parse_args()
    data = load_config(args.config, args.node)
    config, runtime, script_name = render(data, args.node, args.install_dir.resolve())
    destination = args.output_dir.resolve() / args.node
    destination.mkdir(parents=True, exist_ok=True)
    config_path = destination / "keepalived.conf"
    script_path = destination / script_name
    config_path.write_text(config, encoding="utf-8")
    script_path.write_text(runtime, encoding="utf-8")
    script_path.chmod(0o700)
    print("配置校验通过；生成目录：%s" % destination, flush=True)
    if args.check:
        return subprocess.run([sys.executable, str(script_path)], timeout=data["health"]["round_timeout"] + 3).returncode
    if args.dry_run:
        print(config)
        print("未写入系统目录。部署时请将健康脚本与 keepalived.conf 一起安装。")
    else:
        apply(config_path, script_path, args.install_dir.resolve(), data["nodes"][args.node])
    return 0


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        sys.exit("需要 Python 3.9 或更高版本")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("操作已中断", file=sys.stderr)
        sys.exit(130)
    except Exception:
        print("[main] 配置或执行错误：\n" + traceback.format_exc(), file=sys.stderr)
        sys.exit(2)
