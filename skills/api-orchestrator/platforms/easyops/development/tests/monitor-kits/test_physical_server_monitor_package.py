"""验证物理服务器 SNMP 监控套件的导入目录、权限和元数据。"""
import json
import io
import logging
import yaml
from contextlib import redirect_stdout
import re
from unittest.mock import patch
import os
from pathlib import Path
import stat
import unittest
import zipfile


class PackageImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = Path(__file__).resolve().parents[3] / "hub" / "monitor-kits" / "物理服务器SNMP监控套件_0.1.5.zip"
        cls.archive = zipfile.ZipFile(os.environ.get("MONITOR_PACKAGE", str(default)))
        cls.root = "物理服务器SNMP监控/"

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_root_matches_plugin_name(self):
        plugin = self.archive.read(self.root + "plugin.yaml").decode("utf-8")
        name = re.search(r"(?m)^name: (.+)$", plugin).group(1)
        self.assertEqual(self.root, name + "/")
        self.assertIn('version: "%s"' % os.environ.get('MONITOR_PACKAGE_VERSION', '0.1.5'), plugin)
        self.assertIn("samplerType: metric_sampler", plugin)
        self.assertIn("scriptType: python", plugin)

    def test_directories_and_read_permissions(self):
        self.assertTrue(self.archive.getinfo(self.root).is_dir())
        names = set(self.archive.namelist())
        for entry in self.archive.infolist():
            self.assertTrue(entry.filename.startswith(self.root))
            mode = entry.external_attr >> 16
            self.assertEqual(stat.S_IMODE(mode), 0o755 if entry.is_dir() else 0o664)
            parent = str(Path(entry.filename.rstrip("/")).parent)
            if parent != ".":
                self.assertIn(parent + "/", names)
            self.assertNotIn("__pycache__", entry.filename)

    def test_original_script_survives_backend_regeneration(self):
        original = self.archive.read(self.root + "src/物理服务器SNMP监控.orig").decode("utf-8")
        params = ["ip", "port", "version", "community", "username", "auth_key", "auth_protocol", "priv_key", "priv_protocol", "log_level"]
        prefix = "import os\n" + "".join('%s = os.environ.get("EASYOPS_COLLECTOR_%s")\n' % (name, name) for name in params)
        namespace = {"__name__": "rename_test"}
        environment = {"EASYOPS_COLLECTOR_" + name: "example" for name in params}
        environment["EASYOPS_COLLECTOR_ip"] = "192.0.2.8"
        environment["EASYOPS_COLLECTOR_port"] = "1161"
        environment["EASYOPS_COLLECTOR_version"] = "2c"
        regenerated = compile(prefix + original, "renamed-monitor.py", "exec")
        with patch.dict(os.environ, environment):
            exec(regenerated, namespace)
        for name in params:
            self.assertEqual(namespace[name], environment["EASYOPS_COLLECTOR_" + name])
        self.assertIn("huawei", namespace["PROFILES"])
        self.assertIn("dell", namespace["PROFILES"])

    def test_original_has_no_generated_bindings(self):
        original = self.archive.read(self.root + "src/物理服务器SNMP监控.orig").decode("utf-8")
        self.assertNotIn("from __future__ import", original)
        self.assertNotRegex(original, r'(?m)^\w+\s*=\s*os\.environ\.get\("EASYOPS_COLLECTOR_')

    def test_published_script_retains_environment_bindings(self):
        script = self.archive.read(self.root + "src/物理服务器SNMP监控.py").decode("utf-8")
        for name in ["ip", "port", "version", "community", "username", "auth_key", "auth_protocol", "priv_key", "priv_protocol", "log_level"]:
            binding = '%s = os.environ.get("EASYOPS_COLLECTOR_%s")' % (name, name)
            self.assertEqual(script.count(binding), 1)

    def test_alias_display_names_have_namespace_and_are_unique(self):
        aliases = json.loads(self.archive.read(self.root + "alias_metric.json"))
        identities = [(row["objectId"], row["displayName"]) for row in aliases]
        self.assertEqual(len(identities), len(set(identities)))
        for row in aliases:
            self.assertTrue(row["displayName"].startswith("物理机SNMP-"))
            self.assertNotIn(row["displayName"], ("电源状态", "风扇状态", "温度"))

    def test_metric_references_and_runtime_dimensions(self):
        origins = json.loads(self.archive.read(self.root + "origin_metric.json"))
        aliases = json.loads(self.archive.read(self.root + "alias_metric.json"))
        groups = {row["name"] for row in json.loads(self.archive.read(self.root + "metric_set.json"))}
        origin_by_key = {row["key"]: row for row in origins}
        namespace = {"__name__": "dimension_test"}
        exec(compile(self.archive.read(self.root + "src/物理服务器SNMP监控.py"), "monitor.py", "exec"), namespace)
        plugin = self.archive.read(self.root + "plugin.yaml").decode("utf-8")
        self.assertIn("agentType: easyops", plugin)
        for origin in origins:
            self.assertEqual(origin["agentType"], "easyops")
            record = namespace["metric"](origin["key"], 1, "component")
            self.assertEqual(set(record["dims"]), {tag["name"] for tag in origin["tagDefine"]})
        for alias in aliases:
            self.assertTrue(set(alias["metricSet"]).issubset(groups))
            self.assertTrue(set(alias["originalMetrics"]).issubset(origin_by_key))
            tags = {tag["name"] for key in alias["originalMetrics"] for tag in origin_by_key[key]["tagDefine"]}
            self.assertEqual({dimension["originDimName"] for dimension in alias["dims"]}, tags)

    def test_main_stdout_is_json_with_matching_dimensions(self):
        namespace = {"__name__": "output_test"}
        exec(compile(self.archive.read(self.root + "src/物理服务器SNMP监控.py"), "monitor.py", "exec"), namespace)
        namespace["ip"] = "192.0.2.1"
        namespace["vendor"] = lambda response: "fixture"
        namespace["PROFILES"]["fixture"] = {
            "cpu": ["1.1"], "mem": ["1.2"], "temp": ["1.3"],
            "fan": ["1.4"], "power": ["1.5"]}
        oid = namespace["OID"]
        tables = {root: {root + ".1": "INTEGER: 1"} for root in ("1.1", "1.2", "1.3", "1.4", "1.5")}
        for key, value in (("hrSize", "INTEGER: 100"), ("hrUsed", "INTEGER: 25"),
                           ("ifName", "STRING: sfp1"), ("ifOper", "INTEGER: 1"),
                           ("ifAdmin", "INTEGER: 1"), ("ifIn", "Counter64: 100"), ("ifOut", "Counter64: 200")):
            tables[oid[key]] = {oid[key] + ".1": value}
        class FixtureTransport:
            def get(self, requested):
                return "fixture"
            def walk(self, requested):
                return tables.get(requested, {})
        namespace["SNMP"] = FixtureTransport
        output = io.StringIO()
        with redirect_stdout(output):
            namespace["main"]()
        records = json.loads(output.getvalue())
        origins = {row["key"]: row for row in json.loads(self.archive.read(self.root + "origin_metric.json"))}
        self.assertEqual({key for record in records for key in record["vals"]}, set(origins))
        for record in records:
            key = next(iter(record["vals"]))
            self.assertEqual(set(record["dims"]), {tag["name"] for tag in origins[key]["tagDefine"]})
        self.assertNotIn("GATHERING DATA", output.getvalue())

    def load_runtime(self, environment=None):
        namespace = {"__name__": "runtime_test"}
        with patch.dict(os.environ, environment or {}, clear=True):
            exec(compile(self.archive.read(self.root + "src/物理服务器SNMP监控.py"), "monitor.py", "exec"), namespace)
        return namespace

    def test_cmdb_parameters_do_not_use_encryption_or_secret(self):
        plugin = yaml.safe_load(self.archive.read(self.root + "plugin.yaml"))
        for parameter in plugin["paramDefine"]:
            if str(parameter.get("defaultValue", "")).startswith("$."):
                self.assertFalse(parameter["isEncrypt"], parameter["name"])
                self.assertFalse(parameter["isFromSecret"], parameter["name"])
        port = next(parameter for parameter in plugin["paramDefine"] if parameter["name"] == "port")
        self.assertTrue(port["optional"])

    def test_port_normalizes_missing_values_and_preserves_configured_value(self):
        for value in ("", "null", "None", "undefined", "  null  ", "$.snmp_conf.snmpPort"):
            with self.subTest(value=value):
                runtime = self.load_runtime({"EASYOPS_COLLECTOR_port": value})
                self.assertEqual(runtime["port"], "161")
        self.assertEqual(self.load_runtime()["port"], "161")
        self.assertEqual(self.load_runtime({"EASYOPS_COLLECTOR_port": "1161"})["port"], "1161")
        self.assertEqual(self.load_runtime({"EASYOPS_COLLECTOR_port": "null", "EASYOPS_COLLECTOR_snmpPort": "1161"})["port"], "1161")

    def test_log_level_is_configurable_with_error_default(self):
        plugin = yaml.safe_load(self.archive.read(self.root + "plugin.yaml"))
        parameter = next(parameter for parameter in plugin["paramDefine"] if parameter["name"] == "log_level")
        self.assertEqual(parameter["defaultValue"], "ERROR")
        self.assertIn("log_level", plugin["params"])
        runtime = self.load_runtime()
        self.assertEqual(runtime["LOG"].level, logging.ERROR)
        runtime = self.load_runtime({"EASYOPS_COLLECTOR_log_level": "debug"})
        self.assertEqual(runtime["LOG"].level, logging.DEBUG)
        self.load_runtime()

    def test_missing_metric_value_is_warned(self):
        runtime = self.load_runtime()
        with self.assertLogs(runtime["LOG"], level="WARNING") as captured:
            self.assertIsNone(runtime["metric"]("snmp.server.cpu.utilization", None, "cpu0"))
        self.assertIn("snmp.server.cpu.utilization", " ".join(captured.output))
        self.assertIn("cpu0", " ".join(captured.output))

    def test_partial_collection_warns_for_missing_metrics_without_blocking(self):
        runtime = self.load_runtime({"EASYOPS_COLLECTOR_ip": "192.0.2.1"})
        runtime["vendor"] = lambda response: "fixture"
        runtime["PROFILES"]["fixture"] = {"cpu": ["1.1"]}
        class PartialTransport:
            def get(self, requested):
                return "fixture"
            def walk(self, requested):
                return {"1.1.1": "INTEGER: 10"} if requested == "1.1" else {}
        runtime["SNMP"] = PartialTransport
        output = io.StringIO()
        with self.assertLogs(runtime["LOG"], level="WARNING") as captured, redirect_stdout(output):
            runtime["main"]()
        self.assertEqual(len(json.loads(output.getvalue())), 1)
        warnings = " ".join(captured.output)
        for key in runtime["METRIC_DIMENSIONS"]:
            if key != "snmp.server.cpu.utilization":
                self.assertIn(key, warnings)

    def test_snmp_nonzero_exit_and_empty_output_are_warned_and_redacted(self):
        runtime = self.load_runtime({"EASYOPS_COLLECTOR_community": "private-fixture-token"})
        process = type("Process", (), {"returncode": 1, "communicate": lambda self: (b"", b"private-fixture-token: timeout")})()
        with patch.object(runtime["subprocess"], "Popen", return_value=process), self.assertLogs(runtime["LOG"], level="WARNING") as captured:
            self.assertEqual(runtime["SNMP"]().walk("1.2.3"), {})
        messages = " ".join(captured.output)
        self.assertIn("1.2.3", messages)
        self.assertNotIn("private-fixture-token", messages)

    def test_debug_logs_complete_redacted_command_response_and_parsing(self):
        secret = 'debug-secret-"quoted"'
        runtime = self.load_runtime({"EASYOPS_COLLECTOR_log_level": "DEBUG", "EASYOPS_COLLECTOR_community": secret})
        raw = ('1.2.3.0 = INTEGER: 42\n' + 'diagnostic-line-' * 150 + secret + '\n').encode()
        process = type("Process", (), {"returncode": 0, "communicate": lambda self: (raw, secret.encode())})()
        with patch.object(runtime["subprocess"], "Popen", return_value=process), self.assertLogs(runtime["LOG"], level="DEBUG") as captured:
            result = runtime["SNMP"]().get("1.2.3.0")
        messages = " ".join(captured.output)
        self.assertEqual(result, 42)
        for marker in ("command=", "raw_stdout_begin", "raw_stdout_end", "raw_stderr_begin", "parsed=", "[value]", "elapsed_seconds=", "<redacted>"):
            self.assertIn(marker, messages)
        self.assertIn('diagnostic-line-' * 150, messages)
        self.assertNotIn(secret, messages)
        self.assertNotIn(json.dumps(secret)[1:-1], messages)
        self.load_runtime()

    def test_snmp_exception_includes_traceback_without_secret(self):
        secret = "failure-secret"
        runtime = self.load_runtime({"EASYOPS_COLLECTOR_community": secret})
        with patch.object(runtime["subprocess"], "Popen", side_effect=OSError(secret)), self.assertLogs(runtime["LOG"], level="ERROR") as captured:
            result = runtime["SNMP"]().get("1.2.3.0")
        self.assertIsNone(result)
        messages = " ".join(captured.output)
        self.assertIn("Traceback", messages)
        self.assertIn("[SNMP.run]", messages)
        self.assertNotIn(secret, messages)

    def test_metric_files_and_script(self):
        for name in ("metric_set.json", "origin_metric.json", "alias_metric.json"):
            self.assertIsInstance(json.loads(self.archive.read(self.root + name)), list)
        code = self.archive.read(self.root + "src/物理服务器SNMP监控.py")
        compile(code, "physical-server-monitor.py", "exec")


if __name__ == "__main__":
    unittest.main()
