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
    '基础软件':             {'model_id': 'basedSoftware@FINTECHDATA',         'key': '设施标识符'},
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
    '数据中心间距':          {'model_id': 'dataCenterSpacing@FINTECHDATA',    'key': '设施标识符'},
    '应用系统':             {'model_id': 'application@FINTECHDATA',          'key': '设施标识符'},
    '供电关联关系':          {'model_id': 'powerSupplyRelation@FINTECHDATA',  'key': '关系标识符'},
    '网络线路':             {'model_id': 'networkLine@FINTECHDATA',           'key': '设施标识符'},
    '网络线路关联关系':       {'model_id': 'networkRelation@FINTECHDATA',     'key': '关系标识符'},
    '应用系统关联关系':       {'model_id': 'applicationRelation@FINTECHDATA', 'key': '关系标识符'},
    '应用系统软件关联关系':    {'model_id': 'applicationSoftRelation@FINTECHDATA','key': '关系标识符'},
    '软件实例关联关系':       {'model_id': 'softwareRelation@FINTECHDATA',    'key': '关系标识符'},
}

# model_id → [(上报列名|None, 管理列名|None, cmdb属性id), ...]
# 初始为空：investigate() 生成骨架（out/config-skeleton.py），人工核对后粘贴此处
FIELD_MAP = {}

# cmdb属性id → {excel侧裸值 → cmdb合法值(regex 中的值)}
ENUM_MAP = {
    'facilityUseState': {'设施在用': '00-设施在用', '设施已停用': '01-设施已停用',
                         '设施专用于开发或测试': '02-设施专用于开发或测试',
                         '设施已拆除或报废': '03-设施已拆除或报废', '备用设施': '04-备用设施', '其它': '99-其它'},
    'supportIpv6':      {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'wirelessFunction': {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'brandLand':        {'国内': '00-国内', '国外': '01-国外', '其它': '99-其它'},
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
    """读主 sheet（第一个），表头行 1；剔除 skip_columns；返回 [{列名:值}]，空行跳过。"""
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
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

if __name__ == '__main__':
    print('use --stage investigate|transform|compare|import')
