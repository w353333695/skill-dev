#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
vCenter监控 采集脚本（simple-script / metric_sampler）

通过 vCenter SDK（pyVim/pyVmomi，agent py2 内置）动态枚举数据中心、集群、数据存储、
宿主机和虚拟机，输出关键状态与使用率指标。stdout 正常只输出纯 JSON 数组
[{dims, vals}]；顶层致命异常输出 COLLECT_ERROR: + 脱敏 traceback 并 exit 0；
DEBUG 诊断写缓存目录侧车文件（不进 stdout/stderr），不含密码。

参数经环境变量 EASYOPS_COLLECTOR_<name> 注入（平台按 paramDefine 注入）。
依赖：agent 内置 pyVim.connect.SmartConnect 与 pyVmomi.vim；Python 2.7/3 兼容。
"""
import json
import os
import socket
import sys
import time
import traceback

from pyVim import connect as pyvim_connect
from pyVmomi import vim, vmodl

PY2 = sys.version_info[0] == 2
if PY2:
    text_type = unicode  # noqa: F821
    NUM_TYPES = (int, float, long)  # noqa: F821
else:
    text_type = str
    NUM_TYPES = (int, float)

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
DEBUG_LOG_MAX_BYTES = 5 * 1024 * 1024

# 枚举映射：全部输出数值（metric_sampler vals 必须数值型）
CONNECTION_STATE_MAP = {"connected": 0, "disconnected": 1, "notResponding": 2}
HOST_POWER_MAP = {"poweredOn": 1, "poweredOff": 0, "standby": 2}
STATUS_MAP = {"green": 0, "yellow": 1, "red": 2}
VM_POWER_MAP = {"poweredOff": 0, "poweredOn": 1, "suspended": 2}
TOOLS_MAP = {"toolsOk": 0, "toolsOld": 1, "toolsNotRunning": 2, "toolsNotInstalled": 3}

# perf 计数器 (groupInfo, nameInfo) -> 槽位
PERF_DESIRED = {
    ("datastore", "totalReadLatency"): "read_latency",
    ("datastore", "totalWriteLatency"): "write_latency",
    ("net", "received"): "net_in",
    ("net", "transmitted"): "net_out",
}
GB = 1024.0 * 1024.0 * 1024.0
MB = 1024.0 * 1024.0


def safe_text(value):
    """文本归一：bytes 按 UTF-8 解码；unicode/str 原样保留（py2 不做 str() 隐式 ASCII 编码）。"""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "replace")
    return value


def ascii_line(text):
    """一行文本压成 ASCII 安全（py2 用 unicode_escape 兜底，避免本地编码破坏 JSON 日志）。"""
    text = safe_text(text)
    if PY2 and isinstance(text, text_type):
        try:
            text.encode("ascii")
            return text
        except UnicodeEncodeError:
            return text.encode("unicode_escape").decode("ascii", "replace")
    return text


def write_out(text):
    """stdout 写入：py2 写 UTF-8 字节串，py3 写 str；unicode 不按 ASCII 隐式编码。"""
    text = safe_text(text)
    if PY2:
        if isinstance(text, text_type):
            text = text.encode("utf-8")
        sys.stdout.write(text)
    else:
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        sys.stdout.write(text)


def get_param(name, default=""):
    """参数读取：缺键/None/空串都落默认值（平台公约 get(key) or default）。"""
    value = os.environ.get("EASYOPS_COLLECTOR_" + name)
    if value is None or value == "":
        value = default
    return value


def normalize_address(address):
    """归一化 vCenter 地址 -> (scheme, host, port)。
    支持 https://host/sdk、http://host:port/sdk、host、host:port；https 缺省 443，http 缺省 80。"""
    address = (safe_text(address) or "").strip()
    if not address:
        raise ValueError("address 未配置")
    scheme = "https"
    if "://" in address:
        scheme, _, rest = address.partition("://")
        scheme = scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError("address 仅支持 http/https: %s" % ascii_line(address))
    else:
        rest = address
    rest = rest.split("/", 1)[0].strip()
    if rest.endswith(":"):
        rest = rest[:-1]
    if ":" in rest:
        host, _, port_text = rest.rpartition(":")
        if not port_text.isdigit():
            raise ValueError("address 端口非法: %s" % ascii_line(address))
        port = int(port_text)
        if port < 1 or port > 65535:
            raise ValueError("address 端口越界: %s" % ascii_line(address))
    else:
        host = rest
        port = 443 if scheme == "https" else 80
    if not host:
        raise ValueError("address 缺少主机部分: %s" % ascii_line(address))
    return scheme, host, port


class DebugLog(object):
    """DEBUG 诊断侧车日志：只写文件，绝不写 stdout/stderr（前端 JSON 纪律，0.1.12 教训）。"""

    def __init__(self, level_name, path):
        self.level = LOG_LEVELS.get((level_name or "ERROR").upper(), 40)
        self.path = path
        self.enabled = self.level <= LOG_LEVELS["DEBUG"]

    def event(self, level, stage, **fields):
        if not self.enabled or LOG_LEVELS.get(level, 40) < self.level:
            return
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": level, "stage": stage}
        for key, value in fields.items():
            if isinstance(value, bytes):
                value = safe_text(value)
            entry[key] = value
        try:
            parent = os.path.dirname(self.path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) > DEBUG_LOG_MAX_BYTES:
                    os.rename(self.path, self.path + ".old")
            except Exception:
                pass
            with open(self.path, "a") as handle:
                handle.write(json.dumps(entry, default=ascii_line) + "\n")
        except Exception:
            pass  # 诊断日志失败不影响采集输出

    def traceback_event(self, level, stage, marker):
        """异常日志：函数标记 + format_exc()（日志纪律：只有 str(e) 无法定位行号）。"""
        detail = ascii_line(traceback.format_exc())
        self.event(level, stage, error=marker, traceback=detail)


def config():
    """读取并校验注入参数；必填缺失快速失败；密码不进任何日志。"""
    address = get_param("address")
    if not address or address.startswith("$."):
        raise ValueError("address 未配置或仍为 $. 动态路径占位（需在模型实例 url 或任务参数中提供真实地址）")
    scheme, host, port = normalize_address(address)
    username = get_param("username")
    password = get_param("password")
    if not username:
        raise ValueError("username 未配置")
    if not password:
        raise ValueError("password 未配置")
    timeout_text = get_param("timeout", "60")
    try:
        timeout = int(timeout_text)
    except (ValueError, TypeError):
        raise ValueError("timeout 必须是整数: %s" % ascii_line(timeout_text))
    if timeout < 10 or timeout > 300:
        raise ValueError("timeout 范围 10-300: %s" % timeout)
    log_level = (get_param("logLevel", "ERROR") or "ERROR").upper()
    if log_level not in LOG_LEVELS:
        raise ValueError("logLevel 仅支持 DEBUG/INFO/WARN/ERROR: %s" % ascii_line(log_level))
    cache_dir = get_param("cacheDir") or "/tmp/easyops/vcenter-monitor"
    debug_log_path = os.path.join(cache_dir, "vcenter-%s.debug.log" % ascii_line(host))
    return {
        "scheme": scheme, "host": host, "port": port,
        "username": username, "password": password,
        "timeout": timeout, "logLevel": log_level,
        "cacheDir": cache_dir, "debugLogPath": debug_log_path,
        "vcDim": "%s:%s" % (ascii_line(host), port),
    }


def connect_vcenter(cfg, log):
    """连接 + 预检复用同一次 SmartConnect（认证成功才算预检通过，失败即跳过本轮采集）。
    https 自签证书默认不校验；旧版 pyVim 不支持 disableSslCertValidation 参数时降级直连
    （旧版 pyVim 默认即不校验证书）。套接字超时统一走 socket.setdefaulttimeout。"""
    socket.setdefaulttimeout(cfg["timeout"])
    kwargs = {"host": cfg["host"], "port": cfg["port"],
              "user": cfg["username"], "pwd": cfg["password"]}
    if cfg["scheme"] == "https":
        try:
            service_instance = pyvim_connect.SmartConnect(disableSslCertValidation=True, **kwargs)
        except TypeError:
            log.event("WARN", "connect.no_validation_kwarg", note="pyVim 旧版不支持 disableSslCertValidation，按默认行为直连")
            service_instance = pyvim_connect.SmartConnect(**kwargs)
    else:
        kwargs["protocol"] = "http"
        service_instance = pyvim_connect.SmartConnect(**kwargs)
    content = service_instance.RetrieveServiceContent()
    if content is None or getattr(content, "about", None) is None:
        raise ValueError("vCenter 服务内容获取失败")
    log.event("DEBUG", "connect.ok", api=getattr(content.about, "apiType", ""),
              version=getattr(content.about, "version", ""))
    return service_instance


def disconnect(service_instance, log):
    try:
        pyvim_connect.Disconnect(service_instance)
    except Exception:
        log.traceback_event("WARN", "disconnect", "[disconnect]")


def _folder_recursion_specs():
    """Datacenter -> hostFolder(ComputeResource->HostSystem->VirtualMachine)
    与 -> datastoreFolder(Datastore) 的遍历链；嵌套 Folder 由 visitFolders 递归覆盖。
    PropertySpec type=ComputeResource 会同时命中 ClusterComputeResource（子类型）。"""
    selection = vmodl.query.PropertyCollector.SelectionSpec
    traversal = vmodl.query.PropertyCollector.TraversalSpec
    visit_folders = traversal(
        name="visitFolders", type="Folder", path="childEntity", skip=False,
        selectSet=[selection(name="visitFolders"), selection(name="crToH"), selection(name="hToVm")])
    cr_to_h = traversal(
        name="crToH", type="ComputeResource", path="host", skip=False,
        selectSet=[selection(name="hToVm")])
    h_to_vm = traversal(name="hToVm", type="HostSystem", path="vm", skip=False, selectSet=[])
    dc_to_hf = traversal(
        name="dcToHF", type="Datacenter", path="hostFolder", skip=False,
        selectSet=[selection(name="visitFolders"), selection(name="crToH")])
    dc_to_dsf = traversal(
        name="dcToDSF", type="Datacenter", path="datastoreFolder", skip=False,
        selectSet=[selection(name="visitFolders")])
    return [dc_to_hf, dc_to_dsf, visit_folders, cr_to_h, h_to_vm]


def _prop_spec(obj_type, props):
    return vmodl.query.PropertyCollector.PropertySpec(type=obj_type, all=False, pathSet=props)


def retrieve_rows(property_collector, from_obj, select_set, prop_specs):
    """RetrievePropertiesEx（含 token 续拉）-> [{obj, props}]。"""
    obj_spec = vmodl.query.PropertyCollector.ObjectSpec(obj=from_obj, skip=True, selectSet=select_set)
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.propSet = prop_specs
    filter_spec.objectSet = [obj_spec]
    options = vmodl.query.PropertyCollector.RetrieveOptions()
    result = property_collector.RetrievePropertiesEx(specSet=[filter_spec], options=options)
    rows = []
    while result is not None:
        for item in result.objects:
            props = {}
            for prop in (item.propSet or []):
                props[prop.name] = prop.val
            rows.append({"obj": item.obj, "props": props})
        if not result.token:
            break
        result = property_collector.ContinueRetrievePropertiesEx(result.token)
    return rows


def collect_datacenter_names(content):
    """rootFolder 直接子层枚举 Datacenter。"""
    selection = vmodl.query.PropertyCollector.SelectionSpec
    traversal = vmodl.query.PropertyCollector.TraversalSpec
    obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
        obj=content.rootFolder, skip=True,
        selectSet=[traversal(name="rootToDC", type="Folder", path="childEntity",
                             skip=False, selectSet=[selection(name="rootToDC")])])
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.propSet = [_prop_spec("Datacenter", ["name"])]
    filter_spec.objectSet = [obj_spec]
    rows = retrieve_rows_simple(content.propertyCollector, filter_spec)
    datacenters = []
    for row in rows:
        datacenters.append({"obj": row["obj"], "name": safe_text(row["props"].get("name") or "")})
    return datacenters


def retrieve_rows_simple(property_collector, filter_spec):
    """给定 FilterSpec 直查（Datacenter 枚举用）。"""
    options = vmodl.query.PropertyCollector.RetrieveOptions()
    result = property_collector.RetrievePropertiesEx(specSet=[filter_spec], options=options)
    rows = []
    while result is not None:
        for item in result.objects:
            props = {}
            for prop in (item.propSet or []):
                props[prop.name] = prop.val
            rows.append({"obj": item.obj, "props": props})
        if not result.token:
            break
        result = property_collector.ContinueRetrievePropertiesEx(result.token)
    return rows


def query_perf(content, entity_slots, log, deadline):
    """批量 QueryPerf。entity_slots: {moref: [slot,...]} -> {moref: {slot: value}}。
    计数器缺失/查询失败按实体跳过（WARN），不伪造值。"""
    if not entity_slots:
        return {}
    perf_manager = content.perfManager
    if perf_manager is None:
        log.event("WARN", "perf.no_manager")
        return {}
    counter_slot_by_key = {}
    slot_counter_id = {}
    for counter in perf_manager.perfCounter:
        pair = (getattr(counter.groupInfo, "key", ""), getattr(counter.nameInfo, "key", ""))
        counter_slot_by_key[counter.key] = pair
        slot = PERF_DESIRED.get(pair)
        if slot and str(counter.rollupType) == "average" and slot not in slot_counter_id:
            slot_counter_id[slot] = counter.key
    missing = [slot for slot in ("read_latency", "write_latency", "net_in", "net_out")
               if slot not in slot_counter_id]
    if missing:
        log.event("WARN", "perf.counters_missing", slots=missing)
    specs = []
    for entity, slots in entity_slots.items():
        metric_ids = [vim.PerfMetricId(counterId=slot_counter_id[slot], instance="")
                      for slot in slots if slot in slot_counter_id]
        if metric_ids:
            specs.append(vim.PerfQuerySpec(entity=entity, metricId=metric_ids,
                                           maxSample=1, intervalId=20))
    values = {}
    chunk = 50
    for start in range(0, len(specs), chunk):
        if time.time() > deadline:
            log.event("WARN", "perf.deadline_exceeded", resolved=len(values))
            break
        batch = specs[start:start + chunk]
        try:
            outputs = perf_manager.QueryPerf(querySpec=batch)
        except Exception:
            log.traceback_event("WARN", "perf.query_failed", "[query_perf]")
            continue
        for output in outputs:
            slot_values = {}
            for series in (output.value or []):
                pair = counter_slot_by_key.get(series.id.counterId)
                slot = PERF_DESIRED.get(pair) if pair else None
                samples = series.value or []
                if slot and samples:
                    try:
                        slot_values[slot] = float(samples[-1])
                    except (TypeError, ValueError):
                        pass
            if slot_values:
                values[output.entity] = slot_values
    return values


def enum_value(mapping, raw, fallback):
    if raw is None:
        return fallback
    return mapping.get(str(raw), fallback)


def attr_chain(root, *names):
    """逐层 getattr 取托管对象属性，任一缺失返回 None（属性缺失是常态，不算采集错误）。"""
    current = root
    for name in names:
        if current is None:
            return None
        try:
            current = getattr(current, name)
        except Exception:
            return None
    return current


def number_or_none(value):
    if value is None or isinstance(value, bool):
        return 1.0 if value is True else (0.0 if value is False else None)
    if isinstance(value, NUM_TYPES):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MetricBuilder(object):
    """记录组装 + 缺失指标统计（缺失清单进 DEBUG，stdout 只出有值指标）。"""

    def __init__(self):
        self.records = []
        self.missing = {}

    def add(self, dims, vals):
        record_dims = dict((key, safe_text(value)) for key, value in dims.items())
        record_vals = {}
        for key in sorted(vals.keys()):
            number = number_or_none(vals[key])
            if number is None:
                self.missing[key] = self.missing.get(key, 0) + 1
            else:
                record_vals[key] = number
        if record_vals:
            self.records.append({"dims": record_dims, "vals": record_vals})


def assemble_rows(rows, log):
    """属性批次按 MoRef 类型拆视图：cr/host 表 + vm/datastore 列表（保留 MoRef 供 perf）。"""
    view = {"cr": {}, "host": {}, "vm": [], "datastore": []}
    for row in rows:
        obj = row["obj"]
        kind = getattr(obj, "_type", "")
        props = row["props"]
        if kind in ("ComputeResource", "ClusterComputeResource"):
            view["cr"][obj] = props
        elif kind == "HostSystem":
            view["host"][obj] = props
        elif kind == "VirtualMachine":
            view["vm"].append((obj, props))
        elif kind == "Datastore":
            view["datastore"].append((obj, props))
        else:
            log.event("DEBUG", "rows.unknown_type", type=str(kind))
    return view


def cluster_of_host(view, host_ref):
    """host.parent -> CR -> 名称。"""
    host_props = view["host"].get(host_ref)
    if not host_props:
        return ""
    cr_props = view["cr"].get(host_props.get("parent"))
    if not cr_props:
        return ""
    return safe_text(cr_props.get("name") or "")


def collect_vcenter(service_instance, cfg, log, deadline):
    """主采集：按数据中心分批拉对象树 + perf 批查，组装平台/集群/存储/宿主机/虚拟机记录。"""
    content = service_instance.content
    builder = MetricBuilder()
    error_count = [0]

    def warn(stage, **fields):
        error_count[0] += 1
        log.event("WARN", stage, **fields)

    datacenters = collect_datacenter_names(content)
    log.event("DEBUG", "inventory.datacenters", count=len(datacenters),
              names=[dc["name"] for dc in datacenters])

    started = time.time()
    for dc in datacenters:
        if time.time() > deadline:
            warn("inventory.deadline_exceeded", stage="dc_loop")
            break
        prop_specs = [
            _prop_spec("ComputeResource", ["name"]),
            _prop_spec("HostSystem", ["name", "parent", "summary"]),
            _prop_spec("VirtualMachine", ["name", "runtime", "summary"]),
            _prop_spec("Datastore", ["name", "summary"]),
        ]
        try:
            rows = retrieve_rows(content.propertyCollector, dc["obj"],
                                 _folder_recursion_specs(), prop_specs)
        except Exception:
            error_count[0] += 1
            log.traceback_event("WARN", "inventory.dc_failed", "[retrieve_rows]")
            continue
        view = assemble_rows(rows, log)
        log.event("DEBUG", "inventory.dc_batch", datacenter=dc["name"],
                  clusters=len(view["cr"]), hosts=len(view["host"]),
                  vms=len(view["vm"]), datastores=len(view["datastore"]))
        dc_dims = {"vc": cfg["vcDim"], "datacenter": dc["name"]}

        # ---- perf 批查（数据存储延迟 + 宿主机网络）----
        entity_slots = {}
        for ds_ref, _ in view["datastore"]:
            entity_slots[ds_ref] = ["read_latency", "write_latency"]
        for host_ref in view["host"]:
            entity_slots[host_ref] = ["net_in", "net_out"]
        perf = query_perf(content, entity_slots, log, deadline)

        # ---- 集群（usage 汇总自宿主机；capacity 优先集群 effective，缺失回退宿主机规格）----
        hosts_by_cr = {}
        for host_ref, host_props in view["host"].items():
            hosts_by_cr.setdefault(host_props.get("parent"), []).append(host_ref)
        for cr_ref, cr_props in view["cr"].items():
            members = hosts_by_cr.get(cr_ref, [])
            cluster_dims = dict(dc_dims, cluster=safe_text(cr_props.get("name") or ""))
            cr_summary = cr_props.get("summary")
            cpu_usage_sum = 0.0
            mem_usage_sum = 0.0
            cpu_capacity_fallback = 0.0
            mem_capacity_fallback = 0.0
            cpu_capacity = number_or_none(attr_chain(cr_summary, "effectiveCpu"))
            mem_capacity = number_or_none(attr_chain(cr_summary, "effectiveMemory"))
            for host_ref in members:
                summary = view["host"][host_ref].get("summary")
                quick = attr_chain(summary, "quickStats")
                hardware = attr_chain(summary, "hardware")
                cpu_usage = number_or_none(attr_chain(quick, "overallCpuUsage"))
                mem_usage = number_or_none(attr_chain(quick, "overallMemoryUsage"))
                if cpu_usage is not None:
                    cpu_usage_sum += cpu_usage
                    if cpu_capacity is None:
                        cores = number_or_none(attr_chain(hardware, "numCpuCores"))
                        cpu_mhz = number_or_none(attr_chain(hardware, "cpuMhz"))
                        if cores and cpu_mhz:
                            cpu_capacity_fallback += cores * cpu_mhz
                if mem_usage is not None:
                    mem_usage_sum += mem_usage
                    if mem_capacity is None:
                        memory_size = number_or_none(attr_chain(hardware, "memorySize"))
                        if memory_size:
                            mem_capacity_fallback += memory_size / MB
            if cpu_capacity is None and cpu_capacity_fallback > 0:
                cpu_capacity = cpu_capacity_fallback
            if mem_capacity is None and mem_capacity_fallback > 0:
                mem_capacity = mem_capacity_fallback
            vm_total = vm_on = vm_off = vm_suspended = 0
            for _, vm_props in view["vm"]:
                host_ref = attr_chain(vm_props.get("runtime"), "host")
                if host_ref is None:
                    continue
                host_props = view["host"].get(host_ref)
                if not host_props or host_props.get("parent") != cr_ref:
                    continue
                power = enum_value(VM_POWER_MAP, attr_chain(vm_props.get("runtime"), "powerState"), 3)
                vm_total += 1
                if power == 1:
                    vm_on += 1
                elif power == 0:
                    vm_off += 1
                elif power == 2:
                    vm_suspended += 1
            cluster_vals = {
                "vcenter_cluster_status": enum_value(STATUS_MAP, attr_chain(cr_summary, "generalStatus"), 3),
                "vcenter_cluster_host_total": float(len(members)),
                "vcenter_cluster_vm_total": float(vm_total),
                "vcenter_cluster_vm_powered_on": float(vm_on),
                "vcenter_cluster_vm_powered_off": float(vm_off),
                "vcenter_cluster_vm_suspended": float(vm_suspended),
            }
            if cpu_capacity:
                cluster_vals["vcenter_cluster_cpu_usage_pct"] = cpu_usage_sum / cpu_capacity * 100.0
            if mem_capacity:
                cluster_vals["vcenter_cluster_mem_usage_pct"] = mem_usage_sum / mem_capacity * 100.0
            builder.add(cluster_dims, cluster_vals)

        # ---- 数据存储 ----
        for ds_ref, ds_props in view["datastore"]:
            summary = ds_props.get("summary")
            capacity = number_or_none(attr_chain(summary, "capacity"))
            free_space = number_or_none(attr_chain(summary, "freeSpace"))
            accessible = attr_chain(summary, "accessible")
            vals = {"vcenter_datastore_accessible": 1.0 if accessible else 0.0}
            if capacity:
                vals["vcenter_datastore_capacity_gb"] = capacity / GB
            if free_space is not None:
                vals["vcenter_datastore_free_gb"] = free_space / GB
                if capacity:
                    vals["vcenter_datastore_usage_pct"] = (capacity - free_space) / capacity * 100.0
            ds_perf = perf.get(ds_ref) or {}
            if "read_latency" in ds_perf:
                vals["vcenter_datastore_read_latency_ms"] = ds_perf["read_latency"]
            if "write_latency" in ds_perf:
                vals["vcenter_datastore_write_latency_ms"] = ds_perf["write_latency"]
            builder.add(dict(dc_dims, datastore=safe_text(ds_props.get("name") or "")), vals)

        # ---- 宿主机 ----
        vm_count_by_host = {}
        for _, vm_props in view["vm"]:
            host_ref = attr_chain(vm_props.get("runtime"), "host")
            if host_ref is not None and host_ref in view["host"]:
                vm_count_by_host[host_ref] = vm_count_by_host.get(host_ref, 0) + 1
        for host_ref, host_props in view["host"].items():
            summary = host_props.get("summary")
            quick = attr_chain(summary, "quickStats")
            runtime = attr_chain(summary, "runtime")
            hardware = attr_chain(summary, "hardware")
            vals = {
                "vcenter_host_connection_state": enum_value(CONNECTION_STATE_MAP, attr_chain(runtime, "connectionState"), 3),
                "vcenter_host_power_state": enum_value(HOST_POWER_MAP, attr_chain(runtime, "powerState"), 3),
                "vcenter_host_overall_status": enum_value(STATUS_MAP, attr_chain(summary, "overallStatus"), 3),
            }
            total_mem_mb = None
            memory_size = number_or_none(attr_chain(hardware, "memorySize"))
            if memory_size:
                total_mem_mb = memory_size / MB
            cpu_usage = number_or_none(attr_chain(quick, "overallCpuUsage"))
            mem_usage = number_or_none(attr_chain(quick, "overallMemoryUsage"))
            ballooned = number_or_none(attr_chain(quick, "balloonedMemory"))
            if cpu_usage is not None:
                cores = number_or_none(attr_chain(hardware, "numCpuCores"))
                cpu_mhz = number_or_none(attr_chain(hardware, "cpuMhz"))
                if cores and cpu_mhz:
                    vals["vcenter_host_cpu_usage_pct"] = cpu_usage / (cores * cpu_mhz) * 100.0
            if mem_usage is not None and total_mem_mb:
                vals["vcenter_host_mem_usage_pct"] = mem_usage / total_mem_mb * 100.0
            if ballooned is not None and total_mem_mb:
                vals["vcenter_host_mem_ballooned_pct"] = ballooned / total_mem_mb * 100.0
            uptime = number_or_none(attr_chain(quick, "uptime"))
            if uptime is not None:
                vals["vcenter_host_uptime_seconds"] = uptime
            vals["vcenter_host_vm_count"] = float(vm_count_by_host.get(host_ref, 0))
            host_perf = perf.get(host_ref) or {}
            if "net_in" in host_perf:
                vals["vcenter_host_net_in_kbps"] = host_perf["net_in"]
            if "net_out" in host_perf:
                vals["vcenter_host_net_out_kbps"] = host_perf["net_out"]
            builder.add(dict(dc_dims, cluster=cluster_of_host(view, host_ref),
                             host=safe_text(host_props.get("name") or "")), vals)

        # ---- 虚拟机 ----
        now = time.time()
        for _, vm_props in view["vm"]:
            vm_name = safe_text(vm_props.get("name") or "")
            runtime = vm_props.get("runtime")
            host_ref = attr_chain(runtime, "host")
            if host_ref is None:
                warn("vm.orphaned", vm=ascii_line(vm_name))
                continue
            power = enum_value(VM_POWER_MAP, attr_chain(runtime, "powerState"), 3)
            summary = vm_props.get("summary")
            quick = attr_chain(summary, "quickStats")
            vals = {"vcenter_vm_power_state": power}
            cpu_usage = number_or_none(attr_chain(quick, "overallCpuUsage"))
            cpu_max = number_or_none(attr_chain(runtime, "maxCpuUsage"))
            if cpu_usage is not None and cpu_max:
                vals["vcenter_vm_cpu_usage_pct"] = cpu_usage / cpu_max * 100.0
            mem_guest = number_or_none(attr_chain(quick, "guestMemoryUsage"))
            mem_max = number_or_none(attr_chain(runtime, "maxMemoryUsage"))
            if mem_guest is not None and mem_max:
                vals["vcenter_vm_mem_usage_pct"] = mem_guest / mem_max * 100.0
            storage = attr_chain(summary, "storage")
            committed = number_or_none(attr_chain(storage, "committed"))
            uncommitted = number_or_none(attr_chain(storage, "uncommitted"))
            if committed is not None:
                vals["vcenter_vm_storage_committed_gb"] = committed / GB
                if uncommitted is not None and (committed + uncommitted) > 0:
                    vals["vcenter_vm_storage_usage_pct"] = committed / (committed + uncommitted) * 100.0
            vals["vcenter_vm_tools_status"] = enum_value(TOOLS_MAP, attr_chain(summary, "guest", "toolsStatus"), 4)
            boot_time = attr_chain(runtime, "bootTime")
            if boot_time is not None and power == 1:
                try:
                    uptime = now - time.mktime(boot_time.timetuple())
                    if uptime >= 0:
                        vals["vcenter_vm_uptime_seconds"] = uptime
                except Exception:
                    pass
            vm_dims = dict(dc_dims,
                           cluster=cluster_of_host(view, host_ref),
                           host=safe_text((view["host"].get(host_ref) or {}).get("name") or ""),
                           vm=vm_name)
            builder.add(vm_dims, vals)

    duration = time.time() - started
    platform_vals = {
        "vcenter_available": 1.0,
        "vcenter_collect_complete": 1.0 if error_count[0] == 0 else 0.0,
        "vcenter_error_count": float(error_count[0]),
        "vcenter_duration_seconds": duration,
    }
    builder.records.insert(0, {"dims": {"vc": cfg["vcDim"]}, "vals": platform_vals})
    if builder.missing:
        log.event("WARN", "metrics.missing",
                  counts=dict((key, value) for key, value in builder.missing.items()))
    log.event("DEBUG", "collect.summary", records=len(builder.records),
              missing=dict((key, value) for key, value in builder.missing.items()),
              duration=duration, errors=error_count[0])
    return builder.records


def main():
    cfg = config()
    log = DebugLog(cfg["logLevel"], cfg["debugLogPath"])
    log.event("DEBUG", "config.ready", scheme=cfg["scheme"], host=cfg["host"], port=cfg["port"],
              username=cfg["username"], timeout=cfg["timeout"], logLevel=cfg["logLevel"],
              cacheDir=cfg["cacheDir"])
    deadline = time.time() + cfg["timeout"]
    service_instance = connect_vcenter(cfg, log)
    try:
        records = collect_vcenter(service_instance, cfg, log, deadline)
    finally:
        disconnect(service_instance, log)
    if not records:
        raise ValueError("未产出任何指标记录（检查地址/账号权限及 vCenter 对象）")
    write_out(json.dumps(records))
    write_out("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            write_out("COLLECT_ERROR:\n")
            write_out(ascii_line(traceback.format_exc()) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(0)
