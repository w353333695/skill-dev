#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""通用主机 ICMP Ping 监控脚本，参数由 EASYOPS_COLLECTOR_* 环境变量注入。"""
from __future__ import print_function
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import traceback

VERSION = "0.1.0"


def env(name, default=""):
    value = os.environ.get("EASYOPS_COLLECTOR_" + name, default)
    if value is None:
        return default
    value = str(value).strip()
    return default if value.lower() in ("", "null", "none", "undefined", "<nil>") else value


def config():
    ip = env("ip")
    if not ip or ip.startswith("$."):
        raise ValueError("[config] 缺少有效的目标IP，请检查 $.ip 映射")
    try:
        count = int(env("count", "3"))
        timeout = int(env("timeout", "2"))
    except ValueError:
        raise ValueError("[config] count和timeout必须为整数")
    if count < 1 or count > 10:
        raise ValueError("[config] count必须在1到10之间")
    if timeout < 1 or timeout > 30:
        raise ValueError("[config] timeout必须在1到30之间")
    return ip, count, timeout


def ping(ip, count, timeout):
    command = ["ping", "-n", "-c", str(count), "-W", str(timeout), ip]
    process = None
    expired = [False]
    def kill_process():
        if process is not None and process.poll() is None:
            expired[0] = True
            try:
                process.kill()
            except OSError:
                pass
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        timer = threading.Timer(count * timeout + 2, kill_process)
        timer.daemon = True
        timer.start()
        stdout, stderr = process.communicate()
        timer.cancel()
        if expired[0]:
            return {"available": 0.0, "loss": 100.0, "error": "ping command timeout"}
        if not isinstance(stdout, str):
            stdout = stdout.decode("utf-8", "replace")
        text = stdout + "\n" + (stderr.decode("utf-8", "replace") if not isinstance(stderr, str) else stderr)
        loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*packet loss", text)
        loss = float(loss_match.group(1)) if loss_match else (0.0 if process.returncode == 0 else 100.0)
        rtt = re.search(r"=\s*([0-9.]+)\s*/\s*([0-9.]+)\s*/\s*([0-9.]+)", text)
        if rtt:
            minimum, average, maximum = [float(rtt.group(i)) for i in (1, 2, 3)]
        else:
            minimum = average = maximum = -1.0
        return {"available": 1.0 if process.returncode == 0 and loss < 100.0 else 0.0,
                "loss": loss, "min": minimum, "avg": average, "max": maximum}
    except Exception:
        return {"available": 0.0, "loss": 100.0, "error": traceback.format_exc().splitlines()[-1]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="主机ICMP Ping监控。参数由EASYOPS_COLLECTOR_*环境变量提供。")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args(argv)
    try:
        ip, count, timeout = config()
        result = ping(ip, count, timeout)
        values = {"ping_available": result["available"], "ping_packet_loss_pct": result["loss"]}
        for key, metric in (("min", "ping_rtt_min_ms"), ("avg", "ping_rtt_avg_ms"), ("max", "ping_rtt_max_ms")):
            if key in result and result[key] >= 0:
                values[metric] = result[key]
        print(json.dumps([{"dims": {"ip": ip}, "vals": values}], ensure_ascii=True, allow_nan=False))
    except Exception:
        print("COLLECT_ERROR: [main] " + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
