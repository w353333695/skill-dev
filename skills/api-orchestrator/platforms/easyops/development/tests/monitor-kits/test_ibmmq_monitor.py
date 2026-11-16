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
PACKAGE = BASE.parent / "hub/monitor-kits/监控套件_IBM_MQ监控_0.4.5.zip"
XLSX = KIT / "IBM_MQ监控_告警规则模板_0.4.5.xlsx"


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
            "ibmmqInstanceId": "ibmmq-1", "hostIp": "192.168.1.10",
            "installPath": "/opt/mqm",
            "queueFilter": ".*", "includeSystemQueues": False, "processMonitor": False,
            "logLevel": "ERROR", "timeout": 1, "interval": 0,
        }

    def test_version(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.4.5", result.stdout)

    def test_orig_and_runtime_are_identical(self):
        self.assertEqual(SOURCE.read_bytes(), (KIT / "src/ibmmq_monitor.py").read_bytes())

    def test_no_future_import(self):
        for path in (SOURCE, KIT / "src/ibmmq_monitor.py"):
            self.assertNotIn("from __future__ import", path.read_text(encoding="utf-8"))


    def test_windows_commands_and_process_metrics(self):
        with mock.patch.object(self.m, "is_windows", return_value=True):
            self.assertEqual(self.m.mq_command(r"C:\IBM\MQ\bin", "dspmq"), r"C:\IBM\MQ\bin\dspmq.exe")
            with mock.patch.object(self.m, "execute", return_value=(0, "COMMAND ACCEPTED")) as command_execute:
                self.m.run_mqsc(r"C:\IBM\MQ\bin", "QM1", self.settings)
            mqsc_input = command_execute.call_args[0][2]
            self.assertTrue(mqsc_input.endswith("\r\n"))
            self.assertTrue(command_execute.call_args[0][0][0].endswith("runmqsc.exe"))
            process_json = json.dumps([{
                "ProcessId": 101,
                "ExecutablePath": r"C:\Program Files\IBM\MQ\bin\runmqlsr.exe",
                "CommandLine": r"C:\Program Files\IBM\MQ\bin\runmqlsr.exe -m QM1 -t TCP -p 1414",
            }])
            perf_json = json.dumps([{
                "IDProcess": 101, "PercentProcessorTime": "3.5", "ThreadCount": "4",
                "HandleCount": "50", "WorkingSetPrivate": "1048576",
            }])
            def powershell(command, settings):
                return 0, process_json if "Win32_Process |" in command else perf_json
            with mock.patch.object(self.m, "run_powershell", side_effect=powershell):
                grouped = self.m.collect_processes("QM1", self.settings)
            self.assertEqual(len(grouped), 1)
            row = next(iter(grouped.values()))
            self.assertEqual(row["alive"], 1.0)
            self.assertEqual(row["count"], 1.0)
            self.assertEqual(row["cpu"], 3.5)
            self.assertEqual(row["memory"], 1048576.0)
            self.assertEqual(row["threads"], 4.0)
            self.assertEqual(row["fds"], 50.0)

    def test_process_list_extracts_qmgr_and_run_user(self):
        settings = dict(self.settings, processList=json.dumps([
            {"pname": "amqzmgr0", "cmdline": "/opt/mqm/bin/amqzmgr0 -m QM_001", "user": "mqm"},
            {"pname": "runmqlsr", "cmdline": "/opt/mqm/bin/runmqlsr -m QM_002 -t TCP -p 1414", "user": "mqm2"},
            {"cmdline": "/opt/mqm/bin/amqrrmfa -t1"},
        ]))
        targets = self.m.process_targets(settings)
        self.assertEqual(targets, [
            {"qmgrName": "QM_001", "runUser": "mqm"},
            {"qmgrName": "QM_002", "runUser": "mqm2"},
        ])

    def test_process_list_accepts_native_dict_list(self):
        native = [{"pname": "runmqlsr", "cmdline": "/opt/mqm/bin/runmqlsr -m QM_003", "user": "mqm3"}]
        self.assertEqual(
            self.m.process_targets(dict(self.settings, processList=native)),
            [{"qmgrName": "QM_003", "runUser": "mqm3"}],
        )

    def test_process_list_reuses_missing_user_from_later_process(self):
        process_list = [
            {"cmdline": "/opt/mqm/bin/amqzmgr0 -m QM_004"},
            {"cmdline": "/opt/mqm/bin/runmqlsr -m QM_004 -p 1414", "user": "mqm4"},
        ]
        self.assertEqual(
            self.m.process_targets(dict(self.settings, processList=process_list)),
            [{"qmgrName": "QM_004", "runUser": "mqm4"}],
        )

    def test_linux_mq_commands_execute_with_su(self):
        with mock.patch.object(self.m, "execute", return_value=(0, "COMMAND ACCEPTED")) as command_execute:
            self.m.run_mqsc("/opt/mqm/bin", "QM_001", self.settings, "mqm")
        self.assertEqual(
            command_execute.call_args[0][0],
            ["su", "-", "mqm", "-c", "'/opt/mqm/bin/runmqsc' 'QM_001'"],
        )
        with mock.patch.object(self.m, "execute", return_value=(0, "QMNAME(QM_001) STATUS(Running)")) as command_execute:
            self.m.discover_qmgrs("/opt/mqm/bin", self.settings, "mqm")
        self.assertEqual(
            command_execute.call_args[0][0],
            ["su", "-", "mqm", "-c", "'/opt/mqm/bin/dspmq' '-o' 'status'"],
        )

    def test_windows_mq_commands_do_not_use_su(self):
        with mock.patch.object(self.m, "is_windows", return_value=True), \
             mock.patch.object(self.m, "execute", return_value=(0, "COMMAND ACCEPTED")) as command_execute:
            self.m.run_mqsc(r"C:\IBM\MQ\bin", "QM_001", self.settings, "mqm")
        self.assertEqual(command_execute.call_args[0][0], [r"C:\IBM\MQ\bin\runmqsc.exe", "QM_001"])

    def test_invalid_run_user_falls_back_to_current_user(self):
        with mock.patch.object(self.m, "execute", return_value=(0, "COMMAND ACCEPTED")) as command_execute:
            self.m.run_mqsc("/opt/mqm/bin", "QM_001", self.settings, "bad;user")
        self.assertEqual(command_execute.call_args[0][0], ["/opt/mqm/bin/runmqsc", "QM_001"])

    def test_process_list_drives_per_qmgr_discovery(self):
        targets = [
            {"qmgrName": "QM_001", "runUser": "mqm1"},
            {"qmgrName": "QM_002", "runUser": "mqm2"},
        ]
        discovered = [
            [
                {"qmgrName": "QM_001", "status": "Running", "dspmqReturnCode": 0},
                {"qmgrName": "OTHER", "status": "Running", "dspmqReturnCode": 0},
            ],
            [{"qmgrName": "QM_002", "status": "Running", "dspmqReturnCode": 0}],
        ]
        def fake_discovery(_mq_bin, _settings, run_user=""):
            return discovered.pop(0), 0
        with mock.patch.object(self.m, "discover_qmgrs", side_effect=fake_discovery) as discovery:
            qmgrs, returncode = self.m.discover_process_qmgrs("/opt/mqm/bin", self.settings, targets)
        self.assertEqual(returncode, 0)
        self.assertEqual([row["qmgrName"] for row in qmgrs], ["QM_001", "QM_002"])
        self.assertEqual([row["runUser"] for row in qmgrs], ["mqm1", "mqm2"])
        self.assertEqual([call.args[2] for call in discovery.call_args_list], ["mqm1", "mqm2"])

    def test_mqsc_input_includes_zabbix_metric_sources(self):
        with mock.patch.object(self.m, "execute", return_value=(0, "COMMAND ACCEPTED")) as command_execute:
            self.m.run_mqsc("/opt/mqm/bin", "QM1", self.settings)
        mqsc_input = command_execute.call_args[0][2]
        self.assertIn("DISPLAY QMGR DEADQ", mqsc_input)
        self.assertIn("DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH USAGE GET PUT", mqsc_input)
        self.assertIn("DISPLAY CHSTATUS(*) CHANNEL CHLTYPE STATUS MSGS BYTSRCVD BYTSSENT", mqsc_input)

    def test_config_and_qmgr_discovery_do_not_use_manual_parameters(self):
        env = {
            "EASYOPS_COLLECTOR_instanceId": "i1",
            "EASYOPS_COLLECTOR_hostIp": "192.168.1.10",
            "EASYOPS_COLLECTOR_installPath": "/opt/mqm",
        }
        with mock.patch.dict(os.environ, env):
            settings = self.m.config()
        self.assertNotIn("qmgrName", settings)
        self.assertNotIn("mqBinPath", settings)
        self.assertEqual(settings["logLevel"], "ERROR")
        dspmq_output = "QMNAME(QM1) STATUS(Running)\nQMNAME(QM2) STATUS(Running)"
        with mock.patch.object(self.m, "execute", return_value=(0, dspmq_output)) as command_execute:
            qmgrs, returncode = self.m.discover_qmgrs("/opt/mqm/bin", settings)
        self.assertEqual(returncode, 0)
        self.assertEqual([row["qmgrName"] for row in qmgrs], ["QM1", "QM2"])
        self.assertEqual(command_execute.call_args[0][0], ["/opt/mqm/bin/dspmq", "-o", "status"])

    def test_log_level_validation_and_debug_output(self):
        env = {
            "EASYOPS_COLLECTOR_instanceId": "i1",
            "EASYOPS_COLLECTOR_logLevel": "DEBUG",
        }
        with mock.patch.dict(os.environ, env), self.assertLogs(self.m.LOGGER, level="DEBUG") as logs:
            settings = self.m.config()
        self.assertEqual(settings["logLevel"], "DEBUG")
        self.assertTrue(any("[config] version=0.4.5" in message for message in logs.output))
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_logLevel": "VERBOSE"}):
            with self.assertRaises(ValueError):
                self.m.config()

    def test_debug_logs_mirror_to_stdout(self):
        import io
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            self.m.setup_logging("DEBUG")
            self.m.LOGGER.debug("[test] frontend-visible")
        self.assertIn("[test] frontend-visible", stdout.getvalue())
        self.assertIn("[test] frontend-visible", stderr.getvalue())
        self.m.LOGGER.handlers = []

    def test_debug_stdout_contains_logs_and_final_json(self):
        import io
        stdout = io.StringIO()
        stderr = io.StringIO()
        settings = dict(self.settings, logLevel="DEBUG")
        def collect_debug(_settings):
            self.m.LOGGER.debug("[frontend] diagnostic payload")
            return []
        with mock.patch.dict(os.environ, {"EASYOPS_COLLECTOR_logLevel": "DEBUG"}), \
             mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
             mock.patch.object(self.m, "config", return_value=settings), \
             mock.patch.object(self.m, "collect", side_effect=collect_debug):
            result = self.m.main([])
        self.assertEqual(result, 0)
        self.assertIn("[frontend] diagnostic payload", stdout.getvalue())
        self.assertIn("[frontend] diagnostic payload", stderr.getvalue())
        self.assertTrue(stdout.getvalue().rstrip().endswith("[]"))
        self.m.LOGGER.handlers = []

    def test_collect_logs_missing_metric_summary(self):
        qmgrs = [{"qmgrName": "QM1", "status": "Running"}]
        with mock.patch.object(self.m, "find_mq_bin", return_value="/opt/mqm/bin"), \
             mock.patch.object(self.m, "discover_qmgrs", return_value=(qmgrs, 0)), \
             mock.patch.object(self.m, "collect_qmgr", return_value=[{"vals": {"ibmmq_qmgr_status": 1.0}}]), \
             self.assertLogs(self.m.LOGGER, level="ERROR") as logs:
            rows = self.m.collect(self.settings)
        self.assertTrue(rows)
        self.assertTrue(any("[collect] metric gaps count=" in message for message in logs.output))

    def test_debug_logs_cover_mqsc_parsing_and_filter_reasons(self):
        output = "\n".join([
            "QMNAME(QM1) DEADQ(SYSTEM.DEAD.LETTER.QUEUE)",
            "QNAME(APP.Q) CURDEPTH(1) MAXDEPTH(10) USAGE(NORMAL)",
            "QNAME(SYSTEM.ADMIN.Q) CURDEPTH(2) MAXDEPTH(10)",
            "CHANNEL(SDR.CH) CHLTYPE(SDR) STATUS(RUNNING) BYTSRCVD(1) BYTSSENT(2)",
            "LISTENER(TCP.1) PORT(1414) STATUS(RUNNING)",
        ])
        with self.assertLogs(self.m.LOGGER, level="DEBUG") as logs:
            queues, channels, listeners, dead_queue_name = self.m.parse_mqsc(output, self.settings)
        self.assertEqual(len(queues), 1)
        self.assertEqual(dead_queue_name, "SYSTEM.DEAD.LETTER.QUEUE")
        self.assertEqual(len(channels), 1)
        self.assertEqual(len(listeners), 1)
        text = "\n".join(logs.output)
        self.assertIn("[parse_mqsc] discovered queues=", text)
        self.assertIn("exclude queue=SYSTEM.ADMIN.Q reason=SYSTEM_PREFIX", text)
        self.assertIn("[parse_mqsc] select queue=APP.Q", text)

    def test_collect_auto_discovers_all_qmgrs(self):
        qmgrs = [
            {"qmgrName": "QM1", "status": "Running"},
            {"qmgrName": "QM2", "status": "Running"},
        ]
        with mock.patch.object(self.m, "find_mq_bin", return_value="/opt/mqm/bin"), \
             mock.patch.object(self.m, "discover_qmgrs", return_value=(qmgrs, 0)), \
             mock.patch.object(self.m, "collect_qmgr", side_effect=lambda qmgr, mq_bin, settings: [{"vals": {"ibmmq_qmgr_status": 1.0}}]), \
             self.assertLogs(self.m.LOGGER, level="ERROR"):
            rows = self.m.collect(self.settings)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["vals"]["ibmmq_qmgr_count"], 2.0)
        self.assertEqual(rows[-1]["vals"]["ibmmq_collect_success"], 1.0)

    def test_parse_mqsc(self):
        output = "\n".join([
            "   1 : DISPLAY QMGR DEADQ",
            "     QMNAME(QM1)                DEADQ(SYSTEM.DEAD.LETTER.QUEUE)",
            "   2 : DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH USAGE GET PUT",
            "     QNAME(APP.Q)               CURDEPTH( 12) MAXDEPTH(100) USAGE(NORMAL) GET(ENABLED) PUT(ENABLED)",
            "     QNAME(XMIT.Q)              CURDEPTH( 3)  MAXDEPTH(10)  USAGE(XMITQ) GET(ENABLED) PUT(DISABLED)",
            "     QNAME(SYSTEM.DEAD.LETTER.QUEUE) CURDEPTH(1) MAXDEPTH(10) USAGE(NORMAL) GET(ENABLED) PUT(ENABLED)",
            "     QNAME(SYSTEM.ADMIN.Q)      CURDEPTH( 1)  MAXDEPTH(5000)",
            "   6 : DISPLAY QSTATUS(*)",
            "     QUEUE(APP.Q)               MSGAGE( 45)  IPPROCS(1) OPPROCS(2)",
            "   10 : DISPLAY CHSTATUS(*)",
            "     CHANNEL(SENDER.CH)         CHLTYPE(SDR) STATUS(RUNNING) MSGNO(10) BYTSRCVD(200) BYTSSENT(300)",
            "     CHANNEL(RECV.CH)           CHLTYPE(RCVR) STATUS(RETRYING)",
            "  14 : DISPLAY LSSTATUS(*)",
            "     LISTENER(TCP.LISTENER)     PORT(1414)   STATUS(RUNNING)",
        ])
        queues, channels, listeners, dead_queue_name = self.m.parse_mqsc(output, self.settings)
        self.assertEqual(dead_queue_name, "SYSTEM.DEAD.LETTER.QUEUE")
        self.assertEqual([row["queueName"] for row in queues], ["APP.Q", "SYSTEM.DEAD.LETTER.QUEUE", "XMIT.Q"])
        self.assertEqual(queues[0]["currentDepth"], 12.0)
        self.assertEqual(queues[0]["maxDepth"], 100.0)
        self.assertEqual(queues[0]["oldestMessageAge"], 45.0)
        self.assertTrue(queues[1]["isDeadQueue"])
        self.assertTrue(queues[2]["isTransmissionQueue"])
        self.assertEqual(len(channels), 2)
        self.assertEqual(self.m.normalize_status(channels[0]["status"]), 1.0)
        self.assertEqual(self.m.normalize_status(channels[1]["status"]), 0.0)
        self.assertEqual(channels[0]["bytesReceived"], 200.0)
        self.assertEqual(channels[0]["bytesSent"], 300.0)
        self.assertEqual(listeners[0]["port"], "1414")

    def test_collect_qmgr_outputs(self):
        qmgr = {"qmgrName": "QM1", "status": "Running"}
        mqsc = "\n".join([
            "COMMAND ACCEPTED",
            "QMNAME(QM1) DEADQ(SYSTEM.DEAD.LETTER.QUEUE)",
            "QNAME(APP.Q) CURDEPTH(20) MAXDEPTH(100) USAGE(NORMAL) GET(ENABLED) PUT(ENABLED)",
            "QNAME(XMIT.Q) CURDEPTH(9) MAXDEPTH(10) USAGE(XMITQ) GET(ENABLED) PUT(DISABLED)",
            "QNAME(SYSTEM.DEAD.LETTER.QUEUE) CURDEPTH(1) MAXDEPTH(10) GET(ENABLED) PUT(ENABLED)",
            "QUEUE(APP.Q) MSGAGE(301)",
            "CHANNEL(SDR.CH) CHLTYPE(SDR) STATUS(RUNNING) MSGS(3) BYTSRCVD(9) BYTSSENT(11)",
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
        queue_metrics = [value for row in rows for key, value in row["vals"].items() if key == "ibmmq_queue_current_depth"]
        usage_metrics = [value for row in rows for key, value in row["vals"].items() if key == "ibmmq_queue_usage_percent"]
        self.assertIn(20.0, queue_metrics)
        self.assertIn(20.0, usage_metrics)
        self.assertEqual(by_key["ibmmq_queue_get_enabled"], 1.0)
        self.assertEqual(by_key["ibmmq_transmission_queue_usage_percent"], 90.0)
        self.assertEqual(by_key["ibmmq_transmission_queue_put_enabled"], 0.0)
        self.assertEqual(by_key["ibmmq_dlq_configured"], 1.0)
        self.assertEqual(by_key["ibmmq_dlq_current_depth"], 1.0)
        self.assertEqual(by_key["ibmmq_channel_bytes_received"], 9.0)
        self.assertEqual(by_key["ibmmq_channel_bytes_sent"], 11.0)
        self.assertEqual(by_key["ibmmq_channel_status"], 1.0)
        self.assertEqual(by_key["ibmmq_listener_status"], 1.0)
        self.assertIn("DISPLAY QSTATUS", calls[0][1])

    def test_resource_discovery_and_no_model_override(self):
        discovery = json.loads((KIT / "resource_discovery_define.json").read_text())
        self.assertEqual(discovery[0]["objectId"], "IBMMQ@ONEMODEL")
        self.assertEqual(discovery[0]["type"], "ARTIFACT_INST@ONEMODEL")
        self.assertFalse((KIT / "IBMMQ@ONEMODEL.json").exists())

    def test_definitions(self):
        plugin = yaml.safe_load((KIT / "plugin.yaml").read_text())
        origins = json.loads((KIT / "origin_metric.json").read_text())
        aliases = json.loads((KIT / "alias_metric.json").read_text())
        metric_sets = json.loads((KIT / "metric_set.json").read_text())
        self.assertEqual(plugin["name"], "IBM MQ监控")
        self.assertEqual(plugin["relateObjectId"], "IBMMQ@ONEMODEL")
        self.assertIn("Linux/Windows", plugin["memo"])
        self.assertEqual(plugin["version"], "0.4.5")
        self.assertNotIn("qmgrName", plugin["params"])
        self.assertNotIn("mqBinPath", plugin["params"])
        self.assertIn("processList", plugin["params"])
        self.assertIn("logLevel", plugin["params"])
        self.assertNotIn("qmgrName", {row["name"] for row in plugin["paramDefine"]})
        self.assertNotIn("mqBinPath", {row["name"] for row in plugin["paramDefine"]})
        process_list = next(row for row in plugin["paramDefine"] if row["name"] == "processList")
        self.assertEqual(process_list["defaultValue"], "$.processList")
        log_level = next(row for row in plugin["paramDefine"] if row["name"] == "logLevel")
        self.assertEqual(log_level["defaultValue"], "ERROR")
        self.assertEqual(len(origins), 45)
        self.assertEqual(len(aliases), 45)
        self.assertEqual(len(metric_sets), 11)
        self.assertEqual(len({row["displayName"] for row in aliases}), 45)
        self.assertTrue(all(any("\u4e00" <= char <= "\u9fff" for char in row["displayName"]) for row in aliases))
        self.assertEqual({row["key"] for row in origins}, {row["name"] for row in aliases})
        self.assertTrue(all(isinstance(row, dict) and row.get("name") for row in metric_sets))
        origin_dimensions = {row["key"]: set(row["labels"]) for row in origins}
        for alias in aliases:
            self.assertEqual({row["dimName"] for row in alias["dims"]}, origin_dimensions[alias["originalMetrics"][0]])

    def test_alert_xlsx(self):
        workbook = load_workbook(XLSX, data_only=False)
        sheet = workbook.active
        self.assertEqual(sheet["B3"].value, "IBMMQ@ONEMODEL")
        conditions = json.loads(sheet["R3"].value)
        expected = {
            "ibmmq_qmgr_status", "ibmmq_process_alive", "ibmmq_listener_status",
            "ibmmq_channel_status", "ibmmq_queue_current_depth",
            "ibmmq_queue_usage_percent", "ibmmq_queue_oldest_message_age_seconds",
            "ibmmq_transmission_queue_usage_percent", "ibmmq_dlq_current_depth",
        }
        self.assertTrue(expected.issubset({row["metricName"] for row in conditions}))
        by_metric = {row["metricName"]: row for row in conditions}
        self.assertEqual(by_metric["ibmmq_dlq_current_depth"]["alertCount"], 2)
        self.assertEqual(by_metric["ibmmq_dlq_current_depth"]["detectWindow"], 2)
        self.assertEqual(
            [item["threshold"] for item in by_metric["ibmmq_queue_usage_percent"]["comparators"]],
            [80, 90],
        )
        self.assertNotIn("ibmmq_queue_get_enabled", {row["metricName"] for row in conditions})

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
            self.assertIn("IBM MQ监控/IBM_MQ监控_告警规则模板_0.4.5.xlsx", package.namelist())
            self.assertIn("IBM MQ监控/resource_discovery_define.json", package.namelist())
            self.assertNotIn("IBM MQ监控/IBMMQ@ONEMODEL.json", package.namelist())


if __name__ == "__main__":
    unittest.main()
