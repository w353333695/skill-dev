import hashlib
import hmac
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

import yaml
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[2] / "monitor-kits/host-deploy-instance-monitoring"
SOURCE = KIT / "src/host_deploy_instance_monitor.py"
PACKAGE = Path(__file__).resolve().parents[3] / "hub/monitor-kits/监控套件_主机部署实例监控_0.1.8.zip"
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
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = m["config"]()
        self.assertEqual(settings["hostInstanceId"], "65eb86f148251")
        self.assertEqual(settings["cacheTtlSeconds"], 604800)
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_instanceId": "$.instanceId"}, clear=True):
            with self.assertRaises(ValueError):
                m["config"]()

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
            "hostInstanceId": "host1", "sampleInterval": 0.0,
        }
        target = {
            "instanceId": "deploy1", "installPath": "/usr/local/easyops/redis",
            "ports": ["6379"],
            "processList": [{"pname": "redis-server", "cmdline": "./bin/redis-server"}],
        }
        clocks = iter([101.0, 102.0])
        with mock.patch.object(m["time"], "sleep"), mock.patch.object(m["time"], "time", side_effect=lambda: next(clocks)), \
             mock.patch.dict(m, {"parse_proc_stat": mock.Mock(return_value=refreshed), "process_socket_inodes": mock.Mock(return_value=({"inode1"}, True)), "process_memory_bytes": mock.Mock(return_value=1000.0), "process_fd_usage": mock.Mock(return_value=(100, 1024))}):
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
            cache, success = m["ensure_cache"](settings, time.time())
            self.assertEqual(success, 1.0)
            self.assertEqual(cache["targets"], [])
            data["refreshedAt"] = time.time() - 100000
            m["write_json_atomic"](m["cache_path"](settings), data)
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
        self.assertEqual(result.stdout.strip(), "0.1.8")

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
        for name in ("openapiAkText", "openapiSkText"):
            self.assertTrue(params[name]["display"])
            self.assertEqual(params[name]["valueType"], "string")
            self.assertEqual(params[name]["use"], "collectParams")
            self.assertFalse(params[name]["isFromSecret"])
            self.assertFalse(params[name]["isEncrypt"])
        for name in ("openapiAk", "openapiSk", "openapiAccessKey", "openapiSecretKey"):
            self.assertNotIn(name, params)

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
