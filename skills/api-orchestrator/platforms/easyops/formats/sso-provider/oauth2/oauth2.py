# -*- coding: utf-8 -*-
# stdlib
from urllib import urlencode

# 3rd party
import requests
from jsonschema import validate

# project
from settings.setting import PLUGIN_CONFIG
from handlers.providers.base_provider import Provider
from utils.tools import uuid, b2s


class oauth2(Provider):
    _pre_signin_schema = {
        "type": "object",
        "properties": {
            "response_type": {"type": "string"},
            "client_id": {"type": "string"},
            "redirect_uri": {"type": "string"},
            "access_type": {"type": "string"},
        },
        "required": ["response_type", "client_id", "redirect_uri", "access_type"],
    }

    _signin_schema = {
        "type": "object",
        "properties": {
            "grant_type": {"type": "string"},
            "client_id": {"type": "string"},
            "client_secret": {"type": "string"},
            "redirect_uri": {"type": "string"},
        },
        "required": ["grant_type", "client_id", "client_secret", "redirect_uri"]
    }

    _authorization_info_online_schema = {
        "type": "object",
        "properties": {
            "access_token": {"type": "string"},
            "refresh_token": {"type": "string"},
            "token_type": {"type": "string"},
            "expires_in": {"type": "number"},
        },
        "required": ["token_type", "access_token", "refresh_token", "expires_in"]
    }

    _authorization_info_offline_schema = {
        "type": "object",
        "properties": {
            "access_token": {"type": "string"},
            "refresh_token": {"type": "string"},
            "token_type": {"type": "string"},
            "expires_in": {"type": "number"},
        },
        "required": ["token_type", "refresh_token"]
    }

    def __init__(self):
        Provider.__init__(self)
        self._config = PLUGIN_CONFIG.get("oauth2")
        if self._config is None:
            raise Exception(u"导入oauth2模块异常, setting.py中PLUGIN_CONFIG.oauth2配置不存在")

        config_schema = {
            "type": "object",
            "properties": {
                "login_url": {"type": "string"},
                "authorization_url": {"type": "string"},
                "access_type": {"type": "string"},
                "user_info_url": {"type": "string"},
            },
            "required": ["login_url", "authorization_url", "access_type", "user_info_url"]
        }
        try:
            validate(instance=self._config, schema=config_schema)
        except Exception as e:
            raise Exception(u"导入oauth2模块异常, setting.py中PLUGIN_CONFIG.oauth2格式非法: %s" % b2s(e.message))

    def pre_signin(self, params):
        url = self._config["login_url"]
        uri_params = {}
        # required params
        self.pre_signin_required_params(uri_params=uri_params)
        # config scope and state
        self.pre_signin_scope(uri_params=uri_params)
        self.pre_signin_state(uri_params=uri_params)

        return url + "?" + urlencode(uri_params)

    def pre_signin_required_params(self, uri_params):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        try:
            validate(instance=self._config, schema=self._pre_signin_schema)
        except Exception as e:
            raise Exception(u"oauth2.pre_signin_required_params()异常: %s" % b2s(e.message))

        uri_params["response_type"] = self._config["response_type"]
        uri_params["authorization_url"] = self._config["authorization_url"]
        uri_params["client_id"] = self._config["client_id"]
        uri_params["access_type"] = self._config["access_type"]
        uri_params["redirect_uri"] = self._config["redirect_uri"]

    def pre_signin_scope(self, uri_params):
        if self._config.get("scope") is None:
            return

        uri_params["scope"] = self._config["scope"]

    def pre_signin_state(self, uri_params):
        u"""如果你需要自定义state, 你需要重写这个方法"""
        uri_params["state"] = uuid()

    def signin(self, params):
        # parse state
        self.signin_state(state=params.get("state"))
        # 通过code获取访问凭证
        authorization_info = self.signin_authorization(params.get("code"))

        return authorization_info

    def signin_state(self, state):
        u"""如果逻辑中需要解析state, 你需要重写这个方法"""
        pass

    def signin_authorization(self, code):
        # url
        url = self._config["authorization_url"]
        # url params
        params = self.signin_authorization_params(code)
        # method
        method = self.signin_authorization_method()
        method = method.upper()
        # headers
        headers = self.signin_authorization_headers(code)
        kwargs = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
        }
        # body
        if method in ["POST", "PUT"]:
            body = self.signin_authorization_body(code)
            if body is not None:
                kwargs["data"] = body

        # authorization
        resp = requests.request(**kwargs)

        return self.signin_parse_response(resp)

    def signin_authorization_params(self, code):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        params = {}
        try:
            validate(instance=self._config, schema=self._signin_schema)
        except Exception as e:
            raise Exception(u"oauth2.signin_authorization_required_params()异常: %s" % b2s(e.message))

        params["code"] = code
        params["grant_type"] = self._config["grant_type"]
        params["client_id"] = self._config["client_id"]
        params["client_secret"] = self._config["client_secret"]
        params["redirect_uri"] = self._config["redirect_uri"]

        return params

    def signin_authorization_method(self):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        return "POST"

    def signin_authorization_headers(self, code):
        u"""如果你要自定义headers, 你需要重写这个方法"""
        return {"Content-Type": "application/x-www-form-urlencoded"}

    def signin_authorization_body(self, code):
        u"""如果你需要自定义OAuth2认证的请求体, 你需要重写这个方法"""
        return None

    def signin_parse_response(self, resp):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        status_code = resp.status_code
        if status_code < 200 or status_code >= 400:
            raise Exception(u"oauth2.signin_authorization()认证请求失败: [%d]%s" % (status_code, b2s(resp.text)))

        return resp.json()

    def user_info(self, authorization_info=None):
        access_type = self._config["access_type"]

        # 校验 authorization_info 是否合法
        self.user_info_validate(authorization_info)
        # 获取用户信息
        if "online" == access_type:
            access_token = authorization_info["access_token"]
        else:
            access_token = self.user_info_refresh(refresh_token=authorization_info["refresh_token"])

        user_info = self.user_info_endpoint(access_token=access_token, token_type=authorization_info["token_type"])

        return self.parse_user_info(user_info)

    def user_info_validate(self, authorization_info):
        u"""校验authorization_info是否为标准, 如果authorization_info不是OAuth2标准的认证信息, 你需要重写这个方法"""
        access_type = self._config["access_type"]
        if "online" == access_type:
            schema = self._authorization_info_online_schema
        else:
            schema = self._authorization_info_offline_schema

        try:
            validate(instance=authorization_info, schema=schema)
        except Exception as e:
            raise Exception(u"oauth2.user_info()异常, authorization_info格式非法: %s" % b2s(e.message))

    def user_info_refresh(self, refresh_token):
        u"""通过refresh_token获取临时的access_token, 如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        url = self._config.get("refresh_url")
        if url is None:
            raise Exception(u"oauth2.user_info_refresh()执行时异常, 缺少配置项 PLUGIN_CONFIG.oauth2.refresh_url")

        # method
        method = self.user_info_refresh_method()
        method = method.upper()
        # params
        params = self.user_info_refresh_params(refresh_token)
        # headers
        headers = self.user_info_refresh_headers(refresh_token)
        kwargs = {
            "method": method,
            "params": params,
            "headers": headers,
        }

        # body
        if method in ["POST", "PUT"]:
            body = self.user_info_refresh_body(refresh_token)
            if body is not None:
                kwargs["data"] = body

        # send http
        resp = requests.request(**kwargs)
        return self.user_info_refresh_parse_response(resp)

    def user_info_refresh_method(self):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        return "POST"

    def user_info_refresh_params(self, refresh_token):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        params = {
            "client_id": self._config["client_id"],
            "client_secret": self._config["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        scope = self._config.get("scope")
        if scope is not None:
            params[scope] = self._config["scope"]

        return params

    def user_info_refresh_headers(self, refresh_token):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        return {"Content-Type": "application/x-www-form-urlencoded"}

    def user_info_refresh_body(self, refresh_token):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        return None

    def user_info_refresh_parse_response(self, resp):
        u"""如果协议格式不是RFC6749标准, 你需要重写这个方法"""
        status_code = resp.status_code
        if status_code < 200 or status_code >= 400:
            raise Exception(u"oauth2.user_info_refresh()执行时失败, 根据refresh_token获取访问凭证时异常: [%d]%s" % (status_code, resp.text))

        resp_json = resp.json()
        access_token = resp_json.get("access_token")
        if access_token is None:
            raise Exception(u"oauth2.user_info_refresh()执行时失败, 返回结果中无法获取access_token: %s", resp.text)

        return access_token

    def user_info_endpoint(self, access_token, token_type):
        u"""如果协议格式不是OIDC标准, 你需要重写这个方法"""
        url = self._config["user_info_url"]
        headers = {"Authorization": "%s %s" % (token_type, access_token)}

        resp = requests.get(url=url, headers=headers)
        return self.user_info_endpoint_response(resp)

    def user_info_endpoint_response(self, resp):
        u"""如果协议格式不是OIDC标准, 你需要重写这个方法"""
        status_code = resp.status_code
        if status_code < 200 or status_code >= 400:
            raise Exception(u"oauth2.user_info()执行失败, 请求获取用户信息时异常: [%d]%s" % (status_code, resp.text))

        return resp.json()

    def parse_user_info(self, user_info):
        u"""从user_info中获取login_key、login_value, 这是确定cmdb唯一用户的凭证"""
        return "name", user_info["sub"]

    def sign_out(self, authorization_info):
        u"""SSO用户注销后对access_token、refresh_token的处理, 有需要的话重写这个方法"""
        return ""
