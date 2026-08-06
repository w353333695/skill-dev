# EasyOps 告警 Webhook 完整规范

## Webhook URL

```
POST http://{host}/api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{accessId}
```

### 参数说明

| 参数 | 说明 |
|-----|------|
| host | EasyOps 服务器地址 |
| org | 组织 ID |
| accessId | 事件接入 ID，在 EasyOps 控制台 > 事件中心 > 事件接入 创建 |

## 请求格式

### Headers

```
Content-Type: application/json
```

### Body

```json
{
    "alertId": "bbe540e74e2452511f8bb978544fe037729f9681",
    "alertDims": {
        "host": "192.168.100.163",
        "service": "nginx"
    },
    "metricName": "node.cpu.usage",
    "value": "59.18",
    "metricUnit": "%",
    "subject": "Instance 192.168.100.163 CPU usage high",
    "content": "192.168.100.163 CPU usage above 50% (current: 59.18%)",
    "time": 1587783926,
    "isRecover": false,
    "extInfo": {
        "alertInfo": {
            "labels": {
                "severity": "warning",
                "team": "ops"
            }
        }
    },
    "originInfo": {
        "raw_alert": "原始告警数据"
    },
    "source": "prometheus"
}
```

## 字段详解

### alertId (必填)

告警唯一标识符。相同 alertId 的告警会被视为同一告警事件。

生成建议：
```python
import hashlib

def generate_alert_id(source: str, host: str, metric: str) -> str:
    """生成告警 ID"""
    content = f"{source}:{host}:{metric}"
    return hashlib.md5(content.encode()).hexdigest()
```

### alertDims (可选)

告警维度，用于告警分组和资源关联。

```json
{
    "host": "192.168.100.163",
    "instance": "nginx",
    "region": "cn-north-1"
}
```

### time (必填)

告警时间戳，Unix 秒级时间戳。

```python
import time
alert_time = int(time.time())
```

### isRecover (必填)

是否为恢复告警：
- `false`: 告警触发
- `true`: 告警恢复

### extInfo (可选)

扩展信息，会填充到告警事件的 field 字段，可用于：
- 告警通知内容丰富
- 告警重定级规则匹配

```json
{
    "alertInfo": {
        "labels": {
            "severity": "critical",
            "team": "dba"
        }
    },
    "runbook_url": "https://wiki.example.com/runbook/cpu-high"
}
```

### originInfo (可选)

原始告警数据，用于：
- 调试和排查
- 资源关联规则取值

## 响应格式

### 成功

```json
{
    "code": 0,
    "message": "success"
}
```

### 失败

```json
{
    "code": 1,
    "message": "error message"
}
```

## curl 示例

```bash
curl -X POST \
  'http://192.168.100.162/api/gateway/alert_portal.webhook/api/v1/alert/common/8888/abc123' \
  -H 'Content-Type: application/json' \
  -d '{
    "alertId": "bbe540e74e2452511f8bb978544fe037729f9681",
    "metricName": "node.cpu.usage",
    "value": "59.18",
    "subject": "CPU usage high",
    "content": "CPU usage above 50%",
    "time": 1587783926,
    "isRecover": false,
    "source": "prometheus"
  }'
```

## 事件接入策略

推送告警后，需要在 EasyOps 控制台配置事件接入策略：

1. 过滤条件 - 筛选告警
2. 资源关联规则 - 关联 CMDB 资源
3. 告警重定级规则 - 重新定义告警级别

详见 EasyOps 文档。
