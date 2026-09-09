#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人行双平台数据统一到 CMDB。spec: tmp/fintech-sync/spec.md"""
import json, re, subprocess, sys
from datetime import datetime, date
from pathlib import Path
import openpyxl

# ============================== CONFIG ==============================
SIDES = {'report': Path('/workspace/tmp/人行上报'), 'mgmt': Path('/workspace/tmp/人行管理')}

# excel主名(上报侧) → {'model_id','key'(唯一键中文列名),'mgmt_alias'(管理侧文件主名,缺省同名)}
MODEL_MAP = {
    '交换机':               {'model_id': 'switches@FINTECHDATA',              'key': '设施标识符'},
    '路由器':               {'model_id': 'router@FINTECHDATA',                'key': '设施标识符'},
    '防火墙':               {'model_id': 'firewall@FINTECHDATA',              'key': '设施标识符'},
    '负载均衡设备':           {'model_id': 'loadBalancing@FINTECHDATA',        'key': '设施标识符'},
    '上网行为管理设备':       {'model_id': 'onlineBehavior@FINTECHDATA',       'key': '设施标识符'},
    '入侵检测与防御设备（IDS_IPS）': {'model_id': 'idsIps@FINTECHDATA',        'key': '设施标识符', 'mgmt_alias': '入侵检测与防御设备'},
    '运维审计设备':          {'model_id': 'opsAudit@FINTECHDATA',              'key': '设施标识符'},
    '虚拟机资源':            {'model_id': 'virtualMachine@FINTECHDATA',       'key': '设施标识符', 'mgmt_alias': '虚拟机'},
    '机架式服务器':          {'model_id': 'rackServer@FINTECHDATA',           'key': '设施标识符'},
    '基础软件':             {'model_id': 'basedSoftware@FINTECHDATA',         'key': '软件标识符'},
    '光纤交换机':            {'model_id': 'fiberSwitch@FINTECHDATA',          'key': '设施标识符'},
    '机柜':                {'model_id': 'commonCabinet@FINTECHDATA',         'key': '设施标识符', 'mgmt_alias': '普通机柜'},
    '视频监控类':            {'model_id': 'videoMonitoring@FINTECHDATA',      'key': '设施标识符', 'mgmt_alias': '视频监控系统'},
    '动环监控系统':          {'model_id': 'environmentalMonitoring@FINTECHDATA','key': '设施标识符'},
    '门禁系统':             {'model_id': 'entranceGuard@FINTECHDATA',         'key': '设施标识符'},
    '消防系统':             {'model_id': 'fireProtection@FINTECHDATA',        'key': '设施标识符'},
    '中央空调':             {'model_id': 'centralAirCondition@FINTECHDATA',   'key': '设施标识符'},
    '普通空调':             {'model_id': 'commonAirCondition@FINTECHDATA',    'key': '设施标识符'},
    '精密空调':             {'model_id': 'precisionAirCondition@FINTECHDATA', 'key': '设施标识符'},
    '新风系统':             {'model_id': 'freshAir@FINTECHDATA',              'key': '设施标识符'},
    '加湿系统':             {'model_id': 'humidification@FINTECHDATA',        'key': '设施标识符'},
    '发电机':               {'model_id': 'generator@FINTECHDATA',             'key': '设施标识符'},
    '不间断配电':            {'model_id': 'uninterrupted@FINTECHDATA',        'key': '设施标识符'},
    '精密配电设备':          {'model_id': 'precisionPower@FINTECHDATA',       'key': '设施标识符'},
    '高压配电设备':          {'model_id': 'highVoltage@FINTECHDATA',          'key': '设施标识符'},
    '低压配电':             {'model_id': 'lowVoltage@FINTECHDATA',            'key': '设施标识符'},
    '变压器设备':           {'model_id': 'transformer@FINTECHDATA',          'key': '设施标识符'},
    '波分复用设备':          {'model_id': 'wdm@FINTECHDATA',                  'key': '设施标识符'},
    '数据中心':             {'model_id': 'dataCenter@FINTECHDATA',           'key': '设施标识符'},   # 仅上报
    '数据中心间距':          {'model_id': 'dataCenterSpacing@FINTECHDATA',    'key': '关系标识符'},
    '应用系统':             {'model_id': 'application@FINTECHDATA',          'key': '应用系统标识符'},
    '供电关联关系':          {'model_id': 'powerSupplyRelation@FINTECHDATA',  'key': '关系标识符'},
    '网络线路':             {'model_id': 'networkLine@FINTECHDATA',           'key': '设施标识符'},
    '网络线路关联关系':       {'model_id': 'networkRelation@FINTECHDATA',     'key': '关系标识符'},
    '应用系统关联关系':       {'model_id': 'applicationRelation@FINTECHDATA', 'key': '关系标识符'},
    '应用系统软件关联关系':    {'model_id': 'applicationSoftRelation@FINTECHDATA','key': '关系标识符'},
    '软件实例关联关系':       {'model_id': 'softwareRelation@FINTECHDATA',    'key': '关系标识符'},
}

# model_id → [(上报列名|None, 管理列名|None, cmdb属性id), ...]
# 属性 id 支持点号嵌套（structs 子字段，如 'switches_deployment.deployArea'）：
# transform 产出嵌套 dict，import 前组装为 CMDB structs 形态 list[dict]。
# 初始为空：investigate() 生成骨架（out/config-skeleton.py），人工核对后粘贴此处
FIELD_MAP = {
    'onlineBehavior@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("用户认证模式", "用户认证模式", "authenticationPattern"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("Bypass功能", "Bypass功能", "bypass"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("部署区域", "部署区域", "onlineBehavior_deployment.deployArea"),
        ("所属机房", "所属机房", "onlineBehavior_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "onlineBehavior_deployment.deployDb"),
        ("所属楼层", "所属楼层", "onlineBehavior_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "onlineBehavior_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "onlineBehavior_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "onlineBehavior_installationPosition.slotNo"),
        ("日志存储位置", "日志存储位置", "onlineBehavior_logSave.logLocation"),
        ("存储周期(月)", "存储周期", "onlineBehavior_logSave.storagePeriod"),
        ("管理部门", None, "onlineBehavior_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "onlineBehavior_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "onlineBehavior_operationsManagement.serviceEndTime"),
        ("服务级别", None, "onlineBehavior_operationsManagement.serviceLevel"),
        ("服务提供商", None, "onlineBehavior_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "onlineBehavior_operationsManagement.serviceStartTime"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("安全部署方式", "安全部署方式", "safetydeploymentMode"),
        ("安全销售许可", "安全销售许可", "sellingLicense"),
        ("支持的功能", "支持的功能", "supportFunciton"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("吞吐率", "吞吐率", "throughputRate"),
    ],
    'uninterrupted@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("后备电源时长(分钟)", "后备电源时长", "backupPowerSupply"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("部署区域", "部署区域", "uninterrupted_deployment.deployArea"),
        ("所属机房", "所属机房", "uninterrupted_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "uninterrupted_deployment.deployDb"),
        ("所属楼层", "所属楼层", "uninterrupted_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "uninterrupted_deployment.deployGallery"),
        ("管理部门", None, "uninterrupted_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "uninterrupted_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "uninterrupted_operationsManagement.serviceEndTime"),
        ("服务级别", None, "uninterrupted_operationsManagement.serviceLevel"),
        ("服务提供商", None, "uninterrupted_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "uninterrupted_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "uninterrupted_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "uninterrupted_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "uninterrupted_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "uninterrupted_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "uninterrupted_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "uninterrupted_ratedOutputParameter.ratedOutputVoltage"),
        ("蓄电池类型", "蓄电池类型", "uninterrupted_uninterruptibleDistribution.batteryType"),
        ("蓄电池数量(个)", "蓄电池数量", "uninterrupted_uninterruptibleDistribution.numberOfBatteries"),
        ("不间断电源主机功率模块类型", "不间断电源主机功率模块类型", "uninterrupted_uninterruptibleDistribution.typeOfUninterruptibleMainsPowerModule"),
        ("不间断电源主机类型", "不间断电源主机类型", "uninterrupted_uninterruptibleDistribution.uninterruptibleMainsType"),
        ("不间断电源并机系统", "不间断电源并机系统", "upsParallelSystem"),
    ],
    'centralAirCondition@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("部署区域", "部署区域", "centralAirCondition_deployment.deployArea"),
        ("所属机房", "所属机房", "centralAirCondition_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "centralAirCondition_deployment.deployDb"),
        ("所属楼层", "所属楼层", "centralAirCondition_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "centralAirCondition_deployment.deployGallery"),
        ("管理部门", None, "centralAirCondition_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "centralAirCondition_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "centralAirCondition_operationsManagement.serviceEndTime"),
        ("服务级别", None, "centralAirCondition_operationsManagement.serviceLevel"),
        ("服务提供商", None, "centralAirCondition_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "centralAirCondition_operationsManagement.serviceStartTime"),
        ("中央空调分类", "中央空调分类", "centralAirConditioningType"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("设备功率(KW)", "设备功率", "ratedPower"),
        ("空调制冷量(KW)", "空调制冷量", "refrigeratingCapacity"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'switches@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("功能用途", "功能用途", "function"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("网络安全能力", "网络安全能力", "networkSecurityCapability"),
        ("板卡数量(个)", "板卡数量", "numberOfCards"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("部署区域", "部署区域", "switches_deployment.deployArea"),
        ("所属机房", "所属机房", "switches_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "switches_deployment.deployDb"),
        ("所属楼层", "所属楼层", "switches_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "switches_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "switches_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "switches_installationPosition.slotNo"),
        ("管理部门", None, "switches_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "switches_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "switches_operationsManagement.serviceEndTime"),
        ("服务级别", None, "switches_operationsManagement.serviceLevel"),
        ("服务提供商", None, "switches_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "switches_operationsManagement.serviceStartTime"),
        ("无线功能", "无线功能", "wirelessFunction"),
    ],
    'lowVoltage@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("低压配电设备控制类型", "低压配电设备控制类型", "lowVoltageEquipmentControlType"),
        ("低压成套设备类型", "低压成套设备类型", "lowVoltageEquipmentType"),
        ("部署区域", "部署区域", "lowVoltage_deployment.deployArea"),
        ("所属机房", "所属机房", "lowVoltage_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "lowVoltage_deployment.deployDb"),
        ("所属楼层", "所属楼层", "lowVoltage_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "lowVoltage_deployment.deployGallery"),
        ("管理部门", None, "lowVoltage_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "lowVoltage_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "lowVoltage_operationsManagement.serviceEndTime"),
        ("服务级别", None, "lowVoltage_operationsManagement.serviceLevel"),
        ("服务提供商", None, "lowVoltage_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "lowVoltage_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "lowVoltage_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "lowVoltage_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "lowVoltage_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "lowVoltage_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "lowVoltage_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "lowVoltage_ratedOutputParameter.ratedOutputVoltage"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'powerSupplyRelation@FINTECHDATA': [
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", "归属机构", "facilityOwnershipAgency"),
        (None, None, "importId"),
        ("供电设施", "供电设施", "powerSupplyAsset"),
        ("供电设施类型", "供电设施类型", "powerSupplyAssetCategory"),
        ("用电设施", "用电设施", "powerUsedAsset"),
        ("用电设施类型", "用电设施类型", "powerUsedAssetCategory"),
        ("关系标识符", "关系标识符", "relationalIdentifier"),
    ],
    'fiberSwitch@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("部署区域", "部署区域", "fiberSwitch_deployment.deployArea"),
        ("所属机房", "所属机房", "fiberSwitch_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "fiberSwitch_deployment.deployDb"),
        ("所属楼层", "所属楼层", "fiberSwitch_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "fiberSwitch_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "fiberSwitch_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "fiberSwitch_installationPosition.slotNo"),
        ("管理部门", None, "fiberSwitch_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "fiberSwitch_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "fiberSwitch_operationsManagement.serviceEndTime"),
        ("服务级别", None, "fiberSwitch_operationsManagement.serviceLevel"),
        ("服务提供商", None, "fiberSwitch_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "fiberSwitch_operationsManagement.serviceStartTime"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("网络安全能力", "网络安全能力", "networkSecurityCapability"),
        ("光纤端口数量(个)", "光纤端口数量", "numberOfOpticalFiberPorts"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
    ],
    'idsIps@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("Bypass功能", "Bypass功能", "bypass"),
        ("设备类型", "设备类型", "categoryOfEquipment"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("数据存储位置", "数据存储位置", "idsIps_dataSave.dataLocation"),
        ("存储周期(月)", "存储周期", "idsIps_dataSave.storagePeriod"),
        ("部署区域", "部署区域", "idsIps_deployment.deployArea"),
        ("所属机房", "所属机房", "idsIps_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "idsIps_deployment.deployDb"),
        ("所属楼层", "所属楼层", "idsIps_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "idsIps_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "idsIps_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "idsIps_installationPosition.slotNo"),
        ("管理部门", None, "idsIps_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "idsIps_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "idsIps_operationsManagement.serviceEndTime"),
        ("服务级别", None, "idsIps_operationsManagement.serviceLevel"),
        ("服务提供商", None, "idsIps_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "idsIps_operationsManagement.serviceStartTime"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("安全部署方式", "安全部署方式", "safetydeploymentMode"),
        ("安全销售许可", "安全销售许可", "sellingLicense"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("吞吐率", "吞吐率", "throughputRate"),
    ],
    'humidification@FINTECHDATA': [
        ("设备品牌", None, "assetBrand"),
        ("资产编码", None, "assetCode"),
        ("产品序列号", None, "assetSerialNumber"),
        ("设备型号", None, "assetType"),
        ("资产价值(万元)", None, "assetValue"),
        ("品牌属地", None, "brandLand"),
        ("加湿器分类", None, "classificationOfHumidifiers"),
        ("设施分类标识符", None, "facilityCategory"),
        ("设施标识符", None, "facilityDescriptor"),
        ("设施名称", None, "facilityName"),
        ("设施归属机构", None, "facilityOwnershipAgency"),
        ("设施投产日期", None, "facilityUseDate"),
        ("设施在用状态", None, "facilityUseState"),
        ("部署区域", None, "humidification_deployment.deployArea"),
        ("所属机房", None, "humidification_deployment.deployComputerRoom"),
        ("部署数据中心", None, "humidification_deployment.deployDb"),
        ("所属楼层", None, "humidification_deployment.deployFloor"),
        ("所属楼座", None, "humidification_deployment.deployGallery"),
        ("管理部门", None, "humidification_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "humidification_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "humidification_operationsManagement.serviceEndTime"),
        ("服务级别", None, "humidification_operationsManagement.serviceLevel"),
        ("服务提供商", None, "humidification_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "humidification_operationsManagement.serviceStartTime"),
        ("设备功率(KW)", None, "ratedPower"),
        ("备注信息", None, "remarksInformation"),
    ],
    'environmentalMonitoring@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("部署区域", "部署区域", "environmentalMonitoring_deployment.deployArea"),
        ("所属机房", "所属机房", "environmentalMonitoring_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "environmentalMonitoring_deployment.deployDb"),
        ("所属楼层", "所属楼层", "environmentalMonitoring_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "environmentalMonitoring_deployment.deployGallery"),
        ("空调制冷系统", "空调制冷系统", "environmentalMonitoring_monitoringScope.airConditioningSystem"),
        ("电池监控", "电池监控", "environmentalMonitoring_monitoringScope.batteryMonitor"),
        ("发电机系统", "发电机系统", "environmentalMonitoring_monitoringScope.generatorSystem"),
        ("漏水检测", "漏水检测", "environmentalMonitoring_monitoringScope.leakageDetection"),
        ("其它范围", "其它范围", "environmentalMonitoring_monitoringScope.otherRange"),
        ("配电系统", "配电系统", "environmentalMonitoring_monitoringScope.powerDistributionSystem"),
        ("机房温湿度", "机房温湿度", "environmentalMonitoring_monitoringScope.roomTemperatureAndHumidity"),
        ("UPS系统", "UPS系统", "environmentalMonitoring_monitoringScope.upsSystem"),
        ("管理部门", None, "environmentalMonitoring_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "environmentalMonitoring_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "environmentalMonitoring_operationsManagement.serviceEndTime"),
        ("服务级别", None, "environmentalMonitoring_operationsManagement.serviceLevel"),
        ("服务提供商", None, "environmentalMonitoring_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "environmentalMonitoring_operationsManagement.serviceStartTime"),
        ("环境监控软件", "环境监控软件", "environmentalMonitoring_softwareAttribute.environmentalMonitoringSoftware"),
        ("系统集成商", "系统集成商", "environmentalMonitoring_softwareAttribute.systemIntegrator"),
        ("报警功能", "报警功能", "environmentalMonitoring_systemFunction.alarmFunction"),
        ("联动功能", "联动功能", "environmentalMonitoring_systemFunction.linkageFunction"),
        ("日志功能", "日志功能", "environmentalMonitoring_systemFunction.logging"),
        ("监控功能", "监控功能", "environmentalMonitoring_systemFunction.monitoringFunction"),
        ("其它功能", "其它功能", "environmentalMonitoring_systemFunction.otherFeatures"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'generator@FINTECHDATA': [
        ("发电机类型", "发电机类型", "alternatorType"),
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("部署区域", "部署区域", "generator_deployment.deployArea"),
        ("所属机房", "所属机房", "generator_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "generator_deployment.deployDb"),
        ("所属楼层", "所属楼层", "generator_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "generator_deployment.deployGallery"),
        ("额定容量(KVA)", "额定容量", "generator_generatorOperating.nominalCapacity"),
        ("功率因数", "功率因数", "generator_generatorOperating.powerFactor"),
        ("管理部门", None, "generator_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "generator_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "generator_operationsManagement.serviceEndTime"),
        ("服务级别", None, "generator_operationsManagement.serviceLevel"),
        ("服务提供商", None, "generator_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "generator_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "generator_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "generator_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "generator_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "generator_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "generator_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "generator_ratedOutputParameter.ratedOutputVoltage"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'transformer@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("变压器类型", "变压器类型", "transformerType"),
        ("部署区域", "部署区域", "transformer_deployment.deployArea"),
        ("所属机房", "所属机房", "transformer_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "transformer_deployment.deployDb"),
        ("所属楼层", "所属楼层", "transformer_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "transformer_deployment.deployGallery"),
        ("管理部门", None, "transformer_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "transformer_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "transformer_operationsManagement.serviceEndTime"),
        ("服务级别", None, "transformer_operationsManagement.serviceLevel"),
        ("服务提供商", None, "transformer_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "transformer_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "transformer_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "transformer_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "transformer_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "transformer_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "transformer_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "transformer_ratedOutputParameter.ratedOutputVoltage"),
    ],
    'basedSoftware@FINTECHDATA': [
        ("购买数量(套)", "购买数量", "basedSoftware_softwareAsset.number"),
        ("软件许可数量(套)", "软件许可数量", "basedSoftware_softwareAsset.numberOfSoftwareLicenses"),
        ("使用范围", "使用范围", "basedSoftware_softwareAsset.scopeOfUse"),
        ("软件安装条件", "软件安装条件", "basedSoftware_softwareAsset.softwareInstallationConditions"),
        ("软件使用期限", "软件使用期限", "basedSoftware_softwareAsset.softwareLife"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("软件实例数(套)", "软件实例数", "numberOfSoftwareInstance"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("软件分类标识符", "软件分类标识符", "softwareCategory"),
        ("软件标识符", "软件标识符", "softwareDescriptor"),
        ("软件生产商", "软件生产商", "softwareManufacturer"),
        ("软件名称", "软件名称", "softwareName"),
        ("软件所属机构", "软件所属机构", "softwareOwnershipAgency"),
        ("软件来源", "软件来源", "softwareSource"),
        ("软件版本信息", "软件版本信息", "softwareVersionInformation"),
    ],
    'application@FINTECHDATA': [
        ("应用简介", "应用简介", "applicationProfile"),
        ("应用系统标识符", "应用系统标识符", "applySystemIdentifiers"),
        (None, None, "brandLand"),
        ("开发商属地", "开发商属地", "developerTerritory"),
        ("开发语言", "开发语言", "developmentLanguage"),
        ("开发模式", "开发模式", "developmentMode"),
        ("灾备等级", "灾备等级", "disasterRecoveryLevel"),
        ("灾备方式", "灾备方式", "disasterRecoveryMod"),
        ("灾备策略", "灾备策略", "disasterRecoveryStrategy"),
        ("业务领域特征", "业务领域特征", "domainCharacteristics"),
        ("应急预案", "应急预案", "emergencyPlan"),
        ("首次投产日期", "首次投产日期", "facilityFirstUseDate"),
        ("高可用方式", "高可用方式", "highAvailability"),
        ("知识产权", "知识产权", "intellectualProperty"),
        ("是否面向互联网服务", "是否面向互联网服务", "internetSever"),
        ("等级保护级别", "等级保护级别", "levelOfProtection"),
        ("运维模式", None, "maintenanceMode"),
        ("新技术特征", "新技术特征", "newTechnical"),
        ("备注信息", None, "note"),
        ("备注信息", "备注", "note"),
        (None, "RP0", "rpo"),
        ("RPO(分钟)", "RP0", "rpo"),
        (None, "RT0", "rto"),
        ("RTO(分钟)", "RT0", "rto"),
        ("服务对象", "服务对象", "serviceObject"),
        ("服务时段", "服务时段", "servicePeriod"),
        ("分类标识符", None, "softwareCategory"),
        ("分类标识符", "软件分类标识符", "softwareCategory"),
        ("应用系统英文简称", "应用系统英文简称", "softwareEnName"),
        ("应用系统名称", None, "softwareName"),
        ("应用系统名称", "软件名称", "softwareName"),
        ("应用所属机构", None, "softwareOwnershipAgency"),
        ("应用所属机构", "软件所属机构名称", "softwareOwnershipAgency"),
        ("是否采用分布式技术", "是否采用分布式技术", "supportDistributed"),
        ("IPV6支持", "IPV6支持", "supportIpv6"),
    ],
    'applicationRelation@FINTECHDATA': [
        (None, "应用系统标识符", "applicationIdentifier"),
        ("服务器类型标识", "服务器类型标识", "applicationServerType"),
        ("应用系统关联服务器", "应用系统关联服务器", "applicationSystemAssociatedServer"),
        (None, None, "applicationSystemAssociatedStorage"),
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", "归属机构", "facilityOwnershipAgency"),
        ("关系标识符", "关系标识符", "relationalIdentifier"),
    ],
    'applicationSoftRelation@FINTECHDATA': [
        (None, None, "_diffDetail.reportValue"),
        (None, "应用系统标识符", "applicationIdentifier"),
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", "归属机构", "facilityOwnershipAgency"),
        ("关系标识符", "关系标识符", "relationalIdentifier"),
        (None, "基础软件标识符", "softwareDescriptor"),
    ],
    'dataCenter@FINTECHDATA': [
        ("行政区划", None, "administrativeArea"),
        ("国标标准", None, "computerRoomGradeNationalStandard"),
        ("Uptime TIER等级", None, "computerRoomGradeUptimeTier"),
        ("建设模式", None, "constructionMode"),
        ("行政管理区面积(㎡)", None, "dataCenter_area.administrativeArea"),
        ("辅助区面积(㎡)", None, "dataCenter_area.auxiliaryArea"),
        ("建筑面积(㎡)", None, "dataCenter_area.constructionArea"),
        ("主机房使用面积(㎡)", None, "dataCenter_area.mainMachineRoomUsableArea"),
        ("园区面积(㎡)", None, "dataCenter_area.parkArea"),
        ("支持区面积(㎡)", None, "dataCenter_area.supportArea"),
        ("接入网络级别", None, "dataCenter_availability.netLevel"),
        ("网络运营商", None, "dataCenter_availability.networkOperator"),
        ("接入网络运营商数量", None, "dataCenter_availability.networkOperatorNumber"),
        ("供电方案", None, "dataCenter_availability.powerScheme"),
        ("实际能源效率指标", None, "dataCenter_energyEnvironmentAdv.actualPue"),
        ("年用电量(度)", None, "dataCenter_energyEnvironmentAdv.annualElectricityConsumption"),
        ("年用水量(吨)", None, "dataCenter_energyEnvironmentAdv.annualWater"),
        ("用电平均单价(元)", None, "dataCenter_energyEnvironmentAdv.averageUnitPriceOfElectricity"),
        ("用水平均单价(元)", None, "dataCenter_energyEnvironmentAdv.averageUnitPriceOfWater"),
        ("设计总机柜(个)", None, "dataCenter_energyEnvironmentAdv.designCabinetNumber"),
        ("设计总功率(KW)", None, "dataCenter_energyEnvironmentAdv.designPower"),
        ("设计能源效率指标", None, "dataCenter_energyEnvironmentAdv.designingPue"),
        ("用电类型", None, "dataCenter_energyEnvironmentAdv.electricityType"),
        ("制冷方案", None, "dataCenter_energyEnvironmentAdv.refrigerationScheme"),
        ("已用机柜数(个)", None, "dataCenter_energyEnvironmentAdv.usedCabinetNumber"),
        ("年平均运维费用(万元/年)", None, "dataCenter_manageability.averageOpsCosts"),
        ("近五年受灾情况统计(次)", None, "dataCenter_manageability.disasterStatisticsInThePastFiveYears"),
        ("值班情况", None, "dataCenter_manageability.dutyCondition"),
        ("电气设备运维人数(人)", None, "dataCenter_manageability.electricalEquipmentOpsPersonnel"),
        ("暖通运维人数(人)", None, "dataCenter_manageability.hvacOpsPersonnel"),
        ("IT设备运维人数(人)", None, "dataCenter_manageability.itEquipmentOpsPersonnel"),
        ("网络运维人数(人)", None, "dataCenter_manageability.networkOpsPersonnel"),
        ("运维人数(人)", None, "dataCenter_manageability.operationNumbers"),
        ("其它辅助运维人数(人)", None, "dataCenter_manageability.otherSupportingOpsPersonnel"),
        ("外包运维人员总数(人)", None, "dataCenter_manageability.outsourcedNumber"),
        ("建筑抗震", None, "dataCenter_security.antiEarthquakeLevel"),
        ("建筑承重(N/㎡)", None, "dataCenter_security.buildingBearingCapacity"),
        ("建筑防雷", None, "dataCenter_security.buildingLightningProtection"),
        ("灭火系统类型", None, "dataCenter_security.fireExtinguishingSystemType"),
        ("数据中心级别", None, "dbLevel"),
        ("设施分类标识符", None, "facilityCategory"),
        ("设施标识符", None, "facilityDescriptor"),
        ("设施名称", None, "facilityName"),
        ("设施归属机构", None, "facilityOwnershipAgency"),
        (None, None, "facilityUpdateDate"),
        ("设施投产日期", None, "facilityUseDate"),
        ("设施在用状态", None, "facilityUseState"),
        ("功能定位", None, "functionalOrientation"),
        ("地理位置", None, "geographicalPosition"),
        ("LEI全球法人机构识别编码", None, "lei"),
        ("国家地区", None, "nationalArea"),
        ("备注信息", None, "remarksInformation"),
    ],
    'dataCenterSpacing@FINTECHDATA': [
        (None, None, "_diffDetail.reportValue"),
        ("从属关系", "从属关系", "affiliation"),
        ("直线距离(公里)", "直线距离", "airlineDistance"),
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", "归属机构", "facilityOwnershipAgency"),
        ("本端数据中心", "本端数据中心", "localDb"),
        ("对端数据中心", "对端数据中心", "oppositeDb"),
        ("关系标识符", "关系标识符", "relationalIdentifier"),
    ],
    'freshAir@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("新风过滤级别", "新风过滤级别", "freshAirFiltrationLevel"),
        ("新风量(m³/h)", "新风量", "freshAirRate"),
        ("部署区域", "部署区域", "freshAir_deployment.deployArea"),
        ("所属机房", "所属机房", "freshAir_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "freshAir_deployment.deployDb"),
        ("所属楼层", "所属楼层", "freshAir_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "freshAir_deployment.deployGallery"),
        ("管理部门", None, "freshAir_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "freshAir_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "freshAir_operationsManagement.serviceEndTime"),
        ("服务级别", None, "freshAir_operationsManagement.serviceLevel"),
        ("服务提供商", None, "freshAir_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "freshAir_operationsManagement.serviceStartTime"),
        ("新风过滤器性能", "新风过滤器性能", "performanceOfFreshAirFilter"),
        ("设备功率(KW)", "设备功率", "ratedPower"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'commonAirCondition@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("普通空调分类", "普通空调分类", "classificationOfGeneralAirConditioning"),
        ("部署区域", "部署区域", "commonAirCondition_deployment.deployArea"),
        ("所属机房", "所属机房", "commonAirCondition_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "commonAirCondition_deployment.deployDb"),
        ("所属楼层", "所属楼层", "commonAirCondition_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "commonAirCondition_deployment.deployGallery"),
        ("管理部门", None, "commonAirCondition_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "commonAirCondition_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "commonAirCondition_operationsManagement.serviceEndTime"),
        ("服务级别", None, "commonAirCondition_operationsManagement.serviceLevel"),
        ("服务提供商", None, "commonAirCondition_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "commonAirCondition_operationsManagement.serviceStartTime"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("设备功率(KW)", "设备功率", "ratedPower"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'rackServer@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", None, "brandLand"),
        ("业务面IP地址", "业务面IP地址", "businessIp"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("CPU设备品牌", "服务器设备品牌", "rackServer_cpu.assetBrand"),
        ("CPU品牌属地", None, "rackServer_cpu.brandLand"),
        ("CPU主频(GHZ)", "CPU主频", "rackServer_cpu.cpuFrequency"),
        ("产品架构", "产品架构", "rackServer_cpu.productArchitecture"),
        ("CPU总个数(个)", "CPU总个数", "rackServer_cpu.totalNumberOfCpu"),
        ("CPU总核数(个)", "CPU总核数", "rackServer_cpu.totalNumberOfCpuNuclear"),
        ("部署区域", "部署区域", "rackServer_deployment.deployArea"),
        ("所属机房", "所属机房", "rackServer_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "rackServer_deployment.deployDb"),
        ("所属楼层", "所属楼层", "rackServer_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "rackServer_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "rackServer_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "rackServer_installationPosition.slotNo"),
        ("本机存储设备品牌", "硬盘设备品牌", "rackServer_localStorage.assetBrand"),
        ("存储总容量(GB)", "存储总容量", "rackServer_localStorage.totalStorageCapacity"),
        ("内存设备品牌", "内存设备品牌", "rackServer_memory.assetBrand"),
        ("内存容量(GB)", "内存容量", "rackServer_memory.memoryCapacity"),
        ("管理部门", None, "rackServer_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "rackServer_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "rackServer_operationsManagement.serviceEndTime"),
        ("服务级别", None, "rackServer_operationsManagement.serviceLevel"),
        ("服务提供商", None, "rackServer_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "rackServer_operationsManagement.serviceStartTime"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("所属系统信息", "所属系统信息", "systemInformation"),
    ],
    'commonCabinet@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("机柜承重(KG)", "机柜承重", "cabinetBearing"),
        ("部署区域", "部署区域", "commonCabinet_deployment.deployArea"),
        ("所属机房", "所属机房", "commonCabinet_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "commonCabinet_deployment.deployDb"),
        ("所属楼层", "所属楼层", "commonCabinet_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "commonCabinet_deployment.deployGallery"),
        ("管理部门", None, "commonCabinet_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "commonCabinet_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "commonCabinet_operationsManagement.serviceEndTime"),
        ("服务级别", None, "commonCabinet_operationsManagement.serviceLevel"),
        ("服务提供商", None, "commonCabinet_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "commonCabinet_operationsManagement.serviceStartTime"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("最大容积(U)", "最大容积", "maximumVolume"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'wdm@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("线路速率", "线路速率", "lineRate"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("网络安全能力", "网络安全能力", "networkSecurityCapability"),
        ("光通路数", "光通路数", "numberOfFibreChannel"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("支持业务类型", "支持业务类型", "supportType"),
        ("波长范围", "波长范围", "wavelengthRange"),
        ("部署区域", "部署区域", "wdm_deployment.deployArea"),
        ("所属机房", "所属机房", "wdm_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "wdm_deployment.deployDb"),
        ("所属楼层", "所属楼层", "wdm_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "wdm_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "wdm_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "wdm_installationPosition.slotNo"),
        ("管理部门", None, "wdm_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "wdm_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "wdm_operationsManagement.serviceEndTime"),
        ("服务级别", None, "wdm_operationsManagement.serviceLevel"),
        ("服务提供商", None, "wdm_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "wdm_operationsManagement.serviceStartTime"),
    ],
    'fireProtection@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("部署区域", "部署区域", "fireProtection_deployment.deployArea"),
        ("所属机房", "所属机房", "fireProtection_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "fireProtection_deployment.deployDb"),
        ("所属楼层", "所属楼层", "fireProtection_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "fireProtection_deployment.deployGallery"),
        ("火灾报警系统", "火灾报警系统", "fireProtection_fireProtection.fireAlarmSystem"),
        ("消防排烟系统", "消防排烟系统", "fireProtection_fireProtection.fireExhaustSystem"),
        ("气体灭火系统", "气体灭火系统", "fireProtection_fireProtection.gasExhaustSystem"),
        ("其它系统", "其它系统", "fireProtection_fireProtection.otherSystems"),
        ("极早期烟感探测系统", "极早期烟感探测系统", "fireProtection_fireProtection.smokeDetectionSystem"),
        ("水喷淋灭火系统", "水喷淋灭火系统", "fireProtection_fireProtection.sprinklerSystem"),
        ("细水雾灭火系统", "细水雾灭火系统", "fireProtection_fireProtection.waterExhaustSystem"),
        ("管理部门", None, "fireProtection_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "fireProtection_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "fireProtection_operationsManagement.serviceEndTime"),
        ("服务级别", None, "fireProtection_operationsManagement.serviceLevel"),
        ("服务提供商", None, "fireProtection_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "fireProtection_operationsManagement.serviceStartTime"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'precisionAirCondition@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("空调制冷量(KW)", "空调制冷量", "classificationOfAirRefrigerationVolume"),
        ("空调送风方式分类", "空调送风方式分类", "classificationOfAirSupplyModes"),
        ("空调回风方式分类", "空调回风方式分类", "classificationOfReturnAirModes"),
        ("冷源系统", "冷源系统", "coldSourceSystem"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("风机形式", "风机形式", "fanType"),
        ("自然冷却", "自然冷却", "naturalCooling"),
        ("室外机形式", "室外机形式", "outdoorUnitType"),
        ("部署区域", "部署区域", "precisionAirCondition_deployment.deployArea"),
        ("所属机房", "所属机房", "precisionAirCondition_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "precisionAirCondition_deployment.deployDb"),
        ("所属楼层", "所属楼层", "precisionAirCondition_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "precisionAirCondition_deployment.deployGallery"),
        ("管理部门", None, "precisionAirCondition_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "precisionAirCondition_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "precisionAirCondition_operationsManagement.serviceEndTime"),
        ("服务级别", None, "precisionAirCondition_operationsManagement.serviceLevel"),
        ("服务提供商", None, "precisionAirCondition_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "precisionAirCondition_operationsManagement.serviceStartTime"),
        ("设备功率(KW)", "设备功率", "ratedPower"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'precisionPower@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        (None, "精密配电设备类型", "precisionPowerDistribution"),
        ("精密配电设备", "精密配电设备类型", "precisionPowerDistribution"),
        ("部署区域", "部署区域", "precisionPower_deployment.deployArea"),
        ("所属机房", "所属机房", "precisionPower_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "precisionPower_deployment.deployDb"),
        ("所属楼层", "所属楼层", "precisionPower_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "precisionPower_deployment.deployGallery"),
        ("管理部门", None, "precisionPower_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "precisionPower_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "precisionPower_operationsManagement.serviceEndTime"),
        ("服务级别", None, "precisionPower_operationsManagement.serviceLevel"),
        ("服务提供商", None, "precisionPower_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "precisionPower_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "precisionPower_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "precisionPower_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "precisionPower_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "precisionPower_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "precisionPower_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "precisionPower_ratedOutputParameter.ratedOutputVoltage"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'networkLine@FINTECHDATA': [
        (None, None, "_diffDetail.reportValue"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("网络线路运营商", "网络线路运营商", "isp"),
        ("线路资费(元/年)", "线路资费", "lineCost"),
        ("线路类型", "线路类型", "lineType"),
        ("线路用途", "线路用途", "lineUsage"),
        ("网络带宽(M)", "网络带宽", "networkBandwidth"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'networkRelation@FINTECHDATA': [
        (None, None, "_diffDetail.reportValue"),
        ("直连网络设备", "直连网络设备", "directConnectionNetAsset"),
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", "归属机构", "facilityOwnershipAgency"),
        ("本端IT设备", "本端IT设备", "localItAsset"),
        ("关系标识符", "关系标识符", "relationalIdentifier"),
    ],
    'virtualMachine@FINTECHDATA': [
        (None, None, "_diffDetail.reportValue"),
        ("所属宿主机", "所属宿主机", "belongsServer"),
        ("虚拟机宿主机分类", "虚拟机宿主机分类", "belongsServerType"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("虚拟CPU信息", "虚拟CPU信息", "virtualMachineCpuInformation"),
        ("虚拟硬盘大小(GB)", "虚拟硬盘大小", "virtualMachineHarddiskSize"),
        ("虚拟内存大小(GB)", "虚拟内存大小", "virtualMachineMemorySize"),
        ("软件平台品牌属地", "软件平台品牌属地", "virtualizationSoftwareBrandLand"),
        ("虚拟化软件平台", "虚拟化软件平台", "virtualizationSoftwarePlatform"),
        ("虚拟机管理平台", "虚拟机管理平台", "vmManagementPlatform"),
    ],
    'videoMonitoring@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("日志存放周期(天)", "日志存放周期", "dataSavePeriod"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("监控范围", "监控范围", "monitoringScope"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("监控摄像头数量", "监控摄像头数量", "surveillanceNumber"),
        ("部署区域", "部署区域", "videoMonitoring_deployment.deployArea"),
        ("所属机房", "所属机房", "videoMonitoring_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "videoMonitoring_deployment.deployDb"),
        ("所属楼层", "所属楼层", "videoMonitoring_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "videoMonitoring_deployment.deployGallery"),
        ("管理部门", None, "videoMonitoring_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "videoMonitoring_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "videoMonitoring_operationsManagement.serviceEndTime"),
        ("服务级别", None, "videoMonitoring_operationsManagement.serviceLevel"),
        ("服务提供商", None, "videoMonitoring_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "videoMonitoring_operationsManagement.serviceStartTime"),
    ],
    'loadBalancing@FINTECHDATA': [
        (None, None, "wirelessFunction"),
    ],
    'router@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("网络安全能力", "网络安全能力", "networkSecurityCapability"),
        ("板卡数量(个)", "板卡数量", "numberOfCards"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("部署区域", "部署区域", "router_deployment.deployArea"),
        ("所属机房", "所属机房", "router_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "router_deployment.deployDb"),
        ("所属楼层", "所属楼层", "router_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "router_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "router_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "router_installationPosition.slotNo"),
        ("管理部门", None, "router_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "router_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "router_operationsManagement.serviceEndTime"),
        ("服务级别", None, "router_operationsManagement.serviceLevel"),
        ("服务提供商", None, "router_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "router_operationsManagement.serviceStartTime"),
        ("IPv6基础协议", "IPv6基础协议", "router_protocol.ipv6BasicProtocol"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("无线功能", "无线功能", "wirelessFunction"),
    ],
    'softwareRelation@FINTECHDATA': [
        ("基础软件关联服务器", "基础软件关联服务器", "FacilityDescriptor"),
        (None, "软件标识符", "SoftwareDescriptor"),
        ("服务器类型标识", "服务器类型标识", "applicationServerType"),
        ("分类标识符", "分类标识符", "facilityCategory"),
        ("归属机构", None, "facilityOwnershipAgency"),   # TMP enum(预置吉林银行枚举)与河南数据不兼容，弃映射
        ("关系标识符", "关系标识符", "relationalIdentifier"),
    ],
    'opsAudit@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("审计内容", "审计内容", "contentOfAudit"),
        ("数据保存", "数据保存", "dataSave"),
        ("存储周期(月)", "存储周期", "dataSavePeriod"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("身份认证模式", "身份认证模式", "identificationPattern"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("部署区域", "部署区域", "opsAudit_deployment.deployArea"),
        ("所属机房", "所属机房", "opsAudit_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "opsAudit_deployment.deployDb"),
        ("所属楼层", "所属楼层", "opsAudit_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "opsAudit_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "opsAudit_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "opsAudit_installationPosition.slotNo"),
        ("管理部门", None, "opsAudit_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "opsAudit_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "opsAudit_operationsManagement.serviceEndTime"),
        ("服务级别", None, "opsAudit_operationsManagement.serviceLevel"),
        ("服务提供商", None, "opsAudit_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "opsAudit_operationsManagement.serviceStartTime"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("安全部署方式", "安全部署方式", "safetydeploymentMode"),
        ("安全销售许可", "安全销售许可", "sellingLicense"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("吞吐率", "吞吐率", "throughputRate"),
    ],
    'entranceGuard@FINTECHDATA': [
        ("门禁系统类型", "门禁系统类型", "accessControlType"),
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("日志存放周期(天)", "日志存放周期", "dataSaveCycle"),
        ("门禁系统", "门禁系统", "entranceGuardSystem"),
        ("部署区域", "部署区域", "entranceGuard_deployment.deployArea"),
        ("所属机房", "所属机房", "entranceGuard_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "entranceGuard_deployment.deployDb"),
        ("所属楼层", "所属楼层", "entranceGuard_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "entranceGuard_deployment.deployGallery"),
        ("管理部门", None, "entranceGuard_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "entranceGuard_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "entranceGuard_operationsManagement.serviceEndTime"),
        ("服务级别", None, "entranceGuard_operationsManagement.serviceLevel"),
        ("服务提供商", None, "entranceGuard_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "entranceGuard_operationsManagement.serviceStartTime"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("备注信息", "备注信息", "remarksInformation"),
    ],
    'firewall@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("支持Bypass功能", "支持Bypass功能", "bypassFunction"),
        ("部署方式", "部署方式", "deploymentMode"),
        ("设备高度(U)", "设备高度", "deviceHeight"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("部署区域", "部署区域", "firewall_deployment.deployArea"),
        ("所属机房", "所属机房", "firewall_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "firewall_deployment.deployDb"),
        ("所属楼层", "所属楼层", "firewall_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "firewall_deployment.deployGallery"),
        ("所属机柜", "所属机柜", "firewall_installationPosition.belongCabinet"),
        ("槽位号", "槽位号", "firewall_installationPosition.slotNo"),
        ("日志存储位置", "日志存储位置", "firewall_log.logLocation"),
        ("存储周期(月)", "存储周期", "firewall_log.storagePeriod"),
        ("管理部门", None, "firewall_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "firewall_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "firewall_operationsManagement.serviceEndTime"),
        ("服务级别", None, "firewall_operationsManagement.serviceLevel"),
        ("服务提供商", None, "firewall_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "firewall_operationsManagement.serviceStartTime"),
        ("IPv6基础协议", "IPv6基础协议", "firewall_protocol.ipv6BasicProtocol"),
        ("吞吐量(Gbps)", "吞吐量", "handlingCapacity"),
        ("影响系统", "影响系统", "influenceSystem"),
        ("管理IP地址", "管理IP地址", "managementIp"),
        ("最大新建连接速率(万个连接每秒)", "最大新建连接速率", "maximumNewConnectionRate"),
        ("最大并发连接数(万个)", "最大并发连接数", "maximumNumberOfConcurrentConnections"),
        ("网络安全能力", "网络安全能力", "networkSecurityCapability"),
        ("板卡数量(个)", "板卡数量", "numberOfCards"),
        ("操作系统版本信息", "操作系统版本信息", "operatingSystemVersionInformation"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("安全功能要求", "安全功能要求", "securityFunction"),
        ("IPV6支持能力", "IPV6支持能力", "supportIpv6"),
        ("无线功能", "无线功能", "wirelessFunction"),
    ],
    'highVoltage@FINTECHDATA': [
        ("设备品牌", "设备品牌", "assetBrand"),
        ("资产编码", "资产编码(可读性标识编码)", "assetCode"),
        ("产品序列号", "产品序列号", "assetSerialNumber"),
        ("设备型号", "设备型号", "assetType"),
        ("资产价值(万元)", "资产价值", "assetValue"),
        ("品牌属地", "品牌属地", "brandLand"),
        ("通信协议", "通信协议", "communicationProtocol"),
        ("设施分类标识符", "设施分类标识符", "facilityCategory"),
        ("设施标识符", "设施标识符", "facilityDescriptor"),
        ("设施名称", "设施名称", "facilityName"),
        ("设施归属机构", "设施归属机构", "facilityOwnershipAgency"),
        (None, "设施信息更新日期", "facilityUpdateDate"),
        ("设施投产日期", "设施投产日期", "facilityUseDate"),
        ("设施在用状态", "设施在用状态", "facilityUseState"),
        ("部署区域", "部署区域", "highVoltage_deployment.deployArea"),
        ("所属机房", "所属机房", "highVoltage_deployment.deployComputerRoom"),
        ("部署数据中心", "部署数据中心", "highVoltage_deployment.deployDb"),
        ("所属楼层", "所属楼层", "highVoltage_deployment.deployFloor"),
        ("所属楼座", "所属楼座", "highVoltage_deployment.deployGallery"),
        ("管理部门", None, "highVoltage_operationsManagement.administrativeDepartment"),
        ("运维部门", None, "highVoltage_operationsManagement.operationDepartment"),
        ("服务截止时间", None, "highVoltage_operationsManagement.serviceEndTime"),
        ("服务级别", None, "highVoltage_operationsManagement.serviceLevel"),
        ("服务提供商", None, "highVoltage_operationsManagement.serviceProvider"),
        ("服务开始时间", None, "highVoltage_operationsManagement.serviceStartTime"),
        ("额定输入电流(A)", "额定输入电流", "highVoltage_ratedInputParameter.ratedInputCurrent"),
        ("额定输入功率(KW)", "额定输入功率", "highVoltage_ratedInputParameter.ratedInputPower"),
        ("额定输入电压(V)", "额定输入电压", "highVoltage_ratedInputParameter.ratedInputVoltage"),
        ("额定输出电流(A)", "额定输出电流", "highVoltage_ratedOutputParameter.ratedOutputCurrent"),
        ("额定输出功率(KW)", "额定输出功率", "highVoltage_ratedOutputParameter.ratedOutputPower"),
        ("额定输出电压(V)", "额定输出电压", "highVoltage_ratedOutputParameter.ratedOutputVoltage"),
        ("额定交变频率", "额定交变频率", "ratedAlternatingFrequency"),
        ("备注信息", "备注信息", "remarksInformation"),
        ("高压成套配电设备类型", "高压成套配电设备类型", "typesOfHighVoltageEquipment"),
    ],
}


# cmdb属性id → {excel侧裸值 → cmdb合法值(regex 中的值)}
# enums(多选)同样查此表；前缀/后缀式裸值（如 设施在用→00-设施在用、主机房-网络区→01-主机房-网络区）
# 由 clean_value 的 regex 前缀归一自动处理，无需逐条列举。
ENUM_MAP = {
    'facilityUseState': {'设施在用': '00-设施在用', '设施已停用': '01-设施已停用',
                         '设施专用于开发或测试': '02-设施专用于开发或测试',
                         '设施已拆除或报废': '03-设施已拆除或报废', '备用设施': '04-备用设施', '其它': '99-其它'},
    # bool 型 enum（regex=['True','False']）的 excel 形态归一
    'supportIpv6':      {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'wirelessFunction': {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'bypass':           {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'bypassFunction':   {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'emergencyPlan':    {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'internetSever':    {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'sellingLicense':   {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'supportDistributed': {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'brandLand':        {'国内': '00-国内', '国外': '01-国外', '其它': '99-其它'},
    # 后缀歧义（多个 regex 值同后缀），显式指定
    'performanceOfFreshAirFilter': {'中效过滤器': '01-中效过滤器'},
    'idsIps_dataSave.dataLocation': {'服务器存储': '01-服务器存储'},
}

RULES = {
    'invalid_values': ['******'],
    'skip_sheets':  ['维修信息'],
    'skip_columns': ['记录ID', '拥有者', '创建者', '创建时间', '最近修改时间', '数据校验结果'],
}

RUN_SH     = '/workspace/.claude/skills/api-orchestrator/scripts/run.sh'
CMDB_SPEC  = '/workspace/.api-orchestrator/platforms/easyops/easyops-cmdb.yaml'
OUT        = Path('/workspace/tmp/fintech-sync/out')

# ============================== 基础层 ==============================
def norm_text(s):
    """比较用归一：去空白、全角括号→半角。"""
    return str(s).replace('（', '(').replace('）', ')').replace('\t', '').strip()

def find_file(side, main_name):
    """side∈{report,mgmt}；report 文件名=<主名>_YYYYMMDDHHMMSS.xlsx，mgmt=<别名>YYYYMMDDHHMMSS.xlsx"""
    alias = main_name
    if side == 'mgmt':
        for k, cfg in MODEL_MAP.items():
            if k == main_name and 'mgmt_alias' in cfg:
                alias = cfg['mgmt_alias']
    # report 侧时间戳 14 位（<主名>_YYYYMMDDHHMMSS）；mgmt 侧实测 17 位（YYYYMMDDHHMMSS+3位毫秒）
    pat = re.compile(re.escape(alias) + r'_?\d{14,17}\.xlsx$')
    for p in sorted(SIDES[side].glob('*.xlsx')):
        if pat.match(p.name):
            return p
    return None

def read_excel_rows(path):
    """读主 sheet（skip_sheets 过滤后的第一个），表头行 1；剔除 skip_columns；返回 [{列名:值}]，空行跳过。"""
    wb = openpyxl.load_workbook(path)
    ws = next(w for w in wb.worksheets if w.title not in RULES['skip_sheets'])
    rows, header = [], None
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        if i == 1:
            header = [norm_text(c) if c is not None else None for c in row]
            continue
        d = {}
        for col, v in zip(header, row):
            if col and col not in RULES['skip_columns']:
                d[col] = v
        if any(v is not None and str(v).strip() for v in d.values()):
            rows.append(d)
    wb.close()
    return rows

def api_cli(resource, verb, *args, body=None, body_file=None, yes=False):
    """调 run.sh（cwd 必须 /workspace）。body=内联 json 串，body_file=文件路径。返回 (rc, stdout, stderr)。"""
    cmd = [RUN_SH, '--spec', CMDB_SPEC, resource, verb] + [str(a) for a in args]
    if body:      cmd += ['--body', body]
    if body_file: cmd += ['--body-file', str(body_file)]
    if yes:       cmd += ['--yes']
    r = subprocess.run(cmd, capture_output=True, text=True, cwd='/workspace')
    return r.returncode, r.stdout, r.stderr

# ============================== investigate ==============================
SCHEMA_CACHE = OUT / 'schema-cache.json'

def _attr_brief(a):
    v = a.get('value') or {}
    brief = {'name': a.get('name'), 'type': v.get('type'), 'regex': v.get('regex') or None}
    # structs 子字段展平为 dotted id（一层；CMDB struct_define 不允许嵌套 struct）
    for sd in v.get('struct_define') or []:
        brief.setdefault('sub', {})[f"{a['id']}.{sd['id']}"] = {
            'name': sd.get('name'), 'type': sd.get('type'), 'regex': sd.get('regex') or None}
    return brief

def fetch_schema(model_id, refresh=False):
    """detail → {attrs:{id|id.sub:{name,type,regex}}, key_attr}；缓存到 out/schema-cache.json"""
    cache = {}
    if SCHEMA_CACHE.exists():
        cache = json.loads(SCHEMA_CACHE.read_text())
    if model_id in cache and not refresh:
        return cache[model_id]
    rc, out, err = api_cli('object_model', 'detail', model_id)
    if rc != 0:
        raise RuntimeError(f'detail {model_id} 失败: {err.strip()[:200]}')
    data = json.loads(out)['data']
    schema = {'attrs': {a['id']: _attr_brief(a) for a in data.get('attrList', [])},
              'key_attr': None}
    # 展平：dotted 子字段并入顶层索引（顶层与子字段名冲突时子字段优先——excel 列语义即 struct 子字段）
    flat = {}
    for aid, a in schema['attrs'].items():
        flat.update(a.pop('sub', {}))
    schema['attrs'].update(flat)
    cfg = next(c for c in MODEL_MAP.values() if c['model_id'] == model_id)
    schema['key_attr'] = resolve_key_attr(schema['attrs'], cfg['key'])
    cache[model_id] = schema
    OUT.mkdir(exist_ok=True)
    SCHEMA_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return schema

def resolve_key_attr(attrs, key_name):
    for aid, a in attrs.items():
        if norm_text(a['name']) == norm_text(key_name):
            return aid
    return None

def _strip_annot(s):
    """去尾部括号注释：'资产价值(万元)'→'资产价值'（循环去嵌套尾注）。"""
    s = norm_text(s)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r'[(（][^()（）]*[)）]$', '', s).strip()
    return s

def match_field_map(schema, report_headers, mgmt_headers):
    """按属性中文名自动配 excel 列（norm 后比较）。匹配优先级：
    1) 精确名（structs 子字段名优先于顶层名——excel 列语义即子字段，如 部署数据中心）
    2) 去尾部括号注释（'板卡数量(个)'→'板卡数量'；仍子字段优先）
    产出三元组骨架 + 未匹配清单。"""
    def name_index():
        sub_idx, top_idx = {}, {}
        for aid, a in schema['attrs'].items():
            idx = sub_idx if '.' in aid else top_idx
            idx.setdefault(norm_text(a['name']), aid)   # 首个胜出，id 排序已定序
        return sub_idx, top_idx
    sub_idx, top_idx = name_index()
    def lookup(h):
        n = norm_text(h)
        if n in sub_idx: return sub_idx[n]
        if n in top_idx: return top_idx[n]
        b = _strip_annot(h)
        if b and b in sub_idx: return sub_idx[b]
        if b and b in top_idx: return top_idx[b]
        return None
    pairs, used_r, used_m = [], set(), set()
    # 子字段优先：dotted 属性先配列（同名时 excel 列语义=struct 子字段）
    ordered = sorted(schema['attrs'].items(),
                     key=lambda kv: ('.' not in kv[0], kv[0]))
    for aid, a in ordered:
        if aid in ('_dataSource', '_diffDetail', 'memo'):
            continue  # CUSTOM 继承属性/差异字段不参与列映射
        n = norm_text(a['name'])
        b = _strip_annot(a['name'])
        def find(headers, used):
            for cand in (n, b):
                if not cand: continue
                hits = [h for h in headers if h not in used and norm_text(h) == cand]
                if not hits:
                    hits = [h for h in headers if h not in used and _strip_annot(h) == cand]
                if hits: return hits[0]
            return None
        rc_ = find(report_headers, used_r)
        mc_ = find(mgmt_headers, used_m)
        if rc_: used_r.add(rc_)
        if mc_: used_m.add(mc_)
        pairs.append((rc_, mc_, aid))
    # 双侧已配列但配到不同属性时去重（一列只归一个属性）：后配的让位
    uh = [h for h in report_headers if h not in used_r and h not in RULES['skip_columns']]
    uh += [h for h in mgmt_headers if h not in used_m and h not in RULES['skip_columns']]
    ua = [aid for r, m, aid in pairs if r is None and m is None]
    return pairs, uh, ua

def build_custom_attrs_body(detail):
    """CUSTOM 缺 _dataSource/_diffDetail 时产出 import body；已全有→None。"""
    ids = {a['id'] for a in detail.get('attrList', [])}
    if {'_dataSource', '_diffDetail'} <= ids:
        return None
    attrs = list(detail['attrList'])
    if '_dataSource' not in ids:
        attrs.append({'id': '_dataSource', 'name': '数据来源',
                      'value': {'type': 'enum', 'regex': ['上报', '管理', '双源', '双源(有差异)'],
                                'default': None, 'mode': 'default'}})
    if '_diffDetail' not in ids:
        attrs.append({'id': '_diffDetail', 'name': '差异明细',
                      'value': {'type': 'struct', 'default': None, 'mode': 'default',
                                'struct_define': [
                                    {'id': 'attr', 'name': '属性ID', 'type': 'str'},
                                    {'id': 'reportValue', 'name': '上报值', 'type': 'str'},
                                    {'id': 'mgmtValue', 'name': '管理值', 'type': 'str'}]}})
    obj = {k: v for k, v in detail.items() if k != 'attrList'}
    obj['attrList'] = attrs
    if 'parentObjectIds' in obj:
        obj.pop('parentObjectId', None)   # 已弃用字段不回写
    return {'object_list': [obj]}

def ensure_custom_attrs():
    rc, out, err = api_cli('object_model', 'detail', 'CUSTOM@FINTECHDATA')
    if rc != 0:
        raise RuntimeError(f'detail CUSTOM@FINTECHDATA 失败: {err.strip()[:200]}')
    body = build_custom_attrs_body(json.loads(out)['data'])
    if body is None:
        return False
    p = OUT / 'custom-attrs-import.json'
    p.write_text(json.dumps(body, ensure_ascii=False))
    rc2, out2, err2 = api_cli('object_model', 'import', body_file=p, yes=True)
    if rc2 != 0:
        raise RuntimeError(f'补建 CUSTOM 属性失败: {err2.strip()[:300]}')
    return True

def investigate():
    OUT.mkdir(exist_ok=True)
    lines, skel = ['# 模型 schema 调研报告', '', '| 模型 | 属性数 | key属性 | 上报表头 | 管理表头 | 未匹配列 | 未匹配属性 |',
                   '|---|---|---|---|---|---|---|'], {}
    key_missing = []
    for main, cfg in sorted(MODEL_MAP.items()):
        schema = fetch_schema(cfg['model_id'])
        if not schema['key_attr']:
            key_missing.append(f"{cfg['model_id']}: 找不到名为「{cfg['key']}」的属性")
        rp, mp = find_file('report', main), find_file('mgmt', main)
        rh = list(read_excel_rows(rp)[0].keys()) if rp else []
        mh = list(read_excel_rows(mp)[0].keys()) if mp else []
        pairs, uh, ua = match_field_map(schema, rh, mh)
        skel[cfg['model_id']] = {'pairs': pairs, 'report_only_cols': [r for r, m, a in pairs if r and not m],
                                 'mgmt_only_cols': [m for r, m, a in pairs if m and not r]}
        lines.append(f"| {cfg['model_id']} | {len(schema['attrs'])} | {schema['key_attr']} "
                     f"| {len(rh)} | {len(mh)} | {uh} | {ua} |")
    created = ensure_custom_attrs()
    lines += ['', f'## CUSTOM 属性', f'_dataSource/_diffDetail: {"本次补建" if created else "已存在"}']
    if key_missing:
        lines += ['', '## ⚠️ key 属性缺失'] + key_missing
    (OUT / 'investigate.md').write_text('\n'.join(lines))
    (OUT / 'config-skeleton.py').write_text(
        '# FIELD_MAP 骨架（investigate 自动生成，人工核对后整体粘贴回 sync.py 的 FIELD_MAP）\n'
        'FIELD_MAP = ' + json.dumps({m: [list(p) for p in v['pairs']] for m, v in skel.items()},
                                    ensure_ascii=False, indent=1))
    print('investigate 完成 →', OUT / 'investigate.md')

# ============================== transform ==============================
def _enum_one(s, attr_id, attr_def, ctx):
    """单枚举值归一：ENUM_MAP → regex 直通 → regex 后缀匹配（去空格；裸值'主机房-网络区'→'01-主机房-网络区'）。"""
    m = ctx['enums'].get(attr_id, {})
    if s in m:
        return m[s]
    rx = attr_def.get('regex')
    if rx:
        if s in rx:
            return s
        squeeze = lambda t: re.sub(r'\s+', '', t)
        hits = [v for v in rx if isinstance(v, str) and v != '其它'
                and (v.endswith(s) or squeeze(v).endswith(squeeze(s)))]
        if len(hits) == 1:
            return hits[0]
    ctx['errors'].append(f'{attr_id}: 枚举值「{s}」不在合法集 {rx} 且 ENUM_MAP 未映射')
    return s

def clean_value(v, attr_id, attr_def, ctx):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s in ctx['invalid'] or s == '' or s == '无':
        return None
    t = attr_def.get('type')
    if t == 'enum':
        return _enum_one(s, attr_id, attr_def, ctx)
    if t == 'enums':
        parts = [p.strip() for p in re.split(r'[,，;；]', s) if p.strip()]
        return ','.join(_enum_one(p, attr_id, attr_def, ctx) for p in parts) or None
    if t == 'float':
        try:
            return float(s)
        except ValueError:
            pass                                      # 非数值保留原串，import 报错可见
    return s

def _nest_set(out, aid, value):
    """dotted id 嵌套展开：'a.b' → out[a][b]=value（transform 中间形态，import 前再组装）。"""
    if '.' in aid:
        head, rest = aid.split('.', 1)
        out.setdefault(head, {})
        if not isinstance(out[head], dict):          # 与顶层属性冲突时 struct 让位
            return
        _nest_set(out[head], rest, value)
    else:
        if value is not None:
            out[aid] = value
        elif aid in out and out[aid] is None:
            del out[aid]                              # None 污染清理

def normalize_row(raw, pairs, side, ctx):
    """excel行 → {cmdb属性id: 值}（dotted id 为嵌套 dict）。单边列（该侧为 None）不产出键。"""
    out = {}
    attrs = ctx.get('_attr', {})                              # {attr_id: 属性定义}
    for rcol, mcol, aid in pairs:
        col = rcol if side == 'report' else mcol
        if col is None:
            continue
        # 按 aid 取单个属性定义传入（而非整个 attrs dict）
        val = clean_value(raw.get(col), aid, attrs.get(aid, {'name': '', 'type': 'str'}), ctx)
        _nest_set(out, aid, val)
    return out

def build_resolve_tables():
    """mgmt 侧编码→语义值 反解表（消除编码体系假差异）：
    - hex2name: 32位实例 hexID → 设施名称（关系端点/宿主机等引用）
    - cat2code: 分类中文短名 → 人行分类编码（facilityCategory 编码统一）
    - org2name: 机构 hex → 机构中文名（facilityOwnershipAgency）
    report 侧编码为准；反解后仍不同源（如 郑州中支 vs 河南省分行）属真口径差异，保留。"""
    hex2name, org2name, cat_code = {}, {}, {}
    mgmt_cat2code = {}
    for main in MODEL_MAP:                               # report 分类编码表
        rp = find_file('report', main)
        if rp:
            rows = read_excel_rows(rp)
            v = rows[0].get('设施分类标识符') or rows[0].get('分类标识符') or rows[0].get('软件分类标识符')
            if v: cat_code[main] = str(v).strip()
    for main in MODEL_MAP:
        mp = find_file('mgmt', main)
        if not mp:
            continue
        for r in read_excel_rows(mp):
            k, name = r.get('设施标识符'), r.get('设施名称')
            if k and name:
                hex2name[str(k).strip()] = str(name).strip()
            h, n = r.get('设施归属机构'), r.get('设施归属机构名称')
            if h and n:
                org2name[str(h).strip()] = str(n).strip()
            cv = r.get('设施分类标识符') or r.get('分类标识符')
            if cv:
                mgmt_cat2code.setdefault(str(cv).strip(), cat_code.get(main))
    # 基础软件分类：mgmt 中文细分名 = report 分类路径末级 → 编码
    bs = find_file('report', '基础软件')
    if bs:
        for r in read_excel_rows(bs):
            c, p = r.get('软件分类标识符'), r.get('基础软件分类')
            if c and p:
                mgmt_cat2code.setdefault(str(p).strip().split('-')[-1], str(c).strip())
    return hex2name, mgmt_cat2code, org2name

RESOLVE_SKIP_COLS = {'设施标识符', '关系标识符', '软件标识符', '应用系统标识符'}   # 键列不反解（否则两侧键错位）
RESOLVE_CAT_COLS = {'设施分类标识符', '分类标识符', '软件分类标识符'}   # 分类反解仅限分类列（防自由文本误伤，如备注恰=分类短名）

def resolve_refs(row, hex2name, cat2code, org2name):
    """mgmt 行值反解：完整匹配索引键才替换。hex 引用（任意列）/分类中文（仅分类列）/机构 hex（任意列）。键列跳过。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, str) and k not in RESOLVE_SKIP_COLS:
            s = v.strip()
            if s in hex2name:              out[k] = hex2name[s]
            elif k in RESOLVE_CAT_COLS and s in cat2code:
                out[k] = cat2code[s]
            elif s in org2name:            out[k] = org2name[s]
            else:                          out[k] = v
        else:
            out[k] = v
    return out

def transform(side):
    assert FIELD_MAP, 'FIELD_MAP 为空：先跑 investigate 并把 out/config-skeleton.py 核对后粘回'
    outdir = OUT / 'transformed' / side
    outdir.mkdir(parents=True, exist_ok=True)
    stats, all_errors = {}, []
    resolver = (lambda raw: raw) if side == 'report' else None
    for main, cfg in sorted(MODEL_MAP.items()):
        p = find_file(side, main)
        if p is None:
            continue                                    # 该侧无此文件（单边模型）
        if side == 'mgmt' and resolver is None:
            tables = build_resolve_tables()             # mgmt 首模型时构建一次
            resolver = lambda raw, t=tables: resolve_refs(raw, *t)
        schema = fetch_schema(cfg['model_id'])
        rows = read_excel_rows(p)
        ctx = {'enums': ENUM_MAP, 'invalid': RULES['invalid_values'],
               'errors': [], '_attr': schema['attrs']}
        unified = [normalize_row(resolver(r), FIELD_MAP[cfg['model_id']], side, ctx) for r in rows]
        (outdir / f"{cfg['model_id'].split('@')[0]}.json").write_text(
            json.dumps(unified, ensure_ascii=False, indent=1))
        stats[cfg['model_id']] = {'rows': len(unified), 'enum_errors': len(ctx['errors'])}
        all_errors += ctx['errors']
    (OUT / f'transform-{side}-errors.json').write_text(json.dumps(all_errors, ensure_ascii=False, indent=1))
    print(f'transform({side}):', json.dumps(stats, ensure_ascii=False)[:400], '... 枚举错误', len(all_errors))
    return stats

# ============================== compare ==============================
DIFF_EXEMPT_ATTRS = {'facilityOwnershipAgency', 'softwareOwnershipAgency', 'softwareCategory'}
# 系统性口径/编码体系差异豁免逐行比较（值仍取上报侧写入）：
# - facilityOwnershipAgency/softwareOwnershipAgency: 上报=本级机构(郑州中支) vs 管理=上级机构(河南省分行)，全员同模式口径差
# - softwareCategory: basedSoftware 已反解（路径末级对照）；application 侧 mgmt 中文细分名无编码对照表（仅 1 个编码 YYGJGXL000）
# 豁免避免 3000+ 行全员"双源(有差异)"淹没真实数据差异。

def _loose_eq(a, b):
    """宽松等值：str 去 'NN-' 编码前缀与空格后比较（'02-Java'=='Java'、'99-其他'=='其他'）。"""
    if not isinstance(a, str) or not isinstance(b, str):
        return str(a) == str(b)
    strip = lambda t: re.sub(r'^\d+-', '', t).replace(' ', '')
    return strip(a) == strip(b)

def _iter_leaves(d, prefix=''):
    """嵌套 dict 展平为 [(dotted_path, value)]（仅 dict 递归；list/标量为叶）。"""
    for k, v in d.items():
        path = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            yield from _iter_leaves(v, path)
        else:
            yield path, v

def merge_model(r_rows, m_rows, key_attr, attr_ids):
    r = {row[key_attr]: row for row in r_rows if row.get(key_attr)}
    m = {row[key_attr]: row for row in m_rows if row.get(key_attr)}
    orphan = [row for row in r_rows + m_rows if not row.get(key_attr)]
    merged, stats = [], {'both_same': 0, 'both_diff': 0, 'report_only': 0, 'mgmt_only': 0}
    plain_attrs = {a.split('.')[0] for a in attr_ids}       # dotted 归并到顶层容器
    for k in sorted(set(r) | set(m), key=str):
        if k in r and k in m:
            row, diffs = {key_attr: k}, []
            for a in sorted(plain_attrs):
                if a == key_attr:
                    continue
                rv, mv = r[k].get(a), m[k].get(a)
                if rv is None and mv is None:
                    continue
                if mv is None or mv == {}:   row[a] = rv
                elif rv is None or rv == {}: row[a] = mv
                else:
                    # 双侧都有：逐叶比较（struct 子字段级差异定位；单侧缺叶不记差异）
                    rl = dict(_iter_leaves(rv, a)) if isinstance(rv, dict) else {a: rv}
                    ml = dict(_iter_leaves(mv, a)) if isinstance(mv, dict) else {a: mv}
                    row[a] = rv
                    for p in sorted(set(rl) & set(ml)):            # 只比双侧都有值的叶
                        if not _loose_eq(rl[p], ml[p]):
                            diffs.append({'attr': p, 'reportValue': str(rl[p]),
                                          'mgmtValue': str(ml[p])})
                if a in DIFF_EXEMPT_ATTRS:
                    diffs = [d for d in diffs if d['attr'] != a]   # 口径豁免：值取上报，不记差异
            row['_dataSource'] = '双源(有差异)' if diffs else '双源'
            row['_diffDetail'] = diffs
            stats['both_diff' if diffs else 'both_same'] += 1
        else:
            src = r if k in r else m
            row = dict(src[k]); row['_dataSource'] = '上报' if k in r else '管理'
            row['_diffDetail'] = []
            stats['report_only' if k in r else 'mgmt_only'] += 1
        merged.append(row)
    return merged, stats, orphan

def compare():
    assert FIELD_MAP, 'FIELD_MAP 为空：先跑 investigate 并把 out/config-skeleton.py 核对后粘回'
    mdir = OUT / 'merged'
    mdir.mkdir(parents=True, exist_ok=True)
    lines = ['# 两源差异报告', '', '| 模型 | 上报 | 管理 | 合并 | 双源一致 | 双源差异 | 仅上报 | 仅管理 | 孤儿 |',
             '|---|---|---|---|---|---|---|---|---|']
    detail_lines, orphans = [], {}
    for main, cfg in sorted(MODEL_MAP.items()):
        mid = cfg['model_id']
        rp, mp_ = OUT / 'transformed/report' / f"{mid.split('@')[0]}.json", OUT / 'transformed/mgmt' / f"{mid.split('@')[0]}.json"
        if not rp.exists() and not mp_.exists():
            continue
        r_rows = json.loads(rp.read_text()) if rp.exists() else []
        m_rows = json.loads(mp_.read_text()) if mp_.exists() else []
        schema = fetch_schema(mid)
        attr_ids = [a for _, _, a in FIELD_MAP[mid]] + ['_dataSource', '_diffDetail']
        merged, stats, orphan = merge_model(r_rows, m_rows, schema['key_attr'], attr_ids)
        (mdir / f"{mid.split('@')[0]}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1))
        if orphan:
            orphans[mid] = orphan
        lines.append(f"| {mid} | {len(r_rows)} | {len(m_rows)} | {len(merged)} | {stats['both_same']} "
                     f"| {stats['both_diff']} | {stats['report_only']} | {stats['mgmt_only']} | {len(orphan)} |")
        for row in merged:                                   # 明细节
            if row.get('_diffDetail'):
                detail_lines.append(f"- **{row.get(schema['key_attr'])}** ({mid})")
                for d in row['_diffDetail']:
                    detail_lines.append(f"  - {d['attr']}: 上报={d['reportValue']} | 管理={d['mgmtValue']}")
    if detail_lines:                                         # 两遍收集：主表连续，明细节分段在后
        lines += [''] + detail_lines
    (OUT / 'orphan.json').write_text(json.dumps(orphans, ensure_ascii=False, indent=1))
    (OUT / 'diff-report.md').write_text('\n'.join(lines))
    print('compare 完成 →', OUT / 'diff-report.md')

# ============================== import ==============================
def _assemble(row, structs_attrs):
    """transform 嵌套 dict → CMDB 实例形态：structs 属性 {a:{b:v}} → [ {b:v} ]（空 struct 剔除）。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, dict):
            if k in structs_attrs and any(x is not None for x in v.values()):
                out[k] = [v]                            # CMDB structs = list[dict]
        else:
            out[k] = v
    return out

def build_import_body(key_attr, rows, structs_attrs=()):
    datas = [{k: v for k, v in _assemble(r, structs_attrs).items() if v not in (None, '', [], {})} for r in rows]
    return {'keys': [key_attr], 'datas': datas}

def run_import(model_id, body_path):
    rc, out, err = api_cli('object_instance', 'import', model_id, body_file=body_path, yes=True)
    if rc != 0:
        return {'code': -1, 'error': err.strip()[:300]}
    return json.loads(out)

def search_total(model_id):
    rc, out, err = api_cli('object_instance', 'search', model_id,
                           body='{"fields":["instanceId"],"page":1,"page_size":1,"ignore_missing_field_error":true}')
    m = re.search(r'"total":(\d+)', err)
    return int(m.group(1)) if m else 0

def import_cmdb(only=None):
    """only=模型id 则只写该模型（试点）；None 全量。body 落盘留审计。"""
    bdir = OUT / 'import-bodies'
    bdir.mkdir(parents=True, exist_ok=True)
    result = {}
    for main, cfg in sorted(MODEL_MAP.items()):
        mid = cfg['model_id']
        if only and mid != only:
            continue
        mp_ = OUT / 'merged' / f"{mid.split('@')[0]}.json"
        if not mp_.exists():
            continue
        rows = json.loads(mp_.read_text())
        schema = fetch_schema(mid)
        structs_attrs = {aid for aid, a in schema['attrs'].items()
                         if '.' not in aid and a['type'] in ('structs', 'struct')}
        bp = bdir / f"{mid.split('@')[0]}.json"
        bp.write_text(json.dumps(build_import_body(schema['key_attr'], rows, structs_attrs), ensure_ascii=False))
        r = run_import(mid, bp)
        d = r.get('data') or {}
        result[mid] = {'merged': len(rows), 'insert': d.get('insert_count'), 'update': d.get('update_count'),
                       'failed': d.get('failed_count'), 'fail_detail': (d.get('data') or [])[:10],
                       'after_total': search_total(mid), 'error': r.get('error')}
        print(mid, result[mid])
    (OUT / 'import-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result

if __name__ == '__main__':
    stage = sys.argv[sys.argv.index('--stage') + 1] if '--stage' in sys.argv else None
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    if stage == 'investigate': investigate()
    elif stage == 'transform': transform('report'); transform('mgmt')
    elif stage == 'compare':   compare()
    elif stage == 'import':    import_cmdb(only=only)
    else: print('usage: sync.py --stage investigate|transform|compare|import [--only <model_id>]')
