#!/usr/bin/env python3
"""
CMDB 数据采集脚本模板

支持两种认证方式写入 CMDB:
    1. 内网调用（默认）: 通过 agent 配置自动获取 host/org
    2. OpenAPI 调用: 使用 AK/SK 签名认证

使用方法:
    1. 修改配置区域的参数（可选，默认从 agent 配置读取）
    2. 直接运行: python collector.py

生成脚本时，根据实际需求修改:
1. MODELS 配置 - 定义每个模型的 API 路径、唯一键、字段映射
2. ThirdPartyClient - 三方 API 调用逻辑
3. 如需 OpenAPI 调用，配置 AK/SK 并补充 PORT_APP_MAP 类变量
"""

import requests
import json
import logging
import time
import platform
import hashlib
import hmac
import yaml
from functools import wraps
from typing import List, Dict, Any, Optional, Callable, Tuple, Union
from urllib.parse import urlencode

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ============ 配置区域 - 根据实际情况修改 ============
# EasyOps 配置（设置为 None 时自动从 agent 配置文件读取）
HOST = None               # EasyOps 服务器地址，None 则从 agent 配置读取
ORG = None                # 组织 ID，None 则从 agent 配置读取
BATCH_SIZE = 1000         # 批量导入大小

# 三方 API 配置
API_URL = "https://api.example.com"  # 三方 API 地址
API_KEY = ""              # 三方 API 密钥（如需要）

# OpenAPI 认证配置（留空则使用内网调用方式）
AK = ""  # Access Key
SK = ""  # Secret Key
# ====================================================

# ============ 模型配置 ============
# 字段映射规则:
#   "cmdb_field": "source_field"            - 简单字段映射
#   "cmdb_field": "parent.child"            - 嵌套字段（点号分隔）
#   "cmdb_field": ("source_field", default) - 带默认值
#   "cmdb_field": lambda item: expr         - 自定义转换
#
# 关系字段映射:
#   "clusters": lambda item: [{"clusterId": cid} for cid in item.get("clusterIds", [])]
# ====================================
MODELS = {
    "CLUSTER@OCP": {
        "api": "/api/v1/ob/clusters",
        "keys": ["clusterId"],
        "mapping": {
            "clusterId": "id",
            "name": "name",
            "status": ("status", "unknown"),
            "region": "metadata.region",
            "version": "obVersion",
            "ctime": lambda item: parse_datetime(item.get("createTime")),
        },
    },
    "TENANT@OCP": {
        "api": "/api/v1/ob/tenants",
        "keys": ["tenantId"],
        "mapping": {
            "tenantId": "id",
            "name": "name",
            "mode": "mode",
            "status": "status",
            # 关系字段：关联 CLUSTER 模型
            "clusters": lambda item: [{"clusterId": item.get("clusterId")}] if item.get("clusterId") else [],
        },
    },
}


def parse_datetime(value: Any) -> Optional[str]:
    """
    日期时间格式转换（参见 examples/parse_datetime.py 获取完整实现）
    将各种日期时间格式统一转换为 YYYY-MM-DD HH:MM:SS
    """
    if not value:
        return None
    # 根据实际格式实现转换
    return str(value)


def retry(times=3, delay=1, backoff=2):
    """重试装饰器"""
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
                        logger.error(f"重试{times}次后仍然失败: {e}")
                        raise
                    logger.warning(f"第{attempt}次尝试失败,{current_delay}秒后重试: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator


def get_nested(data: Dict, path: str, default=None):
    """
    按点号路径获取嵌套字段值

    :param data: 源数据字典
    :param path: 字段路径，支持点号分隔，如 "metadata.region"
    :param default: 未找到时的默认值
    :return: 字段值
    """
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default


def transform(raw_data: List[Dict], mapping: Dict[str, Any]) -> List[Dict]:
    """
    通用数据转换函数，根据字段映射配置转换数据

    :param raw_data: 原始数据列表
    :param mapping: 字段映射配置
    :return: 转换后的数据列表

    映射值类型:
        str              - 字段路径（支持点号嵌套）
        tuple(str, any)  - (字段路径, 默认值)
        callable         - 自定义转换函数，接收整条原始数据
    """
    result = []
    for item in raw_data:
        row = {}
        for cmdb_field, source in mapping.items():
            if callable(source):
                row[cmdb_field] = source(item)
            elif isinstance(source, tuple):
                path, default = source
                row[cmdb_field] = get_nested(item, path, default)
            else:
                row[cmdb_field] = get_nested(item, source)
        result.append(row)
    return result


class ThirdPartyClient:
    """三方 API 客户端 - 根据实际 API 修改"""

    def __init__(self, api_url: str, api_key: str = None):
        self.api_url = api_url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    @retry()
    def fetch_data(self, api_path: str) -> List[Dict]:
        """
        从三方 API 获取数据

        :param api_path: API 路径，如 /api/v1/clusters
        :return: 数据列表
        """
        url = f"{self.api_url}{api_path}"
        response = requests.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        # 根据实际响应结构修改
        return result.get("data", [])


class CMDBClient:
    """EasyOps CMDB 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射（仅 OpenAPI 模式需要）
    # 根据实际用到的服务填写，从 openapi.yaml 获取
    PORT_APP_MAP = {
        8079: "cmdbservice",
    }

    def __init__(self, host: Optional[str] = None, org: Optional[str] = None,
                 user: str = "defaultUser", ak: str = "", sk: str = ""):
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

        if ak and sk:
            self.is_openapi = True
            self.ak = ak
            self.sk = sk
            self.headers["Host"] = "openapi.easyops-only.com"
        else:
            self.is_openapi = False

    def __get_host_and_org(self) -> tuple:
        """从 agent 配置文件中获取 host 和 org 信息"""
        if platform.system().lower() == "windows":
            conf_path = "C:\\easyOps\\agent\\conf\\conf.yaml"
        else:
            conf_path = "/usr/local/easyops/agent/conf/conf.yaml"
        with open(conf_path, 'r') as f:
            dic = yaml.load(f, Loader=yaml.FullLoader)
        org = dic['base']['client_id']
        host = dic['command']['server_groups'][0]['hosts'][0]['ip']
        return host, str(org)

    def __signature(self, method: str, uri: str, params: Dict = None,
                    data: str = "{}") -> Dict:
        """生成 OpenAPI HMAC-SHA1 签名"""
        params = dict(params) if params else {}
        request_time = str(int(time.time()))
        method = method.upper()

        if method in ("POST", "PUT"):
            content_type = "application/json"
        else:
            content_type = ""

        url_param = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))

        content_md5 = ""
        if method in ("POST", "PUT") and data:
            md5 = hashlib.md5()
            md5.update(data.encode("utf-8") if isinstance(data, str) else data)
            content_md5 = md5.hexdigest()

        string_to_sign = "\n".join([
            method, uri, url_param, content_type,
            content_md5, request_time, self.ak
        ]).encode()

        signature = hmac.new(
            self.sk.encode(), string_to_sign, hashlib.sha1
        ).hexdigest()

        params.update({
            "accesskey": self.ak,
            "signature": signature,
            "expires": request_time
        })
        return params

    @retry()
    def _request(self, method: str, path: str, port: int,
                 data: Dict = None, params: Dict = None) -> requests.Response:
        """
        发送 HTTP 请求，自动根据认证模式选择内网或 OpenAPI 方式

        :param method: HTTP 方法
        :param path: API 路径
        :param port: 服务端口（内网直接使用，OpenAPI 用于查找 app_name）
        :param data: 请求体
        :param params: URL 参数
        :return: 响应 JSON
        """
        request_body = json.dumps(data) if data else None
        method = method.upper()
        headers = self.headers.copy()

        if self.is_openapi:
            # OpenAPI 模式：通过端口查找 app_name，构建 URI 并签名
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(
                    f"端口 {port} 未在 PORT_APP_MAP 中配置，"
                    f"请在类变量 PORT_APP_MAP 中补充映射"
                )
            uri = f"/{app_name}/{path.lstrip('/')}"
            url = f"http://{self.host}{uri}"

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
            logger.debug(f">>> [OpenAPI] {method} {url}")
        else:
            # 内网模式：直接使用 host:port
            url = f"http://{self.host}:{port}/{path.lstrip('/')}"
            logger.debug(f">>> [内网] {method} {url}")
            logger.debug(f">>> Body: {request_body[:2000] if request_body else 'None'}")
        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, params=params,
            timeout=30, verify=False
        )

        logger.debug(f"<<< Status: {response.status_code}")
        logger.debug(f"<<< Response: {response.text[:2000]}")

        response.raise_for_status()
        return response

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 1000) -> Dict:
        """批量导入实例到 CMDB"""
        port = 8079
        path = f"object/{object_id}/instance/_import"
        total_insert = 0
        total_update = 0
        total_failed = 0

        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            data = {"keys": keys, "datas": batch}

            result = self._request("POST", path, port=port, data=data).json()
            result_data = result.get("data", {})

            total_insert += result_data.get("insert_count", 0)
            total_update += result_data.get("update_count", 0)
            total_failed += result_data.get("failed_count", 0)

            logger.info(f"批次 {i // batch_size + 1}: "
                        f"新增 {result_data.get('insert_count', 0)}, "
                        f"更新 {result_data.get('update_count', 0)}, "
                        f"失败 {result_data.get('failed_count', 0)}")

        return {
            "insert_count": total_insert,
            "update_count": total_update,
            "failed_count": total_failed
        }


def run_collect(models: Dict, third_party: ThirdPartyClient,
                cmdb: CMDBClient, batch_size: int = 1000):
    """
    执行多模型数据采集

    :param models: 模型配置字典（MODELS）
    :param third_party: 三方 API 客户端
    :param cmdb: CMDB 客户端
    :param batch_size: 批量导入大小
    """
    for object_id, conf in models.items():
        logger.info(f"========== 采集 {object_id} ==========")

        # 1. 获取三方数据
        api_path = conf["api"]
        logger.info(f"从 {api_path} 获取数据...")
        raw_data = third_party.fetch_data(api_path)
        logger.info(f"获取到 {len(raw_data)} 条原始数据")

        if not raw_data:
            logger.warning(f"{object_id} 无数据，跳过")
            continue

        # 2. 数据转换
        transformed = transform(raw_data, conf["mapping"])
        logger.info(f"转换后 {len(transformed)} 条数据")

        # 3. 导入 CMDB
        keys = conf["keys"]
        result = cmdb.import_instance(object_id, transformed, keys, batch_size)
        logger.info(f"{object_id} 导入完成: "
                    f"新增 {result['insert_count']}, "
                    f"更新 {result['update_count']}, "
                    f"失败 {result['failed_count']}")


if __name__ == "__main__":
    # ============ 使用示例 ============
    logger.setLevel(logging.DEBUG)

    third_party = ThirdPartyClient(API_URL, API_KEY)
    cmdb = CMDBClient(HOST, ORG, ak=AK, sk=SK)

    # 采集所有模型
    run_collect(MODELS, third_party, cmdb, BATCH_SIZE)

    # 也可以只采集指定模型
    # single = {"CLUSTER@OCP": MODELS["CLUSTER@OCP"]}
    # run_collect(single, third_party, cmdb, BATCH_SIZE)
