# -*- coding: utf-8 -*-
"""vCenter监控采集脚本离线回归：mock 对象树回放，不连接真实 vCenter。"""
import io
import json
import os
import sys
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KIT = Path(__file__).resolve().parents[2] / "monitor-kits/vcenter-monitoring"
SOURCE = KIT / "src/vcenter_monitor.py"


def _kwarg_type(cls_name):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    return type(cls_name, (object,), {"__init__": __init__})


def stub_sdk_modules():
    """agent 的 pyVim/pyVmomi 在开发环境不存在，注入最小可导入桩。
    vmodl.query.PropertyCollector 的 spec 构造类按脚本真实调用面补齐。"""
    pyvim = types.ModuleType("pyVim")
    pyvim_connect = types.ModuleType("pyVim.connect")
    pyvim.connect = pyvim_connect
    sys.modules["pyVim"] = pyvim
    sys.modules["pyVim.connect"] = pyvim_connect
    pyvmomi = types.ModuleType("pyVmomi")
    vim_mod = types.ModuleType("pyVmomi.vim")
    for cls_name in ("PerfMetricId", "PerfQuerySpec", "Folder", "Datacenter",
                     "ComputeResource", "ClusterComputeResource", "HostSystem",
                     "VirtualMachine", "Datastore"):
        setattr(vim_mod, cls_name, _kwarg_type(cls_name))
    vmodl_mod = types.ModuleType("pyVmomi.vmodl")
    query_mod = types.ModuleType("vmodl.query")
    pc = _kwarg_type("PropertyCollector")
    for cls_name in ("TraversalSpec", "SelectionSpec", "ObjectSpec",
                     "PropertySpec", "FilterSpec", "RetrieveOptions"):
        setattr(pc, cls_name, _kwarg_type(cls_name))
    query_mod.PropertyCollector = pc
    vmodl_mod.query = query_mod
    pyvmomi.vim = vim_mod
    pyvmomi.vmodl = vmodl_mod
    sys.modules["pyVmomi"] = pyvmomi
    sys.modules["pyVmomi.vim"] = vim_mod
    sys.modules["pyVmomi.vmodl"] = vmodl_mod


def module(name="vcenter_monitor_under_test"):
    stub_sdk_modules()
    namespace = {"__name__": name}
    exec(compile(SOURCE.read_bytes(), str(SOURCE), "exec"), namespace)
    return namespace


class FakeRef(object):
    """托管对象引用桩：仅 _type 参与 assemble_rows 分派。"""

    def __init__(self, kind, value):
        self._type = kind
        self.value = value

    def __hash__(self):
        return hash((self._type, self.value))

    def __eq__(self, other):
        return isinstance(other, FakeRef) and (self._type, self.value) == (other._type, other.value)


def collect_namespace():
    return module()


def fake_content():
    """fake ServiceInstance.content：propertyCollector 仅作透传（retrieve_rows 已被 patch）。"""
    return SimpleNamespace(content=SimpleNamespace(propertyCollector=None))


class ConfigTests(unittest.TestCase):
    def test_address_normalization(self):
        m = collect_namespace()
        cases = {
            "https://9.132.63.82/sdk": ("https", "9.132.63.82", 443),
            "https://vc.corp.com:8443/sdk": ("https", "vc.corp.com", 8443),
            "http://vc.corp.com:8080/sdk": ("http", "vc.corp.com", 8080),
            "9.132.63.82": ("https", "9.132.63.82", 443),
            "9.132.63.82:443": ("https", "9.132.63.82", 443),
            " vc.local/ ": ("https", "vc.local", 443),
            "http://vc.local": ("http", "vc.local", 80),
        }
        for raw, expected in cases.items():
            self.assertEqual(m["normalize_address"](raw), expected, raw)
        for bad in ["", "ftp://vc.local", "vc.local:notaport", "vc.local:99999"]:
            with self.assertRaises(ValueError, msg=bad):
                m["normalize_address"](bad)

    def test_config_requires_params(self):
        m = collect_namespace()
        base = {
            "EASYOPS_COLLECTOR_address": "https://9.132.63.82/sdk",
            "EASYOPS_COLLECTOR_username": "svc-monitor",
            "EASYOPS_COLLECTOR_password": "secret",
        }
        with mock.patch.dict(os.environ, base, clear=True):
            cfg = m["config"]()
        self.assertEqual(cfg["host"], "9.132.63.82")
        self.assertEqual(cfg["port"], 443)
        self.assertEqual(cfg["timeout"], 60)
        self.assertEqual(cfg["logLevel"], "ERROR")
        self.assertEqual(cfg["vcDim"], "9.132.63.82:443")
        self.assertEqual(cfg["password"], "secret")  # 连接需要；不进任何日志（见 DebugLogTests）
        for missing in ("address", "username", "password"):
            env = dict(base)
            env["EASYOPS_COLLECTOR_" + missing] = ""
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError, msg=missing):
                    m["config"]()
        for bad_env, key in (
            ({"EASYOPS_COLLECTOR_address": "$.url"}, "address"),
            ({"EASYOPS_COLLECTOR_timeout": "abc"}, "timeout"),
            ({"EASYOPS_COLLECTOR_timeout": "301"}, "timeout"),
            ({"EASYOPS_COLLECTOR_timeout": "9"}, "timeout"),
            ({"EASYOPS_COLLECTOR_logLevel": "verbose"}, "logLevel"),
        ):
            env = dict(base)
            env.update(bad_env)
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError, msg=key):
                    m["config"]()

    def test_param_blank_falls_back(self):
        m = collect_namespace()
        env = {"EASYOPS_COLLECTOR_timeout": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(m["get_param"]("timeout", "60"), "60")
            self.assertEqual(m["get_param"]("logLevel", "ERROR"), "ERROR")


class UtilTests(unittest.TestCase):
    def test_safe_text_keeps_unicode_and_decodes_bytes(self):
        m = collect_namespace()
        value = u"数据中心-生产"
        self.assertIs(m["safe_text"](value), value)
        self.assertEqual(m["safe_text"](value.encode("utf-8")), value)
        if m["PY2"]:
            self.assertIs(m["safe_text"](b"plain"), b"plain".decode("utf-8"))

    def test_ascii_line_ascii_safe(self):
        m = collect_namespace()
        line = m["ascii_line"](u"数据中心")
        if m["PY2"]:
            line.encode("ascii")  # py2 必须能 ASCII 编码进 JSON 日志
        else:
            self.assertEqual(line, u"数据中心")  # py3 stdout 原生支持 unicode

    def test_enum_and_number_helpers(self):
        m = collect_namespace()
        self.assertEqual(m["enum_value"](m["STATUS_MAP"], "red", 3), 2)
        self.assertEqual(m["enum_value"](m["STATUS_MAP"], "purple", 3), 3)
        self.assertEqual(m["enum_value"](m["STATUS_MAP"], None, 3), 3)
        self.assertIsNone(m["number_or_none"]("not-a-number"))
        self.assertIsNone(m["number_or_none"](None))
        self.assertEqual(m["number_or_none"](True), 1.0)
        self.assertEqual(m["number_or_none"](False), 0.0)
        self.assertEqual(m["number_or_none"](5), 5.0)
        self.assertIsNone(m["attr_chain"](None, "x"))
        self.assertIsNone(m["attr_chain"](object(), "missing", "deep"))


class DebugLogTests(unittest.TestCase):
    def test_debug_buffered_until_dump_and_off_standard_streams(self):
        """DEBUG 日志内存缓冲：event 期间不碰 stdout/stderr，dump_lines 输出 ASCII 安全 JSON 行。"""
        m = collect_namespace()
        logger = m["DebugLog"]("DEBUG")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            logger.event("DEBUG", "config.ready", host=u"生产主机", username="svc-monitor")
            logger.traceback_event("WARN", "probe", "[probe]")
            lines = logger.dump_lines()
        self.assertEqual(stdout.getvalue(), "")  # 缓冲期间 stdout 干净
        self.assertEqual(len(lines), 2)
        entries = [json.loads(line[len("[DEBUG] "):]) for line in lines]
        self.assertEqual(entries[0]["host"], u"生产主机")
        self.assertEqual(entries[0]["username"], "svc-monitor")
        self.assertIn("traceback", entries[1])
        for line in lines:
            line.encode("ascii")  # 每行可 ASCII 编码（中文 \uXXXX 转义，py2 安全）
        # 密码不在缓冲条目里（调用方不发即不落）
        self.assertNotIn("password", entries[0])

    def test_error_level_logger_is_silent(self):
        """默认 ERROR 级别：任何 event 都不缓冲不输出（fatal 走 COLLECT_ERROR stdout 协议）。"""
        m = collect_namespace()
        logger = m["DebugLog"]("ERROR")
        logger.event("DEBUG", "quiet.debug")
        logger.event("WARN", "quiet.warn")
        logger.event("ERROR", "loud.error")
        self.assertEqual(logger.entries, [])
        self.assertEqual(logger.dump_lines(), [])

    def test_non_debug_levels_fully_silent(self):
        """INFO/WARN 档与 ERROR 同为完全静默（仅 DEBUG 档缓冲进 stdout 协议）。"""
        m = collect_namespace()
        for level_name in ("INFO", "WARN"):
            logger = m["DebugLog"](level_name)
            logger.event("DEBUG", "quiet.debug")
            logger.event(level_name, "same.level")
            self.assertEqual(logger.entries, [], level_name)
            self.assertEqual(logger.dump_lines(), [], level_name)


class CollectTests(unittest.TestCase):
    def build_fake(self):
        now = datetime.now()
        vc_ref = FakeRef("Datacenter", "datacenter-1")
        cr_ref = FakeRef("ClusterComputeResource", "domain-c7")
        host_ref = FakeRef("HostSystem", "host-10")
        vm_ref = FakeRef("VirtualMachine", "vm-100")
        ds_ref = FakeRef("Datastore", "datastore-11")

        cr_props = {"name": "Cluster-A",
                    "summary": SimpleNamespace(generalStatus="green", effectiveCpu=10000.0,
                                               effectiveMemory=40960.0)}
        host_props = {"name": "esxi-01", "parent": cr_ref,
                      "summary": SimpleNamespace(
                          quickStats=SimpleNamespace(overallCpuUsage=1000.0, overallMemoryUsage=2048.0,
                                                     balloonedMemory=102.0, uptime=7200.0),
                          runtime=SimpleNamespace(connectionState="connected", powerState="poweredOn"),
                          hardware=SimpleNamespace(memorySize=64.0 * 1024 * 1024 * 1024,
                                                   numCpuCores=2.0, cpuMhz=2500.0),
                          overallStatus="green")}
        vm_props = {"name": u"虚拟机-web-01",
                    "runtime": SimpleNamespace(host=host_ref, powerState="poweredOn",
                                               maxCpuUsage=4000.0, maxMemoryUsage=4096.0,
                                               bootTime=now - timedelta(seconds=3600)),
                    "summary": SimpleNamespace(
                        quickStats=SimpleNamespace(overallCpuUsage=1000.0, guestMemoryUsage=2048.0),
                        storage=SimpleNamespace(committed=20.0 * 1024 * 1024 * 1024,
                                                uncommitted=20.0 * 1024 * 1024 * 1024),
                        guest=SimpleNamespace(toolsStatus="toolsOk"))}
        ds_props = {"name": "DS-01",
                    "summary": SimpleNamespace(accessible=True, capacity=100.0 * 1024 * 1024 * 1024,
                                               freeSpace=10.0 * 1024 * 1024 * 1024)}
        rows = [
            {"obj": cr_ref, "props": cr_props},
            {"obj": host_ref, "props": host_props},
            {"obj": vm_ref, "props": vm_props},
            {"obj": ds_ref, "props": ds_props},
        ]
        return {
            "vc_ref": vc_ref, "cr_ref": cr_ref, "host_ref": host_ref,
            "vm_ref": vm_ref, "ds_ref": ds_ref, "rows": rows,
        }

    def test_collect_vcenter_assembles_records(self):
        m = collect_namespace()
        fake = self.build_fake()
        cfg = {"vcDim": "9.132.63.82:443"}
        log = m["DebugLog"]("ERROR")

        m_state = {"dcs": [{"obj": fake["vc_ref"], "name": u"生产数据中心"}]}
        orig_collect = m["collect_datacenter_names"]
        orig_retrieve = m["retrieve_rows"]
        orig_perf = m["query_perf"]
        m["collect_datacenter_names"] = lambda content: m_state["dcs"]
        m["retrieve_rows"] = lambda pc, from_obj, select_set, prop_specs: fake["rows"]
        m["query_perf"] = lambda content, entity_slots, log, deadline: {
            fake["ds_ref"]: {"read_latency": 12.0, "write_latency": 34.0},
            fake["host_ref"]: {"net_in": 100.0, "net_out": 200.0},
        }
        try:
            records = m["collect_vcenter"](fake_content(), cfg, log, time.time() + 60)
        finally:
            m["collect_datacenter_names"] = orig_collect
            m["retrieve_rows"] = orig_retrieve
            m["query_perf"] = orig_perf

        self.assertEqual(len(records), 5)
        platform = records[0]
        self.assertEqual(platform["dims"], {"vc": "9.132.63.82:443"})
        self.assertEqual(platform["vals"]["vcenter_available"], 1.0)
        self.assertEqual(platform["vals"]["vcenter_collect_complete"], 1.0)

        cluster = [r for r in records if "cluster" in r["dims"] and "host" not in r["dims"]][0]
        self.assertEqual(cluster["dims"], {"vc": "9.132.63.82:443", "datacenter": u"生产数据中心",
                                           "cluster": "Cluster-A"})
        self.assertEqual(cluster["vals"]["vcenter_cluster_status"], 0)
        self.assertEqual(cluster["vals"]["vcenter_cluster_host_total"], 1.0)
        self.assertEqual(cluster["vals"]["vcenter_cluster_vm_total"], 1.0)
        self.assertEqual(cluster["vals"]["vcenter_cluster_vm_powered_on"], 1.0)
        self.assertAlmostEqual(cluster["vals"]["vcenter_cluster_cpu_usage_pct"], 10.0)
        self.assertAlmostEqual(cluster["vals"]["vcenter_cluster_mem_usage_pct"], 5.0)

        ds = [r for r in records if "datastore" in r["dims"]][0]
        self.assertEqual(ds["dims"]["datastore"], "DS-01")
        self.assertEqual(ds["vals"]["vcenter_datastore_accessible"], 1.0)
        self.assertEqual(ds["vals"]["vcenter_datastore_capacity_gb"], 100.0)
        self.assertEqual(ds["vals"]["vcenter_datastore_free_gb"], 10.0)
        self.assertAlmostEqual(ds["vals"]["vcenter_datastore_usage_pct"], 90.0)
        self.assertEqual(ds["vals"]["vcenter_datastore_read_latency_ms"], 12.0)
        self.assertEqual(ds["vals"]["vcenter_datastore_write_latency_ms"], 34.0)

        host = [r for r in records if "host" in r["dims"] and "vm" not in r["dims"]][0]
        self.assertEqual(host["dims"]["host"], "esxi-01")
        self.assertEqual(host["vals"]["vcenter_host_connection_state"], 0)
        self.assertAlmostEqual(host["vals"]["vcenter_host_cpu_usage_pct"], 20.0)
        self.assertAlmostEqual(host["vals"]["vcenter_host_mem_usage_pct"], 2048.0 / 65536.0 * 100.0)
        self.assertEqual(host["vals"]["vcenter_host_net_in_kbps"], 100.0)
        self.assertEqual(host["vals"]["vcenter_host_vm_count"], 1.0)

        vm = [r for r in records if "vm" in r["dims"]][0]
        self.assertEqual(vm["dims"]["vm"], u"虚拟机-web-01")
        self.assertEqual(vm["dims"]["cluster"], "Cluster-A")
        self.assertEqual(vm["vals"]["vcenter_vm_power_state"], 1)
        self.assertAlmostEqual(vm["vals"]["vcenter_vm_cpu_usage_pct"], 25.0)
        self.assertAlmostEqual(vm["vals"]["vcenter_vm_mem_usage_pct"], 50.0)
        self.assertEqual(vm["vals"]["vcenter_vm_storage_committed_gb"], 20.0)
        self.assertAlmostEqual(vm["vals"]["vcenter_vm_storage_usage_pct"], 50.0)
        self.assertEqual(vm["vals"]["vcenter_vm_tools_status"], 0)
        self.assertGreater(vm["vals"]["vcenter_vm_uptime_seconds"], 3500)

        # stdout 输出必须是纯 JSON 数组且不含密码
        payload = json.dumps(records)
        self.assertIn(u"生产数据中心".encode("unicode_escape").decode(), json.dumps(records, ensure_ascii=True))

    def test_missing_perf_and_none_values_are_skipped_not_faked(self):
        m = collect_namespace()
        fake = self.build_fake()
        log = m["DebugLog"]("ERROR")
        m["collect_datacenter_names"] = lambda content: [{"obj": fake["vc_ref"], "name": "DC"}]
        m["retrieve_rows"] = lambda pc, from_obj, select_set, prop_specs: fake["rows"]
        m["query_perf"] = lambda content, entity_slots, log, deadline: {}
        cfg = {"vcDim": "vc:443"}
        records = m["collect_vcenter"](fake_content(), cfg, log, time.time() + 60)
        ds = [r for r in records if "datastore" in r["dims"]][0]
        self.assertNotIn("vcenter_datastore_read_latency_ms", ds["vals"])
        host = [r for r in records if "host" in r["dims"] and "vm" not in r["dims"]][0]
        self.assertNotIn("vcenter_host_net_in_kbps", host["vals"])

    def test_main_emits_pure_json(self):
        m = collect_namespace()
        records = [{"dims": {"vc": "x"}, "vals": {"vcenter_available": 1.0}}]
        m["config"] = lambda: {"scheme": "https", "host": "vc", "port": 443,
                               "username": "u", "password": "p", "timeout": 60,
                               "logLevel": "ERROR", "vcDim": "vc:443"}
        m["connect_vcenter"] = lambda cfg, log: object()
        m["disconnect"] = lambda si, log: None
        m["collect_vcenter"] = lambda si, cfg, log, deadline: records
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = m["main"]()
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue()), records)

    def test_main_debug_mode_emits_collect_error_protocol_with_metrics_tail(self):
        """DEBUG 模式：stdout 按 COLLECT_ERROR: 协议输出诊断行（前端当错误正文直接展示），
        指标 JSON 保留在 METRICS: 之后可提取；不含密码。"""
        m = collect_namespace()
        records = [{"dims": {"vc": "x"}, "vals": {"vcenter_available": 1.0}}]
        m["config"] = lambda: {"scheme": "https", "host": "vc", "port": 443,
                               "username": "svc-monitor", "password": "vcenter-secret",
                               "timeout": 60, "logLevel": "DEBUG", "vcDim": "vc:443"}
        m["connect_vcenter"] = lambda cfg, log: object()
        m["disconnect"] = lambda si, log: None
        m["collect_vcenter"] = lambda si, cfg, log, deadline: records
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = m["main"]()
        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertTrue(output.startswith("COLLECT_ERROR:"), output[:200])
        self.assertIn("[DEBUG]", output)
        self.assertIn("METRICS:", output)
        tail = output.split("METRICS:\n", 1)[1]
        self.assertEqual(json.loads(tail), records)  # METRICS 之后仍是可解析 JSON
        self.assertNotIn("vcenter-secret", output)
        # 诊断行含 config.ready（用户名可见、密码不出现）
        self.assertIn("svc-monitor", output)
        self.assertIn("config.ready", output)


class ConnectFallbackTests(unittest.TestCase):
    """TLS 三级降级 + 密码候选循环（目标环境 11.66.19.194 debug 实测回归）。"""

    def cfg(self, password):
        return {"scheme": "https", "host": "11.66.17.210", "port": 443,
                "username": "zabbix", "password": password,
                "timeout": 60, "logLevel": "ERROR", "vcDim": "11.66.17.210:443"}

    def test_password_candidates_base64_obfuscated_first(self):
        """debug 弹窗轻混淆值（base64(明文)）注入时：解码值排首候选，原值兜底。"""
        m = collect_namespace()
        log = m["DebugLog"]("DEBUG")
        # 用户 debug 实测值：MTIzNC5Bc2Qh = base64("1234.Asd!")
        candidates = m["password_candidates"](self.cfg("MTIzNC5Bc2Qh"), log)
        self.assertEqual(candidates, ["1234.Asd!", "MTIzNC5Bc2Qh"])
        # 正式任务明文（含 ! 非合法 base64）：单候选不受影响
        self.assertEqual(m["password_candidates"](self.cfg("1234Asd!"), log), ["1234Asd!"])
        # 明文恰好是合法 base64（4倍数长度）且解码可打印：解码值优先，原值兜底仍可回退
        dual = m["password_candidates"](self.cfg("MTIzNDA="), log)  # = base64("12340")
        self.assertEqual(dual, ["12340", "MTIzNDA="])
        # 空/二进制解码：单候选
        self.assertEqual(m["password_candidates"](self.cfg(""), log), [""])
        binary = m["password_candidates"](self.cfg("AAECAwQ="), log)  # 解码含控制字符
        self.assertEqual(binary, ["AAECAwQ="])

    def test_tls_falls_back_to_ssl_context_then_plain(self):
        """旧版 pyVim：disableSslCertValidation TypeError → sslContext 分支成功（11.66.19.194 实证）。"""
        m = collect_namespace()
        calls = []

        class FakeSI(object):
            def RetrieveServiceContent(self):
                return SimpleNamespace(about=SimpleNamespace(apiType="vCenter", version="7.0"))

        def fake_smart_connect(**kwargs):
            calls.append(kwargs)
            if "disableSslCertValidation" in kwargs:
                raise TypeError("unexpected keyword 'disableSslCertValidation'")
            self.assertIn("sslContext", kwargs)
            self.assertEqual(kwargs["sslContext"].verify_mode, m["ssl"].CERT_NONE)
            return FakeSI()

        with mock.patch.dict(m, {"pyvim_connect": SimpleNamespace(SmartConnect=fake_smart_connect)}):
            cfg = self.cfg("1234Asd!")
            si = m["connect_vcenter"](cfg, m["DebugLog"]("ERROR"))
        self.assertIsInstance(si, FakeSI)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("disableSslCertValidation", calls[1])

    def test_all_candidates_failed_hint_mentions_secret_chain(self):
        """全部候选认证失败：错误信息带密钥管理链路指引，不回显候选值。"""
        m = collect_namespace()

        class InvalidLogin(Exception):
            pass

        def fake_smart_connect(**kwargs):
            raise m["vim"].fault.InvalidLogin()

        fault_mod = types.ModuleType("pyVmomi.vim.fault")
        fault_mod.InvalidLogin = InvalidLogin
        m["vim"].fault = fault_mod
        with mock.patch.dict(m, {"pyvim_connect": SimpleNamespace(SmartConnect=fake_smart_connect)}):
            with self.assertRaises(ValueError) as ctx:
                m["connect_vcenter"](self.cfg("MTIzNC5Bc2Qh"), m["DebugLog"]("ERROR"))
        msg = str(ctx.exception)
        self.assertIn("密钥管理", msg)
        self.assertIn("secretName", msg)
        self.assertNotIn("MTIzNC5Bc2Qh", msg)
        self.assertNotIn("1234.Asd!", msg)

    def test_auth_failure_rotates_password_candidates(self):
        """认证失败才换下一个候选（解码值→原值）；TLS 错误不换直接抛。"""
        m = collect_namespace()
        tried = []

        class AuthError(Exception):
            pass

        def fake_smart_connect(**kwargs):
            tried.append(kwargs["pwd"])
            if kwargs["pwd"] != "1234.Asd!":
                raise m["vim"].fault.InvalidLogin()
            return SimpleNamespace(
                content=SimpleNamespace(about=SimpleNamespace(apiType="v")),
                RetrieveServiceContent=lambda: SimpleNamespace(
                    about=SimpleNamespace(apiType="vCenter", version="7.0")))

        # vim.fault.InvalidLogin 桩
        fault_mod = types.ModuleType("pyVmomi.vim.fault")
        fault_mod.InvalidLogin = AuthError
        m["vim"].fault = fault_mod
        with mock.patch.dict(m, {"pyvim_connect": SimpleNamespace(SmartConnect=fake_smart_connect)}):
            cfg = self.cfg("MTIzNC5Bc2Qh")
            si = m["connect_vcenter"](cfg, m["DebugLog"]("ERROR"))
        self.assertEqual(tried, ["1234.Asd!"])  # 解码值首候选直接命中，无需回退
        # TLS/网络类错误不换候选直接抛
        tried[:] = []

        def fake_tls_fail(**kwargs):
            tried.append(kwargs["pwd"])
            raise OSError("CERTIFICATE_VERIFY_FAILED")

        with mock.patch.dict(m, {"pyvim_connect": SimpleNamespace(SmartConnect=fake_tls_fail)}):
            with self.assertRaises(OSError):
                m["connect_vcenter"](self.cfg("MTIzNC5Bc2Qh"), m["DebugLog"]("ERROR"))
        self.assertEqual(len(tried), 1)  # 未轮换


class MoTypeCompatTests(unittest.TestCase):
    """TraversalSpec/PropertySpec type 字段兼容（0.1.5 目标环境 TypeError 实证回归）。"""

    def _strict_vmodl(self, m):
        """复现目标环境 pyVmomi：TraversalSpec/PropertySpec 的 type 字段必须是类对象。"""
        def check(name):
            def __init__(self, **kw):
                if not isinstance(kw.get('type'), type):
                    raise TypeError('For "type" expected type type, but got %s'
                                    % type(kw.get('type')).__name__)
                self.__dict__.update(kw)
            return type(name, (object,), {"__init__": __init__})
        pc = m["vmodl"].query.PropertyCollector
        pc.TraversalSpec = check("TraversalSpec")
        pc.PropertySpec = check("PropertySpec")

    def test_traversal_spec_uses_managed_object_class(self):
        m = collect_namespace()
        self._strict_vmodl(m)
        specs = m["_folder_recursion_specs"]()
        self.assertEqual(len(specs), 5)  # 全部构造成功（类对象通过严格校验）
        spec = m["_ts"]("rootToDC", "Folder", "childEntity", [])
        self.assertEqual(spec.path, "childEntity")

    def test_mo_type_falls_back_to_string_when_class_missing(self):
        m = collect_namespace()
        # 极老版本/桩缺类属性：getattr(vim, name) 为 None → 退字符串
        missing = types.ModuleType("pyVmomi.vim")  # 无 Folder 属性
        with mock.patch.object(m["vim"], "Folder", None, create=True):
            self.assertEqual(m["_mo_type"]("Folder"), "Folder")

    def test_prop_spec_resolves_type(self):
        m = collect_namespace()
        self._strict_vmodl(m)
        spec = m["_prop_spec"]("Datastore", ["name", "summary"])
        self.assertTrue(isinstance(spec.type, type))


class FatalProtocolTests(unittest.TestCase):
    def test_top_level_exception_prints_collect_error_and_exits_zero(self):
        """顶层异常走 COLLECT_ERROR: 协议（exit 0，stdout 可见错误正文，凭据不出现）。
        用子进程 + SDK 桩真实执行 __main__ 守卫；连不上的地址触发采集异常。"""
        import subprocess
        runner = (
            "import sys, types\n"
            "pyvim = types.ModuleType('pyVim'); conn = types.ModuleType('pyVim.connect')\n"
            "pyvim.connect = conn\n"
            "pm = types.ModuleType('pyVmomi')\n"
            "pm.vim = types.ModuleType('pyVmomi.vim'); pm.vmodl = types.ModuleType('pyVmomi.vmodl')\n"
            "sys.modules['pyVim'] = pyvim; sys.modules['pyVim.connect'] = conn\n"
            "sys.modules['pyVmomi'] = pm; sys.modules['pyVmomi.vim'] = pm.vim\n"
            "sys.modules['pyVmomi.vmodl'] = pm.vmodl\n"
            "source = open(%r, 'rb').read()\n"
            "exec(compile(source, 'vcenter_monitor.py', 'exec'))\n"
        ) % str(SOURCE)
        env = dict(os.environ)
        env.update({
            "EASYOPS_COLLECTOR_address": "https://127.0.0.1:1/sdk",
            "EASYOPS_COLLECTOR_username": "svc-monitor",
            "EASYOPS_COLLECTOR_password": "vcenter-secret",
        })
        proc = subprocess.run([sys.executable, "-"], input=runner, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("COLLECT_ERROR:"), proc.stdout[:200])
        self.assertNotIn("vcenter-secret", proc.stdout)


if __name__ == "__main__":
    unittest.main()
