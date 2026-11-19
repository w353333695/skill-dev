#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从单一指标 spec 表生成 origin_metric.json / alias_metric.json / metric_set.json，
保证三份文件引用闭合（校验器要求：alias.originalMetrics ⊆ origin.key、
alias.metricSet ⊆ metric_set.name、单原始指标别名维度=原始 labels）。"""
import json
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

VC_DIM = {"vc": "vCenter地址"}
CLUSTER_DIMS = {"datacenter": "数据中心", "cluster": "集群"}
DATASTORE_DIMS = {"datastore": "数据存储"}
HOST_DIMS = {"host": "宿主机"}
VM_DIMS = {"vm": "虚拟机"}

# (指标名, 指标集, 维度组合, unit, 中文别名, 中文描述)
D_VC = VC_DIM
D_CLUSTER = dict(VC_DIM, **CLUSTER_DIMS)
D_DS = dict(D_CLUSTER, **DATASTORE_DIMS)
D_HOST = dict(D_DS, **HOST_DIMS)
D_VM = dict(D_HOST, **VM_DIMS)

SPECS = [
    # ---- 平台状态 ----
    ("vcenter_available", "平台状态", D_VC, "", "vCenter-连接可用", "vCenter SDK 会话建立成功 1/0"),
    ("vcenter_collect_complete", "平台状态", D_VC, "", "vCenter-采集完整", "本轮无局部采集错误 1/0"),
    ("vcenter_error_count", "平台状态", D_VC, "", "vCenter-采集错误数", "本轮局部对象采集失败次数"),
    ("vcenter_duration_seconds", "平台状态", D_VC, "s", "vCenter-采集耗时", "本轮对象遍历与组装耗时"),
    # ---- 集群 ----
    ("vcenter_cluster_status", "集群", D_CLUSTER, "", "vCenter-集群状态", "0绿色/1黄色/2红色/3未知"),
    ("vcenter_cluster_host_total", "集群", D_CLUSTER, "", "vCenter-宿主机总数", "集群内宿主机数量"),
    ("vcenter_cluster_vm_total", "集群", D_CLUSTER, "", "vCenter-虚拟机总数", "集群内虚拟机数量（按运行时归属宿主机统计）"),
    ("vcenter_cluster_vm_powered_on", "集群", D_CLUSTER, "", "vCenter-运行虚拟机数", "电源状态 poweredOn 的虚拟机数量"),
    ("vcenter_cluster_vm_powered_off", "集群", D_CLUSTER, "", "vCenter-关闭虚拟机数", "电源状态 poweredOff 的虚拟机数量"),
    ("vcenter_cluster_vm_suspended", "集群", D_CLUSTER, "", "vCenter-挂起虚拟机数", "电源状态 suspended 的虚拟机数量"),
    ("vcenter_cluster_cpu_usage_pct", "集群", D_CLUSTER, "%", "vCenter-集群CPU使用率", "宿主机CPU使用量合计/集群有效CPU容量（缺失回退宿主机规格合计）"),
    ("vcenter_cluster_mem_usage_pct", "集群", D_CLUSTER, "%", "vCenter-集群内存使用率", "宿主机内存使用量合计/集群有效内存容量（缺失回退宿主机规格合计）"),
    # ---- 数据存储 ----
    ("vcenter_datastore_accessible", "数据存储", D_DS, "", "vCenter-存储可访问", "数据存储 accessible 状态 1/0"),
    ("vcenter_datastore_capacity_gb", "数据存储", D_DS, "GB", "vCenter-存储总容量", "数据存储总容量"),
    ("vcenter_datastore_free_gb", "数据存储", D_DS, "GB", "vCenter-存储可用空间", "数据存储剩余可用空间"),
    ("vcenter_datastore_usage_pct", "数据存储", D_DS, "%", "vCenter-存储使用率", "(容量-可用)/容量 百分比"),
    ("vcenter_datastore_read_latency_ms", "数据存储", D_DS, "ms", "vCenter-存储读延迟", "perf计数器 datastore.totalReadLatency 平均读延迟"),
    ("vcenter_datastore_write_latency_ms", "数据存储", D_DS, "ms", "vCenter-存储写延迟", "perf计数器 datastore.totalWriteLatency 平均写延迟"),
    # ---- 宿主机 ----
    ("vcenter_host_connection_state", "宿主机", D_HOST, "", "vCenter-宿主机连接状态", "0已连接/1已断开/2无响应/3未知"),
    ("vcenter_host_power_state", "宿主机", D_HOST, "", "vCenter-宿主机电源状态", "1运行/0关机/2待机/3未知"),
    ("vcenter_host_overall_status", "宿主机", D_HOST, "", "vCenter-宿主机总体状态", "vCenter overallStatus 0绿色/1黄色/2红色/3灰色未知"),
    ("vcenter_host_cpu_usage_pct", "宿主机", D_HOST, "%", "vCenter-宿主机CPU使用率", "overallCpuUsage/(核心数×核心频率)"),
    ("vcenter_host_mem_usage_pct", "宿主机", D_HOST, "%", "vCenter-宿主机内存使用率", "overallMemoryUsage/物理内存"),
    ("vcenter_host_mem_ballooned_pct", "宿主机", D_HOST, "%", "vCenter-宿主机气球内存占比", "balloonedMemory/物理内存，内存压力大时升高"),
    ("vcenter_host_net_in_kbps", "宿主机", D_HOST, "kbps", "vCenter-宿主机网络流入", "perf计数器 net.received"),
    ("vcenter_host_net_out_kbps", "宿主机", D_HOST, "kbps", "vCenter-宿主机网络流出", "perf计数器 net.transmitted"),
    ("vcenter_host_uptime_seconds", "宿主机", D_HOST, "s", "vCenter-宿主机运行时长", "最近一次开机以来的秒数"),
    ("vcenter_host_vm_count", "宿主机", D_HOST, "", "vCenter-宿主机虚拟机数", "该宿主机上虚拟机数量"),
    # ---- 虚拟机 ----
    ("vcenter_vm_power_state", "虚拟机", D_VM, "", "vCenter-虚拟机电源状态", "0关机/1运行/2挂起/3未知"),
    ("vcenter_vm_cpu_usage_pct", "虚拟机", D_VM, "%", "vCenter-虚拟机CPU使用率", "overallCpuUsage/maxCpuUsage"),
    ("vcenter_vm_mem_usage_pct", "虚拟机", D_VM, "%", "vCenter-虚拟机内存使用率", "guestMemoryUsage/maxMemoryUsage"),
    ("vcenter_vm_storage_committed_gb", "虚拟机", D_VM, "GB", "vCenter-虚拟机已提交存储", "summary.storage.committed"),
    ("vcenter_vm_storage_usage_pct", "虚拟机", D_VM, "%", "vCenter-虚拟机存储使用率", "committed/(committed+uncommitted)"),
    ("vcenter_vm_tools_status", "虚拟机", D_VM, "", "vCenter-虚拟机Tools状态", "0正常/1待升级/2未运行/3未安装/4未知"),
    ("vcenter_vm_uptime_seconds", "虚拟机", D_VM, "s", "vCenter-虚拟机运行时长", "运行中虚拟机自 bootTime 起的秒数"),
]


def origin_metric():
    rows = []
    for name, _set, dims, _unit, _display, _desc in SPECS:
        dim_names = list(dims.keys())
        rows.append({
            "agentType": "easyops",
            "dataType": "double",
            "instanceId": "",
            "key": name,
            "labels": dim_names,
            "metricType": "gauge",
            "tagDefine": [{"name": dim_name, "readOnly": False} for dim_name in dim_names],
        })
    return rows


def alias_metric():
    rows = []
    for name, _set, dims, unit, display, desc in SPECS:
        rows.append({
            "agentType": "easyops",
            "dataType": "double",
            "description": desc,
            "dims": [
                {"dimDisplayName": display_name, "dimName": dim_name,
                 "isArray": False, "originDimName": dim_name}
                for dim_name, display_name in dims.items()
            ],
            "displayName": display,
            "expression": "",
            "metricSet": [_set],
            "name": name,
            "objectId": "CLOUD_PROVIDER@ONEMODEL",
            "originalMetrics": [name],
            "type": "normal",
            "unit": unit,
        })
    return rows


def metric_set():
    seen = []
    for _name, set_name, _dims, _unit, _display, _desc in SPECS:
        if set_name not in seen:
            seen.append(set_name)
    return [{"name": set_name} for set_name in seen]


def main():
    for filename, rows in (
        ("origin_metric.json", origin_metric()),
        ("alias_metric.json", alias_metric()),
        ("metric_set.json", metric_set()),
    ):
        path = KIT / filename
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("write %s rows=%d" % (filename, len(rows)))


if __name__ == "__main__":
    main()
