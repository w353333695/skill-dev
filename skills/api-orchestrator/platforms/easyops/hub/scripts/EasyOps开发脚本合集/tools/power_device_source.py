# -*- coding: utf-8 -*-
"""
上下电设备选择数据源（表单 componentLoad 钩子）

机房设备进出及上下电审批流程-发起 表单「上下电设备」实例选择控件（MODALSELECT）的数据源：
跨 BASE_ASSET@ONEMODEL（基础硬件设备）全部 11 个子模型拉候选，每行带 instanceId/_object_id
（供联动填充工具反查 CMDB 详情）。

入参（平台注入 globals 同名变量）：
    keyword    搜索关键字，字符串，可选——按 设备名称/型号/序列号/设备类型 过滤；空=全量
输出：
    PutStr("output", <JSON 数组串>) —— 候选行 [{instanceId,_object_id,deviceType,name,mdl,sn}]
运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。
"""
import json
import logging
import os
import sys

IS_PY2 = sys.version_info[0] == 2
if IS_PY2:
    reload(sys)
    sys.setdefaultencoding('utf-8')

try:
    _string_types = (str, unicode)  # noqa: F821
except NameError:
    _string_types = (str,)

if IS_PY2:
    import httplib as _http_client
else:
    import http.client as _http_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('power_device_source')

CMDB_PORT = 8079
PAGE_SIZE = 200
PER_MODEL_CAP = 200          # 单模型候选上限（防大模型刷爆选择器）
TOTAL_CAP = 2000             # 总候选上限

# BASE_ASSET@ONEMODEL（基础硬件设备）全部子模型——设备类型中文名供显示
# 名称属性不统一（2026-09-29 .26 实测）：PHYSICAL_SERVER/STORAGE/FIBERCHANNEL_SWITCH 有 name；
# SWITCH/ROUTER/FIREWALL/LOADBALANCER/F5/SECURITY_DEVICE 只有 deviceName（查 name 报
# "Can not find name relation"）；BLADE_CHASSIS/FIBRE_CHANNEL_SWITCH 两者皆无（用 ip 兜底显示）
NAME_ATTRS = {
    'PHYSICAL_SERVER@ONEMODEL': 'name',
    'SWITCH@ONEMODEL': 'deviceName',
    'ROUTER@ONEMODEL': 'deviceName',
    'FIREWALL@ONEMODEL': 'deviceName',
    'STORAGE@ONEMODEL': 'name',
    'LOADBALANCER@ONEMODEL': 'deviceName',
    'FIBERCHANNEL_SWITCH@ONEMODEL': 'name',
    'F5_LB_DEVICE@ONEMODEL': 'deviceName',
    'SECURITY_DEVICE@ONEMODEL': 'deviceName',
    'BLADE_CHASSIS@ONEMODEL': None,
    'FIBRE_CHANNEL_SWITCH': None,
}
CHILD_MODELS = [
    ('PHYSICAL_SERVER@ONEMODEL', u'物理服务器'),
    ('SWITCH@ONEMODEL', u'交换机'),
    ('ROUTER@ONEMODEL', u'路由器'),
    ('FIREWALL@ONEMODEL', u'防火墙'),
    ('STORAGE@ONEMODEL', u'存储设备'),
    ('LOADBALANCER@ONEMODEL', u'负载均衡器'),
    ('BLADE_CHASSIS@ONEMODEL', u'刀箱'),
    ('FIBERCHANNEL_SWITCH@ONEMODEL', u'光纤交换机'),
    ('F5_LB_DEVICE@ONEMODEL', u'F5负载设备'),
    ('SECURITY_DEVICE@ONEMODEL', u'网络安全设备'),
    ('FIBRE_CHANNEL_SWITCH', u'光纤交换机(FC)'),
]

HOST = '127.0.0.1'
ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')
BASE_HEADERS = {}


def _resolve_conn():
    """服务地址解析：globals 注入变量 > env > 回环兜底（agent 集群真实地址优先）。"""
    global HOST, ORG, USER
    g = globals()
    for var in ('EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_CMDB_HOST'):
        v = g.get(var)
        if isinstance(v, str) and v:
            HOST = v.split(':')[0].strip()
            break
    else:
        for var in ('EASYOPS_CMDB_BACKEND_URL', 'EASYOPS_HOST'):
            v = os.environ.get(var)
            if v:
                HOST = v.replace('http://', '').replace('https://', '').split(':')[0].strip()
                break
    ORG = str(g.get('EASYOPS_ORG') if g.get('EASYOPS_ORG') not in (None, '') else ORG)
    USER = str(g.get('EASYOPS_USER') if g.get('EASYOPS_USER') not in (None, '') else USER)
    BASE_HEADERS.update({'org': ORG, 'user': USER,
                         'Host': 'admin.easyops.local', 'Content-Type': 'application/json'})


def _to_unicode(v):
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v


def http_json(method, path, body=None, timeout=30):
    conn = _http_client.HTTPConnection(HOST, CMDB_PORT, timeout=timeout)
    data = json.dumps(body) if body is not None else None
    try:
        conn.request(method, path, body=data, headers=dict(BASE_HEADERS))
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
    finally:
        conn.close()
    text = raw.decode('utf-8', 'replace')
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def cmdb_search(object_id, fields, page=1, page_size=PAGE_SIZE):
    """POST /v3/object/<id>/instance/_search。返回实例列表。"""
    _, resp = http_json('POST', '/v3/object/%s/instance/_search' % object_id,
                        {'page': page, 'pageSize': page_size, 'fields': fields, 'query': {}})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'[cmdb_search] %s 失败: %s' % (object_id, json.dumps(resp, ensure_ascii=False)))
    data = resp.get('data') or {}
    return data.get('list') or []


def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        logger.info(u'[%s] %s', key, value)


def main():
    _resolve_conn()
    keyword = _to_unicode(globals().get('keyword') or globals().get('Keyword') or '')
    if not isinstance(keyword, _string_types):
        keyword = _string_types[0](keyword)
    keyword = keyword.strip()

    rows = []
    errors = []
    for object_id, type_name in CHILD_MODELS:
        name_attr = NAME_ATTRS.get(object_id)
        fields = ['instanceId', '_object_id', 'mdl', 'sn', 'ip']
        if name_attr:
            fields.append(name_attr)
        try:
            insts = cmdb_search(object_id, fields)
        except Exception as e:
            errors.append(u'%s: %s' % (type_name, e))
            continue
        for ins in insts[:PER_MODEL_CAP]:
            name = u''
            if name_attr:
                name = ins.get(name_attr) or u''
            if not name:
                name = ins.get('ip') or ins.get('sn') or u''
            mdl = ins.get('mdl') or u''
            sn = ins.get('sn') or u''
            row = {'instanceId': ins.get('instanceId') or '',
                   '_object_id': ins.get('_object_id') or object_id,
                   'deviceType': type_name,
                   'name': name, 'mdl': mdl, 'sn': sn}
            if keyword:
                hay = u'%s %s %s %s' % (name, mdl, sn, type_name)
                if keyword not in hay:
                    continue
            rows.append(row)
            if len(rows) >= TOTAL_CAP:
                break
        if len(rows) >= TOTAL_CAP:
            break

    put_str('output', json.dumps(rows, ensure_ascii=False))
    logger.info(u'候选设备 %d 条（关键字=%s，模型错误 %d 个）', len(rows), keyword or u'(空)', len(errors))
    for e in errors:
        logger.warning(u'模型查询失败: %s', e)


if __name__ == '__main__':
    main()
