"""VMWare扫描身份及关联离线回归，不连接设备或平台。"""
import ast
import logging
import socket
import unittest
from pathlib import Path
from types import SimpleNamespace as N


SOURCE = Path(__file__).parents[2] / 'cmdb-kits/vmware-scan/src/VMWare_Scan.py'
tree = ast.parse(SOURCE.read_text())
nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
namespace = {'socket': socket, 'logger': logging.getLogger('vmware-test'),
             'vim': N(HostSystem=object), 'SERVER_OBJECT_ID': 'PHYSICAL_SERVER@ONEMODEL',
             'CLOUD_PROVIDER_OBJECT_ID': 'CLOUD_PROVIDER@ONEMODEL'}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)


def host(identity='host-1', ips=('10.0.0.1',), selected=None, serials=()):
    vnics = [N(key='key-vmk%d' % i, device='vmk%d' % i,
               spec=N(ip=N(ipAddress=ip))) for i, ip in enumerate(ips)]
    net = [] if selected is None else [N(nicType='management', selectedVnic=selected)]
    info = [N(identifierType=N(key=k), identifierValue=v) for k, v in serials]
    return N(_moId=identity, config=N(network=N(vnic=vnics),
             virtualNicManagerInfo=N(netConfig=net)),
             hardware=N(systemInfo=N(otherIdentifyingInfo=info)))


def collector(hosts):
    c = namespace['EasyVcenter'].__new__(namespace['EasyVcenter'])
    c.result, c.resource_name, c.provider_instance_id = [], 'vc-uuid', 'provider-1'
    c._get_all_objs = lambda types: hosts
    return c


class IdentityTests(unittest.TestCase):
    def test_management_selected_over_first_vnic(self):
        h = host(ips=('10.1.0.1', '10.2.0.1'), selected=['key-vmk1'])
        self.assertEqual(namespace['management_ip'](h), '10.2.0.1')

    def test_device_selection(self):
        self.assertEqual(namespace['management_ip'](host(selected=['vmk0'])), '10.0.0.1')

    def test_single_ip_fallback(self):
        self.assertEqual(namespace['management_ip'](host()), '10.0.0.1')

    def test_multiple_ip_without_management_is_skipped(self):
        self.assertEqual(namespace['management_ip'](host(ips=('10.0.0.1', '10.0.0.2'))), '')

    def test_management_empty_does_not_use_storage_ip(self):
        self.assertEqual(namespace['management_ip'](host(selected=[])), '')

    def test_management_multiple_ips_is_skipped(self):
        h = host(ips=('10.0.0.1', '10.0.0.2'), selected=['vmk0', 'vmk1'])
        self.assertEqual(namespace['management_ip'](h), '')

    def test_invalid_ips(self):
        for value in ('', 'none', '0.0.0.0', '127.0.0.1', '169.254.1.1',
                      '224.1.1.1', '::', '::1', 'fe80::1', 'ff02::1', '999.1.1.1'):
            with self.subTest(value=value):
                self.assertEqual(namespace['valid_host_ip'](value), '')

    def test_ipv6_normalization(self):
        self.assertEqual(namespace['valid_host_ip']('2001:db8:0:0::1'), '2001:db8::1')

    def test_serial_falls_through_placeholder(self):
        h = host(serials=(('ServiceTag', 'none'), ('SerialNumberTag', 'SN-123')))
        self.assertEqual(namespace['hardware_serial'](h), 'SN-123')

    def test_placeholder_serials(self):
        for value in ('Chassis Serial Number', 'none', ' NONE ', '', 'Default String'):
            self.assertEqual(namespace['hardware_serial'](host(serials=(('SerialNumberTag', value),))), '')

    def test_no_serial_does_not_skip_physical_host(self):
        c = collector([host()])
        c.get_physical_server_list()
        row = c.result[0]
        self.assertEqual(row['dims']['pks'], ['businessIp'])
        self.assertIs(row['dims']['upsert'], False)
        self.assertNotIn('sn', row['vals'])
        self.assertEqual(row['vals']['resourceInstanceId'], 'vc-uuid_host-1')
        self.assertEqual(c.result[1]['vals']['physicalServers'], [{'businessIp': '10.0.0.1'}])

    def test_duplicate_hosts_both_excluded(self):
        c = collector([host('host-1'), host('host-2')])
        c.get_physical_server_list()
        self.assertEqual(c.result, [])
        self.assertEqual(c._physical_relation('host-1'), [])

    def test_missing_ip_does_not_clear_provider_relations(self):
        c = collector([host(ips=())])
        c.get_physical_server_list()
        self.assertEqual(c.result, [])

    def test_relations_use_same_key(self):
        c = collector([host()])
        self.assertEqual(c._physical_relation('host-1'), [{'businessIp': '10.0.0.1'}])
        self.assertEqual(c._physical_relation('absent'), [])

    def test_log_sample_eight_distinct_ips(self):
        ips = ['11.66.17.207', '11.66.26.66', '11.66.17.204', '11.66.26.65',
               '11.66.17.206', '11.66.17.205', '11.66.17.202', '11.66.17.203']
        hosts = [host('host-%d' % i, (ip,), serials=(('SerialNumberTag',
                 'J30011D0' if i == 6 else 'none' if i == 7 else 'Chassis Serial Number'),))
                 for i, ip in enumerate(ips)]
        c = collector(hosts)
        c.get_physical_server_list()
        self.assertEqual(len(c.result), 9)
        self.assertEqual(len({r['vals']['businessIp'] for r in c.result[:8]}), 8)
        self.assertEqual(sum('sn' in r['vals'] for r in c.result[:8]), 1)


if __name__ == '__main__':
    unittest.main()
