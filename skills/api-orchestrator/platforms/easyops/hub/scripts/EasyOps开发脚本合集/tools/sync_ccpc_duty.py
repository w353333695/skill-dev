# -*- coding: utf-8 -*-
"""
EasyOps 工具：同步CCPC值班表（CCPC 值班表 → ITSM 值班组日历配置）

入参：
    ccpc_ip          CCPC 地址，字符串，默认 127.0.0.1（端口固定 8880）
    ccpc_group_id    CCPC 值班组 id，字符串，默认 8882eec490c54bacb382c5e859f20f05
    duty_group_name  EasyOps 值班组名称，字符串，默认 告警值班组
    sync_days        同步今天起 N 天，整数，默认 30

逻辑：
    1) 拉 CCPC 今天起 N 天值班表（/api/dutys/schedule/public）
    2) 动态归纳班次（shiftName → startTime~endTime，不写死白/夜班）
    3) ensure 值班组：无则建（dutyCycle 未来一百年）；班次定义变更则 PUT 更新
    4) 逐日 upsert 日历配置：dutys→users；maintainer+leader→leader
       （已有且人员一致 skip；不一致 PUT；无 POST）

运行环境：EasyOps agent（py2，stdlib only）或编排侧 py3。
鉴权：org/user header 直连后端（免 cookie）。
输出：PutStr 回吐进度与统计（agent 工具模式下可见）。
"""
import datetime
import json
import logging
import os
import sys

if sys.version_info[0] == 2:
    import httplib as _http_client
    import urllib2 as _urllib_request
else:
    import http.client as _http_client
    import urllib.request as _urllib_request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('sync_ccpc_duty')

IS_PY2 = sys.version_info[0] == 2

CCPC_PORT = 8880
FLOWABLE_PORT = 8134               # logic.flowable_service
FLEX_TIME = 5                      # 交接班弹性时间（分钟）

HOST = ''
ORG = ''
USER = ''


def _resolve_conn():
    """运行时解析连接参数（平台 globals 注入 > env；同 alert2ticket 模式）。"""
    global HOST, ORG, USER
    g = globals()
    for var in ('EASYOPS_ITSM_BACKEND_URL', 'EASYOPS_CMDB_BACKEND_URL',
                'EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_HOST'):
        v = g.get(var) or os.environ.get(var, '')
        if v:
            HOST = v.replace('http://', '').replace('https://', '').split(':')[0].strip()
            break
    ORG = str(g.get('EASYOPS_ORG') or os.environ.get('EASYOPS_ORG') or '1888')
    USER = str(g.get('EASYOPS_USER') or os.environ.get('EASYOPS_USER') or 'easyops')


def http_json(method, path, body=None, timeout=30):
    """直连 flowable_service:8134（stdlib，py2/3 兼容）。返回 (status, parsed_json_or_text)。"""
    conn = _http_client.HTTPConnection(HOST, FLOWABLE_PORT, timeout=timeout)
    data = json.dumps(body) if body is not None else None
    headers = {'org': ORG, 'user': USER, 'Host': 'admin.easyops.local',
               'Content-Type': 'application/json'}
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
    finally:
        conn.close()
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def put_str(message):
    logger.info(message)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 纯函数层
# ---------------------------------------------------------------------------
def date_range(n):
    """今天起 n 天 YYYY-MM-DD 列表。"""
    today = datetime.date.today()
    return [(today + datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n)]


def duty_cycle_100y():
    """值班周期：今年 1 月 ~ 今年+100 年 12 月。"""
    y = datetime.date.today().year
    return '%d-01~%d-12' % (y, y + 100)


def analyze_shifts(days):
    """CCPC 响应 → easyops dutyShift 定义列表。

    按 shiftName 归纳 {name → startTime~endTime}；同名不同时段以最后出现为准。
    """
    seen = {}
    order = []
    for day in days or []:
        for shift in day.get('shifts') or []:
            name = shift.get('shiftName') or ''
            if not name:
                continue
            if name not in seen:
                order.append(name)
            seen[name] = '%s~%s' % (shift.get('startTime') or '', shift.get('endTime') or '')
    return [{'name': name, 'dutyTime': seen[name]} for name in order]


def build_shift_conf(day):
    """单日 CCPC 数据 → dutyShiftConf。

    角色映射：dutys→users；maintainer+leader→leader（顺序固定）。
    返回 None 表示该日无数据（跳过）。
    """
    if not day or not day.get('shifts'):
        return None
    conf = []
    for shift in day.get('shifts') or []:
        users, leader = [], []
        for mem in shift.get('members') or []:
            field = mem.get('field')
            uids = [u for u in (mem.get('uids') or []) if u]
            if field == 'dutys':
                users.extend(uids)
            elif field == 'maintainer':
                leader.extend(uids)
            elif field == 'leader':
                leader.extend(uids)
        conf.append({'name': shift.get('shiftName') or '', 'users': users, 'leader': leader})
    return conf


def conf_equal(a, b):
    """dutyShiftConf 深比较（顺序敏感——班次顺序也是配置的一部分）。"""
    return a == b


# ---------------------------------------------------------------------------
# 入参解析（EasyOps 工具入参经 argv：key=value；或模块级调用）
# ---------------------------------------------------------------------------
def parse_args(argv):
    """入参优先级：globals 注入 > env 同名 > argv k=v > 默认值（同 alert2ticket 模式）。"""
    cfg = {'ccpc_ip': '127.0.0.1',
           'ccpc_group_id': '8882eec490c54bacb382c5e859f20f05',
           'duty_group_name': u'告警值班组',
           'sync_days': 30}

    def _coerce(key, val):
        if val in (None, ''):
            return
        if key == 'sync_days':
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                pass
        else:
            cfg[key] = _to_unicode(val).strip() if hasattr(val, 'strip') else str(val)

    g = globals()
    for k in cfg:
        if k in g and g[k] not in (None, ''):
            _coerce(k, g[k])
    for k in cfg:
        _coerce(k, os.environ.get(k) or os.environ.get(k.upper()))
    ti = os.environ.get('EASYOPS_TOOL_INPUT') or (g.get('EASYOPS_TOOL_INPUT') if isinstance(g.get('EASYOPS_TOOL_INPUT'), str) else '')
    if ti:
        try:
            for k, v in (json.loads(ti) or {}).items():
                if k in cfg:
                    _coerce(k, v)
        except ValueError:
            pass
    for a in argv or []:
        if '=' not in a:
            continue
        k, v = a.split('=', 1)
        k = k.lstrip('-').strip()
        if k in cfg:
            _coerce(k, v)
    return cfg


def _to_unicode(v):
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v


# ---------------------------------------------------------------------------
# CCPC 拉取
# ---------------------------------------------------------------------------
def fetch_ccpc(ip, group_id, start, end, fixture=None):
    """拉 CCPC 值班表。fixture 非 None 读样例文件（`response: ` 行），否则 GET。

    返回天数组；非 200 / 非 list 抛 RuntimeError。
    """
    if fixture:
        if not os.path.isfile(fixture):
            raise RuntimeError(u'fixture 文件不存在: %s' % fixture)
        with open(fixture, 'r') as f:
            for line in f:
                if line.startswith('response: '):
                    data = json.loads(line[len('response: '):].strip())
                    return [d for d in data
                            if start <= (d.get('date') or '') <= end]
        raise RuntimeError(u'fixture 无 response 行: %s' % fixture)
    url = 'http://%s:%d/api/dutys/schedule/public?groupId=%s&startDate=%s&endDate=%s' % (
        ip, CCPC_PORT, group_id, start, end)
    if IS_PY2:
        try:
            resp = _urllib_request.urlopen(url, timeout=30)
            raw = resp.read()
            status = resp.getcode()
        except _urllib_request.URLError as e:
            raise RuntimeError(u'CCPC 请求失败 %s: %s' % (url, e))
    else:
        try:
            with _urllib_request.urlopen(url, timeout=30) as resp:
                raw = resp.read()
                status = resp.getcode()
        except _urllib_request.URLError as e:
            raise RuntimeError(u'CCPC 请求失败 %s: %s' % (url, e))
    if status != 200:
        raise RuntimeError(u'CCPC HTTP %s: %s' % (status, url))
    data = json.loads(raw.decode('utf-8', 'replace'))
    if not isinstance(data, list):
        raise RuntimeError(u'CCPC 响应非数组: %r' % type(data))
    return data


# ---------------------------------------------------------------------------
# ensure 值班组
# ---------------------------------------------------------------------------
def ensure_duty_group(name, shifts):
    """查/建/更新值班组。返回 (groupId, 变更描述)。

    无 → 建（dutyCycle 未来一百年，dutyShift=归纳班次，flexTime=5 分钟交接班弹性时间）；
    有且 dutyShift（名称+时段集合）不一致 → PUT 更新 dutyShift（保留 name/dutyCycle）；
    有且 flexTime≠5 → PUT 补设 flexTime（保留其余原值）。
    """
    status, resp = http_json('GET', '/api/flowable_service/v1/duty_group?name=%s' % _url_quote(name))
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        raise RuntimeError(u'查询值班组失败: HTTP %s %s' % (status, _resp_text(resp)))
    lst = (resp.get('data') or {}).get('list') or []
    if not lst:
        body = {'name': name, 'dutyCycle': duty_cycle_100y(), 'status': 'enabled',
                'dutyShift': shifts, 'flexTime': FLEX_TIME,
                'memo': u'sync_ccpc_duty 自动创建'}
        status, resp = http_json('POST', '/api/flowable_service/v1/duty_group', body)
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            raise RuntimeError(u'创建值班组失败: HTTP %s %s' % (status, _resp_text(resp)))
        gid = (resp.get('data') or {}).get('instanceId') or ''
        if not gid:
            raise RuntimeError(u'创建值班组未返回 instanceId: %s' % _resp_text(resp))
        put_str(u'值班组已创建: %s (%s) 班次=%s flexTime=%d' % (
            name, gid, json.dumps(shifts, ensure_ascii=False), FLEX_TIME))
        return gid, 'created'
    group = lst[0]
    gid = group.get('instanceId') or ''
    shifts_diff = sorted_shifts(group.get('dutyShift') or []) != sorted_shifts(shifts)
    flex_diff = group.get('flexTime') != FLEX_TIME
    if shifts_diff or flex_diff:
        body = {'name': group.get('name') or name,
                'dutyCycle': group.get('dutyCycle') or duty_cycle_100y(),
                'status': group.get('status') or 'enabled',
                'dutyShift': shifts,
                'flexTime': FLEX_TIME}
        status, resp = http_json('PUT', '/api/flowable_service/v1/duty_group/%s' % gid, body)
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            raise RuntimeError(u'更新值班组失败: HTTP %s %s' % (status, _resp_text(resp)))
        what = []
        if shifts_diff:
            what.append(u'班次=%s' % json.dumps(shifts, ensure_ascii=False))
        if flex_diff:
            what.append(u'flexTime=%d' % FLEX_TIME)
        put_str(u'值班组已更新: %s (%s)' % (name, u', '.join(what)))
        return gid, 'shifts_updated' if shifts_diff else 'flex_updated'
    return gid, 'unchanged'


def sorted_shifts(shifts):
    """班次集合比较键（名称+时段，排序后比较——组定义顺序非关键）。"""
    return sorted(({'name': s.get('name') or '', 'dutyTime': s.get('dutyTime') or ''}
                   for s in shifts or []),
                  key=lambda x: (x['name'], x['dutyTime']))


def _url_quote(s):
    if IS_PY2:
        import urllib as _u
        return _u.quote(s.encode('utf-8'))
    import urllib.parse as _up
    return _up.quote(str(s))


def _resp_text(resp):
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False)[:300]
    return str(resp)[:300]


# ---------------------------------------------------------------------------
# 逐日 upsert
# ---------------------------------------------------------------------------
def upsert_day(group_id, group_name, date, want_conf):
    """单日配置 upsert。返回 created/updated/skipped/failed:<msg>。

    回读用 v1 search（原始 username 数组）——v2 的 user 增强在用户不存在时
    回填空壳对象 {name:""}，会导致幂等比较永判不等（.26 实测踩坑）。
    """
    status, resp = http_json('POST', '/api/flowable_service/v1/duty_group_config/search',
                             {'groupName': group_name, 'date': date})
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        return 'failed:search HTTP %s %s' % (status, _resp_text(resp))
    existing = None
    for item in (resp.get('data') or {}).get('list') or []:
        if item.get('date') == date:
            existing = item
            break
    if existing is not None:
        have_conf = norm_conf(existing.get('dutyShiftConf') or [])
        if conf_equal(want_conf, have_conf):
            return 'skipped'
        status, resp = http_json('PUT', '/api/flowable_service/v1/duty_group_config/%s'
                                 % existing.get('instanceId'),
                                 {'configId': existing.get('instanceId'), 'date': date,
                                  'status': 0, 'dutyShiftConf': want_conf})
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            return 'failed:update HTTP %s %s' % (status, _resp_text(resp))
        return 'updated'
    status, resp = http_json('POST', '/api/flowable_service/v1/duty_group_config',
                             {'groupId': group_id, 'date': date, 'status': 0,
                              'dutyShiftConf': want_conf})
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        return 'failed:create HTTP %s %s' % (status, _resp_text(resp))
    return 'created'


def norm_conf(conf):
    """v2 search 返回的 dutyShiftConf 归一化（users/leader 可能是对象数组→取 name）。"""
    out = []
    for s in conf or []:
        users = []
        for u in s.get('users') or []:
            users.append(u.get('name') if isinstance(u, dict) else u)
        leader = []
        for l in s.get('leader') or []:
            leader.append(l.get('name') if isinstance(l, dict) else l)
        out.append({'name': s.get('name') or '', 'users': users, 'leader': leader})
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv=None):
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    _resolve_conn()
    put_str(u'配置: %s' % json.dumps(cfg, ensure_ascii=False))

    dates = date_range(cfg['sync_days'])
    start, end = dates[0], dates[-1]

    fixture = os.environ.get('CCPC_FIXTURE') or None
    days = fetch_ccpc(cfg['ccpc_ip'], cfg['ccpc_group_id'], start, end, fixture=fixture)
    put_str(u'CCPC 返回 %d 天 (%s~%s)' % (len(days), start, end))
    by_date = dict((d.get('date'), d) for d in days)

    shifts = analyze_shifts(days)
    if not shifts:
        raise RuntimeError(u'CCPC 数据未归纳出任何班次')
    gid, group_desc = ensure_duty_group(cfg['duty_group_name'], shifts)

    stat = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0}
    for date in dates:
        day = by_date.get(date)
        want_conf = build_shift_conf(day)
        if want_conf is None:
            put_str(u'%s 无CCPC数据，跳过' % date)
            stat['skipped'] += 1
            continue
        result = upsert_day(gid, cfg['duty_group_name'], date, want_conf)
        if result.startswith('failed'):
            stat['failed'] += 1
            put_str(u'%s %s' % (date, result))
        else:
            stat[result] += 1
            if result != 'skipped':
                put_str(u'%s %s' % (date, result))
    put_str(u'同步完成 组=%s(%s) 建=%d 改=%d 跳=%d 败=%d' % (
        cfg['duty_group_name'], group_desc,
        stat['created'], stat['updated'], stat['skipped'], stat['failed']))
    return 0 if stat['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
