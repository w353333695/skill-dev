"""
SSO 单点登录测试工具

支持 OAuth2 协议，代码结构可扩展其他协议（SAML、CAS 等）。
启动后访问 http://localhost:5000 即可发起 OAuth2 登录流程。

用法:
    python sso_tester.py
"""

import abc
import os
import secrets
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from flask import Flask, redirect, request, jsonify, session

# ---------------------------------------------------------------------------
# 通用数据模型
# ---------------------------------------------------------------------------

@dataclass
class SSOConfig:
    """SSO 通用配置基类"""
    redirect_uri: str = ""


@dataclass
class UserInfo:
    """统一用户信息"""
    raw: Dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    username: str = ""
    email: str = ""
    display_name: str = ""

    def summary(self) -> Dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
        }


# ---------------------------------------------------------------------------
# 协议抽象层 —— 新协议只需继承 SSOProtocol 并实现各方法
# ---------------------------------------------------------------------------

class SSOProtocol(abc.ABC):
    """SSO 协议抽象基类"""

    @abc.abstractmethod
    def build_authorize_url(self, state: str) -> str:
        """构造授权跳转 URL"""

    @abc.abstractmethod
    def exchange_token(self, code: str) -> Dict[str, Any]:
        """用授权码换取 token"""

    @abc.abstractmethod
    def fetch_user_info(self, access_token: str) -> UserInfo:
        """用 access_token 获取用户信息"""

    @property
    @abc.abstractmethod
    def protocol_name(self) -> str:
        """协议名称"""


# ---------------------------------------------------------------------------
# OAuth2 实现
# ---------------------------------------------------------------------------

@dataclass
class OAuth2Config(SSOConfig):
    """OAuth2 配置"""
    authorize_url: str = ""
    access_token_url: str = ""
    user_info_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scope: str = "read"


class OAuth2Protocol(SSOProtocol):
    """OAuth2 Authorization Code 流程"""

    def __init__(self, config: OAuth2Config):
        self.config = config

    @property
    def protocol_name(self) -> str:
        return "OAuth2"

    def build_authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": self.config.scope,
            "state": state,
        }
        sep = "&" if "?" in self.config.authorize_url else "?"
        return self.config.authorize_url + sep + urllib.parse.urlencode(params)

    def exchange_token(self, code: str) -> Dict[str, Any]:
        resp = requests.post(
            self.config.access_token_url,
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")
        return resp.json()

    def fetch_user_info(self, access_token: str) -> UserInfo:
        resp = requests.get(
            self.config.user_info_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        return UserInfo(
            raw=data,
            user_id=str(data.get("sub", data.get("user_id", ""))),
            username=data.get("username", data.get("preferred_username", "")),
            email=data.get("email", ""),
            display_name=data.get("name", data.get("nickname", "")),
        )


# ---------------------------------------------------------------------------
# 扩展示例（占位）—— SAML / CAS 只需实现 SSOProtocol
# ---------------------------------------------------------------------------

# class SAMLProtocol(SSOProtocol):
#     ...
#
# class CASProtocol(SSOProtocol):
#     ...


# ---------------------------------------------------------------------------
# SSO 测试器主类
# ---------------------------------------------------------------------------

class SSOTester:
    """SSO 测试器：管理协议实例，提供 Flask 路由"""

    def __init__(self, protocol: SSOProtocol, port: int = 5000):
        self.protocol = protocol
        self.port = port
        # state -> 用途 映射（防 CSRF）
        self._states: Dict[str, str] = {}

        self.app = Flask(__name__)
        self.app.secret_key = secrets.token_hex(32)
        self._register_routes()

    # ---- 路由 ----

    def _register_routes(self):
        self.app.add_url_rule("/", "index", self._handle_index)
        self.app.add_url_rule("/login", "login", self._handle_login, methods=["GET"])
        self.app.add_url_rule("/callback", "callback", self._handle_callback, methods=["GET"])
        self.app.add_url_rule("/result", "result", self._handle_result)

    def _handle_index(self):
        """首页：展示协议信息和登录入口"""
        html = f"""
        <h1>SSO 单点登录测试</h1>
        <p>当前协议: <b>{self.protocol.protocol_name}</b></p>
        <a href="/login">发起登录</a>
        """
        return html

    def _handle_login(self):
        """发起 OAuth2 授权"""
        state = secrets.token_urlsafe(32)
        self._states[state] = "login"
        authorize_url = self.protocol.build_authorize_url(state)
        return redirect(authorize_url)

    def _handle_callback(self):
        """授权回调：用 code 换 token，再获取用户信息"""
        # 校验 state
        state = request.args.get("state", "")
        if state not in self._states:
            return jsonify({"error": "invalid_state", "message": "state 校验失败"}), 400

        code = request.args.get("code")
        if not code:
            error = request.args.get("error", "unknown")
            error_desc = request.args.get("error_description", "")
            return jsonify({"error": error, "message": error_desc}), 400

        # 1) 换取 token
        try:
            token_data = self.protocol.exchange_token(code)
        except Exception as e:
            return jsonify({"step": "exchange_token", "error": str(e)}), 502

        access_token = token_data.get("access_token", "")
        if not access_token:
            return jsonify({"step": "exchange_token", "raw": token_data}), 502

        # 2) 获取用户信息
        try:
            user_info = self.protocol.fetch_user_info(access_token)
        except Exception as e:
            return jsonify({"step": "fetch_user_info", "error": str(e), "token": token_data}), 502

        # 保存到 session，跳转结果页
        session["user_info"] = user_info.summary()
        session["user_raw"] = user_info.raw
        session["token_data"] = token_data
        return redirect("/result")

    def _handle_result(self):
        """展示登录结果"""
        user_info = session.get("user_info")
        if not user_info:
            return redirect("/")

        token_data = session.get("token_data", {})
        user_raw = session.get("user_raw", {})

        html = f"""
        <h1>登录成功</h1>
        <h2>用户信息</h2>
        <pre>{_json_html(user_info)}</pre>
        <h2>原始用户数据</h2>
        <pre>{_json_html(user_raw)}</pre>
        <h2>Token 数据</h2>
        <pre>{_json_html(token_data)}</pre>
        <hr>
        <a href="/login">再次登录</a> | <a href="/">返回首页</a>
        """
        return html

    def run(self, debug: bool = True):
        print(f"SSO 测试器启动，协议: {self.protocol.protocol_name}")
        print(f"请访问 http://localhost:{self.port}")
        self.app.run(port=self.port, debug=debug)


def _json_html(obj) -> str:
    """简单 JSON 转 HTML 安全文本"""
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def create_tester() -> SSOTester:
    """根据配置创建 SSOTester（可在此处切换协议）"""

    oauth2_config = OAuth2Config(
        authorize_url="http://172.30.0.90/next/auth/authorization",
        access_token_url="http://172.30.0.90/api/v1/api_gateway/sso_server/oauth2/access_token",
        user_info_url="http://172.30.0.90/api/v1/api_gateway/sso_server/oauth2/user_info",
        # redirect_uri="http://localhost:5001/callback",
        redirect_uri="http://172.30.0.148/next/sso-auth/authorize",
        client_id="098f6bcd4621d373cade",
        client_secret="J993i8eKL1atvp1R4OBVmsm5cgnS1QO9cJ_fO-8jCqBscqZ6L5OPmCaxaUIwzvVH",
    )

    protocol = OAuth2Protocol(oauth2_config)
    return SSOTester(protocol, port=5001)


if __name__ == "__main__":
    tester = create_tester()
    tester.run()
