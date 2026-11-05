"""物理机 SNMP 模板来源与品牌采集回归，不连接设备。"""
import io
import json
import os
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class BrandCoverageTests(unittest.TestCase):
    def runtime(self):
        default = Path(__file__).resolve().parents[3] / 'hub/monitor-kits/物理服务器SNMP监控套件_0.1.11.zip'
        with zipfile.ZipFile(os.environ.get('MONITOR_PACKAGE', str(default))) as archive:
            code = archive.read('物理服务器SNMP监控/src/物理服务器SNMP监控.py')
        namespace = {'__name__': 'brand_fixture'}
        with patch.dict(os.environ, {'EASYOPS_COLLECTOR_ip': '192.0.2.1'}, clear=True):
            exec(compile(code, 'monitor.py', 'exec'), namespace)
        return namespace

    def collect(self, brand, tables=None, scalars=None):
        runtime = self.runtime()
        responses = tables or {}
        identity = {'sysDescr': 'HP iLO' if brand == 'hp' else brand, 'sysObjectID': '1.3.6.1.4.1.999999'}
        scalar_values = {runtime['OID'][key]: value for key, value in identity.items()}
        scalar_values[runtime['OID']['sysUptime']] = 123
        scalar_values.update(scalars or {})

        class Transport:
            def get(self, requested):
                return scalar_values.get(requested)

            def walk(self, requested):
                return responses.get(requested, {})

        runtime['SNMP'] = Transport
        output = io.StringIO()
        with redirect_stdout(output):
            runtime['main']()
        return json.loads(output.getvalue())

    def test_identification_profiles_are_complete(self):
        runtime = self.runtime()
        for brand in ['huawei', 'dell', 'lenovo', 'inspur', 'ibm', 'hp', 'supermicro', 'h3c']:
            for root in runtime['PROFILES'][brand]['roots']:
                identified = runtime['vendor']({'sysObjectID': root + '.1', 'sysDescr': ''})
                self.assertEqual(identified, brand)
                self.assertIn(identified, runtime['PROFILES'])
        for description, expected in [('IBM IMM', 'ibm'), ('HPE ProLiant', 'hp'), ('Supermicro Aten', 'supermicro'), ('Huanghe iDRAC', 'huanghe'), ('百信', 'baixin')]:
            identified = runtime['vendor']({'sysObjectID': '1.3.6.1.4.1.8072.3.2.10', 'sysDescr': description})
            self.assertEqual(identified, expected)
        self.assertEqual(runtime['vendor']({'sysObjectID': '1.3.6.1.4.1.2320.1'}), 'generic')

    def test_ibm_main_no_keyerror_and_memory_supported(self):
        runtime = self.runtime()
        root = runtime['EXTRA_PROFILES']['ibm']['memory_status']
        records = self.collect('IBM IMM', {root: {root + '.1': 'INTEGER: 1'}})
        self.assertTrue(any('snmp.server.memory.status' in row['vals'] for row in records))
        self.assertFalse(any('snmp.server.cpu.utilization' in row['vals'] for row in records))

    def test_hp_disk_size_preprocessing_matches_zabbix(self):
        runtime = self.runtime()
        root = runtime['EXTRA_PROFILES']['hp']['disk_size']
        records = self.collect('HP iLO', {root: {root + '.1': 'INTEGER: 100'}})
        self.assertIn(100, [row['vals'].get('snmp.server.disk.size') for row in records])

    def test_supermicro_classifies_shared_sensor_table(self):
        root = '1.3.6.1.4.1.21317.1.3.1.2'
        names = '1.3.6.1.4.1.21317.1.3.1.13'
        tables = {
            root: {root + '.1': 'INTEGER: 45', root + '.2': 'INTEGER: 60', root + '.3': 'INTEGER: 12', root + '.4': 'INTEGER: 0'},
            names: {names + '.1': 'STRING: "CPU1 Temp"', names + '.2': 'STRING: "FAN1"', names + '.3': 'STRING: "Voltage"', names + '.4': 'STRING: "CPU2 Temp"'},
        }
        records = self.collect('Supermicro Aten', tables)
        temperatures = [row['vals']['snmp.server.temperature.value'] for row in records if 'snmp.server.temperature.value' in row['vals']]
        fans = [row['vals']['snmp.server.fan.utilization'] for row in records if 'snmp.server.fan.utilization' in row['vals']]
        self.assertEqual(temperatures, [45.0])
        self.assertEqual(fans, [60.0])
        self.assertFalse(any('snmp.server.fan.status' in row['vals'] for row in records))

    def test_text_oid_and_percent_are_preserved(self):
        runtime = self.runtime()
        self.assertEqual(runtime['value']('OID: 1.3.6.1.4.1.232.1'), '1.3.6.1.4.1.232.1')
        self.assertEqual(runtime['value']('STRING: "CPU1 Temp: Inlet"'), 'CPU1 Temp: Inlet')
        self.assertEqual(runtime['numeric']('STRING: "45% of maximum"'), 45.0)

    def test_entity_temperature_scale_precision_and_type(self):
        runtime = self.runtime()
        definitions = [('sensorValue', ['450', '12']), ('sensorType', ['8', '4']), ('sensorScale', ['9', '9']), ('sensorPrecision', ['1', '0']), ('sensorStatus', ['1', '1'])]
        tables = {}
        for key, values in definitions:
            root = runtime['OID'][key]
            tables[root] = {root + '.' + str(index): 'INTEGER: ' + value for index, value in enumerate(values, 1)}
        records = self.collect('generic', tables)
        self.assertEqual([row['vals']['snmp.server.temperature.value'] for row in records if 'snmp.server.temperature.value' in row['vals']], [45])

    def test_cpu_storage_standard_mibs(self):
        runtime = self.runtime()
        fixtures = [('cpuLoad', ['10', '20', '30']), ('hrType', ['OID: 1.3.6.1.2.1.25.2.1.2', 'OID: 1.3.6.1.2.1.25.2.1.4', 'OID: 1.3.6.1.2.1.25.2.1.3']), ('hrSize', ['100', '1000', '100']), ('hrUsed', ['25', '250', '90'])]
        tables = {}
        for key, values in fixtures:
            root = runtime['OID'][key]
            tables[root] = {root + '.' + str(index): value for index, value in enumerate(values, 1)}
        records = self.collect('IBM IMM', tables)
        for kind, expected in [('cpu', [20.0]), ('memory', [25.0]), ('disk', [25.0])]:
            key = 'snmp.server.' + kind + '.utilization'
            self.assertEqual([row['vals'][key] for row in records if key in row['vals']], expected)

    def test_brand_temperature_multipliers(self):
        runtime = self.runtime()
        for brand, expected in [('dell', 45), ('huawei', 45), ('ibm', 450), ('hp', 450), ('huanghe', 45)]:
            root = runtime['EXTRA_PROFILES'][brand]['temperature']
            records = self.collect(brand, {root: {root + '.1': 'INTEGER: 450'}})
            temperatures = [row['vals']['snmp.server.temperature.value'] for row in records if 'snmp.server.temperature.value' in row['vals']]
            self.assertEqual(temperatures, [expected])


if __name__ == '__main__':
    unittest.main()
