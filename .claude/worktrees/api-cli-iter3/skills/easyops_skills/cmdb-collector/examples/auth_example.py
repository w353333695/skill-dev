"""
多认证模式示例

当 API 文档定义了多种认证模式时，采集脚本必须全部支持。
配置区域定义 AUTH_TYPE 变量，用户可选择认证方式。
"""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Dict

# ============ 配置区域 ============
AUTH_TYPE = "basic"  # 可选: basic, aksk, token
USERNAME = ""        # Basic 认证
PASSWORD = ""
ACCESS_KEY = ""      # AK/SK 认证
SECRET_KEY = ""
API_TOKEN = ""       # Token 认证
# ==================================


class APIClient:
    def __init__(self, auth_type: str, **kwargs):
        self.auth_type = auth_type
        self.username = kwargs.get("username", "")
        self.password = kwargs.get("password", "")
        self.access_key = kwargs.get("access_key", "")
        self.secret_key = kwargs.get("secret_key", "")
        self.api_token = kwargs.get("api_token", "")

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}

        if self.auth_type == "basic":
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        elif self.auth_type == "aksk":
            # 实现 HMAC 签名
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            string_to_sign = f"{method}\n{path}\n{timestamp}"
            signature = base64.b64encode(
                hmac.new(self.secret_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
            ).decode()
            headers["Authorization"] = f"HMAC {self.access_key}:{signature}"
            headers["X-Date"] = timestamp
        elif self.auth_type == "token":
            headers["Authorization"] = f"Bearer {self.api_token}"

        return headers
