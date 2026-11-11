"""华为存储 SNMP 解析与脱敏样本回放，不连接设备。"""
import importlib.util
import os
import unittest
import zipfile
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'monitor-kits/storage-snmp-monitoring/src/storage_snmp_monitor.py'


def runtime():
    package = os.environ.get('STORAGE_MONITOR_PACKAGE')
    if package:
        with zipfile.ZipFile(package) as archive:
            script = next(name for name in archive.namelist() if name.endswith('/src/storage_snmp_monitor.py') or name == 'src/storage_snmp_monitor.py')
            code = archive.read(script)
            original = archive.read(script[:-3] + '.orig')
            if code != original:
                raise AssertionError('包内py与orig不一致')
        module = types.ModuleType('storage_monitor')
        exec(compile(code, 'storage_snmp_monitor.py', 'exec'), module.__dict__)
        return module
    spec = importlib.util.spec_from_file_location('storage_monitor', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HuaweiTests(unittest.TestCase):
    def test_oid_is_not_coerced_to_number(self):
        module = runtime()
        value = module.parse_value('SNMPv2-MIB::sysObjectID.0 = OID: SNMPv2-SMI::enterprises.2011.2.91')
        self.assertEqual(module.vendor_for(value, ''), 'huawei_oceanstor')
        self.assertEqual(module.parse_value('.1 = OID: .1.3.6.1.4.1.2011.2.91'), '1.3.6.1.4.1.2011.2.91')
        self.assertEqual(module.vendor_for('1.3.6.1.4.1.2011.2.910', ''), 'generic')

    def test_absent_objects_are_missing_not_numbers(self):
        module = runtime()
        for value in ['No Such Object available on this agent at this OID', 'No Such Instance currently exists at this OID', 'No more variables left in this MIB View', 'NULL']:
            self.assertIsNone(module.parse_value('.1 = ' + value))
        self.assertEqual(module.parse_value('.1 = Timeticks: (12345) 0:02:03.45'), 12345)
        self.assertEqual(module.parse_value('.1 = STRING: "6.1.2.SPH63"'), '6.1.2.SPH63')
        self.assertEqual(module.parse_value('.1 = Counter64: 9007199254740993'), 9007199254740993)

    def test_full_compound_index_is_preserved(self):
        module = runtime()
        root = '1.3.6.1.4.1.34774.4.1.23.5.1.1.1'
        lines = ['.' + root + '.2.48.48 = STRING: "00"', '.' + root + '.2.49.48 = STRING: "10"']
        self.assertEqual(module.parse_table(lines, root), {'2.48.48': '00', '2.49.48': '10'})

    def test_sample_replay(self):
        module = runtime()
        sample = Path(os.environ.get('HUAWEI_SNMP_WALK', str(Path(__file__).with_name('fixtures') / 'huawei_storage_walk.txt')))
        lines = sample.read_text().splitlines()
        def response(oid, walk=False):
            if oid == module.BASE['sys_objectid']:
                return ['.1.3.6.1.2.1.1.2.0 = OID: SNMPv2-SMI::enterprises.2011.2.91'], ''
            selected = []
            for line in lines:
                numeric = line.replace('SNMPv2-SMI::enterprises.', '.1.3.6.1.4.1.')
                lhs = numeric.split(' = ', 1)[0].lstrip('.')
                if lhs == oid or (walk and lhs.startswith(oid + '.')):
                    selected.append(numeric)
            return selected or ['.' + oid + ' = No Such Object available on this agent at this OID'], ''
        with patch.object(module, 'run', response), patch.dict(os.environ, {'EASYOPS_COLLECTOR_ip': '192.0.2.10'}):
            records = module.collect()
        self.assertEqual(records[0]['dims']['vendor'], 'huawei_oceanstor')
        self.assertEqual(records[0]['vals']['storage_info_sys_objectid'], '1.3.6.1.4.1.2011.2.91')
        self.assertNotIn('storage_uptime_ticks', records[0]['vals'])
        arrays = [row for row in records if row['dims'].get('resourceType') == 'array']
        values = {key: value for row in arrays for key, value in row['vals'].items()}
        self.assertEqual(values['storage_capacity_bytes'], 114261655 * 1048576)
        self.assertEqual(values['storage_used_bytes'], 56338073 * 1048576)
        self.assertAlmostEqual(values['storage_used_percent'], 56338073 * 100.0 / 114261655)
        self.assertEqual(values['storage_info_version'], '6.1.2.SPH63')
        pools = [row for row in records if row['dims'].get('resourceType') == 'pool' and 'storage_capacity_bytes' in row['vals']]
        self.assertEqual(pools[0]['dims']['resourceIndex'], '1.48')
        self.assertEqual(pools[0]['vals']['storage_capacity_bytes'], values['storage_capacity_bytes'])
        for kind, expected in [('disk', 20), ('controller', 2), ('pool', 1)]:
            found = [row for row in records if row['dims'].get('resourceType') == kind and row['vals'].get('storage_resource_present') == 1]
            self.assertEqual(len(found), expected, kind)
            self.assertEqual(len({row['dims']['resourceIndex'] for row in found}), expected)
        controllers = [row for row in records if row['dims'].get('resourceType') == 'controller']
        self.assertEqual(sorted(row['vals']['storage_controller_cpu_percent'] for row in controllers), [3, 4])
        self.assertEqual(sorted(row['vals']['storage_controller_memory_percent'] for row in controllers), [51, 52])
        import json
        definitions = {row['key']: row for row in json.loads((SOURCE.parents[1] / 'origin_metric.json').read_text())}
        for row in records:
            for key in row['vals']:
                self.assertIn(key, definitions)
                self.assertEqual(set(row['dims']), {dim['name'] for dim in definitions[key]['tagDefine']})
            self.assertTrue(all(value is not None for value in row['vals'].values()))

    def test_both_base_objects_absent_fails(self):
        module = runtime()
        with patch.object(module, 'run', return_value=(['.1 = No Such Object available on this agent at this OID'], '')):
            with self.assertRaises(RuntimeError):
                module.collect()

    def test_other_vendor_root_matching(self):
        module = runtime()
        self.assertEqual(module.vendor_for('1.3.6.1.4.1.789.1', ''), 'netapp')
        self.assertEqual(module.vendor_for('1.3.6.1.4.1.7890.1', ''), 'generic')


if __name__ == '__main__':
    unittest.main()
