import io
import json
import os
import stat
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2] / "monitor-kits/ping-monitoring/src/ping_monitor.py"
PACKAGE = Path(__file__).resolve().parents[3] / "hub/monitor-kits/监控套件_主机Ping监控_0.1.0.zip"


def module():
    namespace = {"__name__": "ping_monitor_test"}
    exec(compile(SOURCE.read_bytes(), str(SOURCE), "exec"), namespace)
    return namespace


class PingMonitorTests(unittest.TestCase):
    def test_config_and_output(self):
        m = module()
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_ip": "192.0.2.10"}, clear=True):
            self.assertEqual(m["config"](), ("192.0.2.10", 3, 2))
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_ip": "$.ip"}, clear=True):
            with self.assertRaises(ValueError):
                m["config"]()

    def test_parse_successful_ping_without_network(self):
        m = module()
        process = mock.Mock(returncode=0)
        process.poll.return_value = 0
        process.communicate.return_value = (b"3 packets transmitted, 3 received, 0% packet loss\nrtt min/avg/max/mdev = 0.030/0.040/0.050/0.010 ms\n", b"")
        with mock.patch.object(m["subprocess"], "Popen", return_value=process):
            result = m["ping"]("192.0.2.10", 3, 2)
        self.assertEqual(result["available"], 1.0)
        self.assertEqual(result["loss"], 0.0)
        self.assertEqual(result["avg"], 0.04)

    def test_timeout_is_reported_unavailable(self):
        m = module()
        process = mock.Mock(returncode=-9)
        process.poll.return_value = None
        process.communicate.return_value = (b"", b"")
        with mock.patch.object(m["subprocess"], "Popen", return_value=process):
            with mock.patch.object(m["threading"].Timer, "start", side_effect=lambda: process.kill()):
                result = m["ping"]("192.0.2.10", 1, 1)
        self.assertEqual(result["available"], 0.0)

    def test_help_and_version(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "0.1.0")

    def test_package_shape_and_definitions(self):
        if not PACKAGE.exists():
            self.skipTest("package not built yet")
        with zipfile.ZipFile(str(PACKAGE)) as package:
            names = package.namelist()
            self.assertEqual(names[0], "主机Ping监控/")
            self.assertTrue(all(name.startswith("主机Ping监控/") for name in names))
            plugin = package.read("主机Ping监控/plugin.yaml").decode("utf-8")
            self.assertIn("relateObjectId: HOST", plugin)
            origins = json.loads(package.read("主机Ping监控/origin_metric.json"))
            aliases = json.loads(package.read("主机Ping监控/alias_metric.json"))
            self.assertEqual(len(origins), 5)
            self.assertEqual(len(aliases), 5)
            for item in package.infolist():
                self.assertEqual(stat.S_IMODE(item.external_attr >> 16), 0o755 if item.is_dir() else 0o664)


if __name__ == "__main__":
    unittest.main()
