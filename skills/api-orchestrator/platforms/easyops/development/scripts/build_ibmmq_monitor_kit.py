#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 IBM MQ 监控套件定义、告警模板和可导入 ZIP 包。"""
import argparse
import json
import shutil
import stat
import zipfile
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "monitor-kits/ibmmq-monitoring"
HUB = ROOT.parent / "hub/monitor-kits"
NAME = "IBM MQ监控"
VERSION = "0.3.0"
SUPPORTED_PLATFORMS = ("Linux", "Windows")
OBJECT_ID = "IBMMQ@ONEMODEL"
XLSX_NAME = "IBM_MQ监控_告警规则模板_0.3.0.xlsx"
ZIP_NAME = "监控套件_IBM_MQ监控_0.3.0.zip"
BASE_DIMS = ("ibmmqInstanceId", "qmgrName", "hostIp", "installPath")
QUEUE_DIMS = BASE_DIMS + ("queueName",)
CHANNEL_DIMS = BASE_DIMS + ("channelName", "channelType")
LISTENER_DIMS = BASE_DIMS + ("listenerName", "port")
PROCESS_DIMS = BASE_DIMS + ("cmdline",)
INSTANCE_DIMS = ("ibmmqInstanceId",)

METRICS = (
    ("ibmmq_collect_success", "采集成功；1成功，0失败", "", "采集状态", BASE_DIMS),
    ("ibmmq_discovery_success", "dspmq队列管理器发现成功；1成功，0失败", "", "采集状态", BASE_DIMS),
    ("ibmmq_qmgr_count", "当前实例匹配到的队列管理器数量", "个", "队列管理器", INSTANCE_DIMS),
    ("ibmmq_qmgr_status", "队列管理器状态；1 Running，其余0", "", "队列管理器", BASE_DIMS),
    ("ibmmq_sc_command_success", "runmqsc整体执行成功；1成功，0失败", "", "采集状态", BASE_DIMS),
    ("ibmmq_queue_total", "纳入监控的本地队列数量", "个", "队列", BASE_DIMS),
    ("ibmmq_queue_depth_total", "纳入监控队列当前深度合计", "条", "队列", BASE_DIMS),
    ("ibmmq_queue_max_depth", "纳入监控队列最大配置深度", "条", "队列", BASE_DIMS),
    ("ibmmq_queue_max_usage_percent", "队列深度占用率最大值", "%", "队列", BASE_DIMS),
    ("ibmmq_queue_current_depth", "队列当前消息深度", "条", "队列明细", QUEUE_DIMS),
    ("ibmmq_queue_max_depth_config", "队列配置最大深度", "条", "队列明细", QUEUE_DIMS),
    ("ibmmq_queue_usage_percent", "队列当前深度占最大深度比例", "%", "队列明细", QUEUE_DIMS),
    ("ibmmq_queue_oldest_message_age_seconds", "队列最老消息年龄", "s", "队列明细", QUEUE_DIMS),
    ("ibmmq_queue_input_handles", "队列输入句柄数", "个", "队列明细", QUEUE_DIMS),
    ("ibmmq_queue_output_handles", "队列输出句柄数", "个", "队列明细", QUEUE_DIMS),
    ("ibmmq_listener_total", "监听器数量", "个", "监听器", BASE_DIMS),
    ("ibmmq_listener_running_count", "Running状态监听器数量", "个", "监听器", BASE_DIMS),
    ("ibmmq_listener_status", "监听器状态；1 Running，0.5 Starting，0.25 Standby，0异常", "", "监听器明细", LISTENER_DIMS),
    ("ibmmq_channel_total", "通道状态记录数量", "个", "通道", BASE_DIMS),
    ("ibmmq_channel_running_count", "Running状态通道数量", "个", "通道", BASE_DIMS),
    ("ibmmq_channel_retrying_count", "Retrying状态通道数量", "个", "通道", BASE_DIMS),
    ("ibmmq_channel_status", "通道状态；1 Running，0.5 Starting，0.25 Paused，0异常", "", "通道明细", CHANNEL_DIMS),
    ("ibmmq_channel_messages", "通道发送或接收消息计数", "条", "通道明细", CHANNEL_DIMS),
    ("ibmmq_channel_bytes", "通道发送或接收字节数", "B", "通道明细", CHANNEL_DIMS),
    ("ibmmq_process_alive", "匹配到的进程命令行是否存活；1存活", "", "进程资源", PROCESS_DIMS),
    ("ibmmq_process_count", "同命令行IBM MQ进程数量", "个", "进程资源", PROCESS_DIMS),
    ("ibmmq_process_cpu_percent", "进程CPU使用率", "%", "进程资源", PROCESS_DIMS),
    ("ibmmq_process_memory_bytes", "进程RSS内存", "B", "进程资源", PROCESS_DIMS),
    ("ibmmq_process_thread_count", "进程线程数", "个", "进程资源", PROCESS_DIMS),
    ("ibmmq_process_fd_count", "进程打开句柄数", "个", "进程资源", PROCESS_DIMS),
)
PARAMETERS = (
    ("instanceId", "string", "$.instanceId", "IBM MQ实例ID", "取IBMMQ.instanceId，用于实例维度", False, False),
    ("qmgrName", "string", "$.name", "队列管理器", "取IBMMQ实例名称；实例名应配置为队列管理器名", False, False),
    ("hostIp", "string", "$.ip", "部署主机IP", "取ARTIFACT_INST继承ip，用于维度与部署定位", False, False),
    ("installPath", "string", "$.installPath", "安装路径", "取ARTIFACT_INST继承installPath，用于定位bin目录", False, False),
    ("mqBinPath", "string", "", "IBM MQ bin目录", "手动填写或留空；Linux/Windows均按installPath和常见安装目录探测", True, True),
    ("queueFilter", "string", ".*", "队列过滤正则", "默认监控全部非SYSTEM.前缀队列", True, True),
    ("includeSystemQueues", "string", "false", "包含系统队列", "默认排除SYSTEM.前缀队列", True, True),
    ("processMonitor", "string", "true", "启用进程资源采集", "默认启用，按cmdline分组输出进程资源", True, True),
    ("sampleInterval", "float", "0.2", "CPU采样间隔(秒)", "Linux两次/proc CPU采样间隔；Windows读取CIM格式化计数，默认0.2，范围0.05-2", True, True),
    ("commandTimeout", "int", "10", "MQ命令超时(秒)", "dspmq/runmqsc超时时间，默认10，范围1-60", True, True),
)


def dim_rows(names):
    return [{"dimDisplayName": name, "dimName": name, "isArray": False, "originDimName": name} for name in names]


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_definitions():
    metric_sets = [{"name": name} for name in sorted({row[3] for row in METRICS})]
    origins = []
    aliases = []
    for key, description, unit, metric_set, dims in METRICS:
        origins.append({
            "agentType": "easyops", "dataType": "double", "instanceId": "", "key": key,
            "labels": list(dims), "metricType": "gauge",
            "tagDefine": [{"name": name, "readOnly": False} for name in dims],
        })
        aliases.append({
            "agentType": "easyops", "dataType": "double", "description": description,
            "dims": dim_rows(dims), "displayName": key, "expression": "",
            "metricSet": [metric_set], "name": key, "objectId": OBJECT_ID,
            "originalMetrics": [key], "type": "normal", "unit": unit,
        })
    write_json(KIT / "metric_set.json", metric_sets)
    write_json(KIT / "origin_metric.json", origins)
    write_json(KIT / "alias_metric.json", aliases)


def attr_define(attr_id, name, value_type, description, required=False, enum_values=None, default=None):
    value = {
        "type": value_type, "regex": enum_values if value_type == "enum" else None,
        "default_type": "value" if default is not None else "", "default": default,
        "struct_define": [], "mode": "default", "prefix": "", "start_value": 0,
        "series_number_length": 0,
    }
    return {
        "id": attr_id, "name": name, "protected": True, "custom": "false",
        "readonly": "false", "required": str(required).lower(), "unique": "false",
        "tag": ["基本信息" if attr_id == "qmgrName" else "IBM MQ配置"], "value": value,
        "wordIndexDenied": False, "description": description, "tips": "",
        "isInherit": False, "inheritObjectId": "", "notifyDenied": False,
    }


def write_resource_discovery():
    write_json(KIT / "resource_discovery_define.json", [{
        "objectId": OBJECT_ID, "category": "平台资源.消息队列", "type": "ARTIFACT_INST@ONEMODEL",
    }])

def validate_platform_support():
    source = (KIT / "src/ibmmq_monitor.py").read_text(encoding="utf-8")
    readme = (KIT / "readme").read_text(encoding="utf-8")
    required_source = (
        'def is_windows():',
        'def mq_command(',
        'def windows_process_sample(',
        'os.name == "nt"',
        'taskkill',
        'Get-CimInstance',
        'WMIC.exe',
    )
    missing_source = [item for item in required_source if item not in source]
    if missing_source:
        raise RuntimeError("[validate_platform_support] 采集脚本缺少Windows支持: %s" % ", ".join(missing_source))
    if (KIT / "src/ibmmq_monitor.py").read_bytes() != (KIT / "src/ibmmq_monitor.orig").read_bytes():
        raise RuntimeError("[validate_platform_support] .py与.orig必须保持一致")
    for platform in SUPPORTED_PLATFORMS:
        if platform not in readme:
            raise RuntimeError("[validate_platform_support] readme未声明支持平台: %s" % platform)


def plugin_yaml():
    lines = [
        "type: simple-script", "name: %s" % NAME, 'version: "%s"' % VERSION,
        "command:", "    collect:", "        interpreter: \"\"",
        "        scriptPath:", "            - src", "            - ibmmq_monitor.py",
        "        type: python", "        user: \"\"", "params:",
    ]
    lines.extend(["    - %s" % row[0] for row in PARAMETERS])
    lines.append("paramDefine:")
    for name, value_type, default, display_name, description, optional, display in PARAMETERS:
        rendered_default = str(default).lower() if value_type == "bool" else '"%s"' % default
        lines.append(
            "    - {name: %s, valueType: %s, defaultValue: %s, display: %s, displayName: \"%s\", "
            "description: \"%s\", use: collectParams, optional: %s, isFromSecret: false, "
            "isEncrypt: false, extraArgs: null}" % (
                name, value_type, rendered_default, str(display).lower(), display_name,
                description, str(optional).lower()
            )
        )
    lines.extend([
        "agentType: easyops", "category: 消息队列", "scriptType: python",
        "interpreter: \"\"", "samplerType: metric_sampler",
        "memo: \"同时支持Linux/Windows执行节点；按IBM MQ队列管理器实例调用dspmq/runmqsc，采集队列管理器、监听器、通道、队列深度和进程资源指标。\"",
        "icon: null", "relateObjectId: IBMMQ@ONEMODEL",
    ])
    return "\n".join(lines) + "\n"


def alert_conditions():
    rules = (
        ("ibmmq_collect_success", "equal", 0, 1, 1, 1, (("warning", 0), ("critical", 0))),
        ("ibmmq_discovery_success", "equal", 0, 1, 1, 1, (("warning", 0),)),
        ("ibmmq_qmgr_status", "equal", 0, 3, 1, 3, (("warning", 0), ("critical", 0))),
        ("ibmmq_sc_command_success", "equal", 0, 1, 1, 1, (("warning", 0),)),
        ("ibmmq_process_alive", "equal", 0, 3, 1, 3, (("critical", 0),)),
        ("ibmmq_listener_status", "equal", 0, 3, 1, 3, (("warning", 0), ("critical", 0))),
        ("ibmmq_channel_status", "equal", 0, 3, 1, 3, (("warning", 0),)),
        ("ibmmq_channel_retrying_count", "bigger_than", 0, 3, 1, 3, (("warning", 0),)),
        ("ibmmq_queue_current_depth", "bigger_than", 1000, 3, 1, 3, (("warning", 1000), ("critical", 5000))),
        ("ibmmq_queue_usage_percent", "bigger_than", 80, 3, 1, 3, (("warning", 80), ("critical", 90))),
        ("ibmmq_queue_oldest_message_age_seconds", "bigger_than", 300, 3, 1, 3, (("warning", 300), ("critical", 900))),
    )
    result = []
    for metric, condition_type, threshold, alert_count, recover_count, window, levels in rules:
        result.append({
            "metricName": metric, "mode": "static", "type": condition_type,
            "threshold": threshold, "alertCount": alert_count, "recoverCount": recover_count,
            "detectWindow": window,
            "comparators": [{
                "level": level, "threshold": value, "displayThreshold": value,
                "tolerance": 0, "type": condition_type,
            } for level, value in levels],
        })
    return result


def build_xlsx():
    source = ROOT / "monitor-kits/host-deploy-instance-monitoring/主机部署实例监控_告警规则模板.xlsx"
    workbook = load_workbook(source)
    sheet = workbook.active
    sheet["A3"] = "IBM_MQ监控默认告警模板"
    sheet["B3"] = OBJECT_ID
    sheet["C3"] = "{hostname} IBM MQ监控告警"
    sheet["E3"] = "{hostname} IBM MQ队列管理器告警"
    sheet["M3"] = "IBM MQ队列管理器实例默认告警；状态和采集类连续3点触发，队列阈值按占用率、深度和最老消息年龄分层。"
    sheet["R3"] = json.dumps(alert_conditions(), ensure_ascii=False, separators=(",", ":"))
    sheet["W3"] = "{hostname} IBM MQ监控目标"
    sheet["X3"] = "IBM MQ队列管理器实例目标，实例继承部署实例主机与安装路径信息。"
    sheet["AX3"] = "{objectName} IBM MQ通知策略"
    sheet["BD3"] = "IBM MQ队列管理器状态、监听器、通道、队列深度、积压时间和采集失败默认告警。"
    target = KIT / XLSX_NAME
    workbook.save(target)
    return target


def add_archive(archive, arcname, path):
    info = zipfile.ZipInfo(arcname, (1980, 1, 1, 0, 0, 0))
    info.flag_bits |= 0x800
    if arcname.endswith("/"):
        info.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(info, b"")
        return
    info.external_attr = (stat.S_IFREG | 0o664) << 16
    archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_STORED)


def build_zip():
    HUB.mkdir(parents=True, exist_ok=True)
    target = HUB / ZIP_NAME
    directories = [NAME + "/", NAME + "/src/"]
    files = [
        (KIT / "plugin.yaml", NAME + "/plugin.yaml"),
        (KIT / "package.conf.yaml", NAME + "/package.conf.yaml"),
        (KIT / "readme", NAME + "/readme"),
        (KIT / "resource_discovery_define.json", NAME + "/resource_discovery_define.json"),
        (KIT / "metric_set.json", NAME + "/metric_set.json"),
        (KIT / "origin_metric.json", NAME + "/origin_metric.json"),
        (KIT / "alias_metric.json", NAME + "/alias_metric.json"),
        (KIT / XLSX_NAME, NAME + "/" + XLSX_NAME),
        (KIT / "src/ibmmq_monitor.py", NAME + "/src/ibmmq_monitor.py"),
        (KIT / "src/ibmmq_monitor.orig", NAME + "/src/ibmmq_monitor.orig"),
    ]
    with zipfile.ZipFile(target, "w") as archive:
        for directory in directories:
            add_archive(archive, directory, None)
        for source, arcname in files:
            add_archive(archive, arcname, source)
    return target


def main():
    parser = argparse.ArgumentParser(description="生成IBM MQ监控套件离线产物")
    parser.add_argument("--skip-zip", action="store_true", help="只生成源目录定义，不生成Hub ZIP")
    args = parser.parse_args()
    validate_platform_support()
    write_resource_discovery()
    write_definitions()
    (KIT / "plugin.yaml").write_text(plugin_yaml(), encoding="utf-8")
    (KIT / "package.conf.yaml").write_text('name: %s\nversion: "%s"\n' % (NAME, VERSION), encoding="utf-8")
    xlsx = build_xlsx()
    if not args.skip_zip:
        HUB.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(xlsx, HUB / XLSX_NAME)
    package = None if args.skip_zip else build_zip()
    print("生成完成: platforms=%s, metrics=%d, xlsx=%s, zip=%s" % (",".join(SUPPORTED_PLATFORMS), len(METRICS), xlsx, package or "skipped"))


if __name__ == "__main__":
    main()
