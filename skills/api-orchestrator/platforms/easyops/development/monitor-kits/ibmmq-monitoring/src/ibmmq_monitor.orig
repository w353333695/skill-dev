#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""IBM MQ 本地队列管理器监控脚本，参数由 EASYOPS_COLLECTOR_* 环境变量注入。"""
import argparse
import csv
import json
import logging
import locale
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback

VERSION = "0.4.4"
QMGR_COMMAND = "DISPLAY QMGR DEADQ"
STATUS_COMMAND = "DISPLAY QSTATUS(*) CURDEPTH MSGAGE IPPROCS OPPROCS"
QUEUE_COMMAND = "DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH USAGE GET PUT"
CHANNEL_COMMAND = "DISPLAY CHSTATUS(*) CHANNEL CHLTYPE STATUS MSGS BYTSRCVD BYTSSENT"
LISTENER_COMMAND = "DISPLAY LSSTATUS(*) LISTENER PORT STATUS"
LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
LOGGER = logging.getLogger("ibmmq_monitor")
EXPECTED_METRICS = (
    "ibmmq_collect_success", "ibmmq_discovery_success", "ibmmq_qmgr_count", "ibmmq_qmgr_status",
    "ibmmq_sc_command_success", "ibmmq_queue_total", "ibmmq_queue_depth_total", "ibmmq_queue_max_depth",
    "ibmmq_queue_max_usage_percent", "ibmmq_queue_current_depth", "ibmmq_queue_max_depth_config",
    "ibmmq_queue_usage_percent", "ibmmq_queue_oldest_message_age_seconds", "ibmmq_queue_input_handles",
    "ibmmq_queue_output_handles", "ibmmq_queue_get_enabled", "ibmmq_queue_put_enabled",
    "ibmmq_transmission_queue_current_depth", "ibmmq_transmission_queue_max_depth",
    "ibmmq_transmission_queue_usage_percent", "ibmmq_transmission_queue_get_enabled",
    "ibmmq_transmission_queue_put_enabled", "ibmmq_dlq_configured", "ibmmq_dlq_current_depth",
    "ibmmq_dlq_max_depth", "ibmmq_dlq_usage_percent", "ibmmq_dlq_get_enabled", "ibmmq_dlq_put_enabled",
    "ibmmq_listener_total", "ibmmq_listener_running_count", "ibmmq_listener_status",
    "ibmmq_channel_total", "ibmmq_channel_running_count", "ibmmq_channel_retrying_count",
    "ibmmq_channel_status", "ibmmq_channel_messages", "ibmmq_channel_bytes",
    "ibmmq_channel_bytes_received", "ibmmq_channel_bytes_sent", "ibmmq_process_alive",
    "ibmmq_process_count", "ibmmq_process_cpu_percent", "ibmmq_process_memory_bytes",
    "ibmmq_process_thread_count", "ibmmq_process_fd_count",
)


def setup_logging(level_name):
    level_name = level_name.upper() if level_name else "ERROR"
    level = getattr(logging, level_name, logging.ERROR)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
    LOGGER.handlers = []
    formatter = logging.Formatter("%(asctime)s %(levelname)s IBMMQ %(message)s")
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    LOGGER.addHandler(stderr_handler)
    if level_name == "DEBUG":
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(formatter)
        LOGGER.addHandler(stdout_handler)


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
        log_level = env("logLevel", "ERROR").upper()
    except ValueError:
        raise ValueError("[config] commandTimeout必须为整数，sampleInterval必须为数字，logLevel必须合法")
    if timeout < 1 or timeout > 60:
        raise ValueError("[config] commandTimeout必须在1到60之间")
    if interval < 0.05 or interval > 2:
        raise ValueError("[config] sampleInterval必须在0.05到2之间")
    if log_level not in LOG_LEVELS:
        raise ValueError("[config] logLevel只支持DEBUG/INFO/WARN/ERROR")
    settings = {
        "ibmmqInstanceId": env("instanceId"),
        "hostIp": env("hostIp"),
        "installPath": env("installPath"),
        "queueFilter": env("queueFilter", ".*"),
        "includeSystemQueues": env("includeSystemQueues", "false").lower() in ("1", "true", "yes"),
        "processMonitor": env("processMonitor", "true").lower() in ("1", "true", "yes"),
        "logLevel": log_level,
        "timeout": timeout,
        "interval": interval,
    }
    LOGGER.debug(
        "[config] version=%s platform=%s installPath=%s queueFilter=%s includeSystemQueues=%s "
        "processMonitor=%s logLevel=%s timeout=%s interval=%s",
        VERSION, os.name, settings["installPath"], settings["queueFilter"],
        settings["includeSystemQueues"], settings["processMonitor"], settings["logLevel"],
        settings["timeout"], settings["interval"],
    )
    return settings


def decode(value):
    if isinstance(value, bytes):
        preferred = locale.getpreferredencoding(False) or "utf-8"
        for encoding in ("utf-8", preferred, "cp936", "gbk"):
            try:
                return value.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                pass
        return value.decode("utf-8", "replace")
    return value or ""


def is_windows():
    return os.name == "nt"


def execute(args, settings, input_text=None):
    process = None
    expired = [False]
    LOGGER.debug("[execute] start args=%s timeout=%s input=<%s>", repr(args), settings["timeout"], input_text or "")
    def stop_process():
        if process is not None and process.poll() is None:
            expired[0] = True
            try:
                if is_windows():
                    subprocess.call(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                elif hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (OSError, subprocess.CalledProcessError):
                pass

    popen_kwargs = {}
    if not is_windows() and "start_new_session" in subprocess.Popen.__init__.__code__.co_varnames:
        popen_kwargs = {"start_new_session": True}
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs
        )
        timer = threading.Timer(settings["timeout"], stop_process)
        timer.daemon = True
        timer.start()
        stdin_text = None if input_text is None else input_text.encode("utf-8")
        stdout, stderr = process.communicate(stdin_text)
        timer.cancel()
        text = decode(stdout) + "\n" + decode(stderr)
        if expired[0]:
            LOGGER.error("[execute] timeout args=%s timeout=%s output=<%s>", repr(args), settings["timeout"], text.strip())
            return 124, text + "\nAMQ9999E: command timeout"
        LOGGER.debug("[execute] finish args=%s returncode=%s output=<%s>", repr(args), process.returncode or 0, text.strip())
        return process.returncode or 0, text
    except Exception:
        LOGGER.exception("[execute] failed args=%s", repr(args))
        raise
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass


def find_mq_bin(settings):
    install_path = settings.get("installPath", "")
    command = "dspmq.exe" if is_windows() else "dspmq"

    def candidate_bin(path):
        if not path or path.startswith("$."):
            return None
        if os.path.basename(path).lower() == command:
            return os.path.dirname(path)
        return path if os.path.basename(path).lower() == "bin" else path.rstrip("\\/") + os.sep + "bin"

    def usable(path):
        return bool(path) and os.path.isfile(os.path.join(path, command))

    candidates = []
    installation_path = os.environ.get("MQ_INSTALLATION_PATH")
    if installation_path:
        candidates.append(os.path.join(installation_path, "bin"))
    if install_path and not install_path.startswith("$."):
        candidates.append(candidate_bin(install_path))
    if is_windows():
        candidates.extend([
            r"C:\Program Files\IBM\MQ\bin",
            r"C:\Program Files (x86)\IBM\MQ\bin",
        ])
    else:
        candidates.extend(["/opt/mqm/bin", "/opt/ibm/mq/bin", "/usr/mqm/bin"])
    path_env = os.environ.get("PATH", "")
    for name in path_env.split(os.pathsep):
        if name:
            candidates.append(name)
    for candidate in candidates:
        candidate_usable = usable(candidate)
        LOGGER.debug("[find_mq_bin] candidate=%s command=%s usable=%s", candidate, command, candidate_usable)
        if candidate_usable:
            LOGGER.debug("[find_mq_bin] selected=%s", candidate)
            return candidate
    LOGGER.error("[find_mq_bin] not found candidates=%s command=%s", repr(candidates), command)
    return ""


def mq_command(mq_bin, name):
    filename = name + (".exe" if is_windows() else "")
    path = os.path.join(mq_bin, filename)
    return path.replace("/", "\\") if is_windows() else path


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
    args = [mq_command(mq_bin, "dspmq"), "-o", "status"]
    returncode, output = execute(args, settings)
    qmgrs = []
    for line in output.splitlines():
        attrs = parse_attributes(line)
        name = attrs.get("QMNAME")
        if name and not any(row["qmgrName"] == name for row in qmgrs):
            qmgrs.append({"qmgrName": name, "status": attrs.get("STATUS", ""), "dspmqReturnCode": returncode})
    if not qmgrs and returncode != 0:
        LOGGER.error("[discover_qmgrs] failed returncode=%s output=<%s>", returncode, output.strip())
        raise RuntimeError("[discover_qmgrs] dspmq执行失败: " + output.strip()[-500:])
    LOGGER.debug("[discover_qmgrs] count=%d qmgrs=%s", len(qmgrs), json.dumps(qmgrs))
    return qmgrs, returncode


def run_mqsc(mq_bin, qmgr_name, settings):
    newline = "\r\n" if is_windows() else "\n"
    commands = newline.join([
        QMGR_COMMAND, QUEUE_COMMAND, STATUS_COMMAND, CHANNEL_COMMAND, LISTENER_COMMAND, "EXIT"
    ]) + newline
    args = [mq_command(mq_bin, "runmqsc"), qmgr_name]
    returncode, output = execute(args, settings, commands)
    return returncode, output


def parse_mqsc(output, settings):
    queues = {}
    channels = []
    listeners = []
    dead_queue_name = ""
    for line in output.splitlines():
        attrs = parse_attributes(line)
        if not attrs:
            continue
        LOGGER.debug("[parse_mqsc] line=<%s> attrs=%s", line, json.dumps(attrs, sort_keys=True))
        if attrs.get("QMNAME") and attrs.get("DEADQ"):
            dead_queue_name = attrs["DEADQ"]
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
            if "USAGE" in attrs:
                row["usage"] = attrs["USAGE"].upper()
            if "GET" in attrs:
                row["getEnabled"] = attrs["GET"].upper() == "ENABLED"
            if "PUT" in attrs:
                row["putEnabled"] = attrs["PUT"].upper() == "ENABLED"
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
                "bytesReceived": numeric(attrs.get("BYTSRCVD", 0)),
                "bytesSent": numeric(attrs.get("BYTSSENT", 0)),
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
    LOGGER.debug(
        "[parse_mqsc] discovered queues=%d channels=%d listeners=%d deadQueue=%s",
        len(queues), len(channels), len(listeners), dead_queue_name or "<unset>",
    )
    for name in sorted(queues):
        is_dead_queue = bool(dead_queue_name) and name.upper() == dead_queue_name.upper()
        if not settings["includeSystemQueues"] and name.upper().startswith("SYSTEM.") and not is_dead_queue:
            LOGGER.debug("[parse_mqsc] exclude queue=%s reason=SYSTEM_PREFIX", name)
            continue
        if not pattern.search(name):
            LOGGER.debug("[parse_mqsc] exclude queue=%s reason=QUEUE_FILTER pattern=%s", name, settings["queueFilter"])
            continue
        row = queues[name]
        row["queueName"] = name
        row["isDeadQueue"] = is_dead_queue
        row["isTransmissionQueue"] = row.get("usage") == "XMITQ"
        selected_queues.append(row)
        LOGGER.debug(
            "[parse_mqsc] select queue=%s deadQueue=%s transmissionQueue=%s fields=%s",
            name, is_dead_queue, row["isTransmissionQueue"], json.dumps(row, sort_keys=True),
        )
    LOGGER.debug("[parse_mqsc] selected queues=%d", len(selected_queues))
    return selected_queues, channels, listeners, dead_queue_name


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



def json_objects(text):
    if not text.strip():
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


def run_powershell(command, settings):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = os.path.join(
        system_root,
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if not os.path.isfile(powershell):
        return 1, ""
    return execute(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        settings,
    )


def wmic_process_sample(settings):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    wmic = os.path.join(system_root, "System32", "wbem", "WMIC.exe")
    if not os.path.isfile(wmic):
        return []
    returncode, output = execute(
        [wmic, "PATH", "Win32_Process", "GET", "ProcessId,ExecutablePath,CommandLine", "/FORMAT:CSV"],
        settings,
    )
    if returncode != 0:
        return []
    headers = None
    rows = []
    for values in csv.reader(output.splitlines()):
        if not values:
            continue
        if headers is None and "CommandLine" in values:
            headers = [value.strip().lower() for value in values]
            continue
        if headers:
            rows.append(dict(zip(headers, values)))
    return rows


def windows_process_sample(settings):
    process_command = (
        "Get-CimInstance -ClassName Win32_Process |"
        " Select-Object ProcessId,ExecutablePath,CommandLine |"
        " ConvertTo-Json -Compress"
    )
    perf_command = (
        "Get-CimInstance -ClassName Win32_PerfFormattedData_PerfProc_Process |"
        " Select-Object IDProcess,PercentProcessorTime,ThreadCount,HandleCount,WorkingSetPrivate |"
        " ConvertTo-Json -Compress"
    )
    process_returncode, process_output = run_powershell(process_command, settings)
    if process_returncode != 0:
        process_rows = [
            {
                "ProcessId": row.get("processid", ""),
                "ExecutablePath": row.get("executablepath", ""),
                "CommandLine": row.get("commandline", ""),
            }
            for row in wmic_process_sample(settings)
        ]
    else:
        process_rows = json_objects(process_output)

    perf_by_pid = {}
    perf_returncode, perf_output = run_powershell(perf_command, settings)
    if perf_returncode == 0:
        for perf in json_objects(perf_output):
            perf_by_pid[str(perf.get("IDProcess", ""))] = perf

    rows = []
    for item in process_rows:
        pid_text = str(item.get("ProcessId", "")).strip()
        if not pid_text:
            continue
        cmdline = str(item.get("CommandLine") or item.get("ExecutablePath") or "")
        executable = str(item.get("ExecutablePath") or "")
        if not executable and cmdline:
            executable = cmdline.split()[0]
        perf = perf_by_pid.get(pid_text, {})
        rows.append({
            "pid": float(pid_text),
            "executable": executable,
            "cmdline": cmdline,
            "userTicks": 0.0,
            "threads": numeric(perf.get("ThreadCount", 0)),
            "memoryBytes": numeric(perf.get("WorkingSetPrivate", 0)),
            "fdCount": numeric(perf.get("HandleCount", 0)),
            "cpuPercent": numeric(perf.get("PercentProcessorTime", 0)),
        })
    return rows


def ibm_mq_process(row, qmgr_name):
    executable = row["executable"].replace("\\", "/").lower()
    basename = os.path.basename(executable)
    if basename.endswith(".exe"):
        basename = basename[:-4]
    cmdline = row["cmdline"].lower()
    mq_path = any(part in executable for part in ("/opt/mqm/", "/opt/ibm/mq/", "/usr/mqm/", "/ibm/mq/"))
    core_names = ("runmqlsr", "amqmsrv", "amqzxma0", "amqzlaa0", "amqzlsa0", "amqrmppa", "amqzmuc0")
    if qmgr_name and qmgr_name.lower() not in cmdline:
        return False
    return basename in core_names or (mq_path and basename.startswith("amq"))


def collect_processes(qmgr_name, settings):
    LOGGER.debug("[collect_processes] start qmgr=%s platform=%s", qmgr_name, os.name)
    if is_windows():
        rows = [row for row in windows_process_sample(settings) if ibm_mq_process(row, qmgr_name)]
        grouped = {}
        for row in rows:
            key = row["cmdline"][:512]
            if key not in grouped:
                grouped[key] = {"cmdline": key, "alive": 0.0, "count": 0.0, "cpu": 0.0,
                                "memory": 0.0, "threads": 0.0, "fds": 0.0}
            grouped[key]["alive"] = 1.0
            grouped[key]["count"] += 1.0
            grouped[key]["cpu"] += max(0.0, row["cpuPercent"])
            grouped[key]["memory"] += row["memoryBytes"]
            grouped[key]["threads"] += row["threads"]
            grouped[key]["fds"] += row["fdCount"]
        LOGGER.debug("[collect_processes] qmgr=%s matched=%d groups=%d", qmgr_name, len(rows), len(grouped))
        return grouped

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
    LOGGER.debug("[collect_processes] qmgr=%s matched=%d groups=%d", qmgr_name, len(first), len(grouped))
    return grouped


def collect_qmgr(qmgr, mq_bin, settings):
    LOGGER.debug("[collect_qmgr] start qmgr=%s status=%s mqBin=%s", qmgr["qmgrName"], qmgr.get("status", ""), mq_bin)
    base = {"ibmmqInstanceId": settings["ibmmqInstanceId"], "qmgrName": qmgr["qmgrName"], "hostIp": settings.get("hostIp", ""), "installPath": settings.get("installPath", "") or os.path.dirname(mq_bin)}
    values = {
        "ibmmq_qmgr_status": 1.0 if qmgr.get("status", "").upper() == "RUNNING" else 0.0,
        "ibmmq_discovery_success": 1.0,
    }
    rows = [dict(dims=dict(base), vals=dict(values))]
    returncode, output = run_mqsc(mq_bin, qmgr["qmgrName"], settings)
    command_success = float(returncode == 0 and "COMMAND ACCEPTED" in output.upper())
    queues, channels, listeners, dead_queue_name = parse_mqsc(output, settings)
    if command_success != 1.0:
        LOGGER.error("[collect_qmgr] runmqsc failed qmgr=%s returncode=%s output=<%s>", qmgr["qmgrName"], returncode, output.strip())
    LOGGER.debug(
        "[collect_qmgr] parsed qmgr=%s queues=%d transmissionQueues=%d deadQueues=%d channels=%d "
        "listeners=%d deadQueueConfig=%s commandSuccess=%s",
        qmgr["qmgrName"], len(queues), sum(1 for row in queues if row.get("isTransmissionQueue")),
        sum(1 for row in queues if row.get("isDeadQueue")), len(channels), len(listeners),
        dead_queue_name or "<unset>", command_success,
    )
    summary = dict(base)
    summary_values = {
        "ibmmq_collect_success": 1.0,
        "ibmmq_sc_command_success": command_success,
        "ibmmq_queue_total": float(len(queues)),
        "ibmmq_queue_depth_total": float(sum(row.get("currentDepth", 0.0) for row in queues)),
        "ibmmq_queue_max_depth": max([row.get("maxDepth", 0.0) for row in queues] or [0.0]),
        "ibmmq_queue_max_usage_percent": max([float(row.get("currentDepth", 0.0)) / row.get("maxDepth", 1.0) * 100.0 for row in queues] or [0.0]),
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
            "ibmmq_queue_usage_percent": float(row.get("currentDepth", 0.0)) / row.get("maxDepth", 1.0) * 100.0,
        }
        if "oldestMessageAge" in row:
            vals["ibmmq_queue_oldest_message_age_seconds"] = row["oldestMessageAge"]
        if "inputHandles" in row:
            vals["ibmmq_queue_input_handles"] = row["inputHandles"]
        if "outputHandles" in row:
            vals["ibmmq_queue_output_handles"] = row["outputHandles"]
        if "getEnabled" in row:
            vals["ibmmq_queue_get_enabled"] = 1.0 if row["getEnabled"] else 0.0
        if "putEnabled" in row:
            vals["ibmmq_queue_put_enabled"] = 1.0 if row["putEnabled"] else 0.0
        if row.get("isTransmissionQueue"):
            vals.update({
                "ibmmq_transmission_queue_current_depth": row.get("currentDepth", 0.0),
                "ibmmq_transmission_queue_max_depth": row.get("maxDepth", 0.0),
                "ibmmq_transmission_queue_usage_percent": float(row.get("currentDepth", 0.0)) / row.get("maxDepth", 1.0) * 100.0,
            })
            if "getEnabled" in row:
                vals["ibmmq_transmission_queue_get_enabled"] = 1.0 if row["getEnabled"] else 0.0
            if "putEnabled" in row:
                vals["ibmmq_transmission_queue_put_enabled"] = 1.0 if row["putEnabled"] else 0.0
        if row.get("isDeadQueue"):
            vals.update({
                "ibmmq_dlq_configured": 1.0,
                "ibmmq_dlq_current_depth": row.get("currentDepth", 0.0),
                "ibmmq_dlq_max_depth": row.get("maxDepth", 0.0),
                "ibmmq_dlq_usage_percent": float(row.get("currentDepth", 0.0)) / row.get("maxDepth", 1.0) * 100.0,
            })
            if "getEnabled" in row:
                vals["ibmmq_dlq_get_enabled"] = 1.0 if row["getEnabled"] else 0.0
            if "putEnabled" in row:
                vals["ibmmq_dlq_put_enabled"] = 1.0 if row["putEnabled"] else 0.0
        rows.append(dict(dims=dims, vals=vals))
    for row in channels:
        channel_values = {
            "ibmmq_channel_status": normalize_status(row["status"]),
            "ibmmq_channel_messages": row["messages"],
        }
        if "bytesReceived" in row:
            channel_values["ibmmq_channel_bytes_received"] = row["bytesReceived"]
        if "bytesSent" in row:
            channel_values["ibmmq_channel_bytes_sent"] = row["bytesSent"]
        if row.get("bytes"):
            channel_values["ibmmq_channel_bytes"] = row["bytes"]
        LOGGER.debug(
            "[collect_qmgr] channel=%s type=%s status=%s messages=%s bytes=%s bytesReceived=%s bytesSent=%s",
            row["channelName"], row["channelType"], row["status"], row["messages"], row["bytes"],
            row["bytesReceived"], row["bytesSent"],
        )
        rows.append(dict(dims=dict(base, channelName=row["channelName"], channelType=row["channelType"]), vals=channel_values))
    for row in listeners:
        rows.append(dict(dims=dict(base, listenerName=row["listenerName"], port=row["port"]), vals={
            "ibmmq_listener_status": normalize_status(row["status"]),
        }))
    if settings["processMonitor"]:
        process_rows = collect_processes(qmgr["qmgrName"], settings)
        for row in process_rows.values():
            rows.append(dict(dims=dict(base, cmdline=row["cmdline"]), vals={
                "ibmmq_process_alive": row["alive"],
                "ibmmq_process_count": row["count"],
                "ibmmq_process_cpu_percent": row["cpu"],
                "ibmmq_process_memory_bytes": row["memory"],
                "ibmmq_process_thread_count": row["threads"],
                "ibmmq_process_fd_count": row["fds"],
            }))
    else:
        LOGGER.debug("[collect_qmgr] process metrics skipped qmgr=%s reason=processMonitorDisabled", qmgr["qmgrName"])
    LOGGER.debug("[collect_qmgr] finish qmgr=%s rows=%d metrics=%s", qmgr["qmgrName"], len(rows), json.dumps(sorted(set(key for row in rows for key in row["vals"]))))
    return rows


def collect(settings):
    mq_bin = find_mq_bin(settings)
    if not mq_bin:
        raise RuntimeError("[collect] 未找到可执行dspmq；请确认installPath、MQ_INSTALLATION_PATH、PATH或常见IBM MQ安装目录可用")
    qmgrs, returncode = discover_qmgrs(mq_bin, settings)
    output = []
    for qmgr in qmgrs:
        output.extend(collect_qmgr(qmgr, mq_bin, settings))
    target_found = len(qmgrs) > 0
    output.append(dict(dims={"ibmmqInstanceId": settings["ibmmqInstanceId"]}, vals={
        "ibmmq_qmgr_count": float(len(qmgrs)),
        "ibmmq_collect_success": float(target_found),
    }))
    if not qmgrs:
        LOGGER.error("[collect] queue manager discovery returned empty returncode=%s", returncode)
        base = {
            "ibmmqInstanceId": settings["ibmmqInstanceId"], "qmgrName": "",
            "hostIp": settings.get("hostIp", ""), "installPath": settings.get("installPath", ""),
        }
        output.append(dict(dims=base, vals={
            "ibmmq_qmgr_status": 0.0,
            "ibmmq_discovery_success": float(returncode == 0),
            "ibmmq_collect_success": 0.0,
        }))
    emitted_metrics = set(key for row in output for key in row["vals"])
    missing_metrics = [key for key in EXPECTED_METRICS if key not in emitted_metrics]
    if missing_metrics:
        LOGGER.error("[collect] metric gaps count=%d metrics=%s", len(missing_metrics), ",".join(missing_metrics))
    else:
        LOGGER.debug("[collect] all %d expected metrics emitted", len(EXPECTED_METRICS))
    LOGGER.debug("[collect] finish rows=%d metrics=%s payload=%s", len(output), ",".join(sorted(emitted_metrics)), json.dumps(output))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "IBM MQ队列管理器本地监控，同时支持Linux和Windows执行节点。"
            "参数由EASYOPS_COLLECTOR_*环境变量注入。"
        ),
        epilog=(
            "示例：\n"
            "  EASYOPS_COLLECTOR_instanceId=i1 EASYOPS_COLLECTOR_installPath=/opt/mqm %(prog)s\n"
            "  EASYOPS_COLLECTOR_installPath=/opt/mqm %(prog)s\n"
            "  EASYOPS_COLLECTOR_installPath='C:\\Program Files\\IBM\\MQ' %(prog)s\n\n"
            "Linux默认探测/opt/mqm/bin、/opt/ibm/mq/bin、/usr/mqm/bin；Windows默认探测Program Files下IBM MQ bin目录。"
        ),
    )
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args(argv)
    try:
        setup_logging(env("logLevel", "ERROR"))
        sys.stdout.write(json.dumps(collect(config()), ensure_ascii=True, allow_nan=False) + "\n")
    except Exception:
        LOGGER.exception("[main] collection failed")
        sys.stdout.write("COLLECT_ERROR: [main] " + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
