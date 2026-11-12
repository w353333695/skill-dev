#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""HOST 本地部署实例进程与端口监控脚本，参数由 EASYOPS_COLLECTOR_* 注入。"""
from __future__ import division, print_function

import argparse
import errno
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import time
import traceback

if sys.version_info[0] >= 3:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
else:
    from urllib import urlencode
    from urllib2 import Request, urlopen

VERSION = "0.1.3"
OBJECT_ID = "ARTIFACT_INST@ONEMODEL"
OPENAPI_PATH = "/cmdbservice/v3/object/ARTIFACT_INST@ONEMODEL/instance/_search"
OPENAPI_HOST = "openapi.easyops-only.com"
METRIC_KEYS = [
    "deploy_instance_process_alive", "deploy_instance_process_count",
    "deploy_instance_matching_process_count", "deploy_instance_zombie_process_count",
    "deploy_instance_thread_count", "deploy_instance_process_start_timestamp",
    "deploy_instance_process_uptime_seconds", "deploy_instance_process_memory_bytes",
    "deploy_instance_process_memory_percent", "deploy_instance_process_cpu_percent",
    "deploy_instance_process_fd_count", "deploy_instance_process_fd_usage_percent",
    "deploy_instance_expected_port_count", "deploy_instance_listening_port_count",
    "deploy_instance_port_missing_count", "deploy_instance_port_listen",
    "deploy_instance_port_listen_ratio_pct", "deploy_instance_config_valid",
    "deploy_instance_collect_success", "host_deploy_instance_target_count",
    "host_deploy_cache_age_seconds", "host_deploy_cache_refresh_success",
]


def text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


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
    except ValueError:
        raise ValueError("[config] 缓存有效期、采样间隔或请求超时必须是数字")
    if not 1 <= cache_ttl_days <= 90:
        raise ValueError("[config] cacheTtlDays必须在1到90之间")
    if not 0.05 <= sample_interval <= 2:
        raise ValueError("[config] sampleInterval必须在0.05到2之间")
    if not 3 <= request_timeout <= 30:
        raise ValueError("[config] requestTimeout必须在3到30之间")
    return {
        "hostInstanceId": host_instance_id,
        "hostUuid": env("hostUuid"),
        "hostIp": env("hostIp"),
        "cacheDir": env("cacheDir", "/tmp/easyops/deploy-instance-monitor"),
        "cacheTtlSeconds": cache_ttl_days * 86400,
        "gateway": env("openapiGateway") or os.environ.get("EASYOPS_OPENAPI_GATEWAY_URL", ""),
        "accessKey": env("openapiAk") or os.environ.get("EASYOPS_OPENAPI_AK", ""),
        "secretKey": env("openapiSk") or os.environ.get("EASYOPS_OPENAPI_SK", ""),
        "sampleInterval": sample_interval,
        "requestTimeout": request_timeout,
    }


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
        handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.rename(temporary, path)


def cache_path(settings):
    return os.path.join(settings["cacheDir"], settings["hostInstanceId"] + ".json")


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
        raise RuntimeError("[http_json] OpenAPI请求失败: %s" % exc.__class__.__name__)
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except (TypeError, ValueError):
        raise RuntimeError("[http_json] OpenAPI返回非JSON")


def search_targets(settings):
    if not settings["gateway"] or not settings["accessKey"] or not settings["secretKey"]:
        raise ValueError("[search_targets] 缺少OpenAPI网关地址或AK/SK")
    conditions = [
        {"host.instanceId": settings["hostInstanceId"]},
        {"uuid": settings["hostUuid"]},
        {"ip": settings["hostIp"]},
    ]
    conditions = [item for item in conditions if list(item.values())[0]]
    if not conditions:
        raise ValueError("[search_targets] 缺少hostUuid/hostIp，无法定位部署实例")
    fields = ["instanceId", "_object_id", "installPath", "version", "ip", "uuid", "ports", "processList", "processMatchGroups"]
    targets = []
    seen = set()
    for page in range(1, 101):
        body = json.dumps({
            "fields": fields, "page": page, "page_size": 1000,
            "ignore_missing_field_error": True,
            "query": {"isMonitor": "是", "$or": conditions},
        }, ensure_ascii=False).encode("utf-8")
        query = sign_openapi("POST", OPENAPI_PATH, "application/json", body, settings["accessKey"], settings["secretKey"])
        result = http_json(
            settings["gateway"].rstrip("/") + OPENAPI_PATH, query, body,
            {"Host": OPENAPI_HOST, "Content-Type": "application/json"},
            settings["requestTimeout"],
        )
        if result.get("code") not in (0, "0", None):
            raise RuntimeError("[search_targets] OpenAPI业务错误code=%s" % text(result.get("code")))
        data = result.get("data") or {}
        for row in data.get("list") or []:
            instance_id = text(row.get("instanceId"))
            if instance_id and instance_id not in seen:
                seen.add(instance_id)
                targets.append(row)
        total = int(data.get("total") or 0)
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
    refresh_success = 1.0
    if expired:
        try:
            cache = refresh_cache(settings, now)
            write_json_atomic(path, cache)
        except Exception:
            if cache is None:
                raise
            refresh_success = 0.0
    return cache, refresh_success


def decode_bytes(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text(value)


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
    value = text(value).rstrip("/") or "/"
    prefix = text(prefix).rstrip("/")
    return bool(prefix) and (value == prefix or value.startswith(prefix + "/"))


def basename(value):
    return text(value).rstrip("/").rsplit("/", 1)[-1]


def match_one_process(process, expected, install_path):
    if not install_path:
        return False
    cmdline = process.get("cmdline", "")
    cwd = process.get("cwd", "")
    expected_cmdline = text(expected.get("cmdline"))
    expected_cwd = text(expected.get("cwd"))
    expected_name = text(expected.get("pname"))
    actual_names = [process.get("comm", ""), basename(cmdline.split(" ", 1)[0])]
    score = 0
    if install_path in cmdline or path_prefix(cwd, install_path):
        score += 2
    if expected_name and expected_name in actual_names:
        score += 2
    if expected_cmdline and expected_cmdline in cmdline:
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
    return bool(keywords and cmdline) and all(keyword in cmdline for keyword in keywords)


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
    return [process for process in processes if install_path in process.get("cmdline", "") or path_prefix(process.get("cwd", ""), install_path)]


def boot_time():
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
    try:
        for line in decode_bytes(read_file("/proc/meminfo")).splitlines():
            if line.startswith("MemTotal:"):
                return float(line.split()[1]) * 1024.0
    except (IOError, OSError, IndexError, ValueError):
        pass
    return -1.0


def process_memory_bytes(pid):
    try:
        return float(read_file("/proc/%d/statm" % pid).decode("utf-8", "replace").split()[1]) * page_size()
    except (IOError, OSError, IndexError, ValueError):
        return -1.0


def process_fd_usage(pid):
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


def listening_ports():
    result = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        for port, inodes in parse_socket_table(path).items():
            result.setdefault(port, set()).update(inodes)
    return result


def process_socket_inodes(processes):
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
    listening = []
    for port in expected_ports:
        global_inodes = sockets.get(port, set())
        if matched_inodes and matched_inodes.intersection(global_inodes):
            listening.append(port)
        elif not fd_readable and global_inodes:
            listening.append(port)
    before = sum(item["utime"] + item["stime"] for item in matched)
    sample_started = time.time()
    time.sleep(settings["sampleInterval"])
    refreshed = {}
    for item in matched:
        try:
            parsed = parse_proc_stat(read_file("/proc/%d/stat" % item["pid"]))
        except (IOError, OSError):
            parsed = None
        if parsed:
            parsed["cmdline"], parsed["cwd"] = item["cmdline"], item["cwd"]
            refreshed[item["pid"]] = parsed
    elapsed = max(time.time() - sample_started, 0.001)
    after = sum(item["utime"] + item["stime"] for item in refreshed.values())
    cpu_percent = max((after - before) / (elapsed * ticks) * 100.0, 0.0) if refreshed else -1.0
    memory_bytes = sum(max(process_memory_bytes(item["pid"]), 0.0) for item in refreshed.values())
    thread_count = sum(item["threads"] for item in refreshed.values())
    zombie_count = sum(1 for item in refreshed.values() if item["state"] == "Z")
    starts = [boot_ts + item["startTimeTicks"] / ticks for item in refreshed.values()] if boot_ts >= 0 else []
    fd_count = fd_limit = readable_fd_count = 0
    for item in refreshed.values():
        used, limit = process_fd_usage(item["pid"])
        if used >= 0:
            fd_count += used
            readable_fd_count += 1
        if limit > 0:
            fd_limit += limit
    fd_usage = fd_count * 100.0 / fd_limit if fd_limit > 0 else -1.0
    config_valid = bool(text(target.get("installPath")) or (isinstance(target.get("processMatchGroups"), list) and target.get("processMatchGroups")))
    values = {
        "deploy_instance_process_alive": 1.0 if matched else 0.0,
        "deploy_instance_process_count": float(len(matched)),
        "deploy_instance_matching_process_count": float(len(matched)),
        "deploy_instance_zombie_process_count": float(zombie_count),
        "deploy_instance_thread_count": float(thread_count),
        "deploy_instance_process_start_timestamp": min(starts) if starts else -1.0,
        "deploy_instance_process_uptime_seconds": max(now - min(starts), 0.0) if starts else -1.0,
        "deploy_instance_process_memory_bytes": memory_bytes if matched else 0.0,
        "deploy_instance_process_memory_percent": memory_bytes * 100.0 / mem_total if matched and mem_total > 0 else -1.0,
        "deploy_instance_process_cpu_percent": cpu_percent,
        "deploy_instance_process_fd_count": float(fd_count) if readable_fd_count else -1.0,
        "deploy_instance_process_fd_usage_percent": fd_usage,
        "deploy_instance_expected_port_count": float(len(expected_ports)),
        "deploy_instance_listening_port_count": float(len(listening)),
        "deploy_instance_port_missing_count": float(len([port for port in expected_ports if port not in listening])),
        "deploy_instance_port_listen": 1.0 if not expected_ports or len(listening) == len(expected_ports) else 0.0,
        "deploy_instance_port_listen_ratio_pct": len(listening) * 100.0 / len(expected_ports) if expected_ports else 100.0,
        "deploy_instance_config_valid": 1.0 if config_valid else 0.0,
        "deploy_instance_collect_success": 1.0,
        "host_deploy_instance_target_count": float(target_count),
        "host_deploy_cache_age_seconds": cache_age,
        "host_deploy_cache_refresh_success": refresh_success,
    }
    return {"dims": {"hostInstanceId": settings["hostInstanceId"], "deployInstanceId": text(target.get("instanceId")), "installPath": text(target.get("installPath"))}, "vals": values}


def collect(settings):
    now = time.time()
    cache, refresh_success = ensure_cache(settings, now)
    cache_age = max(now - cache["refreshedAt"], 0.0)
    targets = [row for row in cache.get("targets", []) if isinstance(row, dict) and text(row.get("instanceId"))]
    processes, sockets = list_processes(), listening_ports()
    boot_ts, ticks, mem_total = boot_time(), clock_ticks(), memory_total_bytes()
    output = []
    for target in targets:
        try:
            output.append(collect_target(target, processes, sockets, boot_ts, ticks, mem_total, settings, now, cache_age, refresh_success, len(targets)))
        except Exception:
            output.append({"dims": {"hostInstanceId": settings["hostInstanceId"], "deployInstanceId": text(target.get("instanceId")), "installPath": text(target.get("installPath"))}, "vals": {"deploy_instance_config_valid": 0.0, "deploy_instance_collect_success": 0.0, "host_deploy_instance_target_count": float(len(targets)), "host_deploy_cache_age_seconds": cache_age, "host_deploy_cache_refresh_success": refresh_success}})
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="主机部署实例本机监控：按主机instanceId读取7天缓存，OpenAPI刷新isMonitor=是的ARTIFACT_INST目标，采集进程、端口、CPU、内存和句柄指标。",
        epilog="参数均由 EASYOPS_COLLECTOR_* 环境变量注入：instanceId/hostUuid/hostIp/cacheDir/cacheTtlDays/openapiGateway/openapiAk/openapiSk/sampleInterval/requestTimeout。正常输出JSON数组；顶层异常输出COLLECT_ERROR并保持退出码0。示例：EASYOPS_COLLECTOR_instanceId=65eb86f148251 EASYOPS_COLLECTOR_hostUuid=f907... EASYOPS_COLLECTOR_hostIp=192.168.110.24 EASYOPS_COLLECTOR_openapiGateway=http://192.168.110.24 EASYOPS_OPENAPI_AK=... EASYOPS_OPENAPI_SK=... python host_deploy_instance_monitor.py")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args(argv)
    try:
        settings = config()
        print(json.dumps(collect(settings), ensure_ascii=False, allow_nan=False))
    except Exception:
        print("COLLECT_ERROR: [main] " + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
