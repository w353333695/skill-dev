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

VERSION = "1.0.3-py2"
LOGGER = logging.getLogger("zabbix_export")
SENSITIVE = re.compile(r"password|passwd|passphrase|secret|token|community|authorization|api[_ .-]?key|auth[_ .-]?(key|pass)|priv[_ .-]?(key|pass)|psk", re.I)


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
    argument_parser = ArgumentParser(description="只读导出Zabbix 5.4全部可见模板和递归父模板，覆盖服务器、存储、网络及其他设备，不按品牌或采集协议筛选，不连接被监控设备、不修改模板或任务。Python 2.7.9+（也兼容Python 3），无第三方依赖。", epilog="示例：\n  python %(prog)s --url https://zabbix.example/zabbix --list\n  python %(prog)s --url https://zabbix.example/zabbix\n  python %(prog)s --url https://zabbix.example/zabbix --name 'Dell iDRAC SNMP' --name 'Template Server Lenovo XCC SNMPv3'\n  python %(prog)s --url https://zabbix.example/zabbix --template-id 10749 --template-id 10929\n  python %(prog)s --url https://zabbix.example/zabbix --all\n\n认证：ZABBIX_TOKEN，或ZABBIX_USER+ZABBIX_PASSWORD环境变量；无密码时交互隐藏输入。\n默认导出全部可见模板，不按品牌、设备类型或SNMP协议过滤；--name/--template-id仅用于缩小范围。完整性受账号权限限制。\n导出保留原生结构；默认脱敏后不能当完整凭证备份。继承内容需父模板共同导出。\n日志仅记录方法及请求ID，不记录请求体/凭证/原始响应；导出文件仍需人工审查脚本内硬编码秘密。\nCtrl-C退出130；成功0；配置/API/导出失败1。", formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--version", action="version", version=VERSION)
    argument_parser.add_argument("--url", default=os.environ.get("ZABBIX_URL"), help="站点或完整API地址；默认ZABBIX_URL，自动补api_jsonrpc.php")
    argument_parser.add_argument("--user", default=os.environ.get("ZABBIX_USER"), help="用户名；默认ZABBIX_USER；密码勿放命令行")
    selection = argument_parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="显式导出全部可见模板；不指定选择器时也默认全量")
    selection.add_argument("--list", action="store_true", help="仅列出全部可见模板ID/名称，不导出文件")
    argument_parser.add_argument("--name", action="append", default=[], help="精确模板标识或显示名，可重复；未指定选择器时默认导出全部可见模板")
    argument_parser.add_argument("--template-id", action="append", default=[], help="模板ID，可重复；未指定选择器时默认导出全部可见模板")
    argument_parser.add_argument("--output-dir", default="./zabbix-template-exports", help="输出根目录；默认./zabbix-template-exports，创建唯一子目录，不覆盖旧文件")
    argument_parser.add_argument("--timeout", type=int, default=120, help="单次API超时秒；默认120，无自动重试")
    argument_parser.add_argument("--insecure", action="store_true", help="显式跳过HTTPS证书校验；默认验证证书，仅可信自签环境使用")
    argument_parser.add_argument("--include-sensitive", action="store_true", help="保留API返回的凭证/宏值；默认脱敏，不建议开启或分享；API自身隐藏值仍无法恢复")
    return argument_parser


def main(argv=None):
    arguments = parser().parse_args(argv)
    arguments.name = [cli_text(value) for value in arguments.name]
    arguments.template_id = [text(value) for value in arguments.template_id]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=UTF8Stream(sys.stderr))
    client = None
    try:
        if not arguments.url or arguments.timeout <= 0:
            raise ExportError("必须提供--url/ZABBIX_URL，timeout须大于0")
        if (arguments.all or arguments.list) and (arguments.name or arguments.template_id):
            raise ExportError("--all/--list不能与--name/--template-id混用")
        client = Client(cli_text(arguments.url), arguments.timeout, arguments.insecure)
        token = os.environ.get("ZABBIX_TOKEN")
        password = None
        if token:
            client.auth = text(token)
            client.secrets.append(text(token))
            LOGGER.info("[main] Using ZABBIX_TOKEN; password prompt is not needed")
        else:
            if not arguments.user:
                raise ExportError("请提供--user/ZABBIX_USER和--url/ZABBIX_URL，或使用ZABBIX_TOKEN")
            password = os.environ.get("ZABBIX_PASSWORD")
            if password:
                LOGGER.info("[main] Using ZABBIX_PASSWORD; password prompt is not needed")
            else:
                password = getpass.getpass("Zabbix password (hidden): ")
            password = cli_text(password)
            client.secrets.append(password)
        LOGGER.info("[main] API endpoint=%s", client.url)
        api_version = client.call("apiinfo.version", [], authenticated=False)
        if not text(api_version).startswith("5.4."):
            raise ExportError("本脚本针对5.4.x，实际API版本为%s，停止以免错误兼容" % api_version)
        LOGGER.info("API版本=%s", api_version)
        if not token:
            client.login(cli_text(arguments.user), password)
        templates = client.call("template.get", {"output": ["templateid", "host", "name"], "selectParentTemplates": ["templateid", "host", "name"], "sortfield": "host"})
        if not isinstance(templates, list):
            raise ExportError("template.get未返回数组")
        if arguments.list:
            for row in templates:
                write_text(sys.stdout, "%s\t%s\t%s\n" % (row["templateid"], row["host"], row["name"]))
            return 0
        roots, selected = choose_templates(templates, arguments.template_id, arguments.name, arguments.all)
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
        if not arguments.include_sensitive:
            exported = sanitize(exported)
        root = os.path.abspath(os.path.expanduser(cli_text(arguments.output_dir)))
        if not os.path.isdir(root):
            try:
                os.makedirs(root, 0o700)
            except OSError:
                if not os.path.isdir(root):
                    raise
        output = os.path.join(root, "zabbix54_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        os.mkdir(output, 0o700)
        write_json(os.path.join(output, "templates.json"), exported)
        write_json(os.path.join(output, "template-index.json"), {"api_version": api_version, "script_version": VERSION, "root_templateids": sorted(roots, key=int), "templates": selected, "sanitized": not arguments.include_sensitive, "notes": ["未导出主机或主机凭证；默认全部可见模板，不按品牌/类型/协议筛选；包含父模板以补齐继承定义；完整性受账号权限限制", "未读取全局宏、主机宏覆盖或最近监控值", "默认脱敏不保证删除脚本内部硬编码秘密；分享前人工审查"]})
        LOGGER.info("导出完成，模板=%s；请人工审查后分享templates.json和template-index.json", len(selected))
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
