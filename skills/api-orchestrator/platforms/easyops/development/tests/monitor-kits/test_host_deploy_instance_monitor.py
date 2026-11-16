import hashlib
import hmac
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import unittest
import uuid
import zipfile
from contextlib import redirect_stderr

import yaml
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[2] / "monitor-kits/host-deploy-instance-monitoring"
SOURCE = KIT / "src/host_deploy_instance_monitor.py"
PACKAGE = Path(__file__).resolve().parents[3] / "hub/monitor-kits/监控套件_主机部署实例监控_0.1.11.zip"
WORKTREE_ROOT = Path(__file__).resolve().parents[7]


def module():
    namespace = {"__name__": "host_deploy_instance_monitor_test"}
    exec(compile(SOURCE.read_bytes(), str(SOURCE), "exec"), namespace)
    return namespace


class HostDeployInstanceMonitorTests(unittest.TestCase):
    def test_config(self):
        m = module()
        env = {
            "EASYOPS_COLLECTOR_instanceId": "65eb86f148251",
            "EASYOPS_COLLECTOR_hostUuid": "f907bc31-c391-4518-be14-fe50d827bfd8",
            "EASYOPS_COLLECTOR_hostIp": "192.168.110.24",
            "EASYOPS_COLLECTOR_cacheTtlDays": "7",
            "EASYOPS_COLLECTOR_sampleInterval": "0.2",
            "EASYOPS_COLLECTOR_requestTimeout": "10",
            "EASYOPS_COLLECTOR_logLevel": "DEBUG",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = m["config"]()
        self.assertEqual(settings["hostInstanceId"], "65eb86f148251")
        self.assertEqual(settings["cacheTtlSeconds"], 604800)
        self.assertEqual(settings["logLevel"], "DEBUG")
        with mock.patch.dict(m, {"resolve_openapi_gateway": mock.Mock(return_value=("http://192.168.110.24", "agentConfig"))}):
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(m["config"]()["gateway"], "http://192.168.110.24")
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_instanceId": "$.instanceId"}, clear=True):
            with self.assertRaises(ValueError):
                m["config"]()

    def test_openapi_gateway_from_agent_config(self):
        m = module()
        payload = b"""base:\n  client_id: 1888\nreport:\n  server_groups:\n    - hosts:\n        - ip: 10.0.0.2\ncommand:\n  server_groups:\n    - name: default\n      hosts:\n        - ip: 192.168.110.24,192.168.110.25\n          port: 5511\n"""
        with mock.patch.dict(m, {"read_file": mock.Mock(return_value=payload)}):
            self.assertEqual(m["gateway_from_agent_config"]("/agent/conf.yaml"), "http://192.168.110.24")
        self.assertEqual(m["resolve_openapi_gateway"]("http://10.1.1.1/"), ("http://10.1.1.1", "param"))
        with mock.patch.dict(m, {
            "agent_config_paths": mock.Mock(return_value=["/agent/conf.yaml"]),
            "read_file": mock.Mock(return_value=payload),
        }):
            self.assertEqual(m["resolve_openapi_gateway"]("http://10.1.1.1/"), ("http://192.168.110.24", "agentConfig"))

    def test_process_match_prefers_process_list(self):
        m = module()
        process = {
            "pid": 123, "comm": "redis-server", "state": "R", "utime": 10.0,
            "stime": 5.0, "threads": 4, "startTimeTicks": 100.0,
            "cmdline": "./bin/redis-server ./conf/redis.conf",
            "cwd": "/data/easyops/redis/data",
        }
        target = {
            "instanceId": "65df0395e33cd", "installPath": "/usr/local/easyops/redis",
            "ports": ["6379"],
            "processList": [{"pname": "redis-server", "cmdline": "./bin/redis-server", "cwd": "/data/easyops/redis"}],
        }
        self.assertEqual(m["match_target_processes"](target, [process]), [process])

    def test_keyword_group_requires_all_keywords(self):
        m = module()
        process = {"pid": 1, "cmdline": "/usr/local/easyops/java -Dapp=api", "cwd": "/"}
        self.assertTrue(m["match_keyword_group"](process, {"cmdline": ["/usr/local/easyops/java", "-Dapp=api"]}))
        self.assertFalse(m["match_keyword_group"](process, {"cmdline": ["/usr/local/easyops/java", "-Dapp=web"]}))

    def test_windows_process_and_netstat_parsers(self):
        m = module()
        self.assertEqual(m["parse_windows_datetime"]("20261116103000.123456+480"), 1794796200.123456)
        self.assertEqual(m["parse_windows_datetime"]("20261116103000.123456-480"), 1794853800.123456)
        process = m["parse_windows_process_row"]({
            "ProcessId": 123, "Name": "app.exe",
            "CommandLine": r"C:\Program Files\App\app.exe --port 8080",
            "ExecutablePath": r"C:\Program Files\App\app.exe",
            "CreationDate": "20261116103000.123456+480",
            "UserModeTime": 10000000, "KernelModeTime": 5000000,
            "ThreadCount": 4, "WorkingSetSize": 1024, "HandleCount": 32,
        })
        self.assertEqual(process["utime"], 1.0)
        self.assertEqual(process["stime"], 0.5)
        self.assertEqual(process["start_timestamp"], 1794796200.123456)
        self.assertEqual(process["fd_count"], 32)
        netstat = (
            "  Proto  Local Address          Foreign Address        State           PID\r\n"
            "  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       123\r\n"
            "  TCP    [::]:8080              [::]:0                 LISTENING       123\r\n"
        )
        self.assertEqual(m["parse_windows_netstat"](netstat), {8080: {"123"}})

    def test_windows_target_collect_and_path_matching(self):
        m = module()
        process = {
            "pid": 123, "comm": "app.exe", "state": "", "utime": 1.0,
            "stime": 0.5, "threads": 4, "start_timestamp": 1794796200.0,
            "cmdline": r"c:\program files\app\app.exe --port 8080", "cwd": "",
            "memory_bytes": 1024.0, "fd_count": 32,
        }
        refreshed = dict(process, utime=1.2, stime=0.5)
        settings = {"hostInstanceId": "host1", "sampleInterval": 0.0, "logLevel": "ERROR", "windows": True}
        target = {
            "instanceId": "deploy1", "installPath": r"C:\Program Files\App",
            "ports": [8080],
            "processList": [{"pname": "APP.EXE", "cmdline": r"c:\program files\app\app.exe"}],
        }
        clocks = iter([101.0, 102.0])
        with mock.patch.object(m["time"], "sleep"), mock.patch.object(m["time"], "time", side_effect=lambda: next(clocks)), \
             mock.patch.dict(m, {
                 "IS_WINDOWS": True,
                 "refresh_process_record": mock.Mock(return_value=refreshed),
                 "process_socket_inodes": mock.Mock(return_value=({"123"}, True)),
                 "process_memory_bytes": mock.Mock(return_value=1024.0),
                 "process_fd_usage": mock.Mock(return_value=(32, -1)),
                 "windows_process_snapshot": mock.Mock(),
             }):
            with redirect_stderr(io.StringIO()):
                result = m["collect_target"](target, [process], {8080: {"123"}}, -1.0, 100.0, 2048.0, settings, 1794791500.0, 10.0, 1.0, 1)
        process_row, port_row, target_row = result
        self.assertEqual(process_row["vals"]["deploy_instance_process_alive"], 1.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_start_timestamp"], 1794796200.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_memory_percent"], 50.0)
        self.assertAlmostEqual(process_row["vals"]["deploy_instance_process_cpu_percent"], 20.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_fd_count"], 32.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_fd_usage_percent"], -1.0)
        self.assertEqual(port_row["dims"]["port"], "8080")
        self.assertEqual(port_row["vals"]["deploy_instance_port_listen"], 1.0)
        self.assertEqual(set().union(*(row["vals"] for row in result)), set(m["METRIC_KEYS"]))

    def test_collect_target_metrics(self):
        m = module()
        process = {
            "pid": 123, "comm": "redis-server", "state": "R", "utime": 10.0,
            "stime": 5.0, "threads": 4, "startTimeTicks": 100.0,
            "cmdline": "./bin/redis-server ./conf/redis.conf",
            "cwd": "/data/easyops/redis/data",
        }
        refreshed = dict(process)
        refreshed.update({"utime": 16.0, "stime": 5.0})
        settings = {
            "hostInstanceId": "host1", "sampleInterval": 0.0, "logLevel": "DEBUG",
        }
        target = {
            "instanceId": "deploy1", "installPath": "/usr/local/easyops/redis",
            "ports": ["6379"],
            "processList": [{"pname": "redis-server", "cmdline": "./bin/redis-server"}],
        }
        clocks = iter([101.0, 102.0])
        with mock.patch.object(m["time"], "sleep"), mock.patch.object(m["time"], "time", side_effect=lambda: next(clocks)), \
            mock.patch.dict(m, {"read_file": mock.Mock(return_value=b"123 (redis-server) R"), "parse_proc_stat": mock.Mock(return_value=refreshed), "process_socket_inodes": mock.Mock(return_value=({"inode1"}, True)), "process_memory_bytes": mock.Mock(return_value=1000.0), "process_fd_usage": mock.Mock(return_value=(100, 1024))}):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = m["collect_target"](target, [process], {6379: {"inode1"}}, 1000.0, 100.0, 2000.0, settings, 2000.0, 10.0, 1.0, 1)
        self.assertEqual(len(result), 3)
        process_row, port_row, target_row = result
        self.assertEqual(process_row["dims"]["deployInstanceId"], "deploy1")
        self.assertEqual(process_row["dims"]["cmdline"], "./bin/redis-server ./conf/redis.conf")
        self.assertEqual(process_row["vals"]["deploy_instance_process_alive"], 1.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_start_timestamp"], 1001.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_uptime_seconds"], 999.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_cpu_percent"], 6.0)
        self.assertEqual(process_row["vals"]["deploy_instance_process_memory_percent"], 50.0)
        self.assertAlmostEqual(process_row["vals"]["deploy_instance_process_fd_usage_percent"], 9.765625)
        self.assertEqual(set().union(*(row["vals"] for row in result)), set(m["METRIC_KEYS"]))
        self.assertEqual(set(process_row["vals"]), set(m["PROCESS_METRIC_KEYS"]))
        self.assertEqual(port_row["dims"]["port"], "6379")
        self.assertEqual(port_row["vals"]["deploy_instance_port_listen"], 1.0)
        self.assertEqual(port_row["vals"]["deploy_instance_listening_port_count"], 1.0)
        self.assertEqual(port_row["vals"]["deploy_instance_port_missing_count"], 0.0)
        self.assertEqual(set(port_row["vals"]), set(m["PORT_METRIC_KEYS"]))
        self.assertNotIn("cmdline", target_row["dims"])
        self.assertNotIn("port", target_row["dims"])
        self.assertEqual(set(target_row["vals"]), set(m["TARGET_METRIC_KEYS"]))
        log_rows = [json.loads(line) for line in stderr.getvalue().splitlines()]
        self.assertEqual({row["stage"] for row in log_rows}, {"target.start", "port.match", "process.metrics", "port.metrics", "target.metrics"})
        self.assertTrue(all(row["level"] == "DEBUG" for row in log_rows))
        self.assertNotIn("./bin/redis-server", stderr.getvalue())
        self.assertNotIn("accessKey", stderr.getvalue())
        self.assertNotIn("secretKey", stderr.getvalue())

    def test_collect_target_fallback_logs_traceback_and_five_metrics(self):
        m = module()
        settings = {
            "hostInstanceId": "host1", "hostUuid": "uuid", "hostIp": "ip",
            "gateway": "http://gateway", "accessKey": "ak", "secretKey": "sk",
            "sampleInterval": 0.0, "cacheTtlSeconds": 604800.0, "logLevel": "DEBUG",
        }
        target = {"instanceId": "deploy1", "installPath": "/redis"}
        with mock.patch.dict(m, {
            "ensure_cache": mock.Mock(return_value=({"refreshedAt": 1990.0, "targets": [target]}, 1.0)),
            "list_processes": mock.Mock(return_value=[]),
            "listening_ports": mock.Mock(return_value={}),
            "boot_time": mock.Mock(return_value=1000.0),
            "clock_ticks": mock.Mock(return_value=100.0),
            "memory_total_bytes": mock.Mock(return_value=2000.0),
            "collect_target": mock.Mock(side_effect=RuntimeError("target boom")),
        }):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = m["collect"](settings)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["vals"]), {
            "deploy_instance_config_valid", "deploy_instance_collect_success",
            "host_deploy_instance_target_count", "host_deploy_cache_age_seconds",
            "host_deploy_cache_refresh_success",
        })
        log_rows = [json.loads(line) for line in stderr.getvalue().splitlines()]
        failed = next(row for row in log_rows if row["stage"] == "target.collect_failed")
        self.assertEqual(failed["level"], "ERROR")
        self.assertEqual(failed["fallbackMetricCount"], 5)
        self.assertIn("RuntimeError: target boom", failed["traceback"])

    def test_collect_target_splits_process_and_port_dimensions(self):
        m = module()
        first = {"pid": 123, "comm": "redis-server", "state": "R", "utime": 10.0, "stime": 5.0, "threads": 4, "startTimeTicks": 100.0, "cmdline": "redis-server", "cwd": "/redis"}
        second = {"pid": 456, "comm": "redis-sentinel", "state": "R", "utime": 4.0, "stime": 2.0, "threads": 2, "startTimeTicks": 120.0, "cmdline": "redis-sentinel", "cwd": "/redis"}
        refreshed_first = dict(first, utime=12.0, stime=5.0)
        refreshed_second = dict(second, utime=5.0, stime=2.0)
        target = {"instanceId": "deploy1", "installPath": "/redis", "ports": [6379, 26379]}
        clocks = iter([101.0, 102.0])
        with mock.patch.object(m["time"], "sleep"), mock.patch.object(m["time"], "time", side_effect=lambda: next(clocks)), \
             mock.patch.dict(m, {"parse_proc_stat": mock.Mock(side_effect=[refreshed_first, refreshed_second]), "process_socket_inodes": mock.Mock(return_value=({"inode1"}, True)), "process_memory_bytes": mock.Mock(side_effect=[1000.0, 3000.0]), "process_fd_usage": mock.Mock(side_effect=[(100, 1024), (200, 2048)])}):
            with redirect_stderr(io.StringIO()):
                rows = m["collect_target"](target, [first, second], {6379: {"inode1"}}, 1000.0, 100.0, 4000.0, {"hostInstanceId": "host1", "sampleInterval": 0.0}, 2000.0, 10.0, 1.0, 1)
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["dims"].get("cmdline") for row in rows[:2]], ["redis-server", "redis-sentinel"])
        self.assertEqual(rows[2]["dims"]["port"], "6379")
        self.assertEqual(rows[2]["vals"]["deploy_instance_port_listen"], 1.0)
        self.assertEqual(rows[3]["dims"]["port"], "26379")
        self.assertEqual(rows[3]["vals"]["deploy_instance_port_listen"], 0.0)
        self.assertEqual(rows[3]["vals"]["deploy_instance_port_missing_count"], 1.0)

    def test_cache_valid_and_stale_fallback(self):
        m = module()
        cache_root = WORKTREE_ROOT / ".local" / ("test-cache-" + uuid.uuid4().hex)
        cache_root.mkdir(parents=True)
        try:
            settings = {
                "hostInstanceId": "host1", "hostUuid": "uuid", "hostIp": "ip",
                "cacheDir": str(cache_root), "cacheTtlSeconds": 60,
            }
            data = {"version": 1, "refreshedAt": time.time() - 10, "targets": []}
            m["write_json_atomic"](m["cache_path"](settings), data)
            with redirect_stderr(io.StringIO()):
                cache, success = m["ensure_cache"](settings, time.time())
            self.assertEqual(success, 1.0)
            self.assertEqual(cache["targets"], [])
            data["refreshedAt"] = time.time() - 100000
            m["write_json_atomic"](m["cache_path"](settings), data)
            with redirect_stderr(io.StringIO()):
                cache, success = m["ensure_cache"](settings, time.time())
            self.assertEqual(success, 0.0)
            self.assertEqual(cache["targets"], [])
            self.assertEqual(os.stat(m["cache_path"](settings)).st_mode & 0o777, 0o600)
        finally:
            shutil.rmtree(cache_root)

    def test_openapi_signature(self):
        m = module()
        body = '{"query":{"isMonitor":"是"}}'.encode('utf-8')
        with mock.patch.object(m["time"], "time", return_value=1700000000):
            query = m["sign_openapi"]("POST", m["OPENAPI_PATH"], "application/json", body, "ak", "sk")
        expected = hmac.new(b"sk", ("POST\n%s\n\napplication/json\n%s\n1700000000\nak" % (m["OPENAPI_PATH"], hashlib.md5(body).hexdigest())).encode("utf-8"), hashlib.sha1).hexdigest()
        self.assertEqual(query, {"accesskey": "ak", "signature": expected, "expires": "1700000000"})

    def test_help_and_version(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--version"], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "0.1.11")

    def test_python2_json_output_uses_ascii_escape(self):
        source = SOURCE.read_text(encoding="utf-8")
        orig = SOURCE.with_suffix(".orig").read_text(encoding="utf-8")
        self.assertNotIn("ensure_ascii=False", source)
        self.assertNotIn("ensure_ascii=False", orig)
        self.assertEqual(source, orig)

    def test_python_source_allows_parameter_injection_before_imports(self):
        source = SOURCE.read_text(encoding="utf-8")
        orig = SOURCE.with_suffix(".orig").read_text(encoding="utf-8")
        self.assertNotIn("from __future__", source)
        self.assertNotIn("from __future__", orig)
        lines = source.splitlines(keepends=True)
        injected = "".join(lines[:2] + ["import os\n"] + lines[2:])
        compile(injected, "platform-injected-host-deploy-instance-monitor.py", "exec")

    def test_parameter_display_and_plain_credential_mode(self):
        plugin = yaml.safe_load((KIT / "plugin.yaml").read_text(encoding="utf-8"))
        params = {row["name"]: row for row in plugin["paramDefine"]}
        for name in ("instanceId", "hostUuid", "hostIp"):
            self.assertFalse(params[name]["display"])
        self.assertFalse(params["openapiGateway"]["display"])
        self.assertTrue(params["openapiGateway"]["optional"])
        for name in ("openapiAkText", "openapiSkText"):
            self.assertTrue(params[name]["display"])
            self.assertEqual(params[name]["valueType"], "string")
            self.assertEqual(params[name]["use"], "collectParams")
            self.assertFalse(params[name]["isFromSecret"])
            self.assertFalse(params[name]["isEncrypt"])
        for name in ("openapiAk", "openapiSk", "openapiAccessKey", "openapiSecretKey"):
            self.assertNotIn(name, params)
        self.assertEqual(params["logLevel"]["valueType"], "string")
        self.assertEqual(params["logLevel"]["defaultValue"], "ERROR")
        self.assertEqual(params["logLevel"]["use"], "collectParams")
        self.assertFalse(params["logLevel"]["isFromSecret"])
        self.assertFalse(params["logLevel"]["isEncrypt"])

    def test_definitions_and_package(self):
        origins = json.loads((KIT / "origin_metric.json").read_text(encoding="utf-8"))
        aliases = json.loads((KIT / "alias_metric.json").read_text(encoding="utf-8"))
        metric_sets = json.loads((KIT / "metric_set.json").read_text(encoding="utf-8"))
        origin_dimensions = {row["key"]: set(row["labels"]) for row in origins}
        self.assertEqual(len(origins), 22)
        self.assertEqual({row["key"] for row in origins}, {row["name"] for row in aliases})
        for alias in aliases:
            self.assertEqual({row["dimName"] for row in alias["dims"]}, origin_dimensions[alias["originalMetrics"][0]])
        for key, dimensions in origin_dimensions.items():
            if key.startswith("deploy_instance_process"):
                self.assertIn("cmdline", dimensions)
            if key.startswith("deploy_instance_port") or key in ("deploy_instance_expected_port_count", "deploy_instance_listening_port_count"):
                self.assertIn("port", dimensions)
        self.assertTrue(all(isinstance(row, dict) and row.get("name") for row in metric_sets))
        self.assertEqual({row["name"] for row in metric_sets}, {name for row in aliases for name in row["metricSet"]})
        if not PACKAGE.exists():
            self.skipTest("package not built yet")
        with zipfile.ZipFile(PACKAGE) as package:
            self.assertEqual(package.namelist()[0], "主机部署实例监控/")
            packaged_plugin = yaml.safe_load(package.read("主机部署实例监控/plugin.yaml").decode("utf-8"))
            packaged_params = {row["name"]: row for row in packaged_plugin["paramDefine"]}
            for name in ("instanceId", "hostUuid", "hostIp"):
                self.assertFalse(packaged_params[name]["display"])
            self.assertFalse(packaged_params["openapiGateway"]["display"])
            self.assertTrue(packaged_params["openapiGateway"]["optional"])
            for name in ("openapiAkText", "openapiSkText"):
                self.assertTrue(packaged_params[name]["display"])
                self.assertEqual(packaged_params[name]["valueType"], "string")
                self.assertEqual(packaged_params[name]["use"], "collectParams")
                self.assertFalse(packaged_params[name]["isFromSecret"])
                self.assertFalse(packaged_params[name]["isEncrypt"])
            packaged_metric_sets = json.loads(package.read("主机部署实例监控/metric_set.json").decode("utf-8"))
            self.assertEqual(packaged_metric_sets, metric_sets)
            packaged_origins = json.loads(package.read("主机部署实例监控/origin_metric.json").decode("utf-8"))
            self.assertEqual(packaged_origins, origins)
            for item in package.infolist():
                self.assertEqual(stat.S_IMODE(item.external_attr >> 16), 0o755 if item.is_dir() else 0o664)


if __name__ == "__main__":
    unittest.main()
