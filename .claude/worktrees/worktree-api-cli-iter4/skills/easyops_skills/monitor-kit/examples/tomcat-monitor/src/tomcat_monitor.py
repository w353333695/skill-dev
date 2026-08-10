#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""
Tomcat 监控采集脚本
通过 HTTP Manager 接口采集 Tomcat 运行状态
"""
import os
import json
import re
import base64
try:
    from urllib2 import Request, urlopen, HTTPError, URLError
except ImportError:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

# 环境变量获取参数
ip = os.environ.get("EASYOPS_COLLECTOR_ip", "127.0.0.1")
port = os.environ.get("EASYOPS_COLLECTOR_port", "8080")
manager_path = os.environ.get("EASYOPS_COLLECTOR_manager_path", "/manager/status/all")
username = os.environ.get("EASYOPS_COLLECTOR_username", "")
password = os.environ.get("EASYOPS_COLLECTOR_password", "")
install_path = os.environ.get("EASYOPS_COLLECTOR_installPath", "")


def parse_tomcat_status(html):
    """解析 Tomcat Manager 状态页面"""
    metrics = {}

    # JVM 内存信息
    jvm_match = re.search(r'Free memory:\s*([\d.]+)\s*MB.*?Total memory:\s*([\d.]+)\s*MB.*?Max memory:\s*([\d.]+)\s*MB', html, re.DOTALL)
    if jvm_match:
        metrics['jvm_free_memory_mb'] = float(jvm_match.group(1))
        metrics['jvm_total_memory_mb'] = float(jvm_match.group(2))
        metrics['jvm_max_memory_mb'] = float(jvm_match.group(3))
        metrics['jvm_used_memory_mb'] = metrics['jvm_total_memory_mb'] - metrics['jvm_free_memory_mb']
        metrics['jvm_memory_usage_pct'] = round(metrics['jvm_used_memory_mb'] / metrics['jvm_max_memory_mb'] * 100, 2)

    # 线程池信息 (HTTP Connector)
    thread_match = re.search(r'Max threads:\s*(\d+).*?Current thread count:\s*(\d+).*?Current thread busy:\s*(\d+)', html, re.DOTALL)
    if thread_match:
        metrics['max_threads'] = int(thread_match.group(1))
        metrics['current_threads'] = int(thread_match.group(2))
        metrics['busy_threads'] = int(thread_match.group(3))
        metrics['thread_usage_pct'] = round(metrics['busy_threads'] / metrics['max_threads'] * 100, 2)

    # 请求统计
    req_match = re.search(r'Max processing time:\s*(\d+)\s*ms.*?Request count:\s*(\d+).*?Error count:\s*(\d+)', html, re.DOTALL)
    if req_match:
        metrics['max_processing_time_ms'] = int(req_match.group(1))
        metrics['request_count'] = int(req_match.group(2))
        metrics['error_count'] = int(req_match.group(3))

    return metrics


def fetch_status():
    """获取 Tomcat 状态"""
    url = "http://{0}:{1}{2}?XML=true".format(ip, port, manager_path)

    headers = {}
    if username and password:
        auth = base64.b64encode("{0}:{1}".format(username, password).encode()).decode()
        headers['Authorization'] = 'Basic ' + auth

    try:
        req = Request(url, headers=headers)
        response = urlopen(req, timeout=30)
        content = response.read().decode('utf-8')
        return True, content, response.getcode()
    except HTTPError as e:
        return False, str(e.reason), e.code
    except URLError as e:
        return False, str(e.reason), -1
    except Exception as e:
        return False, str(e), -1


if __name__ == "__main__":
    info = []
    dims = {"ip": ip, "installPath": install_path}

    success, content, status_code = fetch_status()

    if success:
        metrics = parse_tomcat_status(content)
        tmp = {"dims": dims, "vals": {"status": 1, "status_code": status_code}}
        tmp["vals"].update(metrics)
        info.append(tmp)
    else:
        info.append({
            "dims": dims,
            "vals": {
                "status": 0,
                "status_code": status_code,
                "error_msg": content
            }
        })

    print(json.dumps(info, ensure_ascii=False))
