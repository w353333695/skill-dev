import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "monitor-kits"
    / "os-snmp-monitoring"
    / "src"
    / "os_snmp_monitor.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("os_snmp_monitor", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mock_snmp(monkeypatch, build_responses):
    module = load_module()
    responses = build_responses(module)

    def run_snmp(oid, walk=False):
        lines = responses.get(oid, [])
        if isinstance(lines, list):
            return lines, ""
        return [], lines

    monkeypatch.setattr(module, "run_snmp", run_snmp)
    return module


def scalar(value):
    return ["1.2.3 = %s" % value]


def test_linux_effective_memory_and_partition_filter(monkeypatch, capsys):
    module = mock_snmp(
        monkeypatch,
        lambda module: {
            module.BASE["sys_descr"]: scalar("STRING: Linux"),
            module.BASE["hr_system_uptime"]: scalar("Timeticks: (100) 0:01:40.00"),
            module.BASE["hr_processes"]: scalar("INTEGER: 10"),
            module.BASE["hr_memory"]: scalar("INTEGER: 1000"),
            module.BASE["mem_total_real"]: scalar("INTEGER: 1000 KB"),
            module.BASE["mem_avail_real"]: scalar("INTEGER: 100 KB"),
            module.BASE["mem_shared"]: scalar("INTEGER: 20 KB"),
            module.BASE["mem_buffer"]: scalar("INTEGER: 30 KB"),
            module.BASE["mem_cached"]: scalar("INTEGER: 200 KB"),
            module.BASE["mem_total_swap"]: scalar("INTEGER: 500 KB"),
            module.BASE["mem_avail_swap"]: scalar("INTEGER: 100 KB"),
            module.BASE["load_1"]: scalar("STRING: 0.10"),
            module.BASE["load_5"]: scalar("STRING: 0.20"),
            module.BASE["load_15"]: scalar("STRING: 0.30"),
            module.BASE["hr_processor_load"]: [".1 = INTEGER: 10"],
            module.TABLES["storage_type"]: [
                ".1.1 = OID: .1.3.6.1.2.1.25.2.1.4",
                ".1.2 = OID: .1.3.6.1.2.1.25.2.1.2",
                ".1.3 = OID: .1.3.6.1.2.1.25.2.1.4",
                ".1.4 = OID: .1.3.6.1.2.1.25.2.1.4",
            ],
            module.TABLES["storage_unit"]: [
                ".1.1 = INTEGER: 1024",
                ".1.2 = INTEGER: 1024",
                ".1.3 = INTEGER: 1024",
                ".1.4 = INTEGER: 1024",
            ],
            module.TABLES["storage_size"]: [
                ".1.1 = INTEGER: 1000",
                ".1.2 = INTEGER: 2048",
                ".1.3 = INTEGER: 200",
                ".1.4 = INTEGER: 100",
            ],
            module.TABLES["storage_used"]: [
                ".1.1 = INTEGER: 500",
                ".1.2 = INTEGER: 1024",
                ".1.3 = INTEGER: 190",
                ".1.4 = INTEGER: 20",
            ],
            module.TABLES["storage_name"]: [
                '.1.1 = STRING: "/"',
                '.1.2 = STRING: "Physical memory"',
                '.1.3 = STRING: "/boot"',
                '.1.4 = STRING: "/boot/efi/"',
            ],
        },
    )
    monkeypatch.setenv("EASYOPS_COLLECTOR_ip", "127.0.0.1")
    monkeypatch.setenv("EASYOPS_COLLECTOR_fsExcludePaths", "/boot/,/boot/efi/")

    assert module.main() == 0
    records = json.loads(capsys.readouterr().out)
    base = records[0]
    assert base["vals"]["os_mem_used"] == 650
    assert base["vals"]["os_mem_pused"] == 65
    partitions = [row["dims"]["resourceName"] for row in records[1:]]
    assert partitions == ["/"]


def test_windows_drive_names_and_memory_fallback(monkeypatch, capsys):
    module = mock_snmp(
        monkeypatch,
        lambda module: {
            module.BASE["sys_descr"]: scalar("STRING: Windows Server"),
            module.BASE["hr_system_uptime"]: scalar("Timeticks: (100) 0:01:40.00"),
            module.BASE["hr_processor_load"]: [".1 = INTEGER: 10"],
            module.TABLES["storage_type"]: [
                ".1.1 = OID: .1.3.6.1.2.1.25.2.1.4",
                ".1.2 = OID: .1.3.6.1.2.1.25.2.1.4",
                ".1.3 = OID: .1.3.6.1.2.1.25.2.1.2",
            ],
            module.TABLES["storage_unit"]: [
                ".1.1 = INTEGER: 4096",
                ".1.2 = INTEGER: 4096",
                ".1.3 = INTEGER: 1024",
            ],
            module.TABLES["storage_size"]: [
                ".1.1 = INTEGER: 1000",
                ".1.2 = INTEGER: 2000",
                ".1.3 = INTEGER: 1048576",
            ],
            module.TABLES["storage_used"]: [
                ".1.1 = INTEGER: 300",
                ".1.2 = INTEGER: 1600",
                ".1.3 = INTEGER: 838860",
            ],
            module.TABLES["storage_name"]: [
                '.1.1 = STRING: "C:\\\\ label: System"',
                '.1.2 = STRING: "D:\\\\ label: Data"',
                '.1.3 = STRING: "Physical memory"',
            ],
        },
    )
    monkeypatch.setenv("EASYOPS_COLLECTOR_ip", "127.0.0.1")

    assert module.main() == 0
    records = json.loads(capsys.readouterr().out)
    partitions = [(row["dims"]["resourceName"], row["vals"]["os_fs_pused"]) for row in records[1:]]
    assert partitions == [("C:\\", 30), ("D:\\", 80)]
    base = records[0]
    assert base["vals"]["os_mem_total_real"] == 1048576
    assert base["vals"]["os_mem_used"] == 838860
    assert base["vals"]["os_mem_pused"] == pytest.approx(80)
