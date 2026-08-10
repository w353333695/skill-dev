#!/usr/bin/env python3
"""
EasyOps API 调用脚本模板

支持两种认证方式:
    1. 内网调用（默认）: 通过 agent 配置自动获取 host/org
    2. OpenAPI 调用: 使用 AK/SK 签名认证

使用方法:
    1. 修改配置区域的参数（可选，默认从 agent 配置读取）
    2. 直接运行: python script_name.py

生成脚本时，根据实际 API 修改:
1. 添加具体的 API 方法（端口直接写在方法内）
2. 如需 OpenAPI 调用，配置 AK/SK 并补充 PORT_APP_MAP 类变量
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
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode
from pprint import pp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射（仅 OpenAPI 模式需要）
    # 根据实际用到的服务填写，从 openapi.yaml 获取
    PORT_APP_MAP = {
        # 8079: "cmdbservice",
        # 8073: "resource_manage",
        # 8181: "tool_service",
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

        # OpenAPI 模式
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
        host = dic['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]
        return host, str(org)

    def __signature(self, method: str, uri: str, params: Dict = None,
                    data: str = "{}") -> Dict:
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
        url_param = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))

        # Content-MD5（仅 POST/PUT）
        content_md5 = ""
        if method in ("POST", "PUT") and data:
            md5 = hashlib.md5()
            md5.update(data.encode("utf-8") if isinstance(data, str) else data)
            content_md5 = md5.hexdigest()

        # 构建签名字符串
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

    def _request(self, method: str, path: str, port: int,
                 **kwargs) -> requests.Response:
        """
        发送 HTTP 请求，自动根据认证模式选择内网或 OpenAPI 方式

        :param method: HTTP 方法
        :param path: API 路径
        :param port: 服务端口（内网直接使用，OpenAPI 用于查找 app_name）
        :param params: URL 参数
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
        else:
            # 内网模式：直接使用 host:port
            url = f"http://{self.host}:{port}/{path.lstrip('/')}"
        logger.debug(f">>> [{'OpenAPI' if self.is_openapi else '内网'}] {method} {url}")
        logger.debug(f">>> Body: {request_body[:2000] if request_body else 'None'}")
        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, timeout=20, **kwargs
        )

        logger.debug(f"<<< Status: {response.status_code}")
        logger.debug(f"<<< Response: {response.text[:2000]}")

        response.raise_for_status()
        return response

    def get_model_info(self, object_id: str) -> Dict:
        """
        获取模型信息

        API: GetObjectApi
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :return: 模型信息
        """
        port = 8079 
        path = f"object/{object_id}"
        result = self._request("GET", path, port=port).json()
        return result.get("data", {})

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 1000) -> Dict:
        """
        批量导入实例

        API: PostImportInstanceApi
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param data_list: 数据列表
        :param keys: 唯一键
        :param batch_size: 批量大小
        :return: 导入结果
        """
        port = 8079
        path = f"object/{object_id}/instance/_import"
        total_insert = 0
        total_update = 0
        total_failed = 0

        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            data = {
                "keys": keys,
                "datas": batch
            }

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


# =============================================================================
# 业务逻辑区域
# =============================================================================
# 注意：以下区域编写具体业务逻辑。EasyOpsClient 只负责 HTTP 请求封装，
# 不要把数据处理、文件读写、流程编排等业务逻辑放到 EasyOpsClient 类中。
# 如需新增 API 方法，在 EasyOpsClient 类中 _request 方法之后添加。


def main():
    """
    主入口函数，编排业务逻辑。

    典型流程：
        1. 初始化 EasyOpsClient
        2. 读取/准备数据（文件、数据库、其他 API 等）
        3. 调用 EasyOps API
        4. 处理返回结果
        5. 输出或写入下游系统
    """
    logger.setLevel(logging.DEBUG)

    # 1. 初始化客户端
    client = EasyOpsClient(
        # host=HOST, org=ORG, # 使用内部api，不指定host、org则自动从agent配置获取
        # user=USER, # 手动指定用户
        # ak=AK, sk=SK # 使用openapi方式
    )

    # 2. 调用 API（示例）
    model = client.get_model_info("HOST")
    print(json.dumps(model, ensure_ascii=False, indent=2))

    # 3. 批量导入实例（示例）
    data = [{"hostname": "web01", "ip": "192.168.1.1"}]
    result = client.import_instance("HOST", data, keys=["hostname"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()