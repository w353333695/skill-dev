# -*- coding: utf-8 -*-
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest import mock
from openpyxl import load_workbook
import yaml

BASE = Path(__file__).resolve().parents[2]
KIT = BASE / "monitor-kits/ibmmq-monitoring"
SOURCE = KIT / "src/ibmmq_monitor.orig"
PACKAGE = BASE.parent / "hub/monitor-kits/监控套件_IBM_MQ监控_0.1.0.zip"
XLSX = KIT / "IBM_MQ监控_告警规则模板_0.1.0.xlsx"


def module():
    sys.dont_write_bytecode = True
    loader = SourceFileLoader("ibmmq_monitor", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


class IBMMQMonitorTest(unittest.TestCase):
    def setUp(self):
        self.m = module()
        self.settings = {
            "hostInstanceId": "host-1", "qmgrName": "", "mqBinPath": "/opt/mqm/bin",
            "queueFilter": ".*", "includeSystemQueues": False, "processMonitor": False,
            "timeout": 1, "interval": 0,
        }

    def test_version(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_orig_and_runtime_are_identical(self):
        self.assertEqual(SOURCE.read_bytes(), (KIT / "src/ibmmq_monitor.py").read_bytes())

    def test_parse_mqsc(self):
        output = "\n".join([
            "   1 : DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH",
            "     QNAME(APP.Q)               CURDEPTH( 12) MAXDEPTH(100)",
            "     QNAME(SYSTEM.ADMIN.Q)      CURDEPTH( 1)  MAXDEPTH(5000)",
            "   5 : DISPLAY QSTATUS(*)",
            "     QUEUE(APP.Q)               MSGAGE( 45)  IPPROCS(1) OPPROCS(2)",
            "   9 : DISPLAY CHSTATUS(*)",
            "     CHANNEL(SENDER.CH)         CHLTYPE(SDR) STATUS(RUNNING) MSGNO(10) BYTES(200)",
            "     CHANNEL(RECV.CH)           CHLTYPE(RCVR) STATUS(RETRYING)",
            "  13 : DISPLAY LSSTATUS(*)",
            "     LISTENER(TCP.LISTENER)     PORT(1414)   STATUS(RUNNING)",
        ])
        queues, channels, listeners = self.m.parse_mqsc(output, self.settings)
        self.assertEqual([row["queueName"] for row in queues], ["APP.Q"])
        self.assertEqual(queues[0]["currentDepth"], 12.0)
        self.assertEqual(queues[0]["maxDepth"], 100.0)
        self.assertEqual(queues[0]["oldestMessageAge"], 45.0)
        self.assertEqual(len(channels), 2)
        self.assertEqual(self.m.normalize_status(channels[0]["status"]), 1.0)
        self.assertEqual(self.m.normalize_status(channels[1]["status"]), 0.0)
        self.assertEqual(listeners[0]["port"], "1414")

    def test_collect_qmgr_outputs(self):
        qmgr = {"qmgrName": "QM1", "status": "Running"}
        mqsc = "\n".join([
            "COMMAND ACCEPTED",
            "QNAME(APP.Q) CURDEPTH(20) MAXDEPTH(100)",
            "QUEUE(APP.Q) MSGAGE(301)",
            "CHANNEL(SDR.CH) CHLTYPE(SDR) STATUS(RUNNING) MSGS(3) BYTES(9)",
            "LISTENER(TCP.1) PORT(1414) STATUS(RUNNING)",
        ])
        calls = []
        def execute(args, settings, input_text=None):
            calls.append((args, input_text))
            return 0, mqsc if args[0].endswith("runmqsc") else "QMNAME(QM1) STATUS(Running)"
        with mock.patch.object(self.m, "execute", side_effect=execute):
            rows = self.m.collect_qmgr(qmgr, "/opt/mqm/bin", self.settings)
        self.assertTrue(rows)
        by_key = {}
        for row in rows:
            by_key.update(row["vals"])
        self.assertEqual(by_key["ibmmq_qmgr_status"], 1.0)
        self.assertEqual(by_key["ibmmq_collect_success"], 1.0)
        self.assertEqual(by_key["ibmmq_sc_command_success"], 1.0)
        self.assertEqual(by_key["ibmmq_queue_current_depth"], 20.0)
        self.assertEqual(by_key["ibmmq_queue_usage_percent"], 20.0)
        self.assertEqual(by_key["ibmmq_channel_status"], 1.0)
        self.assertEqual(by_key["ibmmq_listener_status"], 1.0)
        self.assertIn("DISPLAY QSTATUS", calls[0][1])

    def test_definitions(self):
        plugin = yaml.safe_load((KIT / "plugin.yaml").read_text())
        origins = json.loads((KIT / "origin_metric.json").read_text())
        aliases = json.loads((KIT / "alias_metric.json").read_text())
        metric_sets = json.loads((KIT / "metric_set.json").read_text())
        self.assertEqual(plugin["name"], "IBM MQ监控")
        self.assertEqual(plugin["relateObjectId"], "HOST")
        self.assertEqual(len(origins), 30)
        self.assertEqual({row["key"] for row in origins}, {row["name"] for row in aliases})
        self.assertTrue(all(isinstance(row, dict) and row.get("name") for row in metric_sets))
        origin_dimensions = {row["key"]: set(row["labels"]) for row in origins}
        for alias in aliases:
            self.assertEqual({row["dimName"] for row in alias["dims"]}, origin_dimensions[alias["originalMetrics"][0]])

    def test_alert_xlsx(self):
        workbook = load_workbook(XLSX, data_only=False)
        sheet = workbook.active
        self.assertEqual(sheet["B3"].value, "HOST")
        conditions = json.loads(sheet["R3"].value)
        expected = {
            "ibmmq_qmgr_status", "ibmmq_process_alive", "ibmmq_listener_status",
            "ibmmq_channel_status", "ibmmq_queue_current_depth",
            "ibmmq_queue_usage_percent", "ibmmq_queue_oldest_message_age_seconds",
        }
        self.assertTrue(expected.issubset({row["metricName"] for row in conditions}))

    def test_package(self):
        if not PACKAGE.exists():
            self.skipTest("package not built yet")
        import zipfile
        with zipfile.ZipFile(PACKAGE) as package:
            self.assertEqual(package.namelist()[0], "IBM MQ监控/")
            for item in package.infolist():
                mode = stat.S_IMODE(item.external_attr >> 16)
                self.assertEqual(mode, 0o755 if item.is_dir() else 0o664)
            self.assertIn("IBM MQ监控/src/ibmmq_monitor.orig", package.namelist())
            self.assertIn("IBM MQ监控/IBM_MQ监控_告警规则模板_0.1.0.xlsx", package.namelist())


if __name__ == "__main__":
    unittest.main()
