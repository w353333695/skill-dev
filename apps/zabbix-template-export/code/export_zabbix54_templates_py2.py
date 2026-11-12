#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Zabbix 5.4 全量模板只读导出，自动补齐可见父模板；Python 2.7.9+（也兼容Python 3），无第三方依赖。"""
from __future__ import print_function, unicode_literals

import argparse
import datetime
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

VERSION = "2.0.0"
LOGGER = logging.getLogger("zabbix_export")
SENSITIVE = re.compile(r"sendto|recipient|password|passwd|passphrase|secret|token|community|authorization|api[_ .-]?key|auth[_ .-]?(key|pass)|priv[_ .-]?(key|pass)|psk", re.I)

# 私有化环境直接修改本段变量后运行，不再通过命令行传入连接参数。
ZABBIX_URL = "https://zabbix.example/zabbix"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = ""
ZABBIX_TOKEN = ""
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
TIMEOUT = 120
INSECURE = False
TEMPLATE_IDS = []
TEMPLATE_NAMES = []
EXPORT_ALL = True
EXPORT_HOSTS = True
HOST_IDS = []
BATCH_SIZE = 25
EXPORT_EXTENDED = True
FAIL_ON_PARTIAL = True
EXPORT_EVENTS = True
EXPORT_HISTORY = False
EXPORT_TRENDS = False
EXPORT_TEXT_HISTORY = False
DATA_TIME_FROM = None
DATA_TIME_TILL = None
PAGE_SIZE = 5000


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
    if all_templates and not identifiers and not names:
        roots.update(by_id)
    if not roots:
        raise ExportError("未匹配模板；请检查TEMPLATE_IDS/TEMPLATE_NAMES，或启用EXPORT_ALL")
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


def parse_key(key):
    if "[" not in key or not key.endswith("]"):
        return key, []
    kind, body = key.split("[", 1)
    arguments, token, quoted = [], [], False
    body = body[:-1]
    position = 0
    while position < len(body):
        character = body[position]
        if character == "\\" and quoted and position + 1 < len(body) and body[position + 1] == '"':
            token.append('"')
            position += 2
            continue
        if character == '"':
            quoted = not quoted
        elif character == "," and not quoted:
            arguments.append("".join(token))
            token = []
        else:
            token.append(character)
        position += 1
    if quoted:
        raise ExportError("[parse_key] 监控键存在未闭合引号")
    arguments.append("".join(token))
    return kind, arguments


def primary_interface(host):
    interfaces = host.get("interfaces", [])
    candidates = sorted(interfaces, key=lambda row: (
        text(row.get("type")) != "1", text(row.get("main")) != "1",
        text(row.get("interfaceid", ""))))
    return candidates[0] if candidates else {}


def template_chain(host, templates):
    found, pending, unavailable = [], list(host.get("parentTemplates", [])), []
    while pending:
        parent = pending.pop(0)
        identifier = text(parent["templateid"])
        if identifier in found:
            continue
        found.append(identifier)
        if identifier in templates:
            pending.extend(templates[identifier].get("parentTemplates", []))
        else:
            unavailable.append(identifier)
    return found, unavailable


MACRO = re.compile(r'\{\$[^{}]+\}')


def macro_context(host, templates, globals_):
    levels = [[host.get("macros", [])]]
    pending = list(host.get("parentTemplates", []))
    visited = set()
    while pending:
        level, following = [], []
        for parent in sorted(pending, key=lambda row: int(row["templateid"])):
            identifier = text(parent["templateid"])
            if identifier in visited:
                continue
            visited.add(identifier)
            template = templates.get(identifier, {})
            level.append(template.get("macros", []))
            following.extend(template.get("parentTemplates", []))
        levels.append(level)
        pending = following
    levels.append([globals_])
    resolved, ambiguous = {}, set()
    for level in levels:
        candidates = {}
        for entries in level:
            for macro in entries:
                name = macro.get("macro", "")
                value = macro.get("value", "")
                if SENSITIVE.search(name) or text(macro.get("type", "0")) in ("1", "2"):
                    value = "<redacted>"
                candidates.setdefault(name, set()).add(text(value))
        for name, values in candidates.items():
            if name in resolved or name in ambiguous:
                continue
            if len(values) == 1:
                resolved[name] = next(iter(values))
            else:
                ambiguous.add(name)
    return resolved, ambiguous


def resolve_macros(expression, context):
    values, ambiguous = context
    unresolved = set()
    def replace(match):
        name = match.group(0)
        value = values.get(name)
        if name in ambiguous or value is None or value == "<redacted>":
            unresolved.add(name)
            return name
        return value
    result = MACRO.sub(replace, text(expression or ""))
    unresolved.update(MACRO.findall(result))
    return result, sorted(unresolved)


def expanded_expression(trigger, items):
    expression = trigger.get("expression", "")
    for function in trigger.get("functions", []):
        item = items.get(text(function.get("itemid")), {})
        owner = item.get("_owner", item.get("hostid", "?"))
        parameter = function.get("parameter", "")
        replacement = "%s(/%s/%s%s)" % (function.get("function", "?"), owner,
                     item.get("key_", "?"), "," + parameter if parameter else "")
        expression = expression.replace("{" + text(function["functionid"]) + "}", replacement)
    return expression


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    value = text(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        value = "'" + value
    return value


def write_csv(path, fields, rows):
    import csv
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"\xef\xbb\xbf")
        for row in [fields] + rows:
            values = [csv_value(value) for value in row]
            if sys.version_info[0] == 2:
                from StringIO import StringIO
                buffer = StringIO()
                csv.writer(buffer).writerow([value.encode("utf-8") for value in values])
                stream.write(buffer.getvalue())
            else:
                buffer = io.StringIO(newline="")
                csv.writer(buffer).writerow(values)
                stream.write(buffer.getvalue().encode("utf-8"))


class Exporter(object):
    def __init__(self, client, output):
        self.client, self.output = client, output
        self.datasets, self.status = {}, {}

    def save(self, name, value):
        clean = sanitize(value)
        write_json(os.path.join(self.output, name + ".json"), clean)
        self.datasets[name] = clean
        return clean

    def collect(self, name, method, params, owner_ids=None, identity=None):
        rows, errors = [], []
        batches = [None] if owner_ids is None else [owner_ids[start:start + BATCH_SIZE]
                   for start in range(0, len(owner_ids), BATCH_SIZE)]
        for batch in batches:
            query = dict(params)
            if batch is not None:
                query["hostids"] = batch
            try:
                response = self.client.call(method, query)
                if not isinstance(response, list) or any(not isinstance(row, dict) for row in response):
                    raise ExportError("[collect] API结果不是对象数组: " + method)
                rows.extend(response)
            except Exception:
                details = self.client.safe_error(traceback.format_exc())
                LOGGER.error("[Exporter.collect] dataset=%s %s", name, details)
                errors.append({"owner_ids": batch, "error": details})
        if identity:
            rows = list(dict((text(row[identity]), row) for row in rows).values())
            rows.sort(key=lambda row: text(row[identity]))
        self.status[name] = {"method": method, "state": "partial" if errors else "ok",
                            "count": len(rows), "errors": errors}
        return self.save(name, rows)

    def report(self, api_version):
        hosts = self.datasets.get("hosts", [])
        templates = dict((text(row["templateid"]), row) for row in self.datasets.get("templates-api", []))
        owners = dict(templates)
        owners.update((text(row["hostid"]), row) for row in hosts)
        items = dict((text(row["itemid"]), dict(row)) for row in self.datasets.get("items", []))
        for item in items.values():
            item["_owner"] = owners.get(text(item.get("hostid")), {}).get("host", "?")
        triggers = self.datasets.get("triggers", [])
        trigger_by_item = {}
        for trigger in triggers:
            references = set(text(row["itemid"]) for row in trigger.get("items", []))
            references.update(text(row["itemid"]) for row in trigger.get("functions", []))
            for identifier in references:
                trigger_by_item.setdefault(identifier, []).append(trigger)
        globals_ = self.datasets.get("global-macros", [])
        host_rows, item_rows, alert_rows, process_rows = [], [], [], []
        links, contexts = [], {}
        for host in hosts:
            identifier = text(host["hostid"])
            chain, missing = template_chain(host, templates)
            contexts[identifier] = macro_context(host, templates, globals_)
            interface = primary_interface(host)
            host_rows.append([identifier, host.get("host"), host.get("name"), host.get("status"),
                interface.get("ip"), interface.get("dns"), interface.get("useip"),
                host.get("interfaces", []), host.get("groups", []),
                host.get("parentTemplates", []), chain, missing, host.get("tags", [])])
            links.append({"hostid": identifier, "host": host.get("host"), "templateids": chain,
                          "direct_templates": host.get("parentTemplates", []), "unavailable_templateids": missing})
        for item in items.values():
            identifier = text(item.get("hostid", ""))
            if identifier not in contexts:
                continue
            host = owners[identifier]
            interface = primary_interface(host)
            attached = trigger_by_item.get(text(item["itemid"]), [])
            key, unresolved = resolve_macros(item.get("key_", ""), contexts[identifier])
            try:
                kind, args = parse_key(key)
            except ExportError:
                LOGGER.warning("[Exporter.report.parse_key] %s", traceback.format_exc())
                kind, args = key, []
            item_rows.append([identifier, host.get("host"), host.get("name"), interface.get("ip"),
                interface.get("dns"), item["itemid"], item.get("name"), item.get("key_"), key,
                item.get("type"), item.get("value_type"), item.get("units"), item.get("delay"),
                item.get("status"), item.get("state"), item.get("error"), item.get("interfaceid"),
                item.get("templateid"), item.get("master_itemid"), item.get("preprocessing", []),
                item.get("lastvalue"), [row.get("triggerid") for row in attached], unresolved])
            if kind in ("proc.num", "proc.cpu.util", "proc.mem", "net.tcp.listen", "net.udp.listen", "net.tcp.port", "net.tcp.service", "net.tcp.service.perf"):
                args += [""] * max(0, 5 - len(args))
                process_name, user, commandline, protocol, address, port = "", "", "", "", "", ""
                if kind.startswith("proc."):
                    process_name, user, commandline = args[0], args[1], args[3]
                elif kind in ("net.tcp.listen", "net.udp.listen"):
                    protocol, port = ("UDP" if kind == "net.udp.listen" else "TCP"), args[0]
                elif kind == "net.tcp.port":
                    protocol, address, port = "TCP", args[0], args[1]
                else:
                    protocol, address, port = args[0], args[1], args[2]
                process_rows.append([identifier, host.get("host"), interface.get("ip"), interface.get("dns"),
                    item["itemid"], item.get("name"), kind, item.get("key_"), key,
                    process_name, commandline, user, protocol, address, port,
                    [row.get("triggerid") for row in attached], unresolved,
                    "配置的匹配条件；不是实际PID/进程快照；端口不代表进程归属"])
        for trigger in triggers:
            referenced = set(text(row["itemid"]) for row in trigger.get("items", []))
            referenced.update(text(row["itemid"]) for row in trigger.get("functions", []))
            hostids = set(text(items[itemid].get("hostid")) for itemid in referenced if itemid in items)
            hostids.update(text(host["hostid"]) for host in trigger.get("hosts", []))
            expression = expanded_expression(trigger, items)
            for identifier in sorted(hostids):
                if identifier not in contexts:
                    continue
                host = owners[identifier]
                if len(hostids.intersection(contexts)) > 1:
                    resolved, unresolved = expression, sorted(set(MACRO.findall(expression)))
                else:
                    resolved, unresolved = resolve_macros(expression, contexts[identifier])
                alert_rows.append([identifier, host.get("host"), primary_interface(host).get("ip"),
                    trigger.get("triggerid"), trigger.get("description"), trigger.get("priority"),
                    trigger.get("status"), trigger.get("expression"), expression, resolved,
                    trigger.get("recovery_mode"), trigger.get("recovery_expression"),
                    trigger.get("dependencies", []), trigger.get("tags", []), sorted(referenced),
                    unresolved, "表达式为阈值真源；复杂函数、宏上下文及多主机表达式须结合原文核对"])
        unavailable = [link for link in links if link["unavailable_templateids"]]
        self.status["host-template-links"] = {"method": "derived", "state": "partial" if unavailable else "ok",
                                              "count": len(links), "unavailable": unavailable}
        self.save("host-template-links", links)
        write_csv(os.path.join(self.output, "主机清单.csv"),
            ["主机ID", "技术名称", "显示名称", "状态", "首选接口IP", "DNS", "useip", "全部接口", "主机组", "直接模板", "全部模板ID", "不可见模板ID", "标签"], host_rows)
        write_csv(os.path.join(self.output, "主机监控项清单.csv"),
            ["主机ID", "主机名称", "显示名称", "首选接口IP", "DNS", "itemid", "指标名称", "原始key", "解析后key", "类型", "值类型", "单位", "周期", "状态", "采集状态", "错误", "interfaceid", "来源父监控项ID", "主监控项ID", "预处理", "API返回最新值", "关联触发器ID", "未解析宏"], item_rows)
        write_csv(os.path.join(self.output, "主机告警阈值清单.csv"),
            ["主机ID", "主机名称", "首选接口IP", "triggerid", "告警名称", "级别", "状态", "原始表达式", "函数展开表达式", "主机宏解析表达式", "恢复模式", "恢复表达式", "依赖", "标签", "关联监控项ID", "未解析宏", "说明"], alert_rows)
        write_csv(os.path.join(self.output, "主机进程端口清单.csv"),
            ["主机ID", "主机名称", "首选接口IP", "DNS", "itemid", "监控项名称", "监控类型", "原始key", "解析后key", "进程名参数", "命令行匹配", "用户限制", "协议或服务", "检查目标地址", "端口", "触发器ID", "未解析宏", "说明"], process_rows)
        partial = [name for name, status in self.status.items() if status["state"] != "ok"]
        manifest = {"api_version": api_version, "script_version": VERSION,
            "scope": "当前账号可见的监控配置；不是数据库全量备份", "datasets": self.status,
            "complete_for_requested_scope": not partial, "partial_datasets": partial,
            "report_counts": {"hosts": len(host_rows), "items": len(item_rows),
                              "triggers": len(alert_rows), "process_ports": len(process_rows)},
            "limitations": ["账号权限限制可能静默隐藏对象，API返回成功不等于全组织完整可见",
                "不导出用户/用户组/联系人/凭证/审计日志；文本/日志历史默认不导出",
                "历史/趋势/事件按配置时间范围导出，启用对应开关且未设置时间范围时读取全部仍保留记录；已过期清理的数据无法恢复",
                "不查询主机实时进程；匹配表达式不是实际PID/可执行文件清单",
                "宏上下文/正则上下文不推测，未知宏原样保留；复杂阈值保留表达式",
                "按主机分批获取；单主机监控项数仍受API服务端资源及限制影响"]}
        self.save("export-manifest", manifest)
        return not partial


def export_monitoring(client, output, api_version):
    exporter = Exporter(client, output)
    template_params = {"output": "extend", "selectParentTemplates": ["templateid", "host", "name"],
                       "selectMacros": "extend", "selectGroups": "extend", "selectTags": "extend"}
    templates = exporter.collect("templates-api", "template.get", template_params, identity="templateid")
    if templates or TEMPLATE_IDS or TEMPLATE_NAMES:
        roots, selected = choose_templates(templates, [text(value) for value in TEMPLATE_IDS], TEMPLATE_NAMES, EXPORT_ALL)
    else:
        roots, selected = set(), []
    template_ids = [text(row["templateid"]) for row in selected]
    exporter.status["templates-export"] = {"method": "configuration.export", "state": "ok", "count": 0}
    try:
        if template_ids:
            raw = client.call("configuration.export", {"options": {"templates": template_ids}, "format": "json"})
            exported = json.loads(raw)
            document = exported["zabbix_export"]
            actual = set(row["template"] for row in document.get("templates", []))
            if actual != set(row["host"] for row in selected) or text(document.get("version")) != "5.4":
                raise ExportError("[export_monitoring] 模板集合或文档版本不匹配")
        else:
            exported = {"zabbix_export": {"version": "5.4", "templates": []}}
        exporter.save("templates", exported)
        exporter.status["templates-export"]["count"] = len(selected)
    except Exception:
        details = client.safe_error(traceback.format_exc())
        LOGGER.error("[export_monitoring.templates] %s", details)
        exporter.status["templates-export"].update({"state": "partial", "error": details})
    host_params = {"output": "extend", "selectInterfaces": "extend", "selectParentTemplates": ["templateid", "host", "name"],
                   "selectMacros": "extend", "selectGroups": "extend", "selectTags": "extend", "selectInheritedTags": "extend", "selectInventory": "extend", "selectDiscoveryRule": "extend", "selectHostDiscovery": "extend"}
    if HOST_IDS:
        host_params["hostids"] = [text(value) for value in HOST_IDS]
    hosts = exporter.collect("hosts", "host.get", host_params, identity="hostid") if EXPORT_HOSTS else []
    owner_ids = template_ids + [text(host["hostid"]) for host in hosts]
    exporter.collect("global-macros", "usermacro.get", {"output": "extend", "globalmacro": True}, identity="globalmacroid")
    item_params = {"output": "extend", "selectPreprocessing": "extend", "selectTags": "extend", "selectValueMap": "extend"}
    items = exporter.collect("items", "item.get", item_params, owner_ids, "itemid")
    trigger_params = {"output": "extend", "selectHosts": ["hostid", "host", "name"],
                      "selectItems": ["itemid"], "selectFunctions": "extend", "selectDependencies": "extend", "selectTags": "extend"}
    triggers = exporter.collect("triggers", "trigger.get", trigger_params, owner_ids, "triggerid")
    prototypes = exporter.collect("trigger-prototypes", "triggerprototype.get", trigger_params, owner_ids, "triggerid")
    exporter.collect("discovery-rules", "discoveryrule.get", {"output": "extend", "selectFilter": "extend", "selectPreprocessing": "extend", "selectOverrides": "extend", "selectLLDMacroPaths": "extend"}, owner_ids, "itemid")
    exporter.collect("item-prototypes", "itemprototype.get", item_params, owner_ids, "itemid")
    for name, method, identity, params in (
        ("graphs", "graph.get", "graphid", {"selectGraphItems": "extend"}),
        ("graph-prototypes", "graphprototype.get", "graphid", {"selectGraphItems": "extend"}),
        ("web-scenarios", "httptest.get", "httptestid", {"selectSteps": "extend", "selectTags": "extend"}),
        ("host-prototypes", "hostprototype.get", "hostid", {"selectGroupLinks": "extend", "selectGroupPrototypes": "extend", "selectTemplates": "extend"})):
        params["output"] = "extend"
        exporter.collect(name, method, params, owner_ids, identity)
    if EXPORT_EXTENDED:
        for name, method, params in (
            ("host-groups", "hostgroup.get", {"output": "extend"}),
            ("value-maps", "valuemap.get", {"output": "extend", "selectMappings": "extend"}),
            ("actions", "action.get", {"output": "extend", "selectFilter": "extend", "selectOperations": "extend", "selectRecoveryOperations": "extend", "selectAcknowledgeOperations": "extend"}),
            ("maintenance", "maintenance.get", {"output": "extend", "selectHosts": ["hostid"], "selectGroups": ["groupid"], "selectTimeperiods": "extend", "selectTags": "extend"}),
            ("proxies", "proxy.get", {"output": "extend", "selectInterface": "extend", "selectHosts": ["hostid", "host", "name"]}),
            ("network-discovery", "drule.get", {"output": "extend", "selectDChecks": "extend"}),
            ("correlations", "correlation.get", {"output": "extend", "selectFilter": "extend", "selectOperations": "extend"}),
            ("services", "service.get", {"output": "extend", "selectDependencies": "extend", "selectParentDependencies": "extend", "selectTimes": "extend", "selectAlarms": "extend", "selectTrigger": "extend"}),
            ("maps", "map.get", {"output": "extend", "selectSelements": "extend", "selectLinks": "extend"}),
            ("dashboards", "dashboard.get", {"output": "extend", "selectPages": "extend"}),
            ("media-types", "mediatype.get", {"output": "extend", "selectMessageTemplates": "extend"}),
            ("scripts", "script.get", {"output": "extend", "selectGroups": ["groupid", "name"]}),
            ("images", "image.get", {"output": "extend", "select_image": True}),
            ("discovered-hosts", "dhost.get", {"output": "extend", "selectDServices": "extend"}),
            ("discovered-services", "dservice.get", {"output": "extend"})):

            exporter.collect(name, method, params)
    exporter.save("alert-rules", {"triggers": triggers, "trigger_prototypes": prototypes, "items": items})
    exporter.save("template-index", {"api_version": api_version, "script_version": VERSION,
        "root_templateids": sorted(roots), "templates": selected, "sanitized": True,
        "notes": ["实际主机及IP见hosts.json，模板ID不是主机ID", "全量可见监控配置；导出完整性见export-manifest.json"]})
    export_operational(exporter, hosts, items)
    return exporter.report(api_version)


def time_pages(client, method, params, start, end):
    pending = [(start, end)]
    while pending:
        lower, upper = pending.pop()
        query = dict(params, output="extend", time_from=lower, time_till=upper, limit=PAGE_SIZE)
        response = client.call(method, query)
        if not isinstance(response, list) or any(not isinstance(row, dict) for row in response):
            raise ExportError("[time_pages] API未返回对象数组: " + method)
        if len(response) < PAGE_SIZE:
            for row in response:
                yield row
        elif lower < upper:
            middle = (lower + upper) // 2
            pending.extend([(middle + 1, upper), (lower, middle)])
        else:
            raise ExportError("[time_pages] 同一秒记录达到PAGE_SIZE，无法保证完整性；请调大PAGE_SIZE后重跑: " + method)


def id_pages(client, method, params, start, end):
    cursor = 0
    while True:
        query = dict(params, output="extend", time_from=start, time_till=end,
                     eventid_from=text(cursor), sortfield="eventid", sortorder="ASC", limit=PAGE_SIZE)
        rows = client.call(method, query)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ExportError("[id_pages] API未返回对象数组: " + method)
        for row in rows:
            if int(row["eventid"]) < cursor:
                raise ExportError("[id_pages] API未遵循事件ID游标")
            yield row
        if not rows:
            break
        following = max(int(row["eventid"]) for row in rows) + 1
        if following <= cursor:
            raise ExportError("[id_pages] 事件ID游标没有前进")
        cursor = following


def export_operational(exporter, hosts, items):
    import time
    start = 0 if DATA_TIME_FROM is None else int(DATA_TIME_FROM)
    end = int(time.time()) if DATA_TIME_TILL is None else int(DATA_TIME_TILL)
    if start < 0 or end < start:
        raise ExportError("[export_operational] 时间范围无效，使用Unix秒时间戳或None")
    directory = os.path.join(exporter.output, "operational")
    os.mkdir(directory, 0o700)
    hostids = set(text(row["hostid"]) for row in hosts)
    hostitems = [row for row in items if text(row.get("hostid")) in hostids]
    requests = []
    if EXPORT_EVENTS:
        sources = [(0, 0), (1, 1), (1, 2), (2, 3), (3, 0), (3, 4), (3, 5)]
        for source, object_ in sources:
            params = {"source": source, "object": object_}
            if source == 0:
                params.update({"selectTags": "extend", "selectSuppressionData": "extend", "select_acknowledges": "extend"})
            if HOST_IDS and source in (0, 3):
                params["hostids"] = list(hostids)
            requests.append(("events-%s-%s" % (source, object_), "event.get", params, id_pages))
            if source in (0, 3):
                problem_params = dict(params, recent=True, selectTags="extend", selectSuppressionData="extend")
                requests.append(("problems-%s-%s" % (source, object_), "problem.get", problem_params, id_pages))
            alert_params = {"eventsource": source, "eventobject": object_}
            if HOST_IDS and source in (0, 3):
                alert_params["hostids"] = list(hostids)
            requests.append(("alerts-%s-%s" % (source, object_), "alert.get", alert_params, time_pages))
    for kind, enabled in (("history", EXPORT_HISTORY), ("trends", EXPORT_TRENDS)):
        if not enabled:
            continue
        method = "history.get" if kind == "history" else "trend.get"
        for item in hostitems:
            value_type = text(item.get("value_type", ""))
            if value_type not in ("0", "3") and (kind == "trends" or not EXPORT_TEXT_HISTORY):
                continue
            params = {"itemids": [text(item["itemid"])]}
            if kind == "history":
                params["history"] = int(value_type)
            requests.append((kind + "-" + text(item["itemid"]), method, params, time_pages))
    for name, method, params, pager in requests:
        status = {"method": method, "state": "ok", "count": 0,
                  "time_from": start, "time_till": end, "file": "operational/" + name + ".jsonl"}
        exporter.status[name] = status
        descriptor = os.open(os.path.join(exporter.output, status["file"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            try:
                for row in pager(exporter.client, method, params, start, end):
                    stream.write((json.dumps(sanitize(row), ensure_ascii=False) + "\n").encode("utf-8"))
                    status["count"] += 1
            except Exception:
                details = exporter.client.safe_error(traceback.format_exc())
                LOGGER.error("[export_operational] dataset=%s %s", name, details)
                status.update({"state": "partial", "error": details})
    exporter.save("data-scope", {"events": EXPORT_EVENTS, "history": EXPORT_HISTORY, "trends": EXPORT_TRENDS,
                  "text_history": EXPORT_TEXT_HISTORY, "time_from": start, "time_till": end,
                  "notes": ["JSONL逐条落盘，不把历史数据全部放进内存", "历史按可见且仍存在的主机监控项导出，已删除监控项及过期数据不在可恢复范围内",
                            "配置和历史不是事务快照；导出期间发生的配置变化可能造成差异", "未导出用户/联系人/凭证/审计日志"]})


def parser():
    argument_parser = ArgumentParser(description="Zabbix 5.4 可见监控配置只读导出：主机/IP、模板继承、指标、进程端口、告警表达式和宏。Python 2.7.9+/3，无第三方依赖。先修改脚本顶部配置。", epilog="运行：python %(prog)s\n所有连接参数在脚本顶部配置；默认校验证书、强制脱敏。\nZABBIX_URL=最终API站点；ZABBIX_TOKEN优先，否则使用ZABBIX_USER/ZABBIX_PASSWORD。\nOUTPUT_DIR=exports；TIMEOUT=120；INSECURE=False；EXPORT_ALL=True；EXPORT_HOSTS=True。\nTEMPLATE_IDS/TEMPLATE_NAMES=[]：筛选模板（不限制主机）；HOST_IDS=[]：全部可见主机。\nBATCH_SIZE=25：每批主机/模板数；EXPORT_EXTENDED=True：补充动作、维护、图形等配置。\nFAIL_ON_PARTIAL=True：任一数据集失败仍保存其余结果，最终退出2；正常退出0；致命错误退出1。\nEXPORT_HISTORY=False、EXPORT_TRENDS=False：指标历史及趋势默认不导出，True时保留全量导出能力。\nEXPORT_EVENTS=True：告警事件/通知记录单独控制；PAGE_SIZE=5000；DATA_TIME_FROM/TILL=None为全部保留期。\nEXPORT_TEXT_HISTORY=False：文本/日志可能含敏感信息，默认排除。\n不导出用户凭证；退出码0只表示API请求成功，不保证账号能看到所有组织数据。", formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--version", action="version", version=VERSION)
    return argument_parser


def main(argv=None):
    parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=UTF8Stream(sys.stderr))
    client = None
    try:
        if not ZABBIX_URL or (not ZABBIX_TOKEN and (not ZABBIX_USER or not ZABBIX_PASSWORD)):
            raise ExportError("[main] 配置URL及Token，或URL/用户名/密码；凭证不要贴到群聊")
        if TIMEOUT <= 0 or BATCH_SIZE <= 0 or PAGE_SIZE <= 0:
            raise ExportError("[main] TIMEOUT、BATCH_SIZE、PAGE_SIZE须为正整数")
        client = Client(cli_text(ZABBIX_URL), TIMEOUT, INSECURE)
        api_version = client.call("apiinfo.version", [], authenticated=False)
        if not text(api_version).startswith("5.4."):
            raise ExportError("[main] 仅支持Zabbix 5.4.x，实际版本=" + text(api_version))
        if ZABBIX_TOKEN:
            client.auth = cli_text(ZABBIX_TOKEN)
            client.secrets.append(client.auth)
        else:
            client.login(cli_text(ZABBIX_USER), cli_text(ZABBIX_PASSWORD))
        root = os.path.abspath(os.path.expanduser(cli_text(OUTPUT_DIR)))
        if not os.path.isdir(root):
            os.makedirs(root, 0o700)
        output = os.path.join(root, "zabbix54_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        os.mkdir(output, 0o700)
        complete = export_monitoring(client, output, api_version)
        write_text(sys.stdout, text(output) + "\n")
        return 0 if complete or not FAIL_ON_PARTIAL else 2
    except Exception:
        details = traceback.format_exc()
        LOGGER.error("[main] %s", client.safe_error(details) if client else details)
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
