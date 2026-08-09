#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
easyops_client.py —— EasyOps 通用 HTTP 客户端 SDK（py2/3 兼容）。

定位（platforms/demo onboarding 沉淀）：
  - 双模式：internal（直连后端组件，如 tool_service :8181 / cmdb_service :8079）
            / openapi（走 EasyOps openapi 网关，Host 头切换）
  - 从 api-cli 清单 yaml 反射具名调用（client.tool.list(name='cmdb')）——pyyaml 可选
  - 原生支持二进制/多部分（导出 tar.gz / 导入 multipart）——补 api-cli 的能力缺口
  - 给 EasyOps 工具脚本运行时用（agent /usr/local/easyops/python/bin/python），
    也服务任何 easyops 自动化场景。

依赖：requests（agent 自带 python 已装）。pyyaml 可选（用于 load_spec 反射具名方法）。

快速上手：
    from easyops_client import EasyOpsClient
    c = EasyOpsClient(org=18832008, user='easyops', cookie='PHPSESSID=xxx',
                      mode='internal', base_url='http://172.30.0.232:8181',
                      host='admin.easyops.local', verify=False)
    c.load_spec('easyops-autoops.yaml')            # 可选：反射具名方法
    print(c.tool.list(name='cmdb'))                 # 具名（需 load_spec）
    print(c.call('GET', '/tools', params={'name': 'cmdb'}))   # 通用兜底
    c.export_tool(toolId, versionId, save_to='t.tar.gz')      # 二进制下载
    c.import_tool('pkg.tar.gz')                               # multipart 上传

坑提醒（详见 objects.yaml / entities.yaml）：
  - 导出/删除用 versionId；get/run 用 vId——同名概念两种参数名
  - 删除是软删（delete_me）；force 仅绕 ReadOnly
  - 工具脚本里用 $EASYOPS_* 环境变量，不存在 __instance__/${cmdb.xxx}
"""
from __future__ import print_function

import os
import sys
import io
import json
import time
import logging

PY2 = sys.version_info[0] == 2

try:
    import requests
except ImportError:  # pragma: no cover
    raise ImportError("easyops_client 依赖 requests，请先安装：pip install requests")

# py2/3 字符串类型兼容
if PY2:
    text = unicode  # noqa: F821  pylint: disable=undefined-variable
else:
    text = str


class EasyOpsError(Exception):
    """EasyOps 调用异常。含 code/message/resp。"""

    def __init__(self, code, message, resp=None):
        self.code = code
        self.message = message
        self.resp = resp
        super(EasyOpsError, self).__init__("[%s] %s" % (code, message))


class _Resource(object):
    """load_spec 后的 resource 代理：client.tool.list(...) → client._invoke(...)。"""

    def __init__(self, client, resource, ops):
        self._client = client
        self._resource = resource
        self._ops = ops  # {verb: {method, path, params:{name:{in, ...}}}}

    def __getattr__(self, verb):
        if verb.startswith('_'):
            raise AttributeError(verb)
        if verb not in self._ops:
            raise AttributeError(
                "resource %s 无 verb %s（可用: %s）" % (self._resource, verb, list(self._ops)))
        spec = self._ops[verb]

        def _invoke(*path_args, **kwargs):
            return self._client._invoke(self._resource, verb, spec, path_args, kwargs)

        _invoke.__name__ = str(verb)
        return _invoke


class EasyOpsClient(object):
    """EasyOps 通用 HTTP 客户端（py2/3）。

    :param org:      租户号（请求头 org）；默认取 env EASYOPS_ORG
    :param user:     用户标识（请求头 user）；默认取 env EASYOPS_USER
    :param cookie:   PHPSESSID cookie（'PHPSESSID=xxx'）；默认取 env EASYOPS_COOKIE
                     或 ~/.api-cli/auth.d/easyops-cookie.yaml（与 api-cli 共用凭证）
    :param mode:     'internal'（直连后端组件）/ 'openapi'（走 openapi 网关）
    :param base_url: 后端/openapi 地址（含端口，如 http://172.30.0.232:8181）；
                     默认取 env EASYOPS_AUTOOPS_BACKEND_URL → EASYOPS_CMDB_BACKEND_URL
    :param host:     可选 Host 头（IP 直连时设 admin.easyops.local，网关按 Host 路由）
    :param verify:   TLS 证书校验（EasyOps 自签证书默认 False）
    :param timeout:  HTTP 超时秒
    :param logger:   自定义 logger；默认 'easyops'，DEBUG 到 stderr
    :param log_level:默认 DEBUG（打印请求/响应全文，便于 agent 调试）
    """

    def __init__(self, org=None, user=None, cookie=None, mode='internal',
                 base_url=None, host=None, verify=False, timeout=30,
                 logger=None, log_level=logging.DEBUG):
        self.org = org or os.environ.get('EASYOPS_ORG')
        self.user = user or os.environ.get('EASYOPS_USER')
        self.cookie = cookie or os.environ.get('EASYOPS_COOKIE')
        if not self.cookie:
            self.cookie = self._read_cookie_from_auth()
        self.mode = mode
        self.base_url = (base_url or os.environ.get('EASYOPS_AUTOOPS_BACKEND_URL') or
                         os.environ.get('EASYOPS_CMDB_BACKEND_URL', '')).rstrip('/')
        self.host = host
        self.verify = verify
        self.timeout = timeout

        # logger：默认 'easyops'，DEBUG 到 stderr（agent 调试友好）
        self.logger = logger or logging.getLogger('easyops')
        if not self.logger.handlers:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter('[%(levelname)s easyops] %(message)s'))
            self.logger.addHandler(h)
        self.logger.setLevel(log_level)

        if not self.org or not self.user:
            self.logger.warning("缺少 org/user（env EASYOPS_ORG/EASYOPS_USER）——直连后端会报 empty org/user")
        if not self.cookie:
            self.logger.warning("缺少 cookie（PHPSESSID）——鉴权会失败")
        if not self.base_url:
            self.logger.warning("缺少 base_url（env EASYOPS_AUTOOPS_BACKEND_URL）——调用会失败")

        self._specs = {}  # {resource: {verb: spec}} —— load_spec 后填充

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------
    @staticmethod
    def _read_cookie_from_auth():
        """从 ~/.api-cli/auth.d/easyops-cookie.yaml 读 PHPSESSID（与 api-cli 共用凭证）。"""
        path = os.path.expanduser('~/.api-cli/auth.d/easyops-cookie.yaml')
        if not os.path.exists(path):
            return None
        try:
            import yaml
            data = yaml.safe_load(io.open(path, 'r', encoding='utf-8')) or {}
            val = data.get('cookie') or data.get('value') or data.get('PHPSESSID')
            if val:
                return val if text(val).startswith('PHPSESSID') else 'PHPSESSID=' + text(val)
        except Exception:
            pass
        return None

    def _headers(self, extra=None):
        """构造请求头：org + user + Cookie + Host（直连用）。"""
        h = {
            'org': text(self.org) if self.org is not None else '',
            'user': text(self.user) if self.user is not None else '',
        }
        if self.cookie:
            h['Cookie'] = self.cookie
        if self.host:
            h['Host'] = self.host
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------
    # 通用调用（核心，不依赖 yaml）
    # ------------------------------------------------------------------
    def call(self, method, path, params=None, body=None, headers=None, **kw):
        """通用 HTTP 调用。method/path 相对 base_url。

        - JSON 响应自动解析为 dict/list；非 JSON 返回 bytes
        - 分级日志：DEBUG 全量请求/响应，INFO 摘要，WARNING 非 0 code
        - 业务 code != 0 抛 EasyOpsError

        :return: dict/list（JSON）或 bytes（二进制）
        """
        url = self.base_url + path
        hdrs = self._headers(headers)
        body_desc = body
        if isinstance(body, (bytes, bytearray)):
            body_desc = '<bytes:%dB>' % len(body)
        self.logger.debug("-> %s %s | params=%s | body=%s", method, url, params, body_desc)
        resp = requests.request(method, url, params=params, json=body, headers=hdrs,
                                verify=self.verify, timeout=self.timeout, **kw)
        self.logger.debug("<- %s | %dB | ctype=%s", resp.status_code, len(resp.content),
                          resp.headers.get('Content-Type', ''))
        # JSON 优先解析（easyops 绝大多数接口走 {code,data} wrapper）
        try:
            data = resp.json()
        except ValueError:
            data = resp.content
        # 业务 code 检查（仅对 JSON wrapper）
        if isinstance(data, dict) and 'code' in data:
            code = data.get('code')
            if code not in (0, None, '0'):
                msg = data.get('error') or data.get('message') or 'unknown'
                self.logger.warning("业务错误 code=%s msg=%s", code, msg)
                raise EasyOpsError(code, msg, data)
            self.logger.info("OK %s %s (code=0)", method, path)
        return data

    def request(self, method, path, **kw):
        """call 的别名（贴近 requests 风格）。"""
        return self.call(method, path, **kw)

    # ------------------------------------------------------------------
    # load_spec：从 api-cli yaml 反射具名方法（需 pyyaml，可选）
    # ------------------------------------------------------------------
    def load_spec(self, yaml_path):
        """读 api-cli 清单 yaml，为每个 resource.verb 反射出具名方法。

        调用后即可：client.tool.list(name='cmdb') / client.tool_execution.run(body={...})
        / client.tool.get('<toolId>', vId='$latest_production')（path 参数按位置传，
        query/body 按关键字传）。

        需 pyyaml；不可用则警告并跳过（仍可用 call('GET', '/tools', ...) 兜底）。
        """
        try:
            import yaml
        except ImportError:
            self.logger.warning("无 pyyaml，跳过 load_spec（可用 call(method,path,...) 兜底）")
            return self
        with io.open(yaml_path, 'r', encoding='utf-8') as f:
            spec = yaml.safe_load(f)
        resources = spec.get('resources', {}) or {}
        for rname, rdef in resources.items():
            ops = {}
            for verb, odef in (rdef.get('operations') or {}).items():
                ops[verb] = {
                    'method': odef.get('method', 'GET'),
                    'path': odef.get('path', ''),
                    'params': odef.get('params') or {},
                }
            self._specs[rname] = ops
            setattr(self, rname, _Resource(self, rname, ops))
        self.logger.info("load_spec: %d resources 反射完成 (%s)", len(resources), list(resources))
        return self

    def _invoke(self, resource, verb, spec, path_args, kwargs):
        """load_spec 后 _Resource 调用的内部实现：构造 method/path/params/body 并 call。

        path 参数（params.in==path）按位置（path_args）或同名关键字填进 path 模板；
        query 参数（in==query）进 params；其余按 method 决定（写操作进 body）。
        """
        method = spec['method']
        path = spec['path']
        params_spec = spec['params']
        path_param_names = [p for p, d in params_spec.items() if d.get('in') == 'path']

        # path 参数按位置填（api-cli 风格）
        for i, pname in enumerate(path_param_names):
            if i < len(path_args):
                path = path.replace('{%s}' % pname, text(path_args[i]))

        query = {}
        body = None
        is_write = method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE')
        for k, v in kwargs.items():
            if '{%s}' % k in path:
                path = path.replace('{%s}' % k, text(v))
            elif k == 'body':
                body = v
            elif k in params_spec and params_spec[k].get('in') == 'query':
                query[k] = v
            elif is_write and k not in params_spec:
                body = body or {}
                body[k] = v
            else:
                query[k] = v
        return self.call(method, path, params=query or None, body=body)

    # ------------------------------------------------------------------
    # 二进制/多部分（补 api-cli 缺口）
    # ------------------------------------------------------------------
    def export_tool(self, toolId, versionId, save_to, compatibility=None):
        """导出工具为 tar.gz（GET /tools/{toolId}/export?versionId=），流式存盘。

        :param toolId: 工具 ID（32 hex）
        :param versionId: 版本 ID（32 hex；⚠️参数名 versionId 非 vId！）
        :param save_to: 落盘路径
        :param compatibility: 可选兼容性标签（仅进 tar 文件名）
        :return: 保存路径
        """
        path = '/tools/%s/export' % toolId
        params = {'versionId': versionId}
        if compatibility:
            params['compatibility'] = compatibility
        url = self.base_url + path
        hdrs = self._headers()
        self.logger.debug("-> GET %s export -> %s", url, save_to)
        r = requests.get(url, params=params, headers=hdrs, verify=self.verify,
                         timeout=self.timeout, stream=True)
        if r.status_code != 200:
            raise EasyOpsError(r.status_code, "导出失败: %s" % r.text[:200], r)
        n = 0
        with open(save_to, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    n += len(chunk)
        self.logger.info("OK 导出 %s (%dB -> %s)", toolId, n, save_to)
        return save_to

    def import_tool(self, file_path, systemImport=None, tools=None):
        """导入工具包（POST /tools/import，multipart/form-data）。upsert。

        :param file_path: .tar.gz 文件路径
        :param systemImport: 是否平台系统导入
        :param tools: 可选 tools 元数据（list）
        :return: 导入结果 dict（含每工具 importType=create|update）
        """
        path = '/tools/import'
        url = self.base_url + path
        hdrs = self._headers()
        params = {}
        if systemImport is not None:
            params['systemImport'] = systemImport
        self.logger.debug("-> POST %s import <- %s", url, file_path)
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            data = {}
            if tools is not None:
                data['tools'] = json.dumps(tools)
            r = requests.post(url, params=params, files=files, data=data,
                              headers=hdrs, verify=self.verify, timeout=self.timeout)
        try:
            result = r.json()
        except ValueError:
            result = {'status': r.status_code, 'raw': r.text}
        self.logger.info("OK 导入 %s status=%s", file_path, r.status_code)
        return result

    # ------------------------------------------------------------------
    # 便捷：执行工具 + 轮询（场景4）
    # ------------------------------------------------------------------
    def run_and_wait(self, toolId, inputs=None, agents=None, vId='$latest_production',
                     poll_interval=2, max_wait=600):
        """执行工具并轮询到完成，返回 {execId, status, table, result}。

        场景4『run_cmd 查主机内存』便捷封装：POST /tools/execution → 轮询 status → 取 table。
        目标主机走 inputs 里 type=cmdbInstances 的 @agents 入参（平台按目标解析实例）。

        :return: dict；若 run 未返回 execId 直接返回 run 结果
        """
        body = {'toolId': toolId, 'vId': vId}
        if inputs:
            body['inputs'] = inputs
        if agents:
            body['agents'] = agents
        run = self.call('POST', '/tools/execution', body=body)
        execId = (run.get('data') or {}).get('execId')
        if not execId:
            return run

        status = None
        waited = 0
        while waited < max_wait:
            st = self.call('GET', '/tools/execution/status/%s' % execId)
            status = (st.get('data') or {}).get('status') or (st.get('data') or {}).get('Status')
            self.logger.debug("exec %s status=%s (waited=%ss)", execId, status, waited)
            if text(status).lower() in ('success', 'failed'):
                break
            time.sleep(poll_interval)
            waited += poll_interval

        result = self.call('GET', '/tools/execution/result/%s' % execId)
        table = self.call('GET', '/tools/execution/table/%s' % execId)
        return {'execId': execId, 'status': status, 'result': result, 'table': table}


# ---------------------------------------------------------------------------
# 自测：python easyops_client.py（不真调，只验证 import + 构造 + load_spec 反射）
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import tempfile
    c = EasyOpsClient(org='18832008', user='easyops', cookie='PHPSESSID=test',
                      base_url='http://127.0.0.1:8181', host='admin.easyops.local', verify=False)
    # 找同目录的 easyops-autoops.yaml 试反射
    here = os.path.dirname(os.path.abspath(__file__))
    spec_path = os.path.join(here, 'easyops-autoops.yaml')
    if os.path.exists(spec_path):
        c.load_spec(spec_path)
        print("反射的 resources:", list(c._specs))
        print("tool verbs:", list(c._specs.get('tool', {})))
        print("tool_execution verbs:", list(c._specs.get('tool_execution', {})))
    else:
        print("（未找到 easyops-autoops.yaml，跳过 load_spec 反射验证）")
    print("easyops_client 自测通过（py%d）" % sys.version_info[0])
