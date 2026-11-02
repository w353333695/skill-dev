"""验证物理服务器 SNMP 监控套件的导入目录、权限和元数据。"""
import json
import os
from pathlib import Path
import re
import stat
import unittest
import zipfile


class PackageImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = Path(__file__).resolve().parent.parent / "物理服务器SNMP监控套件_0.1.1.zip"
        cls.archive = zipfile.ZipFile(os.environ.get("MONITOR_PACKAGE", str(default)))
        cls.root = "物理服务器SNMP监控/"

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_root_matches_plugin_name(self):
        plugin = self.archive.read(self.root + "plugin.yaml").decode("utf-8")
        name = re.search(r"(?m)^name: (.+)$", plugin).group(1)
        self.assertEqual(self.root, name + "/")
        self.assertIn('version: "0.1.1"', plugin)
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

    def test_metric_files_and_script(self):
        for name in ("metric_set.json", "origin_metric.json", "alias_metric.json"):
            self.assertIsInstance(json.loads(self.archive.read(self.root + name)), list)
        code = self.archive.read(self.root + "src/物理服务器SNMP监控.py")
        compile(code, "physical-server-monitor.py", "exec")


if __name__ == "__main__":
    unittest.main()
