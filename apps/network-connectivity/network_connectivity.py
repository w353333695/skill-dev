#!/usr/bin/env python3
"""本地与 SSH 远程网络连通性检查；仅使用 Python 标准库。"""
from __future__ import annotations

import argparse
import contextlib
import csv
import inspect
import ipaddress
import itertools
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import traceback

VERSION = "0.1.0"
FIELDS = ["source_ip", "target_ip", "protocol", "target_port", "status", "elapsed_ms", "detail"]
SEPARATORS = r"[/,，;；\s]+"


def expand_ips(text, limit=10000):
    """展开 IPv4、末段缩写及闭区间；斜杠是分隔符，不表示 CIDR。"""
    result = {}
    prefix = None
    for token in filter(None, re.split(SEPARATORS, text.strip())):
        bounds = token.split("-")
        if len(bounds) > 2:
            raise ValueError("IP 范围无效：%s" % token)
        start_text = bounds[0]
        if "." not in start_text:
            if prefix is None or not start_text.isdecimal():
                raise ValueError("IP 缩写前必须有完整 IPv4 地址：%s" % token)
            start_text = prefix + start_text
        try:
            start = ipaddress.IPv4Address(start_text)
            end_text = bounds[-1] if len(bounds) == 2 else str(start)
            if "." not in end_text:
                end_text = str(start).rsplit(".", 1)[0] + "." + end_text
            end = ipaddress.IPv4Address(end_text)
        except ipaddress.AddressValueError as error:
            raise ValueError("IPv4 地址无效：%s（%s）" % (token, error)) from error
        if int(end) < int(start):
            raise ValueError("IP 范围起点不能大于终点：%s" % token)
        if int(end) - int(start) + 1 > limit:
            raise ValueError("IP 展开数量超过上限 %s" % limit)
        for address in range(int(start), int(end) + 1):
            result[str(ipaddress.IPv4Address(address))] = None
            if len(result) > limit:
                raise ValueError("IP 展开数量超过上限 %s" % limit)
        prefix = str(end).rsplit(".", 1)[0] + "."
    if not result:
        raise ValueError("IP 不能为空")
    return list(result)


def expand_ports(text, limit=10000):
    """展开端口闭区间；未写协议时继承上一个协议，初始为 TCP。"""
    protocol = "tcp"
    result = {}
    for token in filter(None, re.split(SEPARATORS, text.strip().lower())):
        matched = re.fullmatch(r"(?:(tcp|udp))?([0-9]+)(?:-([0-9]+))?", token)
        if not matched:
            raise ValueError("端口格式无效：%s" % token)
        protocol = matched.group(1) or protocol
        start = int(matched.group(2))
        end = int(matched.group(3) or start)
        if not 1 <= start <= end <= 65535:
            raise ValueError("端口必须为 1-65535，且范围不能倒序：%s" % token)
        if end - start + 1 > limit:
            raise ValueError("端口展开数量超过上限 %s" % limit)
        for port in range(start, end + 1):
            result[(protocol, port)] = None
            if len(result) > limit:
                raise ValueError("端口展开数量超过上限 %s" % limit)
    if not result:
        raise ValueError("目标端口不能为空")
    return list(result)


def make_tasks(source, target, ports, limit):
    sources = expand_ips(source, limit) if source.strip() else [""]
    targets = expand_ips(target, limit)
    destinations = expand_ports(ports, limit)
    if len(sources) * len(targets) * len(destinations) > limit:
        raise ValueError("源 IP × 目标 IP × 端口的任务数量超过上限 %s" % limit)
    return [dict(source_ip=origin, target_ip=address, protocol=protocol, target_port=port)
            for origin, address, (protocol, port) in itertools.product(sources, targets, destinations)]


def read_tasks_csv(stream, limit):
    aliases = {
        "source_ip": "source", "source": "source", "源ip": "source",
        "target_ip": "target", "target": "target", "目标ip": "target",
        "target_ports": "ports", "target_port": "ports", "ports": "ports", "目标端口": "ports",
    }
    reader = csv.DictReader(stream, strict=True)
    if not reader.fieldnames:
        raise ValueError("任务 CSV 缺少表头")
    columns = {}
    for header in reader.fieldnames:
        canonical = aliases.get(header.lstrip("\ufeff").strip().lower())
        if not canonical or canonical in columns:
            raise ValueError("CSV 列名未知或重复：%s" % header)
        columns[canonical] = header
    if not {"target", "ports"}.issubset(columns):
        raise ValueError("CSV 至少需要 target_ip、target_ports 两列；source_ip 可选")
    tasks = {}
    try:
        for row in reader:
            if not any(value for value in row.values()):
                continue
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV 第 %s 行列数与表头不一致" % reader.line_num)
            source = row.get(columns.get("source", ""), "")
            try:
                expanded = make_tasks(source, row[columns["target"]], row[columns["ports"]], limit)
            except ValueError as error:
                raise ValueError("CSV 第 %s 行：%s" % (reader.line_num, error)) from error
            for task in expanded:
                tasks[tuple(task.values())] = task
                if len(tasks) > limit:
                    raise ValueError("CSV 总任务数量超过上限 %s" % limit)
    except csv.Error as error:
        raise ValueError("CSV 第 %s 行格式错误：%s" % (reader.line_num, error)) from error
    if not tasks:
        raise ValueError("任务 CSV 没有有效任务")
    return list(tasks.values())


def probe(task, timeout, udp_payload):
    """检查一个端点；UDP 只有收到回应才确认可达。"""
    started = time.monotonic()
    protocol = task["protocol"]
    status = "NETWORK_ERROR"
    detail = ""
    try:
        socket_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
        with socket.socket(socket.AF_INET, socket_type) as connection:
            connection.settimeout(timeout)
            connection.connect((task["target_ip"], task["target_port"]))
            if protocol == "udp":
                connection.send(udp_payload)
                data = connection.recv(65535)
                detail = "收到 UDP 回应，长度 %s 字节" % len(data)
            else:
                detail = "TCP 连接成功"
            status = "REACHABLE"
    except socket.timeout:
        status = "UNKNOWN" if protocol == "udp" else "TIMEOUT"
        detail = "UDP 未收到回应，无法区分开放、过滤或服务不应答" if protocol == "udp" else "TCP 连接超时"
    except ConnectionRefusedError:
        status = "REFUSED"
        detail = "连接被拒绝（TCP RST 或 UDP ICMP 拒绝）"
    except OSError:
        detail = "[probe] " + traceback.format_exc()
    return dict(task, status=status, elapsed_ms=round((time.monotonic() - started) * 1000, 3), detail=detail)


def worker_main():
    request = json.load(sys.stdin)
    for task in request["tasks"]:
        result = probe(task, request["timeout"], bytes.fromhex(request["udp_payload_hex"]))
        print(json.dumps(result, ensure_ascii=True), flush=True)


def worker_source():
    return ("import json, socket, sys, time, traceback\n" + inspect.getsource(probe) + "\n"
            + inspect.getsource(worker_main) + "\nif __name__ == '__main__':\n    worker_main()\n")


def ssh_errors(tasks, detail):
    return [dict(task, status="SSH_ERROR", elapsed_ms=0, detail=detail) for task in tasks]


def probe_remote(tasks, args):
    """一个源主机共用一次 SSH 执行；免密失败后让系统 SSH 交互认证。"""
    ssh = shutil.which("ssh")
    if not ssh:
        return ssh_errors(tasks, "[probe_remote] 本机未安装系统 OpenSSH 客户端 ssh")
    known_hosts = Path(args.known_hosts).expanduser().resolve()
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ssh, "-T", "-p", str(args.ssh_port), "-l", args.ssh_user,
        "-o", "ConnectTimeout=%s" % args.ssh_timeout,
        "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2", "-o", "StrictHostKeyChecking=ask",
        "-o", "UserKnownHostsFile=%s" % known_hosts,
        "-o", "NumberOfPasswordPrompts=1", "-o", "BatchMode=yes",
        tasks[0]["source_ip"],
        shlex.quote(args.ssh_python) + " -c " + shlex.quote(worker_source()),
    ]
    payload = json.dumps({"tasks": tasks, "timeout": args.timeout, "udp_payload_hex": args.udp_payload_hex})
    environment = dict(os.environ, LC_ALL="C")
    deadline = args.ssh_timeout + len(tasks) * (3 * args.timeout + 0.1) + 120
    try:
        completed = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", timeout=deadline, env=environment)
        stderr = completed.stderr or ""
        needs_interaction = (completed.returncode == 255 and not completed.stdout.strip()
                             and ("Permission denied" in stderr or "Host key verification failed" in stderr))
        if needs_interaction:
            if not sys.stdin.isatty():
                return ssh_errors(tasks, "[probe_remote] 免密认证或主机密钥验证失败；请在交互终端重试。" + stderr.strip())
            print("源 %s 需要交互认证或主机密钥确认；请按 SSH 提示操作，密码不记录、不落盘。"
                  % tasks[0]["source_ip"], file=sys.stderr)
            interactive = list(command)
            interactive[interactive.index("BatchMode=yes")] = "BatchMode=no"
            completed = subprocess.run(interactive, input=payload, stdout=subprocess.PIPE, stderr=None,
                                       text=True, encoding="utf-8", errors="replace", timeout=deadline, env=environment)
        if completed.returncode:
            return ssh_errors(tasks, "[probe_remote] SSH/远程 Python 执行失败（退出码 %s）；%s"
                              % (completed.returncode, (completed.stderr or "详见终端 SSH 错误").strip()))
        results = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        if len(results) != len(tasks):
            raise ValueError("远程返回的结果数量不匹配")
        for task, result in zip(tasks, results):
            if (not isinstance(result, dict) or set(result) != set(FIELDS)
                    or any(result.get(key) != value for key, value in task.items())
                    or result["status"] not in {"REACHABLE", "UNKNOWN", "TIMEOUT", "REFUSED", "NETWORK_ERROR"}
                    or not isinstance(result["elapsed_ms"], (int, float)) or not isinstance(result["detail"], str)):
                raise ValueError("远程返回的结果字段无效")
        return results
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ssh_errors(tasks, "[probe_remote] " + traceback.format_exc())


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是正整数") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def positive_float(value):
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是有限正数") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("必须是有限正数")
    return parsed


def parser():
    help_parser = argparse.ArgumentParser(
        description="IPv4 TCP/UDP 连通性检查：源为空从本地发起，否则 SSH 到源主机执行。仅用于获授权的端点。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""格式：
  IP：192.168.0.13/14/29-100；支持逗号、分号、空白、换行；斜杠不是 CIDR。
  端口：tcp80/443-500/10034；udp161/162；无协议则继承上一项，初始 TCP。
  CSV：source_ip,target_ip,target_ports；单元格内换行或逗号必须用双引号包围。

示例：
  python3 network_connectivity.py -d '192.168.0.13/14' -p 'tcp80/443'
  python3 network_connectivity.py -s '192.168.1.10' -d '192.168.0.13' -p tcp80
  python3 network_connectivity.py --csv tasks.csv --output results.csv
  python3 network_connectivity.py --csv tasks.csv --dry-run

远程：本机需系统 ssh，源主机需 Python 3.9+；默认 root，先免密后交互认证。
首次连接需确认主机指纹；不会关闭主机密钥检查，密码由 SSH 从终端读取、不保存。
输出：默认逐条打印；-o 同时写 UTF-8 BOM CSV。Ctrl+C 停止，已写出的行保留。
UDP：仅收到响应判为 REACHABLE；无响应为 UNKNOWN，不能视作开放或关闭。
退出码：0=全部可达/仅预览；1=存在失败或不确定；2=参数/文件错误；130=用户中断。
""")
    help_parser.add_argument("-s", "--source", "--source-ip", default="", help="源 IPv4 表达式；默认空，即本地执行，不是绑定本机网卡")
    help_parser.add_argument("-d", "--target", "--target-ip", default="", help="目标 IPv4 表达式；直接模式必填，默认空")
    help_parser.add_argument("-p", "--ports", "--target-ports", default="", help="目标协议与端口表达式；直接模式必填，默认空")
    help_parser.add_argument("-c", "--csv", metavar="FILE", help="任务 CSV（UTF-8，可带 BOM）；默认不使用，不能混用 -s/-d/-p")
    help_parser.add_argument("-o", "--output", metavar="FILE", help="同时输出结果到 CSV，会覆盖同名文件；默认仅打印")
    help_parser.add_argument("-t", "--timeout", type=positive_float, default=2.0, help="每项 socket 操作超时秒数；默认 2")
    help_parser.add_argument("--max-tasks", type=positive_int, default=10000, help="展开数量及总任务上限；默认 10000，超限不执行")
    help_parser.add_argument("--ssh-user", default="root", help="SSH 用户；默认 root；密码仅通过 SSH 交互输入")
    help_parser.add_argument("--ssh-port", type=positive_int, default=22, help="SSH 端口；默认 22")
    help_parser.add_argument("--ssh-timeout", type=positive_int, default=10, help="SSH 建连超时秒数；默认 10")
    help_parser.add_argument("--ssh-python", default="python3", help="源主机的 Python 3.9+ 命令或路径；默认 python3")
    help_parser.add_argument("--known-hosts", default=str(Path(__file__).resolve().parent / ".local" / "known_hosts"),
                             help="SSH 主机密钥文件；默认脚本目录内 .local/known_hosts，不写用户主目录")
    help_parser.add_argument("--udp-payload-hex", default="", help="UDP 报文十六进制内容；默认空报文，按服务协议提供才可能收到回应")
    help_parser.add_argument("--dry-run", action="store_true", help="仅展开、校验和打印计划，不创建网络连接或调用 SSH；默认关闭")
    help_parser.add_argument("-V", "--version", action="version", version="%(prog)s " + VERSION)
    return help_parser


def emit(result, writer):
    detail = " ".join(str(result["detail"]).splitlines())
    print("%s -> %s %s/%s %s %.3fms %s" % (
        result["source_ip"] or "本机", result["target_ip"], result["protocol"],
        result["target_port"], result["status"], result["elapsed_ms"], detail), flush=True)
    if writer:
        writer.writerow(result)


def main(argv=None):
    help_parser = parser()
    args = help_parser.parse_args(argv)
    if args.ssh_port > 65535:
        help_parser.error("SSH 端口必须为 1-65535")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*\$?", args.ssh_user):
        help_parser.error("SSH 用户名格式无效")
    if not args.ssh_python or "\x00" in args.ssh_python:
        help_parser.error("SSH Python 命令不能为空或包含 NUL")
    try:
        udp_payload = bytes.fromhex(args.udp_payload_hex)
        if len(udp_payload) > 65507:
            raise ValueError("UDP 报文不能超过 65507 字节")
        if args.csv:
            if args.source or args.target or args.ports:
                raise ValueError("--csv 不能与 -s/-d/-p 混用")
            if args.output:
                same_path = Path(args.csv).resolve() == Path(args.output).resolve()
                same_file = Path(args.output).exists() and os.path.samefile(args.csv, args.output)
                if same_path or same_file:
                    raise ValueError("输出 CSV 不能覆盖输入任务 CSV")
            with open(args.csv, encoding="utf-8-sig", newline="") as stream:
                tasks = read_tasks_csv(stream, args.max_tasks)
        else:
            tasks = make_tasks(args.source, args.target, args.ports, args.max_tasks)
    except (ValueError, OSError, UnicodeError) as error:
        help_parser.error(str(error))
    failed = 0
    try:
        with contextlib.ExitStack() as stack:
            writer = None
            output = None
            if args.output:
                output = stack.enter_context(open(args.output, "w", encoding="utf-8-sig", newline=""))
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                writer.writeheader()
                output.flush()
            grouped = {}
            for task in tasks:
                grouped.setdefault(task["source_ip"], []).append(task)
            for source, group in grouped.items():
                if args.dry_run:
                    results = (dict(task, status="PLANNED", elapsed_ms=0, detail="仅预览，未执行") for task in group)
                elif source:
                    results = probe_remote(group, args)
                else:
                    results = (probe(task, args.timeout, udp_payload) for task in group)
                for result in results:
                    emit(result, writer)
                    if output:
                        output.flush()
                    failed += result["status"] not in {"REACHABLE", "PLANNED"}
            print("合计 %s 项，失败或不确定 %s 项%s" % (len(tasks), failed, "（仅预览）" if args.dry_run else ""), file=sys.stderr)
    except KeyboardInterrupt:
        print("\n已停止；已输出的 CSV 结果保留。", file=sys.stderr)
        return 130
    except OSError:
        print("[main] " + traceback.format_exc(), file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
