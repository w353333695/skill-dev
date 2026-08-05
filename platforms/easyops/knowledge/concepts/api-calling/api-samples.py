#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""
EasyOps api调用示例（Python 2 / Python 3 通用）

支持两种认证方式:
    1. 内网调用（默认）: 通过 agent 配置自动获取 host/org
    2. OpenAPI 调用: 使用 AK/SK 签名认证
"""

import json
import logging
import hashlib
import hmac
import platform
import time

# py2/py3 兼容：urlencode 位置不同
try:
    from urllib.parse import urlencode  # py3
except ImportError:
    from urllib import urlencode  # py2
    reload(sys)
    sys.setdefaultencoding("utf-8")

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _to_bytes(data):
    """py2/py3 兼容：统一转成 bytes（供 md5/hmac 使用）"""
    if isinstance(data, bytes):
        return data
    return data.encode("utf-8")


class EasyOpsClient(object):
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射（仅 OpenAPI 模式需要）
    PORT_APP_MAP = {
        8079: "cmdbservice",
    }

    def __init__(self, host=None, org=None,
                 user="defaultUser", ak="", sk=""):
        """
        初始化客户端

        :param host: EasyOps 服务器地址，None 则从 agent 配置读取
        :param org: 组织 ID，None 则从 agent 配置读取
        :param user: 用户名
        :param ak: Access Key，用于 OpenAPI 认证
        :param sk: Secret Key，用于 OpenAPI 签名
        """
        if not host:
            host, org = self.__get_host_and_org()
        self.host = host
        self.org = org
        self.headers = {
            "user": user,
            "org": org,
            "Content-Type": "application/json"
        }

        # OpenAPI 模式
        if ak and sk:
            self.is_openapi = True
            self.ak = ak
            self.sk = sk
            self.headers["Host"] = "openapi.easyops-only.com"
        else:
            self.is_openapi = False

    def __get_host_and_org(self):
        """从 agent 配置文件中获取 host 和 org 信息"""
        if platform.system().lower() == "windows":
            conf_path = "C:\\easyOps\\agent\\conf\\conf.yaml"
        else:
            conf_path = "/usr/local/easyops/agent/conf/conf.yaml"
        with open(conf_path, 'r') as f:
            if hasattr(yaml, 'FullLoader'):
                dic = yaml.load(f, Loader=yaml.FullLoader)
            else:
                dic = yaml.load(f, Loader=yaml.Loader)
        org = dic['base']['client_id']
        host = dic['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]
        return host, str(org)

    def __signature(self, method, uri, params=None, data="{}"):
        """
        生成 OpenAPI HMAC-SHA1 签名

        :param method: HTTP 方法
        :param uri: 请求 URI（含 app_name 前缀）
        :param params: URL 查询参数
        :param data: 请求体 JSON 字符串
        :return: 包含签名的参数字典
        """
        params = dict(params) if params else {}
        request_time = str(int(time.time()))
        method = method.upper()

        # POST/PUT 需要 Content-Type，GET/DELETE 不需要
        if method in ("POST", "PUT"):
            content_type = "application/json"
        else:
            content_type = ""

        # URL 参数排序拼接
        url_param = "".join("{0}{1}".format(k, params[k]) for k in sorted(params.keys()))

        # Content-MD5（仅 POST/PUT）
        content_md5 = ""
        if method in ("POST", "PUT") and data:
            md5 = hashlib.md5()
            md5.update(_to_bytes(data))
            content_md5 = md5.hexdigest()

        # 构建签名字符串
        string_to_sign = "\n".join([
            method, uri, url_param, content_type,
            content_md5, request_time, self.ak
        ]).encode("utf-8")

        signature = hmac.new(
            _to_bytes(self.sk), string_to_sign, hashlib.sha1
        ).hexdigest()

        params.update({
            "accesskey": self.ak,
            "signature": signature,
            "expires": request_time
        })
        return params

    def _request(self, method, path, port, **kwargs):
        """
        发送 HTTP 请求，自动根据认证模式选择内网或 OpenAPI 方式

        :param method: HTTP 方法
        :param path: API 路径
        :param port: 服务端口（内网直接使用，OpenAPI 用于查找 app_name）
        :return: requests.Response 对象
        """
        data = kwargs.get('data')
        params = kwargs.get('params')
        if data:
            request_body = json.dumps(data)
            del kwargs['data']
        else:
            request_body = None
        method = method.upper()
        headers = self.headers.copy()

        if self.is_openapi:
            # OpenAPI 模式：通过端口查找 app_name，构建 URI 并签名
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(
                    "端口 {0} 未在 PORT_APP_MAP 中配置，"
                    "请在类变量 PORT_APP_MAP 中补充映射".format(port)
                )
            uri = "/{0}/{1}".format(app_name, path.lstrip('/'))
            url = "http://{0}{1}".format(self.host, uri)

            # 生成签名参数
            sign_params = self.__signature(
                method, uri, params=params, data=request_body or "{}"
            )
            url = url + "?" + urlencode(sign_params)
            params = None

            # OpenAPI 模式下 GET/DELETE 不发 Content-Type
            if method in ("GET", "DELETE"):
                headers.pop("Content-Type", None)
            headers.pop('org', None)
        else:
            # 内网模式：直接使用 host:port
            url = "http://{0}:{1}/{2}".format(self.host, port, path.lstrip('/'))
        logger.debug(">>> [{0}] {1} {2}".format(
            'OpenAPI' if self.is_openapi else '内网', method, url))
        logger.debug(">>> Body: {0}".format(request_body[:2000] if request_body else 'None'))
        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, timeout=20, **kwargs
        )

        logger.debug("<<< Status: {0}".format(response.status_code))
        logger.debug("<<< Response: {0}".format(response.text[:2000]))

        response.raise_for_status()
        return response

    # =====================================================================
    # 以下为具体 API 方法（端口直接写在方法内）
    # =====================================================================

    def search_instances(self, object_id, query=None,
                         fields=None, page_size=1000):
        """
        搜索实例（自动翻页返回全部数据）

        EasyOps API: PostSearchV3
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param query: 查询条件，如 {"name": {"$like": "%xx%"}}
        :param fields: 指定返回字段，None 表示返回全部
        :param page_size: 每页条数，默认 1000
        :return: 实例列表
        """
        port = 8079
        path = "v3/object/{0}/instance/_search".format(object_id)
        body = {
            "fields": fields if fields else ["*"],
            "query": query if query else {},
            "page": 1,
            "page_size": page_size,
        }
        all_list = []
        page = 1
        while True:
            body["page"] = page
            resp = self._request("POST", path, port=port, data=body).json()
            data = resp.get("data", {})
            items = data.get("list", [])
            all_list.extend(items)
            total = data.get("total", 0)
            logger.info("[{0}] 已获取 {1}/{2} 条".format(object_id, len(all_list), total))
            if len(items) < page_size or not items:
                break
            page += 1
            time.sleep(1)
        return all_list
    # =====================================================================
    # 以下为giraffe-contract类型契约的调用
    # =====================================================================
    def activate_collector_kit(self, plugin_instance_id, relate_object_id=None,
                               param=None, query=None,
                               centralized_enable=False, host_ids=None,
                               collect_agent=None, not_require_job=False):
        """
        启用/激活采集套件

        EasyOps API: ActivateCollectorKit
        服务: easyops.api.collector_service.job.ActivateCollectorKit

        :param plugin_instance_id: 插件ID（必填）
        :param relate_object_id: 激活模型ID（可选）
        :param param: 启用参数列表，格式 [{"key": "参数名", "value": "参数值", "paramType": "类型"}]
        :param query: 查询条件，格式 {"filter": "过滤条件"}
        :param centralized_enable: 是否集中采集（默认False）
        :param host_ids: 集中采集的实例ID列表
        :param collect_agent: 执行采集的机器IP
        :param not_require_job: 是否不创建采集任务（默认False）
        :return: 激活结果，包含 resources, totalStatus, relateObjectId
        """
        port = 12000
        path = 'api/v1/collector/kit/activate'

        data = {
            'instanceId': plugin_instance_id,
            'centralizedEnable': centralized_enable,
            'notRequireJob': not_require_job
        }

        if relate_object_id:
            data['relateObjectId'] = relate_object_id
        if param:
            data['param'] = param
        if query:
            data['query'] = query
        if host_ids:
            data['hostIds'] = host_ids
        if collect_agent:
            data['collectAgent'] = collect_agent

        # 临时添加 giraffe-contract-name header
        original_headers = self.headers.copy()
        self.headers['giraffe-contract-name'] = 'easyops.api.collector_service.job.ActivateCollectorKit'
        try:
            response = self._request('POST', path, port=port, timeout=60, data=data)
        finally:
            self.headers = original_headers
        result = response.json()

        data = result.get('data', result)
        resources = data.get('resources', [])
        if result.get('code') == 0:
            logger.info('导入成功')
        for res in resources:
            logger.info("  - {0}: {1} -> {2} (数量: {3})".format(
                res.get('type', ''), res.get('name', ''),
                res.get('result', ''), res.get('count', 0)))

        return data


if __name__ == "__main__":
    logger.setLevel(logging.INFO)
    cli = EasyOpsClient()
    res = cli.search_instances(
        'FLOW_BUILDER_API_CONTRACT@EASYOPS',
        fields=['*'],
        query={"namespaceId": {"$like": "easyops%"}}
    )
