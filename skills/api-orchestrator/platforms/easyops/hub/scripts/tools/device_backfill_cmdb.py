# -*- coding: utf-8 -*-
"""
机房设备进出回填CMDB（流程节点 postScript 钩子——验收节点通过时触发）

机房设备进出及上下电审批流程：验收通过后把「设备信息」table 数据回填 CMDB。
回填策略（2026-09-29 用户定案）：
    · sn 号为唯一键全量写入——设备信息【所有属性】都处理：
      名称（按模型 name/deviceName）/ 型号 mdl / 起始U位 startU / 占用U数 occupiedU /
      机柜 rack / 负责人 assetOwner + 待投产项：上/下电 powerAction / 用电位置 powerPosition /
      额定功率 ratedPower / 使用部门关系 useDepartment→_ITSC_DEPARTMENT@EASYOPS
    · 【能力探测】写入字段按目标模型 attrList/relation_list 过滤——投产前模型缺的属性自动跳过
      （不报错不阻断），投产后父模型加上即自动生效，无需改代码
    · 设备类型列是模型元信息（模型中文名），不回填
    · sn 在 CMDB 已有实例 → upsert 更新；查无实例且设备类型可映射 → 在对应子模型新建
    · CMDB 无对应字段的除外（无）——全部列均有映射

入参（平台注入 globals 同名变量）：
    orderInfo    工单全上下文 JSON 串（postScript 注入；formData 三重 JSON）
    order_info   同上，可选——本地/工具执行调试兜底
输出：
    PutStr("report", <逐台回填结果文本>) —— 完整值不截断
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
logger = logging.getLogger('device_backfill')

CMDB_PORT = 8079

# ---- 表单锚点（机房设备进出及上下电审批流程-发起）----
SEC_DEV = 'hhrx99izxm'           # 设备信息 table 容器
F_ACTION = 'hhrx99izy1'          # 上/下电（RADIO）→ powerAction（🔴待投产属性）
F_TYPE = 'devType'               # 设备类型（模型中文名，用于新建时定位模型）
F_NAME = 'hhrx99izxn'            # 设备名称
F_MDL = 'hhrxj4x1kp'             # 设备型号 → mdl
F_DEPT = 'hhrxmwvszt'            # 使用部门 → useDepartment 关系（🔴待投产关系）
F_RACK = 'hhrx99izxw'            # 所属机柜 → rack
F_STARTU = 'hhrx99izxx'          # 起始U位 → startU
F_OCCU = 'hhrxogs2cp'            # 占用U位 → occupiedU
F_POWER_POS = 'hhrxj9i4h5'       # 用电位置 → powerPosition（🔴待投产属性）
F_RATED = 'hhrxjy2wbt'           # 设备额定功率 → ratedPower（🔴待投产属性）
F_SN = 'hhrxk4ooih'              # 设备序列号（唯一键）
F_OPS = 'hhrx99izxs'             # 运维人 → assetOwner

# 名称属性不统一（2026-09-29 .26 实测）：多数网络设备只有 deviceName；刀箱/FC 无名称属性
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
MODEL_TYPE_NAMES = {
    'PHYSICAL_SERVER@ONEMODEL': u'物理服务器', 'SWITCH@ONEMODEL': u'交换机',
    'ROUTER@ONEMODEL': u'路由器', 'FIREWALL@ONEMODEL': u'防火墙',
    'STORAGE@ONEMODEL': u'存储设备', 'LOADBALANCER@ONEMODEL': u'负载均衡器',
    'BLADE_CHASSIS@ONEMODEL': u'刀箱', 'FIBERCHANNEL_SWITCH@ONEMODEL': u'光纤交换机',
    'F5_LB_DEVICE@ONEMODEL': u'F5负载设备', 'SECURITY_DEVICE@ONEMODEL': u'网络安全设备',
    'FIBRE_CHANNEL_SWITCH': u'光纤交换机(FC)',
}
NAME_TO_MODEL = dict((v, k) for k, v in MODEL_TYPE_NAMES.items())
CHILD_MODELS = list(MODEL_TYPE_NAMES.keys())

HOST = '127.0.0.1'
ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')
BASE_HEADERS = {}
_model_cache = {}


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


def cmdb_import(object_id, keys, datas):
    """upsert 实例（POST /object/<id>/instance/_import）。返回 (insert, update, failed, err_text)。"""
    _, resp = http_json('POST', CMDB_PORT, '/object/%s/instance/_import' % object_id,
                        {'keys': keys, 'datas': datas})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        return 0, 0, len(datas), json.dumps(resp, ensure_ascii=False)
    d = resp.get('data') or {}
    errs = []
    for item in (d.get('data') or []):
        if isinstance(item, dict) and item.get('error'):
            errs.append(item.get('error'))
    return d.get('insert_count') or 0, d.get('update_count') or 0, d.get('failed_count') or 0, u'; '.join(errs)


def model_caps(object_id):
    """模型能力探测（GET /object/<id>，带缓存）→ (attrs set, rels set)。
    投产前缺失的属性/关系在此被过滤——代码全量映射，运行时按实有生效（缺失不写不炸）。"""
    if object_id in _model_cache:
        return _model_cache[object_id]
    attrs, rels = set(), set()
    try:
        _, resp = http_json('GET', CMDB_PORT, '/object/%s' % object_id)
        data = resp.get('data') if isinstance(resp, dict) else None
        if isinstance(data, dict):
            for a in (data.get('attrList') or []):
                if a.get('id'):
                    attrs.add(a['id'])
            for r in (data.get('relation_list') or []):
                for k in ('left_id', 'right_id'):
                    if r.get(k):
                        rels.add(r[k])
    except Exception as e:
        logger.warning(u'[model_caps] %s 探测失败: %s', object_id, e)
    _model_cache[object_id] = (attrs, rels)
    return attrs, rels


def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        logger.info(u'[%s] %s', key, value)


def _inst_ids(v):
    """实例控件值（[{instanceId,name}] / dict / str / 混合）→ instanceId 列表。"""
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
                out.append(iid)
        elif isinstance(item, _string_types) and item:
            out.append(item)
    return out


def _s(v):
    """控件值 → 干净字符串。SELECT/RADIO 枚举对象取 .value。"""
    if isinstance(v, dict):
        vv = v.get('value')
        if isinstance(vv, _string_types):
            return vv.strip()
        lv = v.get('label')
        if isinstance(lv, _string_types):
            return lv.strip()
        return ''
    if isinstance(v, _string_types):
        return v.strip()
    return ''


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, _string_types):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return None
    return None


def find_by_sn(sn):
    """跨子模型按 sn 查实例 → (instanceId, object_id, hit_count) 或 None。"""
    total = 0
    for m in CHILD_MODELS:
        try:
            lst = cmdb_search(m, {'sn': sn}, ['instanceId'])
        except Exception as e:
            logger.warning(u'[find_by_sn] %s 查询失败: %s', m, e)
            continue
        total += len(lst)
        if lst:
            return lst[0].get('instanceId') or '', m, total
    return None if total == 0 else ('', '', total)


def parse_form_rows(order_info):
    """orderInfo → 设备信息行列表（formData 三重 JSON；兜底 stepList done 步骤）。"""
    oi = order_info
    if isinstance(oi, _string_types):
        try:
            oi = json.loads(oi)
        except ValueError:
            return []
    if not isinstance(oi, dict):
        return []
    candidates = []
    fd_raw = oi.get('formData')
    if isinstance(fd_raw, _string_types) and fd_raw.strip():
        try:
            candidates.append(json.loads(fd_raw))
        except ValueError:
            pass
    elif isinstance(fd_raw, list):
        candidates.append(fd_raw)
    for step in (oi.get('stepList') or []):
        sfd = step.get('formData') if isinstance(step, dict) else None
        if isinstance(sfd, _string_types) and sfd.strip():
            try:
                candidates.append(json.loads(sfd))
            except ValueError:
                pass
        elif isinstance(sfd, list):
            candidates.append(sfd)
    for form in candidates:
        if not isinstance(form, list):
            continue
        for c in form:
            if isinstance(c, dict) and c.get('key') == SEC_DEV and c.get('values'):
                return [r for r in c['values'] if isinstance(r, dict)]
    return []


def build_row_data(row):
    """工单行 → 回填 data dict（全量列；待投产项由调用方按模型能力过滤）。"""
    data = {'sn': _s(row.get(F_SN))}
    mdl = _s(row.get(F_MDL))
    if mdl:
        data['mdl'] = mdl
    startu = _num(row.get(F_STARTU))
    if startu is not None:
        data['startU'] = startu
    occu = _num(row.get(F_OCCU))
    if occu is not None:
        data['occupiedU'] = occu
    ppos = _s(row.get(F_POWER_POS))
    if ppos:
        data['powerPosition'] = ppos
    rated = _s(row.get(F_RATED))
    if rated:
        data['ratedPower'] = rated
    action = _s(row.get(F_ACTION))
    if action:
        data['powerAction'] = action
    rack_ids = _inst_ids(row.get(F_RACK))
    if rack_ids:
        data['rack'] = rack_ids
    ops_ids = _inst_ids(row.get(F_OPS))
    if ops_ids:
        data['assetOwner'] = ops_ids
    dept_ids = _inst_ids(row.get(F_DEPT))
    if dept_ids:
        data['useDepartment'] = dept_ids
    return data


# 已确认存在于全部子模型的属性/关系（投产验证过）；PENDING_* 为待投产项（探测到才写）
KNOWN_ATTRS = {'sn', 'mdl', 'startU', 'occupiedU'}
KNOWN_RELS = {'rack', 'assetOwner'}
PENDING_ATTRS = {'powerPosition', 'ratedPower', 'powerAction'}
PENDING_RELS = {'useDepartment'}


def filter_by_caps(data, attrs, rels, name_attr, name_val):
    """按模型能力过滤回填字段（投产前缺失自动跳过）+ 名称按模型键写入。
    探测失败（空集）→ 只写已知字段、跳过全部待投产项（宁少写不报错）。"""
    out = {}
    skipped = []
    for k, v in data.items():
        if k in KNOWN_ATTRS:
            out[k] = v
        elif k in KNOWN_RELS:
            if not rels or k in rels:
                out[k] = v
            else:
                skipped.append(k)
        elif k in PENDING_ATTRS:
            if attrs and k in attrs:
                out[k] = v
            else:
                skipped.append(k)
        elif k in PENDING_RELS:
            if rels and k in rels:
                out[k] = v
            else:
                skipped.append(k)
        else:
            out[k] = v
    if name_val and name_attr:
        out[name_attr] = name_val
    return out, skipped


def main():
    _resolve_conn()
    order_info = globals().get('orderInfo') or globals().get('order_info') or ''
    order_info = _to_unicode(order_info)
    rows = parse_form_rows(order_info)
    if not rows:
        put_str('report', u'未解析到设备信息数据（0 行），无需回填。orderInfo.formData=%s' % (order_info[:200] if isinstance(order_info, _string_types) else order_info))
        return 0

    lines = [u'设备回填 CMDB（sn 唯一键全量同步）：共 %d 行' % len(rows)]
    ok_cnt, skip_cnt = 0, 0
    for i, row in enumerate(rows, 1):
        sn = _s(row.get(F_SN))
        name = _s(row.get(F_NAME))
        dev_type = _s(row.get(F_TYPE))
        if not sn:
            skip_cnt += 1
            lines.append(u'  %d. ⚠️ 跳过（无序列号）：%s' % (i, name or u'(无名称)'))
            continue
        data = build_row_data(row)

        found = find_by_sn(sn)
        if found and found[0]:
            object_id = found[1]
            attrs, rels = model_caps(object_id)
            name_attr = NAME_ATTRS.get(object_id)
            final, skipped = filter_by_caps(data, attrs, rels, name_attr, name)
            ins, upd, fail, err = cmdb_import(object_id, ['sn'], [final])
            if fail:
                lines.append(u'  %d. ❌ %s(sn=%s) 更新失败 @%s：%s' % (i, name, sn, object_id, err))
                skip_cnt += 1
            else:
                ok_cnt += 1
                action = u'新建' if ins else u'更新'
                extra = u'（注意：sn 命中 %d 台，取首个）' % found[2] if found[2] > 1 else ''
                skip_note = u'；待投产未写=%s' % u','.join(skipped) if skipped else ''
                lines.append(u'  %d. ✅ %s(sn=%s) %s @%s 字段=%s%s%s' % (
                    i, name, sn, action, object_id,
                    u','.join(sorted(final.keys())), extra, skip_note))
        else:
            object_id = NAME_TO_MODEL.get(dev_type) or ''
            name_attr = NAME_ATTRS.get(object_id) if object_id else None
            if object_id and (name_attr or not name):
                attrs, rels = model_caps(object_id)
                final, skipped = filter_by_caps(data, attrs, rels, name_attr, name)
                ins, upd, fail, err = cmdb_import(object_id, ['sn'], [final])
                if fail:
                    lines.append(u'  %d. ❌ %s(sn=%s) 新建失败 @%s：%s' % (i, name, sn, object_id, err))
                    skip_cnt += 1
                else:
                    ok_cnt += 1
                    skip_note = u'；待投产未写=%s' % u','.join(skipped) if skipped else ''
                    lines.append(u'  %d. ✅ %s(sn=%s) 新建 @%s 字段=%s%s' % (i, name, sn, object_id, u','.join(sorted(final.keys())), skip_note))
            else:
                skip_cnt += 1
                why = u'设备类型无法映射模型' if not object_id else u'该模型无名称属性且无法定位'
                lines.append(u'  %d. ⚠️ 跳过（CMDB 查无此 sn 且%s）：%s(sn=%s)' % (i, why, name, sn))

    lines.append(u'回填完成：成功 %d / 跳过或失败 %d（报告含待投产字段提示）' % (ok_cnt, skip_cnt))
    put_str('report', u'\n'.join(lines))
    return 0


if __name__ == '__main__':
    main()
