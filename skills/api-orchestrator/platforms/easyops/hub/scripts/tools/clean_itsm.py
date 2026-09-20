#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：清理ITSM（按服务删除工单/服务/流程/表单）

入参：
    itsm_service    ITSM 服务实例（cmdbInstance 选择，必填）
    clean_scope     清理范围（enum 多选：工单/服务/流程/表单，必填，默认 工单）

逻辑（按依赖顺序）：
    ① 工单：查该服务全部工单 → running/done/closed 先作废(cancel)再删；已作废直删
    ② 服务：删服务实例（须工单已清空；内置服务不可删）
    ③ 流程：查引用保护——其他服务也绑了该流程则跳过；否则解绑表单→删版本→删定义
    ④ 表单：查引用保护——其他流程版本还绑着该表单则跳过；否则删版本→删表单

保护规则（用户要求：流程/表单删除须考虑多服务/多流程绑定）：
    · 流程：associatedProcess 指向它的服务 >1（含目标服务已删后仍剩其他）→ 跳过并提示
    · 表单：ITSC_PROCESS_FORM_RELATION 里绑它的流程版本，属其他流程定义 → 跳过并提示

运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。沙箱运行。
"""
import json
import logging
import os
import sys
import time

IS_PY2 = sys.version_info[0] == 2

try:
    _string_types = (str, unicode)  # noqa: F821  (py2)
except NameError:
    _string_types = (str,)          # py3

if IS_PY2:
    import httplib as _http_client
else:
    import http.client as _http_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('clean_itsm')

FLOWABLE_PORT = 8134
CMDB_PORT = 8079


def _default_host():
    for var in ('EASYOPS_CMDB_BACKEND_URL', 'EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_HOST'):
        v = os.environ.get(var, '')
        if v:
            return v.replace('http://', '').replace('https://', '').split(':')[0].strip()
    return '192.168.110.26'


HOST = _default_host()
ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')
BASE_HEADERS = {}


def _to_unicode(v):
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v


def _resolve_conn():
    global HOST, ORG, USER
    g = globals()
    for var in ('EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_CMDB_HOST'):
        v = g.get(var)
        if isinstance(v, str) and v:
            HOST = v.split(':')[0].strip()
            break
    ORG = str(g.get('EASYOPS_ORG') if g.get('EASYOPS_ORG') not in (None, '') else ORG)
    USER = str(g.get('EASYOPS_USER') if g.get('EASYOPS_USER') not in (None, '') else USER)
    BASE_HEADERS.update({'org': ORG, 'user': USER,
                         'Host': 'admin.easyops.local', 'Content-Type': 'application/json'})


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


def put_str(message):
    logger.info(message)
    sys.stdout.flush()


def ok_resp(status, resp):
    return status in (200, 204) and (not isinstance(resp, dict) or resp.get('code') in (0, None))


# ---------------------------------------------------------------------------
# 入参
# ---------------------------------------------------------------------------
def parse_args(argv):
    service_ids = []
    scopes = [u'工单']
    g = globals()

    # itsm_service：cmdbInstance 入参注入（平台形态：list[{instanceId,...}] 或 id 串）
    raw = g.get('itsm_service') or g.get('itsmService') or ''
    if isinstance(raw, (list, tuple)):
        for it in raw:
            if isinstance(it, dict):
                iid = (it.get('instanceId') or '').strip()
                if iid:
                    service_ids.append(iid)
            elif _to_unicode(it).strip():
                service_ids.append(_to_unicode(it).strip())
    elif isinstance(raw, _string_types) and raw.strip():
        service_ids = [x.strip() for x in raw.split(',') if x.strip()]

    # clean_scope：enum 多选（平台形态：list 或逗号串）
    # dry_run：枚举 是/否（字符串"否"是 truthy——bool("否")=True 坑！按值判断）
    _dr = _to_unicode(g.get('dry_run') or g.get('dryRun') or '')
    if isinstance(_dr, bool):
        dry_run = _dr
    elif _dr in (u'是', 'true', 'True', '1', True):
        dry_run = True
    else:
        dry_run = False
    raw = g.get('clean_scope') or g.get('cleanScope') or ''
    if isinstance(raw, (list, tuple)):
        scopes = [_to_unicode(x).strip() for x in raw if _to_unicode(x).strip()]
    elif isinstance(raw, _string_types) and raw.strip():
        scopes = [x.strip() for x in raw.split(',') if x.strip()]
    if not scopes:
        scopes = [u'工单']
    return service_ids, scopes, dry_run


# ---------------------------------------------------------------------------
# ① 工单清理（作废→删除）
# ---------------------------------------------------------------------------
def list_service_tickets(service_id):
    """按服务查工单——专用端点 /v1/service/{id}/ticket_list（v4 filter 的 serviceId
    过滤有 operator 陷阱：只认 =~，传 == 被静默丢弃=全量返回，2026-09-20 误删事故根因）。
    返回后再逐张 CMDB 校验 serviceId 归属（双保险）。"""
    out, page = [], 1
    while page <= 200:
        status, resp = http_json('POST', FLOWABLE_PORT,
                                 '/api/flowable_service/v1/service/%s/ticket_list' % service_id,
                                 {'page': page, 'pageSize': 100})
        if not ok_resp(status, resp):
            put_str(u'查工单失败: HTTP %s %s' % (status, resp))
            return out
        data = resp.get('data') or {}
        lst = data.get('list') or []
        out.extend(lst)
        total = int(data.get('total') or 0)
        if not lst or len(out) >= total or page >= 200:
            break
        page += 1
    # 双保险：逐张校验 serviceId 归属（防端点异常返回全量）
    verified = []
    for t in out:
        tid = t.get('instanceId') or ''
        if not tid:
            continue
        s2, r2 = http_json('POST', CMDB_PORT, '/v3/object/_ITSC_PROCESS_INSTANCE/instance/_search', {
            'fields': ['instanceId', 'serviceId'], 'page': 1, 'page_size': 1,
            'query': {'instanceId': tid}})
        lst2 = (r2.get('data') or {}).get('list') or [] if isinstance(r2, dict) else []
        if lst2 and lst2[0].get('serviceId') == service_id:
            verified.append(t)
        else:
            put_str(u'  跳过非本服务工单 %s（归属校验失败）' % t.get('orderNum'))
    return verified


def clean_tickets(service_id, dry_run=False):
    tickets = list_service_tickets(service_id)
    put_str(u'[%s] 工单数: %d%s' % (service_id, len(tickets), u'（dry_run 仅列出）' if dry_run else ''))
    if dry_run:
        for t in tickets[:20]:
            put_str(u'  [dry] %s %s %s' % (t.get('orderNum'), t.get('status'), (t.get('name') or '')[:30]))
        if len(tickets) > 20:
            put_str(u'  ... 共 %d 张' % len(tickets))
        return 0, 0
    done = skip = 0
    for t in tickets:
        tid = t.get('instanceId') or ''
        if not tid:
            continue
        cancelled = t.get('isCancelled')
        # 非 running 且未作废（done/closed/挂起）→ 先作废
        if not cancelled:
            s, r = http_json('PUT', FLOWABLE_PORT, '/api/flowable_service/v1/process_instance_state', {
                'instanceIds': tid, 'action': 'cancel', 'memo': u'清理ITSM工具作废'})
            if not ok_resp(s, r):
                put_str(u'  作废失败 %s(%s): %s' % (t.get('orderNum'), tid, (r.get('error') if isinstance(r, dict) else r)))
                skip += 1
                continue
        s, r = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/process_instance/%s' % tid)
        if ok_resp(s, r):
            done += 1
        else:
            skip += 1
            put_str(u'  删除失败 %s: %s' % (t.get('orderNum'), (r.get('error') if isinstance(r, dict) else r)))
    put_str(u'[%s] 工单清理: 删除 %d 跳过 %d' % (service_id, done, skip))
    return done, skip


# ---------------------------------------------------------------------------
# ② 服务删除
# ---------------------------------------------------------------------------
def delete_service(service_id):
    s, r = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/service_instance/%s' % service_id)
    if ok_resp(s, r):
        put_str(u'[%s] 服务已删除' % service_id)
        return True
    put_str(u'[%s] 服务删除失败: %s' % (service_id, (r.get('error') if isinstance(r, dict) else r)))
    return False


# ---------------------------------------------------------------------------
# ③ 流程删除（多服务绑定保护）
# ---------------------------------------------------------------------------
def get_service_detail(service_id):
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/service_instance/%s' % service_id)
    if ok_resp(s, r):
        return r.get('data') or {}
    return {}


def find_other_services_on_process(process_def_id, exclude_service_id):
    """绑同一流程定义的其他服务（保护判断）。"""
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/service_instance?catalogID=&page=1&pageSize=500')
    others = []
    if ok_resp(s, r):
        for it in (r.get('data') or {}).get('list') or []:
            ap = it.get('associatedProcess') or {}
            if ap.get('instanceId') == process_def_id and it.get('instanceId') != exclude_service_id:
                others.append(it.get('name') or it.get('instanceId'))
    return others


def clean_process(service_id):
    detail = get_service_detail(service_id)
    ap = detail.get('associatedProcess') or {}
    def_id = ap.get('instanceId') or ''
    if not def_id:
        put_str(u'[%s] 未取到关联流程，跳过流程清理' % service_id)
        return False
    put_str(u'[%s] 关联流程: %s(%s)' % (service_id, ap.get('name'), def_id))
    # 保护：其他服务也绑了该流程
    others = find_other_services_on_process(def_id, service_id)
    if others:
        put_str(u'  ⚠️流程被其他服务绑定(%s)，跳过删除' % ','.join(others))
        return False
    # 删版本（版本被表单绑定时逐个解绑）
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/definition/%s/version?page=1&pageSize=100' % def_id)
    versions = []
    if ok_resp(s, r):
        for v in (r.get('data') or {}).get('list') or []:
            vi = v.get('versionInfo') or v
            if vi.get('vInstanceId') or vi.get('instanceId'):
                versions.append(vi.get('vInstanceId') or vi.get('instanceId'))
    for vid in versions:
        # 版本绑定的表单先解绑（否则『当前流程已有绑定表单，不可删除』）
        s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v2/definition/%s/version/%s' % (def_id, vid))
        form_ids = set()
        if ok_resp(s2, r2):
            for t in (r2.get('data') or {}).get('taskInfo') or []:
                fi = t.get('formInfo') or {}
                if fi.get('relationId') and fi.get('formId'):
                    form_ids.add((fi.get('formId'), fi.get('relationId'), (t.get('node') or {}).get('id')))
        for form_id, rel_id, utid in form_ids:
            s3, r3 = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v1/process/version/%s' % vid, {
                'userTaskId': utid, 'useFormBuilder': False,
                'formRelationInstanceId': rel_id})     # relId 非空 + formId 空 = 解绑
            put_str(u'  解绑表单 %s@%s: %s' % (form_id, vid, 'OK' if ok_resp(s3, r3) else '失败'))
        s4, r4 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/definition/%s/version/%s' % (def_id, vid))
        put_str(u'  删流程版本 %s: %s' % (vid, 'OK' if ok_resp(s4, r4) else (r4.get('error') if isinstance(r4, dict) else r4)))
    # 删定义（版本清光后幂等成功/级联已删）
    s5, r5 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/process_definition/%s' % def_id)
    put_str(u'[%s] 流程定义删除: %s' % (def_id, 'OK' if ok_resp(s5, r5) else (r5.get('error') if isinstance(r5, dict) else r5)))
    return ok_resp(s5, r5)


# ---------------------------------------------------------------------------
# ④ 表单删除（多流程绑定保护）
# ---------------------------------------------------------------------------
def find_forms_of_process(def_id):
    """流程各版本绑定的表单 id 集合。"""
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/definition/%s/version?page=1&pageSize=100' % def_id)
    form_ids = set()
    if ok_resp(s, r):
        for v in (r.get('data') or {}).get('list') or []:
            vi = v.get('versionInfo') or v
            vid = vi.get('vInstanceId') or vi.get('instanceId')
            if not vid:
                continue
            s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v2/definition/%s/version/%s' % (def_id, vid))
            if ok_resp(s2, r2):
                for t in (r2.get('data') or {}).get('taskInfo') or []:
                    fi = t.get('formInfo') or {}
                    if fi.get('formId'):
                        form_ids.add(fi.get('formId'))
    return form_ids


def find_other_processes_on_form(form_id, exclude_def_id):
    """其他流程定义也绑了该表单（保护判断）——扫全部表单关系按 formVersion 归属。"""
    others = []
    s, r = http_json('POST', CMDB_PORT, '/v3/object/_ITSC_PROCESS_FORM_RELATION/instance/_search', {
        'fields': ['instanceId', 'userTaskId', 'ITSC_PROCESS_VERSION'],
        'page': 1, 'page_size': 500})
    if not ok_resp(s, r):
        return None                                   # 查询失败按未知处理
    # 关系实例上无 formId 直查——改经 form_version.list 反查太重；用 form.list 的 processVersions
    return others


def clean_forms(service_id):
    detail = get_service_detail(service_id)
    ap = detail.get('associatedProcess') or {}
    def_id = ap.get('instanceId') or ''
    if not def_id:
        put_str(u'[%s] 未取到关联流程，跳过表单清理' % service_id)
        return False
    form_ids = find_forms_of_process(def_id)
    if not form_ids:
        put_str(u'[%s] 流程未绑定表单，跳过' % service_id)
        return False
    # 保护：查每个表单被哪些流程引用（form.list 的 processVersions 字段）
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form?page=1&pageSize=500')
    form_refs = {}
    if ok_resp(s, r):
        for f in (r.get('data') or {}).get('list') or []:
            fid = f.get('instanceId')
            if fid in form_ids:
                lv = f.get('lastestMainVersion') or {}
                pvs = []
                s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version?page=1&pageSize=50' % fid)
                if ok_resp(s2, r2):
                    for v in (r2.get('data') or {}).get('list') or []:
                        vi = v.get('versionInfo') or v
                        for p in (v.get('processVersions') or []):
                            pid = p.get('instanceId') if isinstance(p, dict) else p
                            if pid and pid != def_id:
                                pvs.append(pid)
                form_refs[fid] = pvs
    deleted = skipped = 0
    for fid in form_ids:
        others = form_refs.get(fid) or []
        if others:
            put_str(u'  ⚠️表单 %s 被其他流程绑定(%s)，跳过' % (fid, ','.join(others)))
            skipped += 1
            continue
        # 删各版本（版本被流程节点引用会拒——流程已在③删或同批删）
        s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version?page=1&pageSize=100' % fid)
        vids = []
        if ok_resp(s2, r2):
            for v in (r2.get('data') or {}).get('list') or []:
                vi = v.get('versionInfo') or v
                if vi.get('instanceId'):
                    vids.append(vi.get('instanceId'))
        vdone = 0
        for vid in vids:
            s3, r3 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version/%s' % (fid, vid))
            if ok_resp(s3, r3):
                vdone += 1
            else:
                put_str(u'  删表单版本 %s: %s' % (vid, (r3.get('error') if isinstance(r3, dict) else r3)))
        # 删 form（版本清光后幂等/级联）
        s4, r4 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s' % fid)
        if ok_resp(s4, r4):
            deleted += 1
            put_str(u'  表单 %s 已删（版本 %d）' % (fid, vdone))
        else:
            skipped += 1
            put_str(u'  删表单 %s: %s' % (fid, (r4.get('error') if isinstance(r4, dict) else r4)))
    put_str(u'[%s] 表单清理: 删除 %d 跳过 %d' % (service_id, deleted, skipped))
    return deleted > 0


# ---------------------------------------------------------------------------
def main(argv=None):
    _resolve_conn()
    service_ids, scopes, dry_run = parse_args(argv if argv is not None else sys.argv[1:])
    if not service_ids:
        put_str(u'缺少必填入参 itsm_service（ITSM 服务实例），退出')
        return 1
    put_str(u'服务: %s | 清理范围: %s | dry_run: %s' % (','.join(service_ids), ','.join(scopes), dry_run))
    for sid in service_ids:
        # 🔴删服务前先缓存关联流程/表单（服务删除后 get_service_detail 404）
        detail = get_service_detail(sid)
        ap = detail.get('associatedProcess') or {}
        def_id = ap.get('instanceId') or ''
        cached_forms = find_forms_of_process(def_id) if def_id else set()
        if u'工单' in scopes:
            clean_tickets(sid, dry_run)
        if u'服务' in scopes:
            if dry_run:
                put_str(u'[dry] 跳过服务删除 %s' % sid)
            else:
                delete_service(sid)
        # 流程/表单清理（用缓存信息；顺序：工单→服务→流程→表单）
        if u'流程' in scopes and def_id:
            if dry_run:
                others = find_other_services_on_process(def_id, sid)
                put_str(u'[dry] 流程清理 %s(%s)：%s' % (
                    ap.get('name'), def_id,
                    u'⚠️被其他服务绑定(%s)将跳过' % ','.join(others) if others else u'将删除（版本+定义）'))
            else:
                _clean_process_with_cache(sid, def_id, ap.get('name'))
        if u'表单' in scopes and def_id:
            if dry_run:
                for f in cached_forms:
                    put_str(u'[dry] 表单清理 %s：将删除（版本+表单）' % f)
                if not cached_forms:
                    put_str(u'[dry] 表单清理：流程未绑定表单')
            else:
                _clean_forms_with_cache(sid, def_id, cached_forms)
    put_str(u'清理完成')
    return 0


def _clean_process_with_cache(service_id, def_id, def_name):
    """流程删除（def_id 由调用方缓存——服务可能已删）。"""
    put_str(u'[%s] 关联流程: %s(%s)' % (service_id, def_name, def_id))
    others = find_other_services_on_process(def_id, service_id)
    if others:
        put_str(u'  ⚠️流程被其他服务绑定(%s)，跳过删除' % ','.join(others))
        return False
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/definition/%s/version?page=1&pageSize=100' % def_id)
    versions = []
    if ok_resp(s, r):
        for v in (r.get('data') or {}).get('list') or []:
            vi = v.get('versionInfo') or v
            vid = vi.get('vInstanceId') or vi.get('instanceId')
            if vid:
                versions.append(vid)
    for vid in versions:
        s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v2/definition/%s/version/%s' % (def_id, vid))
        binds = set()
        if ok_resp(s2, r2):
            for t in (r2.get('data') or {}).get('taskInfo') or []:
                fi = t.get('formInfo') or {}
                if fi.get('relationId') and fi.get('formId'):
                    binds.add((fi.get('formId'), fi.get('relationId'), (t.get('node') or {}).get('id')))
        for form_id, rel_id, utid in binds:
            s3, r3 = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v1/process/version/%s' % vid, {
                'userTaskId': utid, 'useFormBuilder': False, 'formRelationInstanceId': rel_id})
            put_str(u'  解绑表单 %s@%s: %s' % (form_id, vid, 'OK' if ok_resp(s3, r3) else '失败'))
        s4, r4 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/definition/%s/version/%s' % (def_id, vid))
        put_str(u'  删流程版本 %s: %s' % (vid, 'OK' if ok_resp(s4, r4) else (r4.get('error') if isinstance(r4, dict) else r4)))
    s5, r5 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/process_definition/%s' % def_id)
    put_str(u'[%s] 流程定义删除: %s' % (def_id, 'OK' if ok_resp(s5, r5) else (r5.get('error') if isinstance(r5, dict) else r5)))
    return ok_resp(s5, r5)


def _clean_forms_with_cache(service_id, def_id, form_ids):
    """表单删除（form_ids 由调用方缓存）。"""
    if not form_ids:
        put_str(u'[%s] 流程未绑定表单，跳过' % service_id)
        return False
    s, r = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form?page=1&pageSize=500')
    form_refs = {}
    if ok_resp(s, r):
        for f in (r.get('data') or {}).get('list') or []:
            fid = f.get('instanceId')
            if fid in form_ids:
                pvs = []
                s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version?page=1&pageSize=50' % fid)
                if ok_resp(s2, r2):
                    for v in (r2.get('data') or {}).get('list') or []:
                        vi = v.get('versionInfo') or v
                        for p in (v.get('processVersions') or []):
                            pid = p.get('instanceId') if isinstance(p, dict) else p
                            if pid and pid != def_id:
                                pvs.append(pid)
                form_refs[fid] = pvs
    deleted = skipped = 0
    for fid in form_ids:
        others = form_refs.get(fid) or []
        if others:
            put_str(u'  ⚠️表单 %s 被其他流程绑定(%s)，跳过' % (fid, ','.join(others)))
            skipped += 1
            continue
        s2, r2 = http_json('GET', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version?page=1&pageSize=100' % fid)
        vids = []
        if ok_resp(s2, r2):
            for v in (r2.get('data') or {}).get('list') or []:
                vi = v.get('versionInfo') or v
                if vi.get('instanceId'):
                    vids.append(vi.get('instanceId'))
        vdone = 0
        for vid in vids:
            s3, r3 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s/version/%s' % (fid, vid))
            if ok_resp(s3, r3):
                vdone += 1
            else:
                put_str(u'  删表单版本 %s: %s' % (vid, (r3.get('error') if isinstance(r3, dict) else r3)))
        s4, r4 = http_json('DELETE', FLOWABLE_PORT, '/api/flowable_service/v1/form/%s' % fid)
        if ok_resp(s4, r4):
            deleted += 1
            put_str(u'  表单 %s 已删（版本 %d）' % (fid, vdone))
        else:
            skipped += 1
            put_str(u'  删表单 %s: %s' % (fid, (r4.get('error') if isinstance(r4, dict) else r4)))
    put_str(u'[%s] 表单清理: 删除 %d 跳过 %d' % (service_id, deleted, skipped))
    return deleted > 0


if __name__ == '__main__':
    sys.exit(main())
