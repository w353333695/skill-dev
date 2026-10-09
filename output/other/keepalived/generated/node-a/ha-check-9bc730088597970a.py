#!/usr/bin/python3.11
# 自动生成：本机服务健康检查，修改源 YAML 后重新生成。
SPEC = {'policy': 'all', 'round_timeout': 5, 'checks': [{'name': 'nginx_process', 'type': 'process', 'match': 'name', 'pattern': '^nginx$', 'min_count': 1, 'timeout': 1}, {'name': 'api_tcp', 'type': 'tcp', 'host': '127.0.0.1', 'port': 8080, 'timeout': 1}, {'name': 'api_ready', 'type': 'http', 'url': 'http://127.0.0.1:8080/ready', 'timeout': 1, 'expected_status': [200], 'body_contains': '"ready":true'}]}

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
