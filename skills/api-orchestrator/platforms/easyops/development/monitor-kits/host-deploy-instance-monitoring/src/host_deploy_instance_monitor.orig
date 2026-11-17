#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""HOST 本地部署实例进程与端口监控脚本，参数由 EASYOPS_COLLECTOR_* 注入。"""
import argparse
import calendar
import csv
import errno
import hashlib
import hmac
import io
import json
import os
import re
import stat
import subprocess
import sys
import time
import traceback

if sys.version_info[0] >= 3:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
else:
    from urllib import urlencode
    from urllib2 import Request, urlopen

VERSION = "0.1.16"
IS_WINDOWS = os.name == "nt"
OBJECT_ID = "ARTIFACT_INST@ONEMODEL"
OPENAPI_PATH = "/cmdbservice/v3/object/ARTIFACT_INST@ONEMODEL/instance/_search"
OPENAPI_HOST = "openapi.easyops-only.com"
PROCESS_METRIC_KEYS = [
    "deploy_instance_process_alive", "deploy_instance_process_count",
    "deploy_instance_matching_process_count", "deploy_instance_zombie_process_count",
    "deploy_instance_thread_count", "deploy_instance_process_start_timestamp",
    "deploy_instance_process_uptime_seconds", "deploy_instance_process_memory_bytes",
    "deploy_instance_process_memory_percent", "deploy_instance_process_cpu_percent",
    "deploy_instance_process_fd_count", "deploy_instance_process_fd_usage_percent",
]
PORT_METRIC_KEYS = [
    "deploy_instance_expected_port_count", "deploy_instance_listening_port_count",
    "deploy_instance_port_missing_count", "deploy_instance_port_listen",
    "deploy_instance_port_listen_ratio_pct", "deploy_instance_config_valid",
]
TARGET_METRIC_KEYS = [
    "deploy_instance_collect_success", "host_deploy_instance_target_count",
    "host_deploy_cache_age_seconds", "host_deploy_cache_refresh_success",
]
METRIC_KEYS = PROCESS_METRIC_KEYS + PORT_METRIC_KEYS + TARGET_METRIC_KEYS
WINDOWS_PROCESS_CACHE = {}


def value_digest(value):
    return hashlib.sha1(text(value).encode("utf-8")).hexdigest()[:12]


DEBUG_LOG_MAX_BYTES = 5 * 1024 * 1024


def write_debug_log(path, payload):
    directory = os.path.dirname(path)
    if directory:
        try:
            os.makedirs(directory, 0o700)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
    try:
        if os.path.exists(path) and os.path.getsize(path) >= DEBUG_LOG_MAX_BYTES:
            rotated = "%s.1" % path
            try:
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(path, rotated)
            except OSError:
                pass
        with open(path, "ab") as handle:
            handle.write(("%s\n" % payload).encode("utf-8"))
    except (IOError, OSError):
        pass


def log_event(settings, level, stage, **fields):
    configured_level = text(settings.get("logLevel", "ERROR")).upper()
    if level == "DEBUG" and configured_level != "DEBUG":
        return
    if level not in ("DEBUG", "ERROR"):
        return
    payload = {"level": level, "stage": stage}
    payload.update(fields)
    log_path = settings.get("debugLogPath")
    if not log_path:
        return
    write_debug_log(log_path, json.dumps(payload, separators=(",", ":"), allow_nan=False))


def text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if sys.version_info[0] == 2 and isinstance(value, unicode):
        return value
    return str(value)


def safe_error_text(value):
    value = text(value)
    if sys.version_info[0] == 2 and isinstance(value, unicode):
        return value.encode("unicode_escape")
    return value


def env(name, default=""):
    value = os.environ.get("EASYOPS_COLLECTOR_" + name, default)
    if value is None:
        return default
    value = text(value).strip()
    return default if value.lower() in ("", "null", "none", "undefined", "<nil>") else value


def config():
    host_instance_id = env("instanceId")
    if not host_instance_id or host_instance_id.startswith("$."):
        raise ValueError("[config] 缺少有效主机instanceId，请检查 $.instanceId 映射")
    if not re.match(r"^[0-9A-Za-z_-]+$", host_instance_id):
        raise ValueError("[config] 主机instanceId包含非法字符")
    try:
        cache_ttl_days = float(env("cacheTtlDays", "7"))
        sample_interval = float(env("sampleInterval", "0.2"))
        request_timeout = float(env("requestTimeout", "10"))
        log_level = env("logLevel", "ERROR").upper()
        openapi_scheme = env("openapiScheme", "https").lower()
    except ValueError:
        raise ValueError("[config] 缓存有效期、采样间隔、请求超时、日志级别或OpenAPI协议格式错误")
    if not 1 <= cache_ttl_days <= 90:
        raise ValueError("[config] cacheTtlDays必须在1到90之间")
    if not 0.05 <= sample_interval <= 2:
        raise ValueError("[config] sampleInterval必须在0.05到2之间")
    if not 3 <= request_timeout <= 30:
        raise ValueError("[config] requestTimeout必须在3到30之间")
    if log_level not in ("ERROR", "DEBUG"):
        raise ValueError("[config] logLevel仅支持ERROR或DEBUG")
    if openapi_scheme not in ("http", "https"):
        raise ValueError("[config] openapiScheme仅支持http或https")
    settings = {
        "hostInstanceId": host_instance_id,
        "hostUuid": env("hostUuid"),
        "hostIp": env("hostIp"),
        "cacheDir": normalized_cache_dir(env("cacheDir", default_cache_dir())),
        "debugLogPath": os.path.join(
            normalized_cache_dir(env("cacheDir", default_cache_dir())),
            host_instance_id + ".debug.log"
        ),
        "cacheTtlSeconds": cache_ttl_days * 86400,
        "gateway": "",
        "gatewaySource": "missing",
        "openapiScheme": openapi_scheme,
        "accessKey": env("openapiAkText") or os.environ.get("EASYOPS_OPENAPI_AK", ""),
        "secretKey": env("openapiSkText") or os.environ.get("EASYOPS_OPENAPI_SK", ""),
        "sampleInterval": sample_interval,
        "requestTimeout": request_timeout,
        "logLevel": log_level,
        "windows": IS_WINDOWS,
    }
    settings["gateway"], settings["gatewaySource"] = resolve_openapi_gateway(
        env("openapiGateway") or os.environ.get("EASYOPS_OPENAPI_GATEWAY_URL", ""),
        openapi_scheme,
    )
    return settings


def read_file(path):
    with open(path, "rb") as handle:
        return handle.read()


def read_json(path):
    return json.loads(read_file(path).decode("utf-8"))


def write_json_atomic(path, data):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        raise OSError(errno.ENOENT, "cache directory does not exist", directory)
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    replace_file(temporary, path)


def agent_config_paths():
    if IS_WINDOWS:
        return [r"C:\easyops\agent\conf\conf.yaml", r"C:\easyOps\agent\conf\conf.yaml"]
    return ["/usr/local/easyops/agent/conf/conf.yaml"]


def gateway_from_agent_config(path, scheme):
    section = ""
    for raw_line in decode_bytes(read_file(path)).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not raw_line[:1].isspace():
            section = line.split(":", 1)[0].strip()
            continue
        if section != "command":
            continue
        match = re.match(r"^(?:-\s*)?ip\s*:\s*(['\"]?)([^#'\"]+)", line)
        if not match:
            continue
        host = match.group(2).strip().split(",", 1)[0].strip()
        if not host or host.startswith("__"):
            continue
        if ":" in host and not host.startswith("["):
            host = "[%s]" % host
        return "%s://%s" % (scheme, host)
    return ""


def resolve_openapi_gateway(configured_gateway, openapi_scheme="https"):
    for path in agent_config_paths():
        try:
            gateway = gateway_from_agent_config(path, openapi_scheme)
        except (IOError, OSError):
            continue
        if gateway:
            return gateway, "agentConfig"
    configured_gateway = text(configured_gateway).strip().rstrip("/")
    if configured_gateway:
        return configured_gateway, "param"
    return "", "missing"


def default_cache_dir():
    if not IS_WINDOWS:
        return "/tmp/easyops/deploy-instance-monitor"
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(system_root, "Temp", "easyops", "deploy-instance-monitor")


def normalized_cache_dir(path):
    if IS_WINDOWS and path == "/tmp/easyops/deploy-instance-monitor":
        return default_cache_dir()
    return path


def replace_file(source, target):
    if not IS_WINDOWS or not os.path.exists(target):
        os.rename(source, target)
        return
    try:
        os.rename(source, target)
    except OSError:
        os.remove(target)
        os.rename(source, target)


def cache_path(settings):
    return os.path.join(settings["cacheDir"], settings["hostInstanceId"] + ".json")


def target_debug_summary(target):
    process_list = target.get("processList") if isinstance(target.get("processList"), list) else []
    groups = target.get("processMatchGroups") if isinstance(target.get("processMatchGroups"), list) else []
    return {
        "instanceId": text(target.get("instanceId")),
        "objectId": text(target.get("_object_id")),
        "installPath": text(target.get("installPath")),
        "ports": normalize_ports(target),
        "processListCount": len(process_list),
        "processList": [
            {
                "pname": text(item.get("pname")) if isinstance(item, dict) else "",
                "cmdlineHash": value_digest(item.get("cmdline", "")) if isinstance(item, dict) else "",
            }
            for item in process_list if isinstance(item, dict)
        ],
        "processMatchGroupCount": len(groups),
        "processMatchKeywordCounts": [
            len(item.get("cmdline", [])) if isinstance(item, dict) and isinstance(item.get("cmdline"), list) else 0
            for item in groups
        ],
    }


def load_cache(path):
    try:
        data = read_json(path)
        if data.get("version") != 1 or not isinstance(data.get("targets"), list) or not data.get("refreshedAt"):
            raise ValueError("invalid cache schema")
        refreshed_at = float(data.get("refreshedAt"))
        if refreshed_at <= 0:
            raise ValueError("invalid refreshedAt")
        data["refreshedAt"] = refreshed_at
        return data
    except (IOError, OSError, ValueError, TypeError):
        return None


def sign_openapi(method, path, content_type, body, access_key, secret_key):
    timestamp = text(int(time.time()))
    content_md5 = hashlib.md5(body).hexdigest() if body else ""
    string_to_sign = "\n".join([method.upper(), path, "", content_type, content_md5, timestamp, access_key])
    signature = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    return {"accesskey": access_key, "signature": signature, "expires": timestamp}


def http_json(url, query, body, headers, timeout):
    request = Request(url + "?" + urlencode(query), data=body, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
        payload = response.read()
    except Exception as exc:
        raise RuntimeError(u"[http_json] OpenAPI请求失败: %s" % exc.__class__.__name__)
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except (TypeError, ValueError):
        raise RuntimeError("[http_json] OpenAPI返回非JSON")


def search_targets(settings):
    if not settings["gateway"] or not settings["accessKey"] or not settings["secretKey"]:
        raise ValueError("[search_targets] 缺少OpenAPI网关地址或AK/SK")
    if settings["hostUuid"]:
        condition_field, condition_value = "uuid", settings["hostUuid"]
    elif settings["hostIp"]:
        condition_field, condition_value = "ip", settings["hostIp"]
    elif settings["hostInstanceId"]:
        condition_field, condition_value = "host.instanceId", settings["hostInstanceId"]
    else:
        raise ValueError("[search_targets] 缺少hostUuid/hostIp，无法定位部署实例")
    log_event(settings, "DEBUG", "openapi.start", path=OPENAPI_PATH, conditionType=condition_field, pageLimit=100)
    fields = ["instanceId", "_object_id", "installPath", "version", "ip", "uuid", "ports", "processList", "processMatchGroups"]
    targets = []
    seen = set()
    for page in range(1, 101):
        body = json.dumps({
            "fields": fields, "page": page, "page_size": 1000,
            "ignore_missing_field_error": True,
            "query": {"isMonitor": "是", condition_field: condition_value},
        }).encode("utf-8")
        query = sign_openapi("POST", OPENAPI_PATH, "application/json", body, settings["accessKey"], settings["secretKey"])
        try:
            result = http_json(
                settings["gateway"].rstrip("/") + OPENAPI_PATH, query, body,
                {"Host": OPENAPI_HOST, "Content-Type": "application/json"},
                settings["requestTimeout"],
            )
        except Exception:
            log_event(settings, "ERROR", "openapi.request_failed", page=page, traceback=traceback.format_exc())
            raise
        if result.get("code") not in (0, "0", None):
            raise RuntimeError("[search_targets] OpenAPI business error code=%s" % safe_error_text(text(result.get("code"))))
        data = result.get("data") or {}
        for row in data.get("list") or []:
            instance_id = text(row.get("instanceId"))
            if instance_id and instance_id not in seen:
                seen.add(instance_id)
                targets.append(row)
        total = int(data.get("total") or 0)
        log_event(settings, "DEBUG", "openapi.page", page=page, returned=len(data.get("list") or []), total=total, kept=len(targets))
        if page * 1000 >= total:
            break
    return targets


def refresh_cache(settings, now):
    return {
        "version": 1, "refreshedAt": now,
        "hostInstanceId": settings["hostInstanceId"],
        "hostUuid": settings["hostUuid"], "hostIp": settings["hostIp"],
        "targets": search_targets(settings),
    }


def ensure_cache(settings, now):
    try:
        os.makedirs(settings["cacheDir"], 0o700)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
    if not stat.S_ISDIR(os.stat(settings["cacheDir"]).st_mode):
        raise OSError("[ensure_cache] 缓存路径不是目录")
    path = cache_path(settings)
    cache = load_cache(path)
    expired = cache is None or now - cache["refreshedAt"] > settings["cacheTtlSeconds"]
    log_event(settings, "DEBUG", "cache.check", path=path, exists=cache is not None, ageSeconds=max(now - cache["refreshedAt"], 0.0) if cache else None, expired=expired, targetCount=len(cache.get("targets", [])) if cache else 0)
    refresh_success = 1.0
    if expired:
        try:
            cache = refresh_cache(settings, now)
            write_json_atomic(path, cache)
            log_event(settings, "DEBUG", "cache.refresh_success", path=path, targetCount=len(cache.get("targets", [])))
        except Exception:
            log_event(settings, "ERROR", "cache.refresh_failed", path=path, hasOldCache=cache is not None, traceback=traceback.format_exc())
            if cache is None:
                raise
            refresh_success = 0.0
    return cache, refresh_success


def decode_bytes(value):
    if isinstance(value, bytes):
        encoding = "mbcs" if IS_WINDOWS else "utf-8"
        return value.decode(encoding, "replace")
    return text(value)


def run_windows_command(arguments):
    if not IS_WINDOWS:
        raise OSError("[run_windows_command] 仅支持Windows")
    process = subprocess.Popen(list(arguments), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        error = safe_error_text(decode_bytes(stderr)).strip()
        raise OSError("Windows command failed(%s): %s" % (process.returncode, error))
    return decode_bytes(stdout)


def windows_json(command):
    payload = run_windows_command([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", "$ErrorActionPreference='Stop'; " + command,
    ]).strip().lstrip(u"﻿")
    return json.loads(payload or "null")


def parse_windows_csv(payload):
    payload = text(payload).strip().lstrip(u"﻿")
    if not payload:
        return []
    if sys.version_info[0] == 2:
        stream = io.BytesIO(payload.encode("utf-8"))
    else:
        stream = io.StringIO(payload)
    rows = []
    for row in csv.DictReader(stream):
        if sys.version_info[0] == 2:
            decoded = {}
            for key, value in row.items():
                decoded_key = key.decode("utf-8", "replace") if isinstance(key, bytes) else key
                decoded_value = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
                decoded[decoded_key] = decoded_value
            row = decoded
        rows.append(row)
    return rows


def windows_csv(command):
    payload = run_windows_command([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", "$ErrorActionPreference='Stop'; " + command,
    ])
    return parse_windows_csv(payload)


def windows_query_rows(cim_command, wmi_command):
    try:
        payload = windows_json(cim_command)
        return payload if isinstance(payload, list) else [payload]
    except (OSError, ValueError) as exc:
        message = safe_error_text(exc)
        markers = ("Get-CimInstance", "ConvertTo-Json", "CommandNotFoundException")
        if not any(marker in message for marker in markers):
            raise
        return windows_csv(wmi_command)


def parse_windows_datetime(value):
    value = text(value)
    embedded = re.search(r"/Date\((-?\d+)", value)
    if embedded:
        return int(embedded.group(1)) / 1000.0
    wmi = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.(\d+))?([+-]\d{3,4})?$", value)
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$", value)
    match = wmi or iso
    if not match:
        return -1.0
    year, month, day, hour, minute, second = [int(match.group(index)) for index in range(1, 7)]
    fraction = text(match.group(7) or "0")[:6].ljust(6, "0")
    timestamp = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)) + float(fraction) / 1000000.0
    zone = match.group(8)
    if zone and zone not in ("Z",):
        zone_text = zone.replace(":", "")
        zone_sign = -1 if zone_text.startswith("-") else 1
        zone_digits = zone_text.lstrip("+-")
        if len(zone_digits) == 3:
            offset = int(zone_digits) * 60
        else:
            offset = int(zone_digits[-4:-2]) * 3600 + int(zone_digits[-2:]) * 60
        offset *= zone_sign
        timestamp -= offset
    return timestamp


def parse_windows_process_row(row):
    if not isinstance(row, dict):
        return None
    try:
        pid = int(row.get("ProcessId") or 0)
        if pid <= 0:
            return None
        executable = text(row.get("ExecutablePath"))
        name = text(row.get("Name"))
        cmdline = text(row.get("CommandLine")) or executable or name
        user_time = float(row.get("UserModeTime") or 0) / 10000000.0
        kernel_time = float(row.get("KernelModeTime") or 0) / 10000000.0
        return {
            "pid": pid,
            "comm": name or basename(executable),
            "state": "",
            "utime": user_time,
            "stime": kernel_time,
            "threads": int(row.get("ThreadCount") or 0),
            "start_timestamp": parse_windows_datetime(row.get("CreationDate")),
            "cmdline": cmdline,
            "cwd": "",
            "memory_bytes": max(float(row.get("WorkingSetSize") or 0), 0.0),
            "fd_count": int(row.get("HandleCount") or 0),
        }
    except (TypeError, ValueError):
        return None


def windows_process_snapshot():
    rows = windows_query_rows(
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine,"
        "ExecutablePath,CreationDate,UserModeTime,KernelModeTime,ThreadCount,"
        "WorkingSetSize,HandleCount | ConvertTo-Json -Compress -Depth 3",
        "Get-WmiObject Win32_Process | Select-Object ProcessId,Name,CommandLine,"
        "ExecutablePath,CreationDate,UserModeTime,KernelModeTime,ThreadCount,"
        "WorkingSetSize,HandleCount | ConvertTo-Csv -NoTypeInformation"
    )
    processes = [parsed for parsed in (parse_windows_process_row(row) for row in rows) if parsed]
    if not processes:
        raise OSError("Windows进程查询结果为空")
    WINDOWS_PROCESS_CACHE.clear()
    for process in processes:
        WINDOWS_PROCESS_CACHE[process["pid"]] = process
    return processes


def refresh_process_record(process, force=False):
    if not IS_WINDOWS:
        return parse_proc_stat(read_file("/proc/%d/stat" % process["pid"]))
    if force:
        windows_process_snapshot()
    refreshed = WINDOWS_PROCESS_CACHE.get(process["pid"])
    if refreshed is None:
        windows_process_snapshot()
        refreshed = WINDOWS_PROCESS_CACHE.get(process["pid"])
    return dict(refreshed) if refreshed is not None else None


def read_link(path):
    try:
        return decode_bytes(os.readlink(path))
    except OSError:
        return ""


def parse_proc_stat(payload):
    payload = decode_bytes(payload)
    close_position = payload.rfind(")")
    if close_position < 0:
        return None
    prefix = payload[:close_position].split("(", 1)
    fields = payload[close_position + 2:].split()
    if len(fields) < 20 or len(prefix) != 2:
        return None
    try:
        return {
            "pid": int(prefix[0]), "comm": prefix[1], "state": fields[0],
            "utime": float(fields[11]), "stime": float(fields[12]),
            "threads": int(fields[17]), "startTimeTicks": float(fields[19]),
        }
    except (IndexError, ValueError):
        return None


def list_processes():
    if IS_WINDOWS:
        return windows_process_snapshot()
    processes = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        base = "/proc/%d" % pid
        try:
            cmdline = decode_bytes(read_file(base + "/cmdline")).replace("\x00", " ").strip()
        except (IOError, OSError):
            cmdline = ""
        try:
            parsed = parse_proc_stat(read_file(base + "/stat"))
        except (IOError, OSError):
            parsed = None
        if not parsed:
            continue
        parsed["cmdline"] = cmdline
        parsed["cwd"] = read_link(base + "/cwd")
        processes.append(parsed)
    return processes


def path_prefix(value, prefix):
    value = normalize_windows_path(value) or "/"
    prefix = normalize_windows_path(prefix)
    return bool(prefix) and (value == prefix or value.startswith(prefix + "/"))


def normalize_windows_path(value):
    value = text(value).replace("\\", "/").rstrip("/")
    return value.lower() if IS_WINDOWS else value


def basename(value):
    return text(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def match_one_process(process, expected, install_path):
    if not install_path:
        return False
    cmdline = process.get("cmdline", "")
    cwd = process.get("cwd", "")
    expected_cmdline = text(expected.get("cmdline"))
    expected_cwd = text(expected.get("cwd"))
    expected_name = text(expected.get("pname"))
    actual_names = [process.get("comm", ""), basename(cmdline.split(" ", 1)[0])]
    normalized_cmdline = normalize_windows_path(cmdline)
    actual_names = [normalize_windows_path(item) for item in actual_names]
    score = 0
    if normalize_windows_path(install_path) in normalize_windows_path(cmdline) or path_prefix(cwd, install_path):
        score += 2
    if expected_name and normalize_windows_path(expected_name) in actual_names:
        score += 2
    if expected_cmdline and normalize_windows_path(expected_cmdline) in normalized_cmdline:
        score += 2
    if expected_cwd and path_prefix(cwd, expected_cwd):
        score += 2
    return score >= 4


def match_keyword_group(process, group):
    keywords = group.get("cmdline") if isinstance(group, dict) else None
    if not isinstance(keywords, list):
        return False
    keywords = [text(item) for item in keywords if text(item)]
    cmdline = process.get("cmdline", "")
    normalized_cmdline = normalize_windows_path(cmdline)
    return bool(keywords and cmdline) and all(normalize_windows_path(keyword) in normalized_cmdline for keyword in keywords)


def match_target_processes(target, processes):
    groups = target.get("processMatchGroups")
    if isinstance(groups, list) and groups:
        matched = [process for process in processes if any(match_keyword_group(process, group) for group in groups)]
        if matched:
            return matched
    expected = target.get("processList")
    install_path = text(target.get("installPath"))
    if isinstance(expected, list) and expected:
        return [process for process in processes if any(match_one_process(process, item, install_path) for item in expected)]
    if not install_path:
        return []
    return [process for process in processes if normalize_windows_path(install_path) in normalize_windows_path(process.get("cmdline", "")) or path_prefix(process.get("cwd", ""), install_path)]


def boot_time():
    if IS_WINDOWS:
        rows = windows_query_rows(
            "Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime | ConvertTo-Json -Compress",
            "Get-WmiObject Win32_OperatingSystem | Select-Object LastBootUpTime | ConvertTo-Csv -NoTypeInformation"
        )
        row = rows[0] if rows else None
        return parse_windows_datetime(row.get("LastBootUpTime")) if isinstance(row, dict) else -1.0
    try:
        for line in decode_bytes(read_file("/proc/stat")).splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (IOError, OSError, IndexError, ValueError):
        pass
    return -1.0


def clock_ticks():
    try:
        return float(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, ValueError, OSError):
        return 100.0


def page_size():
    try:
        return float(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return 4096.0


def memory_total_bytes():
    if IS_WINDOWS:
        rows = windows_query_rows(
            "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize | ConvertTo-Json -Compress",
            "Get-WmiObject Win32_OperatingSystem | Select-Object TotalVisibleMemorySize | ConvertTo-Csv -NoTypeInformation"
        )
        row = rows[0] if rows else None
        if isinstance(row, dict):
            try:
                return float(row.get("TotalVisibleMemorySize") or 0) * 1048576.0
            except (TypeError, ValueError):
                return -1.0
        return -1.0
    try:
        for line in decode_bytes(read_file("/proc/meminfo")).splitlines():
            if line.startswith("MemTotal:"):
                return float(line.split()[1]) * 1024.0
    except (IOError, OSError, IndexError, ValueError):
        pass
    return -1.0


def process_memory_bytes(pid):
    if IS_WINDOWS:
        process = WINDOWS_PROCESS_CACHE.get(pid) or {}
        return float(process.get("memory_bytes", -1.0))
    try:
        return float(read_file("/proc/%d/statm" % pid).decode("utf-8", "replace").split()[1]) * page_size()
    except (IOError, OSError, IndexError, ValueError):
        return -1.0


def process_fd_usage(pid):
    if IS_WINDOWS:
        process = WINDOWS_PROCESS_CACHE.get(pid) or {}
        try:
            return int(process.get("fd_count", -1)), -1
        except (TypeError, ValueError):
            return -1, -1
    try:
        used = len(os.listdir("/proc/%d/fd" % pid))
    except OSError:
        return -1, -1
    limit = -1
    try:
        for line in read_file("/proc/%d/limits" % pid).decode("utf-8", "replace").splitlines():
            if line.startswith("Max open files"):
                parts = line.split()
                if len(parts) >= 5 and parts[3] != "unlimited":
                    limit = int(parts[3])
                break
    except (IOError, OSError, ValueError, IndexError):
        pass
    return used, limit


def parse_socket_table(path):
    result = {}
    try:
        lines = read_file(path).decode("utf-8", "replace").splitlines()[1:]
    except (IOError, OSError):
        return result
    for line in lines:
        fields = line.split()
        if len(fields) < 10:
            continue
        try:
            port = int(fields[1].rsplit(":", 1)[1], 16)
            state, inode = fields[3], fields[9]
        except (IndexError, ValueError):
            continue
        if state == "0A" and 0 < port <= 65535:
            result.setdefault(port, set()).add(inode)
    return result


def parse_windows_netstat(payload):
    result = {}
    for line in decode_bytes(payload).splitlines():
        match = re.match(r"^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$", line, re.I)
        if match:
            result.setdefault(int(match.group(1)), set()).add(match.group(2))
    return result


def listening_ports():
    if IS_WINDOWS:
        return parse_windows_netstat(run_windows_command(["netstat.exe", "-ano", "-p", "tcp"]))
    result = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        for port, inodes in parse_socket_table(path).items():
            result.setdefault(port, set()).update(inodes)
    return result


def process_socket_inodes(processes):
    if IS_WINDOWS:
        return set(text(process["pid"]) for process in processes), True
    inodes = set()
    readable = False
    for process in processes:
        try:
            entries = os.listdir("/proc/%d/fd" % process["pid"])
            readable = True
            for entry in entries:
                target = read_link("/proc/%d/fd/%s" % (process["pid"], entry))
                if target.startswith("socket:[") and target.endswith("]"):
                    inodes.add(target[8:-1])
        except OSError:
            continue
    return inodes, readable


def normalize_ports(target):
    ports = []
    value = target.get("ports")
    if not isinstance(value, list):
        return ports
    for item in value:
        try:
            port = int(text(item))
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return ports


def collect_target(target, processes, sockets, boot_ts, ticks, mem_total, settings, now, cache_age, refresh_success, target_count):
    matched = match_target_processes(target, processes)
    expected_ports = normalize_ports(target)
    matched_inodes, fd_readable = process_socket_inodes(matched)
    log_event(settings, "DEBUG", "target.start", target=target_debug_summary(target), processCount=len(processes), matchedProcessCount=len(matched), matchedPids=[item["pid"] for item in matched], matchedCmdlineHashes=[value_digest(item.get("cmdline", "")) for item in matched], expectedPorts=expected_ports, fdReadable=fd_readable, matchedSocketInodeCount=len(matched_inodes))
    listening = []
    for port in expected_ports:
        global_inodes = sockets.get(port, set())
        intersect_inodes = matched_inodes.intersection(global_inodes)
        reason = "process_socket" if matched_inodes and intersect_inodes else "global_socket_without_fd" if not fd_readable and global_inodes else "not_listening"
        if matched_inodes and matched_inodes.intersection(global_inodes):
            listening.append(port)
        elif not fd_readable and global_inodes:
            listening.append(port)
        log_event(settings, "DEBUG", "port.match", deployInstanceId=text(target.get("instanceId")), port=port, reason=reason, globalSocketInodeCount=len(global_inodes), intersectSocketInodeCount=len(intersect_inodes))
    before_by_cmdline = {}
    for item in matched:
        cmdline = text(item.get("cmdline"))
        before_by_cmdline[cmdline] = before_by_cmdline.get(cmdline, 0.0) + item["utime"] + item["stime"]
    sample_started = time.time()
    time.sleep(settings["sampleInterval"])
    refreshed = {}
    if IS_WINDOWS:
        windows_process_snapshot()
    for item in matched:
        try:
            parsed = refresh_process_record(item)
        except (IOError, OSError):
            parsed = None
            log_event(settings, "ERROR", "process.refresh_stat_failed", deployInstanceId=text(target.get("instanceId")), pid=item["pid"], traceback=traceback.format_exc())
        if parsed:
            parsed["cmdline"], parsed["cwd"] = item["cmdline"], item["cwd"]
            refreshed[item["pid"]] = parsed
    elapsed = max(time.time() - sample_started, 0.001)
    cmdlines = []
    for item in matched:
        cmdline = text(item.get("cmdline"))
        if cmdline not in cmdlines:
            cmdlines.append(cmdline)
    after_by_cmdline = {}
    for item in refreshed.values():
        cmdline = text(item.get("cmdline"))
        after_by_cmdline[cmdline] = after_by_cmdline.get(cmdline, 0.0) + item["utime"] + item["stime"]
    config_valid = bool(text(target.get("installPath")) or (isinstance(target.get("processMatchGroups"), list) and target.get("processMatchGroups")))
    base_dims = {"hostInstanceId": settings["hostInstanceId"], "deployInstanceId": text(target.get("instanceId")), "installPath": text(target.get("installPath"))}
    rows = []
    for cmdline in cmdlines or [""]:
        group = [item for item in refreshed.values() if text(item.get("cmdline")) == cmdline]
        memory_bytes = sum(max(process_memory_bytes(item["pid"]), 0.0) for item in group)
        thread_count = sum(item["threads"] for item in group)
        zombie_count = sum(1 for item in group if item["state"] == "Z")
        if IS_WINDOWS:
            starts = [float(item["start_timestamp"]) for item in group if item.get("start_timestamp", -1) >= 0]
        else:
            starts = [boot_ts + float(item["startTimeTicks"]) / ticks for item in group] if boot_ts >= 0 else []
        fd_count = fd_limit = 0
        readable_fd_count = 0
        for item in group:
            used, limit = process_fd_usage(item["pid"])
            if used >= 0:
                fd_count += used
                readable_fd_count += 1
            if limit > 0:
                fd_limit += limit
        fd_usage = fd_count * 100.0 / fd_limit if fd_limit > 0 else -1.0
        before = before_by_cmdline.get(cmdline, 0.0)
        after = after_by_cmdline.get(cmdline, 0.0)
        process_values = {
            "deploy_instance_process_alive": 1.0 if group else 0.0,
            "deploy_instance_process_count": float(len(group)),
            "deploy_instance_matching_process_count": float(len(group)),
            "deploy_instance_zombie_process_count": float(zombie_count),
            "deploy_instance_thread_count": float(thread_count),
            "deploy_instance_process_start_timestamp": min(starts) if starts else -1.0,
            "deploy_instance_process_uptime_seconds": max(now - min(starts), 0.0) if starts else -1.0,
            "deploy_instance_process_memory_bytes": memory_bytes if group else 0.0,
            "deploy_instance_process_memory_percent": memory_bytes * 100.0 / mem_total if group and mem_total > 0 else -1.0,
            "deploy_instance_process_cpu_percent": max(float(after - before) / elapsed * 100.0 if IS_WINDOWS else float(after - before) / (elapsed * ticks) * 100.0, 0.0) if group else -1.0,
            "deploy_instance_process_fd_count": float(fd_count) if readable_fd_count else -1.0,
            "deploy_instance_process_fd_usage_percent": fd_usage,
        }
        log_event(settings, "DEBUG", "process.metrics", deployInstanceId=text(target.get("instanceId")), cmdlineHash=value_digest(cmdline), refreshedProcessCount=len(group), beforeTicks=before, afterTicks=after, values=process_values)
        rows.append({"dims": dict(base_dims, cmdline=cmdline), "vals": process_values})
    for port in expected_ports or [""]:
        is_listening = port in listening
        port_values = {
            "deploy_instance_expected_port_count": 1.0 if expected_ports else 0.0,
            "deploy_instance_listening_port_count": 1.0 if is_listening else 0.0,
            "deploy_instance_port_missing_count": 0.0 if not expected_ports or is_listening else 1.0,
            "deploy_instance_port_listen": 1.0 if not expected_ports or is_listening else 0.0,
            "deploy_instance_port_listen_ratio_pct": 100.0 if not expected_ports or is_listening else 0.0,
            "deploy_instance_config_valid": 1.0 if config_valid else 0.0,
        }
        log_event(settings, "DEBUG", "port.metrics", deployInstanceId=text(target.get("instanceId")), port=text(port), values=port_values)
        rows.append({"dims": dict(base_dims, port=text(port)), "vals": port_values})
    target_values = {
        "deploy_instance_collect_success": 1.0,
        "host_deploy_instance_target_count": float(target_count),
        "host_deploy_cache_age_seconds": cache_age,
        "host_deploy_cache_refresh_success": refresh_success,
    }
    log_event(settings, "DEBUG", "target.metrics", deployInstanceId=text(target.get("instanceId")), values=target_values)
    rows.append({"dims": dict(base_dims), "vals": target_values})
    return rows


def collect(settings):
    now = time.time()
    log_event(settings, "DEBUG", "collect.start", version=VERSION, hostInstanceId=settings["hostInstanceId"], hasHostUuid=bool(settings["hostUuid"]), hasHostIp=bool(settings["hostIp"]), cacheTtlSeconds=settings["cacheTtlSeconds"], sampleInterval=settings["sampleInterval"])
    cache, refresh_success = ensure_cache(settings, now)
    cache_age = max(now - cache["refreshedAt"], 0.0)
    targets = [row for row in cache.get("targets", []) if isinstance(row, dict) and text(row.get("instanceId"))]
    processes, sockets = list_processes(), listening_ports()
    boot_ts, ticks, mem_total = boot_time(), clock_ticks(), memory_total_bytes()
    log_event(settings, "DEBUG", "local.snapshot", targetCount=len(targets), processCount=len(processes), listeningPorts=sorted(sockets.keys()), bootTimestamp=boot_ts, clockTicks=ticks, memoryTotalBytes=mem_total)
    output = []
    for target in targets:
        try:
            output.extend(collect_target(target, processes, sockets, boot_ts, ticks, mem_total, settings, now, cache_age, refresh_success, len(targets)))
        except Exception:
            log_event(settings, "ERROR", "target.collect_failed", deployInstanceId=text(target.get("instanceId")), fallbackMetricCount=5, traceback=traceback.format_exc())
            output.append({"dims": {"hostInstanceId": settings["hostInstanceId"], "deployInstanceId": text(target.get("instanceId")), "installPath": text(target.get("installPath"))}, "vals": {"deploy_instance_config_valid": 0.0, "deploy_instance_collect_success": 0.0, "host_deploy_instance_target_count": float(len(targets)), "host_deploy_cache_age_seconds": cache_age, "host_deploy_cache_refresh_success": refresh_success}})
    metric_counts = {}
    for row in output:
        for key in row.get("vals", {}):
            metric_counts[key] = metric_counts.get(key, 0) + 1
    log_event(settings, "DEBUG", "collect.output", rowCount=len(output), uniqueMetricCount=len(metric_counts), expectedMetricCount=len(METRIC_KEYS), missingMetrics=sorted(set(METRIC_KEYS) - set(metric_counts)), metricCounts=dict(sorted(metric_counts.items())))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="主机部署实例本机监控：按主机instanceId读取7天缓存，OpenAPI刷新isMonitor=是的ARTIFACT_INST目标，采集进程、端口、CPU、内存和句柄指标。",
        epilog="参数均由 EASYOPS_COLLECTOR_* 环境变量注入：instanceId/hostUuid/hostIp/cacheDir/cacheTtlDays/openapiScheme(默认https)/openapiGateway(兜底)/openapiAkText/openapiSkText/sampleInterval/requestTimeout/logLevel。logLevel=DEBUG时诊断JSON写入缓存目录<hostInstanceId>.debug.log且不包含AK/SK，stdout/stderr均不混入诊断；默认ERROR只输出异常。顶层异常输出COLLECT_ERROR并保持退出码0。示例：EASYOPS_COLLECTOR_instanceId=65eb86f148251 EASYOPS_COLLECTOR_hostUuid=f907... EASYOPS_COLLECTOR_hostIp=192.168.110.24 EASYOPS_COLLECTOR_openapiGateway=http://192.168.110.24 EASYOPS_OPENAPI_AK=... EASYOPS_OPENAPI_SK=... EASYOPS_COLLECTOR_logLevel=DEBUG python host_deploy_instance_monitor.py")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args(argv)
    try:
        settings = config()
        log_event(settings, "DEBUG", "config.ready", version=VERSION, logLevel=settings["logLevel"], cacheDir=settings["cacheDir"], gatewayConfigured=bool(settings["gateway"]), gatewaySource=settings["gatewaySource"], openapiScheme=settings["openapiScheme"], accessKeyConfigured=bool(settings["accessKey"]), secretKeyConfigured=bool(settings["secretKey"]))
        sys.stdout.write("%s\n" % json.dumps(collect(settings), allow_nan=False))
    except Exception:
        sys.stdout.write("COLLECT_ERROR: [main] %s\n" % traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
