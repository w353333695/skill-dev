# -*- coding: utf-8 -*-
"""IPMI 离线回归；同时使用 Python 2.7/3 执行，不连接任何设备。"""
import contextlib
import hashlib
import io
import json
import logging
import os
import signal
import subprocess
import sys
import time
import types
import unittest
import zipfile
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

ROOT = os.environ["IPMI_KIT_ROOT"]
SCRIPT = os.path.join(ROOT, "src", "ipmi_monitor.py")
monitor = types.ModuleType("ipmi_monitor")
monitor.__file__ = SCRIPT
with open(SCRIPT, "rb") as stream:
    exec(compile(stream.read(), SCRIPT, "exec"), monitor.__dict__)
monitor.load_dependencies()
from pyghmi.ipmi.private import pureaes, session
from pyghmi.ipmi import sdr

SETTINGS = {"ip": "192.0.2.10", "bmc_ip": "192.0.2.11", "username": "test-reader",
            "password": " fixture-secret ", "kg": "fixture-kg", "port": 623,
            "timeout": 5, "privilege": 2}


@contextlib.contextmanager
def changed(target, name, replacement):
    original = getattr(target, name)
    setattr(target, name, replacement)
    try:
        yield
    finally:
        setattr(target, name, original)


class Sensor(object):
    name = u"CPU 温度"
    type = "Temperature"
    units = u"\u00b0C"
    unavailable = False
    health = 0
    value = 42


class FakeReader(object):
    instance = None
    fail_login = False
    fail_sensor = None
    timeout_sensor = None

    def __init__(self, settings):
        FakeReader.instance = self
        self.closed = False
        self.sdr_called = False

    def login(self):
        if self.fail_login:
            raise RuntimeError("rejected " + SETTINGS["password"] + SETTINGS["kg"])

    def power(self):
        return 1

    def sensors(self):
        self.sdr_called = True
        return ["1.0", "2.0", "3.0"]

    def sensor(self, identifier):
        if identifier == self.fail_sensor:
            raise ValueError("optional read failed")
        if identifier == self.timeout_sensor:
            raise monitor.CollectTimeout("fixture timeout")
        return Sensor()

    def close(self):
        self.closed = True


class CollectorTests(unittest.TestCase):
    def setUp(self):
        FakeReader.fail_login = False
        FakeReader.fail_sensor = None
        FakeReader.timeout_sensor = None
        self.log = io.StringIO()
        self.handler = logging.StreamHandler(self.log)
        logging.getLogger().addHandler(self.handler)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)

    def test_success(self):
        rows = monitor.collect(SETTINGS, FakeReader)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_available"], 1)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_collect_complete"], 1)
        self.assertEqual(rows[1]["vals"]["physical_ipmi_temperature_celsius"], 42)
        self.assertNotEqual(rows[1]["dims"]["sensor_id"], rows[2]["dims"]["sensor_id"])
        self.assertTrue(FakeReader.instance.closed)
        self.assertEqual(json.loads(json.dumps(rows, allow_nan=False)), rows)

    def test_failure_redaction_and_no_fake_power(self):
        FakeReader.fail_login = True
        rows = monitor.collect(SETTINGS, FakeReader)
        values = rows[0]["vals"]
        self.assertEqual(values["physical_ipmi_available"], 0)
        self.assertNotIn("physical_ipmi_power_on", values)
        self.assertFalse(FakeReader.instance.sdr_called)
        for secret in (SETTINGS["password"], SETTINGS["kg"]):
            self.assertNotIn(secret, json.dumps(rows))
            self.assertNotIn(secret, self.log.getvalue())
        self.assertIn("Traceback", self.log.getvalue())
        self.assertTrue(FakeReader.instance.closed)

    def test_partial_failure_continues(self):
        FakeReader.fail_sensor = "2.0"
        rows = monitor.collect(SETTINGS, FakeReader)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_error_count"], 1)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_collect_complete"], 0)

    def test_timeout_preserves_previous_readings(self):
        FakeReader.timeout_sensor = "2.0"
        old_handler = signal.getsignal(signal.SIGALRM)
        rows = monitor.collect(SETTINGS, FakeReader)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_available"], 1)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_collect_complete"], 0)
        self.assertEqual(signal.getsignal(signal.SIGALRM), old_handler)
        self.assertEqual(signal.alarm(0), 0)

    def test_real_alarm_on_local_sleep(self):
        class SlowReader(FakeReader):
            def login(self):
                time.sleep(3)
        settings = dict(SETTINGS, timeout=1)
        started = time.time()
        rows = monitor.collect(settings, SlowReader)
        self.assertLess(time.time() - started, 2.5)
        self.assertEqual(rows[0]["vals"]["physical_ipmi_available"], 0)
        self.assertIn("CollectTimeout", rows[0]["vals"]["physical_ipmi_error"])

    def test_unavailable_never_healthy_or_zero_value(self):
        sensor = Sensor()
        sensor.unavailable = True
        self.assertEqual(monitor.sensor_values(sensor), {"physical_ipmi_sensor_available": 0})

    def test_units_and_nan(self):
        sensor = Sensor()
        for unit, suffix in (("RPM", "fan_rpm"), ("V", "voltage_volts"),
                             ("W", "power_watts"), ("A", "current_amperes"),
                             ("%", "sensor_percent"), (u"\u00b0F", "temperature_fahrenheit")):
            sensor.units = unit
            self.assertEqual(monitor.sensor_values(sensor)["physical_ipmi_" + suffix], 42)
        for unit in ("C", "RPM/W", "unknown"):
            sensor.units = unit
            self.assertEqual(len(monitor.sensor_values(sensor)), 2)
        sensor.units = u"\u00b0C"
        sensor.value = float("nan")
        self.assertNotIn("physical_ipmi_temperature_celsius", monitor.sensor_values(sensor))

    def test_health_bitmask(self):
        sensor = Sensor()
        for health in (0, 1, 2, 4, 3, 6, 7):
            sensor.health = health
            self.assertEqual(monitor.sensor_values(sensor)["physical_ipmi_sensor_health"], health)
        sensor.health = 8
        self.assertRaises(ValueError, monitor.sensor_values, sensor)
        sensor.health = None
        self.assertNotIn("physical_ipmi_sensor_health", monitor.sensor_values(sensor))

    def test_raw_command_deny_write(self):
        reader = monitor.IPMIReader(SETTINGS)
        self.assertRaises(ValueError, reader.raw_command, 0, 2, data=(3,))
        self.assertRaises(ValueError, reader.raw_command, 6, 0x45)

    def test_login_privilege(self):
        calls = []
        def fake_session(**kwargs):
            calls.append(kwargs)
            result = types.ModuleType("fake")
            result.ipmiversion = 2.0
            return result
        reader = monitor.IPMIReader(SETTINGS)
        with changed(reader.session_module, "Session", fake_session):
            reader.login()
        self.assertEqual(calls[0]["privlevel"], 2)
        self.assertFalse(calls[0]["keepalive"])
        self.assertEqual(calls[0]["password"], SETTINGS["password"])

    def test_config_defaults_and_secret_whitespace(self):
        clean = dict(("EASYOPS_COLLECTOR_" + key, str(value)) for key, value in SETTINGS.items())
        clean["EASYOPS_COLLECTOR_port"] = ""
        with changed(os, "environ", clean):
            self.assertEqual(monitor.config()["port"], 623)
            self.assertEqual(monitor.config()["password"], SETTINGS["password"])
            clean["EASYOPS_COLLECTOR_privilege"] = "4"
            self.assertRaises(ValueError, monitor.config)
            clean["EASYOPS_COLLECTOR_privilege"] = "2"
            clean["EASYOPS_COLLECTOR_bmc_ip"] = "$.ip"
            self.assertRaises(ValueError, monitor.config)

    def test_unknown_arch_rejected(self):
        with changed(monitor.platform, "machine", lambda: "i686"):
            self.assertRaises(RuntimeError, monitor.load_dependencies)

    def test_arm_bundle_selection_without_hardware_claim(self):
        with changed(monitor.platform, "machine", lambda: "aarch64"):
            monitor.load_dependencies()
            self.assertIn("arm64", sys.path[0])

    def test_main_output_is_only_json(self):
        environment = dict(("EASYOPS_COLLECTOR_" + key, str(value)) for key, value in SETTINGS.items())
        output = StringIO()
        rows = monitor.collect(SETTINGS, FakeReader)
        with changed(os, "environ", environment):
            with changed(monitor, "collect", lambda settings: rows):
                with changed(sys, "stdout", output):
                    self.assertEqual(monitor.main([]), 0)
        self.assertEqual(json.loads(output.getvalue()), rows)

    def test_escaped_secret_is_redacted(self):
        secret = u"fixture\n\t\\secret"
        settings = dict(SETTINGS, password=secret)
        for value in (secret, json.dumps(secret), repr(secret)):
            cleaned = monitor.scrub(value, settings)
            self.assertNotIn(secret, cleaned)
            self.assertNotIn("fixture", cleaned)

    def test_hash_mismatch_is_rejected(self):
        class BadDigest(object):
            def hexdigest(self):
                return "0" * 64
        with changed(monitor.hashlib, "sha256", lambda content: BadDigest()):
            self.assertRaises(RuntimeError, monitor.load_dependencies)

    def test_optional_none_defaults(self):
        environment = dict(("EASYOPS_COLLECTOR_" + key, str(value)) for key, value in SETTINGS.items())
        for key in ("port", "timeout", "login_timeout", "privilege"):
            environment["EASYOPS_COLLECTOR_" + key] = None
        with changed(os, "environ", environment):
            settings = monitor.config()
        self.assertEqual((settings["port"], settings["timeout"], settings["login_timeout"], settings["privilege"]),
                         (623, 60, 5, 2))

    def test_dimensions_match_definitions(self):
        with io.open(os.path.join(ROOT, "origin_metric.json"), encoding="utf-8") as stream:
            origins = dict((row["key"], row) for row in json.load(stream))
        for row in monitor.collect(SETTINGS, FakeReader):
            for key in row["vals"]:
                self.assertEqual(set(row["dims"]), set(item["name"] for item in origins[key]["tagDefine"]))


class ProtocolTests(unittest.TestCase):
    def test_pause_propagates_timeout(self):
        class FakePause(object):
            @classmethod
            def wait_for_rsp(cls, timeout):
                raise monitor.CollectTimeout("fixture interrupted wait")
        method = session.Session.pause
        implementation = getattr(method, "__func__", None) or method.im_func
        with changed(session, "_monotonic_time", lambda: 0):
            self.assertRaises(monitor.CollectTimeout, implementation, FakePause, 1)

    def test_nist_aes_cbc(self):
        self.assertTrue(pureaes.self_test())

    def test_aes_rejects_partial_blocks(self):
        self.assertRaises(ValueError, pureaes.encrypt, b"x" * 16, b"y" * 16, b"bad")

    def test_ipmi_padding_roundtrip(self):
        for length in range(1, 65):
            payload = bytearray(range(length))
            padded = bytes(payload + session._aespad(payload))
            decoded = pureaes.decrypt(b"k" * 16, b"i" * 16, pureaes.encrypt(b"k" * 16, b"i" * 16, padded))
            decoded = bytearray(decoded)
            self.assertEqual(decoded[:-(decoded[-1] + 1)], payload)

    def test_ipmi15_downgrade_blocked_without_network(self):
        holder = object.__new__(session.Session)
        holder.ipmiversion = 1.5
        holder.ipmi15only = None
        replies = []
        holder.onlogon = replies.append
        session.Session._got_channel_auth_cap(holder, {"code": 0, "data": bytearray((1, 4, 0, 0)), "command": 0x38, "netfn": 7})
        self.assertIn("downgrade disabled", replies[0]["error"])

    def test_real_sdr_full_sensor_decode(self):
        body = bytearray(43 + 4)
        body[0:3] = bytearray((0x20, 0, 1))
        body[5] = 0x40
        body[7] = 1
        body[8] = 1
        body[16] = 1
        body[19] = 1
        body[42] = 0xc4
        body[43:] = bytearray(b"TEMP")
        raw = bytearray((1, 0, 0x51, 1, len(body))) + body
        from pyghmi.ipmi.private import constants
        entry = sdr.SDREntry(raw, constants)
        reader = monitor.IPMIReader(SETTINGS)
        reading = entry.decode_sensor_reading(reader, bytearray((42, 0x40, 0, 0)))
        self.assertEqual(reading.name, "TEMP")
        self.assertAlmostEqual(reading.value, 42)
        self.assertAlmostEqual(monitor.sensor_values(reading)["physical_ipmi_temperature_celsius"], 42)


class PackageTests(unittest.TestCase):
    def test_metric_alias_and_alert_graph(self):
        def read(name):
            with io.open(os.path.join(monitor.text(ROOT), monitor.text(name)), encoding="utf-8") as stream:
                return json.load(stream)
        origins = dict((row["key"], row) for row in read("origin_metric.json"))
        groups = set(row["name"] for row in read("metric_set.json"))
        aliases = read("alias_metric.json")
        self.assertEqual(len(aliases), len(set(row["displayName"] for row in aliases)))
        for alias in aliases:
            self.assertTrue(alias["displayName"].startswith(u"物理机IPMI-"))
            self.assertTrue(set(alias["metricSet"]).issubset(groups))
            self.assertTrue(set(alias["originalMetrics"]).issubset(origins))
            expected = set(tag["name"] for key in alias["originalMetrics"] for tag in origins[key]["tagDefine"])
            self.assertEqual(expected, set(dim["originDimName"] for dim in alias["dims"]))
        template = os.path.join(ROOT, u"物理服务器IPMI告警规则模板.xlsx")
        self.assertTrue(os.path.isfile(template))
        with open(template, "rb") as stream:
            self.assertEqual(stream.read(2), b"PK")

    def test_arch_bundles_are_identical_and_pure(self):
        bundles = []
        for architecture in ("x86_64", "arm64"):
            folder = os.path.join(ROOT, "vendor", architecture)
            with open(os.path.join(folder, "manifest.json")) as stream:
                manifest = json.load(stream)
            with open(os.path.join(folder, "dependencies.zip"), "rb") as stream:
                data = stream.read()
            bundles.append(data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["sha256"])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                for package in ("pyghmi", "pyaes", "six"):
                    self.assertTrue(any(name.startswith("LICENSES/" + package + "-") for name in names))
                self.assertFalse(any(name.endswith((".so", ".pyc", ".dll")) for name in names))
        self.assertEqual(bundles[0], bundles[1])

    def test_orig_regeneration(self):
        with open(os.path.join(ROOT, "src/ipmi_monitor.orig"), "rb") as stream:
            original = stream.read()
        self.assertNotIn(b'from __future__', original)
        regenerated = b'import os\nip = os.environ.get("EASYOPS_COLLECTOR_ip")\n' + original
        namespace = {"__name__": "regenerated", "__file__": SCRIPT}
        exec(compile(regenerated, "renamed.py", "exec"), namespace)
        self.assertIn("collect", namespace)

    def test_header(self):
        with open(SCRIPT, "rb") as stream:
            lines = stream.read().splitlines()
        self.assertTrue(lines[0].startswith(b"#!"))
        self.assertIn(b"coding: utf-8", lines[1])
        self.assertEqual(lines[2], b"import os")

    def test_doctor_help_version_no_network(self):
        for flag in ("--doctor", "-h", "--version"):
            process = subprocess.Popen([sys.executable, SCRIPT, flag], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(stdout or stderr)

    def test_invalid_config_frontend_error_and_redaction(self):
        environment = dict((key, value) for key, value in os.environ.items() if not key.startswith("EASYOPS_COLLECTOR_"))
        environment["EASYOPS_COLLECTOR_password"] = "fixture-private"
        process = subprocess.Popen([sys.executable, SCRIPT], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0)
        self.assertIn(b"COLLECT_ERROR:", stdout)
        self.assertIn(b"Traceback", stdout)
        self.assertNotIn(b"fixture-private", stdout + stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
