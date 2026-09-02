#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals, absolute_import

"""
EasyOps 平台迁移工具（Python 2/3 兼容）

通过 YAML 配置驱动，支持 CMDB 模型、CMDB 实例、用户同步、工具等资源的导出和导入。
独立脚本，可直接在 EasyOps 平台上运行。

用法:
    # 导出
    python migration_tool.py export -c config.yaml

    # 导入
    python migration_tool.py import -c config.yaml

    # 完整迁移
    python migration_tool.py migrate -c config.yaml

    # 模拟运行
    python migration_tool.py export -c config.yaml --dry-run
"""

import os
import sys
import json
import time
import hmac
import hashlib
import platform
import traceback
import tarfile
import io
import logging
from functools import wraps

# 兼容 Python 2/3 的 import
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    import requests
except ImportError:
    sys.stderr.write("错误: 缺少 requests 模块，请执行: pip install requests\n")
    sys.exit(1)

try:
    import yaml
except ImportError:
    sys.stderr.write("错误: 缺少 PyYAML 模块，请执行: pip install PyYAML\n")
    sys.exit(1)

# 兼容 Python 2/3 的类型
try:
    text_type = unicode  # Python 2
    binary_type = str
except NameError:
    text_type = str  # Python 3
    binary_type = bytes

# 兼容 Python 2/3 的 makedirs
if hasattr(os, 'makedirs'):
    _makedirs_orig = os.makedirs
    def _makedirs(path):
        try:
            _makedirs_orig(path)
        except OSError:
            if not os.path.isdir(path):
                raise
else:
    def _makedirs(path):
        try:
            os.makedirs(path)
        except OSError:
            if not os.path.isdir(path):
                raise


def _ensure_text(s):
    """确保为 unicode 字符串"""
    if isinstance(s, text_type):
        return s
    if isinstance(s, binary_type):
        return s.decode('utf-8')
    return text_type(s)


def _ensure_bytes(s):
    """确保为 bytes"""
    if isinstance(s, binary_type):
        return s
    if isinstance(s, text_type):
        return s.encode('utf-8')
    return binary_type(s)


def _exc_str(e):
    """
    安全获取异常信息字符串，兼容 Python 2 的 unicode 异常消息。
    Python 2 中 str(Exception(u'中文')) 会触发 ASCII 编码错误。
    """
    try:
        return str(e)
    except UnicodeEncodeError:
        try:
            return unicode(e).encode('utf-8', errors='replace')  # noqa: F821
        except Exception:
            return repr(e)


# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] %(message)s'
)
logger = logging.getLogger('migration_tool')


# ============================================================
# 重试装饰器
# ============================================================

def retry(times=3, delay=1, backoff=2):
    """重试装饰器（仅用于非 HTTP 场景，_request 已自带超时重试）"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            current_delay = delay
            while attempt < times:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= times:
                        raise
                    logger.warning("第{0}次尝试失败,{1}秒后重试: {2}".format(
                        attempt, current_delay, e))
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator


# ============================================================
# EasyOps API 客户端（独立实现，兼容 Py2/Py3）
# ============================================================

class EasyOpsClient(object):
    """EasyOps API HTTP 客户端，支持内网/OpenAPI 双模式"""

    def __init__(self, host=None, org=None, user=None, ak=None, sk=None,
                 token=None, dry_run=False):
        """
        初始化 EasyOps API 客户端

        :param host: EasyOps 服务器主机地址，不填则从 agent 配置读取
        :param org: 组织 ID，不填则从 agent 配置读取
        :param user: 用户名，默认 defaultUser
        :param ak: Access Key（OpenAPI 模式）
        :param sk: Secret Key（OpenAPI 模式）
        :param token: 老版本平台 Cookie Token（PHPSESSID），用于工具 API
        :param dry_run: 是否只打印不执行
        """
        self.dry_run = dry_run
        self.token = token
        user = user or 'defaultUser'

        if not host:
            host, org = self._get_host_and_org_from_agent()

        self.host = host
        self.org = str(org) if org else ''
        self.headers = {
            'user': user,
            'org': self.org,
            'Content-Type': 'application/json',
        }

        if ak and sk:
            self.is_openapi = True
            self.ak = ak
            self.sk = sk
            self.headers['Host'] = 'openapi.easyops-only.com'
        else:
            self.is_openapi = False

    # ---------- 核心 HTTP 请求 ----------

    def _request(self, method, path, port, timeout=3, **kwargs):
        """
        发送 HTTP 请求。仅超时/连接错误自动重试，HTTP 错误立即抛出。

        :param method: GET/POST/PUT/DELETE
        :param path: 请求路径，如 '/tools'
        :param port: 服务端口号
        :param timeout: 超时（秒）
        :param data: 请求体（字典）
        :param params: URL 查询参数（字典）
        :param files: 文件上传参数
        :param form_data: 表单数据（配合 files）
        :return: requests.Response
        """
        # 处理请求体
        if kwargs.get('files'):
            form_data = kwargs.pop('form_data', None)
            if form_data:
                kwargs['data'] = form_data
        elif kwargs.get('data'):
            kwargs['data'] = json.dumps(kwargs['data'])

        headers = self.headers.copy()

        if self.is_openapi:
            url = 'http://{0}{1}'.format(self.host, path)
            params = self._signature(method, path,
                                     kwargs.get('params', {}),
                                     kwargs.get('data', '{}'))
            url = url + '?' + urlencode(params)
            if kwargs.get('params'):
                del kwargs['params']
            if method.upper() in ('GET', 'DELETE'):
                headers.pop('Content-Type', None)
            headers.pop('org', None)
        else:
            url = 'http://{0}:{1}/{2}'.format(
                self.host, port, path.lstrip('/'))

        # dry_run：打印 curl 命令
        if self.dry_run:
            print("[DRY RUN] curl -X {0} '{1}'".format(method, url))
            return _DryRunResponse()

        # 发送请求，错误直接抛出不重试
        if kwargs.get('files'):
            upload_headers = {k: v for k, v in headers.items()
                              if k.lower() != 'content-type'}
            resp = requests.request(method, url, headers=upload_headers,
                                    timeout=timeout, verify=False,
                                    **kwargs)
        else:
            resp = requests.request(method, url, headers=headers,
                                    timeout=timeout, verify=False,
                                    **kwargs)

        # HTTP 错误直接报错退出
        if resp.status_code != 200:
            logger.error("HTTP {0}: {1} {2}".format(
                resp.status_code, method, url))
            logger.error("响应: {0}".format(resp.text[:500]))
            resp.raise_for_status()
        return resp

    # ---------- 老版本平台工具 API（Cookie 认证，通过 curl 调用）----------

    def _token_request(self, method, path, output_file=None, timeout=300):
        """
        老版本平台请求（通过 curl 调用，Cookie/PHPSESSID 认证）

        老版本平台的工具 API 使用 PHP Session 认证，通过 curl 直接调用
        以完全模拟浏览器行为。

        :param method: GET/POST
        :param path: 请求路径，如 '/api/tools/tool'
        :param output_file: 输出文件路径（下载文件时使用）
        :param timeout: 超时（秒）
        :return: (status_code, body_bytes) 元组
        :rtype: tuple
        """
        import subprocess
        url = 'http://{0}{1}'.format(self.host, path)

        cmd = ['curl', '-s', '-w', '\\n%{http_code}', '-X', method, url,
               '--compressed',
               '-H', 'User-Agent: Mozilla/5.0',
               '-H', 'Accept: application/json, text/plain, */*',
               '-H', 'X-Requested-With: XMLHttpRequest',
               '-H', 'Referer: http://{0}/tool'.format(self.host),
               '--connect-timeout', str(timeout)]

        if self.token:
            token_value = self.token
            if token_value.startswith('PHPSESSID='):
                token_value = token_value[len('PHPSESSID='):]
            cmd += ['-H', 'Cookie: PHPSESSID={0}'.format(token_value)]

        if output_file:
            cmd += ['-o', output_file]

        if self.dry_run:
            print("[DRY RUN] {0}".format(' '.join(cmd)))
            return 200, b'[]'

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
        except Exception as e:
            raise Exception('curl 报错: {0}'.format(e))

        if output_file:
            # 下载文件模式：curl -o 直接写文件，stdout 只返回状态码行
            lines = stdout.strip().split(b'\n')
            status_code = int(lines[-1].strip()) if lines else 0
            if status_code != 200:
                raise Exception(
                    'curl 下载失败 HTTP {0}: {1}'.format(status_code, url))
            return status_code, b''

        # 普通请求模式：stdout = body + 最后一行状态码
        parts = stdout.rsplit(b'\n', 1)
        body = parts[0] if len(parts) > 1 else b''
        status_code = int(parts[-1].strip()) if parts else 0

        if status_code != 200:
            logger.error("HTTP {0}: {1} {2}".format(status_code, method, url))
            logger.error("响应: {0}".format(body[:500]))
            raise Exception(
                'HTTP {0}: {1}'.format(status_code, body[:200]))

        return status_code, body

    def list_tools_legacy(self):
        """
        老版本平台：获取工具列表

        返回格式为原始 JSON 数组，每个元素包含 toolId, vId, name, category 等。

        :return: 工具列表
        :rtype: list
        """
        _, body = self._token_request('GET', '/api/tools/tool')
        return json.loads(body)

    def get_tool_versions_legacy(self, tool_id, limit=100, env_type=None):
        """
        老版本平台：获取工具的所有版本列表

        :param tool_id: 工具 ID
        :param limit: 每页数量
        :param env_type: 版本类型过滤（production/development）
        :return: 版本列表
        :rtype: list
        """
        fields = ('vId,vName,vCreator,vDesc,checkType,sourceFrom,'
                  'vCreateTime,envType')
        path = '/api/tools/tool/{0}/versions?fields={1}&limit={2}'.format(
            tool_id, fields, limit)
        if env_type:
            path += '&envType={0}'.format(env_type)

        resp = self._token_request('GET', path)
        data = json.loads(resp[1])
        items = data.get('list', [])
        total = data.get('total', 0)
        logger.info('工具 {0} 获取到 {1}/{2} 个版本'.format(
            tool_id, len(items), total))
        return items

    def export_tool_legacy(self, tool_id, version_id, output_path):
        """
        老版本平台：导出单个版本的工具（直接下载 archive.tar.gz）

        :param tool_id: 工具 ID
        :param version_id: 版本 ID
        :param output_path: 输出文件路径
        :return: 输出文件路径
        """
        path = ('/api/tools/tool/{0}/{1}/archive.tar.gz'
                '?compatibility=latest').format(tool_id, version_id)
        self._token_request('GET', path, output_file=output_path)
        logger.info('工具导出到: {0}'.format(output_path))
        return output_path

    # ---------- OpenAPI 签名 ----------

    def _signature(self, method, uri, params, data):
        """OpenAPI HMAC-SHA1 签名"""
        request_time = str(int(time.time()))
        method = method.upper()
        content_type = 'application/json' if method in ('POST', 'PUT') else ''
        url_param = ''.join(['%s%s' % (k, params[k])
                             for k in sorted(params.keys())])

        content_md5 = ''
        if method in ('POST', 'PUT') and data:
            md5 = hashlib.md5()
            md5.update(_ensure_bytes(data))
            content_md5 = md5.hexdigest()

        parts = [method, uri, url_param, content_type,
                 content_md5, request_time, self.ak]
        string_to_sign = _ensure_text(u'\n').join(
            _ensure_text(p) for p in parts).encode('utf-8')
        secret = _ensure_bytes(self.sk)

        params = dict(params)
        params['accesskey'] = self.ak
        params['signature'] = hmac.new(
            secret, string_to_sign, hashlib.sha1).hexdigest()
        params['expires'] = request_time
        return params

    # ---------- agent 配置读取 ----------

    def _get_host_and_org_from_agent(self):
        """从 agent 配置读取 host 和 org"""
        if platform.system().lower() == 'windows':
            conf_path = r'C:\easyOps\agent\conf\conf.yaml'
        else:
            conf_path = '/usr/local/easyops/agent/conf/conf.yaml'

        if not os.path.exists(conf_path):
            raise Exception('无法读取 agent 配置: {0}，请手动指定 host 和 org'.format(
                conf_path))

        with io.open(conf_path, 'r', encoding='utf-8') as f:
            dic = yaml.safe_load(f)
        org = dic['base']['client_id']
        host = dic['command']['server_groups'][0]['hosts'][0]['ip']
        return host, str(org)

    # ---------- 工具方法 ----------

    def _batch_iter(self, data_list, batch_size):
        """分批迭代器"""
        for i in range(0, len(data_list), batch_size):
            yield data_list[i:i + batch_size]

    # ---------- CMDB 模型 API ----------

    def list_object_basic(self, q=None, page_size=3000, visible='visible',
                          **kwargs):
        """
        获取模型基本信息列表

        :param q: 按模型 ID 模糊匹配
        :param page_size: 页大小
        :param visible: visible/invisible/all
        :param category: 分类
        :param object_ids: 模型 ID 逗号分隔
        :return: 模型列表
        """
        port = 8079
        params = {'page': 1, 'page_size': page_size}
        if q:
            params['q'] = q
        if visible:
            params['visible'] = visible
        for key in ['objectIds', 'category', 'isAbstract', 'fields']:
            if kwargs.get(key):
                params[key] = kwargs[key]

        objects = []
        for page in range(1, 10000):
            params['page'] = page
            resp = self._request('GET', 'object_basic', port=port,
                                 params=params)
            data = resp.json().get('data', {})
            items = data.get('list', [])
            objects.extend(items)
            if len(items) < page_size:
                break
        return objects

    def get_model_desc(self, model_id):
        """
        获取模型完整定义

        :param model_id: 模型 ID
        :return: 模型详情字典
        """
        port = 8079
        resp = self._request('GET', 'object/{0}'.format(model_id), port=port)
        return resp.json().get('data', {})

    def import_model(self, model_list):
        """
        批量导入模型

        :param model_list: 模型定义列表（字典列表）
        """
        port = 8079
        data = {
            'object_list': model_list,
            'ignore_dst_relation': True,
        }
        resp = self._request('POST', '/v2/object_import', port=port,
                             data=data)
        if resp.json().get('code') != 0:
            raise Exception('导入模型失败: {0}'.format(resp.text))

    # ---------- CMDB 实例 API ----------

    def search_instance(self, model_id, **kwargs):
        """
        搜索指定模型的所有实例（自动翻页）

        :param model_id: 模型 ID
        :param fields: 返回字段列表，默认 ['*']
        :param query: 查询条件，如 {'name': {'$like': '%test%'}}
        :param page_size: 每页大小，默认 1000
        :return: 实例列表
        """
        port = 8079
        path = 'v3/object/{0}/instance/_search'.format(model_id)
        data = {
            'fields': kwargs.get('fields', ['*']),
            'query': kwargs.get('query', {}),
            'page': 1,
            'page_size': kwargs.get('page_size', 1000),
        }
        insts = []
        for page in range(1, 10000):
            data['page'] = page
            resp = self._request('POST', path, port=port, data=data)
            items = resp.json()['data']['list']
            insts.extend(items)
            if len(items) < data['page_size']:
                break

        if insts:
            logger.info('模型 {0}: 搜索到 {1} 个实例'.format(model_id, len(insts)))
        else:
            logger.warning('模型 {0}: 未找到实例'.format(model_id))
        return insts

    def import_instance(self, obj_id, data_list, key='instanceId',
                        batch_size=1000):
        """
        批量导入实例

        :param obj_id: 模型 ID
        :param data_list: 实例数据列表
        :param key: 唯一键字段（字符串或列表）
        :param batch_size: 每批数量
        :return: (insert_count, update_count, failed_count)
        """
        port = 8079
        path = 'object/{0}/instance/_import'.format(obj_id)
        keys = [key] if isinstance(key, str) else key

        total_insert = total_update = total_failed = 0
        for batch in self._batch_iter(data_list, batch_size):
            data = {
                'keys': keys,
                'datas': batch,
                'importMetadata': True,
            }
            resp = self._request('POST', path, port=port, data=data)
            d = resp.json().get('data', {})
            total_insert += d.get('insert_count', 0)
            total_update += d.get('update_count', 0)
            total_failed += d.get('failed_count', 0)

        logger.info(
            '导入 {0}: 新增 {1}, 更新 {2}, 失败 {3}'.format(
                obj_id, total_insert, total_update, total_failed))
        return total_insert, total_update, total_failed

    def get_unique_required_attrs(self, object_id):
        """
        获取模型中唯一且必填的属性 ID 列表

        :param object_id: 模型 ID
        :return: 属性 ID 列表
        """
        try:
            model_info = self.get_model_desc(object_id)
            attrs = model_info.get('attrList', [])
            unique_required = []
            for attr in attrs:
                is_unique = attr.get('unique') in (True, 'true')
                is_required = attr.get('required') in (True, 'true')
                if is_unique and is_required:
                    unique_required.append(attr['id'])
            return unique_required
        except Exception as e:
            logger.error('获取模型 {0} 属性信息失败: {1}'.format(object_id, _exc_str(e)))
            return []

    def register_user(self, name, password, email, nickname='',
                      is_admin=False):
        """
        注册 EasyOps 用户账号

        API: UserRegister (easyops.api.user_service.user_admin)
        服务: logic.user_service
        端口: 8111

        :param name: 用户名
        :param password: 密码
        :param email: 邮箱
        :param nickname: 昵称（可选）
        :param is_admin: 是否管理员，默认 False
        :return: API 响应
        :rtype: dict
        """
        port = 8111
        payload = {
            'name': name,
            'password': password,
            'email': email,
            'org': int(self.org),
        }
        if nickname:
            payload['nickname'] = nickname
        if is_admin:
            payload['isAdmin'] = True
        resp = self._request('POST', '/api/v1/users/register',
                             port=port, data=payload)
        return resp.json()

    # ---------- 工具 API ----------

    def list_tools(self, page=1, page_size=300, category=None,
                   name=None, plugin=False, **kwargs):
        """
        获取工具列表

        :param page: 页码
        :param page_size: 页大小
        :param category: 分类筛选
        :param name: 名称筛选
        :param plugin: 是否显示插件
        :return: {'list': [...], 'total': N, ...}
        """
        port = 8181
        params = {
            'page': page,
            'pageSize': page_size,
            'plugin': str(plugin).lower(),
        }
        if category:
            params['category'] = category
        if name:
            params['name'] = name
        params.update(kwargs)

        resp = self._request('GET', '/tools', port=port, params=params)
        data = resp.json()
        if data.get('code') != 0:
            logger.error('获取工具列表失败: {0}'.format(data))
            return {'list': [], 'total': 0}
        return data.get('data', {})

    def get_tool_versions(self, tool_id, limit=100, env_type=None):
        """
        获取工具的所有版本列表

        :param tool_id: 工具 ID
        :param limit: 每页数量
        :param env_type: 版本类型过滤 production/development
        :return: 版本列表
        """
        port = 8181
        all_versions = []
        paging_time = '9999-12-31'

        while True:
            params = {
                'orderBy': 'vCreateTime',
                'orderType': 'DESC',
                'startTime': '1970-01-01',
                'endingTime': '9999-12-31',
                'pagingTime': paging_time,
                'limit': limit,
                'fields': 'toolId,vId,vName,vCreateTime,envType',
            }
            if env_type:
                params['envType'] = env_type

            resp = self._request('GET',
                                 '/tools/{0}/versions'.format(tool_id),
                                 port=port, params=params)
            data = resp.json().get('data', {})
            items = data.get('list', [])
            all_versions.extend(items)

            total = data.get('total', 0)
            new_paging = data.get('pagingTime', '')
            logger.info('工具 {0} 已获取 {1}/{2} 个版本'.format(
                tool_id, len(all_versions), total))

            if len(all_versions) >= total or not items or not new_paging:
                break
            paging_time = new_paging

        return all_versions

    def export_tool(self, tool_id, version_id, output_path):
        """
        导出单个版本的工具

        :param tool_id: 工具 ID
        :param version_id: 版本 ID
        :param output_path: 输出文件路径
        :return: 输出文件路径
        """
        port = 8181
        params = {
            'compatibility':'latest',
            'versionId':version_id,
        }
        resp = self._request('GET', '/tools/{}/export'.format(tool_id),
                             port=port, params=params, timeout=300)

        content_type = resp.headers.get('Content-Type', '')
        if resp.status_code == 200 and content_type.startswith('application/'):
            with io.open(output_path, 'wb') as f:
                f.write(resp.content)
            logger.info('工具导出到: {0}'.format(output_path))
            return output_path
        else:
            raise Exception('导出工具失败: {0}'.format(resp.text))

    def import_tool(self, file_path, new_name=None, new_version_name=None):
        """
        导入工具

        :param file_path: 工具包路径（.tar.gz）
        :param new_name: 新名称（可选）
        :param new_version_name: 新版本名（可选）
        :return: 导入结果字典，冲突时返回 {'skipped': True, ...}
        """
        port = 8181
        path = 'tools/import'

        # 读取文件内容为 bytes，避免 io.open 在 Python 2 的 requests
        # multipart 编码时触发 ASCII 解码错误
        with open(file_path, 'rb') as f:
            file_content = f.read()
        files = {'file': (os.path.basename(file_path),
                          file_content, 'application/gzip')}
        form_data = {}
        if new_name:
            form_data['newName'] = new_name
        if new_version_name:
            form_data['newVersionName'] = new_version_name

        # 工具导入需要自行处理 403 冲突，不走 _request 的 raise_for_status
        headers = self.headers.copy()
        upload_headers = {k: v for k, v in headers.items()
                          if k.lower() != 'content-type'}
        url = 'http://{0}:{1}/{2}'.format(self.host, port, path)

        try:
            resp = requests.request('POST', url, headers=upload_headers,
                                    timeout=300, verify=False,
                                    files=files,
                                    data=form_data if form_data else None)
        except requests.exceptions.RequestException as e:
            raise Exception('工具导入请求失败: {0}'.format(e))

        # 显式解码响应，避免 Python 2 的 ASCII 默认解码
        resp_content = resp.content
        if isinstance(resp_content, binary_type):
            resp_text = resp_content.decode('utf-8', errors='replace')
        else:
            resp_text = resp_content
        result = json.loads(resp_text)
        code = result.get('code', -1)
        if code == 133039:
            return {'skipped': True, 'reason': 'conflict',
                    'conflictList': result.get('conflictList', [])}
        if code != 0:
            error = result.get('error', result.get('codeExplain', ''))
            raise Exception('tool import failed(code={0}): {1}'.format(
                code, _exc_str(error)))
        return result

    def import_tool_check(self, file_path):
        """
        导入工具前检查

        :param file_path: 工具包路径
        :return: 检查结果字典
        """
        tools_info = []
        try:
            with tarfile.open(file_path, 'r:gz') as tar:
                for member in tar.getmembers():
                    if (member.name.endswith('/config')
                            or member.name == 'config'):
                        f = tar.extractfile(member)
                        if f:
                            content = f.read()
                            # 兼容不同编码的 config 文件
                            try:
                                text = content.decode('utf-8')
                            except (UnicodeDecodeError, UnicodeError):
                                text = content.decode('gbk', errors='replace')
                            config = json.loads(text)
                            tools_info.append({
                                'toolId': config.get('toolId', ''),
                                'name': config.get('name', ''),
                                'versionId': config.get('versionId', ''),
                                'versionName': config.get(
                                    'versionName', '1.0.0'),
                            })
        except Exception as e:
            logger.warning('解析工具包失败: {0}'.format(e))

        if not tools_info:
            return {'conflictList': [], 'canImport': False,
                    'reason': '无法解析工具包'}

        return {
            'conflictList': [],
            'canImport': True,
            'tools': tools_info,
        }


class _DryRunResponse(object):
    """dry_run 模式下的假响应"""
    status_code = 200
    text = '{}'
    content = b''
    headers = {'Content-Type': 'application/json'}

    def json(self):
        return {}


# ============================================================
# 资源处理器
# ============================================================

class ResourceHandler(object):
    """资源处理器抽象基类"""

    resource_type = ''

    def export_data(self, client, resource_config, output_dir):
        """导出数据，子类实现"""
        raise NotImplementedError

    def import_data(self, client, resource_config, output_dir, manifest):
        """导入数据，子类实现"""
        raise NotImplementedError


class CMDBModelHandler(ResourceHandler):
    """CMDB 模型处理器"""

    resource_type = 'cmdb_model'

    def export_data(self, client, resource_config, output_dir):
        model_dir = os.path.join(output_dir, 'models')
        _makedirs(model_dir)

        filter_conf = resource_config.get('filter') or {}
        model_ids = filter_conf.get('model_ids')

        kwargs = {}
        if filter_conf.get('category'):
            kwargs['category'] = filter_conf['category']
        if filter_conf.get('q'):
            kwargs['q'] = filter_conf['q']
        if filter_conf.get('object_ids'):
            kwargs['object_ids'] = filter_conf['object_ids']

        if model_ids:
            model_list = []
            for mid in model_ids:
                try:
                    desc = client.get_model_desc(mid)
                    model_list.append({'objectId': mid,
                                       'name': desc.get('name', mid)})
                except Exception as e:
                    logger.warning('获取模型 {0} 失败: {1}'.format(mid, _exc_str(e)))
        else:
            model_list = client.list_object_basic(**kwargs)

        logger.info('共找到 {0} 个模型'.format(len(model_list)))

        all_models = []
        failed = []
        for idx, m in enumerate(model_list, 1):
            oid = m.get('objectId', m.get('object_id', ''))
            if not oid:
                continue
            if oid.startswith('_') or oid.startswith('FLOW_'):
                continue

            logger.info('[{0}/{1}] 导出模型: {2}'.format(idx, len(model_list),
                                                        oid))
            try:
                desc = client.get_model_desc(oid)
                all_models.append(desc)
            except Exception as e:
                failed.append({'objectId': oid, 'error': _exc_str(e)})
                logger.warning('导出模型 {0} 失败: {1}'.format(oid, _exc_str(e)))

        output_file = os.path.join(model_dir, 'models.json')
        with io.open(output_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(all_models, ensure_ascii=False, indent=2))

        logger.info('成功导出 {0} 个模型到 {1}'.format(len(all_models),
                                                      output_file))
        return {
            'type': self.resource_type,
            'file': 'models/models.json',
            'count': len(all_models),
            'failed': failed,
        }

    def import_data(self, client, resource_config, output_dir, manifest):
        model_file = os.path.join(output_dir, manifest['file'])
        if not os.path.exists(model_file):
            logger.error('模型文件不存在: {0}'.format(model_file))
            return {'success': 0, 'failed': 0, 'errors': []}

        with io.open(model_file, 'r', encoding='utf-8') as f:
            models = json.load(f)

        logger.info('开始导入 {0} 个模型'.format(len(models)))
        success = 0
        errors = []
        for model in models:
            oid = model.get('objectId', '')
            try:
                client.import_model([model])
                success += 1
                logger.info('导入模型成功: {0}'.format(oid))
            except Exception as e:
                errors.append({'objectId': oid, 'error': _exc_str(e)})
                logger.warning('导入模型 {0} 失败: {1}'.format(oid, _exc_str(e)))

        return {'success': success, 'failed': len(errors), 'errors': errors}


class CMDBInstanceHandler(ResourceHandler):
    """CMDB 实例处理器"""

    resource_type = 'cmdb_instance'

    def export_data(self, client, resource_config, output_dir):
        inst_dir = os.path.join(output_dir, 'instances')
        _makedirs(inst_dir)

        models = resource_config.get('models', [])
        if not models:
            logger.warning('未指定 models，跳过实例导出')
            return {'type': self.resource_type, 'files': [], 'total': 0}

        # 全局 filter.query 作为兜底（向后兼容），优先级低于 model 级 query
        filter_conf = resource_config.get('filter') or {}
        global_query = filter_conf.get('query', {})

        files_info = []
        total = 0

        for model_item in models:
            # 兼容两种配置形式：
            #   - 字符串: "USER_GROUP"（默认 fields=["*"]，使用全局 query）
            #   - 对象:   {model_id, fields, query}，每个模型独立配置
            if isinstance(model_item, dict):
                model_id = model_item.get('model_id')
                fields = model_item.get('fields') or ['*']
                query = model_item.get('query', global_query)
            else:
                model_id = model_item
                fields = ['*']
                query = global_query
            if not model_id:
                logger.warning('models 中存在空 model_id，跳过该项')
                continue
            logger.info('导出模型 {0} 的实例（fields={1}, query={2})...'.format(
                model_id, fields, query if query else '全部'))
            try:
                instances = client.search_instance(
                    model_id, query=query, fields=fields)
                output_file = os.path.join(inst_dir, '{0}.json'.format(
                    model_id))
                with io.open(output_file, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(instances, ensure_ascii=False,
                                       indent=2))
                count = len(instances)
                total += count
                files_info.append({
                    'model_id': model_id,
                    'file': 'instances/{0}.json'.format(model_id),
                    'count': count,
                })
                logger.info('模型 {0} 导出 {1} 个实例'.format(model_id, count))
            except Exception as e:
                logger.warning('导出模型 {0} 实例失败: {1}'.format(model_id, _exc_str(e)))
                files_info.append({
                    'model_id': model_id, 'file': None,
                    'count': 0, 'error': _exc_str(e),
                })

        return {
            'type': self.resource_type,
            'files': files_info,
            'total': total,
        }

    def import_data(self, client, resource_config, output_dir, manifest):
        batch_size = resource_config.get('batch_size',
                                          manifest.get('batch_size', 1000))
        result = {'success': 0, 'failed': 0, 'details': []}

        for file_info in manifest.get('files', []):
            if not file_info.get('file'):
                continue
            model_id = file_info['model_id']
            inst_file = os.path.join(output_dir, file_info['file'])

            if not os.path.exists(inst_file):
                logger.warning('实例文件不存在: {0}'.format(inst_file))
                continue

            with io.open(inst_file, 'r', encoding='utf-8') as f:
                instances = json.load(f)

            logger.info('导入模型 {0} 的 {1} 个实例'.format(
                model_id, len(instances)))

            try:
                unique_keys = client.get_unique_required_attrs(model_id)
                keys = unique_keys if unique_keys else ['instanceId']
            except Exception:
                keys = ['instanceId']

            try:
                client.import_instance(model_id, instances, key=keys,
                                       batch_size=batch_size)
                result['success'] += len(instances)
                result['details'].append({
                    'model_id': model_id, 'count': len(instances),
                    'status': 'success',
                })
            except Exception as e:
                result['failed'] += len(instances)
                result['details'].append({
                    'model_id': model_id, 'count': len(instances),
                    'status': 'failed', 'error': _exc_str(e),
                })
                logger.warning('导入模型 {0} 实例失败: {1}'.format(model_id, _exc_str(e)))

        return result


class UserSyncHandler(ResourceHandler):
    """用户同步处理器：同步 USER 实例并自动注册新用户"""

    resource_type = 'user_sync'

    USER_MODEL = 'USER'

    def export_data(self, client, resource_config, output_dir):
        inst_dir = os.path.join(output_dir, 'instances')
        _makedirs(inst_dir)

        model_id = self.USER_MODEL
        logger.info('导出用户实例 ({0})...'.format(model_id))

        try:
            instances = client.search_instance(model_id)
            safe_name = model_id.replace('@', '_')
            output_file = os.path.join(inst_dir,
                                       '{0}.json'.format(safe_name))
            with io.open(output_file, 'w', encoding='utf-8') as f:
                f.write(json.dumps(instances, ensure_ascii=False, indent=2))
            logger.info('导出 {0} 个用户实例'.format(len(instances)))
            return {
                'type': self.resource_type,
                'file': 'instances/{0}.json'.format(safe_name),
                'count': len(instances),
                'model_id': model_id,
            }
        except Exception as e:
            logger.error('导出用户实例失败: {0}'.format(_exc_str(e)))
            return {'type': self.resource_type, 'error': _exc_str(e)}

    def import_data(self, client, resource_config, output_dir, manifest):
        model_id = manifest.get('model_id', self.USER_MODEL)
        password_tpl = resource_config.get(
            'password_tpl', '{name}@easyops2026')

        inst_file = os.path.join(output_dir, manifest['file'])
        if not os.path.exists(inst_file):
            logger.error('用户实例文件不存在: {0}'.format(inst_file))
            return {'success': 0, 'registered': 0, 'errors': []}

        with io.open(inst_file, 'r', encoding='utf-8') as f:
            instances = json.load(f)

        if not instances:
            logger.info('无用户实例需要导入')
            return {'success': 0, 'registered': 0, 'errors': []}

        # 1. 查询目标平台已有用户名集合
        existing_names = set()
        try:
            existing_users = client.search_instance(model_id)
            existing_names = {u.get('name', '')
                              for u in existing_users
                              if u.get('name')}
            logger.info('目标平台已有 {0} 个用户'.format(
                len(existing_names)))
        except Exception as e:
            logger.warning('查询目标已有用户失败（将尝试全部注册）: '
                           '{0}'.format(_exc_str(e)))

        # 2. 导入 CMDB 实例
        logger.info('开始导入 {0} 个用户实例到 CMDB...'.format(
            len(instances)))
        try:
            unique_keys = client.get_unique_required_attrs(model_id)
            keys = unique_keys if unique_keys else ['name']
        except Exception:
            keys = ['name']

        batch_size = resource_config.get(
            'batch_size', manifest.get('batch_size', 1000))
        try:
            insert_cnt, update_cnt, failed_cnt = client.import_instance(
                model_id, instances, key=keys, batch_size=batch_size)
            logger.info('CMDB 导入完成: 新增 {0}, 更新 {1}, '
                        '失败 {2}'.format(insert_cnt, update_cnt, failed_cnt))
        except Exception as e:
            logger.error('CMDB 导入失败: {0}'.format(_exc_str(e)))
            return {'success': 0, 'registered': 0,
                    'errors': [{'stage': 'import',
                                'error': _exc_str(e)}]}

        # 3. 注册新用户账号（仅目标平台之前不存在的用户）
        new_users = [u for u in instances
                     if u.get('name') and
                     u.get('name') not in existing_names]
        logger.info('检测到 {0} 个新增用户需要注册'.format(len(new_users)))

        registered = 0
        register_errors = []
        for user in new_users:
            name = user.get('name', '')
            if not name:
                continue
            password = password_tpl.format(name=name)
            email = user.get('email', '')
            if not email:
                email = '{name}@easyops.local'.format(name=name)
            nickname = user.get('nickname', user.get('nick_name', ''))

            try:
                result = client.register_user(
                    name=name, password=password,
                    email=email, nickname=nickname)
                code = result.get('code', -1)
                if code == 0:
                    registered += 1
                    logger.info('注册成功: {0}'.format(name))
                else:
                    err_msg = result.get('error',
                                         result.get('message', ''))
                    register_errors.append({
                        'name': name, 'error': err_msg})
                    logger.warning('注册失败: {0} - {1}'.format(
                        name, err_msg))
            except Exception as e:
                register_errors.append({
                    'name': name, 'error': _exc_str(e)})
                logger.error('注册异常: {0} - {1}'.format(
                    name, _exc_str(e)))

        logger.info('用户同步完成: CMDB 导入 {0} 条, '
                    '新注册 {1}/{2} 个账号'.format(
                        len(instances), registered, len(new_users)))
        return {
            'success': len(instances),
            'insert_count': insert_cnt,
            'update_count': update_cnt,
            'registered': registered,
            'new_users': len(new_users),
            'register_errors': register_errors,
        }


class ToolHandler(ResourceHandler):
    """工具处理器，支持导出所有版本，兼容老版本平台 Token 认证"""

    resource_type = 'tool'

    def export_data(self, client, resource_config, output_dir):
        tool_dir = os.path.join(output_dir, 'tools')
        _makedirs(tool_dir)

        export_all = resource_config.get('export_all_versions', True)
        filter_conf = resource_config.get('filter') or {}
        use_legacy = bool(getattr(client, 'token', None))

        # 获取工具列表
        if use_legacy:
            logger.info('检测到 Token，使用老版本平台工具 API')
            all_tools = client.list_tools_legacy()
            # 老版本返回原始数组，按分类/名称过滤
            if filter_conf.get('category'):
                all_tools = [t for t in all_tools
                             if t.get('category') == filter_conf['category']]
            if filter_conf.get('name'):
                keyword = filter_conf['name']
                all_tools = [t for t in all_tools
                             if keyword in t.get('name', '')]
        else:
            all_tools = []
            page = 1
            while True:
                kwargs = {'page': page, 'page_size': 300}
                if filter_conf.get('category'):
                    kwargs['category'] = filter_conf['category']
                if filter_conf.get('name'):
                    kwargs['name'] = filter_conf['name']

                data = client.list_tools(**kwargs)
                tools = data.get('list', [])
                total = data.get('total', 0)
                all_tools.extend(tools)
                if len(all_tools) >= total or not tools:
                    break
                page += 1

        logger.info('共找到 {0} 个工具'.format(len(all_tools)))

        tools_manifest = []
        exported_files = []

        for idx, tool in enumerate(all_tools, 1):
            tool_id = tool.get('toolId', '')
            tool_name = tool.get('name', '')
            logger.info('[{0}/{1}] 处理工具: {2} ({3})'.format(
                idx, len(all_tools), tool_name, tool_id))

            versions = []
            if export_all:
                try:
                    if use_legacy:
                        versions = client.get_tool_versions_legacy(tool_id)
                    else:
                        versions = client.get_tool_versions(tool_id)
                except Exception as e:
                    logger.warning('获取工具 {0} 版本列表失败: {1}'.format(
                        tool_name, e))
                    versions = [{
                        'toolId': tool_id,
                        'vId': tool.get('vId', ''),
                        'vName': tool.get('vName', ''),
                        'envType': tool.get('envType', ''),
                    }]
            else:
                versions = [{
                    'toolId': tool_id,
                    'vId': tool.get('vId', ''),
                    'vName': tool.get('vName', ''),
                    'envType': tool.get('envType', ''),
                }]

            logger.info('  工具 {0} 共 {1} 个版本'.format(
                tool_name, len(versions)))

            for ver in versions:
                vid = ver.get('vId', '')
                vname = ver.get('vName', '')
                if not vid:
                    continue

                output_path = os.path.join(
                    tool_dir, '{0}_{1}.tar.gz'.format(tool_id, vid))
                # 增量导出：已存在的文件跳过
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info('  跳过已导出: {0} ({1})'.format(vname, vid))
                    exported_files.append({
                        'toolId': tool_id,
                        'toolName': tool_name,
                        'versionId': vid,
                        'versionName': vname,
                        'envType': ver.get('envType', ''),
                        'file': 'tools/{0}_{1}.tar.gz'.format(tool_id, vid),
                    })
                    continue
                try:
                    if use_legacy:
                        client.export_tool_legacy(tool_id, vid, output_path)
                    else:
                        client.export_tool(tool_id, vid, output_path)
                    exported_files.append({
                        'toolId': tool_id,
                        'toolName': tool_name,
                        'versionId': vid,
                        'versionName': vname,
                        'envType': ver.get('envType', ''),
                        'file': 'tools/{0}_{1}.tar.gz'.format(tool_id, vid),
                    })
                    logger.info('  导出版本 {0} ({1})'.format(vname, vid))
                except Exception as e:
                    logger.warning('  导出版本 {0} 失败: {1}'.format(vname, _exc_str(e)))

            tools_manifest.append({
                'toolId': tool_id,
                'toolName': tool_name,
                'versionCount': len(versions),
                'versions': versions,
            })

        manifest_file = os.path.join(tool_dir, 'tools_manifest.json')
        with io.open(manifest_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(tools_manifest, ensure_ascii=False, indent=2))

        return {
            'type': self.resource_type,
            'manifest_file': 'tools/tools_manifest.json',
            'exported_files': exported_files,
            'total_tools': len(all_tools),
            'total_versions': len(exported_files),
        }

    def import_data(self, client, resource_config, output_dir, manifest):
        result = {'success': 0, 'failed': 0, 'skipped': 0, 'details': []}
        conflict_strategy = resource_config.get('conflict_strategy', 'skip')

        for file_info in manifest.get('exported_files', []):
            file_path = os.path.join(output_dir, file_info['file'])
            if not os.path.exists(file_path):
                logger.warning('工具文件不存在: {0}'.format(file_path))
                result['skipped'] += 1
                continue

            tool_name = file_info.get('toolName', 'unknown')
            version_name = file_info.get('versionName', '')

            try:
                check = client.import_tool_check(file_path)
                conflicts = check.get('conflictList', [])

                if conflicts and conflict_strategy == 'skip':
                    logger.info('  跳过（冲突）: {0} {1}'.format(
                        tool_name, version_name))
                    result['skipped'] += 1
                    result['details'].append({
                        'tool': tool_name, 'version': version_name,
                        'status': 'skipped', 'reason': 'conflict',
                    })
                    continue

                res = client.import_tool(file_path)
                # 如果返回 skipped 标记（code 133039 冲突），跳过
                if res.get('skipped'):
                    logger.info('  跳过（冲突）: {0} {1}'.format(
                        tool_name, version_name))
                    result['skipped'] += 1
                    result['details'].append({
                        'tool': tool_name, 'version': version_name,
                        'status': 'skipped', 'reason': 'conflict',
                    })
                    continue

                result['success'] += 1
                logger.info('  导入成功: {0} {1}'.format(
                    tool_name, version_name))
                result['details'].append({
                    'tool': tool_name, 'version': version_name,
                    'status': 'success',
                })
            except Exception as e:
                result['failed'] += 1
                result['details'].append({
                    'tool': tool_name, 'version': version_name,
                    'status': 'failed', 'error': _exc_str(e),
                })
                logger.warning('  导入失败: {0} {1}: {2}'.format(
                    tool_name, version_name, e))

        return result


# ============================================================
# 迁移引擎
# ============================================================

HANDLER_MAP = {
    'cmdb_model': CMDBModelHandler(),
    'cmdb_instance': CMDBInstanceHandler(),
    'user_sync': UserSyncHandler(),
    'tool': ToolHandler(),
}


class MigrationEngine(object):
    """迁移引擎"""

    def __init__(self, config):
        self.config = config
        self.options = config.get('options', {})
        self.output_dir = self.options.get('output_dir', './migration_output')
        self.dry_run = self.options.get('dry_run', False)

    def _create_client(self, endpoint):
        return EasyOpsClient(
            host=endpoint.get('host'),
            org=endpoint.get('org'),
            user=endpoint.get('user', 'defaultUser'),
            ak=endpoint.get('ak'),
            sk=endpoint.get('sk'),
            token=endpoint.get('token'),
            dry_run=self.dry_run,
        )

    def export_data(self):
        source = self.config.get('source', {})
        resources = self.config.get('resources', [])
        if not source:
            logger.error('配置中缺少 source（源平台）信息')
            return {}

        client = self._create_client(source)
        _makedirs(self.output_dir)

        # 加载已有报告（增量场景）
        report_path = os.path.join(self.output_dir, 'export_report.json')
        all_manifests = self._load_export_report(report_path)

        # 模型先导出
        type_order = {'cmdb_model': 0, 'cmdb_instance': 1,
                      'user_sync': 2, 'tool': 3}
        resources_sorted = sorted(
            resources,
            key=lambda r: type_order.get(r.get('type', ''), 99))

        # 已有报告中的类型跳过
        done_types = {m.get('type') for m in all_manifests
                      if m.get('type') and 'error' not in m}

        start_time = time.time()

        for idx, res_conf in enumerate(resources_sorted, 1):
            res_type = res_conf.get('type', '')
            handler = HANDLER_MAP.get(res_type)
            if not handler:
                logger.warning('未知的资源类型: {0}，跳过'.format(res_type))
                continue

            # 已完成的资源跳过
            if res_type in done_types:
                logger.info('[{0}/{1}] {2} 已导出，跳过'.format(
                    idx, len(resources_sorted), res_type))
                continue

            logger.info('=' * 60)
            logger.info('[{0}/{1}] 导出资源: {2}'.format(
                idx, len(resources_sorted), res_type))
            logger.info('=' * 60)

            # 移除同类型的旧记录（如上次失败的），避免重复
            all_manifests = [m for m in all_manifests
                             if m.get('type') != res_type]

            if self.dry_run:
                logger.info('[DRY RUN] 将导出 {0} 资源'.format(res_type))
                all_manifests.append({'type': res_type, 'dry_run': True})
                continue

            try:
                manifest = handler.export_data(client, res_conf,
                                               self.output_dir)
                all_manifests.append(manifest)
            except Exception as e:
                logger.error('导出 {0} 失败: {1}'.format(res_type, _exc_str(e)))
                all_manifests.append({'type': res_type, 'error': _exc_str(e)})

            # 每个资源完成后立即写入报告
            self._save_export_report(report_path, all_manifests, source)

        elapsed = time.time() - start_time

        logger.info('\n' + '=' * 60)
        logger.info('导出完成! 耗时 {0:.1f}s，输出目录: {1}'.format(
            elapsed, self.output_dir))
        logger.info('导出报告: {0}'.format(report_path))
        self._print_export_summary(all_manifests)
        return self._load_export_report(report_path)

    def _load_export_report(self, report_path):
        """加载已有的导出报告"""
        if os.path.exists(report_path):
            try:
                with io.open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                return report.get('resources', [])
            except Exception:
                pass
        return []

    def _save_export_report(self, report_path, resources, source):
        """保存导出报告（增量写入）"""
        report = {
            'export_time': _iso_datetime(),
            'source': self._filter_creds(source),
            'resources': resources,
        }
        with io.open(report_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(report, ensure_ascii=False, indent=2))

    def import_data(self):
        target = self.config.get('target', {})
        resources = self.config.get('resources', [])
        if not target:
            logger.error('配置中缺少 target（目标平台）信息')
            return {}

        report_path = os.path.join(self.output_dir, 'export_report.json')
        if not os.path.exists(report_path):
            logger.error('导出报告不存在: {0}，请先执行导出'.format(
                report_path))
            return {}

        with io.open(report_path, 'r', encoding='utf-8') as f:
            global_manifest = json.load(f)

        # 每个类型取最新一条记录（兼容历史报告中的重复条目）
        manifest_by_type = {}
        for m in global_manifest.get('resources', []):
            t = m.get('type')
            if t:
                manifest_by_type[t] = m

        client = self._create_client(target)
        start_time = time.time()
        all_results = []

        for idx, res_conf in enumerate(resources, 1):
            res_type = res_conf.get('type', '')
            handler = HANDLER_MAP.get(res_type)
            if not handler:
                continue
            res_manifest = manifest_by_type.get(res_type, {})

            logger.info('=' * 60)
            logger.info('[{0}/{1}] 导入资源: {2}'.format(
                idx, len(resources), res_type))
            logger.info('=' * 60)

            if self.dry_run or res_manifest.get('dry_run'):
                logger.info('[DRY RUN] 将导入 {0} 资源'.format(res_type))
                continue

            # 导出失败的资源跳过导入
            # cmdb_instance 用 files 列表，其他资源用 file 字段
            has_file = res_manifest.get('file') or res_manifest.get('files')
            if 'error' in res_manifest or not has_file:
                logger.warning('{0} 导出失败或无数据文件，跳过导入'.format(
                    res_type))
                continue

            try:
                result = handler.import_data(client, res_conf,
                                             self.output_dir, res_manifest)
                result['type'] = res_type
                all_results.append(result)
            except Exception as e:
                logger.error('导入 {0} 失败: {1}'.format(res_type, _exc_str(e)))
                all_results.append({'type': res_type, 'error': _exc_str(e)})

        elapsed = time.time() - start_time
        logger.info('\n' + '=' * 60)
        logger.info('导入完成! 耗时 {0:.1f}s'.format(elapsed))
        self._print_import_summary(all_results)

        report = {
            'import_time': _iso_datetime(),
            'target': self._filter_creds(target),
            'elapsed_seconds': round(elapsed, 2),
            'results': all_results,
        }
        report_path = os.path.join(self.output_dir, 'import_report.json')
        with io.open(report_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(report, ensure_ascii=False, indent=2))
        logger.info('导入报告: {0}'.format(report_path))
        return report

    def migrate(self):
        """导出 + 导入"""
        logger.info('=' * 60)
        logger.info('开始完整迁移流程')
        logger.info('=' * 60)
        self.export_data()
        logger.info('\n')
        self.import_data()

    def _filter_creds(self, endpoint):
        """从 endpoint 中过滤掉敏感信息"""
        return {k: v for k, v in endpoint.items()
                if k not in ('ak', 'sk')}

    def _print_export_summary(self, manifests):
        print('\n--- 导出摘要 ---')
        for m in manifests:
            res_type = m.get('type', 'unknown')
            if 'error' in m:
                print('  {0}: 失败 ({1})'.format(res_type, m['error']))
            elif m.get('dry_run'):
                print('  {0}: [DRY RUN]'.format(res_type))
            elif res_type == 'cmdb_model':
                print('  {0}: {1} 个模型'.format(res_type, m.get('count', 0)))
            elif res_type == 'cmdb_instance':
                print('  {0}: {1} 个实例'.format(
                    res_type, m.get('total', 0)))
            elif res_type == 'user_sync':
                print('  {0}: {1} 个用户'.format(
                    res_type, m.get('count', 0)))
            elif res_type == 'tool':
                print('  {0}: {1} 个工具, {2} 个版本'.format(
                    res_type,
                    m.get('total_tools', 0),
                    m.get('total_versions', 0)))

    def _print_import_summary(self, results):
        print('\n--- 导入摘要 ---')
        for r in results:
            res_type = r.get('type', 'unknown')
            if 'error' in r:
                print('  {0}: 失败 ({1})'.format(res_type, r['error']))
            elif res_type == 'cmdb_model':
                print('  {0}: 成功 {1}, 失败 {2}'.format(
                    res_type, r.get('success', 0), r.get('failed', 0)))
            elif res_type == 'cmdb_instance':
                print('  {0}: 成功 {1}, 失败 {2}'.format(
                    res_type, r.get('success', 0), r.get('failed', 0)))
            elif res_type == 'user_sync':
                print('  {0}: 导入 {1}, 注册 {2}/{3}'.format(
                    res_type, r.get('success', 0),
                    r.get('registered', 0), r.get('new_users', 0)))
            elif res_type == 'tool':
                print('  {0}: 成功 {1}, 失败 {2}, 跳过 {3}'.format(
                    res_type, r.get('success', 0),
                    r.get('failed', 0), r.get('skipped', 0)))


def _iso_datetime():
    """返回 ISO 格式时间字符串"""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())


# ============================================================
# CLI 入口
# ============================================================

def load_config(config_path):
    """加载 YAML 配置文件"""
    if not os.path.exists(config_path):
        logger.error('配置文件不存在: {0}'.format(config_path))
        sys.exit(1)
    with io.open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='EasyOps 平台迁移工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 导出
  python migration_tool.py export -c config.yaml

  # 导入
  python migration_tool.py import -c config.yaml

  # 完整迁移
  python migration_tool.py migrate -c config.yaml

  # 模拟运行
  python migration_tool.py export -c config.yaml --dry-run

  # 仅同步用户
  python migration_tool.py migrate -c config.yaml
  # config.yaml 中 resources 只包含 type: user_sync
        ''')
    parser.add_argument(
        'action',
        choices=['export', 'import', 'migrate'],
        help='操作: export(导出), import(导入), migrate(导出+导入)')
    parser.add_argument(
        '-c', '--config', required=True,
        help='YAML 配置文件路径')
    parser.add_argument(
        '-o', '--output-dir',
        help='覆盖配置中的输出目录')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='仅模拟运行，不实际操作')

    args = parser.parse_args()
    config = load_config(args.config)

    if args.output_dir:
        config.setdefault('options', {})['output_dir'] = args.output_dir
    if args.dry_run:
        config.setdefault('options', {})['dry_run'] = True

    engine = MigrationEngine(config)

    if args.action == 'export':
        engine.export_data()
    elif args.action == 'import':
        engine.import_data()
    elif args.action == 'migrate':
        engine.migrate()


if __name__ == '__main__':
    main()
'''
scp -o KexAlgorithms=+diffie-hellman-group1-sha1 \
-o HostKeyAlgorithms=+ssh-rsa,+ssh-dss \
-o MACs=+hmac-md5,hmac-sha1 \
-o Ciphers=+aes128-cbc,3des-cbc \
-r 192.168.209.222:/tmp/easyops/easyops-migration .
'''