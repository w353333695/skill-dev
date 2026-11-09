import os
from pathlib import Path
import unittest
from unittest import mock
import zipfile


class FCMonitorDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform = Path(__file__).resolve().parents[3]
        package = platform / "hub/monitor-kits/光纤交换机监控套件_v1.0.15.zip"
        with zipfile.ZipFile(package) as archive:
            cls.source = archive.read("光纤交换机监控套件/src/光纤交换机监控.py")
        cls.code = compile(cls.source, "光纤交换机监控.py", "exec")

    def test_null_port_aborts_before_any_snmp_request(self):
        runtime = {"__name__": "__main__"}
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_ip": "192.0.2.10", "EASYOPS_COLLECTOR_port": "null"}, clear=True):
            with mock.patch("subprocess.Popen") as popen:
                with self.assertRaisesRegex(ValueError, "invalid literal"):
                    exec(self.code, runtime)
                popen.assert_not_called()

    def test_brocade_non_numeric_counter_aborts_stage(self):
        runtime = {"__name__": "fc_diagnostics"}
        exec(self.code, runtime)
        monitor_class = runtime["BrocadeMonitor"]
        monitor = monitor_class.__new__(monitor_class)
        values = {
            monitor.OID["port_name"]: {"1": "FC1"},
            monitor.OID["port_enc_in_errors"]: {"1": "NA"},
        }
        monitor._walk_port_column = lambda oid: values.get(oid, {})
        with self.assertRaisesRegex(ValueError, "could not convert"):
            monitor.collect_port_errors("192.0.2.10")


if __name__ == "__main__":
    unittest.main()
