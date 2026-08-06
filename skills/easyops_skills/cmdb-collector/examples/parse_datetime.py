"""
日期时间格式转换工具函数

CMDB 要求的格式：
- date 类型：YYYY-MM-DD（如 2024-01-15）
- datetime 类型：YYYY-MM-DD HH:MM:SS（如 2024-01-15 10:30:00）

采集脚本必须包含以下函数处理三方系统的日期格式转换。
"""

from datetime import datetime, timezone
from typing import Optional, Union


def parse_datetime(value: Union[str, int, None]) -> Optional[str]:
    """
    将各种日期时间格式转换为 CMDB 格式 (YYYY-MM-DD HH:MM:SS)

    支持格式：
    - ISO 8601: 2024-01-15T10:30:00Z, 2024-01-15T10:30:00.000+08:00
    - Unix 时间戳（秒或毫秒）
    - 常见字符串格式
    """
    if value is None or value == "":
        return None

    # Unix 时间戳（秒或毫秒）
    if isinstance(value, (int, float)):
        if value > 1e12:  # 毫秒
            value = value / 1000
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    if not isinstance(value, str):
        return None

    # 尝试多种格式解析
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",      # ISO 8601 with ms and Z
        "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 with Z
        "%Y-%m-%dT%H:%M:%S.%f%z",      # ISO 8601 with ms and timezone
        "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601 with timezone
        "%Y-%m-%dT%H:%M:%S.%f",        # ISO 8601 with ms
        "%Y-%m-%dT%H:%M:%S",           # ISO 8601 basic
        "%Y-%m-%d %H:%M:%S",           # Standard format
        "%Y/%m/%d %H:%M:%S",           # Slash format
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value.replace("+00:00", "Z").replace("+08:00", ""), fmt.replace("%z", ""))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    # 如果都失败，返回原值（可能已经是正确格式）
    return value


def parse_date(value: Union[str, int, None]) -> Optional[str]:
    """
    将各种日期格式转换为 CMDB 格式 (YYYY-MM-DD)
    """
    if value is None or value == "":
        return None

    # 先尝试解析为 datetime，再取日期部分
    dt_str = parse_datetime(value)
    if dt_str and len(dt_str) >= 10:
        return dt_str[:10]

    return value
