#!/usr/local/easyops/python/bin/python
# -*- coding:utf-8 -*-
import os
user = os.environ.get("EASYOPS_COLLECTOR_user")
password = os.environ.get("EASYOPS_COLLECTOR_password")
host = os.environ.get("EASYOPS_COLLECTOR_host")
port = os.environ.get("EASYOPS_COLLECTOR_port")
instanceId = os.environ.get("EASYOPS_COLLECTOR_instanceId")
noCollectVm = os.environ.get("EASYOPS_COLLECTOR_noCollectVm")
reportToOldModel = os.environ.get("EASYOPS_COLLECTOR_reportToOldModel")
import re
import ssl
import sys
import os as _os_for_logger_path
import logging as _builtin_logging
import json
import socket
import traceback
from pyVmomi import vim
from pyVim.connect import SmartConnect

ssl._create_default_https_context = ssl._create_unverified_context

if sys.version_info[0] == 2:
    reload(sys)
    sys.setdefaultencoding('utf8')

# 导入日志库
_current_dir = _os_for_logger_path.path.dirname(_os_for_logger_path.path.abspath(__file__))
_SAMPLER_SCRIPTS = _os_for_logger_path.path.normpath(_os_for_logger_path.path.join(_current_dir, '..', '..', '..', 'easy_process_sampler', 'scripts'))
if _SAMPLER_SCRIPTS not in sys.path:
    sys.path.insert(0, _SAMPLER_SCRIPTS)

try:
    from lib import task_logger
    logging = task_logger.get_logger()
except Exception:
    logging = _builtin_logging
    FORMAT = '[%(asctime)s (line:%(lineno)d) %(levelname)s] %(message)s'
    logging.basicConfig(level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S', format=FORMAT)
logger = logging
_debug_level = (os.environ.get('EASYOPS_COLLECTOR_logLevel') or os.environ.get('EASYOPS_LOG_LEVEL') or 'ERROR').upper()
logger.setLevel(getattr(_builtin_logging, _debug_level, _builtin_logging.ERROR))


def ip_debug(stage, data):
    """仅记录宿主网卡身份和IP，不记录凭证；独立stderr保证前端日志可见。"""
    if _debug_level == 'DEBUG':
        sys.stderr.write('[DEBUG][%s] %s\n' % (stage, json.dumps(data, ensure_ascii=True)))
        sys.stderr.flush()



CLOUD_VM_OBJECT_ID = "CLOUD_VM@ONEMODEL"
SERVER_OBJECT_ID = "PHYSICAL_SERVER@ONEMODEL"
SNAPSHOT_OBJECT_ID = "CLOUD_VM_SNAPSHOT@ONEMODEL"
RESOURCE_POOL_OBJECT_ID = "RESOURCE_POOL@ONEMODEL"
DISK_OBJECT_ID = "CLOUD_DISK@ONEMODEL"
STORAGE_OBJECT_ID = "CLOUD_STORAGE@ONEMODEL"
VPC_OBJECT_ID = "CLOUD_VPC@ONEMODEL"
CLOUD_PROVIDER_OBJECT_ID = "CLOUD_PROVIDER@ONEMODEL"
PROVIDER = "VMware vSphere"
VM_STATUS = {
    "poweredOn": "运行中",
    "poweredOff": "已停止",
    "suspended": "挂起"
}
VM_OBJECT_TYPE = {
    vim.Datacenter: "数据中心",
    vim.ClusterComputeResource: "集群",
    vim.ResourcePool: "资源池",
    vim.Folder: "文件夹",
    vim.vApp: "vApp",
}


def valid_host_ip(value):
    """只接受非回环、非未指定、非链路本地的宿主机单值 IP。"""
    value = (value or '').strip()
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            packed = socket.inet_pton(family, value)
            canonical = socket.inet_ntop(family, packed)
            if family == socket.AF_INET:
                first, second = [int(x) for x in canonical.split('.')[:2]]
                if first in (0, 127) or first >= 224 or (first == 169 and second == 254):
                    return ''
            elif canonical == '::' or canonical == '::1' or canonical.lower().startswith(('fe8', 'fe9', 'fea', 'feb', 'ff')):
                return ''
            return canonical
        except (ValueError, socket.error):
            continue
    return ''


def management_ip(host_obj):
    """优先使用 Management 已选网卡；无配置时仅允许单 IP 回退。"""
    config = getattr(host_obj, 'config', None)
    network = getattr(config, 'network', None)
    vnics = getattr(network, 'vnic', None) or []
    manager = getattr(config, 'virtualNicManagerInfo', None)
    net_configs = getattr(manager, 'netConfig', None) or []
    ip_debug('management_ip', {
        'host': getattr(host_obj, '_moId', ''),
        'vnics': [{'key': getattr(n, 'key', ''), 'device': getattr(n, 'device', ''),
                   'ip': getattr(getattr(getattr(n, 'spec', None), 'ip', None), 'ipAddress', '')} for n in vnics],
        'netConfig': [{'nicType': getattr(n, 'nicType', ''),
                       'selectedVnic': list(getattr(n, 'selectedVnic', None) or []),
                       'candidateVnic': [{'key': getattr(v, 'key', ''), 'device': getattr(v, 'device', ''),
                           'ip': getattr(getattr(getattr(v, 'spec', None), 'ip', None), 'ipAddress', '')}
                           for v in (getattr(n, 'candidateVnic', None) or [])]} for n in net_configs]})
    selected = set()
    has_management_config = False
    for item in net_configs:
        if getattr(item, 'nicType', '') == 'management':
            has_management_config = True
            selected.update(getattr(item, 'selectedVnic', None) or [])
    candidates = set()
    for nic in vnics:
        if has_management_config and not selected.intersection(
                [getattr(nic, 'key', ''), getattr(nic, 'device', '')]):
            continue
        ip_spec = getattr(getattr(nic, 'spec', None), 'ip', None)
        address = valid_host_ip(getattr(ip_spec, 'ipAddress', ''))
        if address:
            candidates.add(address)
    ip_debug('management_ip_result', {'host': getattr(host_obj, '_moId', ''),
        'has_management_config': has_management_config, 'selected': sorted(selected),
        'candidate_ips': sorted(candidates), 'reason': 'unique' if len(candidates) == 1 else 'no_match' if not candidates else 'multiple_ips'})
    if len(candidates) == 1:
        return next(iter(candidates))
    logger.warning('[management_ip] host=%s ambiguous_or_missing_management_ip count=%s',
                   getattr(host_obj, '_moId', ''), len(candidates))
    return ''


def hardware_serial(host_obj):
    """跳过硬件占位值，继续尝试其他序列号候选。"""
    info = getattr(getattr(host_obj, 'hardware', None), 'systemInfo', None)
    candidates = [getattr(info, 'serialNumber', '')]
    for kind in ('ServiceTag', 'SerialNumberTag'):
        for item in getattr(info, 'otherIdentifyingInfo', None) or []:
            if getattr(getattr(item, 'identifierType', None), 'key', '') == kind:
                candidates.append(getattr(item, 'identifierValue', ''))
    invalid = set(['', 'none', 'null', 'n/a', 'na', 'unknown', 'not specified',
                   'not available', 'default string', 'system serial number',
                   'chassis serial number', 'to be filled by o.e.m.',
                   'to be filled by oem', '0', '00000000'])
    for value in candidates:
        value = (value or '').strip()
        if value.lower() not in invalid:
            return value
    return ''


def remove_invalid_sn(values):
    """上报前最后一道保护：异常 SN 直接删除整个键值对。"""
    value = values.get('sn')
    if value is None or (value or '').strip().lower() in set([
            '', 'none', 'null', 'n/a', 'na', 'unknown', 'not specified',
            'not available', 'default string', 'system serial number',
            'chassis serial number', 'to be filled by o.e.m.',
            'to be filled by oem', '0', '00000000']):
        values.pop('sn', None)
    return values


class EasyVcenter:
    def __init__(self, host, port, user, pwd, instance_id="", no_collect_vm=False):
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.provider_instance_id = instance_id
        self.no_collect_vm = no_collect_vm
        self.content = self.get_content()
        instance_uuid = self.content.about.instanceUuid
        # _moId是VMware内部对象的唯一标识，但在多个vCenter环境下可能重复，需要加上vCenter标识符来确保全局唯一性
        if instance_uuid:
            self.resource_name = instance_uuid
        else:
            self.resource_name = instance_id
            logger.warning('vCenter instance uuid为空,使用provider instance id作为id前缀')
        self.result = []

    def _physical_host_keys(self):
        """同一次采集统一匹配键；重复 IP 的所有宿主机均排除。"""
        if hasattr(self, '_physical_keys'):
            return self._physical_keys
        hosts = list(self._get_all_objs([vim.HostSystem]))
        keys = {}
        counts = {}
        for host_obj in hosts:
            address = management_ip(host_obj)
            if address:
                keys[host_obj._moId] = address
                counts[address] = counts.get(address, 0) + 1
        self._physical_keys = {}
        for host_id, address in keys.items():
            if counts[address] == 1:
                self._physical_keys[host_id] = {'businessIp': address}
            else:
                logger.warning('[physical_host_keys] duplicate_business_ip host=%s ip=%s skipped', host_id, address)
        ip_debug('physical_host_keys', {'host_count': len(hosts), 'ip_counts': counts,
            'accepted': self._physical_keys, 'skipped_hosts': [h._moId for h in hosts if h._moId not in self._physical_keys]})
        self._physical_hosts = hosts
        return self._physical_keys

    def _physical_relation(self, host_id):
        key = self._physical_host_keys().get(host_id)
        return [dict(key)] if key else []

    def get_content(self):
        try:
            connect = SmartConnect(
                host=self.host,
                user=self.user,
                pwd=self.pwd,
                port=self.port
            )
            content = connect.RetrieveContent()
            return content
        except Exception as e:
            logger.error("[get_content] vCenter connection failed: %s", traceback.format_exc())
            raise Exception('Connect vcenter failed, error: {}'.format(e))

    def _get_all_objs(self, obj_type, folder=None):
        """
        根据对象类型获取这一类型的所有对象
        """
        if folder is None:
            container = self.content.viewManager.CreateContainerView(self.content.rootFolder,
                                                                     obj_type, True)
        else:
            container = self.content.viewManager.CreateContainerView(folder, obj_type, True)
        return container.view

    def _get_obj(self, obj_type, name):
        """
        根据对象类型和名称来获取具体对象
        """
        obj = None
        container = self.content.viewManager.CreateContainerView(self.content.rootFolder, obj_type,
                                                                 True)
        for c in container.view:
            if c.name == name:
                obj = c
                break
        return obj

    @staticmethod
    def sizeof_fmt(num, unit='bytes'):
        items = ['bytes', 'KB', 'MB', 'GB']

        try:
            index = items.index(unit)
        except ValueError:
            logger.warning('Invalid unit: {}, using default unit: bytes'.format(unit))
            index = 0

        for item in items[index:]:
            if num < 1024.0:
                return "%0.2f%s" % (num, item)
            num /= 1024.0
        return "%.2f%s" % (num, 'TB')

    @staticmethod
    def mac_lower(_mac):
        """mac地址变成小写"""
        if isinstance(_mac, str):
            return _mac.lower()
        return _mac

    def get_obj_id(self, obj):
        return "{}_{}".format(self.resource_name, obj._moId)
    
    def set_cloud_provider(self, vals):
        vals['provider'] = PROVIDER
        vals["cloudProvider"] = [{'instanceId': self.provider_instance_id}]
    
    @staticmethod
    def get_default_ip(hostname, default_ip, ips):
        """
        通过主机名，默认IP，IP列表修正默认IP
        因为主机名后面会带上主机IP的后半部分，当默认IP跟这个不匹配当时候，去IP列表找能匹配的返回，否则直接返回默认的
        :param hostname: 虚拟机主机名，如d1-findg22、d1-oracledg-11.26
        :param default_ip: 默认IP
        :param ips: IP列表
        :return:
        """
        hostname = hostname or ''
        default_ip = default_ip or ''
        ips = ips or []
        ret = re.findall(r'[\d.]+$', hostname)
        if ret:
            suffix_ip = ret[0]
            if not default_ip.endswith(suffix_ip):
                for ip in ips:
                    if ip and ip.endswith(suffix_ip):
                        return ip
        if not default_ip:
            for ip in ips:
                if ip and is_valid_ipv4(ip):
                    default_ip = ip
                    break
        return default_ip
    
    def get_datacenter_list(self):
        """
        采集VMware数据中心
        创建关系：VMware数据中心——资源池，VMware数据中心——VMware集群
        :return:
        """
        logger.info('------------------ 开始采集VMware数据中心 ------------------')
        datacenter_datas = []
        datacenter_obj_list = self._get_all_objs([vim.Datacenter])
        for datacenter_obj in datacenter_obj_list:
            relation_with_cluster = []
            relation_with_host = []
            datacenter = {}
            datacenter_id = str(datacenter_obj).split(':')[1].replace('\'', '')
            datacenter_name = '{}_{}'.format(self.resource_name, datacenter_id)
            datacenter['name'] = datacenter_name
            datacenter['dataCenterId'] = datacenter_id
            datacenter['dataCenterName'] = datacenter_obj.name

            if 'Folder' not in str(datacenter_obj):
                for cluster_obj in datacenter_obj.hostFolder.childEntity:
                    cluster_id = str(cluster_obj).split(':')[1].replace('\'', '')
                    cluster_name = '{}_{}'.format(self.resource_name, cluster_id)
                    relation_with_cluster.append({
                        "name": cluster_name
                    })
                    if 'Folder' not in str(cluster_obj):
                        for host_obj in cluster_obj.host:
                            host_id = str(host_obj).split(':')[1].replace('\'', '')
                            host_name = '{}_{}'.format(self.resource_name, host_id)
                            relation_with_host.append({
                                "name": host_name
                            })
            if relation_with_cluster:
                datacenter['VMWARE_CLUSTER'] = relation_with_cluster
            if relation_with_host:
                datacenter['VMWARE_HOST_COMPUTER'] = relation_with_host

            datacenter_data = {
                "dims": {
                    "objectId": "VMWARE_DATA_CENTER@ONEMODEL",
                    "object_id": "VMWARE_DATA_CENTER@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_CLUSTER",
                        "VMWARE_HOST_COMPUTER",
                    ]
                },
                "vals": datacenter
            }
            datacenter_datas.append(datacenter_data)
        self.result.extend(datacenter_datas)
        logger.info('------------------ VMware数据中心采集完成 ------------------\n')

    def get_cluster_list(self):
        """
        采集VMware集群
        创建关系：VMware集群——VMware存储，VMware集群——VMware宿主机
        :return:
        """
        logger.info('----------------- 开始采集VMware集群 ----------------')
        cluster_datas = []
        cluster_obj_list = self._get_all_objs([vim.ClusterComputeResource])
        for cluster_obj in cluster_obj_list:
            relation_with_store = []
            relation_with_host = []
            cluster = {}
            cluster_id = str(cluster_obj).split(':')[1].replace('\'', '')
            cluster_name = '{}_{}'.format(self.resource_name, cluster_id)
            cluster['name'] = cluster_name
            cluster['clusterId'] = cluster_id
            cluster['drsEnabled'] = str(
                cluster_obj.configuration.drsConfig.enableVmBehaviorOverrides)
            cluster['clusterName'] = cluster_obj.name

            for ds_obj in cluster_obj.datastore:
                ds_id = str(ds_obj).split(':')[1].replace('\'', '')
                ds_name = '{}_{}'.format(self.resource_name, ds_id)
                relation_with_store.append({
                    "name": ds_name,
                })
            if relation_with_store:
                cluster['VMWARE_DATASTORE'] = relation_with_store

            for esxi_host_obj in cluster_obj.host:
                host_id = str(esxi_host_obj).split(':')[1].replace('\'', '')
                host_name = '{}_{}'.format(self.resource_name, host_id)
                relation_with_host.append({
                    "name": host_name
                })
            if relation_with_host:
                cluster['VMWARE_HOST_COMPUTER'] = relation_with_host

            cluster_data = {
                "dims": {
                    "objectId": "VMWARE_CLUSTER@ONEMODEL",
                    "object_id": "VMWARE_CLUSTER@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_VIRTUAL_MACHINE",
                        "VMWARE_HOST_COMPUTER",
                    ]
                },
                "vals": cluster
            }
            cluster_datas.append(cluster_data)

        self.result.extend(cluster_datas)
        logger.info('----------------- VMware集群采集完成 ----------------\n')

    def get_esxi_host_list(self):
        """
        采集宿主机信息
        创建关系：VMware宿主机——VMware虚拟机
        :return:
        """
        logger.info('------------------ 开始采集ESXI主机 -----------------')
        esxi_host_datas = []
        esxi_host_obj_list = self._get_all_objs([vim.HostSystem])
        for obj in esxi_host_obj_list:
            relation_with_vm = []
            item = {}
            esxi_host_id = str(obj).split(':')[1].replace('\'', '')
            esxi_host_name = '{}_{}'.format(self.resource_name, esxi_host_id)
            ips = []
            business_ip = None
            if obj.config and obj.config.network and obj.config.network.vnic:
                vnic_list = obj.config.network.vnic or []
                for i in vnic_list:
                    if i and i.spec and i.spec.ip and i.spec.mac:
                        ip_address = getattr(i.spec.ip, 'ipAddress', None)
                        mac_address = getattr(i.spec, 'mac', None)
                        if ip_address and mac_address:
                            ip_info = {"ip": ip_address, "mac": self.mac_lower(mac_address)}
                            ips.append(ip_info)
                            if not business_ip:
                                business_ip = ip_address
            pnic_version = obj.summary.config.product.fullName if obj.summary and obj.summary.config and obj.summary.config.product else ""
            enableVsan = False
            vsan_system = obj.configManager.vsanSystem if obj.configManager else None
            if vsan_system:
                if vsan_system.config and vsan_system.config.enabled:
                    enableVsan = True
            physical_relation = self._physical_relation(obj._moId)
            if physical_relation:
                item['_physicalServer'] = physical_relation
            business_ip = management_ip(obj)
            item['enableVsan'] = enableVsan
            item['networkInfo'] = ips
            item['businessIp'] = business_ip
            item['name'] = esxi_host_name
            item['hostid'] = esxi_host_id
            item['version'] = pnic_version
            if obj.summary and obj.summary.config:
                item['hostname'] = obj.summary.config.name
            if obj.summary and obj.summary.runtime:
                item['connected'] = obj.summary.runtime.powerState
                item['maintenance'] = str(obj.summary.runtime.inMaintenanceMode)
            if obj.summary and obj.summary.hardware:
                item['cpuCoreCount'] = obj.summary.hardware.numCpuCores
                item['cpuNum'] = obj.summary.hardware.numCpuPkgs
                item['cpuBMhz'] = obj.summary.hardware.cpuMhz
                item['cpuThreadNum'] = obj.summary.hardware.numCpuThreads
                item['memSize'] = int(obj.summary.hardware.memorySize) if obj.summary.hardware.memorySize else 0
            if obj.summary and obj.summary.quickStats:
                item['overallCpuUsage'] = obj.summary.quickStats.overallCpuUsage
                item['overallMemoryUsage'] = obj.summary.quickStats.overallMemoryUsage
                if isinstance(item['overallMemoryUsage'], (str, int, float)):
                    item['overallMemoryUsageGB'] = float(item['overallMemoryUsage']) / 1024
            if obj.vm:
                item['vmNum'] = len(obj.vm)
            if obj.summary and obj.summary.managementServerIp:
                item["ip"] = obj.summary.managementServerIp

            for vm_obj in obj.vm:
                vm_id = str(vm_obj).split(':')[1].replace('\'', '')
                vm_name = '{}_{}'.format(self.resource_name, vm_id)
                relation_with_vm.append({
                    "name": vm_name
                })
            if relation_with_vm:
                item["VMWARE_VIRTUAL_MACHINE"] = relation_with_vm

            esxi_host_data = {
                "dims": {
                    "objectId": "VMWARE_HOST_COMPUTER@ONEMODEL",
                    "object_id": "VMWARE_HOST_COMPUTER@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_VIRTUAL_MACHINE",
                    ] + (["_physicalServer"] if physical_relation else [])
                },
                "vals": item
            }
            esxi_host_datas.append(esxi_host_data)

        self.result.extend(esxi_host_datas)
        logger.info('------------------ ESXI主机采集完成 -----------------\n')

    def get_store_list(self):
        """
        采集存储信息
        创建关系：VMware存储——VMware虚拟机，VMware存储——VMware宿主机
        :return:
        """
        logger.info('------------------ 开始采集VMware存储 -----------------')
        store_datas = []
        store_obj_list = self._get_all_objs([vim.Datastore])
        for obj in store_obj_list:
            relation_with_vm = []
            relation_with_host = []
            item = {}
            store_id = str(obj).split(':')[1].replace('\'', '')
            store_name = '{}_{}'.format(self.resource_name, store_id)
            disk_name = ""
            try:
                if obj.info and obj.info.vmfs and obj.info.vmfs.extent:
                    for dis in obj.info.vmfs.extent:
                        disk_name = dis.diskName
            except AttributeError as e:
                logger.warning('[get_store_list] disk name unavailable: %s', traceback.format_exc())
            ds_capacity = obj.summary.capacity
            ds_freespace = obj.summary.freeSpace
            ds_uncommitted = obj.summary.uncommitted if obj.summary.uncommitted else 0
            ds_provisioned = ds_capacity - ds_freespace + ds_uncommitted
            item['name'] = store_name
            item['id'] = store_id
            item['url'] = obj.summary.url
            item['capacity'] = self.sizeof_fmt(ds_capacity)
            item['freeSpace'] = self.sizeof_fmt(ds_freespace)
            item['uncommittedSpace'] = self.sizeof_fmt(ds_provisioned)
            item['storeName'] = obj.summary.name
            item['diskName'] = disk_name

            # 关联虚拟机
            for vm_obj in obj.vm:
                vm_id = str(vm_obj).split(':')[1].replace('\'', '')
                vm_name = '{}_{}'.format(self.resource_name, vm_id)
                relation_with_vm.append({
                    "name": vm_name
                })
            if relation_with_vm:
                item['VMWARE_VIRTUAL_MACHINE'] = relation_with_vm

            # 关联宿主机
            for host_obj in obj.host:
                host_id = str(host_obj.key).split(':')[1].replace('\'', '')
                host_name = '{}_{}'.format(self.resource_name, host_id)
                relation_with_host.append({
                    "name": host_name
                })
            if relation_with_host:
                item['VMWARE_HOST_COMPUTER'] = relation_with_host

            store_data = {
                "dims": {
                    "objectId": "VMWARE_DATASTORE@ONEMODEL",
                    "object_id": "VMWARE_DATASTORE@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_HOST_COMPUTER",
                        "VMWARE_VIRTUAL_MACHINE",
                    ]
                },
                "vals": item
            }
            store_datas.append(store_data)

        self.result.extend(store_datas)
        logger.info('------------------ VMware存储采集完成 -----------------\n')

    def get_resource_pool_list(self):
        """
        采集VMware资源池
        创建关系：
        :return:
        """
        logger.info('----------------- 开始采集VMware资源池 ---------------')
        resource_pool_datas = []
        resource_pool_obj_list = self._get_all_objs([vim.ResourcePool])
        for obj in resource_pool_obj_list:
            item = {}
            resource_pool_id = str(obj).split(':')[1].replace('\'', '')
            resource_pool_name = '{}_{}'.format(self.resource_name, resource_pool_id)
            item['name'] = resource_pool_name
            item['id'] = resource_pool_id
            item['poolName'] = obj.name
            resource_pool_data = {
                "dims": {
                    "objectId": "VMWARE_RESOURCE_POOL@ONEMODEL",
                    "object_id": "VMWARE_RESOURCE_POOL@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": []
                },
                "vals": item
            }
            resource_pool_datas.append(resource_pool_data)

        self.result.extend(resource_pool_datas)
        logger.info('----------------- VMware资源池采集完成 ---------------\n')

    def get_port_group_list(self):
        """
        采集VMware端口组
        创建关系：VMware端口组——VMware虚拟机,VMware端口组——VMware宿主机,VMware端口组——VMware交换机
        :return:
        """
        logger.info('------------------- 开始采集端口组 -------------------')
        item_datas = []
        obj_list = self._get_all_objs([vim.DistributedVirtualPortgroup])
        for obj in obj_list:
            relation_with_vm = []
            relation_with_host = []
            item = {}
            item_id = str(obj).split(':')[1].replace('\'', '')
            item_name = '{}_{}'.format(self.resource_name, item_id)
            item['id'] = item_id
            item['name'] = item_name
            item['portName'] = obj.name
            vlan_id = obj.config.defaultPortConfig.vlan.vlanId
            if isinstance(vlan_id, int):
                item['vlanId'] = vlan_id
            else:
                logger.warning('{} vlan id is not int,{}'.format(item_name, vlan_id))
            if obj.config:
                item['portNum'] = obj.config.numPorts
            item['ports'] = list(obj.portKeys) if obj.portKeys else []
            # 关联虚拟机
            for vm_obj in obj.vm:
                vm_id = str(vm_obj).split(':')[1].replace('\'', '')
                vm_name = '{}_{}'.format(self.resource_name, vm_id)
                relation_with_vm.append({
                    "name": vm_name
                })
            if relation_with_vm:
                item['VMWARE_VIRTUAL_MACHINE'] = relation_with_vm
            # 关联宿主机
            for host_obj in obj.host:
                host_id = str(host_obj).split(':')[1].replace('\'', '')
                host_name = '{}_{}'.format(self.resource_name, host_id)
                relation_with_host.append({
                    "name": host_name
                })
            if relation_with_host:
                item['VMWARE_HOST_COMPUTER'] = relation_with_host
            # 关联交换机
            if obj.config.distributedVirtualSwitch:
                switch_key = obj.config.distributedVirtualSwitch
                switch_id = str(switch_key).split(':')[1].replace('\'', '')
                switch_name = '{}_{}'.format(self.resource_name, switch_id)
                item['VMWARE_VIRTUAL_SWITCH'] = [{
                    "name": switch_name
                }]

            item_data = {
                "dims": {
                    "objectId": "VMWARE_PORT_GROUP@ONEMODEL",
                    "object_id": "VMWARE_PORT_GROUP@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_VIRTUAL_MACHINE",
                        "VMWARE_HOST_COMPUTER",
                        "VMWARE_VIRTUAL_SWITCH",
                    ]
                },
                "vals": item
            }
            item_datas.append(item_data)

        self.result.extend(item_datas)
        logger.info('------------------- 端口组采集完成 -------------------\n')

    def get_network_list(self):
        """
        采集VMware_网络管理
        关系创建：VMware_网络管理——VMware虚拟机，VMware_网络管理——VMware宿主机
        :return:
        """
        logger.info('--------------- 开始采集VMware_网络管理 --------------')
        item_datas = []
        obj_list = self._get_all_objs([vim.Network])
        for obj in obj_list:
            if isinstance(obj, vim.dvs.DistributedVirtualPortgroup):
                continue
            relation_with_vm = []
            relation_with_host = []
            item = {}
            item_name = '{}_{}'.format(self.resource_name, obj._GetMoId())
            item['name'] = item_name
            item['networkName'] = obj.name
            # 关联虚拟机
            for vm_obj in obj.vm:
                vm_id = str(vm_obj).split(':')[1].replace('\'', '')
                vm_name = '{}_{}'.format(self.resource_name, vm_id)
                relation_with_vm.append({
                    "name": vm_name
                })
            if relation_with_vm:
                item['VMWARE_VIRTUAL_MACHINE'] = relation_with_vm

            # 关联宿主机
            for host_obj in obj.host:
                host_id = str(host_obj).split(':')[1].replace('\'', '')
                host_name = '{}_{}'.format(self.resource_name, host_id)
                relation_with_host.append({
                    "name": host_name
                })
            if relation_with_host:
                item['VMWARE_HOST_COMPUTER'] = relation_with_host

            item_data = {
                "dims": {
                    "objectId": "VMWARE_NETWORK@ONEMODEL",
                    "object_id": "VMWARE_NETWORK@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_VIRTUAL_MACHINE",
                        "VMWARE_HOST_COMPUTER",
                    ]
                },
                "vals": item
            }
            item_datas.append(item_data)

        self.result.extend(item_datas)
        logger.info('--------------- VMware_网络管理采集完成 --------------\n')

    def get_vm_list(self):
        """
        采集VMware虚拟机
        关系创建：VMware虚拟机——主机
        :return:
        """
        logger.info('---------------- 开始采集VMware虚拟机 ----------------')
        item_datas = []
        obj_list = self._get_all_objs([vim.VirtualMachine])
        for obj in obj_list:
            relation_with_host = []
            if obj.summary.config.template is True:  # 忽略模版
                continue
            item = {}
            item_id = str(obj).split(':')[1].replace('\'', '')
            item_name = '{}_{}'.format(self.resource_name, item_id)
            ips = []
            disks = []
            if obj.guest:
                for stack in obj.guest.net or []:
                    if stack.ipAddress:
                        for i in stack.ipAddress:
                            ips.append({'mac': self.mac_lower(stack.macAddress), 'ip': i})
            if obj.config is not None and obj.config.hardware is not None:
                for device in obj.config.hardware.device:
                    if isinstance(device, vim.vm.device.VirtualDisk):
                        disks.append({
                            'diskName': device.deviceInfo.label,
                            'capacity': format(self.sizeof_fmt(device.capacityInKB, unit='KB'))
                        })

            # 获取自定义属性
            tags = []
            if self.content and self.content.customFieldsManager and self.content.customFieldsManager.field:
                custom_fields = self.content.customFieldsManager.field
                if obj.summary and obj.summary.customValue:
                    for value in obj.summary.customValue:
                        field = next((f for f in custom_fields if f.key == value.key), None)
                        if field and field.name and value.value:
                            tags.append({"key": field.name.decode('utf-8'), "value": value.value.decode('utf-8')})

            item['tags'] = tags
            item['name'] = item_name
            if obj.summary and obj.summary.config:
                item['guestId'] = obj.summary.config.guestFullName
                item['id'] = item_id
                if obj.summary.config.memorySizeMB:
                    item['memSize'] = int(obj.summary.config.memorySizeMB) * 1024
                item['uuid'] = obj.summary.config.uuid
                item['vmName'] = obj.summary.config.name
                item['cpuCoreCount'] = obj.summary.config.numCpu
                # 设置默认IP
                ip_list = [each.get('ip') for each in ips if each and each.get('ip')]
                default_ip = self.get_default_ip(obj.summary.config.name, getattr(obj.summary.guest, 'ipAddress', None) if obj.summary.guest else None,
                                                 ip_list)
                item['defaultIP'] = default_ip
                item['vmxPath'] = obj.summary.config.vmPathName
            item['vmwareToolsStatus'] = obj.guestHeartbeatStatus if obj.guestHeartbeatStatus else ""
            item['network'] = ips
            item['disk'] = disks
            item['powerState'] = obj.runtime.powerState if obj.runtime and obj.runtime.powerState else ""
            
            # 关联宿主机
            if obj.runtime.host:
                host_id = str(obj.runtime.host).split(':')[1].replace('\'', '')
                host_name = '{}_{}'.format(self.resource_name, host_id)
                relation_with_host.append({
                    "name": host_name
                })
            if relation_with_host:
                item['VMWARE_HOST_COMPUTER'] = relation_with_host

            item_data = {
                "dims": {
                    "objectId": "VMWARE_VIRTUAL_MACHINE@ONEMODEL",
                    "object_id": "VMWARE_VIRTUAL_MACHINE@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_HOST_COMPUTER",
                    ]
                },
                "vals": item
            }
            item_datas.append(item_data)

        self.result.extend(item_datas)
        logger.info('---------------- VMware虚拟机采集完成 ----------------\n')

    def get_template_list(self):
        """
        采集VMware模版
        关系创建：
        :return:
        """
        logger.info('----------------- 开始采集VMware模版 -----------------')
        item_datas = []
        obj_list = self._get_all_objs([vim.VirtualMachine])
        for obj in obj_list:
            if obj.summary.config.template is not True:  # 忽略非模版
                continue
            item = {}
            item_id = str(obj).split(':')[1].replace('\'', '')
            item_name = '{}_{}'.format(self.resource_name, item_id)
            ips = []
            disks = []
            if obj.guest and obj.guest.net:
                for stack in obj.guest.net:
                    if stack.ipAddress:
                        for i in stack.ipAddress:
                            ips.append({'mac': self.mac_lower(stack.macAddress), 'ip': i})
            if obj.guest and obj.guest.disk:
                for disk_name in obj.guest.disk:
                    if disk_name:
                        disk_path = {'diskName': disk_name.diskPath,
                                     'capacity': format(self.sizeof_fmt(disk_name.capacity)),
                                     'freeCapacity': format(self.sizeof_fmt(disk_name.freeSpace))}
                        disks.append(disk_path)
            item['name'] = item_name
            if obj.summary and obj.summary.guest:
                item['defaultIP'] = obj.summary.guest.ipAddress
            if obj.summary and obj.summary.config:
                item['guestId'] = obj.summary.config.guestFullName
                item['id'] = item_id
                if obj.summary.config.memorySizeMB:
                    item['memSize'] = int(obj.summary.config.memorySizeMB) * 1024
                item['uuid'] = obj.summary.config.uuid
                item['vmName'] = obj.summary.config.name
                item['cpuCoreCount'] = obj.summary.config.numCpu
            item['vmwareToolsStatus'] = obj.guestHeartbeatStatus if obj.guestHeartbeatStatus else ""
            item['network'] = ips
            item['disk'] = disks
            item['powerState'] = obj.runtime.powerState if obj.runtime and obj.runtime.powerState else ""
            item_data = {
                "dims": {
                    "objectId": "VMWARE_TEMPLATE@ONEMODEL",
                    "object_id": "VMWARE_TEMPLATE@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": []
                },
                "vals": item
            }
            item_datas.append(item_data)

        self.result.extend(item_datas)
        logger.info('----------------- VMware模版采集完成 -----------------\n')

    def get_switch_list(self):
        """
        采集VMware交换机
        关系创建：VMware交换机——VMware虚拟机
        :return:
        """
        logger.info('---------------- 开始采集VMware交换机 ----------------')
        item_datas = []
        obj_list = self._get_all_objs([vim.DistributedVirtualSwitch])
        for obj in obj_list:
            relation_with_vm = []
            item = {}
            item_id = str(obj).split(':')[1].replace('\'', '')
            item_name = '{}_{}'.format(self.resource_name, item_id)
            item['id'] = item_id
            item['name'] = item_name
            item['vcName'] = obj.name
            # 关联虚拟机
            for vm_obj in obj.summary.vm:
                vm_id = str(vm_obj).split(':')[1].replace('\'', '')
                vm_name = '{}_{}'.format(self.resource_name, vm_id)
                relation_with_vm.append({
                    "name": vm_name
                })
            if relation_with_vm:
                item['VMWARE_VIRTUAL_MACHINE'] = relation_with_vm

            item_data = {
                "dims": {
                    "objectId": "VMWARE_VIRTUAL_SWITCH@ONEMODEL",
                    "object_id": "VMWARE_VIRTUAL_SWITCH@ONEMODEL",
                    "pks": ["name"],
                    "upsert": True,
                    "set_relation_ids": [
                        "VMWARE_VIRTUAL_MACHINE",
                    ]
                },
                "vals": item
            }
            item_datas.append(item_data)

        self.result.extend(item_datas)
        logger.info('---------------- VMware交换机采集完成 ----------------\n')

    def get_cloud_resource_pool_list(self):
        """
        采集资源池（数据中心+集群）
        关系创建：云平台、物理服务器、云资源
        :return:
        """
        logger.info('---------------- 开始采集云资源池 ----------------')
        datacenter_obj_list = self._get_all_objs([vim.Datacenter])
        for datacenter_obj in datacenter_obj_list:
            id_path = self.resource_name + "/" + datacenter_obj._moId
            name_path = datacenter_obj.name
            path_to_pool = dict()
            for child_entity in datacenter_obj.hostFolder.childEntity:
                self._build_path_to_pool(child_entity, id_path, name_path, "数据中心", path_to_pool)
            for id_path, pool_info in path_to_pool.items():
                vals = {}
                vals['id'] = id_path
                vals['name'] = pool_info['name']
                vals['type'] = pool_info['type']
                vals['cloudProvider'] = [{'instanceId': self.provider_instance_id}]
                vals['cloudResources'] = pool_info['cloudResources']
                if pool_info['physicalServers']:
                    vals['physicalServers'] = pool_info['physicalServers']
                self.result.append({
                    "dims": {
                        "objectId": RESOURCE_POOL_OBJECT_ID,
                        "object_id": RESOURCE_POOL_OBJECT_ID,
                        "pks": ["id"],
                        "upsert": True,
                        "set_relation_ids": ["cloudProvider", "cloudResources"] + (["physicalServers"] if vals.get("physicalServers") else [])
                    },
                    "vals": vals
                })
        logger.info('---------------- 资源池采集完成 ----------------\n')

    def _build_path_to_pool(self, obj, pre_id_path, pre_name_path, last_node_type, path_to_pool):
        if isinstance(obj, vim.ComputeResource) and not isinstance(obj, vim.ClusterComputeResource):
            id_path = pre_id_path
            name_path = pre_name_path
            node_type = last_node_type
        else:
            node_type = VM_OBJECT_TYPE.get(type(obj),  obj._moId.split(':')[0]) if obj and obj._moId else ""
            id_path = pre_id_path + "/" + (obj._moId if obj and obj._moId else "")
            name_path = pre_name_path + "/" + (obj.name if obj and obj.name else "")
        if isinstance(obj, vim.Folder):
            if obj.childEntity:
                for child_obj in obj.childEntity:
                    self._build_path_to_pool(child_obj, id_path, name_path, node_type, path_to_pool)
        elif isinstance(obj, vim.ClusterComputeResource):
            if obj.resourcePool:
                for pool_obj in obj.resourcePool.resourcePool:
                    self._build_path_to_pool(pool_obj, id_path, name_path, node_type, path_to_pool)
        elif isinstance(obj, vim.ResourcePool):
            # 子资源池
            if obj.resourcePool:
                for pool_obj in obj.resourcePool:
                    self._build_path_to_pool(pool_obj, id_path, name_path, node_type, path_to_pool)
        
        if hasattr(obj, 'host') and obj.host:
            for host in obj.host:
                pool_info = path_to_pool.get(id_path)
                if not pool_info:
                    pool_info = {
                        "name": name_path,
                        "type": node_type,
                        "cloudResources": [],
                        "physicalServers": [],
                    }
                    path_to_pool[id_path] = pool_info
                pool_info["physicalServers"].extend(self._physical_relation(host._moId))
        
        if hasattr(obj, 'datastore') and obj.datastore:
            for datastore in obj.datastore:
                pool_info = path_to_pool.get(id_path)
                if not pool_info:
                    pool_info = {
                        "name": name_path,
                        "type": node_type,
                        "cloudResources": [],
                        "physicalServers": [],
                    }
                    path_to_pool[id_path] = pool_info
                pool_info["cloudResources"].append({
                    "id": self.get_obj_id(datastore),
                })
        
        # vm 是挂在集群的默认资源池下的
        if isinstance(obj, vim.ClusterComputeResource):
            obj = obj.resourcePool
        elif isinstance(obj, vim.ComputeResource) and obj.host:
            obj = obj.host[0] if obj.host else None
        if hasattr(obj, 'vm') and obj and obj.vm:
            if self.no_collect_vm:
                return
            for vm in obj.vm:
                pool_info = path_to_pool.get(id_path)
                if not pool_info:
                    pool_info = {
                        "name": name_path,
                        "type": node_type,
                        "cloudResources": [],
                        "physicalServers": []
                    }
                    path_to_pool[id_path] = pool_info
                pool_info["cloudResources"].append({
                    "id": self.resource_name + '_' + (vm._moId if vm and vm._moId else ""),
                })
                snapshots = self.get_all_snapshots(vm)
                for snapshot in snapshots:
                    pool_info["cloudResources"].append({
                        "id": self.resource_name + '_' + (snapshot.snapshot._moId if snapshot and snapshot.snapshot and snapshot.snapshot._moId else ""),
                    })
                
    def get_all_snapshots(self, vm_obj):
        snapshots = []

        def recurse_snapshots(snap_tree_list):
            for snap in snap_tree_list:
                snapshots.append(snap)
                if snap and snap.childSnapshotList:
                    recurse_snapshots(snap.childSnapshotList)

        if vm_obj and vm_obj.snapshot:
            recurse_snapshots(vm_obj.snapshot.rootSnapshotList)

        return snapshots
    
    def get_cloud_vm_list(self):
        """
        采集虚拟机
        关系创建：资源池、宿主机、操作系统
        :return:
        """
        logger.info('---------------- 开始采集VMware虚拟机 ----------------')
        if self.no_collect_vm:
            logger.info('---------------- 跳过VMware虚拟机采集 ----------------\n')
            return
        obj_list = self._get_all_objs([vim.VirtualMachine])
        for obj in obj_list:
            snapshot_rel = []
            snapshots = self.get_all_snapshots(obj)
            for snapshot in snapshots:
                vals = {}
                snapshot_id = self.resource_name + "_" + (snapshot.snapshot._moId if snapshot and snapshot.snapshot and snapshot.snapshot._moId else "")
                vals['id'] = snapshot_id
                vals['cloudResourceName'] = snapshot.name if snapshot and snapshot.name else ""
                vals['createdTime'] = snapshot.createTime.strftime("%Y-%m-%d %H:%M:%S") if snapshot and snapshot.createTime else ""
                vals['resourceDescription'] = snapshot.description if snapshot and snapshot.description else ""
                vals['status'] = VM_STATUS.get(snapshot.state, snapshot.state) if snapshot and snapshot.state else "unknown"
                vals['annotations'] = [
                    {
                        "key": "quiesced",
                        "name": "静默客户机文件系统",
                        "value": "是" if snapshot and snapshot.quiesced else "否"
                    }
                ]
                vals['provider'] = PROVIDER
                vals['cloudProvider'] = [{"instanceId": self.provider_instance_id}]
                self.result.append({
                    "dims": {
                        "objectId": SNAPSHOT_OBJECT_ID,
                        "object_id": SNAPSHOT_OBJECT_ID,
                        "pks": ["id"],
                        "upsert": True,
                        "set_relation_ids": ["cloudProvider"]
                    },
                    "vals": vals
                })
                snapshot_rel.append({
                    "id": snapshot_id
                })
            
            vals = {}
            vals['id'] = self.resource_name + "_" + obj._moId
            if obj.summary and obj.summary.config:
                vals['cloudResourceName'] = obj.summary.config.name or ""
                vals['status'] = VM_STATUS.get(obj.runtime.powerState, obj.runtime.powerState) if obj.runtime and obj.runtime.powerState else "unknown"
                vals['resourceDescription'] = obj.summary.config.annotation if obj.summary.config.annotation else ""
                vals['cpuCoreCount'] = obj.summary.config.numCpu if obj.summary.config.numCpu else 0
                if obj.summary.config.memorySizeMB:
                    vals['memorySize'] = int(obj.summary.config.memorySizeMB) / 1024

            vals['provider'] = PROVIDER
            vals['cloudProvider'] = [{"instanceId": self.provider_instance_id}]

            # 网络接口
            network_interfaces = []
            if obj.guest:
                for nic_info in obj.guest.net or []:
                    # 实际使用的ip
                    if nic_info and nic_info.ipAddress:
                        for ip in nic_info.ipAddress:
                            network_interfaces.append({'mac': nic_info.macAddress if nic_info.macAddress else "", 'ip': ip})
                    # 配置的ip, 场景是虚拟机关机处于封存状态, 但ip还需要保留
                    elif nic_info and nic_info.ipConfig and nic_info.ipConfig.ipAddress:
                        for ip in nic_info.ipConfig.ipAddress:
                            if ip and ip.ipAddress:
                                network_interfaces.append({'mac': nic_info.macAddress if nic_info.macAddress else "", 'ip': ip.ipAddress})
                    # 某些非常规操作系统没有ip地址，但是有mac地址
                    elif nic_info and nic_info.macAddress:
                        network_interfaces.append({'mac': nic_info.macAddress if nic_info.macAddress else "", 'ip': ""})
            vals['networkInterfaceInfo'] = network_interfaces

            # 磁盘
            disks = []
            if obj.config is not None and obj.config.hardware is not None and obj.config.hardware.device:
                for device in obj.config.hardware.device:
                    if device and isinstance(device, vim.vm.device.VirtualDisk) and device.deviceInfo and device.deviceInfo.label:
                        disks.append({
                            'diskName': device.deviceInfo.label if device.deviceInfo.label else "",
                            'capacity': device.capacityInKB / (1024 * 1024) if device.capacityInKB else 0
                        })
            vals['diskInfo'] = disks

            # 关联宿主机
            if obj.runtime and obj.runtime.host:
                host_mo_id = str(obj.runtime.host).split(':')[1].replace('\'', '') if obj.runtime.host else ""
                host_id = '{}_{}'.format(self.resource_name, host_mo_id)
                physical_relation = self._physical_relation(obj.runtime.host._moId)
                if physical_relation:
                    vals['physicalServer'] = physical_relation

            # 关联操作系统, 取第一个ipv4地址作为操作系统ip
            ips = [network_interface.get('ip') for network_interface in network_interfaces if network_interface.get('ip')]
            ip_v4 = ""
            os_relations = []
            for ip in ips:
                if is_valid_ipv4(ip):
                    ip_v4 = ip
                    os_relations.append({'ip': ip})
                    break
            vals['ip'] = ip_v4
            vals['os'] = os_relations
            
            # 关联快照
            vals["snapshots"] = snapshot_rel

            guest_heartbeat_status = getattr(obj, 'guestHeartbeatStatus', "") if obj else ""
            vmx_path = getattr(getattr(getattr(obj, 'summary', None), 'config', None), 'vmPathName', "") if obj and obj.summary else ""
            is_template = getattr(getattr(getattr(obj, 'summary', None), 'config', None), 'template', False) if obj and obj.summary else False
            
            vals['annotations'] = [
                {
                    'key': 'vmwareToolsStatus',
                    'name': 'VMwareTools状态',
                    'value': guest_heartbeat_status
                },
                {
                    'key': 'vmxPath',
                    'name': '虚拟机路径',
                    'value': vmx_path
                },
                {
                    'key': 'isTemplate',
                    'name': '是否为虚拟机模版',
                    'value': convert_annotation_value(is_template)
                }
            ]
            self.result.append({
                "dims": {
                    "objectId": CLOUD_VM_OBJECT_ID,
                    "object_id": CLOUD_VM_OBJECT_ID,
                    "pks": ["id"],
                    "upsert": True,
                    "set_relation_ids": ["cloudProvider", "physicalServer", "os", "snapshots"]
                },
                "vals": vals
            })
        logger.info('---------------- VMware虚拟机采集完成 ----------------\n')
        
    def get_physical_server_list(self):
        """
        采集物理服务器
        关系创建：云平台、资源池、操作系统
        其中物理服务器和云平台的关系需要从云平台模型段建立
        :return:
        """
        logger.info('------------------ 开始采集物理服务器 -----------------')
        physical_server_list = []
        host_keys = self._physical_host_keys()
        physical_server_obj_list = self._physical_hosts
        physical_server_keys = []
        for obj in physical_server_obj_list:
            key = host_keys.get(obj._moId)
            if not key:
                logger.warning('[get_physical_server_list] host=%s has no unique management IP, skip', obj._moId)
                continue
            vals = dict(key)
            sn = hardware_serial(obj)
            if sn:
                vals['sn'] = sn
            else:
                logger.warning('[get_physical_server_list] host=%s invalid SN omitted', obj._moId)
            remove_invalid_sn(vals)
            physical_server_keys.append(dict(key))
            vals['resourceInstanceId'] = '{}_{}'.format(self.resource_name, obj._moId)

            # 关联云平台
            vals['cloudProvider'] = [{'instanceId': self.provider_instance_id}]

            physical_server_data = {
                "dims": {
                    "objectId": SERVER_OBJECT_ID,
                    "object_id": SERVER_OBJECT_ID,
                    "pks": ["businessIp"],
                    "upsert": False,  # 通过物理服务器的台账来发现
                    "set_relation_ids": [
                        "cloudProvider",
                    ]
                },
                "vals": vals
            }
            logger.info('physical server data: {}'.format(physical_server_data))
            physical_server_list.append(physical_server_data)

        self.result.extend(physical_server_list)
        
        if physical_server_keys:
            # 上报数据云平台数据
            rel_vals = {}
            rel_vals['physicalServers'] = physical_server_keys
            rel_vals['instanceId'] = self.provider_instance_id
            physical_server_relation_data = {
                "dims": {
                    "objectId": CLOUD_PROVIDER_OBJECT_ID,
                    "object_id": CLOUD_PROVIDER_OBJECT_ID,
                    "pks": ["instanceId"],
                    "upsert": False,
                    "set_relation_ids": [
                        "physicalServers",
                    ]
                },
                "vals": rel_vals
            }
            self.result.append(physical_server_relation_data)
        
        logger.info('------------------ 物理服务器采集完成 -----------------\n')

    def get_cloud_disk_list(self):
        """
        采集云硬盘
        """
        logger.info('------------------ 开始采集云硬盘 -----------------')
        store_datas = []
        store_obj_list = self._get_all_objs([vim.Datastore])
        for obj in store_obj_list:
            item = {}
            id = '{}_{}'.format(self.resource_name, obj._moId)
            ds_capacity = obj.summary.capacity if obj.summary else 0
            
            disk_name = ""
            try:
                if obj.info and obj.info.vmfs and obj.info.vmfs.extent:
                    for dis in obj.info.vmfs.extent:
                        disk_name = dis.diskName if dis and dis.diskName else ""
            except AttributeError:
                logger.warning('[get_cloud_disk_list] disk name unavailable: %s', traceback.format_exc())
                disk_name = ""
            ds_capacity = obj.summary.capacity if obj.summary else 0
            ds_freespace = obj.summary.freeSpace if obj.summary else 0
            ds_uncommitted = obj.summary.uncommitted if obj.summary and obj.summary.uncommitted else 0
            ds_provisioned = ds_capacity - ds_freespace + ds_uncommitted
            item['id'] = id
            item['cloudResourceName'] = obj.summary.name if obj.summary and obj.summary.name else ""
            item['totalCapacity'] = byte_to_gb(ds_capacity)
            item['availableCapacity'] = byte_to_gb(ds_freespace)
            annotation_tuples = [
                ("freeSpace", "可用空间(GiB)", byte_to_gb(ds_freespace)),
                ("uncommittedSpace", "置备的空间(GiB)", byte_to_gb(ds_provisioned)),
                ("diskName", "磁盘名称", disk_name),
                ("url", "URL", obj.summary.url if obj.summary else ""),
            ]
            item['annotations'] = convert_annotation_tuples(annotation_tuples)
            self.set_cloud_provider(item)

            # 关联虚拟机
            relation_with_vm = []
            if obj.vm:
                for vm_obj in obj.vm:
                    vm_name = '{}_{}'.format(self.resource_name, vm_obj._moId if vm_obj and vm_obj._moId else "")
                    relation_with_vm.append({
                        "name": vm_name
                    })
            item['cloudVMs'] = relation_with_vm

            # 关联宿主机
            relation_with_host = []
            if obj.host:
                for host_obj in obj.host:
                    host_mo_id = str(host_obj.key).split(':')[1].replace('\'', '') if host_obj and host_obj.key else ""
                    host_name = '{}_{}'.format(self.resource_name, host_mo_id)
                    relation_with_host.extend(self._physical_relation(host_obj.key._moId))
            if relation_with_host:
                item['physicalServers'] = relation_with_host

            store_data = {
                "dims": {
                    "objectId": STORAGE_OBJECT_ID,
                    "object_id": STORAGE_OBJECT_ID,
                    "pks": ["id"],
                    "upsert": True,
                    "set_relation_ids": [
                        "cloudVMs",
                        "physicalServers",
                    ]
                },
                "vals": item
            }
            store_datas.append(store_data)

        self.result.extend(store_datas)
        logger.info('------------------ 云硬盘采集完成 -----------------\n')

    def get_cloud_vpc_list(self):
        logger.info('------------------ 开始采集云VPC -----------------\n')
        item_datas = []
        obj_list = self._get_all_objs([vim.DistributedVirtualPortgroup])
        for obj in obj_list:
            item = {}
            item_id = self.get_obj_id(obj)
            item['id'] = item_id
            item['cloudResourceName'] = obj.name
            annotation_tuples = []
            vlan_id = ""
            num_ports = ""
            port_keys = []
            if obj.config:
                if obj.config.defaultPortConfig and obj.config.defaultPortConfig.vlan:
                    vlan_id = obj.config.defaultPortConfig.vlan.vlanId if obj.config.defaultPortConfig.vlan.vlanId else ""
                    if not isinstance(vlan_id, int):
                        vlan_id = ""
                num_ports = obj.config.numPorts if obj.config.numPorts else ""
            if obj.portKeys:
                port_keys = list(obj.portKeys) if obj.portKeys else []
            annotation_tuples = [
                ("vlanId", "VLAN ID", vlan_id),
                ("numPorts", "端口分配总数", num_ports),
                ("portKeys", "分配的端口ID", port_keys)
            ]
            self.set_cloud_provider(item)
            item['annotations'] = convert_annotation_tuples(annotation_tuples)
            item_data = {
                "dims": {
                    "objectId": VPC_OBJECT_ID,
                    "object_id": VPC_OBJECT_ID,
                    "pks": ["id"],
                    "upsert": True,
                    "set_relation_ids": [
                        "cloudProvider",
                    ]
                },
                "vals": item
            }
            item_datas.append(item_data)
        self.result.extend(item_datas)
        logger.info('------------------ 云VPC采集完成 -----------------\n')


def is_valid_ipv4(ip):
    # 匹配 0.0.0.1-255.255.255.255
    if not ip or ip == "0.0.0.0":
        return False
    pattern = r'(([1-9]?\d|1\d\d|2[0-4]\d|25[0-5])\.){3}([1-9]?\d|1\d\d|2[0-4]\d|25[0-5])'
    return re.match(pattern, ip) is not None

def byte_to_gb(val):
    if not val:
        return 0
    gb_value = val / 1073741824.0
    return int(round(gb_value))

def convert_annotation_value(annotation):
    if isinstance(annotation, bool):
        return "是" if annotation else "否"
    return annotation

def convert_annotation_tuples(annotation_tuples):
    annotations = []
    for annotation_tuple in annotation_tuples:
        key, name, value = annotation_tuple
        annotations.append({
            "key": key,
            "name": name,
            "value": value,
        })
    return annotations


def runProc(action, host, port, user, password):
    vcenter = EasyVcenter(host=host, user=user, pwd=password, port=port)
    logger.info('#' * 50 + '\n###### 开始采集VCenter平台信息 {}:{}\n\n'.format(vcenter.resource_name, host))
    if action == '数据中心':
        vcenter.get_datacenter_list()
    elif action == '集群':
        vcenter.get_cluster_list()
    elif action == 'ESXI主机':
        vcenter.get_esxi_host_list()
    elif action == '存储':
        vcenter.get_store_list()
    elif action == 'vm资源池':
        vcenter.get_resource_pool_list()
    elif action == '端口组':
        vcenter.get_port_group_list()
    elif action == '网络':
        vcenter.get_network_list()
    elif action == '虚拟机':
        vcenter.get_vm_list()
    elif action == '模板':
        vcenter.get_template_list()
    elif action == '交换机':
        vcenter.get_switch_list()
    else:
        vcenter.get_template_list()  # 模版
        vcenter.get_resource_pool_list()  # 资源池
        vcenter.get_vm_list()  # 虚拟机
        vcenter.get_esxi_host_list()  # 宿主机
        vcenter.get_switch_list()  # 交换机
        vcenter.get_port_group_list()  # 端口组
        vcenter.get_network_list()  # 网络管理
        vcenter.get_store_list()  # 存储
        vcenter.get_cluster_list()  # 集群
        vcenter.get_datacenter_list()  # 数据中心

    return vcenter.result

def runProcV2(host, port, user, password, instance_id, no_collect_vm):
    vcenter = EasyVcenter(host=host, user=user, pwd=password, port=port, instance_id=instance_id, no_collect_vm=no_collect_vm)
    vcenter.get_physical_server_list()
    vcenter.get_cloud_vm_list()
    vcenter.get_cloud_resource_pool_list()
    vcenter.get_cloud_disk_list()
    vcenter.get_cloud_vpc_list()
    return vcenter.result

def main(action, host, port, user, password, instance_id, no_collect_vm, report_to_old_model):
    if report_to_old_model == "true":
        return runProc(action, host, port, user, password)
    else:
        return runProcV2(host, port, user, password, instance_id, no_collect_vm)


if __name__ == "__main__":
    # 调试或执行
    noCollectVm = True if noCollectVm == "true" else False
    result = main('', host, port, user, password, instanceId, noCollectVm, reportToOldModel)
    try:
        logging.info("Collect datas size: %d" % len(result))
        logging.info(json.dumps(result, indent=2))
    except Exception:
        logger.error('[main] result logging failed: %s', traceback.format_exc())
    print("-----BEGIN GATHERING DATA-----")
    print(json.dumps(result, indent=4))
    print("-----END GATHERING DATA-----")
