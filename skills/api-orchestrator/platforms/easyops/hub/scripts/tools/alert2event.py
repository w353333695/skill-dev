#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：告警转事件工单（未恢复告警 → 构建表单 → 发起工单）

与「告警转故障工单」（alert2ticket，走 _batch 建单+表单回填两步）的区别：
本工具【一步到位】——构建好识别和发起表单（等级/优先级/处理人/批次/关联告警行），
直接 StartProcessInstanceV2 发起（事件处理服务），无需事后回填。

入参：
    range            查询时间范围，字符串，\d+[m,h,d]（如 30m/2h/1d），默认 1d
    auto_create      是否自动转工单，枚举 是/否，默认 是
    alert_level      自动转工单告警级别，枚举 info/warning/critical，默认 critical（含及以上）
    alert_time       自动转工单告警时间（分钟），整数，默认 20（发生时间已超过该时长）
    duty_group       兜底值班组名称，字符串，默认 test（告警无接收人时查当日排班）

运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。
输出：PutStr 回吐进度与统计。
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

if IS_PY2:
    import httplib as _http_client
else:
    import http.client as _http_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('alert2event')

ALERT_SERVICE_PORT = 8131
FLOWABLE_PORT = 8134
CMDB_PORT = 8079

# 「事件处理」服务（前端手动提单同款路径）
SERVICE_ID = '65be037e02d51'
DEFAULT_DUTY_GROUP = 'test'

ALERT_LEVEL_TO_INT = {u'info': 0, u'warning': 1, u'critical': 2}
LEVEL_P = {"critical": {"key": "p1", "label": "P1", "value": "P1"},
           "warning": {"key": "p2", "label": "P2", "value": "P2"},
           "info": {"key": "p4", "label": "P4", "value": "P4"}}
PRIORITY = {"critical": {"key": "urgent", "label": "紧急", "value": "紧急"},
            "warning": {"key": "urgent", "label": "紧急", "value": "紧急"},
            "info": {"key": "normal", "label": "普通", "value": "普通"}}
LEVEL_CN = {"critical": {"key": "critical", "label": "严重", "value": "严重"},
            "warning": {"key": "warning", "label": "警告", "value": "警告"},
            "info": {"key": "notice", "label": "通知", "value": "通知"}}


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


def parse_range(range_str):
    m = re.match(r'^(\d+)([mhd])$', (range_str or '').strip())
    if not m:
        raise ValueError(u'查询时间范围格式非法: %r（应为 30m/2h/1d）' % (range_str,))
    n, unit = int(m.group(1)), m.group(2)
    return n * {'m': 60, 'h': 3600, 'd': 86400}[unit]


def parse_args(argv):
    cfg = {'range': '1d', 'auto_create': u'是', 'alert_level': 'critical',
           'alert_time': 20, 'duty_group': DEFAULT_DUTY_GROUP}

    def _coerce(key, val):
        # py2 平台注入 bytes 统一转 unicode（消 UnicodeWarning）
        if IS_PY2 and isinstance(val, str):
            try:
                val = val.decode('utf-8')
            except UnicodeDecodeError:
                pass
        if isinstance(val, _string_types):
            val = val.strip()
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
            elif val in (u'是', u'否'):
                cfg[key] = val
            else:
                cfg[key] = u'是' if val in ('true', 'True', '1') else u'否'
        elif key in ('range', 'alert_level', 'duty_group'):
            cfg[key] = val if isinstance(val, _string_types) else str(val)

    g = globals()
    for k in cfg:
        if k in g and g[k] not in (None, ''):
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


# ---------------------------------------------------------------------------
# 步骤 1：检索未恢复告警（hasOrder=false——未转单的）
# ---------------------------------------------------------------------------
def search_not_recover(range_sec, min_level, older_than_sec):
    order = {u'info': 0, u'warning': 1, u'critical': 2}
    fields = ['_id', 'eventId', 'batchId', 'startTime', 'time', 'level', 'objectId',
              'instanceId', 'target', 'originContent', 'originTitle', 'metricName',
              'alertReceivers', 'orders']
    out, page = [], 1
    now = int(time.time())
    while page <= 50:
        status, resp = http_json('POST', ALERT_SERVICE_PORT, '/api/v1/monitor_event/not_recover/_search', {
            'onlyNotifyMyself': False,
            'page': page, 'page_size': 300, 'st': 'now-%dd' % max(1, range_sec // 86400),
            'et': '', 'displayNameEnabled': True, 'hasOrder': False,
            'fields': fields,
            'query': {'isGroup': False, 'type': 'alert',
                      'status': {'$nin': ['block', 'inhibition', 'group']}, '$and': []},
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
                continue
            if ev.get('orders'):
                continue                       # 已转单（幂等防重）
            if now - int(ev.get('startTime') or 0) < older_than_sec:
                continue
            out.append(ev)
        total = int(data.get('total') or 0)
        if len(out) >= total or page * 300 >= total:
            break
        page += 1
    return [ev for ev in out if now - int(ev.get('startTime') or 0) <= range_sec]


# ---------------------------------------------------------------------------
# 辅助：处理人（接收人→值班组→easyops）+ USER instanceId
# ---------------------------------------------------------------------------
_USER_CACHE = {}


def lookup_user_instance_id(name):
    if not name or name in _USER_CACHE:
        return _USER_CACHE.get(name, '')
    status, resp = http_json('POST', CMDB_PORT, '/v3/object/USER/instance/_search', {
        'fields': ['instanceId', 'name'], 'page': 1, 'page_size': 5,
        'query': {'name': name}})
    lst = (resp.get('data') or {}).get('list') or [] if isinstance(resp, dict) else []
    _USER_CACHE[name] = lst[0].get('instanceId') if lst else ''
    return _USER_CACHE[name]


def lookup_duty_members(group_name, date_str):
    if not group_name:
        return []
    status, resp = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v2/duty_group_config/search', {
        'groupName': group_name, 'date': date_str})
    if status != 200 or not isinstance(resp, dict) or resp.get('code') not in (0, None):
        return []
    now_hm = time.strftime('%H:%M')

    def _in_shift(duty_time):
        try:
            a, b = (duty_time or '').split('~')
            ah, am = [int(x) for x in a.strip().split(':')]
            bh, bm = [int(x) for x in b.strip().split(':')]
        except ValueError:
            return True
        s, e, n = ah * 60 + am, bh * 60 + bm, int(now_hm[:2]) * 60 + int(now_hm[3:])
        if s == 0 and e == 0:
            return True
        return s <= n < e if s <= e else (n >= s or n < e)

    members = []
    for cfg in (resp.get('data') or {}).get('list') or []:
        if (cfg.get('date') or '') != date_str:
            continue
        for sh in (cfg.get('dutyShiftConf') or []):
            if not _in_shift(sh.get('dutyTime')):
                continue
            for u in (sh.get('users') or []) + (sh.get('leader') or []):
                n = (u.get('name') or '').strip()
                if n and n not in members:
                    members.append(n)
    return members


def resolve_handlers(ev, duty_group, duty_cache):
    """告警通知接收人 → 值班组当日班次 → easyops（含真实 instanceId）。"""
    names = []
    for r in (ev.get('alertReceivers') or []):
        n = (r.get('name') or '').strip()
        if n and n not in names:
            names.append(n)
    if not names and duty_group:
        if duty_group not in duty_cache:
            duty_cache[duty_group] = lookup_duty_members(duty_group, time.strftime('%Y-%m-%d'))
        names = duty_cache[duty_group] or []
    if not names:
        names = ['easyops']
    return [{'instanceId': lookup_user_instance_id(n), 'name': n} for n in names]


# ---------------------------------------------------------------------------
# 步骤 2：构建表单（识别和发起节点 formData，协议同 onload/alert2ticket）
# ---------------------------------------------------------------------------
def fmt_time(ts):
    if not ts:
        return ''
    return time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.gmtime(int(ts) + 8 * 3600))


def build_form_data(ev, handlers):
    lv = (ev.get('level') or u'info').lower()
    row = {
        'alertTime': fmt_time(ev.get('startTime')),
        'alertLevel': LEVEL_CN.get(lv, LEVEL_CN['info']),
        'alertResource': ev.get('target') or '',
        'alertInfo': ev.get('originContent') or ev.get('originTitle') or '',
        'alertSource': ev.get('source') or '',
        'alertUrl': {'label': u'查看告警', 'href': '/next/events/%s/detail' % (ev.get('eventId') or '')},
        'cmdbURL': {'label': u'查看实例', 'href': '/next/next-cmdb-instance-management/next/%s/instance/%s' % (
            ev.get('objectId') or 'HOST', ev.get('instanceId') or '')},
    }
    return json.dumps([
        {'key': 'sec_base', 'values': [{
            'incidentLevel': LEVEL_P.get(lv, LEVEL_P['info']),
            'priority': PRIORITY.get(lv, PRIORITY['info']),
            'incidentType': {'key': 'alert', 'label': u'告警异常', 'value': u'告警异常'},
            'handler': handlers,
            'batchId': [ev.get('batchId')] if ev.get('batchId') else [],
        }]},
        {'key': 'sec_alerts', 'values': [row]},
    ], ensure_ascii=False)


# ---------------------------------------------------------------------------
# 步骤 3：发起工单（StartProcessInstanceV2——一步到位含表单）
# ---------------------------------------------------------------------------
def start_ticket(ev, form_data):
    name = (ev.get('originContent') or ev.get('originTitle') or u'%s 告警' % (ev.get('target') or ''))[:200]
    status, resp = http_json('POST', FLOWABLE_PORT, '/api/flowable_service/v2/process_instance', {
        'serviceId': SERVICE_ID,
        'name': name,
        'visibleRange': 'operator',
        'formData': form_data,
        'handleWay': 'common',
        'source': 'ITSC',
        'isSupervision': False,
        'variables': [{'name': 'pass', 'value': '0'}],
    })
    ok = status == 200 and isinstance(resp, dict) and resp.get('code') in (0, None)
    return ok, resp


def main(argv=None):
    _resolve_conn()
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    put_str(u'配置: %s' % json.dumps(cfg, ensure_ascii=False))
    if cfg['auto_create'] != u'是':
        put_str(u'自动转工单=否，退出')
        return 0
    range_sec = parse_range(cfg['range'])

    events = search_not_recover(range_sec, cfg['alert_level'], cfg['alert_time'] * 60)
    put_str(u'待转工单告警数: %d' % len(events))

    duty_cache = {}
    ok, fail = 0, 0
    for ev in events:
        handlers = resolve_handlers(ev, cfg.get('duty_group') or '', duty_cache)
        form_data = build_form_data(ev, handlers)
        good, resp = start_ticket(ev, form_data)
        if good:
            ok += 1
            pi = (resp.get('data') or {}).get('instanceId') or ''
            put_str(u'发起成功: %s (pi=%s 处理人:%s)' % (
                (ev.get('originContent') or '')[:40], pi, ','.join(h['name'] for h in handlers)))
        else:
            fail += 1
            put_str(u'发起失败: %s HTTP %s %s' % (
                ev.get('eventId'), good, json.dumps(resp, ensure_ascii=False)[:200] if not isinstance(resp, str) else resp[:200]))
    put_str(u'完成: 成功 %d 失败 %d' % (ok, fail))
    return 0


if __name__ == '__main__':
    sys.exit(main())
