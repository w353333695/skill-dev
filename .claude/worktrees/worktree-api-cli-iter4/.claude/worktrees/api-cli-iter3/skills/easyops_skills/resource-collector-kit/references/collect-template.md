# 资源采集脚本模板参考

资源采集脚本用于采集设备/资源的配置信息（CMDB 实例数据），与监控脚本的区别：

- **监控脚本**：输出 dims + vals（指标值），通过 origin_metric.json 定义指标
- **资源采集脚本**：输出 dims + vals（模型属性值），通过 GATHERING DATA 标记包裹，写入 CMDB

## 通用脚本结构

```python
#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
# tool_name: <插件名称>
from __future__ import print_function
import os

# .py 文件：通过环境变量获取参数
# .orig 文件：不包含这段环境变量代码
<param1> = os.environ.get("EASYOPS_COLLECTOR_<param1>")
<param2> = os.environ.get("EASYOPS_COLLECTOR_<param2>")

import sys
import json
import logging
import warnings

warnings.filterwarnings("ignore")
reload(sys)
sys.setdefaultencoding('utf8')

# 日志初始化
current_dir = os.path.dirname(os.path.abspath(__file__))
_SAMPLER_SCRIPTS = os.path.normpath(os.path.join(current_dir, '..', '..', '..', 'easy_process_sampler', 'scripts'))
if _SAMPLER_SCRIPTS not in sys.path:
    sys.path.insert(0, _SAMPLER_SCRIPTS)


FORMAT = '[%(asctime)s (line:%(lineno)d) %(levelname)s] %(message)s'
logging.basicConfig(level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S', format=FORMAT)

# TODO: 采集逻辑

if __name__ == "__main__":
    # 采集入口
    data = []
    print("-----BEGIN GATHERING DATA-----")
    print(json.dumps(data, indent=4))
    print("-----END GATHERING DATA-----")
```

## 输出格式规范

数据通过 stdout 输出，使用特殊标记包裹：

```python
print("-----BEGIN GATHERING DATA-----")
print(json.dumps(data, indent=4))
print("-----END GATHERING DATA-----")
```

### 单模型输出

```python
data = [
    {
        "dims": {
            "object_id": "MODEL_ID",    # 目标模型 ID
            "pks": ["主键字段名"],        # 主键字段，通常是 name
            "upsert": true               # 存在则更新，不存在则创建
        },
        "vals": {
            "name": "设备名称",
            "ip": "192.168.1.1",
            "field1": "value1",
            "field2": "value2"
        }
    }
]
```

### 采集对象（主模型）写入唯一键（重要规则）

资源采集的目标对象本身就是被采集的 CMDB 实例（由资源发现绑定），写入主模型时**必须用 `pks: ["instanceId"]`**，让平台直接定位到该实例更新。**不要**用 `name`、`ip`、`wwn` 等业务字段作为主键 —— 否则当业务字段变更时会产生重复实例或跨实例串写。

```python
{
    "dims": {
        "object_id": "采集对象模型ID",
        "pks": ["instanceId"],   # ← 采集对象固定写 instanceId
        "upsert": True
    },
    "vals": {
        # vals 里不需要写 instanceId
        "name": "业务名称",
        # ... 其他属性
    }
}
```

注意：

- `pks: ["instanceId"]` 是平台特殊约定，表示按当前采集实例的 instanceId 定位
- **仅采集对象（主模型）**用 `instanceId`；关联子模型仍用自己的业务主键（如 `wwpn` / `name`）
- 如果 `instanceId` 入参为空（如未通过资源发现绑定），脚本应中止采集并报错

### 多模型输出（主模型 + 关联模型）

**关系建立方式（重要）**：关系**写在子模型的 `vals` 里**，键 = 子模型 `relation_list` 中指向父模型的 `*_id` 字段名，值 = `[{"_object_id": "父模型ID", "instanceId": "<父实例ID>"}]`（数组，每个元素包含 `_object_id` 和 `instanceId`）。**不要在 dims 中使用 `set_relation_ids`** —— 那是旧用法，且方向常常搞错。

```python
data = [
    # 主模型数据（注意：dims 里没有 set_relation_ids）
    {
        "dims": {
            "object_id": "MAIN_MODEL_ID",
            "pks": ["instanceId"],
            "upsert": True
        },
        "vals": {
            "instanceId": instanceId,
            # ... 其他属性
        }
    },
    # 关联模型数据：通过 vals 中的关系字段指向父实例
    {
        "dims": {
            "object_id": "RELATED_MODEL_ID",
            "pks": ["name"],
            "upsert": True
        },
        "vals": {
            "name": "关联设备名称",
            "<relation_field>": [{"_object_id": "MAIN_MODEL_ID", "instanceId": "<父实例ID>"}],   # 关系字段，值为数组
            # ... 其他属性
        }
    }
]
```

**示例**：光纤交换机采集场景，父模型 `FIBERCHANNEL_SWITCH@ONEMODEL`，instanceId 由 `$.instanceId` 入参提供：

| 子模型                                | 父模型                            | 关系字段 (vals 的 key)   | 取值             |
| ------------------------------------- | --------------------------------- | ------------------------ | ---------------- |
| `FIBERCHANNEL_SWITCH_PORT@ONEMODEL` | `FIBER_CHANNEL_SWITCH@ONEMODEL` | `fiber_channel_switch` | `[{"_object_id": "FIBERCHANNEL_SWITCH@ONEMODEL", "instanceId": "..."}]` |
| `NETDPORT@ONEMODEL`                 | `BASE_NETWARE@ONEMODEL`         | `base_netware`         | `[{"_object_id": "FIBERCHANNEL_SWITCH@ONEMODEL", "instanceId": "..."}]` |
| `FIBERCHANNEL_CFG@ONEMODEL`         | `FIBER_CHANNEL_SWITCH@ONEMODEL` | `switchs`              | `[{"_object_id": "FIBERCHANNEL_SWITCH@ONEMODEL", "instanceId": "..."}]` |

**关系字段名怎么找**：通过 `scripts/get_model.py` 查目标模型的 `relation_list`：

- 找到子模型作为 `left_object_id` 的关系条目
- 取该条目的 `left_id`（即子模型方向的关系字段名）

例如查 `NETDPORT` 的 relation_list 中：

```
{
  "left_object_id": "NETDPORT@ONEMODEL",
  "left_id": "base_netware",         <-- 子模型 vals 用这个 key
  "right_object_id": "BASE_NETWARE@ONEMODEL",
  "right_id": "netdports"
}
```

### 关键字段说明

| 字段                | 说明               | 示例                                   |
| ------------------- | ------------------ | -------------------------------------- |
| `dims.object_id`  | 目标 CMDB 模型 ID  | `PHYSICAL_SERVER@ONEMODEL`           |
| `dims.pks`        | 主键字段名列表     | `["name"]`                           |
| `dims.upsert`     | 是否更新已存在实例 | `True`                               |
| `vals.<relation>` | 关系字段（数组）   | `"base_netware": ["<父instanceId>"]` |
| `vals`            | 模型属性键值对     | `{"name": "xxx", "ip": "x.x.x.x"}`   |

### structs 类型字段

如果模型属性是 structs（列表/结构体）类型，vals 中该字段的值为 JSON 数组：

```python
{
    "dims": { ... },
    "vals": {
        "networkInfo": [
            {"portName": "eth0", "macAddress": "xx:xx:xx:xx:xx:xx", "ipAddress": "10.0.0.1"},
            {"portName": "eth1", "macAddress": "yy:yy:yy:yy:yy:yy", "ipAddress": "10.0.0.2"}
        ]
    }
}
```

## 常见采集模式

### Redfish 采集模式

适用于通过 Redfish API 采集服务器硬件信息（Dell/HPE/Huawei/H3C 等）。

```python
import requests
from urlparse import urljoin

class RedfishCollector:
    """Redfish 采集器基类。"""

    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.base_url = 'https://{}'.format(ip)
        self.session = None

    def create_session(self):
        """创建 Redfish 会话。"""
        url = '{}/redfish/v1/SessionService/Sessions'.format(self.base_url)
        payload = {
            'UserName': self.username,
            'Password': self.password
        }
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code in (200, 201):
            token = resp.headers.get('X-Auth-Token')
            location = resp.headers.get('Location', '')
            self.session = requests.Session()
            self.session.headers.update({'X-Auth-Token': token})
            self.session.verify = False
            return True
        return False

    def get_uri(self, uri):
        """请求 Redfish URI。"""
        url = urljoin(self.base_url, uri)
        resp = self.session.get(url)
        if resp.status_code == 200:
            return resp.json()
        return None

    def get_members(self, uri):
        """获取集合的所有成员数据。"""
        data = self.get_uri(uri)
        if not data:
            return []
        members = data.get('Members', [])
        results = []
        for m in members:
            member_data = self.get_uri(m.get('@odata.id', ''))
            if member_data:
                results.append(member_data)
        return results

    def collect(self):
        """采集逻辑（子类实现）。"""
        raise NotImplementedError
```

### SNMP 采集模式

适用于通过 SNMP 协议采集网络设备/服务器信息。

```python
import subprocess
from collections import namedtuple

Result = namedtuple('Result', ['success', 'data', 'error'])


def parse_snmp_value(value_str):
    """解析 SNMP 返回值。"""
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
    return value_str


class SNMPClient:
    """SNMP 客户端。"""

    def __init__(self, ip, port=161, version='2c', community='public', timeout=10):
        self.ip = ip
        self.port = port
        self.version = version
        self.community = community
        self.timeout = timeout

    def get(self, oid):
        """SNMP GET 请求。"""
        cmd = ['snmpget', '-On', '-v', self.version, '-c', self.community,
               '{}:{}'.format(self.ip, self.port), oid]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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

    def walk(self, oid):
        """SNMP WALK 请求。"""
        cmd = ['snmpwalk', '-On', '-v', self.version, '-c', self.community,
               '{}:{}'.format(self.ip, self.port), oid]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            if proc.returncode == 0 and stdout:
                results = []
                for line in stdout.decode().split('\n'):
                    if '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) >= 2:
                            results.append(Result(True, parse_snmp_value(parts[1]), ""))
                return results
            return []
        except Exception as e:
            return [Result(False, None, str(e))]
```

### HTTP API 采集模式

适用于通过 REST API 采集资源信息。

```python
try:
    import urllib2
    from urllib2 import Request, urlopen, HTTPError, URLError
except ImportError:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

import base64

class APIClient:
    """HTTP API 客户端。"""

    def __init__(self, base_url, username=None, password=None, token=None):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = token

    def _get_headers(self):
        """构建请求头。"""
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer {}'.format(self.token)
        elif self.username and self.password:
            auth = base64.b64encode('{}:{}'.format(self.username, self.password).encode())
            headers['Authorization'] = 'Basic {}'.format(auth)
        return headers

    def get(self, path):
        """GET 请求。"""
        url = '{}/{}'.format(self.base_url, path.lstrip('/'))
        req = Request(url, headers=self._get_headers())
        try:
            response = urlopen(req, timeout=30)
            content = response.read().decode('utf-8')
            return json.loads(content)
        except HTTPError as e:
            logging.error('HTTP Error {}: {}'.format(e.code, e.reason))
            return None
        except Exception as e:
            logging.error('Request Error: {}'.format(str(e)))
            return None
```

## 品牌适配模式（策略模式）

当采集目标有多种品牌/型号且数据处理逻辑不同时，使用策略模式。

### OS 平台 vs 硬件 OEM 品牌（重要区分）

很多硬件厂商（IBM/Lenovo/Dell/EMC/NetApp 等）会 **OEM** 其他厂商的产品（如 Brocade FC 交换机、华为 OceanStor SNS 系列）。这些 OEM 设备：

- **底层 OS 是 Brocade Fabric OS** —— sysObjectID 落在 `1.3.6.1.4.1.1588`
- **硬件品牌不是 Brocade** —— 是 IBM / Lenovo / Dell 等

如果只按 sysObjectID 判断品牌，会把所有 OEM 设备都识别为 Brocade，丢失真实品牌。

**正确做法**：把"采集逻辑选择"与"品牌识别"解耦：

| 维度                   | 来源                                                                                               | 用途                                |
| ---------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------- |
| **OS 平台**      | sysObjectID 前缀 / sysDescr OS 关键词                                                              | 选择 Collector 类（决定用哪套 OID） |
| **OEM 硬件品牌** | connUnitVendor (FCMGMT-MIB) / entPhysicalMfgName (ENTITY-MIB chassis) / connUnitProduct / sysDescr | 写入 CMDB 的品牌字段                |

OEM 关键词识别表（按需扩展）：

```python
OEM_BRAND_KEYWORDS = [
    ("Lenovo",  ["LENOVO"]),
    ("IBM",     ["IBM"]),
    ("Dell",    ["DELL"]),
    ("EMC",     ["EMC", "DELL EMC"]),
    ("NetApp",  ["NETAPP"]),
    ("HPE",     ["HPE", "HEWLETT PACKARD"]),
    ("Cisco",   ["CISCO"]),
    ("H3C",     ["H3C"]),
    ("Huawei",  ["HUAWEI", "华为"]),
    ("Brocade", ["BROCADE"]),
    # ...
]
```

```python
class BrandAdapter(object):
    """品牌适配器基类。"""

    def __init__(self, raw_data):
        self.raw_data = raw_data

    def get_cpu_info(self):
        raise NotImplementedError

    def get_memory_info(self):
        raise NotImplementedError

    def get_disk_info(self):
        raise NotImplementedError


class DellAdapter(BrandAdapter):
    """Dell 品牌适配器。"""

    def get_cpu_info(self):
        # Dell 特定的 CPU 信息解析逻辑
        pass

    def get_memory_info(self):
        # Dell 特定的内存信息解析逻辑
        pass


class HPEAdapter(BrandAdapter):
    """HPE 品牌适配器。"""

    def get_cpu_info(self):
        # HPE 特定的 CPU 信息解析逻辑
        pass


def init_brand(manufacturer, raw_data):
    """根据制造商字段自动选择品牌适配器。"""
    manufacturer = (manufacturer or '').upper()
    if 'DELL' in manufacturer:
        return DellAdapter(raw_data)
    elif 'HPE' in manufacturer or 'HEWLETT' in manufacturer:
        return HPEAdapter(raw_data)
    else:
        return BrandAdapter(raw_data)
```

## 人工维护字段保护

CMDB 中的资产盘点字段（如 `brand` / `mdl` / `sn`）通常由人工录入维护，采集脚本不应覆盖这些字段。约定：

- **采集字段**：`c*` 前缀（如 `cBrand` / `cMdl` / `cSn`）— 采集自动同步
- **资产字段**：无前缀（`brand` / `mdl` / `sn`）— 人工维护，跳过

```python
HUMAN_MANAGED_FIELDS = {"brand", "mdl", "sn"}

def strip_human_managed_fields(vals):
    return {k: v for k, v in vals.items() if k not in HUMAN_MANAGED_FIELDS}

main_vals = strip_human_managed_fields(main_vals)
```

判断规则：模型属性中如果存在成对的 `xxx` 和 `cXxx`，则 `xxx` 是人工字段，`cXxx` 是采集字段。

## .orig 与 .py 文件区别

| 文件      | 说明       | 参数获取方式                                          |
| --------- | ---------- | ----------------------------------------------------- |
| `.orig` | 源码模板   | 不含环境变量代码，用于代码审查和 LLM 生成             |
| `.py`   | 运行时脚本 | 通过 `os.environ.get("EASYOPS_COLLECTOR_xxx")` 获取 |

### .orig 文件参数写法

`.orig` 文件中不应硬编码参数值。如果需要本地调试，使用环境变量带默认值：

```python
# .orig 文件中的参数调试写法
import os
ip = os.environ.get("EASYOPS_COLLECTOR_ip", "127.0.0.1")  # 默认值仅用于调试
```

### .py 文件参数写法

```python
# .py 文件中的参数获取（运行时）
import os
ip = os.environ.get("EASYOPS_COLLECTOR_ip")
```

## Python 2.7.18 兼容性注意事项

采集脚本运行环境为 **Python 2.7.18**，开发时需注意：

1. **字符串编码**：使用 `from __future__ import print_function`，`sys.setdefaultencoding('utf8')`
2. **HTTP 库**：使用 `urllib2`（非 `urllib.request`），使用 `from urlparse import urljoin`（非 `urllib.parse`）
3. **字典方法**：`dict.keys()` 返回列表而非视图，`dict.items()` 同理
4. **异常语法**：使用 `except Exception as e:`（兼容 Python 2.6+）
5. **类继承**：使用 `class Foo(object):` 新式类写法
6. **f-string**：不可用，使用 `.format()` 或 `%` 格式化
7. **类型注解**：不可用
