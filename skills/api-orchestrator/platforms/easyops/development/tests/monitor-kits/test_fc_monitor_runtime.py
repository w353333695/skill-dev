import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[2] / "monitor-kits/fc-switch-monitoring/src/光纤交换机监控.py"


def runtime():
    namespace = {"__name__": "fc_monitor_test"}
    exec(compile(SOURCE.read_bytes(), str(SOURCE), "exec"), namespace)
    return namespace


class FCMonitorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.module = runtime()
        self.environment = {"EASYOPS_COLLECTOR_ip": "192.0.2.10", "EASYOPS_COLLECTOR_community": "test-community"}

    def config(self, **changes):
        environment = dict(self.environment)
        environment.update({"EASYOPS_COLLECTOR_" + key: value for key, value in changes.items()})
        with mock.patch.dict(os.environ, environment, clear=True):
            return self.module["load_config"]()

    def test_null_port_defaults_without_changing_custom_port(self):
        for value in ["", "null", "None", "undefined", " null "]:
            self.assertEqual(self.config(port=value)["port"], 161)
        self.assertEqual(self.config()["port"], 161)
        self.assertEqual(self.config(port="1161")["port"], 1161)
        for value in ["invalid", "0", "65536", "$.snmpPort"]:
            with self.assertRaises(ValueError):
                self.config(port=value)

    def test_invalid_ip_and_auth_fail_before_commands(self):
        for value in ["", "null", "$.ip"]:
            with self.assertRaises(ValueError):
                self.config(ip=value)
        with self.assertRaises(ValueError):
            self.config(community="null")
        with self.assertRaises(ValueError):
            self.config(version="3", username="null")
        with self.assertRaises(ValueError):
            self.config(version="3", username="reader", priv_key="private", auth_key="null")

    def test_preflight_failure_does_not_start_business_collection(self):
        client = mock.Mock()
        client.get.return_value = self.module["Result"](False, None, "authentication failed")
        client.timeout, client.retries = 10, 2
        with mock.patch.dict(self.module, {"detect_vendor": mock.Mock()}):
            with self.assertRaises(RuntimeError):
                self.module["collect_all"](client, "192.0.2.10")
            self.module["detect_vendor"].assert_not_called()
        client.get.assert_called_once_with("1.3.6.1.2.1.1.1.0")
        self.assertEqual((client.timeout, client.retries), (10, 2))

    def test_empty_or_missing_oid_preflight_fails(self):
        for data in [None, "", "No Such Instance currently exists at this OID", "End of MIB"]:
            client = mock.Mock(timeout=10, retries=0)
            client.get.return_value = self.module["Result"](True, data, "")
            with self.assertRaises(RuntimeError):
                self.module["preflight"](client)

    def test_stage_exception_preserves_previous_and_later_data(self):
        client = mock.Mock(timeout=10, retries=0)
        client.get.return_value = self.module["Result"](True, "FC device", "")
        monitor = mock.Mock()
        record = {"dims": {"ip": "192.0.2.10"}, "vals": {"m_cpu_usage": 10.0}}
        monitor.collect_system.return_value = [record]
        monitor.collect_port_status.side_effect = ValueError("bad status")
        monitor.collect_port_traffic.return_value = []
        monitor.collect_port_errors.return_value = []
        monitor.collect_sensors.return_value = []
        monitor.collect_sfp.return_value = [{"dims": {"ip": "192.0.2.10", "port_name": "FC1"}, "vals": {"m_sfp_temperature": 20.0}}]
        with mock.patch.dict(self.module, {"detect_vendor": lambda unused: "brocade", "VENDOR_MONITOR_MAP": {"brocade": lambda unused: monitor}}):
            records = self.module["collect_all"](client, "192.0.2.10")
        self.assertEqual(len(records), 2)
        monitor.collect_sfp.assert_called_once()

    def test_invalid_counter_skips_only_that_metric_and_port(self):
        monitor_class = self.module["BrocadeMonitor"]
        monitor = monitor_class.__new__(monitor_class)
        values = {
            monitor.OID["port_name"]: {"1": "端口一", "2": "FC2"},
            monitor.OID["port_crc_errors"]: {"1": 0, "2": 3},
            monitor.OID["port_enc_in_errors"]: {"1": "NA", "2": 4},
        }
        monitor._walk_port_column = lambda oid: values.get(oid, {})
        records = monitor.collect_port_errors("192.0.2.10")
        self.assertEqual(len(records), 2)
        self.assertNotIn("m_port_enc_in_errors", records[0]["vals"])
        self.assertEqual(records[1]["vals"]["m_port_enc_in_errors"], 4)
        self.assertEqual(records[0]["dims"]["port_name"], "端口一")

    def test_non_finite_numbers_never_enter_metric_output(self):
        values = {}
        for value in [None, "NA", "NaN", "Infinity", "-inf", "null", ""]:
            self.module["set_metric"](values, "m_cpu_usage", value)
        self.assertEqual(values, {})
        self.module["set_metric"](values, "m_cpu_usage", 0)
        self.assertEqual(values["m_cpu_usage"], 0)

    def test_fatal_error_body_visible_and_credentials_redacted(self):
        environment = dict(self.environment, EASYOPS_COLLECTOR_auth_key="auth-secret", EASYOPS_COLLECTOR_priv_key="priv-secret")
        output = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(output):
            with mock.patch.dict(self.module, {"collect_all": mock.Mock(side_effect=RuntimeError("test-community auth-secret priv-secret"))}):
                self.assertEqual(self.module["main"]([]), 0)
        text = output.getvalue()
        self.assertTrue(text.startswith("COLLECT_ERROR:"))
        self.assertIn("Traceback", text)
        for secret in ["test-community", "auth-secret", "priv-secret"]:
            self.assertNotIn(secret, text)
        self.assertEqual(text.count("COLLECT_ERROR:"), 1)

    def test_normal_stdout_is_json_only(self):
        output = io.StringIO()
        records = [{"dims": {"ip": "192.0.2.10", "port_name": "端口一"}, "vals": {"m_port_crc_errors": 1}}]
        with mock.patch.dict(os.environ, self.environment, clear=True), contextlib.redirect_stdout(output):
            with mock.patch.dict(self.module, {"collect_all": mock.Mock(return_value=records)}):
                self.assertEqual(self.module["main"]([]), 0)
        self.assertEqual(json.loads(output.getvalue()), records)

    def test_process_budget_kills_and_reaps_without_network(self):
        client = self.module["SNMPClient"](ip="192.0.2.10", community="not-used", timeout=1)
        started = time.monotonic()
        result = client._execute([sys.executable, "-c", "import time; time.sleep(10)"], budget=0.1)
        self.assertFalse(result.success)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIn("timeout", result.error.lower())

    def test_snmp_arguments_have_explicit_timeout_and_no_retries(self):
        client = self.module["SNMPClient"](ip="2001:db8::10", port=1161, community="test", timeout=3, retries=0)
        with mock.patch.object(client, "_execute", return_value=self.module["Result"](True, b".1.3.6.1.2.1.1.1.0 = STRING: FC", "")) as execute:
            self.assertTrue(client.get("1.3.6.1.2.1.1.1.0").success)
        command = execute.call_args[0][0]
        self.assertEqual(command[command.index("-r") + 1], "0")
        self.assertEqual(command[command.index("-t") + 1], "3")
        self.assertEqual(command[-2], "[2001:db8::10]:1161")

    def test_help_and_version_do_not_collect(self):
        for flag in ["--help", "-h", "--version"]:
            result = subprocess.run([sys.executable, str(SOURCE), flag], capture_output=True, text=True, env={})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout)

    def test_all_brand_stages_tolerate_unavailable_numbers(self):
        stages = ["collect_system", "collect_port_status", "collect_port_traffic", "collect_port_errors", "collect_sensors", "collect_sfp"]
        for name in ["BrocadeMonitor", "CiscoMDSMonitor", "HuaweiMonitor", "FCMgmtMonitor"]:
            monitor_class = self.module[name]
            monitor = monitor_class.__new__(monitor_class)
            monitor.snmp = mock.Mock()
            monitor.snmp.get.return_value = self.module["Result"](True, "NA", "")
            monitor.snmp.walk.return_value = {"1": "NA"}
            for stage in stages:
                with self.subTest(brand=name, stage=stage):
                    rows = getattr(monitor, stage)("192.0.2.10")
                    self.assertEqual(rows, [])

    def test_invalid_status_does_not_become_healthy(self):
        monitor_class = self.module["BrocadeMonitor"]
        monitor = monitor_class.__new__(monitor_class)
        values = {monitor.OID["port_name"]: {"1": "FC1"}, monitor.OID["port_oper_status"]: {"1": "NA"}, monitor.OID["port_speed"]: {"1": 8}}
        monitor._walk_port_column = lambda oid: values.get(oid, {})
        rows = monitor.collect_port_status("192.0.2.10")
        self.assertEqual(rows[0]["vals"], {"m_port_speed": 8})

    def test_missing_memory_pool_free_does_not_imply_full_utilization(self):
        monitor_class = self.module["CiscoMDSMonitor"]
        monitor = monitor_class.__new__(monitor_class)
        monitor.snmp = mock.Mock()
        monitor.snmp.get.return_value = self.module["Result"](False, None, "unsupported")
        monitor.snmp.walk.side_effect = lambda oid: {"1": 50} if oid == monitor.OID["mem_pool_used"] else {}
        self.assertEqual(monitor.collect_system("192.0.2.10"), [])

    def test_fos_mapping_is_per_device_and_accepts_unicode_names(self):
        monitor_class = self.module["BrocadeMonitor"]
        original = dict(monitor_class.OID)
        base = original["port_table"]
        first = mock.Mock()
        first.walk.side_effect = lambda oid: {"1": 123} if oid == base + ".11" else {}
        second = mock.Mock()
        second.walk.side_effect = lambda oid: {"1": "端口一"} if oid == base + ".11" else {}
        monitor_class(first)
        later = monitor_class(second)
        self.assertEqual(monitor_class.OID, original)
        self.assertEqual(later.OID, original)

    def test_preflight_reuses_v3_auth_and_context_with_no_retry(self):
        client = self.module["SNMPClient"](ip="192.0.2.10", port=1161, version="3", username="reader", auth_key="authsecret", priv_key="privsecret", security_level="authPriv", context_name="ctx", timeout=10, retries=2)
        with mock.patch.object(client, "_execute", return_value=self.module["Result"](True, '.1.3.6.1.2.1.1.1.0 = STRING: "FC"', "")) as execute:
            self.module["preflight"](client)
        command = execute.call_args[0][0]
        self.assertEqual(command[command.index("-t") + 1], "3")
        self.assertEqual(command[command.index("-r") + 1], "0")
        self.assertEqual(command[command.index("-n") + 1], "ctx")
        self.assertEqual(command[command.index("-l") + 1], "authPriv")
        self.assertEqual(command[command.index("-A") + 1], "authsecret")
        self.assertEqual(command[command.index("-X") + 1], "privsecret")
        self.assertEqual((client.timeout, client.retries), (10, 2))

    def test_dependency_failure_is_readable_and_does_not_leak_secrets(self):
        client = self.module["SNMPClient"](ip="192.0.2.10", community="unique-secret")
        with mock.patch("subprocess.Popen", side_effect=OSError("dependency missing unique-secret")):
            result = client.get("1.3.6.1.2.1.1.1.0")
        self.assertFalse(result.success)
        self.assertIn("Traceback", result.error)
        self.assertNotIn("unique-secret", result.error)

    def test_walk_filters_missing_oids_and_preserves_unicode(self):
        client = self.module["SNMPClient"](ip="192.0.2.10", community="test")
        output = '.1.2.3.1 = STRING: "端口一"\n.1.2.3.2 = No Such Instance\n.1.2.30.1 = INTEGER: 8\n'
        with mock.patch.object(client, "_execute", return_value=self.module["Result"](True, output.encode(), "")):
            self.assertEqual(client.walk("1.2.3"), {"1": "端口一"})
        self.assertEqual(self.module["parse_snmp_value"]("INTEGER: online(1)"), 1)

    def test_empty_collection_becomes_error_not_empty_success(self):
        client = mock.Mock(timeout=10, retries=0)
        client.get.return_value = self.module["Result"](True, "FC device", "")
        monitor = mock.Mock()
        for stage in ["collect_system", "collect_port_status", "collect_port_traffic", "collect_port_errors", "collect_sensors", "collect_sfp"]:
            getattr(monitor, stage).return_value = []
        with mock.patch.dict(self.module, {"detect_vendor": lambda unused: "brocade", "VENDOR_MONITOR_MAP": {"brocade": lambda unused: monitor}}):
            with self.assertRaises(RuntimeError):
                self.module["collect_all"](client, "192.0.2.10")

    def test_all_brand_real_collection_outputs_registered_metrics(self):
        root = SOURCE.parents[1]
        origins = json.loads((root / "origin_metric.json").read_text())
        declared = {item["key"]: {tag["name"] for tag in item["tagDefine"]} for item in origins}
        for vendor in ["brocade", "cisco", "huawei", "fcmgmt"]:
            client = mock.Mock(timeout=10, retries=0)
            client.get.return_value = self.module["Result"](True, 1, "")
            client.walk.return_value = self.module["OrderedDict"]([("1", 1)])
            with self.subTest(vendor=vendor), mock.patch.dict(self.module, {"detect_vendor": lambda unused: vendor}):
                records = self.module["collect_all"](client, "192.0.2.10")
                self.assertTrue(records)
                for record in records:
                    for metric in record["vals"]:
                        self.assertIn(metric, declared)
                        self.assertEqual(set(record["dims"]), declared[metric])
                json.dumps(records, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
