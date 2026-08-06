#!/usr/bin/env python3
"""
Prometheus Alertmanager 告警接入示例

使用方法:
    python prometheus_alertmanager.py --host 172.30.0.90 --org 8888 --access-id abc123 --alertmanager-url http://alertmanager:9093

功能:
    从 Prometheus Alertmanager 获取活跃告警并推送到 EasyOps
"""

import requests
import json
import logging
import argparse
import time
from datetime import datetime
from functools import wraps
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SOURCE = "prometheus"


def retry(times=3, delay=1, backoff=2):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            current_delay = delay
            while attempt < times:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= times:
                        logger.error(f"重试{times}次后仍然失败: {e}")
                        raise
                    logger.warning(f"第{attempt}次尝试失败,{current_delay}秒后重试: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator


def parse_time(time_str: str) -> int:
    """解析 ISO 8601 时间为 Unix 时间戳"""
    if not time_str:
        return int(time.time())
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


@retry()
def fetch_alerts(alertmanager_url: str) -> List[Dict]:
    """从 Alertmanager 获取告警"""
    url = f"{alertmanager_url.rstrip('/')}/api/v2/alerts"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def transform_alert(alert: Dict) -> Dict:
    """转换 Prometheus 告警为 EasyOps 格式"""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    return {
        "alertId": alert.get("fingerprint"),
        "alertDims": labels,
        "metricName": labels.get("alertname", ""),
        "value": annotations.get("value", ""),
        "metricUnit": "",
        "subject": annotations.get("summary", labels.get("alertname", "")),
        "content": annotations.get("description", ""),
        "time": parse_time(alert.get("startsAt")),
        "isRecover": alert.get("status", {}).get("state") == "resolved",
        "extInfo": {
            "alertInfo": {
                "labels": labels,
                "annotations": annotations
            }
        },
        "originInfo": alert,
        "source": SOURCE
    }


@retry()
def push_to_webhook(host: str, org: str, access_id: str, alert: Dict) -> bool:
    """推送告警到 EasyOps webhook"""
    url = f"http://{host}/api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{access_id}"
    headers = {"Content-Type": "application/json"}

    response = requests.post(url, headers=headers, data=json.dumps(alert), timeout=30)
    response.raise_for_status()

    result = response.json()
    if result.get("code") != 0:
        logger.error(f"推送失败: {result.get('message')}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='Prometheus Alertmanager 告警接入')
    parser.add_argument('--host', type=str, required=True, help='EasyOps 服务器地址')
    parser.add_argument('--org', type=str, required=True, help='组织 ID')
    parser.add_argument('--access-id', type=str, required=True, help='事件接入 ID')
    parser.add_argument('--alertmanager-url', type=str, required=True, help='Alertmanager 地址')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    # 获取告警
    logger.info(f"从 {args.alertmanager_url} 获取告警...")
    alerts = fetch_alerts(args.alertmanager_url)
    logger.info(f"获取到 {len(alerts)} 条告警")

    # 转换并推送
    success_count = 0
    fail_count = 0

    for alert in alerts:
        try:
            transformed = transform_alert(alert)
            if push_to_webhook(args.host, args.org, args.access_id, transformed):
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            logger.error(f"处理告警失败: {e}")

    logger.info(f"推送完成: 成功 {success_count}, 失败 {fail_count}")


if __name__ == "__main__":
    main()
