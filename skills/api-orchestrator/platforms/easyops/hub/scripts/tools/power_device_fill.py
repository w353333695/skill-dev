# -*- coding: utf-8 -*-
"""
上下电设备联动填充（表单 onValueChange 钩子）

机房设备进出及上下电审批流程-发起 表单：监听「上下电设备」实例选择控件的值变化，
按选中设备反查 CMDB 详情，合并填充「设备信息」table。

合并策略（2026-09-29 用户定案）：
    · sn 为唯一键对齐行——已有该 sn 的行【只补空】：行内已填的（人工改过）不覆盖
    · 新选中的设备（表内无此 sn）→ 追加新行，CMDB 能带的字段全带，其余留空
    · 表内已有但未选中的行不动（不删行）
    · 填充目标容器（设备信息段）在 formData 里缺失 → 按 {key,values} 格式构造并回填
      全部选中设备（不跳过）；值来源容器缺失才原样回吐

全量字段映射（2026-09-29 用户要求：设备信息所有属性都处理）：
    · 现有 CMDB 属性/关系直接映射：名称/型号/机柜 rack/起始U位 startU/占用U位 occupiedU/
      序列号 sn/运维人 assetOwner
    · 【待投产属性】（BASE_ASSET 父模型暂无，用户投产后自加，代码按 id 预留）：
      上/下电 powerAction / 用电位置 powerPosition / 额定功率 ratedPower /
      使用部门关系 useDepartment→_ITSC_DEPARTMENT@EASYOPS
    · 运行时按模型 attrList/relation_list 探测——存在才查询/带出，缺失自动跳过（投产前后都跑得通）

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
FIELD_POWER = 'powerDevices'     # 上下电设备控件
SEC_DEV = 'hhrx99izxm'           # 设备信息 table 容器

# 设备信息列 modelField → CMDB 属性/关系 id 全量映射
F_ACTION = 'hhrx99izy1'          # 上/下电（RADIO）→ powerAction（🔴待投产属性）
F_TYPE = 'devType'               # 设备类型（模型中文名，脚本填，不回填 CMDB）
F_NAME = 'hhrx99izxn'            # 设备名称 → name/deviceName（按模型）
F_MDL = 'hhrxj4x1kp'             # 设备型号 → mdl
F_DEPT = 'hhrxmwvszt'            # 使用部门（CMDBINSTANCESELECT）→ useDepartment 关系（🔴待投产关系）
F_RACK = 'hhrx99izxw'            # 所属机柜 → rack 关系
F_STARTU = 'hhrx99izxx'          # 起始U位 → startU
F_OCCU = 'hhrxogs2cp'            # 占用U位 → occupiedU
F_POWER_POS = 'hhrxj9i4h5'       # 用电位置 → powerPosition（🔴待投产属性）
F_RATED = 'hhrxjy2wbt'           # 设备额定功率 → ratedPower（🔴待投产属性）
F_SN = 'hhrxk4ooih'              # 设备序列号 → sn（唯一键）
F_OPS = 'hhrx99izxs'             # 运维人 → assetOwner 关系

CMDB_ATTR_MAP = {
    F_MDL: 'mdl',
    F_STARTU: 'startU',
    F_OCCU: 'occupiedU',
    F_POWER_POS: 'powerPosition',   # 待投产
    F_RATED: 'ratedPower',          # 待投产
    F_ACTION: 'powerAction',        # 待投产
}
CMDB_REL_MAP = {
    F_RACK: 'rack',
    F_OPS: 'assetOwner',
    F_DEPT: 'useDepartment',        # 待投产（→_ITSC_DEPARTMENT@EASYOPS）
}

# BASE_ASSET@ONEMODEL 子模型全集；名称属性不统一（多数网络设备只有 deviceName 无 name，
# 查 name 报 "Can not find name relation"；刀箱/FC 两者皆无，ip 兜底）
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
CHILD_MODELS = list(NAME_ATTRS.keys())
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
_MODEL_CACHE = {}   # object_id → {'attrs': set, 'rels': set}


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


def http_json(method, port, path, body=None, timeout=30):
    conn = _http_client.HTTPConnection(HOST, port, timeout=timeout)
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
    _, resp = http_json('POST', CMDB_PORT, '/v3/object/%s/instance/_search' % object_id,
                        {'page': 1, 'pageSize': 50, 'fields': fields, 'query': query})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'[cmdb_search] %s 失败: %s' % (object_id, json.dumps(resp, ensure_ascii=False)))
    return (resp.get('data') or {}).get('list') or []


def model_caps(object_id):
    """模型能力探测（GET /object/<id>，带缓存）→ {'attrs': set(属性id), 'rels': set(关系id)}。
    投产前缺失的属性/关系在此被过滤——代码全量映射，运行时按实有生效。"""
    if object_id in _MODEL_CACHE:
        return _MODEL_CACHE[object_id]
    caps = {'attrs': set(), 'rels': set()}
    try:
        _, resp = http_json('GET', CMDB_PORT, '/object/%s' % object_id)
        data = resp.get('data') if isinstance(resp, dict) else None
        if isinstance(data, dict):
            for a in (data.get('attrList') or []):
                if a.get('id'):
                    caps['attrs'].add(a['id'])
            # 关系侧：relation_list 含继承关系（如 rack 定义于 BASE_ASSET 但子模型也返回），
            # 双向键都收——设备侧键（right_id，如 rack/assetOwner/useDepartment）是我们用的
            for r in (data.get('relation_list') or []):
                for k in ('left_id', 'right_id'):
                    if r.get(k):
                        caps['rels'].add(r[k])
    except Exception as e:
        logger.warning(u'[model_caps] %s 探测失败（按空能力处理）: %s', object_id, e)
    _MODEL_CACHE[object_id] = caps
    return caps


def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        logger.info(u'[%s] %s', key, value)


def _is_empty(v):
    if v is None:
        return True
    if isinstance(v, _string_types):
        return v.strip() == ''
    if isinstance(v, (list, tuple, dict)):
        return len(v) == 0
    return False


def _norm_inst_list(v):
    """CMDB 关系/实例值 → 控件值列表。【全属性保留】（2026-09-29 用户定：CMDB 实例
    全部属性都回填，不影响前端渲染）——dict 有 instanceId 原样保留（nickname/user_tel/
    show_key 等全字段都在，frontKey 任取都能显示）；str/异常形态才补最小集。"""
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
                # 原样保留完整实例对象（只确保 instanceId 存在）
                item = dict(item)
                item.setdefault('instanceId', iid)
                item.setdefault('name', item.get('name') or iid)
                out.append(item)
        elif isinstance(item, _string_types) and item:
            out.append({'instanceId': item, 'name': item})
    return out


def _load_json_maybe(v):
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
    """上下电设备控件值 → 选中行列表。"""
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


def _detail_fields(object_id, caps):
    """按模型能力拼 search fields（属性在 attrList、关系在 rels 才带）。"""
    fields = ['instanceId', 'ip']
    name_attr = NAME_ATTRS.get(object_id)
    if name_attr and (name_attr in caps['attrs'] or not caps['attrs']):
        fields.append(name_attr)
    for field_key, cmdb_id in CMDB_ATTR_MAP.items():
        if not caps['attrs'] or cmdb_id in caps['attrs']:
            fields.append(cmdb_id)
    for field_key, cmdb_id in CMDB_REL_MAP.items():
        if not caps['rels'] or cmdb_id in caps['rels']:
            fields.append(cmdb_id)
    # 去重保序
    seen = set()
    out = []
    for f in fields:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out, name_attr


def _resolve_name(ins, name_attr):
    if name_attr and ins.get(name_attr):
        return ins.get(name_attr)
    return ins.get('ip') or ins.get('sn') or u''


def fetch_device_detail(sel):
    """选中行 → CMDB 实例详情（带 _resolved_name）。优先 instanceId 直查；兜底 sn → 名称。"""
    try:
        if sel.get('instanceId') and sel.get('_object_id'):
            caps = model_caps(sel['_object_id'])
            fields, name_attr = _detail_fields(sel['_object_id'], caps)
            lst = cmdb_search(sel['_object_id'], {'instanceId': sel['instanceId']}, fields)
            if lst:
                ins = lst[0]
                ins['_resolved_name'] = _resolve_name(ins, name_attr)
                ins['_caps'] = caps
                return ins
        if sel.get('sn'):
            for m in CHILD_MODELS:
                caps = model_caps(m)
                fields, name_attr = _detail_fields(m, caps)
                lst = cmdb_search(m, {'sn': sel['sn']}, fields)
                if lst:
                    ins = lst[0]
                    ins['_resolved_name'] = _resolve_name(ins, name_attr)
                    ins['_caps'] = caps
                    return ins
        if sel.get('name'):
            for m in CHILD_MODELS:
                name_attr = NAME_ATTRS.get(m)
                if not name_attr:
                    continue
                lst = cmdb_search(m, {name_attr: sel['name']}, ['instanceId'])
                if lst:
                    caps = model_caps(m)
                    fields, na2 = _detail_fields(m, caps)
                    lst = cmdb_search(m, {'instanceId': lst[0].get('instanceId')}, fields)
                    if lst:
                        ins = lst[0]
                        ins['_resolved_name'] = _resolve_name(ins, na2)
                        ins['_caps'] = caps
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
        put_str('formData', raw)
        logger.error(u'formData 非合法 JSON，原样回吐')
        return 0
    if not isinstance(form, list):
        put_str('formData', raw)
        logger.warning(u'formData 非容器数组形态，原样回吐')
        return 0

    # 定位容器：值来源缺失→回吐；填充目标缺失→构造（2026-09-29 用户纠偏：不跳过）
    sec_base = None
    sec_dev = None
    for c in form:
        if c.get('key') == SEC_BASE:
            sec_base = c
        elif c.get('key') == SEC_DEV:
            sec_dev = c
    if not sec_base:
        put_str('formData', json.dumps(form, ensure_ascii=False))
        logger.warning(u'值来源容器 %s 不存在（无从取选中值），原样回吐', SEC_BASE)
        return 0
    if not sec_dev:
        sec_dev = {'key': SEC_DEV, 'values': []}
        form.append(sec_dev)
        logger.info(u'目标容器 %s 不存在，按格式构造并回填全部数据', SEC_DEV)

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
        caps = detail.get('_caps') or {'attrs': set(), 'rels': set()}
        object_id = detail.get('_object_id') or sel.get('_object_id') or ''

        # 全量 auto 映射（能力过滤后）
        auto = {
            F_TYPE: MODEL_TYPE_NAMES.get(object_id, sel.get('deviceType') or ''),
            F_NAME: detail.get('_resolved_name') or '',
        }
        for field_key, cmdb_id in CMDB_ATTR_MAP.items():
            if caps['attrs'] and cmdb_id not in caps['attrs']:
                continue
            v = detail.get(cmdb_id)
            if field_key == F_ACTION and not _is_empty(v):
                # RADIO 枚举值包装 {key,label,value}（items 未配置时自等值包装）
                v = {'key': v, 'label': v, 'value': v} if not isinstance(v, dict) else v
            auto[field_key] = v
        for field_key, cmdb_id in CMDB_REL_MAP.items():
            if caps['rels'] and cmdb_id not in caps['rels']:
                continue
            auto[field_key] = _norm_inst_list(detail.get(cmdb_id))

        sn = detail.get('sn') or sel.get('sn') or ''
        sn = sn.strip() if isinstance(sn, _string_types) else sn
        auto[F_SN] = sn
        pos = idx_by_sn.get(sn) if sn else None
        if pos is not None:
            row = dev_rows[pos]
            for k, v in auto.items():
                if k == F_SN:
                    continue
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
