#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：告警处理（读取 / 导出 CSV / 删除 / columndb CRUD）

数据链路（data_exchange :8152 直连，org+user header 免 cookie）：
    库   = <org>（如 1888）
    表   = monitor_event@EASYOPS【默认·历史告警·全状态含已恢复，按月分 partition】
           / monitor_event_last@EASYOPS（当前告警·活跃热视图，恢复后行被移走）
    时间 = time 字段【毫秒】时间戳

方法（仿 sdk/easyops_client.py 写法，class + internal 直连）：
    search_alerts()            检索（filter 精确 + $gte/$lte，skip/limit 翻页）
    count_alerts()             计数
    insert_alerts()            插入（tsdb_column/insert）
    update_alerts_by_filter()  按 filter 批量更新
    update_alert_by_row_id()   按 _row_id 更新（data 每行须带 _row_id）
    upsert_alerts()            按搜索键 upsert
    delete_alerts()            按 filter 删除（delete_by_filter）
    export_csv()               全字段 CSV 导出（utf-8 + BOM，Excel 友好）

入参（agent 平台注入 / CLI k=v 双兜底）：
    action      必填，枚举：导出 / 删除（CLI 另支持 查询）
    time_range  时间范围，\d+[y|m|d]（如 30d/6m/1y），不填=所有时间
    export_dir  导出位置，默认 /tmp/easyops/alert_export
    table       数据表，枚举 历史告警（默认·全状态）/ 当前告警（仅活跃）
    status      可选，告警状态过滤（如 unsent/sent）
    level       可选，告警级别过滤（info/warning/critical）
    confirm     删除二次确认（删除操作必须显式 confirm=是/true 才执行；
                删除自动联动清理另一张表——活跃告警两表并存防残影）

运行环境：EasyOps agent（py2）/ 编排侧 py3。stdlib only。
输出：PutStr 回吐进度、统计与导出文件路径。
"""
import csv
import json
import logging
import os
import re
import sys
import time

IS_PY2 = sys.version_info[0] == 2

if IS_PY2:
    # py2 兜底：json.dumps(ensure_ascii=False) 遇「unicode+非ASCII bytes 混树」会
    # UnicodeDecodeError（告警转事件工单 v2.4 实测坑）——统一按 utf-8 隐式解码。
    reload(sys)
    sys.setdefaultencoding('utf-8')
    import httplib as _http_client
    from StringIO import StringIO
else:
    import http.client as _http_client
    from io import StringIO

try:
    _string_types = (str, unicode)  # noqa: F821  (py2)
except NameError:
    _string_types = (str,)          # py3

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('alert_tool')

# ---------------------------------------------------------------------------
# 常量（源码定案：alert_service/internal/monitoreventop/monitor_event.go:45-48）
# ---------------------------------------------------------------------------
DATA_EXCHANGE_PORT = 8152          # logic.data_exchange
EVENT_LAST_TABLE = 'monitor_event_last@EASYOPS'   # 当前告警（活跃热视图，恢复后行被移走）
EVENT_HISTORY_TABLE = 'monitor_event@EASYOPS'     # 全量历史告警（含未恢复+已恢复，按月分 partition）

# CSV 全量表头（monitor_event_last@EASYOPS 实测字段全集，48 列）
CSV_COLUMNS = [
    'eventId', 'batchId', 'alertId', 'trackId', 'type', 'source', 'org',
    'level', 'status', 'isRecover', 'recoverType', 'isGroup', 'isNotify',
    'notifyBlock', 'blockStatus', 'operatingStatus', 'currentStep', 'currentStepV2',
    'subject', 'originTitle', 'originContent', 'content',
    'target', 'resource', 'objectId', 'instanceId', 'instance',
    'appIds', 'appSystemIds', 'businessIds', 'serviceIds', 'serviceSets',
    'alertRuleId', 'alertRuleVersion', 'ruleId', 'strategyType',
    'metricName', 'metricNames', 'metricValue', 'metricUnit',
    'metricThreshold', 'metricThresholdComparator', 'metricThresholdValue',
    'metrics', 'triggeredCondition', 'context',
    'alertCount', 'alertDuration', 'alertDims', 'alertDimIndex',
    'startTime', 'time', 'notifyTime', 'processTime', 'insertTime',
    'responseTime', 'suspendTime', 'suspendEndTime',
    'responder', 'handlers', 'notifies', 'relatedMetricData',
    '_row_id',
]

# CSV 摘要视图（复杂结构压 JSON，时间戳转可读）
CSV_RENDERERS = {
    'startTime': lambda v: fmt_ms(v),
    'time': lambda v: fmt_ms(v),
    'notifyTime': lambda v: fmt_sec(v),
    'processTime': lambda v: fmt_sec(v),
    'insertTime': lambda v: fmt_sec(v),
}


def fmt_ms(v):
    """毫秒时间戳 -> 可读（空值原样）。"""
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(v) / 1000 + 8 * 3600)) if v else (v or '')


def fmt_sec(v):
    """秒时间戳 -> 可读（空值原样）。"""
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(v) + 8 * 3600)) if v else (v or '')


class AlertToolClient(object):
    """EasyOps 告警处理客户端（columndb via data_exchange，internal 直连）。

    :param base_url: data_exchange 地址（如 http://192.168.110.26:8152）；
                     默认取 env EASYOPS_DATA_EXCHANGE_URL / EASYOPS_CMDB_BACKEND_URL host 拼 8152
    :param org/user: 请求头（默认取 env EASYOPS_ORG / EASYOPS_USER）
    :param host:      Host 头（IP 直连设 admin.easyops.local，网关按 Host 路由）
    :param timeout:   HTTP 超时秒
    """

    def __init__(self, base_url=None, org=None, user=None, host=None, timeout=30):
        self.timeout = timeout
        self.host = host or 'admin.easyops.local'
        # 解析优先级（agent 沙箱实测）：
        # ① 显式参数 → ② 平台注入的【全局变量】EASYOPS_DATA_EXCHANGE_URL / EASYOPS_CMDB_HOST /
        #    EASYOPS_CMDB_SERVICE_HOST（tool_service internal.param.default.yaml 注入，ip:port 形态，
        #    CMDB 与 data_exchange 同机部署时借用其 host 拼 8152）→ ③ 同名 env → ④ 127.0.0.1
        g = globals()
        base = base_url
        if not base:
            for var in ('EASYOPS_DATA_EXCHANGE_URL', 'EASYOPS_CMDB_HOST', 'EASYOPS_CMDB_SERVICE_HOST'):
                v = g.get(var) or os.environ.get(var, '')
                if isinstance(v, _string_types) and v.strip():
                    base = v.strip()
                    break
        if not base:
            for var in ('EASYOPS_CMDB_BACKEND_URL', 'EASYOPS_HOST'):
                v = os.environ.get(var, '')
                if v:
                    base = v
                    break
        if not base:
            base = '127.0.0.1'
        base = base.replace('http://', '').replace('https://', '').split(':')[0].strip()
        base = 'http://%s:%d' % (base, DATA_EXCHANGE_PORT)
        self.base_url = base
        g_org = g.get('EASYOPS_ORG')
        self.org = org if org not in (None, '') else (g_org if g_org not in (None, '') else os.environ.get('EASYOPS_ORG', ''))
        g_user = g.get('EASYOPS_USER')
        self.user = user if user not in (None, '') else (g_user if g_user not in (None, '') else os.environ.get('EASYOPS_USER', 'easyops'))
        self.database = str(self.org)              # 库名 = org（源码 fmt.Sprintf("%d", org)）

    # ------------------------------------------------------------------
    # HTTP 基础层
    # ------------------------------------------------------------------
    def _request(self, method, path, body=None):
        """通用请求。返回 (status, resp_dict_or_text)。非 0 code 抛 RuntimeError。"""
        u = self.base_url.split('//', 1)[1]
        hp = u.split('/', 1)[0]
        h, p = hp.split(':')[0], int(hp.split(':')[1]) if ':' in hp else 80
        conn = _http_client.HTTPConnection(h, p, timeout=self.timeout)
        data = json.dumps(body) if body is not None else None
        headers = {'org': str(self.org), 'user': str(self.user),
                   'Host': self.host, 'Content-Type': 'application/json'}
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
        finally:
            conn.close()
        text = raw.decode('utf-8', 'replace')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = text
        if status != 200:
            raise RuntimeError(u'HTTP %s %s %s' % (status, path, text[:200]))
        if isinstance(parsed, dict):
            code = parsed.get('code')
            if code not in (0, None):
                inner = (parsed.get('data') or {})
                inner_code = inner.get('code') if isinstance(inner, dict) else None
                if inner_code not in (0, None):
                    raise RuntimeError(u'code %s: %s %s' % (
                        inner_code, inner.get('message') or '', path))
        return status, parsed

    def _data(self, resp):
        """剥双层 wrapper：外层 {code,data} → 内层 {code,data/total/...}。"""
        d = resp.get('data') if isinstance(resp, dict) else resp
        if isinstance(d, dict):
            return d.get('data') if 'data' in d else d
        return d

    # ------------------------------------------------------------------
    # 检索 / 计数
    # ------------------------------------------------------------------
    def search_alerts(self, filter=None, start_time=0, end_time=None, table=None,
                      fields=None, sorts=None, limit=1000, max_rows=10000):
        """检索告警（tsdb_column/search-with-skip）。filter 支持精确值与
        {'$gte'/'$lte'/'$in'...} 操作符（columndb filter 语义）；时间【毫秒】。

        :return: (rows, total)——rows 逐页拉全（受 max_rows 上限保护）
        """
        table = table or EVENT_HISTORY_TABLE
        et = end_time if end_time is not None else 9007199254740991
        rows, skip, total = [], 0, None
        while len(rows) < max_rows:
            body = {'database': self.database, 'object_ids': [table],
                    'start_time': int(start_time), 'end_time': int(et),
                    'skip': skip, 'limit': limit,
                    'fields': fields or ['*'], 'without_total': skip > 0}
            if filter:
                body['filter'] = filter
            if sorts:
                body['sorts'] = sorts
            _, resp = self._request('POST', '/api/v1/data_exchange/tsdb_column/search-with-skip', body)
            inner = resp.get('data') or {}
            if total is None:
                total = int(inner.get('total') or 0)
            page_rows = inner.get('data') or []
            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < limit:
                break
            skip += limit
        return rows[:max_rows], total or len(rows)

    def count_alerts(self, filter=None, start_time=0, end_time=None, table=None):
        """计数（tsdb_column/count）。"""
        table = table or EVENT_HISTORY_TABLE
        et = end_time if end_time is not None else 9007199254740991
        body = {'database': self.database, 'object_ids': [table],
                'start_time': int(start_time), 'end_time': int(et)}
        if filter:
            body['filter'] = filter
        _, resp = self._request('POST', '/api/v1/data_exchange/tsdb_column/count', body)
        inner = resp.get('data') or {}
        return int(inner.get('count') or 0)

    # ------------------------------------------------------------------
    # 写：insert / update / upsert / delete
    # ------------------------------------------------------------------
    def insert_alerts(self, records, table=None):
        """插入/覆盖告警行（upsert_by_search_keys，eventId 锚定——.26 实测唯一可靠
        写入路径：tsdb_column/insert 只进 tmp 表有 flush 延迟不可立查）。

        :param records: list[dict]——必填列 batchId/alertId/eventId；时间字段双轨：
                        time=毫秒、startTime/notifyTime/processTime/insertTime=秒(Int32)
                        （缺省自动按当前时间补齐）；缺 batchId 等必填列会 300313
        :return: (insert_count, update_count)
        """
        if not records:
            return 0, 0
        now_ms = int(time.time() * 1000)
        now_s = now_ms // 1000
        rows = []
        for r in records:
            row = dict(r)
            if not row.get('time'):
                row['time'] = now_ms
            for sec_field in ('startTime', 'notifyTime', 'processTime', 'insertTime'):
                if not row.get(sec_field):
                    row[sec_field] = now_s
            rows.append(row)
        _, resp = self._request('PUT', '/api/v1/data_exchange/tsdb_column/upsert_by_search_keys', {
            'database': self.database, 'object_id': table or EVENT_HISTORY_TABLE,
            'search_keys': ['eventId'], 'start_time': 0, 'end_time': 9007199254740991,
            'data': rows})
        inner = resp.get('data') or {}
        return int(inner.get('insert_count') or 0), int(inner.get('update_count') or 0)

    def update_alerts_by_filter(self, filter, update_data, table=None):
        """按 filter 批量更新（PUT tsdb_column/update_by_filter）。"""
        _, resp = self._request('PUT', '/api/v1/data_exchange/tsdb_column/update_by_filter', {
            'database': self.database, 'object_id': table or EVENT_HISTORY_TABLE,
            'filter': filter, 'update_data': update_data})
        inner = resp.get('data') or {}
        return int(inner.get('update_count') or 0)

    def update_alert_by_row_id(self, rows, table=None):
        """按 _row_id 更新（PUT tsdb_column/update_by_id_v2）。

        :param rows: list[dict]——每行必须带 _row_id + 要改的字段
        :return: (update_count, update_fail_count)
        """
        _, resp = self._request('PUT', '/api/v1/data_exchange/tsdb_column/update_by_id_v2', {
            'database': self.database, 'object_id': table or EVENT_HISTORY_TABLE,
            'data': rows})
        inner = resp.get('data') or {}
        return int(inner.get('update_count') or 0), int(inner.get('update_fail_count') or 0)

    def upsert_alerts(self, data, search_keys=None, table=None):
        """按搜索键 upsert（PUT tsdb_column/upsert_by_search_keys）。

        :param search_keys: 匹配键字段名列表（默认 ['eventId']）
        :param data: list[dict] 待写入行（必填列 batchId/alertId/eventId，时间双轨）
        :return: (insert_count, update_count)
        """
        _, resp = self._request('PUT', '/api/v1/data_exchange/tsdb_column/upsert_by_search_keys', {
            'database': self.database, 'object_id': table or EVENT_HISTORY_TABLE,
            'search_keys': search_keys or ['eventId'],
            'start_time': 0, 'end_time': 9007199254740991, 'data': data})
        inner = resp.get('data') or {}
        return int(inner.get('insert_count') or 0), int(inner.get('update_count') or 0)

    def delete_alerts(self, filter, table=None):
        """按 filter 删除（POST tsdb_column/delete_by_filter）。

        ⚠️物理删，不可恢复。返回 delete_count。
        """
        _, resp = self._request('POST', '/api/v1/data_exchange/tsdb_column/delete_by_filter', {
            'database': self.database, 'object_id': table or EVENT_HISTORY_TABLE,
            'filter': filter})
        inner = resp.get('data') or {}
        return int(inner.get('delete_count') or 0)

    # ------------------------------------------------------------------
    # CSV 导出
    # ------------------------------------------------------------------
    def export_csv(self, rows, export_dir):
        """全字段 CSV 导出。复杂结构（dict/list）压 JSON；时间戳转可读。

        沙箱以 nobody 运行，/tmp 一级目录可能无写权——逐级回退：
        指定目录 → 脚本工作目录（agent 缓存目录，nobody 可写）→ /tmp。
        :return: 文件绝对路径
        """
        candidates = []
        d = (export_dir or '').strip()
        if d:
            candidates.append(d)
        candidates.append(os.path.abspath(os.path.dirname(os.path.realpath(__file__))))
        candidates.append(os.getcwd())
        candidates.append('/tmp')
        path = None
        errs = []
        for cand in candidates:
            try:
                if not os.path.isdir(cand):
                    os.makedirs(cand)
                path = os.path.join(cand, 'alerts_%s.csv' % time.strftime('%Y%m%d_%H%M%S'))
                with open(path, 'wb' if IS_PY2 else 'w') as f:
                    if not IS_PY2:
                        f.write(u'﻿')           # BOM（Excel 中文）
                    writer = csv.writer(f)
                    cols = list(CSV_COLUMNS)
                    for r in rows:
                        for k in r:
                            if k not in cols:
                                cols.append(k)
                    writer.writerow([c for c in cols])
                    for r in rows:
                        out = []
                        for c in cols:
                            v = r.get(c, '')
                            renderer = CSV_RENDERERS.get(c)
                            if renderer:
                                v = renderer(v)
                            elif isinstance(v, (dict, list, tuple)):
                                v = json.dumps(v, ensure_ascii=False)
                            out.append(u'' if v is None else v)
                        writer.writerow(out)
                break
            except OSError as e:
                errs.append(u'%s: %s' % (cand, e))
                path = None
        if path is None:
            raise RuntimeError(u'导出目录均不可写: %s' % '; '.join(errs))
        return path


# ---------------------------------------------------------------------------
# 入参解析（平台注入 globals + env + argv k=v 三兜底，同 alert2event 家族）
# ---------------------------------------------------------------------------
def parse_range(range_str):
    """时间范围解析：\\d+[y|m|d] → (起始毫秒, 描述)。空 → (0, '所有时间')。"""
    s = (range_str or '').strip()
    if not s:
        return 0, u'所有时间'
    m = re.match(r'^(\d+)([ymd])$', s)
    if not m:
        raise ValueError(u'时间范围格式非法: %r（应为 30d/6m/1y）' % (range_str,))
    n, unit = int(m.group(1)), m.group(2)
    sec = n * {'y': 365 * 86400, 'm': 30 * 86400, 'd': 86400}[unit]
    return int((time.time() - sec) * 1000), u'%d%s' % (n, unit)


def parse_args(argv):
    cfg = {'action': u'导出', 'time_range': '', 'export_dir': '/tmp/easyops/alert_export',
           'status': '', 'level': '', 'confirm': '', 'table': u'历史告警'}

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
        if key in cfg:
            cfg[key] = val

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


TABLE_CHOICES = {u'历史告警': EVENT_HISTORY_TABLE, u'当前告警': EVENT_LAST_TABLE}


def pick_table(cfg):
    """table 入参 → 实际表名。默认历史告警（全状态含已恢复）；
    当前告警=monitor_event_last（活跃热视图，恢复后行被移走）。"""
    return TABLE_CHOICES.get(cfg.get('table') or u'历史告警', EVENT_HISTORY_TABLE)


def build_filter(cfg, start_ms):
    """入参 → columndb filter。时间【毫秒】$gte；status/level 精确。"""
    f = {}
    if start_ms:
        f['time'] = {'$gte': start_ms}
    if cfg.get('status'):
        f['status'] = cfg['status']
    if cfg.get('level'):
        f['level'] = cfg['level']
    return f


def put_str(msg):
    logger.info(msg)


def main(argv=None):
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    put_str(u'配置: %s' % json.dumps(cfg, ensure_ascii=False))
    client = AlertToolClient()
    start_ms, range_desc = parse_range(cfg.get('time_range'))
    flt = build_filter(cfg, start_ms)
    table = pick_table(cfg)

    action = cfg['action']
    if action == u'查询':
        rows, total = client.search_alerts(flt, table=table)
        put_str(u'告警总数: %s（%s，%s）' % (total, range_desc, cfg.get('table') or u'历史告警'))
        for r in rows[:20]:
            put_str(u'  %s [%s] %s' % (r.get('eventId'), r.get('level'),
                                        (r.get('originContent') or '')[:60]))
        return 0
    if action == u'导出':
        rows, total = client.search_alerts(flt, table=table)
        put_str(u'导出告警: %d/%s 条（%s，%s）' % (len(rows), total, range_desc,
                                                  cfg.get('table') or u'历史告警'))
        path = client.export_csv(rows, cfg.get('export_dir'))
        put_str(u'导出完成: %s（%d 字段 x %d 行）' % (path, len(CSV_COLUMNS), len(rows)))
        PutStr('export_path', path)
        return 0
    if action == u'删除':
        n = client.count_alerts(flt, table=table)
        put_str(u'待删除告警: %d 条（%s，%s）filter=%s' % (n, range_desc,
                                                          cfg.get('table') or u'历史告警',
                                                          json.dumps(flt, ensure_ascii=False)))
        if cfg.get('confirm') not in (u'是', 'true', 'True', '1'):
            put_str(u'未确认（confirm != 是/true）——仅预览未删除。确认请加 confirm=是')
            return 0
        deleted = client.delete_alerts(flt, table=table)
        put_str(u'删除完成: %s %d 条' % (cfg.get('table') or u'历史告警', deleted))
        # 双表清理：活跃告警两表并存（last=热视图，历史=全量），单删一张另一张留残影。
        # 删历史 → 补删 last 同 filter；删 last → 补删历史。count=0 视为无需补删。
        other = EVENT_LAST_TABLE if table == EVENT_HISTORY_TABLE else EVENT_HISTORY_TABLE
        n_other = client.count_alerts(flt, table=other)
        if n_other:
            d_other = client.delete_alerts(flt, table=other)
            put_str(u'联动清理: %s %d/%d 条' % (u'当前告警' if other == EVENT_LAST_TABLE else u'历史告警',
                                                d_other, n_other))
        else:
            put_str(u'联动表无匹配（%s 0 条），无需清理' % (u'当前告警' if other == EVENT_LAST_TABLE else u'历史告警'))
        return 0
    put_str(u'未知操作模式: %s（支持 导出/删除/查询）' % action)
    return 1


if IS_PY2:
    def PutStr(name, value):     # noqa: F811  agent 平台输出通道（py2 agent 注入）
        sys.stdout.write('%s=%s\n' % (name, value))
        sys.stdout.flush()
else:
    def PutStr(name, value):     # noqa: F811
        print('%s=%s' % (name, value))


if __name__ == '__main__':
    sys.exit(main())
