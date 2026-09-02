# -*- coding: utf-8 -*-
import logging
from jsonschema import validate
from urlparse import urlparse

# project
from handlers.providers.cas.cas_client import CASClient
from settings.setting import PLUGIN_CONFIG
from handlers.providers.base_provider import Provider
from utils.tools import b2s


class cas(Provider):
    def __init__(self):
        Provider.__init__(self)
        self._config = PLUGIN_CONFIG.get("cas")
        if self._config is None:
            raise Exception(u"导入cas模块异常, setting.py中PLUGIN_CONFIG.cas配置不存在")

        config_schema = {
            "type": "object",
            "properties": {
                "login_url": {"type": "string"},
                "redirect_uri": {"type": "string"},
                "login_name": {"type": "string"},
            },
            "required": ["login_url", "redirect_uri"]
        }
        try:
            validate(instance=self._config, schema=config_schema)
        except Exception as e:
            raise Exception(u"导入cas模块异常, setting.py中PLUGIN_CONFIG.cas格式非法: %s" % b2s(e.message))
        parsed_url = urlparse(self._config["redirect_uri"])
        port = parsed_url.port
        if port:
            address = "{scheme}://{hostname}:{port}".format(scheme=parsed_url.scheme, hostname=parsed_url.hostname,
                                                            port=port)
        else:
            address = "{scheme}://{hostname}".format(scheme=parsed_url.scheme, hostname=parsed_url.hostname)
        self._redirect_uri = "{address}/next/sso-auth/authorize".format(address=address)
        self._logout_service_url = "{address}/next".format(address=address)
        auth_prefix = self._config.get("auth_prefix", "/cas")
        if auth_prefix is not "":
            if auth_prefix.startswith("/") is False:
                auth_prefix = "/{}".format(auth_prefix)
            self._cas_client = CASClient(self._config["login_url"], auth_prefix=auth_prefix)
        else:
            self._cas_client = CASClient(self._config["login_url"])
        self._login_name = self._config.get("login_name", "name")

    def pre_signin(self, params):
        return self._cas_client.get_login_url(service_url=self._redirect_uri)

    def signin(self, params):
        authorization_info = {
            "ticket": params.get("ticket"),
        }
        return authorization_info

    def user_info(self, authorization_info=None):
        ticket = authorization_info.get("ticket")
        try:
            cas_response = self._cas_client.perform_service_validate(ticket=ticket,
                                                                     service_url=self._redirect_uri)
            if cas_response and cas_response.success:
                user = cas_response.user
            else:
                raise Exception(u"invalid cas_response: %s" % cas_response.response_text)
        except Exception as e:
            raise Exception(u"cas.perform_service_validate()异常: %s" % b2s(e.message))
        return self._login_name, user

    def sign_out(self, params):
        return self._cas_client.get_logout_url(service_url=self._logout_service_url)

    def sso_global_sign_out(self, params):
        logout_requests = params.get("logoutRequest", [])
        if len(logout_requests) < 1:
            raise Exception(u"logout request args not found")
        logout_request = logout_requests[0]
        result = self._cas_client.parse_logout_request(logout_request)
        logging.info("parse result: %s", result)
        ticket = result.get("session_index", "")
        if not ticket:
            raise Exception(u"ticket is null")
        logging.info("ticket: %s", ticket)
        return ticket
