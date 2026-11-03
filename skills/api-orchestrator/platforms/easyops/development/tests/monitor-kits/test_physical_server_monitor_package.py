"""验证物理服务器 SNMP 监控套件的导入目录、权限和元数据。"""
import json
import io
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
        default = Path(__file__).resolve().parents[3] / "hub" / "monitor-kits" / "物理服务器SNMP监控套件_0.1.4.zip"
        cls.archive = zipfile.ZipFile(os.environ.get("MONITOR_PACKAGE", str(default)))
        cls.root = "物理服务器SNMP监控/"

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_root_matches_plugin_name(self):
        plugin = self.archive.read(self.root + "plugin.yaml").decode("utf-8")
        name = re.search(r"(?m)^name: (.+)$", plugin).group(1)
        self.assertEqual(self.root, name + "/")
        self.assertIn('version: "%s"' % os.environ.get('MONITOR_PACKAGE_VERSION', '0.1.4'), plugin)
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
        params = ["ip", "port", "version", "community", "username", "auth_key", "auth_protocol", "priv_key", "priv_protocol"]
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
        for name in ["ip", "port", "version", "community", "username", "auth_key", "auth_protocol", "priv_key", "priv_protocol"]:
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

    def test_metric_files_and_script(self):
        for name in ("metric_set.json", "origin_metric.json", "alias_metric.json"):
            self.assertIsInstance(json.loads(self.archive.read(self.root + name)), list)
        code = self.archive.read(self.root + "src/物理服务器SNMP监控.py")
        compile(code, "physical-server-monitor.py", "exec")


if __name__ == "__main__":
    unittest.main()
