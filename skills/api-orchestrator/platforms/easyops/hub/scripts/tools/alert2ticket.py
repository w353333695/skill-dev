#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：告警转工单（未恢复告警 → 故障工单 → 回填表单）

入参：
    range            查询时间范围，字符串，\d+[m,h,d]（如 30m/2h/1d），发生时间在范围内
    auto_create      是否自动转工单，枚举 是/否，默认 是
    alert_level      自动转工单告警级别，枚举 info/warning/critical，默认 critical（含及以上）
    alert_time       自动转工单告警时间（分钟），整数，默认 20（发生时间已超过该时长）

逻辑：
    1) auto_create=是：检索未恢复告警（时间范围+级别及以上+持续超时），逐条转故障工单
    2) 查询范围内新建的转故障工单（states=divide,diagnostic,recover）
    3) 按工单关联 _ITSC_PROCESS_INSTANCE 实例 → 「识别和发起」_ITSC_INSTANCE_STEP，
       将工单详情回填表单属性（故障等级/优先级/类型/处理人/关联告警 table）

运行环境：EasyOps agent（py2，requests 可用）或编排侧 py3。
鉴权：org/user header 直连后端（免 cookie）。

输出：PutStr 回吐进度与统计（agent 工具模式下可见）。
"""
import json
import logging
import os
import re
import sys
import time

IS_PY2 = sys.version_info[0] == 2

try:
    _string_types = (str, unicode)  # noqa: F821  (py2)
except NameError:
    _string_types = (str,)          # py3


def _to_unicode(v):
    """py2 平台注入的 str 可能是 bytes——统一转 unicode（py3 直接返回 str）。"""
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v

if IS_PY2:
    import httplib as _http_client
else:
    import http.client as _http_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('alert2ticket')

# ---------------------------------------------------------------------------
# 环境与常量（agent 注入 EASYOPS_*；编排侧可覆盖）
# ---------------------------------------------------------------------------
ALERT_SERVICE_PORT = 8131          # logic.alert_service
FLOWABLE_PORT = 8134               # logic.flowable_service
CMDB_PORT = 8079                   # logic.cmdb.service

def _default_host():
    """从 EASYOPS_*_URL 类变量提取 host；都无则回退硬编码。"""
    for var in ('EASYOPS_CMDB_BACKEND_URL', 'EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_HOST'):
        v = os.environ.get(var, '')
        if v:
            return v.replace('http://', '').replace('https://', '').split(':')[0].strip()
    return '172.30.0.232'


HOST = _default_host()
ORG = os.environ.get('EASYOPS_ORG', '1888')
USER = os.environ.get('EASYOPS_USER', 'easyops')


def _platform_var(name, default):
    """平台注入变量：header 同名 python 变量 > 进程 env > 默认（见 objects.yaml tool_param_injection）。"""
    g = globals()
    if name in g and g[name] not in (None, ''):
        return g[name]
    return os.environ.get(name, default)


def _resolve_conn():
    """运行时解析连接参数（平台注入优先；env 用 *_URL/同名变量多形态解析）。"""
    global HOST, ORG, USER
    g = globals()
    url_host = ''
    for var in ('EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_CMDB_HOST'):
        if isinstance(g.get(var), str) and g[var]:
            url_host = str(g[var]).split(':')[0].strip()
            break
    if not url_host:
        url_host = _default_host()
    HOST = url_host or HOST
    ORG = str(_platform_var('EASYOPS_ORG', ORG))
    USER = str(_platform_var('EASYOPS_USER', USER))
    BASE_HEADERS.update({'org': ORG, 'user': USER})

SERVICE_ID = '60c33d948bf61'       # 「故障处理」服务实例（事件管理）
HANDLER_NAME = 'easyops'           # 默认处理人（工单 handlerName 必填）
STEP_TASK_NAME = u'识别和发起'      # 表单数据挂靠的流程步骤

# 告警 level(str) → 工单 level(int)
ALERT_LEVEL_TO_INT = {u'info': 0, u'warning': 1, u'critical': 2}
# 告警 level(str) → 表单故障等级（P1-P5）
ALERT_LEVEL_TO_P = {u'critical': u'P1', u'warning': u'P2', u'info': u'P4'}
# 表单「等级」列（通知/警告/严重）
ALERT_LEVEL_TO_CN = {u'info': u'通知', u'warning': u'警告', u'critical': u'严重'}

BASE_HEADERS = {
    'org': ORG,
    'user': USER,
    'Host': 'admin.easyops.local',
    'Content-Type': 'application/json',
}


def http_json(method, port, path, body=None, timeout=30):
    """直连后端调 API（stdlib 实现，py2/3 兼容——agent 无第三方包）。

    返回 (status, parsed_json_or_text)。
    """
    conn = _http_client.HTTPConnection(HOST, port, timeout=timeout)
    data = json.dumps(body) if body is not None else None
    headers = dict(BASE_HEADERS)
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
    finally:
        conn.close()
    if IS_PY2:
        text = raw.decode('utf-8', 'replace')
    else:
        text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def put_str(message):
    """agent 工具模式回吐进度；本地模式打日志。"""
    logger.info(message)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 入参解析（EasyOps 工具入参经 argv：key=value；或模块级调用）
# ---------------------------------------------------------------------------
def parse_range(range_str):
    """'\d+[m,h,d]' → 秒。非法则报错退出。"""
    m = re.match(r'^(\d+)([mhd])$', (range_str or '').strip())
    if not m:
        raise ValueError(u'查询时间范围格式非法: %r（应为 30m/2h/1d）' % (range_str,))
    n, unit = int(m.group(1)), m.group(2)
    return n * {'m': 60, 'h': 3600, 'd': 86400}[unit]


def parse_args(argv):
    """入参获取（EasyOps 平台优先）。

    平台注入形态：inputs 与 EASYOPS_* 都不是进程环境变量，而是执行器拼在脚本
    header 的【同名 python 变量赋值】（creator.go AssembleParams）——用
    globals().get() 取；本地/编排侧兜底 EASYOPS_TOOL_INPUT(JSON) 与 argv k=v。
    优先级：globals 注入 > env 同名 > argv > 默认值。
    """
    cfg = {'range': '1d', 'auto_create': u'是', 'alert_level': 'critical', 'alert_time': 20}

    def _coerce(key, val):
        val = _to_unicode(val)
        val = val.strip() if isinstance(val, _string_types) else val
        if val in (None, ''):
            return
        if key == 'alert_time':
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                pass
        elif key == 'auto_create':
            if isinstance(val, bool):
                cfg[key] = u'是' if val else u'否'
            elif isinstance(val, _string_types):
                cfg[key] = val if val in (u'是', u'否') else (u'是' if val in ('true', 'True', '1') else u'否')
        elif key in ('range', 'alert_level'):
            cfg[key] = str(val)

    # ① 平台 header 注入的同名变量（最高优先）
    g = globals()
    for k in cfg:
        if k in g and g[k] not in (None, ''):
            _coerce(k, g[k] if not isinstance(g[k], (list, tuple, dict)) else str(g[k]))
    # ② env 同名（agent 兼容/编排侧）
    for k in cfg:
        v = os.environ.get(k) or os.environ.get(k.upper())
        if v:
            _coerce(k, v)
    # ③ EASYOPS_TOOL_INPUT JSON 兜底（本地调试）
    ti = os.environ.get('EASYOPS_TOOL_INPUT') or (g.get('EASYOPS_TOOL_INPUT') if isinstance(g.get('EASYOPS_TOOL_INPUT'), str) else '')
    if ti:
        try:
            for k, v in (json.loads(ti) or {}).items():
                if k in cfg:
                    _coerce(k, v)
        except ValueError:
            pass
    # ④ argv k=v（最低）
    for a in argv or []:
        if '=' not in a:
            continue
        k, v = a.split('=', 1)
        k = k.lstrip('-').strip()
        if k in cfg:
            _coerce(k, v)
    return cfg


# ---------------------------------------------------------------------------
# 步骤 1：检索未恢复告警
# ---------------------------------------------------------------------------
def search_not_recover(range_sec, min_level, older_than_sec):
    """未恢复告警：发生时间在范围内 + 级别≥min_level + 首次发生已超过 older_than_sec。

    分页拉全（page_size 上限 300），内存过滤 level/startTime。
    """
    order = {u'info': 0, u'warning': 1, u'critical': 2}
    fields = ['_id', 'eventId', 'batchId', 'startTime', 'time', 'level', 'objectId',
              'instanceId', 'target', 'originContent', 'originTitle', 'metricName',
              'metricValue', 'metricThresholdValue', 'metricThresholdComparator',
              'source', 'alertRuleId']
    st = '-%d' % range_sec
    now = int(time.time())
    out, page = [], 1
    while True:
        status, resp = http_json('POST', ALERT_SERVICE_PORT, '/api/v1/monitor_event/not_recover/_search', {
            'page': page, 'page_size': 300, 'st': st, 'fields': fields,
        })
        if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
            raise RuntimeError(u'检索未恢复告警失败: HTTP %s %s' % (status, resp))
        data = resp.get('data') or {}
        lst = data.get('list') or []
        if not lst:
            break
        for ev in lst:
            lv = (ev.get('level') or u'info').lower()
            if order.get(lv, 0) < order.get(min_level, 0):
                continue                       # 级别不足
            if now - int(ev.get('startTime') or 0) < older_than_sec:
                continue                       # 持续时长不足
            out.append(ev)
        if len(out) >= int(data.get('total') or 0) or page * 300 >= int(data.get('total') or 0):
            break
        page += 1
    return out


# ---------------------------------------------------------------------------
# 步骤 2：批量转故障工单
# ---------------------------------------------------------------------------
def build_ticket(ev):
    """告警事件 → 工单 ticket 结构（对齐 BatchCreate validator）。"""
    lv = (ev.get('level') or u'info').lower()
    content = ev.get('originContent') or ev.get('originTitle') or ev.get('metricName') or ''
    title = content[:200] or (u'%s 告警' % ev.get('target', ''))
    return {
        'resourceList': [{
            'objectId': ev.get('objectId') or 'HOST',
            'resourceId': ev.get('instanceId') or '',
            'showFields': ['hostname', 'ip'],
            'objectName': u'主机',
        }] if ev.get('instanceId') else [],
        'alertList': [{
            'startTime': int(ev.get('startTime') or 0),
            'time': int(ev.get('time') or ev.get('startTime') or 0),
            'batchId': ev.get('batchId') or '',
            'eventId': ev.get('eventId') or ev.get('_id') or '',
        }],
        'priority': 0,
        'handlerName': HANDLER_NAME,
        'memo': u'\n发生时间：%s\n告警资源：%s\n告警等级：%s\n事件描述：%s\n事件来源：%s' % (
            fmt_time(ev.get('startTime')), ev.get('target') or '', ALERT_LEVEL_TO_CN.get(lv, lv),
            content, u'统一数据告警'),
        'serviceId': SERVICE_ID,
        'category': 'alert',
        'level': ALERT_LEVEL_TO_INT.get(lv, 0),
        'title': title,
    }


def batch_create_tickets(events):
    """逐条转工单（_batch 接口虽批量，逐条调用便于错误归因与部分成功统计）。"""
    ok, fail = 0, 0
    for ev in events:
        status, resp = http_json('POST', FLOWABLE_PORT,
                                 '/api/flowable_service/v1/incident_management/ticket/_batch',
                                 {'ticketList': [build_ticket(ev)]})
        body = json.dumps(resp, ensure_ascii=False) if not isinstance(resp, str) else resp
        if status == 200 and isinstance(resp, dict) and resp.get('code') in (0, None):
            ok += 1
            put_str(u'转工单成功: %s (%s)' % (build_ticket(ev).get('title'), ev.get('eventId')))
        else:
            fail += 1
            put_str(u'转工单失败: %s -> HTTP %s %s' % (ev.get('eventId'), status, body[:200]))
    return ok, fail


def fmt_time(ts):
    if not ts:
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(ts)))


# ---------------------------------------------------------------------------
# 步骤 3：查时间范围内新建的故障工单
# ---------------------------------------------------------------------------
def list_created_tickets(range_sec):
    st = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(time.time()) - range_sec))
    et = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    out, page = [], 1
    while True:
        status, resp = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v1/incident_management/ticket', {
            'ctimeRange': {'st': st, 'et': et},
            'states': 'divide,diagnostic,recover',
            'page': page, 'pageSize': 100,
        })
        if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
            raise RuntimeError(u'查询故障工单失败: HTTP %s %s' % (status, resp))
        data = resp.get('data') or {}
        lst = data.get('list') or []
        out.extend(lst)
        total = int(data.get('total') or 0)
        if not lst or len(out) >= total or page >= 100:
            break
        page += 1
    return out


# ---------------------------------------------------------------------------
# 步骤 4+5：关联流程实例 → 识别和发起 step → 回填表单
# ---------------------------------------------------------------------------
def find_process_instance(ticket):
    """工单 → _ITSC_PROCESS_INSTANCE 实例（按 orderNum 精确）。同时缓存 eventId→alertRuleId。"""
    order_num = ticket.get('orderNum') or ''
    if not order_num:
        return None
    status, resp = http_json('POST', CMDB_PORT, '/v3/object/_ITSC_PROCESS_INSTANCE/instance/_search', {
        'fields': ['instanceId', 'name', 'orderNum', 'serviceId'],
        'page': 1, 'page_size': 5,
        'query': {'orderNum': order_num},
    })
    if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
        return None
    lst = (resp.get('data') or {}).get('list') or []
    return lst[0] if lst else None


_USER_INSTANCE_CACHE = {}


def lookup_user_instance_id(name):
    """USER 模型按 name 查 instanceId（带缓存）——CMDBINSTANCESELECT 值需要真 instanceId。"""
    if not name or name in _USER_INSTANCE_CACHE:
        return _USER_INSTANCE_CACHE.get(name)
    status, resp = http_json('POST', CMDB_PORT, '/v3/object/USER/instance/_search', {
        'fields': ['instanceId', 'name'],
        'page': 1, 'page_size': 5,
        'query': {'name': name},
    })
    lst = (resp.get('data') or {}).get('list') or [] if isinstance(resp, dict) else []
    iid = lst[0].get('instanceId') if lst else ''
    _USER_INSTANCE_CACHE[name] = iid
    return iid


def find_identify_step(pi_instance_id):
    """流程实例 → 「识别和发起」_ITSC_INSTANCE_STEP。

    用 STEP 模型 search 的关系键（reverseQueryKey=ITSC_PROCESS_INSTANCE）过滤：
    query 按 taskName 命中，fields 带关系键回读所属流程实例，配对匹配。
    """
    status, resp = http_json('POST', CMDB_PORT, '/v3/object/_ITSC_INSTANCE_STEP/instance/_search', {
        'fields': ['instanceId', 'taskName', 'userTaskId', 'status', 'formData', 'ITSC_PROCESS_INSTANCE'],
        'page': 1, 'page_size': 200,
        'query': {'taskName': STEP_TASK_NAME},
    })
    if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
        return None
    for s in (resp.get('data') or {}).get('list') or []:
        for rel in (s.get('ITSC_PROCESS_INSTANCE') or []):
            if rel.get('instanceId') == pi_instance_id:
                return s
    return None


def build_form_data(ticket, alert_rule_id=''):
    """工单详情 → 表单 formData 结构（[{key:容器, values:[{控件:值}]}]）。

    控件赋值协议（objects.yaml#itsm_form_component「formData 控件赋值协议」）：
    SELECT 单选传 {key,label,value} 对象；COMMONDATE 传 RFC3339 串；LINK 传 {href,label}。
    """
    lv_int = ticket.get('level')
    # SELECT 控件 key 对齐表单 extraProps.items（key→label/value）
    def _enum(key, label_value):
        return {'key': key, 'label': label_value, 'value': label_value}

    p_map = {2: _enum('p1', u'P1'), 1: _enum('p2', u'P2'), 0: _enum('p4', u'P4')}
    priority_map = {2: _enum('urgent', u'紧急'), 1: _enum('urgent', u'紧急'), 0: _enum('normal', u'普通')}
    handler_names = ticket.get('operator') or [HANDLER_NAME]
    rows = []
    for al in ticket.get('alertList') or []:
        rows.append({
            'alertTime': rfc3339(al.get('startTime')),
            'alertLevel': {2: _enum('critical', u'严重'), 1: _enum('warning', u'警告'), 0: _enum('notice', u'通知')}.get(lv_int, _enum('notice', u'通知')),
            'alertResource': (ticket.get('resource') or {}).get('resourceName', ''),
            'alertInfo': ticket.get('title') or '',
            'alertSource': u'统一数据告警',
            'alertUrl': {'label': u'查看告警', 'href': '/next/events/%s/detail' % (al.get('eventId') or '')},
            'cmdbURL': {'label': u'查看实例', 'href': '/next/next-cmdb-instance-management/next/%s/instance/%s' % (
                (ticket.get('resource') or {}).get('objectId', 'HOST'),
                (ticket.get('resource') or {}).get('resourceId', ''))},
        })
    return [
        {'key': 'sec_base', 'values': [{
            'incidentLevel': p_map.get(lv_int, _enum('p4', u'P4')),
            'priority': priority_map.get(lv_int, _enum('normal', u'普通')),
            'incidentType': _enum('alert', u'告警异常'),
            'handler': [{'instanceId': lookup_user_instance_id(n), 'name': n} for n in handler_names],
        }]},
        {'key': 'sec_alerts', 'values': rows},
    ]


def rfc3339(ts):
    """unix 时间戳 → RFC3339 带本地时区串（COMMONDATE 控件协议，不收时间戳）。"""
    if not ts:
        return ''
    ts = int(ts)
    if IS_PY2:
        import datetime
        dt = datetime.datetime.fromtimestamp(ts)
        offset = datetime.datetime.utcnow() - datetime.datetime.now()
        off_sec = int(offset.total_seconds())
        sign = '+' if off_sec >= 0 else '-'
        off_sec = abs(off_sec)
        return dt.strftime('%Y-%m-%dT%H:%M:%S') + '%s%02d:%02d' % (sign, off_sec // 3600, (off_sec % 3600) // 60)
    import datetime
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')


def fill_step_form(step_instance_id, form_data):
    """更新 step 实例 formData（CMDB instance update）。"""
    status, resp = http_json('PUT', CMDB_PORT,
                             '/v2/object/_ITSC_INSTANCE_STEP/instance/%s' % step_instance_id,
                             {'formData': json.dumps(form_data, ensure_ascii=False)})
    return status == 200 and isinstance(resp, dict) and resp.get('code') in (0, None), resp


def main(argv=None):
    _resolve_conn()
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    put_str(u'配置: %s' % json.dumps(cfg, ensure_ascii=False))
    range_sec = parse_range(cfg['range'])

    # 步骤 1+2：自动转工单（同时留 eventId→alertRuleId 索引供回填用；
    # 防重：_batch 成功即消费事件（移出 not_recover），天然幂等）
    ev_rule_map = {}
    if cfg['auto_create'] == u'是':
        events = search_not_recover(range_sec, cfg['alert_level'], cfg['alert_time'] * 60)
        put_str(u'待转工单告警数: %d' % len(events))
        for ev in events:
            if ev.get('alertRuleId'):
                ev_rule_map[ev['eventId'] or ev.get('_id')] = ev['alertRuleId']
        ok, fail = batch_create_tickets(events)
        put_str(u'转工单完成: 成功 %d 失败 %d' % (ok, fail))
    else:
        put_str(u'自动转工单=否，跳过检索与建单')

    # 全量事件建 ruleId 索引（覆盖历史单回填——not_recover 之外的事件也带 alertRuleId）
    status, resp = http_json('POST', ALERT_SERVICE_PORT, '/api/v1/monitor_event/_search', {
        'page': 1, 'page_size': 300, 'st': '-%d' % range_sec,
        'fields': ['eventId', 'alertRuleId'],
    })
    if status == 200 and isinstance(resp, dict):
        for ev in (resp.get('data') or {}).get('list') or []:
            if ev.get('alertRuleId'):
                ev_rule_map[ev.get('eventId') or ev.get('_id')] = ev['alertRuleId']

    # 步骤 3：查范围内新建的转故障工单
    tickets = list_created_tickets(range_sec)
    put_str(u'范围内故障工单数: %d' % len(tickets))

    # 步骤 4+5：回填表单
    filled, skipped = 0, 0
    for t in tickets:
        pi = find_process_instance(t)
        if not pi:
            skipped += 1
            put_str(u'未找到流程实例: %s' % t.get('orderNum'))
            continue
        step = find_identify_step(pi.get('instanceId'))
        if not step:
            skipped += 1
            put_str(u'未找到识别和发起步骤: %s' % pi.get('instanceId'))
            continue
        rule_id = ''
        for al in t.get('alertList') or []:
            rule_id = ev_rule_map.get(al.get('eventId')) or ''
            if rule_id:
                break
        ok, resp = fill_step_form(step['instanceId'], build_form_data(t, rule_id))
        if ok:
            filled += 1
            put_str(u'表单回填成功: %s -> step %s' % (t.get('orderNum'), step['instanceId']))
        else:
            skipped += 1
            put_str(u'表单回填失败: %s HTTP %s %s' % (t.get('orderNum'), ok, json.dumps(resp, ensure_ascii=False)[:200] if not isinstance(resp, str) else resp[:200]))
    put_str(u'回填完成: 成功 %d 跳过/失败 %d' % (filled, skipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
