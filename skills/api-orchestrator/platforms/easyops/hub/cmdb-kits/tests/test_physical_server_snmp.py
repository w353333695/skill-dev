"""从实际交付 ZIP 加载独立脚本，离线验证容错、资产映射及参数注入。"""
import io
import ast
import os
import sys
import tempfile
import logging
from unittest.mock import patch
import json
import re
import types
import unittest
import zipfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
PACKAGES = list(HUB.glob('CMDB采集套件_物理服务器SNMP信息采集_*.zip'))
PACKAGE = max(PACKAGES, key=lambda path: tuple(map(int, path.stem.rsplit('_', 1)[1].split('.'))))
with zipfile.ZipFile(PACKAGE) as archive:
    ORIGINAL = archive.read('物理服务器SNMP信息采集/src/server_snmp_collect.orig').decode('utf-8')
    INJECTED = archive.read('物理服务器SNMP信息采集/src/server_snmp_collect.py').decode('utf-8')
    PLUGIN = json.loads(archive.read('物理服务器SNMP信息采集/plugin.yaml'))
    DICTIONARY = json.loads(archive.read('物理服务器SNMP信息采集/oid-dictionary.json'))
collector = types.ModuleType('server_snmp_collect')
exec(compile(ORIGINAL, str(PACKAGE) + '/server_snmp_collect.orig', 'exec'), collector.__dict__)


class FakeTransport:
    def __init__(self, profile='dell-idrac', values=None, failures=None):
        self.values = {collector.SYS_OBJECT: collector.PROFILES[profile]['prefixes'][0], collector.SYS_DESCR: ''}
        self.values.update(values or {})
        self.failures = failures or {}
        self.calls = []
        self.config = {}
        self.issues = []

    def get(self, oids, **kwargs):
        self.calls.extend(oids)
        for oid in oids:
            if oid in self.failures:
                raise self.failures[oid]
        return {oid: self.values[oid] for oid in oids if oid in self.values}

    def walk(self, root):
        self.calls.append(root)
        if root in self.failures:
            raise self.failures[root]
        return {oid: value for oid, value in self.values.items() if oid.startswith(root + '.')}


def table(profile, kind):
    return next(item for item in collector.PROFILES[profile]['tables'] if item['kind'] == kind)


def bindings(specification, rows):
    return {specification['root'] + '.' + specification['fields'][field]['column'] + '.' + index: value
            for index, fields in rows.items() for field, value in fields.items()}


def collect(transport, previous=None):
    return collector.collect({'instanceId': 'fixture-server', 'snmp_conf': {'enabled': True},
                              'previous': previous or {}}, transport)


def server(records):
    return next(item['vals'] for item in records if item['dims']['object_id'] == collector.SERVER_MODEL)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.previous_log_level = collector.LOGGER.level
        collector.LOGGER.setLevel(logging.CRITICAL)

    def tearDown(self):
        collector.LOGGER.setLevel(self.previous_log_level)

    def test_entity_timeout_continues_to_private_identity(self):
        oid = collector.PROFILES['dell-idrac']['scalars']['sn']['oid']
        transport = FakeTransport(values={oid: 'DELL123'}, failures={collector.ENTITY: collector.CollectionError('Timeout: No Response')})
        result = server(collect(transport))
        self.assertEqual(result['sn'], 'DELL123')
        self.assertEqual(result['brand'], 'Dell')
        self.assertIn(collector.FC_PORT, transport.calls)
        self.assertTrue(transport.issues)

    def test_private_column_timeout_continues_same_table_and_later_tables(self):
        cpu = table('ibm-imm', 'cpuInfo')
        fan = table('ibm-imm', 'fans')
        values = bindings(cpu, {'1': {'totalCores': 8, 'totalThreads': 16, 'id': 'CPU1'}})
        values.update(bindings(fan, {'1': {'fanName': 'Fan1', 'currentReading': '5000 RPM'}}))
        failed_oid = cpu['fields']['mdl']['oid']
        transport = FakeTransport('ibm-imm', values, {failed_oid: collector.CollectionError('Timeout: No Response')})
        result = server(collect(transport))
        self.assertEqual(result['fans'][0]['fanName'], 'Fan1')
        self.assertIn(cpu['fields']['totalCores']['oid'], transport.calls)
        self.assertNotIn('cpuCoreCount', result)

    def test_preflight_failure_remains_fatal(self):
        with self.assertRaises(collector.CollectionError):
            collect(FakeTransport(failures={collector.SYS_OBJECT: collector.CollectionError('No Response')}))

    def test_missing_tool_remains_fatal(self):
        with self.assertRaises(OSError):
            collect(FakeTransport(failures={collector.ENTITY: OSError(2, 'missing executable')}))

    def test_security_failure_remains_fatal(self):
        with self.assertRaises(collector.CollectionError):
            collect(FakeTransport(failures={collector.ENTITY: collector.CollectionError('Authentication failure')}))

    def test_uuid_hex_continuation_without_indentation(self):
        oid = '1.2.3.0'
        parsed = collector.parse_walk('.1.2.3.0 = Hex-STRING: 00 01 02 03 04 05 06 07\n08 09 0A 0B 0C 0D 0E 0F\n.1.2.4.0 = ""')
        self.assertEqual(parsed[oid].raw_hex.lower(), '000102030405060708090a0b0c0d0e0f')
        self.assertEqual(parsed['1.2.4.0'], '')

    def test_cores_and_threads_sum(self):
        specification = table('dell-idrac', 'cpuInfo')
        data = bindings(specification, {'1': {'mdl': 'CPU-A', 'totalCores': 8, 'totalThreads': 16},
                                        '2': {'mdl': 'CPU-B', 'totalCores': 12, 'totalThreads': 24}})
        result = {}
        collector.collect_private_table(data, specification, result, [], 'fixture-server')
        self.assertEqual((result['cpuNum'], result['cpuCoreCount'], result['cpuThreadNum']), (2, 20, 40))

    def test_missing_core_does_not_publish_partial_sum(self):
        specification = table('dell-idrac', 'cpuInfo')
        result = {}
        collector.collect_private_table(bindings(specification, {'1': {'mdl': 'A', 'totalCores': 8}, '2': {'mdl': 'B'}}), specification, result, [], 'fixture-server')
        self.assertNotIn('cpuCoreCount', result)
        self.assertEqual(len(result['cpuInfo']), 2)

    def test_bad_row_does_not_discard_other_rows(self):
        specification = table('dell-idrac', 'cpuInfo')
        result = {}
        collector.collect_private_table(bindings(specification, {'1': {'totalCores': 8}, '2': {'mdl': 'CPU-B', 'totalCores': 12}}), specification, result, [], 'fixture-server')
        self.assertEqual(len(result['cpuInfo']), 1)
        self.assertNotIn('cpuCoreCount', result)
        self.assertNotIn('cpuNum', result)

    def test_gpu_mapping(self):
        for profile in ('ibm-imm', 'lenovo-xcc'):
            with self.subTest(profile=profile):
                specification = table(profile, 'gpuInfo')
                result = {}
                collector.collect_private_table(bindings(specification, {'1': {'name': 'GPU-1', 'mdl': 'GPU Model', 'manufacturer': 'Vendor'}}), specification, result, [], 'fixture-server')
                self.assertEqual(result['gpuInfo'][0]['mdl'], 'GPU Model')

    def test_fans_use_model_field_names(self):
        specification = table('dell-idrac', 'fans')
        result = {}
        collector.collect_private_table(bindings(specification, {'1': {'fanName': 'Fan1', 'currentReading': 3000}}), specification, result, [], 'fixture-server')
        self.assertEqual(result['fans'][0]['fanName'], 'Fan1')
        self.assertNotIn('name', result['fans'][0])

    def test_fcoe_uses_fc_address_not_ethernet_mac(self):
        specification = table('ibm-imm', 'convergedPorts')
        records = []
        result = {'networkInfo': [{'name': 'CNA@1', 'model': 'CNA Model', 'portCount': 2}]}
        values = bindings(specification, {'1': {'name': 'CNA', 'protocol': 'FCoE', 'address': '00:11:22:33:44:55', 'fcoeAddress': '10:00:00:11:22:33:44:55', 'portNumber': 1}})
        collector.collect_private_table(values, specification, result, records, 'fixture-server')
        port = next(item['vals'] for item in records if item['dims']['object_id'] == 'FIBER_CHANNEL_PORT@ONEMODEL')
        self.assertEqual(port['wwpn'], '10:00:00:11:22:33:44:55')
        self.assertEqual(port['physicalServer'][0]['instanceId'], 'fixture-server')
        self.assertNotIn('fiber_channel_switch', port)
        self.assertTrue(result['hbaInfo'])

    def test_injection_and_standalone_compilation(self):
        compile(INJECTED, 'server_snmp_collect.py', 'exec')
        for name in PLUGIN['params']:
            self.assertIn('%s = os.environ.get("EASYOPS_COLLECTOR_%s")' % (name, name), INJECTED[:2500])
        self.assertIn(ORIGINAL.split('\n', 1)[1], INJECTED)

    def test_dictionary_and_runtime_rules_match(self):
        indexed = {(item['symbol'], item['oid']) for item in DICTIONARY}
        for profile in collector.PROFILES.values():
            rules = list(profile.get('scalars', {}).values())
            rules += [rule for specification in profile.get('tables', []) for rule in specification['fields'].values()]
            for rule in rules:
                self.assertIn((rule['symbol'], rule['oid'].removesuffix('.0') if 'column' not in rule else rule['oid']), indexed)
                if 'column' in rule:
                    self.assertTrue(rule['oid'].endswith('.' + rule['column']))

    def test_dell_supply_watts_unit(self):
        specification = table('dell-idrac', 'powers')
        result = {}
        collector.collect_private_table(bindings(specification, {'1': {'name': 'PSU1', 'powerCapacityWatts': 7500}}), specification, result, [], 'fixture-server')
        self.assertEqual(result['powers'][0]['powerCapacityWatts'], '750')
        self.assertNotIn('lastPowerOutputWatts', result['powers'][0])

    def test_bmc_firmware_is_not_host_os_or_cpu_microcode(self):
        specification = table('ibm-imm', 'firmwareInventory')
        result = {}
        collector.collect_private_table(bindings(specification, {'1': {'name': 'spFirmware', 'version': '2.0'}, '2': {'name': 'Bios', 'version': '1.0'}}), specification, result, [], 'fixture-server')
        self.assertEqual(result['firmware'], '2.0')
        self.assertNotIn('microcode', result)
        self.assertNotIn('sysVersion', result)

    def test_empty_collection_is_fatal(self):
        transport = FakeTransport('generic') if collector.PROFILES['generic']['prefixes'] else FakeTransport()
        transport.values = {collector.SYS_OBJECT: '1.3.6.1.4.1.99999.1'}
        with self.assertRaises(collector.CollectionError):
            collect(transport)

    def test_optional_cpu_column_failure_does_not_prevent_core_sum(self):
        specification = table('dell-idrac', 'cpuInfo')
        values = bindings(specification, {'1': {'mdl': 'CPU', 'totalCores': 8, 'totalThreads': 16}})
        transport = FakeTransport(values=values, failures={specification['fields']['manufacturer']['oid']: collector.CollectionError('No Response')})
        result = server(collect(transport))
        self.assertEqual(result['cpuCoreCount'], 8)
        self.assertEqual(result['cpuNum'], 1)

    def test_cpu_core_column_failure_does_not_publish_sum(self):
        specification = table('dell-idrac', 'cpuInfo')
        values = bindings(specification, {'1': {'mdl': 'CPU', 'totalThreads': 16}})
        transport = FakeTransport(values=values, failures={specification['fields']['totalCores']['oid']: collector.CollectionError('No Response')})
        result = server(collect(transport))
        self.assertNotIn('cpuCoreCount', result)
        self.assertEqual(result['cpuThreadNum'], 16)

    def test_partial_inventory_keeps_old_unobserved_rows(self):
        specification = table('dell-idrac', 'cpuInfo')
        values = bindings(specification, {'1': {'mdl': 'CPU-A', 'name': 'CPU1'}})
        previous = {'cpuInfo': [{'name': 'CPU1', 'mdl': 'old', 'totalCores': 8}, {'name': 'CPU2', 'mdl': 'CPU-B', 'totalCores': 8}]}
        result = server(collect(FakeTransport(values=values), previous))
        self.assertEqual(len(result['cpuInfo']), 2)
        self.assertEqual(result['cpuInfo'][0]['totalCores'], 8)
        self.assertNotIn('cpuCoreCount', result)

    def test_budget_keeps_collected_cpu_fields(self):
        specification = table('dell-idrac', 'cpuInfo')
        values = bindings(specification, {'1': {'mdl': 'CPU', 'name': 'CPU1'}})
        transport = FakeTransport(values=values, failures={specification['fields']['name']['oid']: collector.BudgetExceeded('budget exhausted')})
        result = server(collect(transport))
        self.assertEqual(result['cpuInfo'][0]['mdl'], 'CPU')
        self.assertTrue(transport.budget_stopped)
        self.assertNotIn('cpuCoreCount', result)

    def test_huawei_presence_unknown_skips_only_one_row(self):
        specification = table('huawei-ibmc', 'powers')
        values = bindings(specification, {'1': {'name': 'PSU1'}, '2': {'name': 'PSU2', 'mdl': 'Model'}})
        values[specification['root'] + '.9.1'] = 3
        values[specification['root'] + '.9.2'] = 2
        result = {}
        collector.collect_private_table(values, specification, result, [], 'fixture-server')
        self.assertEqual([item['name'] for item in result['powers']], ['PSU2'])

    def test_hba_ambiguous_adapter_names_are_not_inferred(self):
        specification = table('ibm-imm', 'convergedPorts')
        result = {'networkInfo': [{'name': 'CNA@1'}, {'name': 'CNA@2'}]}
        records = []
        collector.collect_private_table(bindings(specification, {'1': {'name': 'CNA', 'protocol': 'FC', 'address': '10:00:00:11:22:33:44:55'}}), specification, result, records, 'fixture-server')
        self.assertNotIn('hbaInfo', result)
        self.assertEqual(len(records), 1)

    def test_dell_network_inventory_does_not_leak_helper_fields_to_port(self):
        specification = table('dell-idrac', 'networkPorts')
        result = {}
        records = []
        collector.collect_private_table(bindings(specification, {'1': {'ifName': 'NIC.1', 'inventoryModel': 'NIC Model', 'inventoryManufacturer': 'Vendor', 'physAddress': '00:11:22:33:44:55'}}), specification, result, records, 'fixture-server')
        self.assertEqual(result['networkInfo'][0]['model'], 'NIC Model')
        self.assertNotIn('inventoryModel', records[0]['vals'])

    def test_missing_identity_is_never_written_as_null(self):
        result = server(collect(FakeTransport()))
        self.assertNotIn('mdl', result)
        self.assertNotIn('sn', result)
        self.assertEqual(result['brand'], 'Dell')

    def test_null_like_secrets_do_not_corrupt_logs(self):
        self.assertEqual(collector.redact('{"a": null}', ['null', 'None']), '{"a": null}')
        self.assertNotIn('private-value', collector.redact('private-value', ['private-value']))

    def test_dell_thread_and_huawei_logical_name_columns(self):
        self.assertEqual(table('dell-idrac', 'cpuInfo')['fields']['totalThreads']['oid'], '1.3.6.1.4.1.674.10892.5.4.1100.30.1.19')
        self.assertEqual(table('huawei-ibmc', 'logicalDrives')['fields']['name']['column'], '19')

    def test_model_fields_and_discovery_models_remain_valid(self):
        with zipfile.ZipFile(PACKAGE) as archive:
            models = json.loads(archive.read('物理服务器SNMP信息采集/PHYSICAL_SERVER@ONEMODEL.json'))
            discovery = json.loads(archive.read('物理服务器SNMP信息采集/resource_discovery_define.json'))
        fields = {item['id']: item for item in models[0]['attrList']}
        for kind in ('cpuInfo', 'powers', 'fans', 'gpuInfo', 'hbaInfo', 'networkInfo'):
            allowed = {item['id'] for item in fields[kind]['value']['struct_define']}
            for profile in collector.PROFILES.values():
                for specification in profile['tables']:
                    if specification['kind'] == kind:
                        self.assertTrue(set(specification['fields']).issubset(allowed), (kind, specification))
        self.assertEqual(models[0]['view']['attr_authorizers']['snmp_conf']['authorizers'], ['easyops'])
        for model in ('PHYSICAL_SERVER@ONEMODEL', 'NETDPORT@ONEMODEL', 'FIBER_CHANNEL_PORT@ONEMODEL'):
            self.assertIn(model, json.dumps(discovery))

    def test_partial_process_stdout_is_retained_and_secret_redacted(self):
        root = Path(__file__).resolve().parents[7] / 'projects/api-cli/.local/snmp-tests'
        root.mkdir(parents=True, exist_ok=True)
        config = collector.connection_config({'target': '192.0.2.10', 'version': '2c'}, {'community': 'sensitive-fixture'})
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        collector.LOGGER.addHandler(handler)
        previous_level = collector.LOGGER.level
        collector.LOGGER.setLevel(logging.DEBUG)
        try:
            with tempfile.TemporaryDirectory(dir=str(root)) as directory:
                with collector.NetSnmp(config, directory) as transport:
                    transport.stage = 'private.table.fixture'
                    transport.command = lambda *args: [sys.executable, '-c', 'import sys;sys.stdout.write(".1.2.3.1 = INTEGER: 8\\n");sys.stderr.write("Timeout: No Response sensitive-fixture");sys.exit(1)']
                    result = transport.walk('1.2.3')
                    self.assertEqual(result['1.2.3.1'], 8)
                    self.assertEqual(transport.requests[-1]['status'], 'partial')
                    self.assertTrue(transport.issues)
            self.assertIn('Traceback', stream.getvalue())
            self.assertNotIn('sensitive-fixture', stream.getvalue())
        finally:
            collector.LOGGER.removeHandler(handler)
            collector.LOGGER.setLevel(previous_level)


    def test_ascii_uuid_continuation_and_empty_description_from_real_response_shape(self):
        raw = '.1.3.6.1.4.1.2.3.51.3.1.5.2.1.4.0 = Hex-STRING: 30 31 32 33 34 35 36 37 38 39 41 42 43 44 45 46\n30 31 32 33 34 35 36 37 38 39 41 42 43 44 45 46\n.1.3.6.1.2.1.1.2.0 = OID: 1.3.6.1.4.1.674.10892.5\n.1.3.6.1.2.1.1.1.0 = ""'
        warnings = []
        values = collector.parse_walk(raw, warnings)
        self.assertEqual(str(values['1.3.6.1.4.1.2.3.51.3.1.5.2.1.4.0']), '0123456789ABCDEF0123456789ABCDEF')
        self.assertEqual(values[collector.SYS_OBJECT], '1.3.6.1.4.1.674.10892.5')
        self.assertEqual(warnings, [])

    def test_security_and_optional_exception_classification(self):
        for message in ('Authentication failure', 'Unknown user name', 'Decryption error', 'Unsupported security level'):
            with self.subTest(message=message):
                self.assertEqual(collector.diagnostic_status(collector.CollectionError(message)), 'security_error')
        for error in (collector.ConfigError('invalid local rule'), OSError(13, 'permission denied')):
            with self.assertRaises(type(error)):
                collect(FakeTransport(failures={collector.ENTITY: error}))

    def test_all_preflight_configuration_errors_fail_with_logs(self):
        import contextlib
        output = io.StringIO()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        collector.LOGGER.addHandler(handler)
        try:
            with patch.dict(os.environ, {'EASYOPS_COLLECTOR_logLevel': 'DEBUG'}, clear=True), contextlib.redirect_stdout(output):
                self.assertEqual(collector.agent_main(), 1)
            self.assertIn('[agent_main]', stream.getvalue())
            self.assertIn('Traceback', stream.getvalue())
            self.assertIn('agent_error', stream.getvalue())
            self.assertIn('BEGIN GATHERING DATA', output.getvalue())
        finally:
            collector.LOGGER.removeHandler(handler)

    def test_no_such_oid_and_malformed_varbind_do_not_discard_other_values(self):
        warnings = []
        values = collector.parse_walk('.1.2.3.1 = No Such Object available on this agent at this OID\n.1.2.3.2 = INTEGER: broken\n.1.2.3.3 = 0\n.1.2.3.4 = STRING: good', warnings)
        self.assertEqual(values, {'1.2.3.3': 0, '1.2.3.4': 'good'})
        self.assertEqual(len(warnings), 2)


    def test_pci_inventory_requires_explicit_gpu_or_fc_description(self):
        for profile in ('dell-idrac', 'huawei-ibmc'):
            with self.subTest(profile=profile):
                specification = table(profile, 'pciInventory')
                values = bindings(specification, {'1': {'name': 'PCI1', 'description': 'GPU Graphics Accelerator', 'manufacturer': 'Vendor'}, '2': {'name': 'PCI2', 'description': 'Dual Port Fibre Channel HBA'}, '3': {'name': 'PCI3', 'description': 'Unknown PCI Device'}})
                if specification.get('presence'):
                    for index in ('1', '2', '3'):
                        values[specification['root'] + '.' + specification['presence']['column'] + '.' + index] = 2
                result = {}
                collector.collect_private_table(values, specification, result, [], 'fixture-server')
                self.assertEqual(len(result['gpuInfo']), 1)
                self.assertEqual(len(result['hbaInfo']), 1)
                self.assertNotIn('portCount', result['hbaInfo'][0])


    def test_profiles_are_foldable_native_python_literals(self):
        tree = ast.parse(ORIGINAL)
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PROFILES' for target in node.targets))
        self.assertIsInstance(assignment.value, ast.Dict)
        self.assertEqual(ast.literal_eval(assignment.value), collector.PROFILES)


if __name__ == '__main__':
    unittest.main()
