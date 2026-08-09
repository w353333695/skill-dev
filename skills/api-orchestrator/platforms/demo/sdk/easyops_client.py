#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ⚠️ 本文件【不要】用 `from __future__ import ...`——EasyOps 工具库下发执行时，平台会在
# 脚本开头注入内部方法/变量，使 __future__ 不在文件首行，触发 SyntaxError:
# from __future__ imports must occur at the beginning of the file。
# py2/3 兼容改用运行时判断（见下方 PY2 / text）+ logging（不直接 print）。
# 坑详见 platforms/demo/objects.yaml#api_behavior.tool_script_no_future。
"""
easyops_client.py —— EasyOps 通用 HTTP 客户端（py2/3，自包含，双模式）。

定位：给 EasyOps 工具脚本运行时（agent /usr/local/easyops/python/bin/python）调 easyops
      API 用；也可用于任何 easyops 自动化。【自包含】——不依赖任何 yaml/外部代码文件，
      单文件即可运行（仅依赖 requests）。

双模式（互斥）：
  - openapi（外网 / 非内网首选）：AK/SK HMAC-SHA1 签名，走 openapi 网关
    （openapi.easyops-only.com）。不直连组件端口（8181 等），适合非内网环境。
    签名协议：StringToSign = method\\npath\\nparams\\ncontent-type\\ncontent-md5\\n
              timestamp\\naccessKey；signature=HMAC-SHA1(secret_key, StringToSign) hex；
              accesskey/signature/expires 放 query，Host 放 header。
  - internal（内网）：直连组件端口 + org/user header + cookie。

依赖：requests（agent 自带 python 已装）。仅此一项。

快速上手：
    from easyops_client import EasyOpsClient, EasyOpsError
    # openapi（外网，AK/SK）
    c = EasyOpsClient(mode='openapi', access_key='ak', secret_key='sk')
    c.list_tools(name='cmdb')                 # 便捷方法（autoops 端点路径内置）
    c.execute_tool(toolId, inputs={'cmd': 'free -m'}, vId='<具体vId>')  # ⚠️inputs 是 map
    # internal（内网，org/user/cookie）
    c = EasyOpsClient(mode='internal', base_url='http://172.30.0.232:8181',
                      org='18832008', user='easyops', cookie='PHPSESSID=xxx')
    c.call('GET', '/tools', params={'name': 'cmdb'})  # 通用兜底

便捷方法（autoops）：list_tools / get_tool / create_tool / update_tool / delete_tool /
list_versions / execute_tool / get_exec_status/result/table / export_tool / import_tool /
run_and_wait。通用兜底：call(method, path, params=, body=)。

坑（详见各方法 docstring + objects.yaml e2e_findings）：
  - update body **flat**（非 {tool:{}}）；改 version 字段派生新版本（development）
  - execute inputs 是 **map**（{name:value}，非数组）
  - run vId 对 development 工具用具体值（$latest_production 报 100005）
  - 导出/删除用 versionId（非 vId）
  - 本文件勿用 from __future__（工具库 header 注入破坏）
"""
import os
import sys
import json
import time
import hmac
import hashlib
import logging

PY2 = sys.version_info[0] == 2
if PY2:
    text = unicode  # noqa: F821  pylint: disable=undefined-variable
else:
    text = str

try:
    import requests
except ImportError:  # pragma: no cover
    raise ImportError("easyops_client 依赖 requests，请先安装：pip install requests")


def _md5_hex(data):
    """body 的 md5 hex（openapi 签名 Content-MD5 段用）。"""
    if isinstance(data, text):
        data = data.encode('utf-8')
    return hashlib.md5(data).hexdigest()


def _hmac_sha1_hex(secret, msg):
    """HMAC-SHA1 hex（easyops openapi 签名）。secret/msg 均 utf-8 编码。"""
    if isinstance(secret, text):
        secret = secret.encode('utf-8')
    if isinstance(msg, text):
        msg = msg.encode('utf-8')
    return hmac.new(secret, msg, hashlib.sha1).hexdigest()


class EasyOpsError(Exception):
    """EasyOps 调用异常（含业务 code != 0 或 HTTP/配置错误）。"""

    def __init__(self, code, message, resp=None):
        self.code = code
        self.message = message
        self.resp = resp
        super(EasyOpsError, self).__init__("[%s] %s" % (code, message))


class EasyOpsClient(object):
    """EasyOps 通用 HTTP 客户端（py2/3，自包含，openapi/internal 双模式）。

    :param mode: 'openapi'（AK/SK 签名走网关，外网首选）或 'internal'（直连组件端口，内网）
    :param access_key/secret_key: openapi 模式的 AK/SK（默认取 env EASYOPS_OPENAPI_AK/SK）
    :param openapi_host: openapi 网关 host（默认 openapi.easyops-only.com）
    :param base_url: internal 模式的组件地址（含端口，如 http://172.30.0.232:8181）；
                     默认取 env EASYOPS_AUTOOPS_BACKEND_URL。openapi 模式若不给则用 https://openapi_host
    :param org/user/cookie: internal 模式鉴权（默认取 env EASYOPS_ORG/USER/COOKIE）
    :param verify: TLS 证书校验（自签证书默认 False）
    :param timeout: HTTP 超时秒
    :param logger/log_level: 日志（默认 'easyops'，INFO 到 stderr）
    """

    def __init__(self, mode='openapi', access_key=None, secret_key=None,
                 openapi_host='openapi.easyops-only.com', base_url=None,
                 org=None, user=None, cookie=None, host=None, verify=False, timeout=30,
                 logger=None, log_level=logging.INFO):
        self.mode = mode
        self.verify = verify
        self.timeout = timeout
        self.logger = logger or logging.getLogger('easyops')
        if not self.logger.handlers:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter('[%(levelname)s easyops] %(message)s'))
            self.logger.addHandler(h)
        self.logger.setLevel(log_level)

        if mode == 'openapi':
            self.access_key = access_key or os.environ.get('EASYOPS_OPENAPI_AK')
            self.secret_key = secret_key or os.environ.get('EASYOPS_OPENAPI_SK')
            self.openapi_host = openapi_host
            self.base_url = (base_url or ('https://' + openapi_host)).rstrip('/')
            if not self.access_key or not self.secret_key:
                raise EasyOpsError('CONFIG', 'openapi 模式需要 access_key/secret_key（参数或 env EASYOPS_OPENAPI_AK/SK）')
            self.logger.debug("openapi 模式: %s AK=%s...", self.base_url, self.access_key[:6])
        elif mode == 'internal':
            self.base_url = (base_url or os.environ.get('EASYOPS_AUTOOPS_BACKEND_URL', '')).rstrip('/')
            self.org = org or os.environ.get('EASYOPS_ORG')
            self.user = user or os.environ.get('EASYOPS_USER')
            self.cookie = cookie or os.environ.get('EASYOPS_COOKIE')
            self.host = host  # 直连 IP 时设 admin.easyops.local（网关/服务按 Host 路由）
            if not self.base_url:
                raise EasyOpsError('CONFIG', 'internal 模式需要 base_url（如 http://ip:8181）')
            self.logger.debug("internal 模式: %s org=%s user=%s", self.base_url, self.org, self.user)
        else:
            raise EasyOpsError('CONFIG', "mode 只能是 'openapi' 或 'internal'，收到: %s" % mode)

    # ------------------------------------------------------------------
    # openapi AK/SK 签名（HMAC-SHA1）
    # ------------------------------------------------------------------
    def _sign(self, method, path, query, content_type, body_bytes):
        """构造 easyops openapi 签名。返回 (query_dict, header_dict)。

        - Parameters 段：仅 GET，query 按 key 升序以 key+value 串联（无分隔符）；其余空串
        - Content-MD5 段：仅 POST/PUT，body 的 md5 hex；其余空串
        - expires = timestamp（同一值既进签名串也作 query）
        """
        ts = text(int(time.time()))
        if method == 'GET' and query:
            params_str = ''.join(text(k) + text(query[k]) for k in sorted(query.keys()))
        else:
            params_str = ''
        if method in ('POST', 'PUT') and body_bytes:
            content_md5 = _md5_hex(body_bytes)
        else:
            content_md5 = ''
        string_to_sign = '\n'.join([method, path, params_str, content_type, content_md5, ts, self.access_key])
        signature = _hmac_sha1_hex(self.secret_key, string_to_sign)
        q = dict(query or {})
        q.update({'accesskey': self.access_key, 'signature': signature, 'expires': ts})
        return q, {'Host': self.openapi_host, 'Content-Type': content_type}

    def _internal_headers(self, content_type):
        """internal 模式请求头（org/user/cookie）。直连后端实测 cookie 非必需，org/user 必需。"""
        h = {'Content-Type': content_type}
        if self.host:
            h['Host'] = self.host
        if self.org is not None:
            h['org'] = text(self.org)
        if self.user is not None:
            h['user'] = text(self.user)
        if self.cookie:
            h['Cookie'] = self.cookie
        return h

    # ------------------------------------------------------------------
    # 通用调用（核心）
    # ------------------------------------------------------------------
    def call(self, method, path, params=None, body=None, headers=None):
        """通用 HTTP 调用。method/path 相对 base_url。

        - body 是 dict/list 时 JSON 序列化（utf-8），签名与请求体一致
        - JSON 响应自动解析；非 JSON 返回 bytes；业务 code != 0 抛 EasyOpsError
        """
        method = method.upper()
        content_type = 'application/json'
        body_bytes = None
        if body is not None:
            body_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')
        if self.mode == 'openapi':
            q, h = self._sign(method, path, params or {}, content_type, body_bytes)
        else:
            q = dict(params or {})
            h = self._internal_headers(content_type)
        if headers:
            h.update(headers)
        url = self.base_url + path
        self.logger.debug("-> %s %s params=%s body=%dB", method, url, q, len(body_bytes or b''))
        resp = requests.request(method, url, params=q, data=body_bytes, headers=h,
                                verify=self.verify, timeout=self.timeout)
        self.logger.debug("<- %s %dB", resp.status_code, len(resp.content))
        try:
            data = resp.json()
        except ValueError:
            data = resp.content
        if isinstance(data, dict) and 'code' in data and data.get('code') not in (0, None, '0'):
            msg = data.get('error') or data.get('message') or 'unknown'
            self.logger.warning("业务错误 code=%s msg=%s", data.get('code'), msg)
            raise EasyOpsError(data.get('code'), msg, data)
        return data

    # ------------------------------------------------------------------
    # autoops 便捷方法（端点路径内置，免记）
    # ------------------------------------------------------------------
    def list_tools(self, **query):
        """工具列表。query: name(模糊匹配 name+memo)/category(含子类)/type/page/pageSize。
        返回 [Tool, ...]。后端响应是 {code,data:{list,total}} wrapper；api-cli 调同端点会流式
        输出 NDJSON（每行一个 Tool——那是 api-cli 的分页输出特性，非后端响应格式）。本方法取 data.list。"""
        data = self.call('GET', '/tools', params=query or None)
        if isinstance(data, (bytes, bytearray)):
            return [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
        if isinstance(data, dict):
            return (data.get('data') or {}).get('list') or []
        return data

    def get_tool(self, toolId, vId=None):
        """工具详情。vId 支持别名 $latest_version/$latest_development/$latest_production（不填=最新生产版）。"""
        return self.call('GET', '/tools/' + toolId, params={'vId': vId} if vId else None)

    def create_tool(self, tool_def):
        """新建工具（同时建首个版本）。tool_def 必填 name/type/category/content。返回 {toolId,vId}。"""
        return self.call('POST', '/tools', body=tool_def)

    def update_tool(self, toolId, fields):
        """改工具/加版本。⚠️fields 是 **flat**（顶层字段，勿套 {tool:{}}——否则假成功）。
        改 ToolVersion 字段（inputs/content/outputDefs/vDesc 等）派生新版本（development）。
        响应只返 {toolId}，派生成功否须 list_versions 复查。"""
        return self.call('PUT', '/tools/' + toolId, body=fields)

    def delete_tool(self, toolId, force=None, versionId=None):
        """删工具（软删）。force='true' 绕 ReadOnly；versionId 不填删整个/填删单版本。"""
        q = {}
        if force is not None:
            q['force'] = force
        if versionId:
            q['versionId'] = versionId
        return self.call('DELETE', '/tools/' + toolId, params=q or None)

    def list_versions(self, toolId):
        """列工具所有版本（{data:{list:[...]}} wrapper）。"""
        return self.call('GET', '/tools/' + toolId + '/versions')

    def execute_tool(self, toolId, inputs=None, agents=None, vId=None):
        """异步执行工具。⚠️inputs 是 **map**（{name:value}，非 [{name,value}] 数组，否则报 100000）。
        vId 默认 $latest_production；development 工具用具体 vId 或 $latest_development。返 {execId}。"""
        body = {'toolId': toolId}
        if vId:
            body['vId'] = vId
        if inputs:
            body['inputs'] = inputs
        if agents:
            body['agents'] = agents
        return self.call('POST', '/tools/execution', body=body)

    def get_exec_status(self, execId):
        return self.call('GET', '/tools/execution/status/' + execId)

    def get_exec_result(self, execId):
        """执行完整结果（每主机 outputs/status）。"""
        return self.call('GET', '/tools/execution/result/' + execId)

    def get_exec_table(self, execId):
        """执行表格结果（工具声明 tableDefs 时；查主机内存用）。"""
        return self.call('GET', '/tools/execution/table/' + execId)

    def run_and_wait(self, toolId, inputs=None, agents=None, vId=None, poll_interval=2, max_wait=600):
        """执行 + 轮询到完成。返 {execId, status, result, table}。"""
        run = self.execute_tool(toolId, inputs=inputs, agents=agents, vId=vId)
        execId = (run.get('data') or {}).get('execId')
        if not execId:
            return run
        status = None
        waited = 0
        while waited < max_wait:
            st = self.get_exec_status(execId)
            status = (st.get('data') or {}).get('status')
            self.logger.debug("exec %s status=%s waited=%ss", execId, status, waited)
            if text(status).lower() in ('success', 'failed'):
                break
            time.sleep(poll_interval)
            waited += poll_interval
        return {
            'execId': execId, 'status': status,
            'result': self.get_exec_result(execId),
            'table': self.get_exec_table(execId),
        }

    def export_tool(self, toolId, versionId, save_to, compatibility=None):
        """导出工具为 tar.gz（GET 二进制流式存盘）。⚠️参数是 versionId 非 vId（32 hex）。"""
        path = '/tools/' + toolId + '/export'
        params = {'versionId': versionId}
        if compatibility:
            params['compatibility'] = compatibility
        if self.mode == 'openapi':
            q, h = self._sign('GET', path, params, 'application/json', None)
        else:
            q = dict(params)
            h = self._internal_headers('application/json')
        url = self.base_url + path
        self.logger.debug("-> GET %s export -> %s", url, save_to)
        r = requests.get(url, params=q, headers=h, verify=self.verify, timeout=self.timeout, stream=True)
        if r.status_code != 200:
            raise EasyOpsError(r.status_code, "导出失败: " + r.text[:200], r)
        n = 0
        with open(save_to, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    n += len(chunk)
        self.logger.info("OK 导出 %s (%dB -> %s)", toolId, n, save_to)
        return save_to

    def import_tool(self, file_path, systemImport=None, tools=None):
        """导入工具包（multipart/form-data，upsert）。openapi 模式手动构造 multipart + 签名。

        :param file_path: .tar.gz 文件路径
        :param systemImport: 是否平台系统导入
        :param tools: 可选 tools 元数据（list）
        :return: 导入结果 dict（含每工具 importType=create|update）
        """
        path = '/tools/import'
        with open(file_path, 'rb') as f:
            fcontent = f.read()
        fname = os.path.basename(file_path)
        boundary = '----easyops' + _md5_hex(text(time.time()))
        parts = []
        fields = {}
        if systemImport is not None:
            fields['systemImport'] = 'true' if systemImport else 'false'
        if tools is not None:
            fields['tools'] = json.dumps(tools)
        for k, v in fields.items():
            parts.extend(['--' + boundary,
                          'Content-Disposition: form-data; name="%s"' % k, '', v])
        parts.extend(['--' + boundary,
                      'Content-Disposition: form-data; name="file"; filename="%s"' % fname,
                      'Content-Type: application/gzip', '', fcontent])
        parts.extend(['--' + boundary + '--', ''])
        body_bytes = b'\r\n'.join(p.encode('utf-8') if isinstance(p, text) else p for p in parts)
        content_type = 'multipart/form-data; boundary=' + boundary
        if self.mode == 'openapi':
            q, h = self._sign('POST', path, None, content_type, body_bytes)
        else:
            q = {}
            h = self._internal_headers(content_type)
        url = self.base_url + path
        self.logger.debug("-> POST %s import <- %s", url, file_path)
        r = requests.post(url, params=q, data=body_bytes, headers=h, verify=self.verify, timeout=self.timeout)
        try:
            result = r.json()
        except ValueError:
            result = {'status': r.status_code, 'raw': r.text}
        self.logger.info("OK 导入 %s status=%s", file_path, r.status_code)
        return result

    # ------------------------------------------------------------------
    # cmdb 便捷方法（工具脚本常调 cmdb 查实例/模型；与 autoops 方法共用同一 client，
    # 仅 base_url 指向 cmdb_service:8079）
    # ------------------------------------------------------------------
    def search_instances(self, object_id, fields, query=None, page=1, page_size=30, **kw):
        """cmdb 实例搜索（POST /v3/object/{objectId}/instance/_search）。

        :param object_id: 模型 id（如 HOST / APP_SYSTEM@ONEMODEL）
        :param fields: 返回字段（属性 id 列表）——【必填】，留空后端报 100000
        :param query: MongoDB 风格过滤（$and/$or/$like/$regex/$in/$eq...），如 {'name': {'$like': 'dev'}}
        :param page/page_size: 分页（page_size 上限 3000）
        :return: 后端响应 {code,data:{list,total,...}}；实例总数读 data.total
        ⚠️ openapi 模式需后端在 api_gateway/conf/openapi.yaml 的 app_route 放行
           cmdb service + 本 uri（POST /v3/object/{objectId}/instance/_search），否则 403/404。
        """
        body = {'fields': fields, 'page': page, 'page_size': page_size}
        if query:
            body['query'] = query
        body.update(kw)
        return self.call('POST', '/v3/object/%s/instance/_search' % object_id, body=body)

    def get_object(self, object_id):
        """cmdb 模型详情（GET /object/{objectId}，含 attrList/relation_list/indexList/view）。"""
        return self.call('GET', '/object/%s' % object_id)


# ---------------------------------------------------------------------------
# 自测：python easyops_client.py（不真调，验证 import/构造/签名/便捷方法存在）
# ---------------------------------------------------------------------------
def _selftest():
    # openapi 构造 + 签名（不真调）
    c = EasyOpsClient(mode='openapi', access_key='ak_test_123456', secret_key='sk_test_789012',
                      log_level=logging.WARNING)
    q, h = c._sign('GET', '/tools', {'name': 'cmdb', 'category': 'ITSM'}, 'application/json', None)
    assert q['accesskey'] == 'ak_test_123456'
    assert q['signature'] and len(q['signature']) == 40  # HMAC-SHA1 hex = 40
    assert q['expires'] and h['Host'] == 'openapi.easyops-only.com'
    # POST 签名带 Content-MD5
    body = b'{"name":"t"}'
    q2, _ = c._sign('POST', '/tools', None, 'application/json', body)
    assert q2['signature'] and len(q2['signature']) == 40
    # 签名可重现（同 timestamp）—— _hmac_sha1_hex 纯函数
    s = _hmac_sha1_hex('sk', 'GET\n/tools\n\napplication/json\n\n111\nak')
    assert s == _hmac_sha1_hex('sk', 'GET\n/tools\n\napplication/json\n\n111\nak')
    # 便捷方法存在
    for m in ['list_tools', 'get_tool', 'create_tool', 'update_tool', 'delete_tool',
              'list_versions', 'execute_tool', 'get_exec_status', 'get_exec_result',
              'get_exec_table', 'run_and_wait', 'export_tool', 'import_tool', 'call']:
        assert hasattr(c, m), 'missing ' + m
    # internal 构造
    c2 = EasyOpsClient(mode='internal', base_url='http://127.0.0.1:8181',
                       org='18832008', user='easyops', log_level=logging.WARNING)
    assert c2._internal_headers('application/json')['org'] == '18832008'
    # mode 校验
    try:
        EasyOpsClient(mode='bogus', log_level=logging.WARNING)
        raise AssertionError('应拒绝 bogus mode')
    except EasyOpsError:
        pass
    print('easyops_client 自测通过（py%d, mode=%s/openapi 签名 OK）' % (sys.version_info[0], c2.mode))


if __name__ == '__main__':
    _selftest()
