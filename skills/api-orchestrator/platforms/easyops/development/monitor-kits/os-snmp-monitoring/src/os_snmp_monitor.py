#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""EasyOps 带内操作系统 SNMP 监控采集器。"""
import json
import os
import re
import subprocess
import sys
import time
import traceback

try:
    text_type = unicode
except NameError:
    text_type = str


def to_text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def to_bytes(value):
    value = to_text(value)
    return value.encode("utf-8", "replace") if isinstance(value, text_type) else value


def write_stdout(value):
    value = to_text(value)
    if sys.version_info[0] < 3:
        sys.stdout.write(to_bytes(value))
    else:
        sys.stdout.write(value)


def format_target(host, port):
    host = to_text(host).strip()
    port = to_text(port).strip()
    if not port:
        return host
    if ":" in host and not host.startswith("["):
        return "[%s]:%s" % (host, port)
    return "%s:%s" % (host, port)


def is_missing_oid_error(error):
    text = to_text(error).lower()
    return ("nosuchname" in text or "no such variable" in text or
            "nosuchobject" in text or "nosuchinstance" in text)


def append_error(errors, error):
    if error and not is_missing_oid_error(error):
        errors.append(to_text(error))


BASE = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
    "hr_system_uptime": "1.3.6.1.2.1.25.1.1.0",
    "hr_processes": "1.3.6.1.2.1.25.1.6.0",
    "hr_memory": "1.3.6.1.2.1.25.2.2.0",
    "mem_total_real": "1.3.6.1.4.1.2021.4.5.0",
    "mem_avail_real": "1.3.6.1.4.1.2021.4.6.0",
    "mem_shared": "1.3.6.1.4.1.2021.4.13.0",
    "mem_buffer": "1.3.6.1.4.1.2021.4.14.0",
    "mem_cached": "1.3.6.1.4.1.2021.4.15.0",
    "mem_total_swap": "1.3.6.1.4.1.2021.4.3.0",
    "mem_avail_swap": "1.3.6.1.4.1.2021.4.4.0",
    "load_1": "1.3.6.1.4.1.2021.10.1.3.1",
    "load_5": "1.3.6.1.4.1.2021.10.1.3.2",
    "load_15": "1.3.6.1.4.1.2021.10.1.3.3",
    "hr_processor_load": "1.3.6.1.2.1.25.3.3.1.2",
}
TABLES = {
    "storage_type": "1.3.6.1.2.1.25.2.3.1.2",
    "storage_unit": "1.3.6.1.2.1.25.2.3.1.4",
    "storage_size": "1.3.6.1.2.1.25.2.3.1.5",
    "storage_used": "1.3.6.1.2.1.25.2.3.1.6",
    "storage_name": "1.3.6.1.2.1.25.2.3.1.3",
    "if_descr": "1.3.6.1.2.1.2.2.1.2",
    "if_speed": "1.3.6.1.2.1.2.2.1.5",
    "if_oper": "1.3.6.1.2.1.2.2.1.8",
    "if_in_octets": "1.3.6.1.2.1.2.2.1.10",
    "if_in_errors": "1.3.6.1.2.1.2.2.1.14",
    "if_out_octets": "1.3.6.1.2.1.2.2.1.16",
    "if_out_errors": "1.3.6.1.2.1.2.2.1.20",
}
STORAGE_FIXED_DISK = "1.3.6.1.2.1.25.2.1.4"
STORAGE_RAM = "1.3.6.1.2.1.25.2.1.2"


def env(name, default=""):
    return os.environ.get("EASYOPS_COLLECTOR_" + name, default)


def env_any(*names):
    for name in names:
        value = env(name, "")
        if value not in (None, "", "null", "None"):
            return value
    return ""


def command_args():
    version = (env_any("snmpVersion", "version") or "2c").lower()
    port = env_any("snmpPort", "port") or "161"
    target = format_target(env("ip", "127.0.0.1"), port)
    if version in ("1", "2c", "2"):
        args = ["-v", "2c" if version == "2" else version, "-c", env("community", "public"), target]
        return [to_bytes(arg) for arg in args]
    security_level = env_any("securityLevel") or "noAuthNoPriv"
    username = env_any("securityName", "username")
    args = ["-v", "3", "-u", username, "-l", security_level]
    auth_protocol = env_any("authProtocol", "auth_protocol").upper()
    priv_protocol = env_any("privProtocol", "priv_protocol").upper()
    if security_level in ("authNoPriv", "authPriv"):
        args.extend(["-a", auth_protocol, "-A", env_any("authKey", "auth_key")])
    if security_level == "authPriv":
        args.extend(["-x", priv_protocol, "-X", env_any("privKey", "priv_key")])
    context_name = env_any("contextName")
    if context_name:
        args.extend(["-n", context_name])
    args.append(target)
    return [to_bytes(arg) for arg in args]


def run_snmp(oid, walk=False):
    cmd = ["snmpwalk" if walk else "snmpget", "-On", "-t", "3", "-r", "1"] + command_args() + [oid]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        output = to_text(stdout).strip()
        if proc.returncode != 0:
            return [], to_text(stderr).strip() or output
        return output.splitlines(), ""
    except Exception:
        return [], u"[run_snmp]\n%s" % to_text(traceback.format_exc())


def parse_value(text):
    text = to_text(text)
    value = text.split(" = ", 1)[-1].strip()
    if value.startswith("STRING:"):
        return value[7:].strip().strip('"')
    if value.startswith("Hex-STRING:"):
        return value[11:].strip()
    if value.startswith("OID:"):
        return value[4:].strip().strip('"')
    if value.startswith("Timeticks:"):
        match = re.search(r"\(([-+]?\d+)\)", value)
        return float(match.group(1)) / 100.0 if match else 0.0
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if match:
        number = float(match.group(0))
        return int(number) if number.is_integer() else number
    return value


def parse_table(lines):
    result = {}
    for line in lines:
        match = re.match(r"^(\.\d+(?:\.\d+)*)\s*=\s*(.*)$", line)
        if not match:
            continue
        suffix = match.group(1).split(".")[-1]
        result[suffix] = parse_value(line)
    return result


def scalar(oid):
    lines, error = run_snmp(oid)
    return (parse_value(lines[0]) if lines else None), error


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def storage_type_oid(value):
    match = re.search(r"(\d+(?:\.\d+)+)", to_text(value))
    return match.group(1) if match else ""


def normalize_partition_name(name, os_type):
    name = to_text(name).strip()
    if os_type == "windows":
        match = re.match(r"(?i)^\s*([a-z]):[\\/]?", name)
        if match:
            return match.group(1).upper() + u":\\"
        return name
    if name != u"/":
        name = name.rstrip(u"/")
    return name or u"/"


def excluded_partitions(os_type):
    value = env_any("fsExcludePaths", "fs_exclude_paths") or "/boot,/boot/efi"
    if to_text(value).lower() in ("null", "none"):
        return set()
    items = re.split(r"[,;]", to_text(value))
    return set(normalize_partition_name(item, os_type) for item in items if to_text(item).strip())


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        write_stdout(u"采集带内 Linux/Windows 操作系统 SNMP 指标；凭证和fsExcludePaths通过 EASYOPS_COLLECTOR_* 参数传入。\n")
        write_stdout(u"fsExcludePaths默认/boot,/boot/efi；仅匹配规范化后的分区名，Linux为挂载点，Windows为盘符。\n")
        return 0
    now = int(time.time() * 1000)
    ip = env("ip", "127.0.0.1")
    tags = {"ip": ip, "osType": "unknown"}
    vals = {}
    errors = []
    descr, error = scalar(BASE["sys_descr"])
    append_error(errors, error)
    uptime, error = scalar(BASE["hr_system_uptime"])
    if uptime is None:
        uptime, error = scalar(BASE["sys_uptime"])
    append_error(errors, error)
    if descr is None:
        detail = to_text(error) or u"snmpget sysDescr returned no value"
        raise RuntimeError(to_bytes(u"[collect] SNMP基础连通性失败（sysDescr不可读）：%s" % detail))
    descr_text = to_text(descr)
    if re.search(r"windows|microsoft", descr_text, re.I):
        tags["osType"] = "windows"
    else:
        load_probe, _ = scalar(BASE["load_5"])
        tags["osType"] = "linux" if load_probe is not None else "unknown"
    vals["os_snmp_available"] = 1
    vals["os_info_sys_descr"] = descr
    vals["os_uptime_seconds"] = numeric(uptime)
    for name, oid in BASE.items():
        if name in ("sys_descr", "sys_uptime", "hr_system_uptime"):
            continue
        value, error = scalar(oid)
        if value is not None:
            vals["os_%s" % name] = numeric(value)
        elif error:
            append_error(errors, error)
    total_real = vals.get("os_mem_total_real", 0)
    avail_real = vals.get("os_mem_avail_real", 0)
    mem_shared = vals.get("os_mem_shared", 0)
    mem_buffer = vals.get("os_mem_buffer", 0)
    mem_cached = vals.get("os_mem_cached", 0)
    total_swap = vals.get("os_mem_total_swap", 0)
    avail_swap = vals.get("os_mem_avail_swap", 0)
    if total_real > 0:
        mem_used = total_real - avail_real - mem_shared - mem_buffer - mem_cached
        mem_used = min(max(mem_used, 0.0), total_real)
        vals["os_mem_used"] = mem_used
        vals["os_mem_pused"] = mem_used * 100.0 / total_real
    if total_swap > 0:
        vals["os_swap_pused"] = (total_swap - avail_swap) * 100.0 / total_swap
    processor_lines, _ = run_snmp(BASE["hr_processor_load"], walk=True)
    processor_loads = [numeric(parse_value(line)) for line in processor_lines if " = " in line]
    if processor_loads:
        vals["os_cpu_util"] = sum(processor_loads) / len(processor_loads)
        vals["os_cpu_count"] = len(processor_loads)
    records = [{"dims": tags, "vals": vals, "timestamp": now}]
    storage = {key: parse_table(run_snmp(oid, walk=True)[0]) for key, oid in TABLES.items() if key.startswith("storage_")}
    excludes = excluded_partitions(tags["osType"])
    memory_storage = None
    for index, size in storage["storage_size"].items():
        unit = numeric(storage["storage_unit"].get(index), 1)
        used = numeric(storage["storage_used"].get(index), 0)
        if size <= 0:
            continue
        storage_type = storage_type_oid(storage["storage_type"].get(index))
        if storage_type == STORAGE_RAM:
            memory_storage = (size, used, unit)
        if storage_type != STORAGE_FIXED_DISK:
            continue
        resource_name = normalize_partition_name(storage["storage_name"].get(index, index), tags["osType"])
        if resource_name in excludes:
            continue
        resource = dict(tags, resourceType="filesystem", resourceIndex=index, resourceName=resource_name)
        records.append({"dims": resource, "vals": {"os_fs_total_bytes": size * unit, "os_fs_used_bytes": used * unit, "os_fs_pused": used * 100.0 / size}, "timestamp": now})
    if total_real <= 0 and memory_storage:
        size, used, unit = memory_storage
        vals["os_mem_total_real"] = size * unit / 1024.0
        vals["os_mem_used"] = used * unit / 1024.0
        vals["os_mem_pused"] = used * 100.0 / size
    interfaces = {key: parse_table(run_snmp(oid, walk=True)[0]) for key, oid in TABLES.items() if key.startswith("if_")}
    for index, name in interfaces["if_descr"].items():
        resource = dict(tags, resourceType="interface", resourceIndex=index, resourceName=to_text(name))
        records.append({"dims": resource, "vals": {"os_if_speed_bps": numeric(interfaces["if_speed"].get(index)), "os_if_oper_status": numeric(interfaces["if_oper"].get(index)), "os_if_in_octets": numeric(interfaces["if_in_octets"].get(index)), "os_if_out_octets": numeric(interfaces["if_out_octets"].get(index)), "os_if_in_errors": numeric(interfaces["if_in_errors"].get(index)), "os_if_out_errors": numeric(interfaces["if_out_errors"].get(index))}, "timestamp": now})
    if errors:
        records[0]["vals"]["os_snmp_error"] = u"; ".join(to_text(item) for item in errors[:3])
    write_stdout(json.dumps(records))
    write_stdout("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        write_stdout(u"COLLECT_ERROR:\n")
        write_stdout(traceback.format_exc())
        sys.stdout.flush()
        sys.exit(0)
