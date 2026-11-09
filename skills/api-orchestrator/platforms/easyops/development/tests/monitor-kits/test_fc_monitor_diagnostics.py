import json
import os
from pathlib import Path
import stat
import unittest
import zipfile

import yaml


class FCMonitorPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform = Path(__file__).resolve().parents[3]
        default = platform / "hub/monitor-kits/监控套件_光纤交换机监控_1.0.17.zip"
        cls.package = zipfile.ZipFile(os.environ.get("FC_MONITOR_PACKAGE", str(default)))
        cls.prefix = "光纤交换机监控/"

    @classmethod
    def tearDownClass(cls):
        cls.package.close()

    def test_single_root_version_permissions_and_original_source(self):
        entries = self.package.infolist()
        self.assertEqual(entries[0].filename, self.prefix)
        for item in entries:
            self.assertTrue(item.filename.startswith(self.prefix))
            self.assertNotIn("__pycache__", item.filename)
            self.assertNotIn("光纤交换机监控/光纤交换机监控", item.filename)
            self.assertEqual(stat.S_IMODE(item.external_attr >> 16), 0o755 if item.is_dir() else 0o664)
        plugin = yaml.safe_load(self.package.read(self.prefix + "plugin.yaml"))
        self.assertEqual(plugin["name"], "光纤交换机监控")
        self.assertEqual(plugin["version"], "1.0.17")
        self.assertEqual(plugin["relateObjectId"], "FIBERCHANNEL_SWITCH@ONEMODEL")
        script = self.package.read(self.prefix + "src/光纤交换机监控.py")
        self.assertEqual(script, self.package.read(self.prefix + "src/光纤交换机监控.orig"))
        self.assertTrue(script.splitlines()[1].startswith(b"# -*- coding: utf-8 -*-"))
        self.assertIn(b'VERSION = "1.0.17"', script)

    def test_cmdb_parameters_are_dynamic_not_double_encrypted(self):
        plugin = yaml.safe_load(self.package.read(self.prefix + "plugin.yaml"))
        params = {item["name"]: item for item in plugin["paramDefine"]}
        self.assertEqual(set(plugin["params"]), set(params))
        self.assertEqual(params["ip"]["defaultValue"], "$.ip")
        self.assertTrue(params["port"]["optional"])
        self.assertEqual(params["context_name"]["defaultValue"], "$.auth.contextName")
        self.assertEqual(params["logLevel"]["defaultValue"], "ERROR")
        for param in params.values():
            if str(param["defaultValue"]).startswith("$."):
                self.assertFalse(param["isFromSecret"])
                self.assertFalse(param["isEncrypt"])
                self.assertIn(param["valueType"], ["cmdb", "int"])

    def test_metric_and_alert_references_remain_closed(self):
        origins = json.loads(self.package.read(self.prefix + "origin_metric.json"))
        aliases = json.loads(self.package.read(self.prefix + "alias_metric.json"))
        sets = json.loads(self.package.read(self.prefix + "metric_set.json"))
        self.assertEqual((len(origins), len(aliases), len(sets)), (33, 33, 6))
        keys = {item["key"] for item in origins}
        names = {item["name"] for item in aliases}
        set_names = {item["name"] for item in sets}
        for alias in aliases:
            self.assertTrue(set(alias["originalMetrics"]).issubset(keys))
            self.assertTrue(set(alias["metricSet"]).issubset(set_names))
            self.assertEqual(alias["objectId"], "FIBERCHANNEL_SWITCH@ONEMODEL")
        rule_name = next(name for name in self.package.namelist() if name.startswith(self.prefix + "alertRule/") and name.endswith(".json"))
        rule = json.loads(self.package.read(rule_name))
        self.assertEqual(rule["objectId"], "FIBERCHANNEL_SWITCH@ONEMODEL")
        for strategy in rule["alertConditionStrategy"]:
            for condition in strategy["multiConditions"]:
                self.assertIn(condition["metricName"], names)


if __name__ == "__main__":
    unittest.main()
