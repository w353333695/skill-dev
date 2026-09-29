# -*- coding: utf-8 -*-
"""
上下电设备联动填充（表单 onValueChange 钩子）

机房设备进出及上下电审批流程-发起 表单：监听「上下电设备」实例选择控件的值变化，
按选中设备反查 CMDB 详情，合并填充「设备信息」table。

合并策略（2026-09-29 用户定案）：
    · sn 为唯一键对齐行——已有该 sn 的行【只补空】：CMDB 能提供的字段里，行内已填的
      （人工改过）不覆盖；CMDB 没有的字段（上/下电/使用部门/用电位置/设备额定功率）绝不碰
    · 新选中的设备（表内无此 sn）→ 追加新行，自动字段填 CMDB 值，人工字段留空
    · 行内隐藏键 _instanceId/_objectId 始终刷新（回填 CMDB 用）
    · 表内已有但未选中的行不动（不删行）

入参（平台注入 globals 同名变量）：
    formData    整张表单 JSON 串（onValueChange 注入）
    form_data   同上，可选——本地/工具执行调试兜底（formData 未注入时用它）
输出：
    PutStr("formData", <改后整张表单 JSON 串>)——🔴无改动也必须原样回吐（平台协议）
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
logger = logging.getLogger('power_device_fill')

CMDB_PORT = 8079

# ---- 表单锚点（机房设备进出及上下电审批流程-发起）----
SEC_BASE = 'hhrx99izxd'          # 基本信息容器
FIELD_POWER = 'powerDevices'     # 上下电设备控件（本次新增）
SEC_DEV = 'hhrx99izxm'           # 设备信息 table 容器

# 设备信息列 modelField
F_TYPE = 'devType'               # 设备类型（本次新增）
F_NAME = 'hhrx99izxn'            # 设备名称
F_MDL = 'hhrxj4x1kp'             # 设备型号
F_RACK = 'hhrx99izxw'            # 所属机柜（CMDBINSTANCESELECT RACK）
F_STARTU = 'hhrx99izxx'          # 起始U位
F_OCCU = 'hhrxogs2cp'            # 占用U位
F_SN = 'hhrxk4ooih'              # 设备序列号（唯一键）
F_OPS = 'hhrx99izxs'             # 运维人（USER_SELECTOR）
# 人工字段（CMDB 无，绝不写入）：上/下电 hhrx99izy1 / 使用部门 hhrxmwvszt /
# 用电位置 hhrxj9i4h5 / 设备额定功率 hhrxjy2wbt

# BASE_ASSET@ONEMODEL 子模型全集（sn/型号等继承自抽象父模型）
# 名称属性不统一（2026-09-29 .26 实测）：多数网络设备只有 deviceName 无 name
# （查 name 报 "Can not find name relation"）；刀箱/FC 光纤交换机两者皆无（ip 兜底）
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
    'PHYSICAL_SERVER@ONEMODEL', 'SWITCH@ONEMODEL', 'ROUTER@ONEMODEL', 'FIREWALL@ONEMODEL',
    'STORAGE@ONEMODEL', 'LOADBALANCER@ONEMODEL', 'BLADE_CHASSIS@ONEMODEL',
    'FIBERCHANNEL_SWITCH@ONEMODEL', 'F5_LB_DEVICE@ONEMODEL', 'SECURITY_DEVICE@ONEMODEL',
    'FIBRE_CHANNEL_SWITCH',
]
MODEL_TYPE_NAMES = {
    'PHYSICAL_SERVER@ONEMODEL': u'物理服务器', 'SWITCH@ONEMODEL': u'交换机',
    'ROUTER@ONEMODEL': u'路由器', 'FIREWALL@ONEMODEL': u'防火墙',
    'STORAGE@ONEMODEL': u'存储设备', 'LOADBALANCER@ONEMODEL': u'负载均衡器',
    'BLADE_CHASSIS@ONEMODEL': u'刀箱', 'FIBERCHANNEL_SWITCH@ONEMODEL': u'光纤交换机',
    'F5_LB_DEVICE@ONEMODEL': u'F5负载设备', 'SECURITY_DEVICE@ONEMODEL': u'网络安全设备',
    'FIBRE_CHANNEL_SWITCH': u'光纤交换机(FC)',
}

HOST = '127.0.0.1'
ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')
BASE_HEADERS = {}


def _resolve_conn():
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


def cmdb_search(object_id, query, fields):
    _, resp = http_json('POST', '/v3/object/%s/instance/_search' % object_id,
                        {'page': 1, 'pageSize': 50, 'fields': fields, 'query': query})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'[cmdb_search] %s 失败: %s' % (object_id, json.dumps(resp, ensure_ascii=False)))
    return (resp.get('data') or {}).get('list') or []


def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        logger.info(u'[%s] %s', key, value)


def _is_empty(v):
    """空判定：None/空串/空列表/空dict。数字 0 与 False 视为【有值】（U位可为0）。"""
    if v is None:
        return True
    if isinstance(v, _string_types):
        return v.strip() == ''
    if isinstance(v, (list, tuple, dict)):
        return len(v) == 0
    return False


def _norm_inst_list(v):
    """CMDB 关系字段值归一 → [{instanceId, name}]。容忍 dict/str/混合列表/None。"""
    if v is None:
        return []
    if isinstance(v, dict):
        v = [v]
    if isinstance(v, _string_types):
        v = [v]
    out = []
    for item in v:
        if isinstance(item, dict):
            iid = item.get('instanceId') or item.get('id') or ''
            if iid:
                out.append({'instanceId': iid, 'name': item.get('name') or iid})
        elif isinstance(item, _string_types) and item:
            out.append({'instanceId': item, 'name': item})
    return out


def _load_json_maybe(v):
    """字符串尝试二次 parse（值可能被序列化过）。"""
    if isinstance(v, _string_types):
        s = v.strip()
        if s.startswith('[') or s.startswith('{'):
            try:
                return json.loads(s)
            except ValueError:
                return None
        return None
    return v


def parse_selected(value_raw):
    """上下电设备控件值 → 选中行列表（每行至少含 instanceId/_object_id/name/sn 中若干）。"""
    v = _load_json_maybe(value_raw)
    if v is None:
        v = value_raw if isinstance(value_raw, list) else []
    rows = []
    for item in v:
        if isinstance(item, _string_types):
            parsed = _load_json_maybe(item)
            if isinstance(parsed, dict):
                item = parsed
            else:
                continue
        if isinstance(item, dict):
            rows.append({
                'instanceId': item.get('instanceId') or item.get('id') or '',
                '_object_id': item.get('_object_id') or item.get('objectId') or item.get('_objectId') or '',
                'name': item.get('name') or '',
                'sn': item.get('sn') or '',
                'deviceType': item.get('deviceType') or '',
            })
    return rows


def _detail_fields(object_id):
    """按模型拼 search fields（名称属性按模型取 name/deviceName，皆无则不查名称）。"""
    fields = ['mdl', 'sn', 'startU', 'occupiedU', 'rack', 'assetOwner', '_object_id', 'instanceId', 'ip']
    name_attr = NAME_ATTRS.get(object_id)
    if name_attr:
        fields.append(name_attr)
    return fields, name_attr


def _resolve_name(ins, name_attr):
    if name_attr and ins.get(name_attr):
        return ins.get(name_attr)
    return ins.get('ip') or ins.get('sn') or u''


def fetch_device_detail(sel):
    """选中行 → CMDB 实例详情 {name,mdl,sn,startU,occupiedU,rack,assetOwner,_object_id}。
    优先 instanceId 直查；兜底 sn → 名称 跨子模型反查。查不到返 None。"""
    try:
        if sel.get('instanceId') and sel.get('_object_id'):
            fields, name_attr = _detail_fields(sel['_object_id'])
            lst = cmdb_search(sel['_object_id'], {'instanceId': sel['instanceId']}, fields)
            if lst:
                ins = lst[0]
                ins['_resolved_name'] = _resolve_name(ins, name_attr)
                return ins
        if sel.get('sn'):
            for m in CHILD_MODELS:
                fields, name_attr = _detail_fields(m)
                lst = cmdb_search(m, {'sn': sel['sn']}, fields)
                if lst:
                    ins = lst[0]
                    ins['_resolved_name'] = _resolve_name(ins, name_attr)
                    return ins
        if sel.get('name'):
            for m in CHILD_MODELS:
                fields, name_attr = _detail_fields(m)
                if not name_attr:
                    continue
                lst = cmdb_search(m, {name_attr: sel['name']}, fields)
                if lst:
                    ins = lst[0]
                    ins['_resolved_name'] = _resolve_name(ins, name_attr)
                    return ins
    except Exception as e:
        logger.warning(u'[fetch_device_detail] %s 反查失败: %s', sel.get('name') or sel.get('sn'), e)
    return None


def main():
    _resolve_conn()
    raw = globals().get('formData') or globals().get('form_data') or ''
    raw = _to_unicode(raw)
    if isinstance(raw, _string_types):
        raw = raw.strip()
    if not raw:
        put_str('formData', '[]')
        logger.warning(u'formData 未注入且 form_data 兜底为空——原样回吐空表')
        return 0

    try:
        form = json.loads(raw)
    except ValueError:
        put_str('formData', raw)  # 坏串原样回吐，不炸表单
        logger.error(u'formData 非合法 JSON，原样回吐')
        return 0
    if not isinstance(form, list):
        put_str('formData', raw)
        logger.warning(u'formData 非容器数组形态，原样回吐')
        return 0

    # 定位两容器
    sec_base = None
    sec_dev = None
    for c in form:
        if c.get('key') == SEC_BASE:
            sec_base = c
        elif c.get('key') == SEC_DEV:
            sec_dev = c
    if not sec_base or not sec_dev:
        put_str('formData', json.dumps(form, ensure_ascii=False))
        logger.warning(u'未找到容器 %s/%s，原样回吐', SEC_BASE, SEC_DEV)
        return 0

    base_vals = sec_base.get('values') or [{}]
    selected = parse_selected(base_vals[0].get(FIELD_POWER) if base_vals else None)
    if not selected:
        put_str('formData', json.dumps(form, ensure_ascii=False))
        logger.info(u'上下电设备未选中任何实例，原样回吐')
        return 0

    dev_rows = sec_dev.get('values')
    if not isinstance(dev_rows, list):
        dev_rows = []
        sec_dev['values'] = dev_rows

    # 现有行按 sn 建索引（sn 空 → 不参与对齐，视为无键行）
    idx_by_sn = {}
    for i, row in enumerate(dev_rows):
        if isinstance(row, dict):
            sn = row.get(F_SN)
            if isinstance(sn, _string_types) and sn.strip():
                idx_by_sn[sn.strip()] = i

    appended, merged, skipped = 0, 0, 0
    for sel in selected:
        detail = fetch_device_detail(sel)
        if not detail:
            skipped += 1
            logger.warning(u'设备 %s（sn=%s）CMDB 反查不到，跳过', sel.get('name'), sel.get('sn'))
            continue
        sn = detail.get('sn') or sel.get('sn') or ''
        sn = sn.strip() if isinstance(sn, _string_types) else sn
        object_id = detail.get('_object_id') or sel.get('_object_id') or ''
        auto = {
            F_TYPE: MODEL_TYPE_NAMES.get(object_id, sel.get('deviceType') or ''),
            F_NAME: detail.get('_resolved_name') or detail.get('name') or '',
            F_MDL: detail.get('mdl') or '',
            F_RACK: _norm_inst_list(detail.get('rack')),
            F_STARTU: detail.get('startU'),
            F_OCCU: detail.get('occupiedU'),
            F_SN: sn,
            F_OPS: _norm_inst_list(detail.get('assetOwner')),
        }
        pos = idx_by_sn.get(sn) if sn else None
        if pos is not None:
            row = dev_rows[pos]
            for k, v in auto.items():
                if k == F_SN:
                    continue  # 唯一键本身不对齐时已匹配
                if _is_empty(row.get(k)) and not _is_empty(v):
                    row[k] = v
            row['_instanceId'] = detail.get('instanceId') or ''
            row['_objectId'] = object_id
            merged += 1
        else:
            new_row = {}
            for k, v in auto.items():
                if not _is_empty(v):
                    new_row[k] = v
            new_row['_instanceId'] = detail.get('instanceId') or ''
            new_row['_objectId'] = object_id
            dev_rows.append(new_row)
            if sn:
                idx_by_sn[sn] = len(dev_rows) - 1
            appended += 1

    sec_dev['values'] = dev_rows
    put_str('formData', json.dumps(form, ensure_ascii=False))
    logger.info(u'联动填充完成：追加 %d / 补空合并 %d / 反查不到跳过 %d', appended, merged, skipped)
    return 0


if __name__ == '__main__':
    main()
