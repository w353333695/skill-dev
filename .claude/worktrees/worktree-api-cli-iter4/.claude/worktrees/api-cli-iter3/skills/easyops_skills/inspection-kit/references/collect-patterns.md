# 巡检采集脚本模式

## 命令行采集 + 正则解析

适用于通过 shell 命令获取数据的场景。

```python
#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json
import re
import subprocess
import platform

def exec_cmd(command, user=None):
    """执行命令并返回结果"""
    if user:
        command = 'su - {} -c "{}" '.format(user, command)
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    return process.returncode, output, error

def parse_with_regex(output, pattern):
    """使用正则解析输出"""
    matches = re.finditer(pattern, output, re.S)
    return [m.groupdict() for m in matches]

# 示例：解析 dspmq 输出
code, output, err = exec_cmd("dspmq")
pattern = r'QMNAME\((?P<QMNAME>.*?)\)\s*STATUS\((?P<STATUS>.*?)\)'
results = parse_with_regex(output, pattern)

# 转换为巡检输出格式
result = []
for item in results:
    result.append({
        "id": "queue_status",
        "dims": [{"id": "QMNAME", "value": item["QMNAME"]}],
        "vals": [{"id": "STATUS", "value": item["STATUS"]}]
    })

print "-------start-------"
print json.dumps(result)
print "-------end-------"
```

## API 调用采集

适用于通过 HTTP API 获取数据的场景。

```python
#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json
import requests

def call_api(url, method="GET", headers=None, data=None):
    """调用 API"""
    resp = requests.request(method, url, headers=headers, json=data, timeout=30)
    return resp.json()

# 示例：调用管理 API
api_url = "http://localhost:8080/api/status"
data = call_api(api_url)

result = [{
    "id": "api_status",
    "dims": [],
    "vals": [
        {"id": "status", "value": data.get("status", "unknown")},
        {"id": "uptime", "value": data.get("uptime", 0)}
    ]
}]

print "-------start-------"
print json.dumps(result)
print "-------end-------"
```

## 配置文件解析

适用于读取并解析配置文件的场景。

```python
#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json
import re
import os

def parse_config(filepath):
    """解析配置文件"""
    config = {}
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config

# 示例：解析配置文件
config = parse_config("/etc/myapp/config.conf")

result = [{
    "id": "config_check",
    "dims": [],
    "vals": [
        {"id": "max_connections", "value": int(config.get("max_connections", 0))},
        {"id": "timeout", "value": int(config.get("timeout", 0))}
    ]
}]

print "-------start-------"
print json.dumps(result)
print "-------end-------"
```

## 多指标组采集

一个脚本采集多个指标组。

```python
#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json

class Inspector:
    def __init__(self):
        self.result = []

    def collect_basic_info(self):
        """采集基本信息"""
        # 采集逻辑...
        self.result.append({
            "id": "basic",
            "dims": [],
            "vals": [
                {"id": "version", "value": "1.0.0"},
                {"id": "status", "value": "running"}
            ]
        })

    def collect_performance(self):
        """采集性能指标"""
        # 采集逻辑...
        self.result.append({
            "id": "performance",
            "dims": [],
            "vals": [
                {"id": "cpu_usage", "value": 50.5},
                {"id": "memory_usage", "value": 1024}
            ]
        })

    def print_result(self):
        print "-------start-------"
        print json.dumps(self.result)
        print "-------end-------"

if __name__ == '__main__':
    inspector = Inspector()
    inspector.collect_basic_info()
    inspector.collect_performance()
    inspector.print_result()
```

## 带维度的多行数据采集

采集多行数据，每行有不同维度值。

```python
#!/usr/local/easyops/python/bin/python
# coding:utf-8
import json
import subprocess
import re

def exec_cmd(cmd):
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return p.returncode, out, err

# 采集多个队列的深度
code, output, err = exec_cmd('echo "dis ql(*) curdepth"|runmqsc QMGR1')
pattern = r'QUEUE\((?P<QUEUE>.*?)\).*?TYPE\((?P<TYPE>.*?)\).*?CURDEPTH\((?P<CURDEPTH>\d*?)\)'
matches = re.finditer(pattern, output, re.S)

result = []
for m in matches:
    d = m.groupdict()
    result.append({
        "id": "queue_depth",
        "dims": [
            {"id": "QUEUE", "value": d["QUEUE"]},
            {"id": "TYPE", "value": d["TYPE"]}
        ],
        "vals": [
            {"id": "CURDEPTH", "value": int(d["CURDEPTH"])}
        ]
    })

print "-------start-------"
print json.dumps(result)
print "-------end-------"
```
