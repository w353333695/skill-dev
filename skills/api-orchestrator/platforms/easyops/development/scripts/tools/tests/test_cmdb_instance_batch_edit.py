# -*- coding: utf-8 -*-
"""CMDB 实例批量编辑工具离线回归：参数解析、校验、分组写入、回读与工具包结构。"""
import importlib.util
import json
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

EASYOPS = Path(__file__).resolve().parents[4]
SOURCE = EASYOPS / 'development' / 'scripts' / 'tools' / 'cmdb_instance_batch_edit.py'
PACKAGE = EASYOPS / 'hub' / 'tools' / '工具_CMDB实例批量编辑_1.0.3.tar.gz'

SPEC = importlib.util.spec_from_file_location('cmdb_instance_batch_edit', str(SOURCE))
edit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edit)


class ParseTests(unittest.TestCase):
    def test_parse_changes_accepts_json_values_and_comments(self):
        raw = '\n'.join([
            '# 注释行',
            'memo="新备注"',
            'port=8080',
            'status=true',
            'owner={"instanceId":"5a377b5dc86a5"}',
            'tags=["a","b"]',
            'empty=null',
            '',
        ])
        changes = edit._parse_changes(raw)
        self.assertEqual([item['attr'] for item in changes],
                         ['memo', 'port', 'status', 'owner', 'tags', 'empty'])
        self.assertEqual(changes[0]['value'], u'新备注')
        self.assertEqual(changes[1]['value'], 8080)
        self.assertIs(changes[2]['value'], True)
        self.assertEqual(changes[3]['value'], {'instanceId': '5a377b5dc86a5'})
        self.assertEqual(changes[4]['value'], ['a', 'b'])
        self.assertIsNone(changes[5]['value'])

    def test_parse_changes_accepts_list_input(self):
        changes = edit._parse_changes(['memo="a"', 'port=1'])
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[1]['value'], 1)

    def test_parse_changes_rejects_invalid_json_with_line_hint(self):
        with self.assertRaises(ValueError) as ctx:
            edit._parse_changes('memo=新备注')
        message = str(ctx.exception)
        self.assertIn('第 1 行', message)
        self.assertIn('不是合法 JSON', message)

    def test_parse_changes_rejects_duplicate_attr(self):
        with self.assertRaises(ValueError) as ctx:
            edit._parse_changes('memo="a"\nport=1\nmemo="b"')
        self.assertIn('重复', str(ctx.exception))

    def test_parse_changes_rejects_empty_value(self):
        with self.assertRaises(ValueError) as ctx:
            edit._parse_changes('memo=')
        self.assertIn('null', str(ctx.exception))

    def test_parse_changes_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            edit._parse_changes('# 只有注释\n\n')

    def test_parse_query_accepts_object_and_empty(self):
        self.assertEqual(edit._parse_query('{"ip":{"$like":"10.1.%"}}'), {'ip': {'$like': '10.1.%'}})
        self.assertEqual(edit._parse_query(''), {})
        self.assertEqual(edit._parse_query(None), {})

    def test_parse_query_rejects_non_object(self):
        with self.assertRaises(ValueError):
            edit._parse_query('[1,2]')


class HttpTests(unittest.TestCase):
    """网络层回归：优先 requests，body 统一 utf-8 bytes，py2 header 转 bytes。"""

    class _FakeResponse(object):
        status_code = 200
        content = b'{"code":0,"data":{"ok":true}}'

    def test_http_uses_requests_with_utf8_bytes_body(self):
        fake = self._FakeResponse()
        body = {'query': {'memo': u'中文测试'}}
        with patch.object(edit.requests, 'request', return_value=fake) as request:
            data = edit._http('POST', '127.0.0.1', 8079, '/object/HOST/instance/_search',
                              body=body, query={'page': 1}, headers={'org': '8888', 'user': 'easyops'},
                              timeout=7)
        self.assertEqual(data['code'], 0)
        args, kwargs = request.call_args
        self.assertEqual(args[0], 'POST')
        self.assertEqual(args[1], 'http://127.0.0.1:8079/object/HOST/instance/_search')
        self.assertEqual(kwargs['data'], json.dumps(body, ensure_ascii=False).encode('utf-8'))
        self.assertEqual(kwargs['params'], {'page': 1})
        self.assertEqual(kwargs['timeout'], 7)
        self.assertTrue(kwargs['verify'])
        self.assertEqual(kwargs['headers']['org'], '8888')

    def test_http_requests_https_disables_verify(self):
        with patch.object(edit.requests, 'request', return_value=self._FakeResponse()) as request:
            edit._http('GET', '127.0.0.1', 443, '/object/HOST', scheme='https')
        self.assertFalse(request.call_args[1]['verify'])

    def test_header_value_is_bytes_on_py2(self):
        with patch.object(edit, 'IS_PY2', True), patch.object(edit, 'unicode', str, create=True):
            self.assertIsInstance(edit._header_value(u'中文'), bytes)
    def test_import_group_sends_utf8_body_through_http(self):
        class _Response(object):
            status_code = 200
            content = b'{"code":0,"data":{"insert_count":0,"update_count":1,"failed_count":0,"data":[]}}'

        rows = [{'instanceId': 'a1'}]
        changes = [{'attr': 'memo', 'value': u'中文值', 'line': 1, 'raw': '"中文值"'}]
        with patch.object(edit.requests, 'request', return_value=_Response()) as request, \
             patch.object(edit, '_cmdb_base', return_value='http://127.0.0.1:8079'), \
             patch.object(edit, '_org', return_value='8888'):
            result = edit._import_group('HOST', rows, changes)
        self.assertEqual(result['update'], 1)
        body = request.call_args[1]['data']
        self.assertIsInstance(body, bytes)
        self.assertIn(u'中文值'.encode('utf-8'), body)
        self.assertTrue(request.call_args[1]['headers']['Content-Type'].startswith('application/json'))



class CmdbBaseTests(unittest.TestCase):
    """CMDB 地址解析优先级：agent conf > 注入 URL > EASYOPS_CMDB_HOST > EASYOPS_CMDB_SERVICE_HOST。"""

    def test_agent_conf_wins_over_injected_service_host(self):
        with patch.object(edit, '_agent_config_host_org', return_value=('172.30.0.90', '8888')), \
             patch.object(edit, 'EASYOPS_CMDB_SERVICE_HOST', '127.0.0.1', create=True), \
             patch.object(edit, 'EASYOPS_CMDB_HOST', '10.0.0.1', create=True):
            self.assertEqual(edit._cmdb_base(), 'http://172.30.0.90:8079')

    def test_backend_url_wins_when_agent_conf_missing(self):
        with patch.object(edit, '_agent_config_host_org', return_value=('', '')), \
             patch.object(edit, 'EASYOPS_CMDB_BACKEND_URL', 'http://10.0.0.9:9999/', create=True), \
             patch.object(edit, 'EASYOPS_CMDB_HOST', '10.0.0.1', create=True):
            self.assertEqual(edit._cmdb_base(), 'http://10.0.0.9:9999')

    def test_cmdb_host_wins_over_service_host(self):
        with patch.object(edit, '_agent_config_host_org', return_value=('', '')), \
             patch.object(edit, 'EASYOPS_CMDB_HOST', '10.0.0.1', create=True), \
             patch.object(edit, 'EASYOPS_CMDB_SERVICE_HOST', '10.0.0.2', create=True):
            self.assertEqual(edit._cmdb_base(), 'http://10.0.0.1:8079')

    def test_missing_everything_raises(self):
        with patch.object(edit, '_agent_config_host_org', return_value=('', '')), \
             patch.object(edit, 'EASYOPS_CMDB_BACKEND_URL', '', create=True), \
             patch.object(edit, 'EASYOPS_CMDB_HOST', '', create=True), \
             patch.object(edit, 'EASYOPS_CMDB_SERVICE_HOST', '', create=True):
            with self.assertRaises(RuntimeError) as ctx:
                edit._cmdb_base()
            self.assertIn(u'缺少 CMDB 服务地址', str(ctx.exception))


class ValidationTests(unittest.TestCase):
    def test_resolve_model_from_cmdb_model_instance(self):
        with patch.object(edit, '_search_instances',
                          return_value=([{'instanceId': 'm1', 'objectId': 'HOST', 'objectName': '主机'}], 1)):
            model_id, model_name = edit._resolve_model('m1')
        self.assertEqual(model_id, 'HOST')
        self.assertEqual(model_name, u'主机')

    def test_resolve_model_accepts_direct_object_id(self):
        with patch.object(edit, '_model_name', return_value=u'主机'):
            self.assertEqual(edit._resolve_model('HOST@EASYOPS'), ('HOST@EASYOPS', u'主机'))

    def test_resolve_model_rejects_empty(self):
        with self.assertRaises(ValueError):
            edit._resolve_model('')

    def test_validate_changes_rejects_forbidden_and_unknown_and_readonly(self):
        attrs = {
            'memo': {'name': u'备注', 'readonly': False, 'type': 'str'},
            'locked': {'name': u'只读', 'readonly': True, 'type': 'str'},
        }
        changes = [
            {'attr': 'instanceId', 'value': 'x', 'line': 1, 'raw': '"x"'},
            {'attr': 'unknown', 'value': 1, 'line': 2, 'raw': '1'},
            {'attr': 'locked', 'value': 2, 'line': 3, 'raw': '2'},
            {'attr': 'memo', 'value': 3, 'line': 4, 'raw': '3'},
        ]
        errors = edit._validate_changes(changes, {'HOST': (attrs, set())})
        joined = '\n'.join(errors)
        self.assertIn('instanceId', joined)
        self.assertIn('不属于所选模型及其子模型', joined)
        self.assertIn('只读', joined)
        self.assertNotIn('memo', joined)

    def test_validate_changes_allows_attr_defined_on_child(self):
        changes = [{'attr': 'child_only', 'value': 1, 'line': 1, 'raw': '1'}]
        attr_map = {
            'PARENT': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set()),
            'CHILD': ({'child_only': {'name': u'子属性', 'readonly': False, 'type': 'str'}}, set()),
        }
        self.assertEqual(edit._validate_changes(changes, attr_map), [])

    def test_validate_changes_skips_model_check_when_detail_unavailable(self):
        changes = [{'attr': 'whatever', 'value': 1, 'line': 1, 'raw': '1'}]
        self.assertEqual(edit._validate_changes(changes, {'HOST': (None, None)}), [])

    def test_descendants_recurses_children_bfs(self):
        def fake_cmdb(method, path, body=None, query=None):
            parent = (query or {}).get('parentObjectId')
            children = {
                'PARENT': [{'objectId': 'CHILD_A'}, {'objectId': 'CHILD_B'}],
                'CHILD_A': [{'objectId': 'GRANDCHILD'}],
            }.get(parent, [])
            return {'code': 0, 'data': {'list': children, 'total': len(children)}}

        with patch.object(edit, 'cmdb', side_effect=fake_cmdb):
            self.assertEqual(edit._descendants('PARENT'),
                             ['PARENT', 'CHILD_A', 'CHILD_B', 'GRANDCHILD'])

    def test_search_models_dedupes_parent_and_child(self):
        def fake_search(object_id, query=None, fields=None):
            if object_id == 'PARENT':
                return ([{'instanceId': 'a1', '_object_id': 'PARENT'},
                          {'instanceId': 'b1', '_object_id': 'CHILD'}], 2)
            if object_id == 'CHILD':
                return [{'instanceId': 'b1', '_object_id': 'CHILD'}], 1
            return [], 0

        changes = [{'attr': 'memo', 'value': 1, 'line': 1, 'raw': '1'}]
        attr_map = {'PARENT': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set()),
                    'CHILD': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set())}
        with patch.object(edit, '_search_instances', side_effect=fake_search):
            rows = edit._search_models(['PARENT', 'CHILD'], {}, changes, attr_map)
        self.assertEqual([row['instanceId'] for row in rows], ['a1', 'b1'])

    def test_search_fields_picks_existing_display_attr(self):
        changes = [{'attr': 'memo', 'value': 1, 'line': 1, 'raw': '1'}]
        host_map = {'HOST': ({'hostname': {'name': u'主机名', 'readonly': False, 'type': 'str'},
                              'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set())}
        self.assertEqual(edit._search_fields('HOST', changes, host_map),
                         ['instanceId', '_object_id', 'hostname', 'memo'])
        name_map = {'APP': ({'name': {'name': u'名称', 'readonly': False, 'type': 'str'},
                             'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set())}
        self.assertEqual(edit._search_fields('APP', changes, name_map),
                         ['instanceId', '_object_id', 'name', 'memo'])
        unknown_map = {'HOST': (None, None)}
        self.assertEqual(edit._search_fields('HOST', changes, unknown_map),
                         ['instanceId', '_object_id', 'memo'])

    def test_filter_groups_skips_models_missing_or_readonly_attr(self):
        attr_map = {
            'PARENT': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set()),
            'CHILD': ({'other': {'name': u'其他', 'readonly': False, 'type': 'str'}}, set()),
            'LOCKED': ({'memo': {'name': u'备注', 'readonly': True, 'type': 'str'}}, set()),
        }
        changes = [{'attr': 'memo', 'value': 1, 'line': 1, 'raw': '1'}]
        groups = [('PARENT', [{'instanceId': 'a1'}]), ('CHILD', [{'instanceId': 'b1'}]),
                  ('LOCKED', [{'instanceId': 'c1'}])]
        kept, skipped = edit._filter_groups(groups, changes, attr_map)
        self.assertEqual([model for model, _ in kept], ['PARENT'])
        self.assertEqual([item['model'] for item in skipped], ['CHILD', 'LOCKED'])
        self.assertIn('缺少属性 memo', skipped[0]['reason'])
        self.assertIn('只读', skipped[1]['reason'])


class WriteTests(unittest.TestCase):
    def test_group_rows_dedupes_and_groups_by_actual_model(self):
        rows = [
            {'instanceId': 'a1', '_object_id': 'HOST'},
            {'instanceId': 'a2', '_object_id': 'HOST'},
            {'instanceId': 'a1', '_object_id': 'HOST'},
            {'instanceId': 'b1', '_object_id': 'HOST_CHILD'},
        ]
        groups = edit._group_rows(rows, 'HOST')
        self.assertEqual([model for model, _ in groups], ['HOST', 'HOST_CHILD'])
        self.assertEqual([row['instanceId'] for row in groups[0][1]], ['a1', 'a2'])
        self.assertEqual([row['instanceId'] for row in groups[1][1]], ['b1'])

    def test_import_group_builds_upsert_payload_and_aggregates(self):
        rows = [{'instanceId': 'a1'}, {'instanceId': 'a2'}]
        changes = [{'attr': 'memo', 'value': u'新值', 'line': 1, 'raw': '"新值"'},
                   {'attr': 'port', 'value': 8080, 'line': 2, 'raw': '8080'}]
        calls = []

        def fake_cmdb(method, path, body=None, query=None):
            calls.append((method, path, body))
            return {'code': 0, 'data': {'insert_count': 0, 'update_count': 2, 'failed_count': 0, 'data': []}}

        with patch.object(edit, 'cmdb', side_effect=fake_cmdb):
            result = edit._import_group('HOST', rows, changes)
        self.assertEqual(result['update'], 2)
        self.assertEqual(result['failed'], 0)
        method, path, body = calls[0]
        self.assertEqual((method, path), ('POST', '/object/HOST/instance/_import'))
        self.assertEqual(body['keys'], ['instanceId'])
        self.assertTrue(body['importMetadata'])
        self.assertTrue(body['disableNestedCreateInstance'])
        self.assertEqual(body['datas'][0], {'instanceId': 'a1', 'memo': u'新值', 'port': 8080})
        self.assertEqual(len(body['datas']), 2)

    def test_import_group_collects_failures_and_insert_warning(self):
        rows = [{'instanceId': 'a1'}]
        changes = [{'attr': 'memo', 'value': 1, 'line': 1, 'raw': '1'}]
        response = {'code': 0, 'data': {'insert_count': 1, 'update_count': 0, 'failed_count': 1,
                                        'data': [{'code': 133001, 'error': '只读', 'data': {'instanceId': 'a1'}}]}}
        with patch.object(edit, 'cmdb', return_value=response):
            result = edit._import_group('HOST', rows, changes)
        self.assertTrue(result['insert_warn'])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['details'][0]['instanceId'], 'a1')
        self.assertEqual(result['details'][0]['error'], u'只读')

    def test_readback_counts_ok_mismatch_missing(self):
        groups = [('HOST', [{'instanceId': 'a1'}, {'instanceId': 'a2'}, {'instanceId': 'a3'}])]
        changes = [{'attr': 'memo', 'value': u'新', 'line': 1, 'raw': '"新"'}]

        def fake_search(object_id, query=None, fields=None):
            ids = query['instanceId']['$in']
            rows = []
            if 'a1' in ids:
                rows.append({'instanceId': 'a1', 'memo': u'新'})
            if 'a2' in ids:
                rows.append({'instanceId': 'a2', 'memo': u'旧'})
            return rows, len(rows)

        attr_map = {'HOST': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set())}
        with patch.object(edit, '_search_instances', side_effect=fake_search):
            result = edit._readback(groups, changes, attr_map)
        self.assertEqual(result['ok'], 1)
        self.assertEqual(result['mismatch'], 1)
        self.assertEqual(result['missing'], 1)
        self.assertEqual(result['details'][0]['attr'], 'memo')

    def test_values_equal_is_tolerant(self):
        self.assertTrue(edit._values_equal(1, 1.0))
        self.assertTrue(edit._values_equal({'instanceId': 'a'}, {'instanceId': 'a', 'name': 'x'}))
        self.assertTrue(edit._values_equal(['a', 'b'], ['b', 'a']))
        self.assertTrue(edit._values_equal('a', ['a', 'b']))
        self.assertFalse(edit._values_equal('a', 'b'))
        self.assertFalse(edit._values_equal(True, 1))


class MainTests(unittest.TestCase):
    def _patch_platform(self, rows, import_counts=None):
        def fake_search(object_id, query=None, fields=None):
            if isinstance(query, dict) and 'instanceId' in query:
                ids = query['instanceId'].get('$in') or []
                return [row for row in rows if row['instanceId'] in ids], len(ids)
            return list(rows), len(rows)

        def fake_cmdb(method, path, body=None, query=None):
            if path.endswith('/instance/_import'):
                counts = import_counts or {'insert_count': 0, 'update_count': len(body['datas']),
                                           'failed_count': 0, 'data': []}
                return {'code': 0, 'data': counts}
            raise AssertionError('unexpected cmdb call: %s %s' % (method, path))

        return fake_search, fake_cmdb

    def _run(self, action, rows, query='{"ip":{"$like":"10.1.%"}}', changes='memo="新备注"', import_counts=None):
        captured = {}
        fake_search, fake_cmdb = self._patch_platform(rows, import_counts)
        edit.cmdb_model = 'm1'
        edit.query = query
        edit.changes = changes
        edit.action = action
        with patch.object(edit, '_resolve_model', return_value=('HOST', u'主机')), \
             patch.object(edit, '_descendants', return_value=['HOST']), \
             patch.object(edit, '_model_attrs', return_value=({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set())), \
             patch.object(edit, '_search_instances', side_effect=fake_search), \
             patch.object(edit, 'cmdb', side_effect=fake_cmdb), \
             patch.object(edit, 'put_str', side_effect=lambda key, value: captured.update({key: value})):
            code = edit.main()
        return code, captured

    def test_preview_reports_before_after_without_writing(self):
        rows = [{'instanceId': 'a1', 'name': 'host-1', '_object_id': 'HOST', 'memo': u'旧备注'}]
        code, captured = self._run(u'预览', rows)
        self.assertEqual(code, 0)
        self.assertIn(u'预览', captured['report'])
        self.assertIn(u'memo: "旧备注" -> "新备注"', captured['report'])
        self.assertIn(u'未写入', captured['summary'])

    def test_execute_imports_and_readbacks(self):
        rows = [{'instanceId': 'a1', 'name': 'host-1', '_object_id': 'HOST', 'memo': u'旧备注'},
                {'instanceId': 'a2', 'name': 'host-2', '_object_id': 'HOST', 'memo': u'旧备注'}]
        code, captured = self._run(u'执行', rows)
        self.assertEqual(code, 0)
        self.assertIn(u'update=2', captured['report'])
        self.assertIn(u'一致 2 项', captured['report'])
        self.assertIn(u'更新=2', captured['summary'])

    def test_execute_rejects_empty_query(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(u'执行', [], query='')
        self.assertIn('拒绝空 query', str(ctx.exception))

    def test_execute_returns_nonzero_on_failures(self):
        rows = [{'instanceId': 'a1', '_object_id': 'HOST', 'memo': u'旧'}]
        counts = {'insert_count': 0, 'update_count': 0, 'failed_count': 1,
                  'data': [{'code': 1, 'error': '失败', 'data': {'instanceId': 'a1'}}]}
        code, captured = self._run(u'执行', rows, import_counts=counts)
        self.assertEqual(code, 1)
        self.assertIn(u'失败明细', captured['report'])
        self.assertIn(u'失败=1', captured['summary'])

    def test_preview_allows_empty_query(self):
        code, captured = self._run(u'预览', [], query='')
        self.assertEqual(code, 0)
        self.assertIn(u'模型下全部实例', captured['report'])

    def test_preview_includes_parent_and_child_models(self):
        rows = [{'instanceId': 'a1', '_object_id': 'HOST', 'memo': u'旧'},
                {'instanceId': 'b1', '_object_id': 'HOST_CHILD', 'memo': u'旧'}]
        fake_search, fake_cmdb = self._patch_platform(rows)
        attr_map = {
            'HOST': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set()),
            'HOST_CHILD': ({'memo': {'name': u'备注', 'readonly': False, 'type': 'str'}}, set()),
        }
        captured = {}
        edit.cmdb_model = 'm1'
        edit.query = '{"ip":{"$like":"10.1.%"}}'
        edit.changes = 'memo="新"'
        edit.action = u'预览'
        with patch.object(edit, '_resolve_model', return_value=('HOST', u'主机')), \
             patch.object(edit, '_descendants', return_value=['HOST', 'HOST_CHILD']), \
             patch.object(edit, '_model_attrs', side_effect=lambda model: attr_map[model]), \
             patch.object(edit, '_search_instances', side_effect=fake_search), \
             patch.object(edit, 'cmdb', side_effect=fake_cmdb), \
             patch.object(edit, 'put_str', side_effect=lambda key, value: captured.update({key: value})):
            code = edit.main()
        self.assertEqual(code, 0)
        self.assertIn(u'含 1 个子模型', captured['report'])
        self.assertIn(u'HOST_CHILD', captured['report'])
        self.assertIn(u'命中实例：2 条', captured['report'])


class PackageTests(unittest.TestCase):
    def test_tool_package_structure_and_config(self):
        self.assertTrue(PACKAGE.exists(), '工具包不存在: %s' % PACKAGE)
        with tarfile.open(str(PACKAGE), 'r:gz') as bundle:
            names = bundle.getnames()
            root = 'CMDB实例批量编辑'
            for member in ('._easyPackageConfig.dat', 'config', 'script'):
                self.assertIn('%s/%s' % (root, member), names)
            self.assertFalse([name for name in names if '__pycache__' in name or name.endswith('.pyc')])
            dat = json.loads(bundle.extractfile('%s/._easyPackageConfig.dat' % root).read().decode('utf-8'))
            config = json.loads(bundle.extractfile('%s/config' % root).read().decode('utf-8'))
            script = bundle.extractfile('%s/script' % root).read()

        self.assertEqual(dat['package']['packageId'], dat['version']['packageId'])
        self.assertEqual(dat['version']['versionId'], config['vId'])
        self.assertEqual(dat['package']['name'], root)
        self.assertTrue(config['sandboxRun'])
        self.assertEqual(config['type'], 'python')
        self.assertEqual(script, SOURCE.read_bytes())

        inputs = {item['name']: item for item in config['inputs']}
        self.assertEqual(inputs['cmdb_model']['type'], 'cmdbInstance')
        self.assertFalse(inputs['cmdb_model']['multiple'])
        self.assertEqual(inputs['cmdb_model']['cmdbObjectId'], 'CMDB_MODEL@EASYOPS')
        self.assertEqual(inputs['cmdb_model']['cmdbAttrId'], 'instanceId')
        self.assertEqual(inputs['query']['type'], 'strings')
        self.assertEqual(inputs['changes']['type'], 'strings')
        self.assertEqual(inputs['action']['enum'], [u'预览', u'执行'])
        self.assertEqual(inputs['action']['default'], u'预览')
        self.assertEqual([item['id'] for item in config['outputDefs']], ['report', 'summary'])

    def test_source_parses_as_python2(self):
        try:
            from lib2to3.refactor import RefactoringTool
            from lib2to3.pgen2.parse import ParseError
        except Exception:
            self.skipTest('lib2to3 不可用')
        source = SOURCE.read_text(encoding='utf-8')
        try:
            RefactoringTool([]).refactor_string(source + '\n', name='cmdb_instance_batch_edit.py')
        except ParseError as error:
            self.fail('Python 2 语法解析失败: %s' % error)


if __name__ == '__main__':
    unittest.main()
