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
HANDLER_NAME = 'easyops'           # 工单 handlerName 兜底（建单必填）
STEP_TASK_NAME = u'识别和发起'      # 表单数据挂靠的流程步骤
DEFAULT_DUTY_GROUP = 'test'        # 兜底值班组名（告警无待响应人时查今日排班）

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
    cfg = {'range': '1d', 'auto_create': u'是', 'alert_level': 'critical', 'alert_time': 20,
           'duty_group': DEFAULT_DUTY_GROUP}

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
        elif key in ('range', 'alert_level', 'duty_group'):
            # py2 str(u中文) 触发 ascii 编码错——已是字符串（str/unicode）直接用
            cfg[key] = val if isinstance(val, _string_types) else str(val)

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
              'source', 'alertRuleId', 'alertReceivers']
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
# 步骤 3：查时间范围内已转单的告警事件（hasOrder=true，2026-09-18 v9 换接口）
# ---------------------------------------------------------------------------
def list_ordered_events(range_sec):
    """查范围内已转工单的告警事件（事件侧反查，替代 incident_management/ticket——
    后者部分版本不可用；hasOrder=true 查询同时返回 orders[].orderNum（工单号）、
    alertReceivers（通知接收人）与事件详情，一次拿全回填所需数据）。

    返回事件列表（每项含 orders/alertReceivers/详情字段）。
    """
    out, page = [], 1
    while page <= 50:
        status, resp = http_json('POST', ALERT_SERVICE_PORT, '/api/v1/monitor_event/not_recover/_search', {
            'onlyNotifyMyself': False,
            'page': page, 'page_size': 100,
            'st': 'now-%dd' % max(1, range_sec // 86400) if range_sec >= 86400 else 'now-1d',
            'et': '',
            'displayNameEnabled': True,
            'withCurrentStepUsers': True,
            'hasOrder': True,
            'fields': ['eventId', 'batchId', 'startTime', 'time', 'level', 'objectId',
                       'instanceId', 'target', 'originContent', 'originTitle', 'metricName',
                       'responder', 'alertReceivers', 'notifies', 'orders'],
            'query': {'isGroup': False, 'type': 'alert',
                      'status': {'$nin': ['block', 'inhibition', 'group']}, '$and': []},
        })
        if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
            raise RuntimeError(u'查询已转单事件失败: HTTP %s %s' % (status, resp))
        data = resp.get('data') or {}
        lst = data.get('list') or []
        out.extend(lst)
        total = int(data.get('total') or 0)
        if not lst or len(out) >= total or page >= 50:
            break
        page += 1
    # st 只支持 now-Nd 天粒度兜底——内存过滤 startTime 精确到 range_sec
    now = int(time.time())
    return [ev for ev in out if now - int(ev.get('startTime') or 0) <= range_sec]


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


def build_event_detail_index(range_sec):
    """历史事件索引：eventId → 事件详情（表单表格行级数据源）。

    表格每行对齐【该条告警】自己的内容（信息/等级/资源/时间），
    不用工单级聚合值——同一工单挂多条告警时各行不同。
    """
    idx = {}
    page = 1
    while page <= 20:                                    # 上限 20 页保护
        status, resp = http_json('POST', ALERT_SERVICE_PORT, '/api/v1/monitor_event/_search', {
            'page': page, 'page_size': 300, 'st': '-%d' % range_sec,
            'fields': ['eventId', 'responder', 'originContent', 'originTitle',
                       'target', 'level', 'startTime', 'objectId', 'instanceId'],
        })
        if status != 200 or not isinstance(resp, dict):
            break
        data = resp.get('data') or {}
        lst = data.get('list') or []
        if not lst:
            break
        for ev in lst:
            idx[ev.get('eventId') or ev.get('_id')] = ev
        if page * 300 >= int(data.get('total') or 0):
            break
        page += 1
    return idx


def lookup_duty_members(group_name, date_str):
    """值班组【当日】值班人——duty_group_config v2 search。

    ⚠️date 传 YYYY-MM-DD 时后端仍可能返回整月配置（.26 实测）——须按 cfg.date
    精确过滤到当日；多班次按【当前时刻】选在班班次（白班 08:00~19:00 样式），
    取该班次 users + leader 去重。

    :param group_name: 值班组名（兜底入参）
    :param date_str: YYYY-MM-DD
    :return: 值班人 name 列表（去重保序）；查不到返回 []
    """
    if not group_name:
        return []
    status, resp = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v2/duty_group_config/search', {
        'groupName': group_name, 'date': date_str,
    })
    if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
        put_str(u'值班组查询失败: %s HTTP %s' % (group_name, status))
        return []
    now_hm = time.strftime('%H:%M')

    def _in_shift(duty_time):
        """dutyTime "08:00~19:00"（00:00~00:00=全天）→ 当前是否在班。"""
        try:
            a, b = (duty_time or '').split('~')
            ah, am = [int(x) for x in a.strip().split(':')]
            bh, bm = [int(x) for x in b.strip().split(':')]
        except ValueError:
            return True                     # 解析失败视为在班（宽松）
        start, end, now = ah * 60 + am, bh * 60 + bm, int(now_hm[:2]) * 60 + int(now_hm[3:])
        if start == 0 and end == 0:
            return True                     # 全天班
        if start <= end:
            return start <= now < end
        return now >= start or now < end    # 跨夜班（19:00~08:00）

    members = []
    for cfg in (resp.get('data') or {}).get('list') or []:
        if (cfg.get('date') or '') != date_str:
            continue                        # 后端返回整月时只取当日
        for shift in (cfg.get('dutyShiftConf') or []):
            if not _in_shift(shift.get('dutyTime')):
                continue                    # 只取当前在班班次
            for u in (shift.get('users') or []):
                n = (u.get('name') or '').strip()
                if n and n not in members:
                    members.append(n)
            for l in (shift.get('leader') or []):
                n = (l.get('name') or '').strip()
                if n and n not in members:
                    members.append(n)
    return members


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


def build_form_data(ticket, responder_names, event_idx=None):
    """工单详情 → 表单 formData 结构（[{key:容器, values:[{控件:值}]}]）。

    控件赋值协议（objects.yaml#itsm_form_component「formData 控件赋值协议」）：
    SELECT 单选传 {key,label,value} 对象；COMMONDATE 传 RFC3339 串；LINK 传 {href,label}。
    :param responder_names: 处理人列表（告警待响应人去重合并；空则值班组兜底，由调用方决定）
    :param event_idx: eventId → 事件详情索引；表格行优先取【该条告警】自己的
                      信息/等级/资源/时间（工单挂多告警时各行不同），索引缺失时回退工单级值。
    """
    event_idx = event_idx or {}
    lv_int = ticket.get('level')
    # SELECT 控件 key 对齐表单 extraProps.items（key→label/value）
    def _enum(key, label_value):
        return {'key': key, 'label': label_value, 'value': label_value}

    p_map = {2: _enum('p1', u'P1'), 1: _enum('p2', u'P2'), 0: _enum('p4', u'P4')}
    priority_map = {2: _enum('urgent', u'紧急'), 1: _enum('urgent', u'紧急'), 0: _enum('normal', u'普通')}
    handler_names = responder_names or [HANDLER_NAME]
    # 事件 level(str) → 表格「等级」SELECT 枚举
    ev_level_enum = {u'critical': _enum('critical', u'严重'), u'warning': _enum('warning', u'警告'),
                     u'info': _enum('notice', u'通知')}
    ticket_resource = ticket.get('resource') or {}
    rows = []
    for al in ticket.get('alertList') or []:
        ev = event_idx.get(al.get('eventId')) or {}
        # 行级：优先事件自己的内容，缺失回退工单级
        info = (ev.get('originContent') or ev.get('originTitle')
                or ticket.get('title') or '')
        ev_lv = ((ev.get('level') or '').lower()
                 if ev.get('level') else '')
        rows.append({
            'alertTime': rfc3339(al.get('startTime') or ev.get('startTime')),
            'alertLevel': ev_level_enum.get(ev_lv) or
                          {2: _enum('critical', u'严重'), 1: _enum('warning', u'警告'),
                           0: _enum('notice', u'通知')}.get(lv_int, _enum('notice', u'通知')),
            'alertResource': ev.get('target') or ticket_resource.get('resourceName', ''),
            'alertInfo': info,
            'alertSource': u'统一数据告警',
            'alertUrl': {'label': u'查看告警', 'href': '/next/events/%s/detail' % (al.get('eventId') or '')},
            'cmdbURL': {'label': u'查看实例', 'href': '/next/next-cmdb-instance-management/next/%s/instance/%s' % (
                ev.get('objectId') or ticket_resource.get('objectId', 'HOST'),
                ev.get('instanceId') or ticket_resource.get('resourceId', ''))},
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

    # 步骤 1+2：自动转工单
    # （防重：_batch 成功即消费事件移出 not_recover，天然幂等）
    if cfg['auto_create'] == u'是':
        events = search_not_recover(range_sec, cfg['alert_level'], cfg['alert_time'] * 60)
        put_str(u'待转工单告警数: %d' % len(events))
        ok, fail = batch_create_tickets(events)
        put_str(u'转工单完成: 成功 %d 失败 %d' % (ok, fail))
    else:
        put_str(u'自动转工单=否，跳过检索与建单')

    # 全量事件索引：eventId → 事件详情——表格行级数据源
    event_idx = build_event_detail_index(range_sec)

    # 值班组兜底（懒查：只在事件缺接收人时用）
    _duty_cache = {}

    def _resolve_handlers(ev):
        """告警通知接收人 alertReceivers（去重保序，2026-09-18 v9 主来源）
        → 空则值班组当日排班 → 仍空 HANDLER_NAME。"""
        names = []
        for r in (ev.get('alertReceivers') or []):
            n = (r.get('name') or '').strip()
            if n and n not in names:
                names.append(n)
        if names:
            return names
        dg = cfg.get('duty_group') or ''
        if dg not in _duty_cache:
            _duty_cache[dg] = lookup_duty_members(dg, time.strftime('%Y-%m-%d')) if dg else []
        if _duty_cache[dg]:
            put_str(u'告警无接收人，兜底值班组 %s: %s' % (dg, ','.join(_duty_cache[dg])))
            return _duty_cache[dg]
        return []

    # 步骤 3：查范围内已转单事件（v9：hasOrder=true 事件侧反查，含工单号/接收人/详情）
    events = list_ordered_events(range_sec)
    put_str(u'范围内已转单告警数: %d' % len(events))

    # 步骤 4+5：按事件回填表单（一事件一工单，orders[0] 即工单号）
    filled, skipped = 0, 0
    for ev in events:
        orders = ev.get('orders') or []
        order_num = orders[0].get('orderNum') if orders else ''
        if not order_num:
            skipped += 1
            put_str(u'事件无关联工单号: %s' % ev.get('eventId'))
            continue
        ticket_like = {
            'orderNum': order_num,
            'level': ALERT_LEVEL_TO_INT.get((ev.get('level') or u'info').lower(), 0),
            'title': ev.get('originContent') or ev.get('originTitle') or '',
            'resource': {'resourceName': ev.get('target') or '',
                         'objectId': ev.get('objectId') or 'HOST',
                         'resourceId': ev.get('instanceId') or ''},
            'alertList': [{'eventId': ev.get('eventId'), 'startTime': ev.get('startTime'),
                           'time': ev.get('time'), 'batchId': ev.get('batchId')}],
        }
        pi = find_process_instance(ticket_like)
        if not pi:
            skipped += 1
            put_str(u'未找到流程实例: %s' % order_num)
            continue
        step = find_identify_step(pi.get('instanceId'))
        if not step:
            skipped += 1
            put_str(u'未找到识别和发起步骤: %s' % pi.get('instanceId'))
            continue
        # 事件详情优先本事件对象（hasOrder 查询已带），索引兜底
        ev_detail = dict(ev)
        ev_detail.setdefault('eventId', ev.get('eventId'))
        event_idx[ev.get('eventId')] = ev_detail
        ok, resp = fill_step_form(step['instanceId'], build_form_data(ticket_like, _resolve_handlers(ev), event_idx))
        if ok:
            filled += 1
            put_str(u'表单回填成功: %s -> step %s' % (order_num, step['instanceId']))
        else:
            skipped += 1
            put_str(u'表单回填失败: %s HTTP %s %s' % (order_num, ok, json.dumps(resp, ensure_ascii=False)[:200] if not isinstance(resp, str) else resp[:200]))
    put_str(u'回填完成: 成功 %d 跳过/失败 %d' % (filled, skipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
