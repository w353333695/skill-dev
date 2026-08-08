# 告警字段映射指南

## 常见三方告警系统字段映射

### Prometheus Alertmanager

```python
def map_prometheus_alert(alert: dict) -> dict:
    """Prometheus 告警映射"""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    return {
        "alertId": alert.get("fingerprint"),
        "alertDims": labels,
        "metricName": labels.get("alertname"),
        "value": annotations.get("value", ""),
        "subject": annotations.get("summary", labels.get("alertname")),
        "content": annotations.get("description", ""),
        "time": parse_time(alert.get("startsAt")),
        "isRecover": alert.get("status") == "resolved",
        "extInfo": {"alertInfo": {"labels": labels}},
        "originInfo": alert,
        "source": "prometheus"
    }
```

### Zabbix

```python
def map_zabbix_alert(alert: dict) -> dict:
    """Zabbix 告警映射"""
    return {
        "alertId": f"zabbix_{alert.get('eventid')}",
        "alertDims": {"host": alert.get("host")},
        "metricName": alert.get("name"),
        "value": alert.get("value", ""),
        "subject": alert.get("subject"),
        "content": alert.get("message"),
        "time": int(alert.get("clock", time.time())),
        "isRecover": alert.get("value") == "0",
        "extInfo": {"severity": alert.get("severity")},
        "originInfo": alert,
        "source": "zabbix"
    }
```

### 云厂商告警

```python
def map_cloud_alert(alert: dict, cloud: str) -> dict:
    """云厂商告警映射"""
    return {
        "alertId": alert.get("alarm_id") or alert.get("AlarmId"),
        "alertDims": {
            "instance_id": alert.get("instance_id"),
            "region": alert.get("region")
        },
        "metricName": alert.get("metric_name"),
        "value": str(alert.get("current_value", "")),
        "subject": alert.get("alarm_name"),
        "content": alert.get("alarm_description"),
        "time": parse_cloud_time(alert.get("alarm_time")),
        "isRecover": alert.get("alarm_status") in ["ok", "resolved"],
        "extInfo": {},
        "originInfo": alert,
        "source": cloud
    }
```

## 字段映射最佳实践

### alertId 生成

确保唯一性，推荐方式：

```python
import hashlib

def generate_alert_id(source: str, *keys) -> str:
    """
    生成告警 ID
    使用告警源 + 关键字段生成唯一 ID
    """
    content = ":".join([source] + [str(k) for k in keys])
    return hashlib.md5(content.encode()).hexdigest()

# 示例
alert_id = generate_alert_id("prometheus", host, alertname, instance)
```

### 时间戳转换

```python
from datetime import datetime

def parse_time(time_str: str) -> int:
    """解析各种时间格式为 Unix 时间戳"""
    if not time_str:
        return int(time.time())

    # ISO 8601 格式
    if "T" in time_str:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return int(dt.timestamp())

    # Unix 毫秒时间戳
    if len(time_str) == 13 and time_str.isdigit():
        return int(time_str) // 1000

    # Unix 秒时间戳
    if time_str.isdigit():
        return int(time_str)

    return int(time.time())
```

### 告警级别映射

```python
SEVERITY_MAP = {
    # Prometheus
    "critical": "critical",
    "warning": "warning",
    "info": "info",
    # Zabbix (0-5)
    "5": "critical",
    "4": "major",
    "3": "warning",
    "2": "minor",
    "1": "info",
    "0": "info",
    # 云厂商
    "ALARM": "critical",
    "WARN": "warning",
    "OK": "info"
}

def map_severity(severity: str) -> str:
    return SEVERITY_MAP.get(str(severity).lower(), "warning")
```

## 常见问题

### 告警去重

使用稳定的 alertId 确保相同告警不会重复：

```python
# 好的做法 - 使用稳定字段
alert_id = generate_alert_id(source, host, metric, instance)

# 不好的做法 - 使用时间戳
alert_id = f"{source}_{time.time()}"  # 每次都不同
```

### 恢复告警

确保恢复告警的 alertId 与触发告警一致：

```python
# 触发告警
{"alertId": "abc123", "isRecover": false, ...}

# 恢复告警 - alertId 必须相同
{"alertId": "abc123", "isRecover": true, ...}
```
