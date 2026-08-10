# 采集脚本模板

## SNMP 采集模板

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess
import json
import platform
from collections import namedtuple

# 环境变量获取参数
ip = os.environ.get("EASYOPS_COLLECTOR_ip")
port = os.environ.get("EASYOPS_COLLECTOR_port", "161")
version = os.environ.get("EASYOPS_COLLECTOR_version", "2c")
community = os.environ.get("EASYOPS_COLLECTOR_community", "public")
username = os.environ.get("EASYOPS_COLLECTOR_username")
auth_key = os.environ.get("EASYOPS_COLLECTOR_auth_key")
auth_protocol = os.environ.get("EASYOPS_COLLECTOR_auth_protocol")
priv_key = os.environ.get("EASYOPS_COLLECTOR_priv_key")
priv_protocol = os.environ.get("EASYOPS_COLLECTOR_priv_protocol")
# 自定义参数
oid = os.environ.get("EASYOPS_COLLECTOR_oid")
dim_value = os.environ.get("EASYOPS_COLLECTOR_dim_value")

Result = namedtuple('Result', ['success', 'data', 'error'])


def parse_snmp_value(value_str):
    """解析SNMP返回值，自动转换数据类型"""
    value_str = value_str.strip()
    if ':' in value_str:
        parts = value_str.split(':', 1)
        if len(parts) == 2:
            value_part = parts[1].strip()
            try:
                return int(value_part)
            except ValueError:
                try:
                    return float(value_part)
                except ValueError:
                    return value_part
    try:
        return int(value_str)
    except ValueError:
        try:
            return float(value_str)
        except ValueError:
            return value_str


class SNMPClient:
    def __init__(self, ip, port=161, version='2c', community='public',
                 username=None, auth_key=None, auth_protocol='MD5',
                 priv_key=None, priv_protocol='DES', timeout=10):
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

    def _build_auth_params(self):
        if self.version in ['1', '2c']:
            return ['-v', self.version, '-c', self.community]
        elif self.version == '3':
            params = ['-v', '3', '-u', self.username]
            if self.auth_key:
                params.extend(['-A', self.auth_key, '-a', self.auth_protocol])
            if self.priv_key:
                params.extend(['-X', self.priv_key, '-x', self.priv_protocol])
            else:
                params.extend(['-l', 'noPriv'])
            return params

    def get(self, oid):
        auth_params = self._build_auth_params()
        command = ['snmpget', '-On'] + auth_params + ["{0}:{1}".format(self.ip, self.port), oid]
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            if proc.returncode == 0 and stdout:
                for line in stdout.decode().split('\n'):
                    if '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) >= 2:
                            return Result(True, parse_snmp_value(parts[1]), "")
            return Result(False, None, stderr.decode() if stderr else "Unknown error")
        except Exception as e:
            return Result(False, None, str(e))


if __name__ == "__main__":
    client = SNMPClient(ip=ip, port=int(port), version=version, community=community,
                        username=username, auth_key=auth_key, auth_protocol=auth_protocol,
                        priv_key=priv_key, priv_protocol=priv_protocol)

    info = []
    result = client.get(oid)
    if result.success:
        tmp = {
            "dims": {"dim_name": dim_value},
            "vals": {}
        }
        if isinstance(result.data, (int, float)):
            tmp['vals']['num_val'] = result.data
        else:
            tmp['vals']['str_val'] = str(result.data)
        info.append(tmp)

    print(json.dumps(info, ensure_ascii=False))
```

## HTTP API 采集模板

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os
import json
try:
    import urllib2
    from urllib2 import Request, urlopen, HTTPError, URLError
except ImportError:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

# 环境变量获取参数
url = os.environ.get("EASYOPS_COLLECTOR_url")
method = os.environ.get("EASYOPS_COLLECTOR_method", "GET")
headers_str = os.environ.get("EASYOPS_COLLECTOR_headers", "{}")
body = os.environ.get("EASYOPS_COLLECTOR_body", "")
timeout = int(os.environ.get("EASYOPS_COLLECTOR_timeout", "30"))
dim_value = os.environ.get("EASYOPS_COLLECTOR_dim_value")
# JSON路径提取（简单实现）
json_path = os.environ.get("EASYOPS_COLLECTOR_json_path", "")


def extract_value(data, path):
    """简单的JSON路径提取，支持 a.b.c 格式"""
    if not path:
        return data
    keys = path.split('.')
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and key.isdigit():
            data = data[int(key)]
        else:
            return None
    return data


if __name__ == "__main__":
    info = []
    try:
        headers = json.loads(headers_str)
        req = Request(url, data=body.encode() if body else None, headers=headers)
        req.get_method = lambda: method

        response = urlopen(req, timeout=timeout)
        content = response.read().decode('utf-8')

        # 尝试解析JSON
        try:
            data = json.loads(content)
            value = extract_value(data, json_path)
        except:
            value = content

        tmp = {
            "dims": {"dim_name": dim_value},
            "vals": {}
        }
        if isinstance(value, (int, float)):
            tmp['vals']['num_val'] = value
        else:
            tmp['vals']['str_val'] = str(value) if value else ""

        # 添加响应状态
        tmp['vals']['status_code'] = response.getcode()
        info.append(tmp)

    except HTTPError as e:
        info.append({
            "dims": {"dim_name": dim_value},
            "vals": {"status_code": e.code, "str_val": str(e.reason)}
        })
    except URLError as e:
        info.append({
            "dims": {"dim_name": dim_value},
            "vals": {"status_code": -1, "str_val": str(e.reason)}
        })
    except Exception as e:
        info.append({
            "dims": {"dim_name": dim_value},
            "vals": {"status_code": -1, "str_val": str(e)}
        })

    print(json.dumps(info, ensure_ascii=False))
```

## 命令行采集模板

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess
import json
import re

# 环境变量获取参数
command = os.environ.get("EASYOPS_COLLECTOR_command")
timeout = int(os.environ.get("EASYOPS_COLLECTOR_timeout", "30"))
regex_pattern = os.environ.get("EASYOPS_COLLECTOR_regex", "")
dim_value = os.environ.get("EASYOPS_COLLECTOR_dim_value")


if __name__ == "__main__":
    info = []
    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate()
        output = stdout.decode('utf-8').strip()

        tmp = {
            "dims": {"dim_name": dim_value},
            "vals": {"exit_code": proc.returncode}
        }

        # 如果有正则表达式，提取匹配值
        if regex_pattern and output:
            match = re.search(regex_pattern, output)
            if match:
                value = match.group(1) if match.groups() else match.group(0)
                try:
                    tmp['vals']['num_val'] = float(value)
                except ValueError:
                    tmp['vals']['str_val'] = value
            else:
                tmp['vals']['str_val'] = output
        else:
            tmp['vals']['str_val'] = output

        info.append(tmp)

    except Exception as e:
        info.append({
            "dims": {"dim_name": dim_value},
            "vals": {"exit_code": -1, "str_val": str(e)}
        })

    print(json.dumps(info, ensure_ascii=False))
```

## 数据库查询模板 (MySQL)

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import os
import json

# 环境变量获取参数
host = os.environ.get("EASYOPS_COLLECTOR_host")
port = int(os.environ.get("EASYOPS_COLLECTOR_port", "3306"))
user = os.environ.get("EASYOPS_COLLECTOR_user")
password = os.environ.get("EASYOPS_COLLECTOR_password")
database = os.environ.get("EASYOPS_COLLECTOR_database")
query = os.environ.get("EASYOPS_COLLECTOR_query")
dim_value = os.environ.get("EASYOPS_COLLECTOR_dim_value")

try:
    import MySQLdb
except ImportError:
    import pymysql as MySQLdb


if __name__ == "__main__":
    info = []
    try:
        conn = MySQLdb.connect(
            host=host, port=port, user=user,
            passwd=password, db=database, charset='utf8'
        )
        cursor = conn.cursor()
        cursor.execute(query)

        # 获取列名
        columns = [desc[0] for desc in cursor.description]

        for row in cursor.fetchall():
            tmp = {
                "dims": {"dim_name": dim_value},
                "vals": {}
            }
            for i, col in enumerate(columns):
                value = row[i]
                if isinstance(value, (int, float)):
                    tmp['vals'][col] = value
                else:
                    tmp['vals'][col] = str(value) if value else ""
            info.append(tmp)

        cursor.close()
        conn.close()

    except Exception as e:
        info.append({
            "dims": {"dim_name": dim_value},
            "vals": {"error": str(e)}
        })

    print(json.dumps(info, ensure_ascii=False))
```
