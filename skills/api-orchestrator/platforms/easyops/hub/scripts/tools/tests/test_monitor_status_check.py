"""实例明细、执行主机关联和无执行主机状态回归。"""
import importlib.util
import csv
import io
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'monitor_status_check.py'
SPEC = importlib.util.spec_from_file_location('monitor_status_check', str(SOURCE))
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class MonitorStatusTests(unittest.TestCase):
    def test_cmdb_requests_optional_zabbix_memo(self):
        with patch.object(monitor, 'cmdb', return_value={'data': {'list': []}}) as request:
            monitor._search_instances('HOST')
        body = request.call_args.args[2]
        self.assertIn('zabbix_memo', body['fields'])
        self.assertTrue(body['ignore_missing_field_error'])

    def test_main_preserves_memo_and_blanks_missing_values(self):
        instances = [{'instanceId': 'present', 'zabbix_memo': '来自Zabbix,备注'},
                     {'instanceId': 'absent'}, {'instanceId': 'null', 'zabbix_memo': None}]
        captured = []
        with patch.object(monitor, '_selected_models', return_value=[]), \
             patch.object(monitor, '_instance_groups', return_value=[('HOST', '主机', instances)]), \
             patch.object(monitor, '_model_jobs', return_value=[]), \
             patch.object(monitor, '_write_csv', side_effect=lambda rows: captured.extend(rows) or 'memory.csv'), \
             patch.object(monitor, '_base_url', return_value='http://example.invalid'), \
             patch.object(monitor, 'put_str'):
            monitor.main()
        self.assertEqual([row['zabbix_memo'] for row in captured], ['来自Zabbix,备注', '', ''])

    def test_csv_contains_optional_memo_column(self):
        stream = io.StringIO()
        with patch.object(monitor.io, 'open', return_value=stream), patch.object(stream, 'close'):
            monitor._write_csv([{'instance': 'one', 'zabbix_memo': '备注,"引号"'}, {'instance': 'two'}])
        rows = list(csv.DictReader(io.StringIO(stream.getvalue().lstrip('\ufeff'))))
        self.assertIn('zabbix_memo', rows[0])
        self.assertEqual(rows[0]['zabbix_memo'], '备注,"引号"')
        self.assertEqual(rows[1]['zabbix_memo'], '')

    def test_instance_detail_uses_config_id_and_internal_monitor_api(self):
        pages = [{'data': {'instances': [{'instanceId': 'one'}, {'instanceId': 'two'}], 'total': 3}},
                 {'data': {'instances': [{'instanceId': 'three'}], 'total': 3}}]
        with patch.object(monitor, 'DEFAULT_PAGE_SIZE', 2), patch.object(monitor, '_monitor_get', side_effect=pages) as request:
            rows = monitor._job_instances({'configId': 'job'})
        self.assertEqual(len(rows), 3)
        self.assertEqual(request.call_args_list[0].args[0], monitor.MONITOR_INSTANCES_BACKEND_PATH)
        query = request.call_args_list[0].args[2]
        self.assertEqual(query['configId'], 'job')
        self.assertEqual(query['statusFilter'], 'all')
        self.assertEqual(query['name'], '')
        self.assertNotIn('jobId', query)
        self.assertEqual(request.call_args_list[1].args[2]['page'], 2)

    def test_execution_host_uuid_is_not_target_uuid(self):
        mapping = {'target': {'instanceId': 'target', '_uuid': 'target-uuid',
                              'executionHosts': [{'uuid': 'executor-uuid'}]}}
        with patch.object(monitor, '_status_get', return_value={'data': {'list': [{'instanceId': 'target', 'status': 'ok', 'lastErr': ''}]}}) as request:
            result = monitor._status_map({'configId': 'job', 'uuid': 'job-uuid'}, ['target'], mapping)
        self.assertEqual(request.call_args.args[0]['list'], [{'instanceId': 'target', 'uuid': 'executor-uuid'}])
        self.assertEqual(monitor._row_status(result['target']), '成功')

    def test_missing_executor_does_not_poison_other_instances(self):
        mapping = {'ready': {'uuid': 'executor'}, 'missing': {'_uuid': 'asset-uuid', 'executionHosts': [{'uuid': ''}]}}
        with patch.object(monitor, '_status_get', return_value={'data': {'list': [{'instanceId': 'ready', 'status': 'failed', 'lastErr': 'target null:161'}]}}) as request:
            result = monitor._status_map({'configId': 'job'}, ['ready', 'missing', 'not-covered'], mapping)
        self.assertEqual(request.call_args.args[0]['list'], [{'instanceId': 'ready', 'uuid': 'executor'}])
        self.assertEqual(result['ready']['lastErr'], 'target null:161')
        self.assertEqual(monitor._row_status(result['missing']), '未知')
        self.assertIn('执行主机', result['missing']['lastErr'])
        self.assertNotIn('not-covered', result)

    def test_all_missing_never_calls_status_api(self):
        with patch.object(monitor, '_status_get') as request:
            result = monitor._status_map({'configId': 'job', 'uuid': 'not-an-executor'}, ['target'], {'target': {'executionHosts': [{'uuid': ''}]}})
        request.assert_not_called()
        self.assertEqual(monitor._row_status(result['target']), '未知')

    def test_collector_instance_id_is_not_an_agent_uuid(self):
        with patch.object(monitor, '_status_get') as request:
            result = monitor._status_map({'configId': 'job'}, ['target'], {'target': {'collector': {'instanceId': 'host-cmdb-id'}}})
        request.assert_not_called()
        self.assertEqual(monitor._row_status(result['target']), '未知')

    def test_status_queries_are_batched(self):
        mapping = {str(index): {'uuid': 'executor'} for index in range(3)}
        with patch.object(monitor, 'DEFAULT_PAGE_SIZE', 2), patch.object(monitor, '_status_get', return_value={'data': {'list': []}}) as request:
            result = monitor._status_map({'configId': 'job'}, list(mapping), mapping)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(monitor._row_status(row) == '未知' for row in result.values()))

    def test_multiple_execution_hosts_aggregate_without_overwrite(self):
        mapping = {'target': {'executionHosts': [{'uuid': 'first'}, {'uuid': 'second'}, {'uuid': 'first'}]}}
        response = {'data': {'list': [{'instanceId': 'target', 'uuid': 'first', 'status': 'ok', 'lastErr': ''},
                                      {'instanceId': 'target', 'uuid': 'second', 'status': 'failed', 'lastErr': 'SNMP timeout'}]}}
        with patch.object(monitor, '_status_get', return_value=response) as request:
            result = monitor._status_map({'configId': 'job'}, ['target'], mapping)
        self.assertEqual(len(request.call_args.args[0]['list']), 2)
        self.assertEqual(monitor._row_status(result['target']), '部分成功')
        self.assertIn('SNMP timeout', result['target']['lastErr'])

    def test_no_response_does_not_fabricate_success(self):
        with patch.object(monitor, '_status_get', return_value={'data': {'list': []}}):
            result = monitor._status_map({'configId': 'job'}, ['target'], {'target': {'uuid': 'executor'}})
        self.assertEqual(monitor._row_status(result['target']), '未知')
        self.assertIn('未返回', result['target']['lastErr'])


if __name__ == '__main__':
    unittest.main()
