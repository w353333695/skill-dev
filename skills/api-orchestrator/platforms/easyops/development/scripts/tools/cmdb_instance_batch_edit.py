# -*- coding: utf-8 -*-
"""EasyOps 工具：CMDB 实例批量编辑。

功能：
    按「CMDB 模型 + query 查询条件」筛选实例，再把「变更数据」统一写入命中的实例。
    支持父模型：递归展开全部子模型，父模型与子模型实例一并处理；按实例实际模型分组写入，
    子模型缺少属性或属性只读时整组跳过并在报告中说明。
    变更数据每行一条 attr_id=value，value 必须是合法 JSON（字符串带双引号）：
        memo="新备注"
        port=8080
        status=true
        owner={"instanceId":"5a377b5dc86a5"}
        tags=["a","b"]
    空行与 # 注释行忽略。

入参（平台注入 globals 同名变量；本地调试可用环境变量/argv 兜底）：
    cmdb_model   CMDB 模型（必填，cmdbInstance 单选，CMDB_MODEL@EASYOPS 模型实例）
    query        查询参数（必填，多行字符串，CMDB v3 search 的 query JSON）
    changes      变更数据（必填，多行字符串，每行 attr_id=value，value 为 JSON）
    action       动作（枚举 预览/执行，默认 预览）
                 预览=只列出命中实例与变更前后值，不写 CMDB
                 执行=按 instanceId 批量 upsert 更新，并回读校验

安全约束：
    · 执行动作拒绝空 query（空 query 会命中模型全部实例）；预览允许，用于评估影响面。
    · 禁止修改 instanceId/_object_id/_id/_uuid 与 ctime/mtime/creator/modifier 等系统字段。
    · 写入前按「所选模型 + 全部子模型」校验属性 ID 与只读属性；按实例实际 _object_id 分组写入。
    · 单次最多处理 10000 条实例，超出直接中止，要求缩小查询范围。
    · 写入后按 instanceId 回读，逐属性比对期望值，输出不一致明细。

输出：
    PutStr("report", ...)  预览/执行报告（完整文本）
    PutStr("summary", ...) 一行汇总

运行环境：EasyOps 沙箱（sandboxRun=true，内部 agent 执行，Python 2.7）/ 本地 Python 3。
依赖：仅标准库；yaml 可选（读取 agent conf.yaml，缺失时用最小文本解析兜底）。
"""
import json
import logging
import os
import platform
import re
import sys
import time

try:
    import ssl
except ImportError:
    ssl = None

try:
    import yaml
except ImportError:
    yaml = None

IS_PY2 = sys.version_info[0] == 2
if IS_PY2:
    import httplib as _http_client
    import urllib
else:
    import http.client as _http_client
    import urllib.parse as _url_parse

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOGGER = logging.getLogger('cmdb_instance_batch_edit')

TOOL_VERSION = '1.0.0'
CMDB_PORT = 8079
MODEL_OBJECT_ID = 'CMDB_MODEL@EASYOPS'
PAGE_SIZE = 1000
MAX_INSTANCES = 10000
BATCH_SIZE = 500
MODEL_PAGE_SIZE = 300
PREVIEW_LIMIT = 100
FORBIDDEN_ATTRS = ('instanceId', '_object_id', '_id', '_uuid', 'ctime', 'mtime', 'creator', 'modifier')
ATTR_ID_RE = re.compile(r'^[0-9A-Za-z_]+$')


def _text(value):
    if value is None:
        return u''
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
    """平台把入参注入 globals；本地调试兼容环境变量、EASYOPS_TOOL_INPUT 与 argv k=v。"""
    value = globals().get(name)
    if value not in (None, ''):
        return value
    value = os.environ.get('EASYOPS_TOOL_' + name.upper())
    if value not in (None, ''):
        return value
    raw = os.environ.get('EASYOPS_TOOL_INPUT')
    data = _json_load(raw, {})
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
    if isinstance(value, dict):
        value = value.get('instanceId') or value.get('id') or value.get('objectId') or value.get('modelId')
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


def _multiline(value):
    if isinstance(value, (list, tuple)):
        return u'\n'.join([_text(item) for item in value])
    return _text(value or '')


def _host(value):
    value = _text(value or '')
    value = re.sub(r'^https?://', '', value).split('/', 1)[0]
    return value.split(':', 1)[0] or '127.0.0.1'


def _port(value, default):
    text = _text(value or '')
    match = re.search(r':(\d+)(?:/|$)', text)
    return int(match.group(1)) if match else default


_AGENT_CONFIG_CACHE = None
_MODEL_ATTR_CACHE = {}


def _agent_config_host_org():
    """读取 agent conf.yaml 的 command server host 与 base client_id。"""
    global _AGENT_CONFIG_CACHE
    if _AGENT_CONFIG_CACHE is not None:
        return _AGENT_CONFIG_CACHE
    path = r'C:\easyOps\agent\conf\conf.yaml' if platform.system().lower() == 'windows' else '/usr/local/easyops/agent/conf/conf.yaml'
    try:
        with open(path, 'r') as stream:
            raw = stream.read()
        data = None
        if yaml is not None:
            try:
                data = yaml.safe_load(raw) or {}
            except Exception:
                data = None
        if isinstance(data, dict):
            org = ((data.get('base') or {}).get('client_id'))
            groups = ((data.get('command') or {}).get('server_groups') or [])
            hosts = (groups[0].get('hosts') or []) if groups else []
            host_value = hosts[0].get('ip') if hosts else ''
            host = _text(host_value).split(',')[0].strip()
            if host and org not in (None, ''):
                _AGENT_CONFIG_CACHE = (host, _text(org))
                return _AGENT_CONFIG_CACHE
        org_match = re.search(r'(?m)^\s*client_id\s*:\s*["\']?([^#\s"\']+)', raw)
        ip_match = re.search(r'(?m)^\s*ip\s*:\s*["\']?([^#\s"\']+)', raw)
        if org_match and ip_match:
            _AGENT_CONFIG_CACHE = (ip_match.group(1).split(',')[0], org_match.group(1))
            return _AGENT_CONFIG_CACHE
    except Exception as error:
        LOGGER.debug('read agent conf failed path=%s: %s', path, _text(error))
    return ('', '')


def _org():
    _, agent_org = _agent_config_host_org()
    org = agent_org or globals().get('EASYOPS_ORG') or os.environ.get('EASYOPS_ORG')
    if org in (None, ''):
        raise RuntimeError(u'缺少 agent 配置或 EASYOPS_ORG，无法构建内部请求')
    return _text(org)


def _headers():
    user = globals().get('EASYOPS_USER') or os.environ.get('EASYOPS_USER') or 'easyops'
    return {
        'Content-Type': 'application/json',
        'org': _org(),
        'user': _text(user),
        'Host': 'admin.easyops.local',
    }


def _json_bytes(value):
    """py2 下 json.dumps 可能返回 str(utf-8 bytes) 或 unicode，统一成 utf-8 bytes。"""
    text = json.dumps(value, ensure_ascii=False)
    if IS_PY2:
        if isinstance(text, unicode):
            return text.encode('utf-8')
        return text
    return text.encode('utf-8')


def _http(method, host, port, path, body=None, query=None, headers=None, timeout=30, scheme='http'):
    params = query or {}
    if params:
        encoded = urllib.urlencode(params) if IS_PY2 else _url_parse.urlencode(params)
        path += ('&' if '?' in path else '?') + encoded
    payload = _json_bytes(body) if body is not None else None
    connection = _http_client.HTTPSConnection if scheme.lower() == 'https' else _http_client.HTTPConnection
    if scheme.lower() == 'https' and ssl is not None:
        try:
            conn = connection(host, port, timeout=timeout, context=ssl._create_unverified_context())
        except TypeError:
            conn = connection(host, port, timeout=timeout)
    else:
        conn = connection(host, port, timeout=timeout)
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
        raise RuntimeError(u'HTTP %s %s: %s' % (status, path, _safe_error(data)))
    if isinstance(data, dict) and data.get('code') not in (None, 0, '0'):
        raise RuntimeError(u'API code %s: %s' % (data.get('code'), _safe_error(data)))
    return data


def _safe_error(data):
    if isinstance(data, dict):
        return _text(data.get('error') or data.get('message') or data.get('codeExplain') or data)[:1000]
    return _text(data)[:1000]


def _internal_request(method, base_url, path, body=None, query=None):
    if not base_url or not re.match(r'^https?://', _text(base_url)):
        raise RuntimeError(u'内部 API 缺少有效的服务地址')
    if path.startswith('/next/'):
        raise ValueError(u'内部 API 禁止使用前端网关路径')
    scheme = 'https' if _text(base_url).lower().startswith('https://') else 'http'
    return _http(method, _host(base_url), _port(base_url, 443 if scheme == 'https' else 80),
                 path, body=body, query=query, headers=_headers(), scheme=scheme)


def _cmdb_base():
    """CMDB 地址解析：注入的完整 URL > 注入的 host > agent conf > 报错。"""
    value = globals().get('EASYOPS_CMDB_BACKEND_URL') or os.environ.get('EASYOPS_CMDB_BACKEND_URL')
    if value:
        return _text(value).rstrip('/')
    value = globals().get('EASYOPS_CMDB_SERVICE_HOST') or os.environ.get('EASYOPS_CMDB_SERVICE_HOST')
    if value:
        return 'http://%s:%s' % (_host(value), _port(value, CMDB_PORT))
    agent_host, _ = _agent_config_host_org()
    if agent_host:
        return 'http://%s:%s' % (_host(agent_host), CMDB_PORT)
    raise RuntimeError(u'缺少 CMDB 服务地址：未注入 EASYOPS_CMDB_BACKEND_URL/EASYOPS_CMDB_SERVICE_HOST，也读不到 agent conf.yaml')


def cmdb(method, path, body=None, query=None):
    return _internal_request(method, _cmdb_base(), path, body=body, query=query)


def _data(response):
    if isinstance(response, dict):
        return response.get('data', response)
    return response


def _list(response):
    data = _data(response)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('list', 'items', 'instances', 'rows', 'result'):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _search_instances(object_id, query=None, fields=None):
    """按条件翻页搜索实例；返回 (rows, total)。total 取不到时为 None。"""
    rows = []
    total = None
    page = 1
    while True:
        body = {
            'page': page,
            'page_size': PAGE_SIZE,
            'fields': fields or ['instanceId', 'name', '_object_id'],
            'query': query or {},
            'ignore_missing_field_error': True,
        }
        response = cmdb('POST', '/v3/object/%s/instance/_search' % object_id, body)
        batch = _list(response)
        rows.extend(batch)
        data = _data(response)
        if isinstance(data, dict) and data.get('total') is not None:
            total = data.get('total')
        if not batch or len(batch) < PAGE_SIZE:
            break
        if isinstance(total, int) and len(rows) >= total:
            break
        if len(rows) >= MAX_INSTANCES or page >= 1000:
            break
        page += 1
    return rows, total


def _model_name(model_id):
    try:
        data = _data(cmdb('GET', '/object/%s' % model_id)) or {}
        if not isinstance(data, dict):
            return _text(model_id)
        return _text(data.get('objectName') or data.get('name') or data.get('displayName') or model_id)
    except Exception:
        return _text(model_id)


def _resolve_model(raw):
    """cmdbInstance 单选注入的是 CMDB_MODEL@EASYOPS 实例的 instanceId，解析成模型 objectId。"""
    values = _ids(raw)
    if not values:
        raise ValueError(u'cmdb_model 必填：请选择 CMDB_MODEL@EASYOPS 模型实例')
    value = values[0]
    if '@' in value:
        return value, _model_name(value)
    rows, _ = _search_instances(MODEL_OBJECT_ID, {'instanceId': {'$eq': value}}, ['instanceId', 'objectId', 'objectName'])
    if not rows:
        raise ValueError(u'未能从 CMDB_MODEL@EASYOPS 解析模型实例 %s，请重新选择模型' % value)
    row = rows[0]
    model_id = _text(row.get('objectId') or row.get('modelId') or row.get('object_id') or row.get('id'))
    if not model_id:
        raise ValueError(u'模型实例 %s 未返回 objectId，无法确定模型 ID' % value)
    model_name = _text(row.get('objectName') or row.get('name') or row.get('displayName') or model_id)
    return model_id, model_name


def _parse_query(raw):
    if isinstance(raw, dict):
        return raw
    text = _multiline(raw).strip()
    if not text:
        return {}
    data = _json_load(text)
    if not isinstance(data, dict):
        raise ValueError(u'查询参数必须是 JSON 对象，例如 {"ip":{"$like":"10.1.%"}}')
    return data


def _parse_changes(raw):
    """解析多行 attr_id=value；value 必须是合法 JSON。返回 [{attr,value,line,raw}]。"""
    lines = _multiline(raw).replace('\r\n', '\n').replace('\r', '\n').split('\n')
    changes = []
    seen = {}
    errors = []
    for index, line in enumerate(lines, 1):
        text = _text(line).strip()
        if not text or text.startswith('#'):
            continue
        if '=' not in text:
            errors.append(u'第 %d 行缺少 "="：%s' % (index, text))
            continue
        attr, raw_value = text.split('=', 1)
        attr = attr.strip()
        raw_value = raw_value.strip()
        if not ATTR_ID_RE.match(attr):
            errors.append(u'第 %d 行属性 ID 非法（仅字母/数字/下划线）：%s' % (index, attr))
            continue
        if attr in seen:
            errors.append(u'属性 %s 重复（第 %d 行与第 %d 行）' % (attr, seen[attr], index))
            continue
        if not raw_value:
            errors.append(u'第 %d 行 %s 的值为空；清空请写 null，如 %s=null' % (index, attr, attr))
            continue
        try:
            value = json.loads(raw_value)
        except Exception as error:
            errors.append(u'第 %d 行 %s 的值不是合法 JSON（字符串请加双引号，如 %s="新备注"）：%s'
                          % (index, attr, attr, _text(error)))
            continue
        seen[attr] = index
        changes.append({'attr': attr, 'value': value, 'line': index, 'raw': raw_value})
    if errors:
        raise ValueError(u'变更数据解析失败：\n  ' + u'\n  '.join(errors))
    if not changes:
        raise ValueError(u'变更数据为空（只含空行/注释），每行格式 attr_id=value')
    return changes


def _model_attrs(model_id):
    """读取模型属性与关系定义；返回 (attrs{id: meta}, relation_ids set)。"""
    data = _data(cmdb('GET', '/object/%s' % model_id)) or {}
    if not isinstance(data, dict):
        data = {}
    attrs = {}
    for item in data.get('attrList') or []:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        value = item.get('value') or {}
        attrs[_text(item['id'])] = {
            'name': _text(item.get('name') or item['id']),
            'readonly': _text(item.get('readonly')).lower() == 'true',
            'type': _text(value.get('type') if isinstance(value, dict) else ''),
        }
    relation_ids = set()
    for item in data.get('relation_list') or []:
        if not isinstance(item, dict):
            continue
        for key in ('left_id', 'right_id'):
            if item.get(key):
                relation_ids.add(_text(item[key]))
    return attrs, relation_ids


def _descendants(model_id):
    """递归展开父模型的全部子模型（BFS、去重，父模型在前）。"""
    result = [model_id]
    seen = set([model_id])
    queue = [model_id]
    while queue:
        parent = queue.pop(0)
        page = 1
        while True:
            try:
                response = cmdb('GET', '/object_basic', query={
                    'parentObjectId': parent, 'page': page, 'pageSize': MODEL_PAGE_SIZE})
                batch = _list(response)
            except Exception as error:
                LOGGER.warning(u'[_descendants] 查询子模型失败 parent=%s: %s',
                               _text(parent), _text(error))
                batch = []
            for child in batch:
                child_id = _text(child.get('objectId') or child.get('id') or child.get('object_id'))
                if child_id and child_id not in seen:
                    seen.add(child_id)
                    result.append(child_id)
                    queue.append(child_id)
            if len(batch) < MODEL_PAGE_SIZE or page >= 100:
                break
            page += 1
    return result


def _model_attr_map(models):
    """批量读取模型属性定义；返回 {model_id: (attrs, relation_ids)}，读取失败为 (None, None)。"""
    result = {}
    for model_id in models:
        if model_id not in _MODEL_ATTR_CACHE:
            try:
                _MODEL_ATTR_CACHE[model_id] = _model_attrs(model_id)
            except Exception as error:
                LOGGER.warning(u'[_model_attr_map] 读取模型 %s 属性定义失败，跳过该模型校验: %s',
                               _text(model_id), _text(error))
                _MODEL_ATTR_CACHE[model_id] = (None, None)
        result[model_id] = _MODEL_ATTR_CACHE[model_id]
    return result


def _search_fields(model_id, changes, attr_map):
    """按模型属性定义选字段：展示字段取 name/deviceName/hostname/ip 中第一个存在的，
    变更字段只请求该模型确实拥有的，避免请求不存在的 name 关系导致 133116。"""
    attrs, relation_ids = attr_map.get(model_id, (None, None))
    fields = ['instanceId', '_object_id']
    if attrs is not None:
        for display in ('name', 'deviceName', 'hostname', 'ip'):
            if display in attrs:
                fields.append(display)
                break
    for entry in changes:
        attr = entry['attr']
        if attrs is None or attr in attrs or attr in relation_ids:
            fields.append(attr)
    return fields


def _search_models(models, query, changes, attr_map):
    """逐模型搜索并按 (实际模型, instanceId) 去重，父模型与子模型重复命中只保留一条。"""
    rows = []
    seen = set()
    for model_id in models:
        fields = _search_fields(model_id, changes, attr_map)
        batch, _ = _search_instances(model_id, query, fields)
        for row in batch:
            instance_id = _text(row.get('instanceId') or row.get('id'))
            if not instance_id:
                continue
            actual_model = _text(row.get('_object_id') or model_id)
            key = (actual_model, instance_id)
            if key in seen:
                continue
            seen.add(key)
            item = dict(row)
            item['_object_id'] = actual_model
            rows.append(item)
        if len(rows) >= MAX_INSTANCES:
            raise ValueError(u'查询命中数达到单次上限 %d 条，已中止。请缩小查询范围。' % MAX_INSTANCES)
    return rows


def _validate_changes(changes, attr_map):
    """按「所选模型 + 全部子模型」的属性并集校验；返回错误列表。"""
    errors = []
    for entry in changes:
        if entry['attr'] in FORBIDDEN_ATTRS:
            errors.append(u'属性 %s 不允许通过本工具修改（主键/系统元数据）' % entry['attr'])
    if not [attrs for attrs, _ in attr_map.values() if attrs]:
        return errors
    for entry in changes:
        attr = entry['attr']
        found = False
        readonly_everywhere = True
        for attrs, relation_ids in attr_map.values():
            if attrs is None:
                continue
            if attr in attrs:
                found = True
                if not attrs[attr]['readonly']:
                    readonly_everywhere = False
            elif attr in relation_ids:
                found = True
                readonly_everywhere = False
        if not found:
            errors.append(u'属性 %s 不属于所选模型及其子模型（请核对属性 ID，或当前用户无该字段权限）' % attr)
        elif readonly_everywhere:
            errors.append(u'属性 %s 在所有候选模型中都是只读属性，不允许修改' % attr)
    return errors


def _filter_groups(groups, changes, attr_map):
    """逐子模型检查属性是否可用；缺属性/只读的子模型整组跳过并返回原因。"""
    kept = []
    skipped = []
    for model_id, rows in groups:
        attrs, relation_ids = attr_map.get(model_id, (None, None))
        if attrs is None:
            kept.append((model_id, rows))
            continue
        missing = []
        readonly = []
        for entry in changes:
            attr = entry['attr']
            if attr in attrs:
                if attrs[attr]['readonly']:
                    readonly.append(u'%s（%s）' % (attr, attrs[attr]['name']))
            elif attr not in relation_ids:
                missing.append(attr)
        if missing or readonly:
            reasons = []
            if missing:
                reasons.append(u'缺少属性 %s' % u'、'.join(missing))
            if readonly:
                reasons.append(u'只读属性 %s' % u'、'.join(readonly))
            skipped.append({'model': model_id, 'count': len(rows), 'reason': u'；'.join(reasons)})
        else:
            kept.append((model_id, rows))
    return kept, skipped


def _instance_label(row):
    name = (row.get('name') or row.get('deviceName') or row.get('hostname')
            or row.get('ip') or row.get('objectId') or '')
    return _text(name)


def _group_rows(rows, default_model):
    """按实例实际 _object_id 分组。返回 [(model_id, [rows])]。"""
    grouped = {}
    order = []
    seen = set()
    for row in rows:
        instance_id = _text(row.get('instanceId') or row.get('id'))
        if not instance_id or instance_id in seen:
            continue
        seen.add(instance_id)
        model_id = _text(row.get('_object_id') or default_model)
        if model_id not in grouped:
            grouped[model_id] = []
            order.append(model_id)
        grouped[model_id].append(row)
    return [(model_id, grouped[model_id]) for model_id in order]


def _format_value(value):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = _text(value)
    if len(text) > 200:
        text = text[:200] + u'...'
    return _text(text)


def _values_equal(expected, actual):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if expected == actual:
        return True
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return float(expected) == float(actual)
    if isinstance(actual, list):
        for item in actual:
            if _values_equal(expected, item):
                return True
        if isinstance(expected, list):
            if len(expected) != len(actual):
                return False
            remaining = list(actual)
            for item in expected:
                for index, candidate in enumerate(remaining):
                    if _values_equal(item, candidate):
                        remaining.pop(index)
                        break
                else:
                    return False
            return True
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.get('instanceId') and actual.get('instanceId'):
            return _text(expected['instanceId']) == _text(actual['instanceId'])
        if not expected and not actual:
            return True
    return False


def _import_group(model_id, rows, changes):
    """按 instanceId 批量 upsert；返回 {insert,update,failed,details,insert_warn}。"""
    result = {'insert': 0, 'update': 0, 'failed': 0, 'details': [], 'insert_warn': False}
    datas = []
    for row in rows:
        item = {'instanceId': _text(row.get('instanceId') or row.get('id'))}
        for entry in changes:
            item[entry['attr']] = entry['value']
        datas.append(item)
    for start in range(0, len(datas), BATCH_SIZE):
        chunk = datas[start:start + BATCH_SIZE]
        body = {
            'keys': ['instanceId'],
            'datas': chunk,
            'importMetadata': True,
            'disableNestedCreateInstance': True,
        }
        response = cmdb('POST', '/object/%s/instance/_import' % model_id, body)
        data = _data(response) or {}
        if not isinstance(data, dict):
            data = {}
        insert_count = data.get('insert_count') or 0
        update_count = data.get('update_count') or 0
        failed_count = data.get('failed_count') or 0
        result['insert'] += int(insert_count)
        result['update'] += int(update_count)
        result['failed'] += int(failed_count)
        if int(insert_count) > 0:
            result['insert_warn'] = True
        for failure in data.get('data') or []:
            if isinstance(failure, dict):
                result['details'].append({
                    'instanceId': _text(failure.get('instanceId') or (failure.get('data') or {}).get('instanceId')),
                    'code': _text(failure.get('code')),
                    'error': _text(failure.get('error') or failure.get('message')),
                })
            else:
                result['details'].append({'instanceId': u'', 'code': u'', 'error': _text(failure)})
    return result


def _readback(groups, changes, attr_map):
    """按 instanceId 回读变更字段并比对；返回 {ok,mismatch,missing,details}。"""
    result = {'ok': 0, 'mismatch': 0, 'missing': 0, 'details': []}
    for model_id, rows in groups:
        attrs, relation_ids = attr_map.get(model_id, (None, None))
        fields = ['instanceId'] + [entry['attr'] for entry in changes
                                   if attrs is None or entry['attr'] in attrs
                                   or entry['attr'] in relation_ids]
        ids = [_text(row.get('instanceId') or row.get('id')) for row in rows]
        actual = {}
        for start in range(0, len(ids), BATCH_SIZE):
            chunk = ids[start:start + BATCH_SIZE]
            try:
                found, _ = _search_instances(model_id, {'instanceId': {'$in': chunk}}, fields)
            except Exception as error:
                LOGGER.warning(u'[_readback] 模型 %s 回读失败: %s', _text(model_id), _text(error))
                result['missing'] += len(chunk)
                continue
            for row in found:
                instance_id = _text(row.get('instanceId') or row.get('id'))
                if instance_id:
                    actual[instance_id] = row
        for instance_id in ids:
            row = actual.get(instance_id)
            if row is None:
                result['missing'] += 1
                continue
            for entry in changes:
                attr = entry['attr']
                if attr not in row:
                    result['missing'] += 1
                    result['details'].append({
                        'instanceId': instance_id, 'attr': attr,
                        'expected': _format_value(entry['value']), 'actual': u'<未返回>',
                    })
                    continue
                if _values_equal(entry['value'], row.get(attr)):
                    result['ok'] += 1
                else:
                    result['mismatch'] += 1
                    result['details'].append({
                        'instanceId': instance_id, 'attr': attr,
                        'expected': _format_value(entry['value']),
                        'actual': _format_value(row.get(attr)),
                    })
    return result


def _common_header(action, model_id, model_name, query, changes, matched, groups,
                   model_count=1, skipped=None):
    lines = []
    lines.append(u'CMDB 实例批量编辑报告（%s）' % action)
    lines.append(u'工具版本：%s    执行时间：%s' % (TOOL_VERSION, time.strftime('%Y-%m-%d %H:%M:%S')))
    lines.append(u'模型：%s（%s）' % (model_id, model_name))
    if model_count > 1:
        lines.append(u'模型范围：含 %d 个子模型（父模型与子模型实例一并处理）' % (model_count - 1))
    lines.append(u'查询条件：%s' % (_format_value(query) if query else u'<空，模型下全部实例>'))
    lines.append(u'变更字段（%d 个）：%s' % (len(changes), u'、'.join(
        [u'%s=%s' % (entry['attr'], _format_value(entry['value'])) for entry in changes])))
    skipped_count = sum([item['count'] for item in (skipped or [])])
    lines.append(u'命中实例：%d 条' % (matched + skipped_count))
    if skipped:
        lines.append(u'跳过子模型：%s' % u'；'.join(
            [u'%s %d 条（%s）' % (item['model'], item['count'], item['reason']) for item in skipped]))
    if len(groups) > 1:
        lines.append(u'按实际模型分组：%s' % u'，'.join(
            [u'%s=%d' % (model_id_, len(rows)) for model_id_, rows in groups]))
    return lines


def _preview_report(model_id, model_name, query, changes, rows, groups, model_count=1, skipped=None):
    matched = sum([len(group_rows) for _, group_rows in groups])
    lines = _common_header(u'预览', model_id, model_name, query, changes, matched, groups,
                           model_count, skipped)
    lines.append(u'')
    lines.append(u'实例明细（仅展示前 %d 条，共 %d 条）：' % (PREVIEW_LIMIT, matched))
    shown = 0
    for group_model, group_rows in groups:
        for row in group_rows:
            if shown >= PREVIEW_LIMIT:
                break
            shown += 1
            instance_id = _text(row.get('instanceId') or row.get('id'))
            lines.append(u'  [%d] %s instanceId=%s name=%s' % (
                shown, group_model, instance_id, _instance_label(row)))
            for entry in changes:
                before = row.get(entry['attr'], u'<无值>') if entry['attr'] in row else u'<无值>'
                lines.append(u'      %s: %s -> %s' % (
                    entry['attr'], _format_value(before), _format_value(entry['value'])))
        if shown >= PREVIEW_LIMIT:
            break
    if matched > PREVIEW_LIMIT:
        lines.append(u'  ... 其余 %d 条未展示' % (matched - PREVIEW_LIMIT))
    lines.append(u'')
    lines.append(u'提示：预览不写入 CMDB。确认无误后把「动作」改为「执行」。')
    return u'\n'.join(lines)


def _execute_report(model_id, model_name, query, changes, rows, groups, import_results, readback,
                    model_count=1, skipped=None):
    matched = sum([len(group_rows) for _, group_rows in groups])
    lines = _common_header(u'执行', model_id, model_name, query, changes, matched, groups,
                           model_count, skipped)
    lines.append(u'')
    lines.append(u'执行结果：')
    if matched == 0:
        lines.append(u'  命中 0 条，未执行任何写入。')
    total_insert = 0
    total_update = 0
    total_failed = 0
    insert_warn = False
    details = []
    for (group_model, _), result in zip(groups, import_results):
        total_insert += result['insert']
        total_update += result['update']
        total_failed += result['failed']
        insert_warn = insert_warn or result['insert_warn']
        lines.append(u'  模型 %s：update=%d，failed=%d，insert=%d' % (
            group_model, result['update'], result['failed'], result['insert']))
        details.extend(result['details'])
    lines.append(u'  合计：update=%d，failed=%d，insert=%d' % (total_update, total_failed, total_insert))
    if insert_warn:
        lines.append(u'  ⚠ 出现 insert（新建）：可能是实例在查询后被删除，请核对 CMDB 中是否产生新实例。')
    if details:
        lines.append(u'')
        lines.append(u'失败明细（最多展示 50 条，共 %d 条）：' % len(details))
        for detail in details[:50]:
            lines.append(u'  - instanceId=%s code=%s error=%s' % (
                detail['instanceId'] or u'-', detail['code'] or u'-', detail['error'] or u'-'))
    lines.append(u'')
    lines.append(u'回读校验：一致 %d 项，不一致 %d 项，未返回 %d 项' % (
        readback['ok'], readback['mismatch'], readback['missing']))
    if readback['details']:
        lines.append(u'回读差异（最多展示 50 条，共 %d 条）：' % len(readback['details']))
        for detail in readback['details'][:50]:
            lines.append(u'  - instanceId=%s %s: 期望=%s 实际=%s' % (
                detail['instanceId'], detail['attr'], detail['expected'], detail['actual']))
    return u'\n'.join(lines), total_insert, total_update, total_failed, insert_warn


def _summary(action, model_id, matched, update=0, failed=0):
    if action == u'预览':
        return u'动作=预览；模型=%s；命中=%d；未写入' % (model_id, matched)
    return u'动作=执行；模型=%s；命中=%d；更新=%d；失败=%d' % (model_id, matched, update, failed)


def put_str(key, value):
    try:
        PutStr(key, _output_text(value))  # noqa: F821 (平台注入)
    except NameError:
        LOGGER.info(u'[%s] %s', key, value)


def main():
    action = _text(_input('action', u'预览')).strip() or u'预览'
    if action not in (u'预览', u'执行'):
        raise ValueError(u'动作只支持 预览/执行，当前：%s' % action)
    model_id, model_name = _resolve_model(_input('cmdb_model'))
    query = _parse_query(_input('query'))
    changes = _parse_changes(_input('changes'))
    models = _descendants(model_id)
    attr_map = _model_attr_map(models)
    errors = _validate_changes(changes, attr_map)
    if errors:
        raise ValueError(u'变更数据校验失败：\n  ' + u'\n  '.join(errors))
    if action == u'执行' and not query:
        raise ValueError(u'执行动作拒绝空 query：空条件会命中模型全部实例。请填写过滤条件；只想评估影响面请用「预览」。')

    rows = _search_models(models, query, changes, attr_map)
    if len(rows) >= MAX_INSTANCES:
        raise ValueError(u'查询命中数达到单次上限 %d 条，已中止。请缩小查询范围。' % MAX_INSTANCES)
    all_groups = _group_rows(rows, model_id)
    groups, skipped = _filter_groups(all_groups, changes, attr_map)
    matched = sum([len(group_rows) for _, group_rows in groups])
    LOGGER.info('[main] action=%s model=%s children=%d query=%s changes=%d matched=%d skipped=%d groups=%d',
                _text(action), _text(model_id), len(models) - 1,
                _text(_format_value(query)), len(changes), matched,
                sum([item['count'] for item in skipped]), len(groups))

    if action == u'预览':
        report = _preview_report(model_id, model_name, query, changes, rows, groups,
                                 len(models), skipped)
        put_str('report', report)
        put_str('summary', _summary(action, model_id, matched))
        return 0

    import_results = []
    for group_model, group_rows in groups:
        LOGGER.info('[main] import model=%s instances=%d', _text(group_model), len(group_rows))
        import_results.append(_import_group(group_model, group_rows, changes))
    readback = _readback(groups, changes, attr_map)
    report, total_insert, total_update, total_failed, insert_warn = _execute_report(
        model_id, model_name, query, changes, rows, groups, import_results, readback,
        len(models), skipped)
    put_str('report', report)
    put_str('summary', _summary(action, model_id, matched, total_update, total_failed))
    if total_failed > 0 or insert_warn:
        return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        LOGGER.exception(u'[cmdb_instance_batch_edit] 执行失败: %s', _text(error))
        put_str('summary', u'执行失败：%s' % error)
        sys.exit(1)
