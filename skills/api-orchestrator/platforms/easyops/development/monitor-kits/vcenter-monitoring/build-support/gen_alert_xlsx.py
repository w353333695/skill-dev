#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 vCenter监控 告警规则模板 xlsx（Hub 统一三段式格式）。
底版：host-deploy-instance-monitoring 的告警规则模板 xlsx（当前环境已验证可导入的格式）。
阈值对齐现网 Zabbix（见 sources.md）：存储空间 85/95、读/写延迟 1000ms、宿主机重启 10 分钟、
集群红/黄、连接断开、电源状态 diff。级别仅 warning/critical（平台枚举）。"""
import json
from pathlib import Path

from openpyxl import load_workbook

BASE_DIR = Path(__file__).resolve().parents[2]
BASE_XLSX = BASE_DIR / "host-deploy-instance-monitoring/主机部署实例监控_告警规则模板.xlsx"
KIT = BASE_DIR / "vcenter-monitoring"
OBJECT_ID = "CLOUD_PROVIDER@ONEMODEL"
NAME = "vCenter监控"
# 版本随套件 package.conf.yaml，保证告警模板与套件同版本交付
VERSION = __import__("yaml").safe_load((KIT / "package.conf.yaml").read_text(encoding="utf-8"))["version"]
OUTPUT = KIT / ("vCenter监控_告警规则模板_%s.xlsx" % VERSION)


def threshold_rule(metric, condition_type, threshold, alert_count, recover_count, window, levels):
    comparators = [{
        "level": level, "threshold": value, "displayThreshold": value,
        "tolerance": 0, "type": condition_type,
    } for level, value in levels]
    return {
        "metricName": metric, "mode": "static", "type": condition_type,
        "threshold": threshold, "alertCount": alert_count,
        "recoverCount": recover_count, "detectWindow": window,
        "comparators": comparators,
    }


def diff_rule(metric):
    body = {
        "threshold": [None, None], "alertCount": 1, "recoverCount": 0, "detectWindow": 1,
        "params": [{"key": "offset", "value": 0}, {"key": "window", "value": 8}],
    }
    comparator = {
        "level": "warning", "threshold": [None, None], "displayThreshold": [None, None],
        "displayUnit": "", "params": [{"key": "offset", "value": 0},
                                      {"key": "window", "value": 8}], "tolerance": 0,
        "type": "diff",
    }
    body.update({"metricName": metric, "mode": "static", "type": "diff",
                 "comparators": [comparator]})
    return body


def alert_conditions():
    return [
        # 平台可用性
        threshold_rule("vcenter_available", "equal", 0, 1, 1, 1, (("critical", 0),)),
        threshold_rule("vcenter_collect_complete", "equal", 0, 1, 1, 1, (("warning", 0),)),
        # 集群：黄 Warning / 红 Critical（对齐现网 Average/High）
        threshold_rule("vcenter_cluster_status", "bigger_than", 0, 1, 1, 1,
                       (("warning", 0), ("critical", 1))),
        # 数据存储：空间两档（free<15%/5% 等价 usage>85%/95%，对齐现网宏 8~15/5）、
        # 读/写延迟 1000ms（现网宏）、不可访问单点 Critical
        threshold_rule("vcenter_datastore_usage_pct", "bigger_than", 85, 3, 1, 3,
                       (("warning", 85), ("critical", 95))),
        threshold_rule("vcenter_datastore_read_latency_ms", "bigger_than", 1000, 3, 1, 3,
                       (("warning", 1000),)),
        threshold_rule("vcenter_datastore_write_latency_ms", "bigger_than", 1000, 3, 1, 3,
                       (("warning", 1000),)),
        threshold_rule("vcenter_datastore_accessible", "equal", 0, 1, 1, 1, (("critical", 0),)),
        # 宿主机：连接断开（>=1 断开 Warning、>=2 无响应 Critical）、总体状态黄/红、
        # 重启 10 分钟内 Warning（对齐现网 uptime<10m）、资源两档、气球内存、关机
        threshold_rule("vcenter_host_connection_state", "bigger_than", 0, 1, 1, 1,
                       (("warning", 0), ("critical", 1))),
        threshold_rule("vcenter_host_overall_status", "bigger_than", 0, 1, 1, 1,
                       (("warning", 0), ("critical", 1))),
        threshold_rule("vcenter_host_uptime_seconds", "smaller_than", 600, 1, 1, 1,
                       (("warning", 600),)),
        threshold_rule("vcenter_host_cpu_usage_pct", "bigger_than", 90, 3, 1, 3,
                       (("warning", 90), ("critical", 95))),
        threshold_rule("vcenter_host_mem_usage_pct", "bigger_than", 90, 3, 1, 3,
                       (("warning", 90), ("critical", 95))),
        threshold_rule("vcenter_host_mem_ballooned_pct", "bigger_than", 10, 3, 1, 3,
                       (("warning", 10),)),
        threshold_rule("vcenter_host_power_state", "equal", 0, 1, 1, 1, (("warning", 0),)),
        # 虚拟机：电源状态变化 diff、Tools 异常
        diff_rule("vcenter_vm_power_state"),
        threshold_rule("vcenter_vm_tools_status", "bigger_than", 0, 3, 1, 3,
                       (("warning", 0),)),
    ]


def build():
    workbook = load_workbook(BASE_XLSX)
    sheet = workbook.active
    sheet["A3"] = "%s默认告警模板" % NAME
    sheet["B3"] = OBJECT_ID
    sheet["C3"] = "{name} %s告警" % NAME
    sheet["E3"] = "{name} vCenter关键指标告警"
    sheet["M3"] = ("vCenter关键指标默认告警；阈值对齐现网Zabbix：集群红/黄、数据存储空间85%/95%、"
                   "读写延迟1000ms、宿主机重启10分钟内、连接断开、总体状态黄/红、气球内存10%%；"
                   "虚拟机电源状态变化diff、Tools异常。级别仅warning/critical（平台枚举）。")
    sheet["R3"] = json.dumps(alert_conditions(), ensure_ascii=False, separators=(",", ":"))
    sheet["W3"] = "{name} vCenter监控目标"
    sheet["X3"] = "云平台实例目标，按数据中心/集群/数据存储/宿主机/虚拟机维度动态覆盖全部关联对象。"
    sheet["AX3"] = "{name} vCenter通知策略"
    sheet["BD3"] = "vCenter平台可用性、集群状态、数据存储空间与延迟、宿主机与虚拟机关键状态默认告警。"
    workbook.save(OUTPUT)
    print("written: %s" % OUTPUT)


if __name__ == "__main__":
    build()
