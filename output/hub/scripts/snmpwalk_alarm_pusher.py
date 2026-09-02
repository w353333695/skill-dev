#!/usr/bin/env python3
"""
SNMP Walk 告警采集 & EasyOps Webhook 推送脚本

通过 snmpwalk 轮询共济系统告警事件表，解析后推送到 EasyOps 三方告警接入。
一次性执行，适合 cron 定时调度。

依赖: pip install requests
系统依赖: snmpwalk (net-snmp)
"""

import hashlib
import json
import logging
import re
import subprocess
import time
from datetime import datetime

import requests

# ============================================================
# 配置区域 - 根据实际环境修改
# ============================================================

# SNMP 目标配置
SNMP_HOST = "192.168.1.100"          # 共济 SNMP 服务器地址
SNMP_PORT = 161                       # SNMP 端口
SNMP_VERSION = "2c"                   # SNMP 版本: 1, 2c, 3
SNMP_COMMUNITY = "public"             # SNMP v1/v2c 团体名

# SNMP v3 配置（仅 SNMP_VERSION=3 时生效）
SNMP_V3_USER = ""
SNMP_V3_AUTH_PROTO = "MD5"            # MD5 / SHA
SNMP_V3_AUTH_PASS = ""
SNMP_V3_PRIV_PROTO = "DES"           # DES / AES
SNMP_V3_PRIV_PASS = ""

# EasyOps Webhook 配置
EASYOPS_HOST = "192.168.1.200"       # EasyOps 服务器地址
EASYOPS_ORG = "8888"                  # 组织 ID
EASYOPS_ACCESS_ID = "your_access_id"  # 事件接入 ID
ALERT_SOURCE = "snmp-gongji"          # 告警源标识

# 请求配置
REQUEST_TIMEOUT = 30                  # HTTP 请求超时(秒)
MAX_RETRIES = 3                       # 推送重试次数
SNMP_TIMEOUT = 10                     # snmpwalk 超时(秒)

# 告警事件 OID 表
BASE_OID = "1.3.6.1.4.1.41475.1.1"
OID_FIELD_MAP = {
    "1": "resource_id",
    "2": "oid",
    "3": "device_tag",
    "4": "device_name",
    "5": "oid_name",
    "6": "event_level",
    "7": "event_snapshot",
    "8": "unit",
    "9": "alarm_type",
    "10": "alarm_time",
    "11": "alarm_recover_time",
    "12": "content",
}

WEBHOOK_URL = (
    f"http://{EASYOPS_HOST}/api/gateway/alert_portal.webhook"
    f"/api/v1/alert/common/{EASYOPS_ORG}/{EASYOPS_ACCESS_ID}"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def run_snmpwalk() -> str:
    """执行 snmpwalk 命令，返回原始输出"""
    if SNMP_VERSION == "3":
        cmd = [
            "snmpwalk", "-v3",
            "-u", SNMP_V3_USER,
            "-l", "authPriv",
            "-a", SNMP_V3_AUTH_PROTO, "-A", SNMP_V3_AUTH_PASS,
            "-x", SNMP_V3_PRIV_PROTO, "-X", SNMP_V3_PRIV_PASS,
            "-t", str(SNMP_TIMEOUT),
            f"{SNMP_HOST}:{SNMP_PORT}", BASE_OID,
        ]
    else:
        cmd = [
            "snmpwalk",
            f"-v{SNMP_VERSION}",
            "-c", SNMP_COMMUNITY,
            "-t", str(SNMP_TIMEOUT),
            f"{SNMP_HOST}:{SNMP_PORT}", BASE_OID,
        ]

    logger.info("执行: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        logger.error("snmpwalk 失败: %s", result.stderr.strip())
        raise RuntimeError(f"snmpwalk 执行失败: {result.stderr.strip()}")

    return result.stdout


def parse_snmpwalk_output(raw: str) -> list[dict]:
    """
    解析 snmpwalk 输出为告警记录列表。

    snmpwalk 输出格式示例:
      SNMPv2-SMI::enterprises.41475.1.1.1.1 = STRING: "sensor_001"
      SNMPv2-SMI::enterprises.41475.1.1.1.2 = STRING: "sensor_002"
      ...
    或数字 OID 格式:
      .1.3.6.1.4.1.41475.1.1.1.1 = STRING: "sensor_001"
    """
    # OID 匹配模式: 基础OID.字段号.行索引
    # 例: .1.3.6.1.4.1.41475.1.1.5.3 => 字段5(oid_name), 行3
    pattern = re.compile(
        r"(?:SNMPv2-SMI::enterprises\.41475\.1\.1|"
        r"\.?1\.3\.6\.1\.4\.1\.41475\.1\.1)"
        r"\.(\d+)\.(\d+)\s*=\s*\S+:\s*(.*)"
    )

    rows: dict[str, dict] = {}
    for line in raw.strip().splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        field_idx, row_idx, raw_val = m.group(1), m.group(2), m.group(3)
        field_name = OID_FIELD_MAP.get(field_idx)
        if not field_name:
            continue
        # 去除引号
        val = raw_val.strip().strip('"')
        rows.setdefault(row_idx, {})[field_name] = val

    alarms = list(rows.values())
    logger.info("解析到 %d 条告警记录", len(alarms))
    return alarms


def parse_alarm_time(time_str: str) -> int:
    """将告警时间字符串转为 Unix 时间戳(秒)"""
    if not time_str or time_str == "0":
        return int(time.time())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return int(datetime.strptime(time_str, fmt).timestamp())
        except ValueError:
            continue
    # 尝试直接作为时间戳
    try:
        ts = int(time_str)
        return ts // 1000 if ts > 1e12 else ts
    except ValueError:
        return int(time.time())


def generate_alert_id(alarm: dict) -> str:
    """基于稳定字段生成告警唯一 ID"""
    key = f"{ALERT_SOURCE}:{alarm.get('resource_id', '')}:{alarm.get('device_tag', '')}:{alarm.get('oid', '')}"
    return hashlib.md5(key.encode()).hexdigest()


def is_recover(alarm: dict) -> bool:
    """判断是否为恢复告警"""
    recover_time = alarm.get("alarm_recover_time", "").strip()
    return bool(recover_time and recover_time != "0")


def map_to_webhook(alarm: dict) -> dict:
    """将 SNMP 告警记录映射为 EasyOps Webhook 格式"""
    device_name = alarm.get("device_name", "未知设备")
    oid_name = alarm.get("oid_name", "未知信号")
    alarm_type = alarm.get("alarm_type", "")
    event_snapshot = alarm.get("event_snapshot", "")
    unit_str = alarm.get("unit", "")
    content = alarm.get("content", "")

    subject = f"[{device_name}] {oid_name} {alarm_type}".strip()
    detail = content if content else f"{oid_name} 当前值: {event_snapshot}{unit_str}"

    return {
        "alertId": generate_alert_id(alarm),
        "alertDims": {
            "device_tag": alarm.get("device_tag", ""),
            "resource_id": alarm.get("resource_id", ""),
        },
        "metricName": oid_name,
        "value": event_snapshot,
        "metricUnit": unit_str,
        "subject": subject,
        "content": detail,
        "time": parse_alarm_time(alarm.get("alarm_time", "")),
        "isRecover": is_recover(alarm),
        "extInfo": {
            "alertInfo": {
                "labels": {
                    "event_level": str(alarm.get("event_level", "")),
                    "alarm_type": alarm_type,
                }
            }
        },
        "originInfo": alarm,
        "source": ALERT_SOURCE,
    }


def push_to_webhook(payload: dict) -> bool:
    """推送单条告警到 EasyOps Webhook，带重试"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                WEBHOOK_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("推送成功: alertId=%s", payload["alertId"])
                return True
            logger.warning(
                "推送返回错误(第%d次): %s", attempt, data.get("message", "")
            )
        except Exception as e:
            logger.warning("推送异常(第%d次): %s", attempt, e)
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
    logger.error("推送失败，已达最大重试次数: alertId=%s", payload["alertId"])
    return False


def main():
    """主流程: snmpwalk -> 解析 -> 映射 -> 推送"""
    logger.info("===== 开始 SNMP 告警采集推送 =====")
    logger.info("目标: %s:%d, Webhook: %s", SNMP_HOST, SNMP_PORT, WEBHOOK_URL)

    # 1. 执行 snmpwalk
    raw_output = run_snmpwalk()
    if not raw_output.strip():
        logger.info("snmpwalk 无输出，无告警数据")
        return

    # 2. 解析告警
    alarms = parse_snmpwalk_output(raw_output)
    if not alarms:
        logger.info("未解析到告警记录")
        return

    # 3. 映射并推送
    success, fail = 0, 0
    for alarm in alarms:
        payload = map_to_webhook(alarm)
        logger.debug("推送数据: %s", json.dumps(payload, ensure_ascii=False))
        if push_to_webhook(payload):
            success += 1
        else:
            fail += 1

    logger.info("===== 完成: 共%d条, 成功%d, 失败%d =====", len(alarms), success, fail)


if __name__ == "__main__":
    main()


# ============================================================
# 使用示例
# ============================================================
#
# 1. 安装依赖:
#    pip install requests
#    # 确保系统已安装 net-snmp (snmpwalk 命令)
#    # macOS: brew install net-snmp
#    # CentOS: yum install net-snmp-utils
#    # Ubuntu: apt install snmp
#
# 2. 修改脚本顶部配置:
#    SNMP_HOST = "10.0.0.1"           # 共济 SNMP 服务器
#    SNMP_COMMUNITY = "public"         # 团体名
#    EASYOPS_HOST = "10.0.0.2"        # EasyOps 地址
#    EASYOPS_ORG = "8888"             # 组织 ID
#    EASYOPS_ACCESS_ID = "xxx"        # 事件接入 ID
#
# 3. 手动执行:
#    python3 snmpwalk_alarm_pusher.py
#
# 4. 定时执行 (cron):
#    */5 * * * * /usr/bin/python3 /path/to/snmpwalk_alarm_pusher.py >> /var/log/snmp_alarm.log 2>&1