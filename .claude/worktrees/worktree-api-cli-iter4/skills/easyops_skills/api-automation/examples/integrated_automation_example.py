#!/usr/bin/env python3
"""
综合自动化脚本示例：从 CSV 读取主机数据，处理后批量导入 EasyOps CMDB

此示例展示如何结合 EasyOps API 与数据处理、文件读写等逻辑。
核心原则：EasyOpsClient 只做 HTTP 请求封装，业务逻辑完全外置。
"""

import csv
import json
import logging
import hashlib
import hmac
import platform
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# EasyOps API 客户端（保持模板结构，只添加具体 API 方法）
# =============================================================================

class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    PORT_APP_MAP = {}

    def __init__(self, host: Optional[str] = None, org: Optional[str] = None,
                 user: str = "defaultUser", ak: str = "", sk: str = ""):
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

    def _request(self, method: str, path: str, port: int,
                 **kwargs) -> requests.Response:
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
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(
                    f"端口 {port} 未在 PORT_APP_MAP 中配置"
                )
            uri = f"/{app_name}/{path.lstrip('/')}"
            url = f"http://{self.host}{uri}"
            sign_params = self.__signature(
                method, uri, params=params, data=request_body or "{}"
            )
            url = url + "?" + urlencode(sign_params)
            params = None
            if method in ("GET", "DELETE"):
                headers.pop("Content-Type", None)
            headers.pop('org', None)
        else:
            url = f"http://{self.host}:{port}/{path.lstrip('/')}"
        logger.debug(f">>> [{'OpenAPI' if self.is_openapi else '内网'}] {method} {url}")
        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, timeout=20, **kwargs
        )
        response.raise_for_status()
        return response

    def search_instances(self, object_id: str, query: Dict = None,
                         page: int = 1, page_size: int = 100) -> Dict:
        """
        搜索实例

        API: PostSearchV3
        服务: logic.cmdb.service
        端口: 8079
        """
        port = 8079
        path = f"v3/object/{object_id}/instance/_search"
        payload = query or {"fields": ["*"], "page": page, "page_size": page_size}
        return self._request("POST", path, port=port, data=payload).json()

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 1000) -> Dict:
        """
        批量导入实例

        API: PostImportInstanceApi
        服务: logic.cmdb.service
        端口: 8079
        """
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


# =============================================================================
# 业务逻辑区域（数据处理、文件读写、流程编排）
# =============================================================================

def read_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    从 CSV 文件读取原始数据。

    :param file_path: CSV 文件路径
    :return: 每行数据转为字典的列表
    """
    rows = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    logger.info(f"从 {file_path} 读取 {len(rows)} 条原始数据")
    return rows


def transform_host_data(raw_data: List[Dict]) -> List[Dict]:
    """
    将原始 CSV 数据转换为 EasyOps CMDB HOST 模型格式。

    字段映射示例：
        csv_hostname -> hostname
        csv_ip       -> ip
        csv_os       -> os

    :param raw_data: 原始数据列表
    :return: 转换后的数据列表
    """
    transformed = []
    for row in raw_data:
        item = {
            "hostname": row.get("csv_hostname", "").strip(),
            "ip": row.get("csv_ip", "").strip(),
            "os": row.get("csv_os", "").strip(),
        }
        transformed.append(item)
    logger.info(f"数据转换完成，共 {len(transformed)} 条")
    return transformed


def validate_host_data(data: List[Dict]) -> tuple:
    """
    校验主机数据合法性。

    规则：
        - hostname 不能为空
        - ip 必须符合基本格式

    :param data: 待校验数据
    :return: (合法数据列表, 非法数据列表)
    """
    valid = []
    invalid = []
    for item in data:
        errors = []
        if not item.get("hostname"):
            errors.append("hostname 为空")
        ip = item.get("ip", "")
        if not ip or "." not in ip:
            errors.append(f"ip 格式错误: {ip}")

        if errors:
            item["_errors"] = errors
            invalid.append(item)
        else:
            valid.append(item)

    logger.info(f"校验结果：合法 {len(valid)} 条，非法 {len(invalid)} 条")
    return valid, invalid


def write_report(results: Dict, invalid_data: List[Dict], output_dir: str):
    """
    写入执行报告和非法数据文件。

    :param results: API 调用结果统计
    :param invalid_data: 校验未通过的数据
    :param output_dir: 输出目录
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 执行报告
    report = {
        "generated_at": datetime.now().isoformat(),
        "import_result": results,
        "invalid_count": len(invalid_data),
    }
    report_file = output_path / "report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"执行报告已写入: {report_file}")

    # 非法数据
    if invalid_data:
        invalid_file = output_path / "invalid_data.json"
        with open(invalid_file, 'w', encoding='utf-8') as f:
            json.dump(invalid_data, f, ensure_ascii=False, indent=2)
        logger.info(f"非法数据已写入: {invalid_file}")


def main():
    """
    主入口：编排完整自动化流程。

    流程：
        1. 初始化 EasyOpsClient
        2. 从 CSV 读取源数据
        3. 数据转换（字段映射、格式清洗）
        4. 数据校验（过滤非法数据）
        5. 调用 EasyOps API 批量导入
        6. 生成执行报告
    """
    # 配置
    input_csv = "hosts.csv"
    output_dir = "output"
    object_id = "HOST"
    unique_keys = ["hostname"]

    # 1. 初始化客户端
    client = EasyOpsClient()

    # 2. 读取源数据
    raw_data = read_csv(input_csv)

    # 3. 数据转换
    transformed = transform_host_data(raw_data)

    # 4. 数据校验
    valid_data, invalid_data = validate_host_data(transformed)

    if not valid_data:
        logger.warning("没有合法数据可供导入，流程结束")
        write_report({"insert_count": 0, "update_count": 0, "failed_count": 0},
                     invalid_data, output_dir)
        return

    # 5. 调用 EasyOps API 批量导入
    results = client.import_instance(object_id, valid_data, keys=unique_keys)

    # 6. 生成报告
    write_report(results, invalid_data, output_dir)
    logger.info("自动化流程执行完毕")


if __name__ == "__main__":
    main()
