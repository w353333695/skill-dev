#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""IBM MQ 本地队列管理器监控脚本，参数由 EASYOPS_COLLECTOR_* 环境变量注入。"""
from __future__ import division, print_function
import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import traceback

VERSION = "0.2.0"
STATUS_COMMAND = "DISPLAY QSTATUS(*) CURDEPTH MSGAGE IPPROCS OPPROCS"
QUEUE_COMMAND = "DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH"
CHANNEL_COMMAND = "DISPLAY CHSTATUS(*) CHANNEL CHLTYPE STATUS MSGS BYTES"
LISTENER_COMMAND = "DISPLAY LSSTATUS(*) LISTENER PORT STATUS"


def env(name, default=""):
    value = os.environ.get("EASYOPS_COLLECTOR_" + name, default)
    if value is None:
        return default
    value = str(value).strip()
    return default if value.lower() in ("", "null", "none", "undefined", "<nil>") else value


def config():
    try:
        timeout = int(env("commandTimeout", "10"))
        interval = float(env("sampleInterval", "0.2"))
    except ValueError:
        raise ValueError("[config] commandTimeout必须为整数，sampleInterval必须为数字")
    if timeout < 1 or timeout > 60:
        raise ValueError("[config] commandTimeout必须在1到60之间")
    if interval < 0.05 or interval > 2:
        raise ValueError("[config] sampleInterval必须在0.05到2之间")
    return {
        "ibmmqInstanceId": env("instanceId"),
        "qmgrName": env("qmgrName"),
        "hostIp": env("hostIp"),
        "installPath": env("installPath"),
        "mqBinPath": env("mqBinPath"),
        "queueFilter": env("queueFilter", ".*"),
        "includeSystemQueues": env("includeSystemQueues", "false").lower() in ("1", "true", "yes"),
        "processMonitor": env("processMonitor", "true").lower() in ("1", "true", "yes"),
        "timeout": timeout,
        "interval": interval,
    }
    if not settings["qmgrName"] or settings["qmgrName"].startswith("$."):
        raise ValueError("[config] IBMMQ_QMGR实例缺少qmgrName，无法定位队列管理器")


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def execute(args, settings, input_text=None):
    process = None
    expired = [False]
    def stop_process():
        if process is not None and process.poll() is None:
            expired[0] = True
            try:
                process.kill()
            except OSError:
                pass
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        timer = threading.Timer(settings["timeout"], stop_process)
        timer.daemon = True
        timer.start()
        stdin_text = None if input_text is None else input_text.encode("utf-8")
        stdout, stderr = process.communicate(stdin_text)
        timer.cancel()
        text = decode(stdout) + "\n" + decode(stderr)
        if expired[0]:
            return 124, text + "\nAMQ9999E: command timeout"
        return process.returncode or 0, text
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass


def find_mq_bin(settings):
    configured = settings["mqBinPath"]
    install_path = settings.get("installPath", "")
    if install_path:
        candidates = [install_path if install_path.endswith("/bin") else install_path.rstrip("/") + "/bin"]
    else:
        candidates = []
    if configured and not configured.startswith("$."):
        path = os.path.join(configured, "dspmq")
        if os.access(path, os.X_OK):
            return configured
    installation_path = os.environ.get("MQ_INSTALLATION_PATH")
    if installation_path:
        candidates.append(os.path.join(installation_path, "bin"))
    candidates.extend([install_path.rstrip("/") + "/bin" if install_path and not install_path.endswith("/bin") else install_path, "/opt/mqm/bin", "/opt/ibm/mq/bin", "/usr/mqm/bin"])
    path_env = os.environ.get("PATH", "")
    for name in path_env.split(os.pathsep):
        if name:
            candidates.append(name)
    for candidate in candidates:
        if os.access(os.path.join(candidate, "dspmq"), os.X_OK):
            return candidate
    return ""


def parse_attributes(line):
    result = {}
    pattern = re.compile(r"([A-Z][A-Z0-9_]{1,40})\s*\(([^()]*)\)")
    for match in pattern.finditer(line):
        key = match.group(1)
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def numeric(value, default=0.0):
    try:
        number = float(value)
        return number if not (math.isnan(number) or math.isinf(number)) else default
    except (TypeError, ValueError):
        return default


def discover_qmgrs(mq_bin, settings):
    args = [os.path.join(mq_bin, "dspmq"), "-o", "status"]
    if settings["qmgrName"]:
        args.extend(["-m", settings["qmgrName"]])
    returncode, output = execute(args, settings)
    qmgrs = []
    for line in output.splitlines():
        attrs = parse_attributes(line)
        name = attrs.get("QMNAME")
        if name and not any(row["qmgrName"] == name for row in qmgrs):
            qmgrs.append({"qmgrName": name, "status": attrs.get("STATUS", ""), "dspmqReturnCode": returncode})
    if not qmgrs and returncode != 0:
        raise RuntimeError("[discover_qmgrs] dspmq执行失败: " + output.strip()[-500:])
    return qmgrs, returncode


def run_mqsc(mq_bin, qmgr_name, settings):
    commands = "\n".join([QUEUE_COMMAND, STATUS_COMMAND, CHANNEL_COMMAND, LISTENER_COMMAND, "EXIT"]) + "\n"
    args = [os.path.join(mq_bin, "runmqsc"), qmgr_name]
    returncode, output = execute(args, settings, commands)
    return returncode, output


def parse_mqsc(output, settings):
    queues = {}
    channels = []
    listeners = []
    for line in output.splitlines():
        attrs = parse_attributes(line)
        if not attrs:
            continue
        queue_name = attrs.get("QNAME") or attrs.get("QUEUE")
        if queue_name:
            name = queue_name
            if name not in queues:
                queues[name] = {}
            row = queues[name]
            if "CURDEPTH" in attrs:
                row["currentDepth"] = numeric(attrs.get("CURDEPTH"))
            if "MAXDEPTH" in attrs:
                row["maxDepth"] = numeric(attrs.get("MAXDEPTH"), 1.0)
            if "MSGAGE" in attrs:
                row["oldestMessageAge"] = numeric(attrs.get("MSGAGE"))
            if "IPPROCS" in attrs:
                row["inputHandles"] = numeric(attrs.get("IPPROCS"))
            if "OPPROCS" in attrs:
                row["outputHandles"] = numeric(attrs.get("OPPROCS"))
        channel_name = attrs.get("CHANNEL")
        if channel_name:
            channels.append({
                "channelName": channel_name,
                "channelType": attrs.get("CHLTYPE", "UNKNOWN"),
                "status": attrs.get("STATUS", ""),
                "messages": numeric(attrs.get("MSGNO", attrs.get("MSGS", 0))),
                "bytes": numeric(attrs.get("BYTES", attrs.get("BYTS", 0))),
            })
        listener_name = attrs.get("LISTENER")
        if listener_name:
            listeners.append({
                "listenerName": listener_name,
                "port": attrs.get("PORT", ""),
                "status": attrs.get("STATUS", ""),
            })
    selected_queues = []
    pattern = re.compile(settings["queueFilter"])
    for name in sorted(queues):
        if not settings["includeSystemQueues"] and name.upper().startswith("SYSTEM."):
            continue
        if not pattern.search(name):
            continue
        row = queues[name]
        row["queueName"] = name
        selected_queues.append(row)
    return selected_queues, channels, listeners


def normalize_status(status):
    value = (status or "").upper()
    if "RUNNING" in value:
        return 1.0
    if "STARTING" in value or "INITIAL" in value or "BINDING" in value:
        return 0.5
    if "PAUSED" in value or "STANDBY" in value:
        return 0.25
    return 0.0


def read_cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            data = handle.read().split(b"\0")
        return decode(data[0]), " ".join([decode(item) for item in data[1:] if item])
    except (IOError, OSError):
        return "", ""


def read_process(pid):
    executable, arguments = read_cmdline(pid)
    if not executable:
        return None
    row = {"pid": pid, "executable": executable, "cmdline": (executable + " " + arguments).strip()}
    try:
        with open("/proc/%d/stat" % pid, "rb") as handle:
            fields = decode(handle.read()).split()
        row["userTicks"] = float(fields[13]) + float(fields[14])
        row["threads"] = float(fields[19])
    except (IOError, OSError, ValueError, IndexError):
        row["userTicks"] = 0.0
        row["threads"] = 0.0
    row["memoryBytes"] = 0.0
    row["fdCount"] = 0.0
    try:
        with open("/proc/%d/status" % pid, "rb") as handle:
            for line in handle:
                if line.startswith(b"VmRSS:"):
                    row["memoryBytes"] = float(line.split()[1]) * 1024.0
                    break
    except (IOError, OSError, ValueError, IndexError):
        pass
    try:
        row["fdCount"] = float(len(os.listdir("/proc/%d/fd" % pid)))
    except OSError:
        pass
    return row


def ibm_mq_process(row, qmgr_name):
    executable = row["executable"].lower()
    basename = os.path.basename(executable)
    cmdline = row["cmdline"].lower()
    mq_path = "/opt/mqm/" in executable or "/opt/ibm/mq/" in executable or "/usr/mqm/" in executable
    core_names = ("runmqlsr", "amqzxma0", "amqzlaa0", "amqzlsa0", "amqrmppa", "amqzmuc0")
    if qmgr_name and qmgr_name.lower() not in cmdline:
        return False
    return basename in core_names or (mq_path and basename.startswith("amq"))


def collect_processes(qmgr_name, settings):
    first = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        row = read_process(pid)
        if row and ibm_mq_process(row, qmgr_name):
            first[pid] = row
    if settings["interval"] > 0:
        time.sleep(settings["interval"])
    grouped = {}
    ticks_per_second = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0
    for pid, old in first.items():
        row = read_process(pid)
        if not row:
            continue
        cpu = (row["userTicks"] - old["userTicks"]) / ticks_per_second / settings["interval"] * 100.0
        key = row["cmdline"][:512]
        if key not in grouped:
            grouped[key] = {"cmdline": key, "alive": 0.0, "count": 0.0, "cpu": 0.0,
                            "memory": 0.0, "threads": 0.0, "fds": 0.0}
        grouped[key]["alive"] = 1.0
        grouped[key]["count"] += 1.0
        grouped[key]["cpu"] += max(0.0, cpu)
        grouped[key]["memory"] += row["memoryBytes"]
        grouped[key]["threads"] += row["threads"]
        grouped[key]["fds"] += row["fdCount"]
    return grouped


def collect_qmgr(qmgr, mq_bin, settings):
    base = {"ibmmqInstanceId": settings["ibmmqInstanceId"], "qmgrName": qmgr["qmgrName"], "hostIp": settings.get("hostIp", ""), "installPath": settings.get("installPath", "") or os.path.dirname(mq_bin)}
    values = {
        "ibmmq_qmgr_status": 1.0 if qmgr.get("status", "").upper() == "RUNNING" else 0.0,
        "ibmmq_discovery_success": 1.0,
    }
    rows = [dict(dims=dict(base), vals=dict(values))]
    returncode, output = run_mqsc(mq_bin, qmgr["qmgrName"], settings)
    command_success = float(returncode == 0 and "COMMAND ACCEPTED" in output.upper())
    queues, channels, listeners = parse_mqsc(output, settings)
    summary = dict(base)
    summary_values = {
        "ibmmq_collect_success": 1.0,
        "ibmmq_sc_command_success": command_success,
        "ibmmq_queue_total": float(len(queues)),
        "ibmmq_queue_depth_total": float(sum(row.get("currentDepth", 0.0) for row in queues)),
        "ibmmq_queue_max_depth": max([row.get("maxDepth", 0.0) for row in queues] or [0.0]),
        "ibmmq_queue_max_usage_percent": max([row.get("currentDepth", 0.0) / row.get("maxDepth", 1.0) * 100.0 for row in queues] or [0.0]),
        "ibmmq_listener_total": float(len(listeners)),
        "ibmmq_listener_running_count": float(sum(1 for row in listeners if normalize_status(row["status"]) == 1.0)),
        "ibmmq_channel_total": float(len(channels)),
        "ibmmq_channel_running_count": float(sum(1 for row in channels if normalize_status(row["status"]) == 1.0)),
        "ibmmq_channel_retrying_count": float(sum(1 for row in channels if "RETRY" in row["status"].upper())),
    }
    rows.append(dict(dims=summary, vals=summary_values))
    for row in queues:
        dims = dict(base, queueName=row["queueName"])
        vals = {
            "ibmmq_queue_current_depth": row.get("currentDepth", 0.0),
            "ibmmq_queue_max_depth": row.get("maxDepth", 0.0),
            "ibmmq_queue_usage_percent": row.get("currentDepth", 0.0) / row.get("maxDepth", 1.0) * 100.0,
        }
        if "oldestMessageAge" in row:
            vals["ibmmq_queue_oldest_message_age_seconds"] = row["oldestMessageAge"]
        if "inputHandles" in row:
            vals["ibmmq_queue_input_handles"] = row["inputHandles"]
        if "outputHandles" in row:
            vals["ibmmq_queue_output_handles"] = row["outputHandles"]
        rows.append(dict(dims=dims, vals=vals))
    for row in channels:
        rows.append(dict(dims=dict(base, channelName=row["channelName"], channelType=row["channelType"]), vals={
            "ibmmq_channel_status": normalize_status(row["status"]),
            "ibmmq_channel_messages": row["messages"],
            "ibmmq_channel_bytes": row["bytes"],
        }))
    for row in listeners:
        rows.append(dict(dims=dict(base, listenerName=row["listenerName"], port=row["port"]), vals={
            "ibmmq_listener_status": normalize_status(row["status"]),
        }))
    if settings["processMonitor"]:
        for row in collect_processes(qmgr["qmgrName"], settings).values():
            rows.append(dict(dims=dict(base, cmdline=row["cmdline"]), vals={
                "ibmmq_process_alive": row["alive"],
                "ibmmq_process_count": row["count"],
                "ibmmq_process_cpu_percent": row["cpu"],
                "ibmmq_process_memory_bytes": row["memory"],
                "ibmmq_process_thread_count": row["threads"],
                "ibmmq_process_fd_count": row["fds"],
            }))
    return rows


def collect(settings):
    mq_bin = find_mq_bin(settings)
    if not mq_bin:
        raise RuntimeError("[collect] 未找到可执行dspmq，请设置mqBinPath并确认执行用户有IBM MQ命令权限")
    qmgrs, returncode = discover_qmgrs(mq_bin, settings)
    output = []
    for qmgr in qmgrs:
        output.extend(collect_qmgr(qmgr, mq_bin, settings))
    target_found = len(qmgrs) == 1
    output.append(dict(dims={"ibmmqInstanceId": settings["ibmmqInstanceId"]}, vals={
        "ibmmq_qmgr_count": float(len(qmgrs)),
        "ibmmq_collect_success": float(target_found),
    }))
    if not qmgrs:
        base = {
            "ibmmqInstanceId": settings["ibmmqInstanceId"], "qmgrName": settings["qmgrName"],
            "hostIp": settings.get("hostIp", ""), "installPath": settings.get("installPath", ""),
        }
        output.append(dict(dims=base, vals={
            "ibmmq_qmgr_status": 0.0,
            "ibmmq_discovery_success": float(returncode == 0),
            "ibmmq_collect_success": 0.0,
        }))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="IBM MQ队列管理器本地监控。参数由EASYOPS_COLLECTOR_*环境变量注入；仅支持Linux执行节点。")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args(argv)
    try:
        print(json.dumps(collect(config()), ensure_ascii=True, allow_nan=False))
    except Exception:
        sys.stdout.write("COLLECT_ERROR: [main] " + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
