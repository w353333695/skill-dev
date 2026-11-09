#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用存储设备 SNMP 监控采集器，兼容 Python 2.7/3.x。"""
import json
import logging
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

BASE = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_objectid": "1.3.6.1.2.1.1.2.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
}
TABLES = {
    "storage_type": "1.3.6.1.2.1.25.2.3.1.2",
    "storage_name": "1.3.6.1.2.1.25.2.3.1.3",
    "storage_unit": "1.3.6.1.2.1.25.2.3.1.4",
    "storage_size": "1.3.6.1.2.1.25.2.3.1.5",
    "storage_used": "1.3.6.1.2.1.25.2.3.1.6",
}
PROFILES = {
    "huawei_oceanstor": {
        "roots": ["1.3.6.1.4.1.34774"],
        "capacity_total": "1.3.6.1.4.1.34774.4.1.1.5.0",
        "capacity_used": "1.3.6.1.4.1.34774.4.1.1.4.0",
        "device_status": "1.3.6.1.4.1.34774.4.1.1.3.0",
        "version": "1.3.6.1.4.1.34774.4.1.1.6.0",
        "discoveries": {
            "disk": "1.3.6.1.4.1.34774.4.1.23.5.1.1.1",
            "controller": "1.3.6.1.4.1.34774.4.1.23.5.2.1.1",
            "pool": "1.3.6.1.4.1.34774.4.1.23.4.2.1.2",
            "lun": "1.3.6.1.4.1.34774.4.1.19.9.4.1.2",
        },
    },
    "netapp": {
        "roots": ["1.3.6.1.4.1.789"],
        "failed_disks": "1.3.6.1.4.1.789.1.6.4.7.0",
        "failed_disks_message": "1.3.6.1.4.1.789.1.6.4.10.0",
        "version": "1.3.6.1.4.1.789.1.1.2.0",
    },
    "xsky": {
        "roots": ["1.3.6.1.4.1.48871"],
        "capacity_total": "1.3.6.1.4.1.48871.1.1.1.1.0",
        "capacity_used": "1.3.6.1.4.1.48871.1.1.1.2.0",
    },
    "emc_dd2500": {"roots": ["1.3.6.1.4.1.19746"]},
    "dell_idrac": {"roots": ["1.3.6.1.4.1.674.10892"]},
}
LOG = logging.getLogger("storage_snmp_monitor")


def text(value):
    if value is None:
        return u""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, text_type) else text_type(value)


def env(name, default=""):
    return os.environ.get("EASYOPS_COLLECTOR_" + name, default)


def target():
    host = text(env("ip", "127.0.0.1")).strip()
    port = text(env("snmpPort", env("port", "161"))).strip() or "161"
    if ":" in host and not host.startswith("["):
        return "[%s]:%s" % (host, port)
    return "%s:%s" % (host, port)


def command_args():
    version = text(env("snmpVersion", env("version", "2c"))).lower()
    if version == "2":
        version = "2c"
    args = ["-v", version]
    if version in ("1", "2c"):
        args += ["-c", env("community", "public")]
    else:
        level = env("securityLevel", "noAuthNoPriv")
        args += ["-u", env("securityName", env("username", "")), "-l", level]
        if level in ("authNoPriv", "authPriv"):
            args += ["-a", env("authProtocol", "SHA"), "-A", env("authKey", "")]
        if level == "authPriv":
            args += ["-x", env("privProtocol", "AES"), "-X", env("privKey", "")]
        if env("contextName", ""):
            args += ["-n", env("contextName", "")]
    return args + [target()]


def run(oid, walk=False):
    command = ["snmpwalk" if walk else "snmpget", "-On", "-t", "3", "-r", "1"] + command_args() + [oid]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        output = text(out).strip()
        if proc.returncode != 0:
            return [], text(err).strip() or output
        return output.splitlines(), ""
    except Exception:
        return [], "[run_snmp]\n%s" % traceback.format_exc()


def parse_value(line):
    value = text(line).split(" = ", 1)[-1].strip()
    value = re.sub(r"^(STRING|INTEGER|Counter32|Counter64|Gauge32|Unsigned32|OID|Timeticks|Hex-STRING|Opaque):\s*", "", value, flags=re.I)
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if match:
        number = float(match.group(0))
        return int(number) if number.is_integer() else number
    return value


def parse_table(lines):
    values = {}
    for line in lines:
        match = re.match(r"^\.(\d+(?:\.\d+)*)\s*=", text(line))
        if match:
            index = match.group(1).split(".")[-1]
            values[index] = parse_value(line)
    return values


def scalar(oid):
    lines, error = run(oid)
    return (parse_value(lines[0]) if lines else None), error


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def vendor_for(object_id, descr):
    haystack = (text(object_id) + " " + text(descr)).lower()
    for name, profile in PROFILES.items():
        if any(text(root) in text(object_id) for root in profile.get("roots", [])):
            return name
    checks = (("huawei", "huawei_oceanstor"), ("oceanstor", "huawei_oceanstor"), ("netapp", "netapp"), ("xsky", "xsky"), ("data domain", "emc_dd2500"), ("idrac", "dell_idrac"), ("dell", "dell_idrac"))
    for marker, name in checks:
        if marker in haystack:
            return name
    return "generic"


def add_record(records, tags, values, resource_type="", resource_index="", resource_name=""):
    dims = dict(tags)
    if resource_type:
        dims.update({"resourceType": resource_type, "resourceIndex": text(resource_index), "resourceName": text(resource_name or resource_index)})
    records.append({"dims": dims, "vals": values, "timestamp": int(time.time() * 1000)})


def collect():
    errors = []
    descr, error = scalar(BASE["sys_descr"])
    object_id, object_error = scalar(BASE["sys_objectid"])
    if descr is None and object_id is None:
        raise RuntimeError("[collect] SNMP基础连通性失败（sysDescr/sysObjectID不可读）：%s" % (error or object_error or "no response"))
    vendor = vendor_for(object_id, descr)
    tags = {"ip": env("ip", "127.0.0.1"), "vendor": vendor}
    records = []
    base_values = {"storage_snmp_available": 1, "storage_info_sys_descr": text(descr), "storage_info_sys_objectid": text(object_id)}
    uptime, uptime_error = scalar(BASE["sys_uptime"])
    if uptime is not None:
        base_values["storage_uptime_ticks"] = number(uptime)
    if uptime_error:
        errors.append(uptime_error)
    add_record(records, tags, base_values)

    storage = {}
    for name, oid in TABLES.items():
        lines, table_error = run(oid, walk=True)
        storage[name] = parse_table(lines)
        if table_error and "nosuch" not in table_error.lower() and "no such" not in table_error.lower():
            errors.append(table_error)
    indexes = sorted(set(storage["storage_size"]) | set(storage["storage_used"]))
    for index in indexes:
        size = number(storage["storage_size"].get(index))
        used = number(storage["storage_used"].get(index))
        unit = number(storage["storage_unit"].get(index)) or 1
        if size is None or used is None or size <= 0:
            continue
        name = storage["storage_name"].get(index, index)
        kind = "memory" if text(storage["storage_type"].get(index)).endswith(".2") else "filesystem"
        add_record(records, tags, {"storage_capacity_bytes": size * unit, "storage_used_bytes": used * unit, "storage_used_percent": used * 100.0 / size}, kind, index, name)

    profile = PROFILES.get(vendor, {})
    for metric, oid_key in (("storage_capacity_bytes", "capacity_total"), ("storage_used_bytes", "capacity_used"), ("storage_status", "device_status"), ("storage_info_version", "version"), ("storage_failed_disk_count", "failed_disks")):
        oid = profile.get(oid_key)
        if not oid:
            continue
        value, metric_error = scalar(oid)
        if value is not None:
            parsed = number(value) if metric not in ("storage_info_version",) else text(value)
            add_record(records, tags, {metric: parsed}, "array", "0", vendor)
        elif metric_error and "nosuch" not in metric_error.lower() and "no such" not in metric_error.lower():
            errors.append(metric_error)
    for resource_type, oid in profile.get("discoveries", {}).items():
        lines, discovery_error = run(oid, walk=True)
        if discovery_error and "nosuch" not in discovery_error.lower() and "no such" not in discovery_error.lower():
            errors.append(discovery_error)
        for index, value in parse_table(lines).items():
            add_record(records, tags, {"storage_resource_present": 1, "storage_resource_value": text(value)}, resource_type, index, value)
    if errors:
        records[0]["vals"]["storage_snmp_error"] = "; ".join(text(item) for item in errors[:3])
    return records


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("采集存储设备 SNMP 指标，自动识别 Huawei OceanStor、NetApp、XSKY、EMC Data Domain、Dell iDRAC，并以 HOST-RESOURCES-MIB 作为通用兜底。")
        return 0
    print(json.dumps(collect(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stdout.write("COLLECT_ERROR:\n")
        sys.stdout.write(traceback.format_exc())
        sys.stdout.flush()
        sys.exit(0)
