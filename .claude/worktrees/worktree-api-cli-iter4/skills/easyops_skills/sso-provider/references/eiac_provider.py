# coding=utf-8
# 西南证券sso对接
# stdlib
import logging
import time

# 3rd party
from jsonschema import validate

# project
from settings.setting import PLUGIN_CONFIG
from handlers.providers.base_provider import Provider
from handlers.providers.http_request_info import PreSignInRequest, SignOutRequest
from utils.tools import b2s
from handlers.providers.eiac.eiac_crypto import create_authenticator, validate_authenticator


class eiac(Provider):
    def __init__(self):
        Provider.__init__(self)
        self._config = PLUGIN_CONFIG.get("eiac")
        if self._config is None:
            raise Exception(u"导入eiac模块异常, setting.py中PLUGIN_CONFIG.eiac配置不存在")
        config_schema = {
            "type": "object",
            "properties": {
                "login_url": {"type": "string"},
                "IASID": {"type": "string"},
                "easyops_host": {"type": "string"},
                "IASKey": {"type": "string"},
                "logout_url": {"type": "string"},
                "iv": {"type": "string"},
            },
            "required": ["login_url", "IASID", "easyops_host", "IASKey", "logout_url"]
        }
        try:
            validate(instance=self._config, schema=config_schema)
        except Exception as e:
            logging.error(u"导入eiac模块异常, setting.py中PLUGIN_CONFIG.eiac格式非法: %s" % b2s(e.message))
            raise Exception(u"导入eiac模块异常, setting.py中PLUGIN_CONFIG.eiac格式非法: %s" % b2s(e.message))

    def pre_signin(self, params):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        IASID = self._config["IASID"]
        IASKey = self._config["IASKey"]
        easyops_url = self._config["easyops_host"]
        returnUrl = easyops_url + "/api/v2/sso/authorization/default"
        byte_iv = self._config.get("iv", "")
        authenticator = create_authenticator(IASID, timestamp, returnUrl, IASKey, byte_iv)
        data = {
            "IASID": IASID,
            "TimeStamp": timestamp,
            "ReturnURL": returnUrl,
            "Authenticator": authenticator
        }
        login_url = self._config["login_url"]
        method = "POST"
        presignin_request = PreSignInRequest(login_url=login_url, method=method, data=data)
        return presignin_request

    def signin(self, params):
        data = params
        authenticator = data.get("Authenticator", "")
        timestamp = data.get("TimeStamp", "")
        user_account = data.get("UserAccount", "")
        error_description = data.get("ErrorDescription", "")
        result = data.get("Result", "")
        IASKey = self._config["IASKey"]
        IASID = self._config["IASID"]
        byte_iv = self._config.get("iv", "")
        is_ok = validate_authenticator(IASID, timestamp, user_account, result, error_description, IASKey, authenticator, byte_iv)
        if is_ok and user_account:
            data["easyops_host"] = self._config["easyops_host"]
            return data
        else:
            raise Exception("sso validate authenticator failed")

    def user_info(self, authorization_info):
        login_key, login_value = self.parse_user_info(authorization_info)
        logging.info("login_key: %s", login_key)
        logging.info("login_value: %s", login_value)
        return login_key, login_value

    def parse_user_info(self, user_info):
        u"""从user_info中获取login_key、login_value, 这是确定cmdb唯一用户的凭证"""
        login_key = "name"
        login_value = user_info["UserAccount"]
        return login_key, login_value

    def sign_out(self, authorization_info):
        logout_url = self._config["logout_url"]
        logging.info("logout_url: %s", logout_url)
        method = "POST"
        sign_out_request = SignOutRequest(logout_url=logout_url, method=method, data=None)
        return sign_out_request

