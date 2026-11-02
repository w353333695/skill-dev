"""验证物理服务器 SNMP 监控套件的导入目录、权限和元数据。"""
import json
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
        default = Path(__file__).resolve().parents[3] / "hub" / "monitor-kits" / "物理服务器SNMP监控套件_0.1.2.zip"
        cls.archive = zipfile.ZipFile(os.environ.get("MONITOR_PACKAGE", str(default)))
        cls.root = "物理服务器SNMP监控/"

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_root_matches_plugin_name(self):
        plugin = self.archive.read(self.root + "plugin.yaml").decode("utf-8")
        name = re.search(r"(?m)^name: (.+)$", plugin).group(1)
        self.assertEqual(self.root, name + "/")
        self.assertIn('version: "%s"' % os.environ.get('MONITOR_PACKAGE_VERSION', '0.1.2'), plugin)
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

    def test_metric_files_and_script(self):
        for name in ("metric_set.json", "origin_metric.json", "alias_metric.json"):
            self.assertIsInstance(json.loads(self.archive.read(self.root + name)), list)
        code = self.archive.read(self.root + "src/物理服务器SNMP监控.py")
        compile(code, "physical-server-monitor.py", "exec")


if __name__ == "__main__":
    unittest.main()
