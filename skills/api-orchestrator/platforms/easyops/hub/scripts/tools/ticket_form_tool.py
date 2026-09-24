#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：流程表单修改（工单表单控件值 查询/修改）

能力：
    查询——列工单全部节点×容器×控件的当前值（或只看指定控件）；
    修改——把指定控件在【全部节点】的值统一改掉（每个节点一份 formData 快照，全改保持一致）。

数据链路（无平台直接接口，操作持久层）：
    · 进行中工单（热库）：CMDB :8079
        查节点  POST /v3/object/_ITSC_INSTANCE_STEP/instance/_search
                query {"ITSC_PROCESS_INSTANCE.instanceId":"<工单ID>"}（关系键穿越）
        改      PUT  /v2/object/_ITSC_INSTANCE_STEP/instance/<stepId>
                body {"formData":"<完整JSON串>"}  🔴全量覆盖——读-改-写闭环
    · 已完结工单（冷库）：data_exchange :8152（借 CMDB host 拼 8152，同机部署）
        查节点  POST /api/v1/data_exchange/tsdb_column/search-with-skip
                filter {"ticketId":"<工单ID>"}，表 itsm_task@EASYOPS
        改      PUT  /api/v1/data_exchange/tsdb_column/update_by_id_v2
                data [{"_row_id":"...","formData":"<新JSON串>"}]
    · 冷热分派：CMDB _ITSC_PROCESS_INSTANCE 能查到=running（热库），查不到=走冷库。
    · 控件名解析：节点 formVersionId → CMDB _ITSC_FORM_VERSION.formDefinition
                → [{key,name,propertys:[{key,label,modelField,type}]}]
                入参先按 modelField/key 精确匹配，未命中按 label 中文名匹配；
                任一层命中多个不同控件 → 报错退出（列候选，让用户用 ID 重试）。

安全设计（流血教训固化，2026-09-24 PUT 清空事故）：
    · 修改前自动备份：每个目标节点原 formData 全文写备份文件（永久保留），
      路径 PutStr 回吐 backup_file；
    · confirm_yes=否（默认）只计算并输出 diff，不写库——看 diff 后带 是 重跑才真改；
    · 整体回写：永远基于读出的完整 formData 改单键后整体序列化回写，绝不构造局部 body；
    · 写后回读：重拉全部目标节点，校验新值落库 + 其余容器/控件零变化。

入参：
    ticket_url    工单URL，字符串，必填。两种格式（自动提取工单ID）：
                  https://host/next/itsc-ticket-center/task-list/<工单ID>/<任务ID>
                  https://host/next/itsc-ticket-center/ticket-list/<工单ID>
    field         表单控件名称或ID，字符串，必填（中文名或 modelField/key）
    new_value     新值，字符串，修改时必填。JSON（纯值或完整对象，如
                  '{"value":"1","label":"是","key":"1"}'；SELECT/RADIO 传纯值时按
                  现有值结构自动包装）
    action        动作，枚举 查询/修改，默认 查询
    confirm_yes   修改时跳过确认直接写库，枚举 是/否，默认 否

运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。
输出：PutStr 回吐进度/diff/备份路径；PutRow 回吐节点级明细表。
"""
import json
import logging
import os
import re
import sys
import time

IS_PY2 = sys.version_info[0] == 2

if IS_PY2:
    # py2 兜底：json.dumps(ensure_ascii=False) 遇「unicode+非ASCII bytes 混树」在
    # ''.join(chunks) UnicodeDecodeError（2026-09-23 .26 agent 实测）——与 alert2event
    # 家族对齐，setdefaultencoding(utf-8) 让 bytes 隐式按 utf-8 解。
    reload(sys)
    sys.setdefaultencoding('utf-8')

try:
    _string_types = (str, unicode)  # noqa: F821  (py2)
except NameError:
    _string_types = (str,)          # py3

if IS_PY2:
    import httplib as _http_client
else:
    import http.client as _http_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('ticket_form_tool')

CMDB_PORT = 8079
DATA_EXCHANGE_PORT = 8152

# 模型/表名
OBJ_TICKET = '_ITSC_PROCESS_INSTANCE'
OBJ_STEP = '_ITSC_INSTANCE_STEP'
OBJ_FORM_VERSION = '_ITSC_FORM_VERSION'
OBJ_FORM_RELATION = '_ITSC_PROCESS_FORM_RELATION'
COLD_TASK_TABLE = 'itsm_task@EASYOPS'

# data_exchange 时间范围（毫秒；0 ~ max int64 安全段）
TS_MIN = 0
TS_MAX = 9007199254740991

ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')
HOST = '127.0.0.1'
BASE_HEADERS = {}


def _resolve_conn():
    """服务地址解析：globals 注入变量 > env > 回环兜底。

    EASYOPS_CMDB_SERVICE_HOST / EASYOPS_CMDB_HOST 是执行器注入的脚本头全局变量
    （集群真实地址，非 agent 本机——2026-09-23 告警工具 v2 踩坑）。注入清单不含
    data_exchange，借 CMDB host 拼 :8152（同机部署成立）。
    """
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
                HOST = re.sub(r'^https?://', '', v).split(':')[0].strip()
                break
    ORG = str(g.get('EASYOPS_ORG') if g.get('EASYOPS_ORG') not in (None, '') else ORG)
    USER = str(g.get('EASYOPS_USER') if g.get('EASYOPS_USER') not in (None, '') else USER)
    BASE_HEADERS.update({'org': ORG, 'user': USER,
                         'Host': 'admin.easyops.local', 'Content-Type': 'application/json'})


def http_json(method, port, path, body=None, timeout=60):
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


def put_row(table, row):
    """平台 SDK PutRow 协议：收 "k=v&k=v" URL 编码串（dict 直接传 TypeError）。"""
    try:
        from urllib import urlencode  # py2
    except ImportError:
        from urllib.parse import urlencode  # py3
    pairs = []
    for k, v in row.items():
        if not isinstance(v, _string_types):
            v = json.dumps(v, ensure_ascii=False)
        pairs.append((k, v))
    try:
        PutRow(table, urlencode(pairs))  # noqa: F821  (平台注入 SDK)
    except NameError:
        logger.info(u'[row:%s] %s', table, urlencode(pairs))


# ----------------------------------------------------------------------------
# CMDB（热库）访问
# ----------------------------------------------------------------------------

def cmdb_search(object_id, query, fields, page=1, page_size=100):
    """POST /v3/object/<id>/instance/_search。返回实例列表（自动翻页）。"""
    out = []
    while True:
        _, resp = http_json('POST', CMDB_PORT,
                            '/v3/object/%s/instance/_search' % object_id,
                            {'page': page, 'pageSize': page_size,
                             'fields': fields, 'query': query})
        if not isinstance(resp, dict) or resp.get('code') not in (0, None):
            raise RuntimeError(u'CMDB search %s 失败: %s' % (object_id, json.dumps(resp, ensure_ascii=False)[:300]))
        data = resp.get('data') or {}
        rows = data.get('list') or []
        out.extend(rows)
        total = data.get('total') or 0
        if page * page_size >= total or not rows:
            break
        page += 1
    return out


def cmdb_put_step_formdata(step_id, form_data_str):
    """PUT /v2/object/_ITSC_INSTANCE_STEP/instance/<id>。🔴全量覆盖，body 只带 formData。"""
    _, resp = http_json('PUT', CMDB_PORT,
                        '/v2/object/%s/instance/%s' % (OBJ_STEP, step_id),
                        {'formData': form_data_str})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'CMDB PUT step %s 失败: %s' % (step_id, json.dumps(resp, ensure_ascii=False)[:300]))
    return True


# ----------------------------------------------------------------------------
# data_exchange（冷库）访问
# ----------------------------------------------------------------------------

def cold_search_tasks(ticket_id):
    """冷库 itsm_task@EASYOPS 按 ticketId 查全部节点行。"""
    _, resp = http_json('POST', DATA_EXCHANGE_PORT,
                        '/api/v1/data_exchange/tsdb_column/search-with-skip',
                        {'database': ORG, 'object_ids': [COLD_TASK_TABLE],
                         'start_time': TS_MIN, 'end_time': TS_MAX,
                         'filter': {'ticketId': ticket_id},
                         'fields': ['*'], 'limit': 200})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'data_exchange search 失败: %s' % json.dumps(resp, ensure_ascii=False)[:300])
    inner = resp.get('data') or {}
    if inner.get('code') not in (0, None):
        raise RuntimeError(u'data_exchange search 内层失败: %s' % json.dumps(inner, ensure_ascii=False)[:300])
    return inner.get('data') or []


def cold_update_formdata(row_id, form_data_str):
    """PUT update_by_id_v2（按 _row_id 精确更新 formData）。"""
    _, resp = http_json('PUT', DATA_EXCHANGE_PORT,
                        '/api/v1/data_exchange/tsdb_column/update_by_id_v2',
                        {'database': ORG, 'object_id': COLD_TASK_TABLE,
                         'data': [{'_row_id': row_id, 'formData': form_data_str}]})
    if not isinstance(resp, dict) or resp.get('code') not in (0, None):
        raise RuntimeError(u'data_exchange update 失败: %s' % json.dumps(resp, ensure_ascii=False)[:300])
    inner = resp.get('data') or {}
    if inner.get('update_fail_count'):
        raise RuntimeError(u'data_exchange update 有失败行: %s' % json.dumps(inner, ensure_ascii=False)[:200])
    return True


# ----------------------------------------------------------------------------
# 工单/节点/表单定义
# ----------------------------------------------------------------------------

URL_RE = re.compile(r'(?:task|ticket)-list/([0-9a-fA-F]{6,24})(?:/([0-9a-fA-F]{6,24}))?')


def parse_ticket_url(url):
    """工单 URL → (工单ID, 任务ID或None)。不匹配则把入参当裸工单 ID 兜底。"""
    m = URL_RE.search(url or '')
    if m:
        return m.group(1), m.group(2)
    if re.match(r'^[0-9a-fA-F]{6,24}$', (url or '').strip()):
        return url.strip(), None
    raise ValueError(u'无法从工单URL提取工单ID: %r（应形如 .../task-list/<id>[/<taskId>] 或 .../ticket-list/<id>）' % (url,))


def load_nodes(ticket_id):
    """冷热分派 + 拉全部节点。返回 (库别, [节点dict], 工单号)。

    节点统一字段：node_id(热库stepId/冷库_row_id)、instanceId、name、status、
    formData(原串)、formVersionIds(该节点适用的表单版本列表)、store('hot'/'cold')。

    热库表单版本解析链（step 上无 formVersionId 字段，从流程定义侧解析）：
    工单 →(ITSC_PROCESS_VERSION)→ _ITSC_PROCESS_FORM_RELATION（含 userTaskId）
    →(ITSC_FORM_VERSION)→ 表单定义。节点按 userTaskId 对齐；未命中绑定的节点
    沿用工单全部表单定义合集（数据继承场景）。
    冷库直接用行上的 formVersionId。
    """
    hot = cmdb_search(OBJ_TICKET, {'instanceId': ticket_id},
                      ['instanceId', 'status', 'orderNum',
                       'ITSC_PROCESS_VERSION.instanceId'], 1, 5)
    if hot:
        rows = cmdb_search(OBJ_STEP, {'ITSC_PROCESS_INSTANCE.instanceId': ticket_id},
                           ['instanceId', 'name', 'taskName', 'status', 'formData',
                            'userTaskId'], 1, 200)
        # 节点→表单版本映射（userTaskId 对齐）
        pv = (hot[0].get('ITSC_PROCESS_VERSION') or [{}])[0].get('instanceId') or ''
        utask2fvids, all_fvids = {}, []
        if pv:
            rels = cmdb_search(OBJ_FORM_RELATION, {'ITSC_PROCESS_VERSION.instanceId': pv},
                               ['instanceId', 'userTaskId', 'ITSC_FORM_VERSION.instanceId'], 1, 200)
            for r in rels:
                fvids = [f.get('instanceId') for f in (r.get('ITSC_FORM_VERSION') or []) if f.get('instanceId')]
                ut = r.get('userTaskId') or ''
                if ut and fvids:
                    utask2fvids[ut] = fvids
                all_fvids.extend(f for f in fvids if f not in all_fvids)
        nodes = []
        for r in rows:
            ut = r.get('userTaskId') or ''
            nodes.append({'node_id': r.get('instanceId'), 'instanceId': r.get('instanceId'),
                          'name': r.get('taskName') or r.get('name') or '',
                          'status': r.get('status') or '', 'formData': r.get('formData') or '',
                          'formVersionIds': utask2fvids.get(ut) or all_fvids, 'store': 'hot'})
        order = hot[0].get('orderNum') or ticket_id
        return 'hot', nodes, order
    rows = cold_search_tasks(ticket_id)
    nodes = [{'node_id': r.get('_row_id'), 'instanceId': r.get('instanceId'),
              'name': r.get('name') or r.get('userTaskId') or '',
              'status': r.get('status') or '', 'formData': r.get('formData') or '',
              'formVersionIds': [r['formVersionId']] if r.get('formVersionId') else [],
              'store': 'cold'} for r in rows]
    return 'cold', nodes, ticket_id


_FORM_DEF_CACHE = {}


def load_form_definition(form_version_id):
    """_ITSC_FORM_VERSION.formDefinition → [(容器key, 容器name, [控件...])]。带缓存。"""
    if form_version_id in _FORM_DEF_CACHE:
        return _FORM_DEF_CACHE[form_version_id]
    rows = cmdb_search(OBJ_FORM_VERSION, {'instanceId': form_version_id},
                       ['instanceId', 'formDefinition'], 1, 5)
    if not rows:
        _FORM_DEF_CACHE[form_version_id] = None
        return None
    raw = rows[0].get('formDefinition') or ''
    try:
        fd = json.loads(raw) if raw.strip() else []
    except ValueError:
        fd = []
    out = []
    for cntr in fd:
        comps = []
        for p in (cntr.get('propertys') or []):
            comps.append({'key': p.get('key') or '',
                          'label': p.get('label') or p.get('name') or '',
                          'modelField': p.get('modelField') or p.get('key') or '',
                          'type': p.get('type') or ''})
        out.append({'key': cntr.get('key') or '', 'name': cntr.get('name') or '',
                    'modelField': cntr.get('modelField') or cntr.get('key') or '',
                    'components': comps})
    _FORM_DEF_CACHE[form_version_id] = out
    return out


def resolve_field(field, form_version_ids):
    """入参 field → (modelField, 控件类型列表)。多匹配报错。

    匹配规则：先在【所有出现的表单版本】范围内按 modelField/key 精确匹配；
    未命中再按 label 中文名匹配。同一层命中多个不同 modelField → 报错退出。
    """
    by_id, by_label = {}, {}
    for fvid in form_version_ids:
        fd = load_form_definition(fvid)
        if not fd:
            continue
        for cntr in fd:
            for comp in cntr['components']:
                if comp['modelField'] and comp['modelField'] == field:
                    by_id.setdefault(comp['modelField'], {'types': set(), 'where': set()})['types'].add(comp['type'])
                    by_id[comp['modelField']]['where'].add(u'%s/%s' % (cntr.get('name') or cntr.get('key'), comp['label']))
                if comp['label'] and comp['label'] == field:
                    by_label.setdefault(comp['modelField'], {'types': set(), 'where': set()})['types'].add(comp['type'])
                    by_label[comp['modelField']]['where'].add(u'%s/%s' % (cntr.get('name') or cntr.get('key'), comp['label']))
    for pool, how in ((by_id, u'ID'), (by_label, u'名称')):
        if len(pool) == 1:
            mf, info = pool.items()[0] if IS_PY2 else list(pool.items())[0]
            return mf, sorted(info['types']), sorted(info['where']), how
        if len(pool) > 1:
            lines = [u'  %s <- %s' % (mf, '; '.join(info['where'])) for mf, info in pool.items()]
            raise RuntimeError(u'控件%s「%s」匹配到 %d 个不同字段，无法确定目标：\n%s\n请改用 modelField/控件ID 精确指定'
                               % (how, field, len(pool), u'\n'.join(lines)))
    raise RuntimeError(u'控件「%s」在工单绑定的表单定义中未找到（查 modelField/key 和 label 中文名均未命中）' % field)


# ----------------------------------------------------------------------------
# formData 解析与修改
# ----------------------------------------------------------------------------

def parse_form_data(raw):
    """formData JSON 串 → [{'key':容器, 'values':[...]}]（坏串/空串返回 []）。"""
    if not raw or not (raw or '').strip():
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def dump_form_data(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def coerce_value(old, new):
    """新值按现有值结构对齐。

    · old 是 dict（SELECT/RADIO 等枚举对象）且 new 非 dict：保留 old 的 key/label，
      只换 value/label（label=value 的字符串形式）；
    · old 是 list 且 new 是纯值：包装为 [new]；
    · 其余：原样。
    """
    if isinstance(old, dict) and not isinstance(new, dict):
        merged = dict(old)
        merged['value'] = new
        merged['label'] = new if isinstance(new, _string_types) else json.dumps(new, ensure_ascii=False)
        return merged
    if isinstance(old, list) and not isinstance(new, list):
        return [new]
    return new


def locate_and_set(data, model_field, new_value, auto_wrap=True):
    """在 formData 结构里定位控件并写新值。返回 (命中容器数, 命中行数)。"""
    n_cntr, n_row = 0, 0
    for cntr in data:
        vals = cntr.get('values')
        if not isinstance(vals, list):
            continue
        hit = False
        for row in vals:
            if isinstance(row, dict) and model_field in row:
                row[model_field] = coerce_value(row.get(model_field), new_value) if auto_wrap else new_value
                hit = True
                n_row += 1
        if hit:
            n_cntr += 1
    return n_cntr, n_row


def summarize_value(v, limit=120):
    s = v if isinstance(v, _string_types) else json.dumps(v, ensure_ascii=False)
    return s[:limit] + (u'…' if len(s) > limit else u'')


# ----------------------------------------------------------------------------
# 备份
# ----------------------------------------------------------------------------

def write_backup(ticket_id, store, nodes):
    """改前备份：原 formData 全文 → JSON 文件（永久保留）。沙箱目录回退链。"""
    stamp = time.strftime('%Y%m%d_%H%M%S')
    payload = {'ticket_id': ticket_id, 'store': store, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
               'nodes': [{'node_id': n['node_id'], 'name': n['name'], 'status': n['status'],
                          'store': n['store'], 'formData': n['formData']} for n in nodes]}
    candidates = []
    cache_dir = os.environ.get('EASYOPS_SCRIPT_CACHE') or ''
    if cache_dir:
        candidates.append(os.path.join(cache_dir, 'ticket_form_backups'))
    candidates.extend([os.path.join(os.path.abspath(os.curdir), 'ticket_form_backups'), '/tmp/ticket_form_backups'])
    last_err = None
    for d in candidates:
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
            path = os.path.join(d, u'ticket_%s_%s.json' % (ticket_id, stamp))
            with open(path, 'w') as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            return path
        except (OSError, IOError) as e:
            last_err = e
            continue
    raise RuntimeError(u'备份文件写入失败（所有候选目录均不可写，最后错误: %s）——为安全起见中止修改' % last_err)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def parse_args(argv):
    cfg = {'ticket_url': '', 'field': '', 'new_value': '',
           'action': u'查询', 'confirm_yes': u'否'}

    def _coerce(key, val):
        if IS_PY2 and isinstance(val, str):
            try:
                val = val.decode('utf-8')
            except UnicodeDecodeError:
                pass
        if isinstance(val, _string_types):
            val = val.strip()
        if val in (None, ''):
            return
        if key in ('action', 'confirm_yes'):
            if isinstance(val, bool):
                cfg[key] = (u'是' if val else u'查询' if key == 'action' else u'否')
            else:
                cfg[key] = val
        else:
            cfg[key] = val if isinstance(val, _string_types) else str(val)

    g = globals()
    for k in cfg:
        if g.get(k) not in (None, ''):
            _coerce(k, g[k])
    for k in cfg:
        v = os.environ.get(k) or os.environ.get(k.upper())
        if v:
            _coerce(k, v)
    for a in argv or []:
        if '=' in a:
            k, v = a.lstrip('-').split('=', 1)
            if k.strip() in cfg:
                _coerce(k.strip(), v)
    return cfg


def main(argv=None):
    _resolve_conn()
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    if not cfg['ticket_url'] or not cfg['field']:
        put_str(u'缺少必填入参 ticket_url / field')
        return 1
    action = cfg['action']
    if action not in (u'查询', u'修改'):
        put_str(u'action 非法: %r（应为 查询/修改）' % (action,))
        return 1

    ticket_id, task_id = parse_ticket_url(cfg['ticket_url'])
    put_str(u'工单ID: %s%s  动作: %s' % (ticket_id, (u'  任务ID: %s' % task_id) if task_id else u'', action))

    store, nodes, order_num = load_nodes(ticket_id)
    if not nodes:
        put_str(u'未找到工单 %s 的任何节点（热库/冷库均无）' % ticket_id)
        return 1
    put_str(u'存储: %s（%s）  节点数: %d' % (u'热库CMDB' if store == 'hot' else u'冷库columndb', order_num, len(nodes)))

    # 控件解析（多匹配报错退出）
    fvids = []
    for n in nodes:
        for f in n.get('formVersionIds') or []:
            if f and f not in fvids:
                fvids.append(f)
    if not fvids:
        put_str(u'⚠️ 节点无 formVersionId，无法做控件名解析——field 必须直接是 formData 里的存储键')
        model_field, types, where, how = cfg['field'], [], [], u'直连键'
    else:
        try:
            model_field, types, where, how = resolve_field(cfg['field'], fvids)
        except RuntimeError as e:
            put_str(u'❌ %s' % e)
            return 2
        put_str(u'控件命中: %s（按%s匹配，类型 %s）' % (model_field, how, u'/'.join(types) or u'?'))

    # 新值解析
    new_value = None
    if action == u'修改':
        if not cfg['new_value']:
            put_str(u'❌ 修改动作缺少 new_value')
            return 1
        raw = cfg['new_value']
        try:
            new_value = json.loads(raw) if isinstance(raw, _string_types) else raw
        except ValueError:
            new_value = raw  # 非合法 JSON 按纯字符串值处理
        put_str(u'新值: %s' % summarize_value(new_value))

    # ---- 查询：列全部控件值（或指定控件），逐节点输出 ----
    if action == u'查询':
        for n in nodes:
            data = parse_form_data(n['formData'])
            if not data:
                put_row('nodes', {'node': n['name'], 'status': n['status'], 'store': n['store'],
                                  'container': '-', 'field': '-', 'value': u'(空/坏 formData)'})
                continue
            if cfg['field'] and how != u'直连键':
                shown = False
                for cntr in data:
                    for row in cntr.get('values') or []:
                        if isinstance(row, dict) and model_field in row:
                            put_row('nodes', {'node': n['name'], 'status': n['status'], 'store': n['store'],
                                              'container': cntr.get('key'), 'field': model_field,
                                              'value': summarize_value(row.get(model_field))})
                            shown = True
                if not shown:
                    put_row('nodes', {'node': n['name'], 'status': n['status'], 'store': n['store'],
                                      'container': '-', 'field': model_field, 'value': u'(该节点无此控件)'})
            else:
                for cntr in data:
                    for row in cntr.get('values') or []:
                        if isinstance(row, dict):
                            for k, v in row.items():
                                put_row('nodes', {'node': n['name'], 'status': n['status'], 'store': n['store'],
                                                  'container': cntr.get('key'), 'field': k,
                                                  'value': summarize_value(v)})
        put_str(u'查询完成（%d 节点）' % len(nodes))
        return 0

    # ---- 修改：diff → 备份 → 写回 → 回读验证 ----
    plan = []   # [{'node':..., 'data':新结构, 'old_raw':..., 'new_raw':...}]
    skipped = []
    for n in nodes:
        data = parse_form_data(n['formData'])
        if not data:
            skipped.append(n)
            continue
        probe = json.loads(dump_form_data(data))  # 深拷贝试算
        n_cntr, n_row = locate_and_set(probe, model_field, new_value)
        if not n_row:
            skipped.append(n)
            continue
        plan.append({'node': n, 'data': probe, 'old_raw': n['formData'],
                     'new_raw': dump_form_data(probe), 'n_cntr': n_cntr, 'n_row': n_row})

    if not plan:
        put_str(u'⚠️ 任何节点的 formData 里都没有控件 %s，无需修改（跳过节点 %d 个）'
                % (model_field, len(skipped)))
        return 0

    put_str(u'变更计划: %d/%d 节点命中（跳过 %d 个无此控件的节点）' % (len(plan), len(nodes), len(skipped)))
    for p in plan:
        n = p['node']
        old_vs, new_v = [], None
        for cntr in parse_form_data(p['old_raw']):
            for row in cntr.get('values') or []:
                if isinstance(row, dict) and model_field in row:
                    old_vs.append(row.get(model_field))
        for cntr in p['data']:
            for row in cntr.get('values') or []:
                if isinstance(row, dict) and model_field in row and new_v is None:
                    new_v = row.get(model_field)
        old_v = old_vs[0] if old_vs else None
        distinct = set(json.dumps(v, ensure_ascii=False, sort_keys=True) for v in old_vs)
        warn = u'  ⚠️ 原 %d 行有 %d 种不同值，将统一改为新值' % (len(old_vs), len(distinct)) if len(distinct) > 1 else u''
        put_row('diff', {'node': n['name'], 'status': n['status'], 'store': n['store'],
                         'rows': p['n_row'],
                         'old': summarize_value(old_v), 'new': summarize_value(new_v)})
        put_str(u'  [%s] %s（%s）: %s → %s（%d 容器 %d 行）%s'
                % (n['store'], n['name'], n['status'],
                   summarize_value(old_v, 60), summarize_value(new_v, 60), p['n_cntr'], p['n_row'], warn))

    if cfg['confirm_yes'] != u'是':
        put_str(u'confirm_yes=否：仅输出 diff 未写库。确认无误后带 confirm_yes=是 重跑执行修改。')
        return 0

    # 备份（永久保留）
    backup_path = write_backup(ticket_id, store, [p['node'] for p in plan])
    put_str(u'已备份 %d 节点原 formData → %s' % (len(plan), backup_path))

    # 写回
    ok, fail = 0, []
    for p in plan:
        n = p['node']
        try:
            if n['store'] == 'hot':
                cmdb_put_step_formdata(n['node_id'], p['new_raw'])
            else:
                cold_update_formdata(n['node_id'], p['new_raw'])
            ok += 1
        except RuntimeError as e:
            fail.append((n['name'], text(e)))
            put_str(u'❌ 写回失败 [%s] %s: %s' % (n['store'], n['name'], e))
            break  # 失败即停（备份在，可恢复）
    put_str(u'写回完成: 成功 %d 失败 %d' % (ok, len(fail)))
    if fail:
        return 3

    # 回读验证：新值落库 + 其余控件零变化
    _, nodes2, _ = load_nodes(ticket_id)
    idx = dict((n['node_id'], n) for n in nodes2)
    bad = []
    for p in plan:
        n2 = idx.get(p['node']['node_id'])
        if not n2:
            bad.append((p['node']['name'], u'回读不到节点'))
            continue
        if parse_form_data(n2['formData']) != p['data']:
            bad.append((p['node']['name'], u'回读 formData 与预期不一致'))
    if bad:
        put_str(u'⚠️ 回读校验异常: %s（原值备份在 %s）' % (u'; '.join(u'%s:%s' % b for b in bad), backup_path))
        return 4
    put_str(u'✅ 回读校验通过: %d 节点新值落库，其余控件零变化' % len(plan))
    return 0


def text(e):
    return e.message if IS_PY2 and hasattr(e, 'message') else str(e)


if __name__ == '__main__':
    sys.exit(main())
