#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os

port=os.environ.get("EASYOPS_COLLECTOR_port")
auth_key=os.environ.get("EASYOPS_COLLECTOR_auth_key")
auth_protocol=os.environ.get("EASYOPS_COLLECTOR_auth_protocol")
priv_key=os.environ.get("EASYOPS_COLLECTOR_priv_key")
priv_protocol=os.environ.get("EASYOPS_COLLECTOR_priv_protocol")
singl_point_oid=os.environ.get("EASYOPS_COLLECTOR_singl_point_oid")
ip=os.environ.get("EASYOPS_COLLECTOR_ip")
community=os.environ.get("EASYOPS_COLLECTOR_community")
username=os.environ.get("EASYOPS_COLLECTOR_username")
version=os.environ.get("EASYOPS_COLLECTOR_version")
monitor_point_path=os.environ.get("EASYOPS_COLLECTOR_monitor_point_path")
import subprocess
import re
import json
import platform
from collections import namedtuple

# 定义返回值类型
Result = namedtuple('Result', ['success', 'data', 'error'])


def parse_snmp_value(value_str):
    """
    解析SNMP返回的值，尝试转换为适当的数据类型
    
    :param value_str: 原始字符串值
    :return: 转换后的值（可能是str, int, float等）
    """
    # 去除首尾空格
    value_str = value_str.strip()
    
    # 如果包含特殊SNMP类型标识（如 INTEGER, STRING, OCTETSTR 等），提取实际值
    if ':' in value_str:
        parts = value_str.split(':', 1)
        if len(parts) == 2:
            type_part = parts[0].strip().upper()
            value_part = parts[1].strip()
            
            # 根据SNMP类型进行处理
            if type_part in ['INTEGER', 'COUNTER32', 'COUNTER64', 'GAUGE32', 'TIMETICKS', 'IPADDRESS']:
                try:
                    return int(value_part)
                except ValueError:
                    return value_part
            elif type_part in ['STRING', 'OCTETSTR', 'OPAQUE', 'OBJECT IDENTIFIER']:
                return value_part
            elif type_part in ['COUNTER', 'GAUGE']:
                try:
                    return int(value_part)
                except ValueError:
                    return value_part
            else:
                # 尝试数字转换
                try:
                    # 尝试转换为整数
                    return int(value_part)
                except ValueError:
                    try:
                        # 尝试转换为浮点数
                        return float(value_part)
                    except ValueError:
                        # 返回原始字符串
                        return value_part
        else:
            # 尝试数字转换
            try:
                # 尝试转换为整数
                return int(value_part)
            except ValueError:
                try:
                    # 尝试转换为浮点数
                    return float(value_part)
                except ValueError:
                    # 返回原始字符串
                    return value_part
    else:
        # 如果没有类型标识，尝试转换为数字
        try:
            # 尝试转换为整数
            return int(value_str)
        except ValueError:
            try:
                # 尝试转换为浮点数
                return float(value_str)
            except ValueError:
                # 返回原始字符串
                return value_str


class SNMPClient:
    """
    Linux SNMP客户端类，使用系统自带的snmpwalk、snmpget等命令
    """

    def __init__(self, ip, port=161, version='2c', community='public',
                 username=None, auth_key=None, auth_protocol='MD5',
                 priv_key=None, priv_protocol='DES', timeout=10, retries=3):
        """
        初始化SNMP客户端

        :param ip: 目标设备IP地址
        :param port: SNMP端口，默认161
        :param version: SNMP版本 ('1', '2c', '3')
        :param community: SNMP团体名（v1/v2c使用）
        :param username: 用户名（v3使用）
        :param auth_key: 认证密钥（v3使用）
        :param auth_protocol: 认证协议（v3使用）MD5/SHA
        :param priv_key: 加密密钥（v3使用）
        :param priv_protocol: 加密协议（v3使用）DES/3DES/AES/AES192/AES256
        :param timeout: 超时时间（秒）
        :param retries: 重试次数
        """
        self.ip = ip
        self.port = port
        self.version = version
        self.community = community
        self.username = username
        self.auth_key = auth_key
        self.auth_protocol = auth_protocol.upper() if auth_protocol else 'MD5'
        self.priv_key = priv_key
        self.priv_protocol = priv_protocol.upper() if priv_protocol else 'DES'
        self.timeout = timeout
        self.retries = retries

        # 验证系统是否安装了snmp工具
        self._check_snmp_tools()

    def _check_snmp_tools(self):
        """检查系统是否安装了snmp工具"""
        try:
            result = subprocess.Popen(['which', 'snmpwalk'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = result.communicate()
            if not stdout.strip():
                raise RuntimeError("未找到snmpwalk命令，请先安装net-snmp-utils或snmp软件包")
        except:
            raise RuntimeError("未找到snmpwalk命令，请先安装net-snmp-utils或snmp软件包")

    def _build_auth_params(self):
        """构建认证参数"""
        if self.version in ['1', '2c']:
            # v1和v2c使用community
            return ['-v', self.version, '-c', self.community]
        elif self.version == '3':
            # v3使用用户名和认证参数
            params = ['-v', '3', '-u', self.username]

            # 添加认证参数
            if self.auth_key:
                params.extend(['-A', self.auth_key, '-a', self.auth_protocol])

            # 添加隐私参数
            if self.priv_key:
                params.extend(['-X', self.priv_key, '-x', self.priv_protocol])
            else:
                # 如果没有隐私密钥，使用noPriv
                params.extend(['-l', 'noPriv'])

            return params
        else:
            raise ValueError("不支持的SNMP版本: {0}".format(self.version))

    def _execute_command(self, command):
        """
        执行SNMP命令

        :param command: 要执行的命令列表
        :return: Result(success, stdout, stderr)
        """
        try:
            # 检测操作系统类型，如果是macOS则不使用timeout命令
            is_macos = platform.system().lower() == 'darwin'
            if is_macos:
                # 直接执行命令，避免timeout命令导致gmon.out错误
                proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = proc.communicate()
            else:
                # Linux系统使用timeout命令
                cmd = ['timeout', str(self.timeout)] + command
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = proc.communicate()

            success = proc.returncode == 0
            stdout = stdout.strip() if stdout else ""
            stderr = stderr.strip() if stderr else ""

            # 清理stderr中的gmon.out错误信息
            if stderr:
                # 过滤掉与gmon.out相关的错误
                stderr_lines = stderr.split('\n')
                filtered_stderr = [line for line in stderr_lines if 'gmon.out' not in line and '_mcleanup' not in line]
                stderr = '\n'.join(filtered_stderr).strip()

            return Result(success=success, data=stdout, error=stderr)
        except Exception as e:
            return Result(success=False, data="", error=str(e))

    def get(self, oid):
        """
        获取单个OID的值

        :param oid: OID字符串，例如 '1.3.6.1.2.1.1.1.0'
        :return: Result(success, result_dict, error_message)
        """
        auth_params = self._build_auth_params()
        command = ['snmpget', '-On', '-v'] + auth_params[1:] + ["{0}:{1}".format(self.ip, self.port), oid]

        result = self._execute_command(command)

        if result.success and result.data:
            # 解析输出，格式通常是：OID = 类型: 值
            lines = result.data.split('\n')
            result_dict = {}
            for line in lines:
                if '=' in line:
                    parts = line.split('=', 1)
                    if len(parts) >= 2:
                        oid_part = parts[0].strip()
                        value_part = parts[1].strip()
                        # 解析值部分，自动转换数据类型
                        parsed_value = parse_snmp_value(value_part)
                        result_dict[oid_part] = parsed_value
            return Result(success=True, data=result_dict, error="")
        else:
            return Result(success=False, data={}, error=result.error or "未知错误")

    def walk(self, oid):
        """
        遍历OID树

        :param oid: 起始OID字符串
        :return: 结果列表 [(oid, value), ...]
        """
        auth_params = self._build_auth_params()
        command = ['snmpwalk', '-On', '-v'] + auth_params[1:] + ["{0}:{1}".format(self.ip, self.port), oid]

        result = self._execute_command(command)

        if result.success and result.data:
            results = []
            for line in result.data.split('\n'):
                if line.strip() and '=' in line:
                    parts = line.split('=', 1)
                    if len(parts) >= 2:
                        oid_part = parts[0].strip()
                        value_part = parts[1].strip()
                        # 解析值部分，自动转换数据类型
                        parsed_value = parse_snmp_value(value_part)
                        results.append((oid_part, parsed_value))
            return results
        else:
            return [('ERROR', result.error or "未知错误")]

    def get_bulk(self, oids, non_repeaters=0, max_repetitions=10):
        """
        使用GETBULK获取多个OID的值

        :param oids: OID列表
        :param non_repeaters: 非重复器数量
        :param max_repetitions: 最大重复次数
        :return: 结果列表 [(oid, value), ...]
        """
        if self.version == '1':
            # SNMPv1不支持GETBULK，降级到GETNEXT
            print("SNMPv1不支持GETBULK，使用GETNEXT替代")
            results = []
            for oid in oids:
                results.extend(self.walk(oid))
            return results

        auth_params = self._build_auth_params()
        command = ['snmpbulkwalk', '-On', '-v', '2c'] + auth_params[2:] + \
                  ['-Cn', str(non_repeaters), '-Cr', str(max_repetitions), "{0}:{1}".format(self.ip, self.port)] + oids

        result = self._execute_command(command)

        if result.success and result.data:
            results = []
            for line in result.data.split('\n'):
                if line.strip() and '=' in line:
                    parts = line.split('=', 1)
                    if len(parts) >= 2:
                        oid_part = parts[0].strip()
                        value_part = parts[1].strip()
                        # 解析值部分，自动转换数据类型
                        parsed_value = parse_snmp_value(value_part)
                        results.append((oid_part, parsed_value))
            return results
        else:
            return [('ERROR', result.error or "未知错误")]

    def set(self, oid, value, snmp_type='octetstring'):
        """
        设置OID的值

        :param oid: OID字符串
        :param value: 要设置的值
        :param snmp_type: SNMP数据类型 ('integer', 'octetstring', 'ipaddress', etc.)
        :return: Result(success, result, error_message)
        """
        auth_params = self._build_auth_params()
        # 转换类型为小写
        snmp_type = snmp_type.lower()

        command = ['snmpset', '-v'] + auth_params[1:] + ["{0}:{1}".format(self.ip, self.port), oid, snmp_type, value]

        result = self._execute_command(command)

        if result.success and result.data:
            return Result(success=True, data=result.data, error="")
        else:
            return Result(success=False, data="", error=result.error or "未知错误")

    def test_connection(self):
        """
        测试与SNMP设备的连接

        :return: 连接是否成功
        """
        # 尝试获取系统描述来测试连接
        result = self.get('1.3.6.1.2.1.1.1.0')
        return result.success


# 示例用法
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # # singl_point_oid = '1.3.6.1.2.1.1.1.0' # sysDescr
    # singl_point_oid = '1.3.6.1.2.1.6.9.0' # tcpCurrEstab
    # monitor_point_path = '测试'
    # ip = '172.30.0.90'
    # port = 161
    # version = '2c'
    # community = 'public'
    # username = None
    # auth_key = None
    # auth_protocol = None
    # priv_key = None
    # priv_protocol = None

    snmp_client = SNMPClient(
        ip=ip,
        port=port,
        version=version,
        community=community,
        username=username,
        auth_key=auth_key,
        auth_protocol=auth_protocol,
        priv_key=priv_key,
        priv_protocol=priv_protocol,
    )

    info = []
    result = snmp_client.get(singl_point_oid)
    if not result.success:
        logging.error("{0}获取失败: {1}".format(singl_point_oid, result.error))
    tmp = {
        "dims": {"monitor_point_path": monitor_point_path,"singl_point_oid":singl_point_oid},
        "vals": {
          # 'str_val': '', 
          # 'num_val': -1
        }
    }
    value = list(result.data.values())[0]
    if isinstance(value, (int, float)):
        tmp['vals']['num_val'] = value
    else:
        tmp['vals']['str_val'] = value
    info.append(tmp)
    print(json.dumps(info, ensure_ascii=False, indent=4))