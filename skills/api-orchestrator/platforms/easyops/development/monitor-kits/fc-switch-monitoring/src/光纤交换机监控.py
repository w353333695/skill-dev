#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""光纤交换机SNMP监控采集脚本

支持品牌自动探测和采集：
- Brocade/博科（SW-MIB）
- Cisco MDS（CISCO-FC-FE-MIB）
- 华为SNS（华为私有OID / Brocade OEM）
- 其他品牌回退 FCMGMT-MIB
"""
import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import traceback
from collections import namedtuple, OrderedDict

try:
    text_type = unicode
    string_types = (basestring,)
except NameError:
    text_type = str
    string_types = (str, bytes)

LOGGER = logging.getLogger("fc_snmp_monitor")
VERSION = "1.0.17"


def to_text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def env_text(name, default=""):
    value = to_text(os.environ.get("EASYOPS_COLLECTOR_" + name, "")).strip()
    return default if value.lower() in ("", "null", "none", "undefined", "<nil>") else value


def redact(value, secrets=()):
    text = to_text(value)
    values = list(secrets)
    for name in ("community", "username", "auth_key", "priv_key"):
        values.append(env_text(name))
    for secret in sorted(set(to_text(item) for item in values if item), key=len, reverse=True):
        text = text.replace(secret, "******")
    return text


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(logging.Formatter.format(self, record))


def setup_logging():
    level = env_text("logLevel", os.environ.get("EASYOPS_LOG_LEVEL", "ERROR")).upper()
    LOGGER.setLevel(getattr(logging, level, logging.ERROR))
    LOGGER.propagate = False
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(SafeFormatter("%(levelname)s %(message)s"))
        LOGGER.addHandler(handler)


def load_config():
    address = env_text("ip")
    if not address or address.startswith("$."):
        raise ValueError("[load_config] 缺少有效的设备IP，请检查 $.ip 映射")
    port_text = env_text("port", "161")
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ValueError("[load_config] SNMP端口必须是1到65535的整数")
    config = dict(ip=address, port=int(port_text), version=env_text("version", "2c"),
                  community=env_text("community"), username=env_text("username"),
                  auth_key=env_text("auth_key"), auth_protocol=env_text("auth_protocol", "MD5"),
                  priv_key=env_text("priv_key"), priv_protocol=env_text("priv_protocol", "DES"),
                  context_name=env_text("context_name"), security_level=env_text("security_level"))
    if config["version"] == "2":
        config["version"] = "2c"
    if config["version"] not in ("1", "2c", "3"):
        raise ValueError("[load_config] SNMP版本必须是1、2c或3")
    if config["version"] in ("1", "2c") and (not config["community"] or config["community"].startswith("$.")):
        raise ValueError("[load_config] SNMP v1/v2c缺少团体名，请检查CMDB认证字段")
    if config["version"] == "3":
        if not config["username"] or config["username"].startswith("$."):
            raise ValueError("[load_config] SNMPv3缺少安全名")
        if config["priv_key"] and not config["auth_key"]:
            raise ValueError("[load_config] SNMPv3隐私认证要求同时配置认证密钥")
        level = config["security_level"] or ("authPriv" if config["priv_key"] else "authNoPriv" if config["auth_key"] else "noAuthNoPriv")
        if level not in ("noAuthNoPriv", "authNoPriv", "authPriv"):
            raise ValueError("[load_config] SNMPv3安全级别不合法")
        if level in ("authNoPriv", "authPriv") and not config["auth_key"]:
            raise ValueError("[load_config] SNMPv3缺少认证密钥")
        if level == "authPriv" and not config["priv_key"]:
            raise ValueError("[load_config] SNMPv3缺少隐私密钥")
        config["security_level"] = level
    return config


def missing_value(value):
    text = to_text(value).strip().lower()
    return not text or text in ("null", "none") or any(marker in text for marker in (
        "no such", "nosuchobject", "nosuchinstance", "nosuchname", "end of mib", "no more variables"))


def _safe_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(to_text(value).strip().strip('"').strip("'"))
        return None if math.isnan(number) or math.isinf(number) else number
    except (ValueError, TypeError, OverflowError):
        return None


def safe_int(value):
    number = _safe_float(value)
    if number is None or number != int(number):
        LOGGER.warning("[safe_int] 跳过非整数指标值")
        return None
    return int(number)


def set_metric(values, name, value, divisor=1.0):
    number = _safe_float(value)
    if number is None:
        LOGGER.warning("[set_metric] 跳过不可用指标 %s", name)
        return
    values[name] = number / divisor


Result = namedtuple('Result', ['success', 'data', 'error'])


def parse_snmp_value(value_str):
    """解析SNMP返回值，自动转换数据类型"""
    value_str = value_str.strip()
    if ':' in value_str:
        parts = value_str.split(':', 1)
        if len(parts) == 2:
            type_part = parts[0].strip().upper()
            value_part = parts[1].strip()
            if type_part in ['INTEGER', 'COUNTER32', 'COUNTER64', 'GAUGE32',
                             'TIMETICKS', 'IPADDRESS', 'COUNTER', 'GAUGE']:
                # Timeticks 形如 "(3905183420) 451 days, 23:43:54.20"，
                # 括号内为厘秒值（1/100 秒），需提取为整数，否则 int() 会失败
                if type_part == 'TIMETICKS' and '(' in value_part and ')' in value_part:
                    inside = value_part.split('(', 1)[1].split(')', 1)[0]
                    try:
                        return int(inside)
                    except ValueError:
                        pass
                try:
                    return int(value_part)
                except ValueError:
                    enum_value = re.search(r"\((-?\d+)\)$", value_part)
                    return int(enum_value.group(1)) if enum_value else value_part
            if type_part in ['STRING', 'OCTETSTR', 'OPAQUE', 'OBJECT IDENTIFIER', 'OID']:
                return value_part.strip('"')
            try:
                return int(value_part)
            except ValueError:
                try:
                    return float(value_part)
                except ValueError:
                    return value_part.strip('"')
    try:
        return int(value_str)
    except ValueError:
        try:
            return float(value_str)
        except ValueError:
            return value_str




class SNMPClient(object):
    """同一认证配置用于前置检查和正式采集，每条命令均设进程期限。"""

    def __init__(self, ip, port=161, version='2c', community='',
                 username=None, auth_key=None, auth_protocol='MD5',
                 priv_key=None, priv_protocol='DES', timeout=10, retries=0,
                 context_name='', security_level=''):
        self.ip = ip
        self.port = int(port)
        self.version = version
        self.community = community
        self.username = username
        self.auth_key = auth_key
        self.auth_protocol = auth_protocol.upper() if auth_protocol else 'MD5'
        self.priv_key = priv_key
        self.priv_protocol = priv_protocol.upper() if priv_protocol else 'DES'
        self.timeout = timeout
        self.retries = retries
        self.context_name = context_name
        self.security_level = security_level

    def _build_auth_params(self):
        params = ['-t', to_text(self.timeout), '-r', to_text(self.retries)]
        if self.version in ('1', '2c'):
            return params + ['-v', self.version, '-c', self.community]
        level = self.security_level or ('authPriv' if self.priv_key else 'authNoPriv' if self.auth_key else 'noAuthNoPriv')
        params.extend(['-v', '3', '-u', self.username, '-l', level])
        if level in ('authNoPriv', 'authPriv'):
            params.extend(['-a', self.auth_protocol, '-A', self.auth_key])
        if level == 'authPriv':
            params.extend(['-x', self.priv_protocol, '-X', self.priv_key])
        if self.context_name:
            params.extend(['-n', self.context_name])
        return params

    def _execute(self, command, budget=None):
        process = None
        timer = None
        expired = threading.Event()
        secrets = (self.community, self.username, self.auth_key, self.priv_key)

        def stop_process():
            if process.poll() is None:
                expired.set()
                try:
                    process.kill()
                except OSError:
                    LOGGER.debug("[SNMPClient.stop_process] %s", redact(traceback.format_exc(), secrets))

        try:
            args = [to_text(value) for value in command]
            if sys.version_info[0] < 3:
                args = [value.encode('utf-8') for value in args]
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            timer = threading.Timer(self.timeout if budget is None else budget, stop_process)
            timer.daemon = True
            timer.start()
            stdout, stderr = process.communicate()
            if expired.is_set():
                return Result(False, '', 'SNMP command timeout')
            output = to_text(stdout).strip()
            error = to_text(stderr).strip()
            error = '\n'.join(line for line in error.splitlines() if 'gmon.out' not in line and '_mcleanup' not in line)
            LOGGER.debug("[SNMPClient._execute] oid=%s output=%s", args[-1], redact(output, secrets))
            return Result(process.returncode == 0, output, redact(error, secrets))
        except Exception:
            return Result(False, '', '[SNMPClient._execute] ' + redact(traceback.format_exc(), secrets))
        finally:
            if timer is not None:
                timer.cancel()
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    process.communicate()
                except OSError:
                    LOGGER.debug("[SNMPClient._execute.cleanup] %s", redact(traceback.format_exc(), secrets))

    def _target(self):
        host = to_text(self.ip)
        if ':' in host and not host.startswith('['):
            host = '[' + host + ']'
        return '%s:%s' % (host, self.port)

    def get(self, oid):
        command = ['snmpget', '-On'] + self._build_auth_params() + [self._target(), oid]
        result = self._execute(command)
        if result.success:
            for line in to_text(result.data).splitlines():
                if '=' in line:
                    value = line.split('=', 1)[1].strip()
                    if not missing_value(value):
                        return Result(True, parse_snmp_value(value), '')
            return Result(False, None, 'SNMP基础OID无有效数据')
        LOGGER.warning('[SNMPClient.get] oid=%s error=%s', oid, result.error)
        return Result(False, None, result.error or 'SNMP请求失败')

    def walk(self, oid):
        command = ['snmpwalk', '-On'] + self._build_auth_params() + [self._target(), oid]
        result = self._execute(command)
        data = OrderedDict()
        base = oid.lstrip('.')
        if not result.success:
            LOGGER.warning("[SNMPClient.walk] oid=%s error=%s", oid, result.error)
            return data
        for line in to_text(result.data).splitlines():
            if '=' not in line:
                continue
            oid_part, value_part = line.split('=', 1)
            oid_part = oid_part.strip().lstrip('.')
            value_part = value_part.strip()
            if missing_value(value_part) or not oid_part.startswith(base + '.'):
                continue
            suffix = oid_part[len(base) + 1:]
            if suffix:
                data[suffix] = parse_snmp_value(value_part)
        return data


# ============================================================================
# 品牌探测
# ============================================================================
VENDOR_BROCADE = 'brocade'
VENDOR_CISCO = 'cisco'
VENDOR_HUAWEI = 'huawei'
VENDOR_FCMGMT = 'fcmgmt'

# 企业OID前缀
ENTERPRISE_BROCADE = '1.3.6.1.4.1.1588'
ENTERPRISE_CISCO = '1.3.6.1.4.1.9'
ENTERPRISE_HUAWEI = '1.3.6.1.4.1.2011'


def detect_vendor(snmp_client):
    """品牌探测：通过 sysObjectID 判断厂商

    :param snmp_client: SNMPClient 实例
    :return: 厂商标识字符串
    """
    result = snmp_client.get('1.3.6.1.2.1.1.2.0')
    if not result.success or result.data is None:
        return VENDOR_FCMGMT

    sys_obj_id = to_text(result.data)
    # 去除 OID 类型前缀（如 OID: ）
    if sys_obj_id.startswith('OID: '):
        sys_obj_id = sys_obj_id[5:]
    sys_obj_id = sys_obj_id.strip('.')

    if sys_obj_id == ENTERPRISE_BROCADE or sys_obj_id.startswith(ENTERPRISE_BROCADE + "."):
        return VENDOR_BROCADE
    elif sys_obj_id == ENTERPRISE_CISCO or sys_obj_id.startswith(ENTERPRISE_CISCO + "."):
        return VENDOR_CISCO
    elif sys_obj_id == ENTERPRISE_HUAWEI or sys_obj_id.startswith(ENTERPRISE_HUAWEI + "."):
        # 华为可能是OEM Brocade，尝试walk Brocade树
        test_result = snmp_client.get('1.3.6.1.4.1.1588.2.1.1.1.26.1.0')
        if test_result.success and test_result.data is not None:
            return VENDOR_BROCADE  # 华为OEM，使用Brocade OID
        return VENDOR_HUAWEI
    else:
        return VENDOR_FCMGMT


# ============================================================================
# Brocade 采集器 (SW-MIB)
# ============================================================================
class BrocadeMonitor(object):
    """Brocade/博科光纤交换机采集器"""

    # Brocade SW-MIB OID 定义
    OID = {
        # 设备基础
        'cpu_usage': '1.3.6.1.4.1.1588.2.1.1.1.26.1.0',
        'mem_usage': '1.3.6.1.4.1.1588.2.1.1.1.26.6.0',
        'sys_uptime': '1.3.6.1.2.1.1.3.0',
        'oper_status': '1.3.6.1.4.1.1588.2.1.1.1.1.7.0',
        'domain_id': '1.3.6.1.4.1.1588.2.1.1.1.2.1.0',
        # FC端口表 (swFCPortTable) — 列索引由 _detect_fos_variant 动态设置
        'port_table': '1.3.6.1.4.1.1588.2.1.1.1.6.2.1',
        'port_name': 1,          # swFCPortIndex（swFCPortName 在 11，部分 FOS 不实现）
        'port_oper_status': 4,   # swFCPortOpStatus
        'port_phy_state': 3,     # swFCPortTxType
        'port_link_state': 6,    # swFCPortLinkState
        'port_no_tx_credits': 20,# swFCPortNoTxCredits
        # 以下列索引为默认值，_detect_fos_variant 会根据 FOS 版本自动调整
        'port_speed': 35,        # swFCPortSpeed（探测后设置）
        'port_login_count': 28,  # swFCPortNxPorts（探测后设置）
        'port_tx_words': 13,     # swFCPortTxWords（探测后设置）
        'port_rx_words': 14,     # swFCPortRxWords（探测后设置）
        'port_tx_frames': 15,    # swFCPortTxFrames（探测后设置）
        'port_rx_frames': 16,    # swFCPortRxFrames（探测后设置）
        'port_c3_discards': 19,  # swFCPortC3Discards（探测后设置）
        # 错误
        'port_crc_errors': 22,       # swFCPortRxCrcs
        'port_enc_in_errors': 21,    # swFCPortRxEncInFrs
        'port_enc_out_errors': 26,   # swFCPortRxEncOutFrs
        'port_trunc_frames': 23,     # swFCPortRxTruncs
        'port_too_long_frames': 24,  # swFCPortRxTooLongs
        'port_bad_eof': 25,          # swFCPortRxBadEofs
        # 传感器表
        'sensor_table': '1.3.6.1.4.1.1588.2.1.1.1.1.22.1',
        'sensor_type': 1,    # swSensorType (1=温度,2=风扇,3=电源)
        'sensor_status': 2,  # swSensorStatus
        'sensor_value': 3,   # swSensorInfo
        # SFP表
        'sfp_table': '1.3.6.1.4.1.1588.2.1.1.1.28.1.1',
        'sfp_temperature': 1, # swSfpTemperature
        'sfp_voltage': 2,     # swSfpVoltage
        'sfp_rx_power': 4,    # swSfpRxPower
        'sfp_tx_power': 5,    # swSfpTxPower
    }

    # 端口运行状态映射
    PORT_STATUS_MAP = {
        0: 0,  # unknown -> 0
        1: 1,  # online -> 1
        2: 0,  # offline -> 0
        3: 2,  # testing -> 2
        4: 3,  # faulty -> 3
    }

    def __init__(self, snmp_client):
        self.snmp = snmp_client
        self.OID = self.OID.copy()
        self._detect_fos_variant()

    def _detect_fos_variant(self):
        """探测 FOS 版本，自动适配 swFCPortTable 列索引

        FOS 6.x 布局:  TxWords=11, RxWords=12, TxFrames=13, RxFrames=14,
                       C3Discards=28, NxPorts=19, Speed=35
        FOS 7.x+ 布局: TxWords=13, RxWords=14, TxFrames=15, RxFrames=16,
                       C3Discards=19, NxPorts=28, Speed=12

        探测策略: 读取 col 11，如果返回值是数字 → FOS 6.x（TxWords 是 Counter32），
        如果不存在或返回值是字符串 → FOS 7.x+（col 11 是 swFCPortName）。
        """
        base = self.OID['port_table']
        # 探测 col 11：FOS 6.x → swFCPortTxWords (Counter32/数字)
        #           FOS 7.x+ → swFCPortName (DisplayString/字符串或无数据)
        test = self.snmp.walk(base + '.11')
        fos_6x = False
        if len(test) > 0:
            first_val = next(iter(test.values()))
            # Python 2: basestring 覆盖 str 和 unicode
            if isinstance(first_val, string_types):
                fos_6x = False  # 字符串 → port name → FOS 7.x+
            else:
                fos_6x = True   # 数字 → TxWords → FOS 6.x

        if fos_6x:
            self.OID.update({
                'port_tx_words': 11, 'port_rx_words': 12,
                'port_tx_frames': 13, 'port_rx_frames': 14,
                'port_c3_discards': 28, 'port_login_count': 19,
            })
        # 否则保持默认（FOS 7.x+ 布局）

        # 探测 port_speed：FOS 7.x+ 在 12，FOS 6.x 在 35
        for col in (12, 35):
            s = self.snmp.walk(base + '.' + to_text(col))
            if len(s) > 0:
                self.OID['port_speed'] = col
                break

    def collect_system(self, ip_addr):
        """采集设备基础指标"""
        vals = {}
        result = self.snmp.get(self.OID['cpu_usage'])
        if result.success and result.data is not None:
            set_metric(vals, 'm_cpu_usage', result.data)

        result = self.snmp.get(self.OID['mem_usage'])
        if result.success and result.data is not None:
            set_metric(vals, 'm_mem_usage', result.data)

        result = self.snmp.get(self.OID['sys_uptime'])
        if result.success and result.data is not None:
            # sysUpTime 单位为厘秒，转换为秒；解析异常时跳过避免中断整个采集
            try:
                set_metric(vals, 'm_sys_uptime', result.data, divisor=100.0)
            except (TypeError, ValueError):
                pass

        result = self.snmp.get(self.OID['oper_status'])
        if result.success and result.data is not None:
            status = safe_int(result.data)
            if status is not None:
                vals['m_oper_status'] = 1.0 if status == 1 else 0.0

        result = self.snmp.get(self.OID['domain_id'])
        if result.success and result.data is not None:
            set_metric(vals, 'm_domain_id', result.data)

        if not vals:
            return []
        return [{"dims": {"ip": ip_addr}, "vals": vals}]

    def _walk_port_column(self, col_index):
        """Walk 端口表的某一列"""
        base_oid = self.OID['port_table'] + '.' + to_text(col_index)
        return self.snmp.walk(base_oid)

    def collect_port_status(self, ip_addr):
        """采集FC端口状态指标"""
        names = self._walk_port_column(self.OID['port_name'])
        oper_statuses = self._walk_port_column(self.OID['port_oper_status'])
        phy_states = self._walk_port_column(self.OID['port_phy_state'])
        link_states = self._walk_port_column(self.OID['port_link_state'])
        speeds = self._walk_port_column(self.OID['port_speed'])
        logins = self._walk_port_column(self.OID['port_login_count'])

        results = []
        for idx in names:
            port_name = to_text(names.get(idx, idx))
            port_name = port_name.strip('"').strip()
            if not port_name:
                port_name = "Port_" + idx

            vals = {}
            if idx in oper_statuses:
                raw_status = safe_int(oper_statuses[idx])
                if raw_status is not None:
                    set_metric(vals, 'm_port_oper_status', self.PORT_STATUS_MAP.get(raw_status, 0))
            if idx in phy_states:
                set_metric(vals, 'm_port_phy_state', phy_states[idx])
            if idx in link_states:
                set_metric(vals, 'm_port_link_state', link_states[idx])
            if idx in speeds:
                set_metric(vals, 'm_port_speed', speeds[idx])
            if idx in logins:
                set_metric(vals, 'm_port_login_count', logins[idx])

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": port_name},
                    "vals": vals
                })
        return results

    def collect_port_traffic(self, ip_addr):
        """采集FC端口流量指标"""
        names = self._walk_port_column(self.OID['port_name'])
        tx_words = self._walk_port_column(self.OID['port_tx_words'])
        rx_words = self._walk_port_column(self.OID['port_rx_words'])
        tx_frames = self._walk_port_column(self.OID['port_tx_frames'])
        rx_frames = self._walk_port_column(self.OID['port_rx_frames'])
        c3_discards = self._walk_port_column(self.OID['port_c3_discards'])
        no_tx_credits = self._walk_port_column(self.OID['port_no_tx_credits'])

        results = []
        for idx in names:
            port_name = to_text(names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in tx_words:
                set_metric(vals, 'm_port_tx_words', tx_words[idx])
            if idx in rx_words:
                set_metric(vals, 'm_port_rx_words', rx_words[idx])
            if idx in tx_frames:
                set_metric(vals, 'm_port_tx_frames', tx_frames[idx])
            if idx in rx_frames:
                set_metric(vals, 'm_port_rx_frames', rx_frames[idx])
            if idx in c3_discards:
                set_metric(vals, 'm_port_c3_discards', c3_discards[idx])
            if idx in no_tx_credits:
                set_metric(vals, 'm_port_no_tx_credits', no_tx_credits[idx])

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": port_name},
                    "vals": vals
                })
        return results

    def collect_port_errors(self, ip_addr):
        """采集FC端口错误指标"""
        names = self._walk_port_column(self.OID['port_name'])
        crc_errors = self._walk_port_column(self.OID['port_crc_errors'])
        enc_in_errors = self._walk_port_column(self.OID['port_enc_in_errors'])
        enc_out_errors = self._walk_port_column(self.OID['port_enc_out_errors'])
        trunc_frames = self._walk_port_column(self.OID['port_trunc_frames'])
        too_long_frames = self._walk_port_column(self.OID['port_too_long_frames'])
        bad_eof = self._walk_port_column(self.OID['port_bad_eof'])

        results = []
        for idx in names:
            port_name = to_text(names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in crc_errors:
                set_metric(vals, 'm_port_crc_errors', crc_errors[idx])
            if idx in enc_in_errors:
                set_metric(vals, 'm_port_enc_in_errors', enc_in_errors[idx])
            if idx in enc_out_errors:
                set_metric(vals, 'm_port_enc_out_errors', enc_out_errors[idx])
            if idx in trunc_frames:
                set_metric(vals, 'm_port_trunc_frames', trunc_frames[idx])
            if idx in too_long_frames:
                set_metric(vals, 'm_port_too_long_frames', too_long_frames[idx])
            if idx in bad_eof:
                set_metric(vals, 'm_port_bad_eof', bad_eof[idx])

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": port_name},
                    "vals": vals
                })
        return results

    def collect_sensors(self, ip_addr):
        """采集传感器指标（温度/风扇/电源）"""
        sensor_types = self.snmp.walk(self.OID['sensor_table'] + '.' + to_text(self.OID['sensor_type']))
        sensor_statuses = self.snmp.walk(self.OID['sensor_table'] + '.' + to_text(self.OID['sensor_status']))
        sensor_values = self.snmp.walk(self.OID['sensor_table'] + '.' + to_text(self.OID['sensor_value']))

        type_labels = {1: 'Temp', 2: 'Fan', 3: 'PS'}

        results = []
        for idx in sensor_types:
            s_type = safe_int(sensor_types[idx])
            if s_type is None:
                continue
            label = type_labels.get(s_type, 'Sensor')
            sensor_name = "{0}_{1}".format(label, idx)

            vals = {}
            if idx in sensor_values:
                v = _safe_float(sensor_values[idx])
                if v is not None:
                    vals['m_sensor_value'] = v
            if idx in sensor_statuses:
                v = _safe_float(sensor_statuses[idx])
                if v is not None:
                    vals['m_sensor_status'] = v

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "sensor_name": sensor_name},
                    "vals": vals
                })
        return results

    def collect_sfp(self, ip_addr):
        """采集SFP光模块指标

        Brocade设备在端口未插光模块时返回字符串 "NA"，需跳过这些无效值。
        """
        sfp_temps = self.snmp.walk(self.OID['sfp_table'] + '.' + to_text(self.OID['sfp_temperature']))
        sfp_voltages = self.snmp.walk(self.OID['sfp_table'] + '.' + to_text(self.OID['sfp_voltage']))
        sfp_rx_powers = self.snmp.walk(self.OID['sfp_table'] + '.' + to_text(self.OID['sfp_rx_power']))
        sfp_tx_powers = self.snmp.walk(self.OID['sfp_table'] + '.' + to_text(self.OID['sfp_tx_power']))

        # 获取端口名映射
        names = self._walk_port_column(self.OID['port_name'])

        results = []
        for idx in sfp_temps:
            # SFP 索引格式为 <WWN(16字节)>.<portIndex>，取末段端口号匹配端口名
            port_idx = idx.rsplit('.', 1)[-1] if '.' in idx else idx
            port_name = to_text(names.get(port_idx, port_idx)).strip('"').strip() or "SFP_" + to_text(port_idx)
            vals = {}
            if idx in sfp_temps:
                v = _safe_float(sfp_temps[idx])
                if v is not None:
                    vals['m_sfp_temperature'] = v
            if idx in sfp_voltages:
                v = _safe_float(sfp_voltages[idx])
                if v is not None:
                    vals['m_sfp_voltage'] = v
            if idx in sfp_rx_powers:
                v = _safe_float(sfp_rx_powers[idx])
                if v is not None:
                    vals['m_sfp_rx_power'] = v
            if idx in sfp_tx_powers:
                v = _safe_float(sfp_tx_powers[idx])
                if v is not None:
                    vals['m_sfp_tx_power'] = v

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": port_name},
                    "vals": vals
                })
        return results


# ============================================================================
# Cisco MDS 采集器 (CISCO-FC-FE-MIB)
# ============================================================================
class CiscoMDSMonitor(object):
    """Cisco MDS 光纤交换机采集器"""

    OID = {
        # 设备基础
        'cpu_usage': '1.3.6.1.4.1.9.9.109.1.1.1.1.8',  # cpmCPUTotal5minRev（表，取第一个）
        'mem_pool_used': '1.3.6.1.4.1.9.9.221.1.1.1.1.18',  # ciscoMemoryPoolUsed
        'mem_pool_free': '1.3.6.1.4.1.9.9.221.1.1.1.1.20',  # ciscoMemoryPoolFree
        'sys_uptime': '1.3.6.1.2.1.1.3.0',
        'oper_status': '1.3.6.1.3.94.1.6.1.5',  # connUnitStatus（表）
        # FC端口 - 通过 ifTable + fcIfTable
        'if_table': '1.3.6.1.2.1.2.2.1',
        'if_desc': 2,           # ifDescr
        'if_oper_status': 8,    # ifOperStatus
        'if_speed': 5,          # ifSpeed
        # fcIfTable (CISCO-FC-FE-MIB)
        'fc_if_table': '1.3.6.1.4.1.9.9.289.1.1.2',
        'fc_if_wwn': '1.3.6.1.4.1.9.9.289.1.1.2.1.3',  # fcIfWwn
        'fc_if_port_mode': '1.3.6.1.4.1.9.9.289.1.1.2.1.5', # fcIfPortMode
        # FC 流量
        'fc_if_c3_in_octets': '1.3.6.1.4.1.9.9.289.1.2.3.1.1',  # fcIfC3InOctets
        'fc_if_c3_out_octets': '1.3.6.1.4.1.9.9.289.1.2.3.1.2', # fcIfC3OutOctets
        'fc_if_c3_discards': '1.3.6.1.4.1.9.9.289.1.2.3.1.5',   # fcIfC3Discards
        # FC 错误
        'fc_if_invalid_crcs': '1.3.6.1.4.1.9.9.289.1.2.1.1.6',   # fcIfInvalidCrcs
        'fc_if_link_failures': '1.3.6.1.4.1.9.9.289.1.2.1.1.1',  # fcIfLinkFailures
        'fc_if_sync_losses': '1.3.6.1.4.1.9.9.289.1.2.1.1.2',    # fcIfSyncLosses
        'fc_if_sig_losses': '1.3.6.1.4.1.9.9.289.1.2.1.1.3',     # fcIfSigLosses
        'fc_if_credit_loss': '1.3.6.1.4.1.9.9.289.1.2.1.1.37',   # fcIfCreditLoss
        'fc_if_fec_uncorrected': '1.3.6.1.4.1.9.9.289.1.2.1.1.43', # fcIfFECUncorrectedBlks
        # 传感器 - ENTITY-SENSOR-MIB
        'ent_phynum_table': '1.3.6.1.2.1.47.1.1.1.1',  # entPhysicalTable
        'ent_phy_name': 7,       # entPhysicalName
        'ent_phy_class': 5,      # entPhysicalClass
        'ent_sensor_value': '1.3.6.1.2.1.99.1.1.1.4',  # entPhySensorValue
        'ent_sensor_status': '1.3.6.1.2.1.99.1.1.1.5',  # entPhySensorStatus
        'ent_sensor_type': '1.3.6.1.2.1.99.1.1.1.3',    # entPhySensorType
    }

    def __init__(self, snmp_client):
        self.snmp = snmp_client

    def collect_system(self, ip_addr):
        """采集设备基础指标"""
        vals = {}

        # CPU - 取第一个实例
        cpu_data = self.snmp.walk(self.OID['cpu_usage'])
        if cpu_data:
            first_key = next(iter(cpu_data))
            set_metric(vals, 'm_cpu_usage', cpu_data[first_key])

        # 内存利用率
        mem_used = self.snmp.walk(self.OID['mem_pool_used'])
        mem_free = self.snmp.walk(self.OID['mem_pool_free'])
        if mem_used and mem_free:
            # 取第一个内存池
            first_key = next(iter(mem_used))
            used = _safe_float(mem_used[first_key])
            free = _safe_float(mem_free.get(first_key))
            total = used + free if used is not None and free is not None else 0
            if total > 0:
                vals['m_mem_usage'] = round(used / total * 100.0, 2)

        # sysUpTime
        result = self.snmp.get(self.OID['sys_uptime'])
        if result.success and result.data is not None:
            # sysUpTime 单位为厘秒，转换为秒；解析异常时跳过避免中断整个采集
            try:
                set_metric(vals, 'm_sys_uptime', result.data, divisor=100.0)
            except (TypeError, ValueError):
                pass

        # connUnitStatus
        status_data = self.snmp.walk(self.OID['oper_status'])
        if status_data:
            first_key = next(iter(status_data))
            status = safe_int(status_data[first_key])
            if status is not None:
                # 1=online, 2=offline, 3=testing, 4=faulty
                vals['m_oper_status'] = 1.0 if status == 1 else 0.0

        if not vals:
            return []
        return [{"dims": {"ip": ip_addr}, "vals": vals}]

    def _get_fc_port_index_map(self):
        """获取FC端口索引到名称的映射"""
        port_names = OrderedDict()
        # 通过 ifDescr 识别 FC 端口
        if_descs = self.snmp.walk(self.OID['if_table'] + '.' + to_text(self.OID['if_desc']))
        for idx, desc in if_descs.items():
            desc_str = to_text(desc).strip('"').strip()
            if desc_str and ('fc' in desc_str.lower() or 'fiber' in desc_str.lower()
                             or 'san' in desc_str.lower() or desc_str.startswith('fc')):
                port_names[idx] = desc_str

        # 如果没有匹配FC端口，取所有非管理口
        if not port_names:
            for idx, desc in if_descs.items():
                desc_str = to_text(desc).strip('"').strip()
                if desc_str and 'mgmt' not in desc_str.lower() and 'loop' not in desc_str.lower():
                    port_names[idx] = desc_str

        return port_names

    def collect_port_status(self, ip_addr):
        """采集FC端口状态指标"""
        port_names = self._get_fc_port_index_map()
        if_oper_statuses = self.snmp.walk(
            self.OID['if_table'] + '.' + to_text(self.OID['if_oper_status']))
        if_speeds = self.snmp.walk(
            self.OID['if_table'] + '.' + to_text(self.OID['if_speed']))
        fc_wwns = self.snmp.walk(self.OID['fc_if_wwn'])

        results = []
        for idx, name in port_names.items():
            vals = {}
            if idx in if_oper_statuses:
                raw_status = safe_int(if_oper_statuses[idx])
                if raw_status is not None:
                    # ifOperStatus: 1=up, 2=down, 3=testing
                    if raw_status == 1:
                        vals['m_port_oper_status'] = 1.0
                        vals['m_port_link_state'] = 1.0
                    elif raw_status == 2:
                        vals['m_port_oper_status'] = 0.0
                        vals['m_port_link_state'] = 0.0
                    elif raw_status == 3:
                        vals['m_port_oper_status'] = 2.0
                        vals['m_port_link_state'] = 0.0
                    else:
                        vals['m_port_oper_status'] = 0.0
                        vals['m_port_link_state'] = 0.0

            if idx in if_speeds:
                speed_bps = _safe_float(if_speeds[idx])
                if speed_bps is not None:
                    vals['m_port_speed'] = round(speed_bps / 1e9, 2)

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_traffic(self, ip_addr):
        """采集FC端口流量指标"""
        port_names = self._get_fc_port_index_map()
        c3_in = self.snmp.walk(self.OID['fc_if_c3_in_octets'])
        c3_out = self.snmp.walk(self.OID['fc_if_c3_out_octets'])
        c3_discards = self.snmp.walk(self.OID['fc_if_c3_discards'])

        results = []
        for idx, name in port_names.items():
            vals = {}
            if idx in c3_out:
                set_metric(vals, 'm_port_tx_words', c3_out[idx])
            if idx in c3_in:
                set_metric(vals, 'm_port_rx_words', c3_in[idx])
            if idx in c3_discards:
                set_metric(vals, 'm_port_c3_discards', c3_discards[idx])
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_errors(self, ip_addr):
        """采集FC端口错误指标"""
        port_names = self._get_fc_port_index_map()
        invalid_crcs = self.snmp.walk(self.OID['fc_if_invalid_crcs'])
        link_failures = self.snmp.walk(self.OID['fc_if_link_failures'])
        sync_losses = self.snmp.walk(self.OID['fc_if_sync_losses'])
        sig_losses = self.snmp.walk(self.OID['fc_if_sig_losses'])
        credit_loss = self.snmp.walk(self.OID['fc_if_credit_loss'])
        fec_uncorrected = self.snmp.walk(self.OID['fc_if_fec_uncorrected'])

        results = []
        for idx, name in port_names.items():
            vals = {}
            if idx in invalid_crcs:
                set_metric(vals, 'm_port_crc_errors', invalid_crcs[idx])
            if idx in link_failures:
                set_metric(vals, 'm_port_link_failures', link_failures[idx])
            if idx in sync_losses:
                set_metric(vals, 'm_port_sync_losses', sync_losses[idx])
            if idx in sig_losses:
                set_metric(vals, 'm_port_sig_losses', sig_losses[idx])
            if idx in credit_loss:
                set_metric(vals, 'm_port_credit_loss', credit_loss[idx])
            if idx in fec_uncorrected:
                set_metric(vals, 'm_port_fec_uncorrected', fec_uncorrected[idx])
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_sensors(self, ip_addr):
        """采集传感器指标"""
        ent_phy_names = self.snmp.walk(
            self.OID['ent_phynum_table'] + '.' + to_text(self.OID['ent_phy_name']))
        sensor_values = self.snmp.walk(self.OID['ent_sensor_value'])
        sensor_statuses = self.snmp.walk(self.OID['ent_sensor_status'])

        results = []
        for idx in sensor_values:
            phy_name = to_text(ent_phy_names.get(idx, idx)).strip('"').strip() or "Sensor_" + idx
            vals = {}
            if idx in sensor_values:
                set_metric(vals, 'm_sensor_value', sensor_values[idx])
            if idx in sensor_statuses:
                # entPhySensorStatus: 1=ok, 2=unavailable, 3=nonCritical, 4=critical, 5=shutdown
                raw_status = safe_int(sensor_statuses[idx])
                if raw_status is not None:
                    status_map = {1: 2, 2: 4, 3: 5, 4: 6, 5: 3}
                    set_metric(vals, 'm_sensor_status', status_map.get(raw_status, 4))
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "sensor_name": phy_name},
                    "vals": vals
                })
        return results

    def collect_sfp(self, ip_addr):
        """采集SFP光模块指标（Cisco通过ENTITY-SENSOR-MIB间接获取）"""
        # Cisco 没有直接的SFP诊断OID，通过传感器表过滤光模块相关传感器
        ent_phy_names = self.snmp.walk(
            self.OID['ent_phynum_table'] + '.' + to_text(self.OID['ent_phy_name']))
        sensor_values = self.snmp.walk(self.OID['ent_sensor_value'])
        sensor_types = self.snmp.walk(self.OID['ent_sensor_type'])

        results = []
        for idx in sensor_values:
            phy_name = to_text(ent_phy_names.get(idx, idx)).strip('"').strip()
            # 过滤包含 SFP/Transceiver/Power/Temperature/Voltage 的传感器
            lower_name = phy_name.lower()
            if not any(k in lower_name for k in ['sfp', 'transceiver', 'xcvr', 'power', 'temp', 'volt']):
                continue
            vals = {}
            sensor_val = _safe_float(sensor_values[idx])
            if sensor_val is None:
                continue
            s_type = safe_int(sensor_types.get(idx, 0))
            if s_type is None:
                continue
            # EntitySensorDataType: 1=other, 2=unknown, 3=voltsAC, 4=voltsDC, 5=amperes,
            # 6=watts, 7=hertz, 8=celsius, 9=percentRH, 10=rpm, 11=cmm, 12=truthvalue
            if s_type == 8:  # celsius
                vals['m_sfp_temperature'] = sensor_val
            elif s_type in [3, 4]:  # volts
                vals['m_sfp_voltage'] = sensor_val
            elif 'tx' in lower_name or 'transmit' in lower_name:
                vals['m_sfp_tx_power'] = sensor_val
            elif 'rx' in lower_name or 'receive' in lower_name:
                vals['m_sfp_rx_power'] = sensor_val

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": phy_name},
                    "vals": vals
                })
        return results


# ============================================================================
# 华为自研采集器
# ============================================================================
class HuaweiMonitor(object):
    """华为自研（非OEM）光纤交换机采集器"""

    OID = {
        # 设备基础（华为私有MIB）
        'cpu_usage': '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5',  # hwEntityCpuUsage（表）
        'mem_usage': '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7',   # hwEntityMemUsage（表）
        'sys_uptime': '1.3.6.1.2.1.1.3.0',
        # FC端口 - 尝试FCMGMT-MIB标准表
        'conn_unit_table': '1.3.6.1.3.94.1.6',
        'conn_unit_status': 5,
        'conn_unit_name': 3,
        # 端口表 (FCMGMT-MIB)
        'fc_port_table': '1.3.6.1.3.94.1.10.1',
        'fc_port_name': 6,
        'fc_port_oper_status': 7,
        'fc_port_phy_state': 8,
        'fc_port_tx_words': 12,
        'fc_port_rx_words': 13,
        'fc_port_tx_frames': 14,
        'fc_port_rx_frames': 15,
        'fc_port_speed': 11,
        # 传感器
        'ent_sensor_value': '1.3.6.1.2.1.99.1.1.1.4',
        'ent_sensor_status': '1.3.6.1.2.1.99.1.1.1.5',
        'ent_phy_name': '1.3.6.1.2.1.47.1.1.1.1.7',
    }

    def __init__(self, snmp_client):
        self.snmp = snmp_client

    def collect_system(self, ip_addr):
        """采集设备基础指标"""
        vals = {}

        cpu_data = self.snmp.walk(self.OID['cpu_usage'])
        if cpu_data:
            first_key = next(iter(cpu_data))
            set_metric(vals, 'm_cpu_usage', cpu_data[first_key])

        mem_data = self.snmp.walk(self.OID['mem_usage'])
        if mem_data:
            first_key = next(iter(mem_data))
            set_metric(vals, 'm_mem_usage', mem_data[first_key])

        result = self.snmp.get(self.OID['sys_uptime'])
        if result.success and result.data is not None:
            # sysUpTime 单位为厘秒，转换为秒；解析异常时跳过避免中断整个采集
            try:
                set_metric(vals, 'm_sys_uptime', result.data, divisor=100.0)
            except (TypeError, ValueError):
                pass

        if not vals:
            return []
        return [{"dims": {"ip": ip_addr}, "vals": vals}]

    def collect_port_status(self, ip_addr):
        """采集FC端口状态指标"""
        port_names = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_name']))
        port_statuses = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_oper_status']))
        port_phys = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_phy_state']))
        port_speeds = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_speed']))

        results = []
        for idx in port_names:
            name = to_text(port_names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in port_statuses:
                raw_status = safe_int(port_statuses[idx])
                if raw_status is not None:
                    # connUnitPortStatus: 1=unknown, 2=unused, 3=ready, 4=warning, 5=failure
                    if raw_status == 3:
                        vals['m_port_oper_status'] = 1.0
                    elif raw_status == 4:
                        vals['m_port_oper_status'] = 5.0  # warning
                    elif raw_status == 5:
                        vals['m_port_oper_status'] = 3.0  # faulty
                    else:
                        vals['m_port_oper_status'] = 0.0

            if idx in port_phys:
                set_metric(vals, 'm_port_phy_state', port_phys[idx])
            if idx in port_speeds:
                set_metric(vals, 'm_port_speed', port_speeds[idx])

            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_traffic(self, ip_addr):
        """采集FC端口流量指标"""
        port_names = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_name']))
        tx_words = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_tx_words']))
        rx_words = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_rx_words']))
        tx_frames = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_tx_frames']))
        rx_frames = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_rx_frames']))

        results = []
        for idx in port_names:
            name = to_text(port_names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in tx_words:
                set_metric(vals, 'm_port_tx_words', tx_words[idx])
            if idx in rx_words:
                set_metric(vals, 'm_port_rx_words', rx_words[idx])
            if idx in tx_frames:
                set_metric(vals, 'm_port_tx_frames', tx_frames[idx])
            if idx in rx_frames:
                set_metric(vals, 'm_port_rx_frames', rx_frames[idx])
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_errors(self, ip_addr):
        """采集FC端口错误指标（华为FCMGMT-MIB无详细错误表）"""
        return []

    def collect_sensors(self, ip_addr):
        """采集传感器指标"""
        phy_names = self.snmp.walk(self.OID['ent_phy_name'])
        sensor_values = self.snmp.walk(self.OID['ent_sensor_value'])
        sensor_statuses = self.snmp.walk(self.OID['ent_sensor_status'])

        results = []
        for idx in sensor_values:
            name = to_text(phy_names.get(idx, idx)).strip('"').strip() or "Sensor_" + idx
            vals = {}
            if idx in sensor_values:
                set_metric(vals, 'm_sensor_value', sensor_values[idx])
            if idx in sensor_statuses:
                raw = safe_int(sensor_statuses[idx])
                if raw is not None:
                    status_map = {1: 2, 2: 4, 3: 5, 4: 6, 5: 3}
                    set_metric(vals, 'm_sensor_status', status_map.get(raw, 4))
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "sensor_name": name},
                    "vals": vals
                })
        return results

    def collect_sfp(self, ip_addr):
        """采集SFP光模块指标（华为无直接SFP诊断OID）"""
        return []


# ============================================================================
# FCMGMT-MIB 标准回退采集器
# ============================================================================
class FCMgmtMonitor(object):
    """FCMGMT-MIB (RFC 2837) 标准采集器，作为回退方案"""

    OID = {
        'sys_uptime': '1.3.6.1.2.1.1.3.0',
        'conn_unit_table': '1.3.6.1.3.94.1.6',
        'conn_unit_status': 5,
        'conn_unit_name': 3,
        # 端口表
        'fc_port_table': '1.3.6.1.3.94.1.10.1',
        'fc_port_name': 6,
        'fc_port_type': 5,
        'fc_port_oper_status': 7,
        'fc_port_tx_words': 12,
        'fc_port_rx_words': 13,
        'fc_port_tx_frames': 14,
        'fc_port_rx_frames': 15,
        'fc_port_speed': 11,
        # 传感器
        'ent_sensor_value': '1.3.6.1.2.1.99.1.1.1.4',
        'ent_sensor_status': '1.3.6.1.2.1.99.1.1.1.5',
        'ent_phy_name': '1.3.6.1.2.1.47.1.1.1.1.7',
    }

    def __init__(self, snmp_client):
        self.snmp = snmp_client

    def collect_system(self, ip_addr):
        """采集设备基础指标"""
        vals = {}
        result = self.snmp.get(self.OID['sys_uptime'])
        if result.success and result.data is not None:
            # sysUpTime 单位为厘秒，转换为秒；解析异常时跳过避免中断整个采集
            try:
                set_metric(vals, 'm_sys_uptime', result.data, divisor=100.0)
            except (TypeError, ValueError):
                pass

        status_data = self.snmp.walk(
            self.OID['conn_unit_table'] + '.' + to_text(self.OID['conn_unit_status']))
        if status_data:
            first_key = next(iter(status_data))
            status = safe_int(status_data[first_key])
            if status is not None:
                vals['m_oper_status'] = 1.0 if status == 1 else 0.0

        if not vals:
            return []
        return [{"dims": {"ip": ip_addr}, "vals": vals}]

    def collect_port_status(self, ip_addr):
        """采集FC端口状态指标"""
        port_names = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_name']))
        port_statuses = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_oper_status']))
        port_speeds = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_speed']))

        results = []
        for idx in port_names:
            name = to_text(port_names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in port_statuses:
                raw_status = safe_int(port_statuses[idx])
                if raw_status is not None:
                    if raw_status == 3:
                        vals['m_port_oper_status'] = 1.0
                    elif raw_status == 4:
                        vals['m_port_oper_status'] = 5.0
                    elif raw_status == 5:
                        vals['m_port_oper_status'] = 3.0
                    else:
                        vals['m_port_oper_status'] = 0.0
            if idx in port_speeds:
                set_metric(vals, 'm_port_speed', port_speeds[idx])
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_traffic(self, ip_addr):
        """采集FC端口流量指标"""
        port_names = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_name']))
        tx_words = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_tx_words']))
        rx_words = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_rx_words']))
        tx_frames = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_tx_frames']))
        rx_frames = self.snmp.walk(self.OID['fc_port_table'] + '.' + to_text(self.OID['fc_port_rx_frames']))

        results = []
        for idx in port_names:
            name = to_text(port_names.get(idx, idx)).strip('"').strip() or "Port_" + idx
            vals = {}
            if idx in tx_words:
                set_metric(vals, 'm_port_tx_words', tx_words[idx])
            if idx in rx_words:
                set_metric(vals, 'm_port_rx_words', rx_words[idx])
            if idx in tx_frames:
                set_metric(vals, 'm_port_tx_frames', tx_frames[idx])
            if idx in rx_frames:
                set_metric(vals, 'm_port_rx_frames', rx_frames[idx])
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "port_name": name},
                    "vals": vals
                })
        return results

    def collect_port_errors(self, ip_addr):
        """FCMGMT-MIB无详细错误表"""
        return []

    def collect_sensors(self, ip_addr):
        """采集传感器指标"""
        phy_names = self.snmp.walk(self.OID['ent_phy_name'])
        sensor_values = self.snmp.walk(self.OID['ent_sensor_value'])
        sensor_statuses = self.snmp.walk(self.OID['ent_sensor_status'])

        results = []
        for idx in sensor_values:
            name = to_text(phy_names.get(idx, idx)).strip('"').strip() or "Sensor_" + idx
            vals = {}
            if idx in sensor_values:
                set_metric(vals, 'm_sensor_value', sensor_values[idx])
            if idx in sensor_statuses:
                raw = safe_int(sensor_statuses[idx])
                if raw is not None:
                    status_map = {1: 2, 2: 4, 3: 5, 4: 6, 5: 3}
                    set_metric(vals, 'm_sensor_status', status_map.get(raw, 4))
            if vals:
                results.append({
                    "dims": {"ip": ip_addr, "sensor_name": name},
                    "vals": vals
                })
        return results

    def collect_sfp(self, ip_addr):
        """FCMGMT-MIB无SFP诊断表"""
        return []


# ============================================================================
# 采集入口
# ============================================================================
VENDOR_MONITOR_MAP = {
    VENDOR_BROCADE: BrocadeMonitor,
    VENDOR_CISCO: CiscoMDSMonitor,
    VENDOR_HUAWEI: HuaweiMonitor,
    VENDOR_FCMGMT: FCMgmtMonitor,
}

VENDOR_LABEL = {
    VENDOR_BROCADE: 'Brocade',
    VENDOR_CISCO: 'Cisco',
    VENDOR_HUAWEI: 'Huawei',
    VENDOR_FCMGMT: 'FCMGMT',
}


def preflight(snmp_client):
    """一次只读SNMP认证检查，预算3秒、零重试，失败不进入业务采集。"""
    timeout, retries = snmp_client.timeout, snmp_client.retries
    snmp_client.timeout, snmp_client.retries = 3, 0
    try:
        result = snmp_client.get('1.3.6.1.2.1.1.1.0')
        if not result.success or missing_value(result.data):
            raise RuntimeError('[preflight] SNMP检查失败: ' + redact(result.error or '基础OID无有效数据'))
        LOGGER.debug('[preflight] SNMP认证检查通过')
    finally:
        snmp_client.timeout, snmp_client.retries = timeout, retries


def collect_all(snmp_client, ip_addr):
    """按阶段隔离可选采集异常，保留已采集结果；全空不伪报成功。"""
    preflight(snmp_client)
    vendor = detect_vendor(snmp_client)
    LOGGER.debug('[collect_all] vendor=%s', vendor)
    monitor_cls = VENDOR_MONITOR_MAP.get(vendor, FCMgmtMonitor)
    monitor = monitor_cls(snmp_client)
    records = []
    errors = []
    for stage in ('collect_system', 'collect_port_status', 'collect_port_traffic',
                  'collect_port_errors', 'collect_sensors', 'collect_sfp'):
        try:
            current = getattr(monitor, stage)(ip_addr)
            records.extend(current)
            LOGGER.debug('[collect_all.%s] rows=%s', stage, len(current))
        except Exception:
            error = '[collect_all.%s] %s' % (stage, redact(traceback.format_exc()))
            errors.append(error)
            LOGGER.warning('%s', error)
    if not records:
        raise RuntimeError('[collect_all] 所有指标均无有效数据\n' + '\n'.join(errors))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='光纤交换机SNMP监控。参数由EASYOPS_COLLECTOR_*环境变量提供，凭证不写命令行。',
        epilog='示例：EASYOPS_COLLECTOR_ip=192.0.2.10 EASYOPS_COLLECTOR_port=161 python 光纤交换机监控.py\n'
               '团体名/认证密钥通过环境变量注入。前置检查3秒、零重试，正式命令默认10秒。\n'
               '成功stdout为JSON数组；失败stdout为COLLECT_ERROR和脱敏traceback，均退出0供平台展示。\n'
               '参数用法错误退出2；可用Ctrl+C停止。logLevel默认ERROR，可设DEBUG输出脱敏诊断。',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', action='version', version=VERSION, help='显示套件版本并退出')
    parser.parse_args(argv)
    setup_logging()
    try:
        config = load_config()
        client = SNMPClient(**config)
        records = collect_all(client, config['ip'])
        sys.stdout.write(json.dumps(records, ensure_ascii=True, allow_nan=False) + '\n')
    except Exception:
        text = 'COLLECT_ERROR: [main]\n' + redact(traceback.format_exc())
        if sys.version_info[0] < 3:
            text = text.encode('utf-8')
        sys.stdout.write(text + ('\n' if sys.version_info[0] >= 3 else b'\n'))
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
