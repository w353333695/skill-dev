# -*- coding: utf-8 -*-
"""EasyOps 工具：查看 CMDB 模型监控覆盖和最近执行状态。

输入：
    @agents：HOST cmdbInstances（工具执行目标，不参与统计）
    cmdb_models：CMDB_MODEL@EASYOPS 多选，选中模型实例；也兼容直接传模型 ID

输出：
    monitor_status 表格：模型名称、实例、是否监控、所属监控任务、监控状态、报错。

脚本只读调用 CMDB、资源监控任务和任务状态接口；沙箱运行不需要主机文件权限。
"""
import json
import logging
import os
import re
import sys
import time

IS_PY2 = sys.version_info[0] == 2
if IS_PY2:
    import httplib as _http_client
    import urllib
    import urllib2 as _url_request
else:
    import http.client as _http_client
    import urllib.parse as _url_parse
    import urllib.request as _url_request

try:
    _STRING_TYPES = (str, unicode)
except NameError:
    _STRING_TYPES = (str,)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOGGER = logging.getLogger('monitor_status_check')
CMDB_PORT = 8079
DEFAULT_PAGE_SIZE = 300
MONITOR_BACKEND_PATH = '/api/v1/list-resource-monitor-job'
MONITOR_INSTANCES_BACKEND_PATH = '/api/v1/list-resource-monitor-job-instances'
STATUS_BACKEND_PATH = '/api/v1/job_status/get'
MONITOR_JOB_CONTRACT = 'easyops.api.collector_service.job.ListResourceMonitorJob'
MONITOR_INSTANCES_CONTRACT = 'easyops.api.collector_service.job.ListJobInstances'
STATUS_CONTRACT = 'easyops.api.collector_service.job_status.GetStatus'


def _text(value):
    if value is None:
        return u'' if IS_PY2 else ''
    if IS_PY2:
        if isinstance(value, unicode):
            return value
        if isinstance(value, str):
            try:
                return value.decode('utf-8')
            except Exception:
                return value.decode('utf-8', 'replace')
        try:
            return unicode(value)
        except Exception:
            return unicode(str(value), 'utf-8', 'replace')
    return str(value)


def _output_text(value):
    """PutStr/PutRow 在 py2 agent 中要求 utf-8 bytes，禁止隐式 ascii 编码。"""
    text = _text(value)
    if IS_PY2 and isinstance(text, unicode):
        return text.encode('utf-8')
    return text


def _log_text(value):
    return _output_text(value)


def _json_load(value, default=None):
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return default
    text = _text(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _input(name, default=None):
    value = globals().get(name)
    if value not in (None, ''):
        return value
    value = os.environ.get('EASYOPS_TOOL_' + name.upper())
    if value not in (None, ''):
        return value
    raw = os.environ.get('EASYOPS_TOOL_INPUT')
    data = _json_load(raw, {}) or {}
    if isinstance(data, dict) and data.get(name) not in (None, ''):
        return data.get(name)
    for item in sys.argv[1:]:
        if '=' in item:
            key, val = item.lstrip('-').split('=', 1)
            if key == name:
                return val
    return default


def _ids(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        parsed = _json_load(value)
        if isinstance(parsed, list):
            items = parsed
        else:
            items = _text(value).strip('[]').split(',')
    result = []
    for item in items:
        if isinstance(item, dict):
            item = item.get('instanceId') or item.get('id') or item.get('objectId') or item.get('modelId')
        item = _text(item).strip().strip('"\'')
        if item and item not in result:
            result.append(item)
    return result


def _host(value):
    value = _text(value or '')
    value = re.sub(r'^https?://', '', value).split('/', 1)[0]
    return value.split(':', 1)[0] or '127.0.0.1'


def _base_url():
    for key in ('EASYOPS_CMDB_FRONTEND_URL', 'EASYOPS_OPENAPI_GATEWAY_URL', 'EASYOPS_COLLECTOR_FRONTEND_URL'):
        value = globals().get(key) or os.environ.get(key)
        if value:
            return _text(value).rstrip('/')
    return 'http://127.0.0.1'


def _headers():
    org = globals().get('EASYOPS_ORG') or os.environ.get('EASYOPS_ORG') or '1888'
    user = globals().get('EASYOPS_USER') or os.environ.get('EASYOPS_USER') or 'easyops'
    headers = {'Content-Type': 'application/json', 'org': _text(org), 'user': _text(user), 'Host': 'admin.easyops.local'}
    cookie = globals().get('EASYOPS_COOKIE') or os.environ.get('EASYOPS_COOKIE') or os.environ.get('PHPSESSID')
    if cookie:
        headers['Cookie'] = _text(cookie) if 'PHPSESSID=' in _text(cookie) else 'PHPSESSID=' + _text(cookie)
    return headers


def _monitor_backend():
    value = (globals().get('EASYOPS_COLLECTOR_SERVICE_BACKEND_URL') or
             os.environ.get('EASYOPS_COLLECTOR_SERVICE_BACKEND_URL') or
             globals().get('EASYOPS_COLLECTOR_SERVICE_HOST') or
             os.environ.get('EASYOPS_COLLECTOR_SERVICE_HOST'))
    if value:
        return value
    # 沙箱默认只注入 *_SERVICE_HOST；采集服务与 CMDB 共用集群地址，端口固定 12000。
    value = (globals().get('EASYOPS_CMDB_SERVICE_HOST') or
             os.environ.get('EASYOPS_CMDB_SERVICE_HOST'))
    if value:
        host = _host(value)
        return 'http://%s:12000' % host
    raise RuntimeError('缺少采集服务内网地址（EASYOPS_COLLECTOR_SERVICE_HOST/EASYOPS_CMDB_SERVICE_HOST）')


def _monitor_get(path, contract, query):
    backend = _monitor_backend()
    headers = _headers()
    headers['giraffe-contract-name'] = contract
    return _http('GET', _host(backend), _port(backend, 12000), path,
                  query=query, headers=headers)


def _port(value, default):
    text = _text(value or '')
    match = re.search(r':(\d+)(?:/|$)', text)
    return int(match.group(1)) if match else default


def _http(method, host, port, path, body=None, query=None, headers=None, timeout=30):
    params = query or {}
    if params:
        encoded = urllib.urlencode(params) if IS_PY2 else _url_parse.urlencode(params)
        path += ('&' if '?' in path else '?') + encoded
    payload = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    conn = _http_client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, path, payload, headers or {})
        response = conn.getresponse()
        raw = response.read()
        status = response.status
    finally:
        conn.close()
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    try:
        data = json.loads(text)
    except Exception:
        data = text
    if status >= 400:
        raise RuntimeError('HTTP %s %s: %s' % (status, path, _safe_error(data)))
    if isinstance(data, dict) and data.get('code') not in (None, 0, '0'):
        raise RuntimeError('API code %s: %s' % (data.get('code'), _safe_error(data)))
    return data


def _safe_error(data):
    if isinstance(data, dict):
        return _text(data.get('error') or data.get('message') or data.get('codeExplain') or data)[:1000]
    return _text(data)[:1000]


def cmdb(method, path, body=None, query=None):
    base = globals().get('EASYOPS_CMDB_BACKEND_URL') or os.environ.get('EASYOPS_CMDB_BACKEND_URL')
    return _http(method, _host(base), CMDB_PORT, path, body, query, _headers())


def gateway(method, path, body=None, query=None):
    return _http(method, _host(_base_url()), 80, path, body, query, _headers())


def _data(response):
    if isinstance(response, dict):
        return response.get('data', response)
    return response


def _list(response):
    data = _data(response)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('list', 'items', 'jobs', 'instances', 'rows', 'result'):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _search_instances(object_id, query=None):
    rows = []
    page = 1
    while True:
        body = {'page': page, 'page_size': DEFAULT_PAGE_SIZE,
                'fields': ['instanceId', 'name', 'deviceName', 'objectId', 'modelId', 'modelName', 'ip', 'status'],
                'query': query or {}, 'ignore_missing_field_error': True}
        response = cmdb('POST', '/v3/object/%s/instance/_search' % object_id, body)
        batch = _list(response)
        rows.extend(batch)
        total = (_data(response) or {}).get('total') if isinstance(_data(response), dict) else None
        if not batch or len(batch) < DEFAULT_PAGE_SIZE or (isinstance(total, int) and len(rows) >= total):
            return rows
        page += 1
        if page > 1000:
            return rows


def _model_name(model_id):
    try:
        response = cmdb('GET', '/object/%s' % model_id)
        data = _data(response) or {}
        return data.get('name') or data.get('displayName') or data.get('objectName') or model_id
    except Exception:
        return model_id


def _descendants(model_id):
    result = [model_id]
    queue = [model_id]
    seen = set(result)
    while queue:
        parent = queue.pop(0)
        try:
            children = _list(cmdb('GET', '/object_basic', query={'parentObjectId': parent, 'page': 1, 'pageSize': 300}))
        except Exception as error:
            LOGGER.warning('查询子模型失败 %s: %s', parent, error)
            children = []
        for child in children:
            child_id = child.get('objectId') or child.get('id') or child.get('object_id')
            if child_id and child_id not in seen:
                seen.add(child_id)
                result.append(child_id)
                queue.append(child_id)
    return result


def _selected_models():
    selected = _ids(_input('cmdb_models'))
    if not selected:
        raise ValueError('cmdb_models 必填：请选择 CMDB_MODEL@EASYOPS 模型实例')
    model_rows = []
    direct = []
    for instance_id in selected:
        try:
            rows = _search_instances('CMDB_MODEL@EASYOPS', {'instanceId': {'$eq': instance_id}})
        except Exception:
            rows = []
        if rows:
            row = rows[0]
            model_id = row.get('objectId') or row.get('modelId') or row.get('object_id') or row.get('id')
            if model_id:
                model_rows.append((model_id, row.get('name') or row.get('displayName') or model_id))
        elif '@' in instance_id:
            direct.append(instance_id)
    if not model_rows and direct:
        model_rows = [(model_id, _model_name(model_id)) for model_id in direct]
    if not model_rows:
        raise ValueError('未能从 CMDB_MODEL@EASYOPS 选择项解析模型 ID')
    models = []
    seen = set()
    for model_id, name in model_rows:
        for child_id in _descendants(model_id):
            if child_id not in seen:
                seen.add(child_id)
                models.append((child_id, name if child_id == model_id else _model_name(child_id)))
    return models


def _job_id(job):
    return job.get('jobId') or job.get('instanceId') or job.get('id') or job.get('configId')


def _job_url(job_id):
    return '%s/next/collect-platform/data-collection/strategy/%s/detail?page=1' % (_base_url(), job_id)


def _instance_url(model_id, instance_id):
    return '%s/next/next-cmdb-instance-management/next/%s/instance/%s' % (_base_url(), model_id, instance_id)


def _model_jobs(model_id):
    # 监控服务内网接口：GET :12000/api/v1/list-resource-monitor-job。
    # 该接口要求完整 query 字段；不再调用 /next/api/gateway 前端代理。
    query = {'page': 1, 'pageSize': DEFAULT_PAGE_SIZE, 'nameQ': '',
             'objectIdQ': model_id, 'statusQ': '', 'agentQ': '',
             'typeQ': '', 'enableQ': ''}
    try:
        response = _monitor_get(MONITOR_BACKEND_PATH, MONITOR_JOB_CONTRACT, query)
        return _list(response)
    except Exception as error:
        LOGGER.warning('query monitor jobs failed model=%s: %s', _log_text(model_id), _log_text(error))
        return []


def _job_instances(job):
    job_id = _job_id(job)
    if not job_id:
        return []
    query = {'page': 1, 'pageSize': DEFAULT_PAGE_SIZE, 'statusFilter': '',
             'configId': job_id, 'jobId': job_id, 'objectId': '',
             'agentId': '', 'startTime': '', 'endTime': ''}
    try:
        return _list(_monitor_get(MONITOR_INSTANCES_BACKEND_PATH,
                                  MONITOR_INSTANCES_CONTRACT, query))
    except Exception as error:
        LOGGER.debug('query job instances failed %s: %s', _log_text(job_id), _log_text(error))
        return []


def _status(job, instance_id):
    job_id = _job_id(job)
    if not job_id:
        return {}
    query = {'jobId': job_id, 'instanceId': instance_id}
    try:
        data = _data(_monitor_get(STATUS_BACKEND_PATH, STATUS_CONTRACT, query))
        return data if isinstance(data, dict) else {}
    except Exception as error:
        LOGGER.debug('query status failed job=%s instance=%s: %s',
                     _log_text(job_id), _log_text(instance_id), _log_text(error))
        return {}


def _status_text(value):
    text = _text(value).lower()
    if any(x in text for x in ('success', 'succeed', 'successful', '正常', '成功', 'ok', 'done')):
        return u'成功'
    if any(x in text for x in ('partial', '部分', 'warning', 'warn')):
        return u'部分成功'
    if any(x in text for x in ('fail', 'error', 'failed', '失败', '异常')):
        return u'失败'
    return u'未知'


def _row_status(row):
    for key in ('status', 'jobStatus', 'taskStatus', 'state', 'resultStatus', 'monitorStatus'):
        if row.get(key) not in (None, ''):
            return _status_text(row.get(key))
    return u'未知'


def _error_text(value):
    if isinstance(value, dict):
        for key in ('errMsg', 'error', 'message', 'errorMsg', 'reason', 'detail'):
            if value.get(key):
                return _text(value[key])
        return _safe_error(value)
    return _text(value)


def _job_instance_map(job):
    mapping = {}
    for row in _job_instances(job):
        instance_id = row.get('instanceId') or row.get('targetInstanceId') or row.get('id')
        if instance_id:
            mapping[_text(instance_id)] = row
    return mapping


_ROW_SEQ = 0

def put_row(table, values):
    global _ROW_SEQ
    try:
        _ROW_SEQ += 1
        values = dict(values)
        # 先写入稳定且唯一的行时间戳；SDK 仍会追加自身 _E_TS，兼容两种解析器。
        values['_E_TS'] = str(int(time.time() * 1000) + _ROW_SEQ)
        pairs = []
        for key, value in values.items():
            text = _output_text(value)
            if IS_PY2:
                encoded = urllib.quote_plus(text)
            else:
                encoded = _url_parse.quote_plus(text)
            pairs.append('%s=%s' % (key, encoded))
        PutRow(table, '&'.join(pairs))
        # 平台 SDK 以毫秒级 _E_TS 作为行标识；连续 PutRow 可能覆盖同毫秒的上一行。
        time.sleep(0.002)
    except NameError:
        print(json.dumps({'table': table, 'values': values}, ensure_ascii=False))


def put_str(key, value):
    try:
        PutStr(key, _output_text(value))
    except NameError:
        LOGGER.info('%s: %s', _log_text(key), _log_text(value))


def main():
    models = _selected_models()
    all_rows = []
    task_count = 0
    limit_value = _input('instance_limit', '1000')
    try:
        instance_limit = max(1, int(_text(limit_value)))
    except Exception:
        raise ValueError('instance_limit 必须是正整数')
    omitted = 0
    for model_id, model_name in models:
        instances = _search_instances(model_id)
        if len(instances) > instance_limit:
            omitted += len(instances) - instance_limit
            LOGGER.warning('模型 %s 实例数=%d，按 instance_limit=%d 输出前 %d 行',
                           _log_text(model_id), len(instances), instance_limit, instance_limit)
            instances = instances[:instance_limit]
        jobs = _model_jobs(model_id)
        task_count += len(jobs)
        maps = [(job, _job_instance_map(job)) for job in jobs]
        for instance in instances:
            instance_id = _text(instance.get('instanceId') or instance.get('id'))
            if not instance_id:
                continue
            matched = []
            statuses = []
            errors = []
            for job, mapping in maps:
                if instance_id in mapping:
                    detail = mapping[instance_id]
                    matched.append(job)
                    statuses.append(_row_status(detail))
                    errors.append(_error_text(detail.get('errMsg') or detail.get('error') or detail.get('errorMsg')))
                    continue
                # 任务实例接口有的环境只返回任务级状态，再补查状态接口。
                status = _status(job, instance_id)
                if status:
                    matched.append(job)
                    statuses.append(_row_status(status))
                    errors.append(_error_text(status.get('errMsg') or status.get('error') or status.get('message')))
            if not matched:
                monitor = u'否'
                state = u'未知'
                error = u'未找到该实例对应的监控任务'
                task_url = ''
            else:
                monitor = u'是'
                uniq = set(statuses)
                state = u'失败' if u'失败' in uniq else (u'部分成功' if u'部分成功' in uniq or len(uniq) > 1 else (u'成功' if u'成功' in uniq else u'未知'))
                error = '; '.join(x for x in errors if x)
                task_url = _job_url(_job_id(matched[0]))
            row = {'modelName': model_name, 'instance': _instance_url(model_id, instance_id),
                   'isMonitored': monitor, 'monitorJob': task_url, 'monitorStatus': state,
                   'error': error}
            all_rows.append(row)
    for row in all_rows:
        put_row('monitor_status', row)
    LOGGER.info('完成采集：模型数=%d，实例行数=%d，监控任务数=%d，跳过实例=%d', len(models), len(all_rows), task_count, omitted)
    summary = u'模型=%d，实例=%d，监控任务=%d，已监控=%d，失败/部分=%d，跳过=%d' % (
        len(models), len(all_rows), task_count,
        len([row for row in all_rows if row['isMonitored'] == u'是']),
        len([row for row in all_rows if row['monitorStatus'] in (u'失败', u'部分成功')]), omitted)
    put_str('summary', summary)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        LOGGER.exception('monitor status check failed: %s', _log_text(error))
        put_str('summary', u'执行失败：%s' % error)
        sys.exit(1)
