#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Zabbix 5.4 全量模板只读导出，自动补齐可见父模板；Python 2.7.9+（也兼容Python 3），无第三方依赖。"""
from __future__ import print_function, unicode_literals

import argparse
import datetime
import getpass
import io
import json
import logging
import os
import re
import ssl
import sys
import traceback
try:
    import urllib2 as http_request
    import urlparse as url_parse
except ImportError:
    import urllib.request as http_request
    import urllib.parse as url_parse

try:
    text_type = unicode
except NameError:
    text_type = str


def text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def cli_text(value):
    if isinstance(value, bytes):
        encoding = (sys.getfilesystemencoding() or "mbcs") if os.name == "nt" else "utf-8"
        return value.decode(encoding)
    return text(value)


def write_windows_console(stream, value):
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        import msvcrt
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        kernel = ctypes.WinDLL(b"kernel32.dll", use_last_error=True)
        mode = wintypes.DWORD()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        writer = kernel.WriteConsoleW
        writer.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        writer.restype = wintypes.BOOL
        for offset in range(0, len(value), 4096):
            buffer = ctypes.create_unicode_buffer(value[offset:offset + 4096])
            remaining = len(buffer) - 1
            position = 0
            while remaining:
                written = wintypes.DWORD()
                pointer = ctypes.cast(ctypes.byref(buffer, position * ctypes.sizeof(ctypes.c_wchar)), wintypes.LPCWSTR)
                if not writer(handle, pointer, remaining, ctypes.byref(written), None) or not written.value:
                    raise ctypes.WinError(ctypes.get_last_error())
                position += written.value
                remaining -= written.value
        return True
    except (AttributeError, TypeError, ValueError, io.UnsupportedOperation):
        return False


def write_text(stream, value):
    value = text(value)
    if write_windows_console(stream, value):
        return
    if sys.version_info[0] == 2:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(value.encode(encoding, "backslashreplace"))
    else:
        stream.write(value)


class UTF8Stream(object):
    def __init__(self, stream):
        self.stream = stream

    def write(self, message):
        write_text(self.stream, message)

    def flush(self):
        self.stream.flush()


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if message:
            write_text(file or sys.stderr, message)

VERSION = "1.2.0-py2"
LOGGER = logging.getLogger("zabbix_export")
SENSITIVE = re.compile(r"password|passwd|passphrase|secret|token|community|authorization|api[_ .-]?key|auth[_ .-]?(key|pass)|priv[_ .-]?(key|pass)|psk", re.I)

# 私有化环境直接修改本段变量后运行，不再通过命令行传入连接参数。
ZABBIX_URL = "https://zabbix.example/zabbix"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = "zabbix"
ZABBIX_TOKEN = ""
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
TIMEOUT = 120
INSECURE = False
INCLUDE_SENSITIVE = True
TEMPLATE_IDS = []
TEMPLATE_NAMES = []
EXPORT_ALL = True


class ExportError(RuntimeError):
    pass


class NoRedirect(http_request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ExportError("API返回重定向；请直接指定最终站点的API地址，避免凭证转发")


def api_url(value):
    parsed = url_parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ExportError("--url 必须是http/https站点或api_jsonrpc.php地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExportError("API地址不得包含账号、密码、query或fragment")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api_jsonrpc.php"):
        path += "/api_jsonrpc.php"
    return url_parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class Client(object):
    def __init__(self, url, timeout=60, insecure=False):
        self.url = api_url(url)
        self.timeout = timeout
        self.auth = None
        self.session_owned = False
        self.sequence = 0
        self.secrets = []
        if not hasattr(ssl, "create_default_context"):
            raise ExportError("需要Python 2.7.9或更新版本，不能在缺少证书校验能力时静默降级")
        context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
        self.opener = http_request.build_opener(NoRedirect(), http_request.HTTPSHandler(context=context))

    def safe_error(self, value):
        message = text(value)
        for secret in self.secrets:
            if secret:
                message = message.replace(text(secret), "<redacted>")
                message = message.replace(json.dumps(secret)[1:-1], "<redacted>")
        return message

    def call(self, method, params, authenticated=True):
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.sequence}
        if authenticated:
            if not self.auth:
                raise ExportError("未认证")
            body["auth"] = self.auth
        request = http_request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json-rpc"})
        LOGGER.info("API method=%s request_id=%s", method, self.sequence)
        try:
            response = self.opener.open(request, timeout=self.timeout)
            try:
                result = json.loads(response.read().decode("utf-8-sig"))
            finally:
                response.close()
        except http_request.HTTPError as error:
            status = error.code
            error.close()
            hint = "；404通常是站点路径错误，请确认浏览器实际部署在根目录还是/zabbix，并提供对应api_jsonrpc.php地址" if status == 404 else ""
            raise ExportError("[Client.call] method=%s HTTP=%s API=%s%s" % (method, status, self.url, hint))
        except (http_request.URLError, ValueError, IOError, OSError) as error:
            raise ExportError("[Client.call] %s请求失败: %s" % (method, self.safe_error(error)))
        if not isinstance(result, dict) or result.get("id") != self.sequence:
            raise ExportError("[Client.call] %s响应结构或请求ID不匹配" % method)
        if "error" in result:
            raise ExportError("[Client.call] %s: %s" % (method, self.safe_error(json.dumps(result["error"], ensure_ascii=False))))
        if "result" not in result:
            raise ExportError("[Client.call] %s缺少result" % method)
        return result["result"]

    def login(self, user, password):
        self.secrets.append(password)
        self.auth = self.call("user.login", {"username": user, "password": password}, authenticated=False)
        if not isinstance(self.auth, (str, bytes, text_type)) or not self.auth:
            raise ExportError("登录未返回有效会话")
        self.secrets.append(self.auth)
        self.session_owned = True

    def close(self):
        if self.session_owned and self.auth:
            self.call("user.logout", [])
            self.auth = None


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(entry) for entry in value]
    if not isinstance(value, dict):
        return value
    result = {key: sanitize(entry) for key, entry in value.items()}
    if "macro" in result and "value" in result:
        if SENSITIVE.search(text(result["macro"])) or text(result.get("type", "")).upper() in ("1", "2", "SECRET_TEXT", "VAULT_SECRET"):
            result["value"] = "<redacted>"
    if SENSITIVE.search(text(result.get("name", ""))) and "value" in result:
        result["value"] = "<redacted>"
    for key in list(result):
        if SENSITIVE.search(key) and not isinstance(result[key], (dict, list)) and result[key] not in ("", None):
            result[key] = "<redacted>"
    return result


def choose_templates(templates, identifiers, names, all_templates=False):
    by_id = {text(row["templateid"]): row for row in templates}
    roots = set()
    for identifier in identifiers:
        if identifier not in by_id:
            raise ExportError("模板ID不存在或无读取权限: " + identifier)
        roots.add(identifier)
    for name in names:
        matches = [identifier for identifier, row in by_id.items() if name in (row["host"], row["name"])]
        if not matches:
            raise ExportError("模板名称不存在或无读取权限: " + name)
        roots.update(matches)
    if all_templates or (not identifiers and not names):
        roots.update(by_id)
    if not roots:
        raise ExportError("未匹配模板；使用--list查看，或用--name/--template-id明确选择")
    selected = set(roots)
    pending = list(roots)
    while pending:
        identifier = pending.pop()
        for parent in by_id[identifier].get("parentTemplates", []):
            parent_id = text(parent["templateid"])
            if parent_id not in by_id:
                raise ExportError("模板%s的父模板%s不可见，无法完整导出" % (identifier, parent_id))
            if parent_id not in selected:
                selected.add(parent_id)
                pending.append(parent_id)
    return roots, [by_id[identifier] for identifier in sorted(selected, key=int)]


def write_json(path, value):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(text(path), flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def parser():
    argument_parser = ArgumentParser(description="从Zabbix 5.4只读导出模板、告警触发器、触发器原型和监控项阈值。请先修改脚本顶部配置变量；不接受连接、输出路径等命令行参数。Python 2.7.9+（也兼容Python 3）。", epilog="运行：python %(prog)s\n帮助：python %(prog)s --help\n配置项：ZABBIX_URL、ZABBIX_USER、ZABBIX_PASSWORD、OUTPUT_DIR、TEMPLATE_IDS、TEMPLATE_NAMES。", formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--version", action="version", version=VERSION)
    return argument_parser


def main(argv=None):
    parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=UTF8Stream(sys.stderr))
    client = None
    try:
        if not ZABBIX_URL or not ZABBIX_USER or not ZABBIX_PASSWORD or TIMEOUT <= 0:
            raise ExportError("请先填写脚本顶部的ZABBIX_URL、ZABBIX_USER、ZABBIX_PASSWORD，TIMEOUT须大于0")
        client = Client(cli_text(ZABBIX_URL), TIMEOUT, INSECURE)
        token = ZABBIX_TOKEN
        password = None
        if token:
            client.auth = text(token)
            client.secrets.append(text(token))
            LOGGER.info("[main] Using ZABBIX_TOKEN; password prompt is not needed")
        else:
            password = ZABBIX_PASSWORD
            LOGGER.info("[main] Using configured ZABBIX_PASSWORD")
            password = cli_text(password)
            client.secrets.append(password)
        LOGGER.info("[main] API endpoint=%s", client.url)
        api_version = client.call("apiinfo.version", [], authenticated=False)
        if not text(api_version).startswith("5.4."):
            raise ExportError("本脚本针对5.4.x，实际API版本为%s，停止以免错误兼容" % api_version)
        LOGGER.info("API版本=%s", api_version)
        if not token:
            client.login(cli_text(ZABBIX_USER), password)
        templates = client.call("template.get", {"output": ["templateid", "host", "name"], "selectParentTemplates": ["templateid", "host", "name"], "sortfield": "host"})
        if not isinstance(templates, list):
            raise ExportError("template.get未返回数组")
        roots, selected = choose_templates(templates, TEMPLATE_IDS, TEMPLATE_NAMES, EXPORT_ALL)
        LOGGER.info("匹配根模板=%s，含父模板=%s", len(roots), len(selected))
        raw = client.call("configuration.export", {"options": {"templates": [row["templateid"] for row in selected]}, "format": "json", "prettyprint": True})
        exported = json.loads(raw)
        document = exported.get("zabbix_export", {})
        actual = {row["template"] for row in document.get("templates", [])}
        expected = {row["host"] for row in selected}
        if expected != actual:
            raise ExportError("导出模板集合不匹配；缺失=%s，额外=%s" % (sorted(expected-actual), sorted(actual-expected)))
        if text(document.get("version")) != "5.4":
            raise ExportError("导出文档版本不是5.4")
        template_ids = [row["templateid"] for row in selected]
        alert_params = {"hostids": template_ids, "output": "extend", "selectHosts": ["hostid", "host", "name"], "selectItems": "extend", "selectFunctions": "extend", "selectDependencies": "extend", "selectTags": "extend", "expand": True}
        alerts = {
            "triggers": client.call("trigger.get", alert_params),
            "trigger_prototypes": client.call("triggerprototype.get", alert_params),
            "items": client.call("item.get", {"hostids": template_ids, "output": "extend", "selectPreprocessing": "extend", "selectTags": "extend", "selectValueMap": "extend", "sortfield": "name"}),
        }
        if not INCLUDE_SENSITIVE:
            exported = sanitize(exported)
            alerts = sanitize(alerts)
        root = os.path.abspath(os.path.expanduser(cli_text(OUTPUT_DIR)))
        if not os.path.isdir(root):
            try:
                os.makedirs(root, 0o700)
            except OSError:
                if not os.path.isdir(root):
                    raise
        output = os.path.join(root, "zabbix54_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        os.mkdir(output, 0o700)
        write_json(os.path.join(output, "templates.json"), exported)
        write_json(os.path.join(output, "alert-rules.json"), alerts)
        write_json(os.path.join(output, "template-index.json"), {"api_version": api_version, "script_version": VERSION, "root_templateids": sorted(roots, key=int), "templates": selected, "alert_counts": dict((key, len(value)) for key, value in alerts.items()), "sanitized": not INCLUDE_SENSITIVE, "notes": ["alert-rules.json包含触发器、触发器原型、监控项及预处理，可用于整理EasyOps告警模板和阈值", "未导出主机或主机凭证；完整性受账号权限限制"]})
        LOGGER.info("导出完成，模板=%s，触发器=%s，触发器原型=%s，监控项=%s", len(selected), len(alerts["triggers"]), len(alerts["trigger_prototypes"]), len(alerts["items"]))
        write_text(sys.stdout, text(output) + "\n")
        return 0
    except Exception:
        details = traceback.format_exc()
        LOGGER.error("[main] %s", client.safe_error(details) if client else text(details))
        return 1
    finally:
        if client:
            try:
                client.close()
            except Exception:
                LOGGER.warning("[main.logout] %s", client.safe_error(traceback.format_exc()))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        LOGGER.warning("用户中止")
        sys.exit(130)
