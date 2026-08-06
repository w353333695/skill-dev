#!/usr/bin/env python3
"""
告警推送脚本模板

使用方法:
    1. 修改配置区域的参数
    2. 直接运行: python webhook_pusher.py

生成脚本时，根据实际需求修改:
1. AlertClient.fetch_alerts() - 三方告警 API 调用逻辑
2. AlertClient.transform() - 告警转换逻辑
"""

import requests
import json
import logging
import time
import hashlib
from functools import wraps
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ 配置区域 - 根据实际情况修改 ============
# EasyOps 配置
HOST = "172.30.0.90"      # EasyOps 服务器地址
ORG = "8888"              # 组织 ID
ACCESS_ID = "abc123"      # 事件接入 ID
SOURCE = "third_party"    # 告警源标识

# 三方告警 API 配置
ALERT_API_URL = "https://api.example.com/alerts"  # 三方告警 API 地址
ALERT_API_KEY = ""        # 三方 API 密钥（如需要）
# ====================================================


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


class AlertClient:
    """三方告警 API 客户端 - 根据实际 API 修改"""

    def __init__(self, api_url: str, api_key: str = None, source: str = "third_party"):
        self.api_url = api_url
        self.source = source
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    @retry()
    def fetch_alerts(self) -> List[Dict]:
        """
        从三方 API 获取告警
        根据实际 API 修改此方法
        """
        response = requests.get(self.api_url, headers=self.headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result.get("alerts", [])

    def _generate_alert_id(self, *keys) -> str:
        """生成告警唯一 ID"""
        content = ":".join([self.source] + [str(k) for k in keys])
        return hashlib.md5(content.encode()).hexdigest()

    def transform(self, alert: Dict) -> Dict:
        """
        转换告警为 EasyOps webhook 格式
        根据实际告警结构修改此方法
        """
        return {
            "alertId": self._generate_alert_id(
                alert.get("host"),
                alert.get("metric")
            ),
            "alertDims": {
                "host": alert.get("host")
            },
            "metricName": alert.get("metric"),
            "value": str(alert.get("value", "")),
            "metricUnit": alert.get("unit", ""),
            "subject": alert.get("title", ""),
            "content": alert.get("description", ""),
            "time": int(alert.get("timestamp", time.time())),
            "isRecover": alert.get("status") == "resolved",
            "extInfo": {
                "severity": alert.get("severity")
            },
            "originInfo": alert,
            "source": self.source
        }


class WebhookClient:
    """EasyOps Webhook 客户端"""

    def __init__(self, host: str, org: str, access_id: str):
        self.host = host
        self.org = org
        self.access_id = access_id
        self.url = f"http://{host}/api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{access_id}"

    @retry()
    def push(self, alert: Dict) -> bool:
        """推送告警到 EasyOps webhook"""
        headers = {"Content-Type": "application/json"}
        response = requests.post(
            self.url,
            headers=headers,
            data=json.dumps(alert),
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        if result.get("code") != 0:
            logger.error(f"推送失败: {result.get('message')}")
            return False
        return True


class AlertPusher:
    """告警推送器"""

    def __init__(self, alert_client: AlertClient, webhook: WebhookClient):
        self.alert_client = alert_client
        self.webhook = webhook

    def run(self) -> Dict:
        """执行告警推送"""
        # 1. 获取三方告警
        logger.info("从三方 API 获取告警...")
        alerts = self.alert_client.fetch_alerts()
        logger.info(f"获取到 {len(alerts)} 条告警")

        # 2. 转换并推送
        success_count = 0
        fail_count = 0

        for alert in alerts:
            try:
                transformed = self.alert_client.transform(alert)
                if self.webhook.push(transformed):
                    success_count += 1
                    logger.debug(f"推送成功: {transformed['alertId']}")
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                logger.error(f"处理告警失败: {e}")

        logger.info(f"推送完成: 成功 {success_count}, 失败 {fail_count}")
        return {"success": success_count, "failed": fail_count}

    def push_single(self, alert: Dict) -> bool:
        """推送单条告警"""
        transformed = self.alert_client.transform(alert)
        return self.webhook.push(transformed)


if __name__ == "__main__":
    # ============ 使用示例 ============

    # 创建客户端
    alert_client = AlertClient(ALERT_API_URL, ALERT_API_KEY, SOURCE)
    webhook = WebhookClient(HOST, ORG, ACCESS_ID)
    pusher = AlertPusher(alert_client, webhook)

    # 执行推送
    result = pusher.run()
    print(f"推送结果: {result}")

    # 也可以单独推送一条告警:
    # alert = {"host": "192.168.1.1", "metric": "cpu", "value": 90, "title": "CPU高"}
    # pusher.push_single(alert)
