#!/usr/bin/env python3
"""
列出 CMDB 模型基本信息

使用方式:
    # 列出所有模型
    python list_models.py --host 172.30.0.90 --org 8888

    # 按关键字模糊搜索
    python list_models.py --keyword "REDIS" --host 172.30.0.90 --org 8888

    # 按分类筛选
    python list_models.py --category "基础设施" --host 172.30.0.90 --org 8888
"""

import argparse
import json
import logging
import platform
import sys
from typing import Optional

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EasyOpsClient:
    """轻量 EasyOps API 客户端"""

    def __init__(self, host: Optional[str] = None, org: Optional[str] = None):
        if not host:
            host, org = self._get_host_and_org_from_agent()
        self.host = host
        self.org = org
        self.headers = {
            "user": "defaultUser",
            "org": str(org),
            "Content-Type": "application/json"
        }

    @staticmethod
    def _get_host_and_org_from_agent() -> tuple:
        if platform.system().lower() == "windows":
            conf_path = "C:\\easyOps\\agent\\conf\\conf.yaml"
        else:
            conf_path = "/usr/local/easyops/agent/conf/conf.yaml"
        with open(conf_path, 'r') as f:
            dic = yaml.load(f, Loader=yaml.FullLoader)
        org = dic['base']['client_id']
        host = dic['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]
        return host, str(org)

    def list_object_basic(self, keyword: str = "", category: str = "",
                          page_size: int = 500) -> list:
        """列出 CMDB 模型基本信息

        :param keyword: 模型ID模糊匹配关键字
        :param category: 模型分类过滤
        :param page_size: 每页大小
        :return: 模型基本信息列表
        """
        url = f"http://{self.host}:8079/object_basic"
        params = {"page_size": page_size}
        if keyword:
            params["q"] = keyword
        if category:
            params["category"] = category
        logger.info(f"GET {url} params={params}")
        response = requests.get(
            url, headers=self.headers, params=params, timeout=30, verify=False
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"API 返回错误: code={data.get('code')}, "
                f"error={data.get('error', '')}"
            )
        return data.get("data", {}).get("list", [])


def main():
    parser = argparse.ArgumentParser(
        description="列出 CMDB 模型基本信息"
    )
    parser.add_argument("--host", type=str, help="EasyOps 服务器地址")
    parser.add_argument("--org", type=str, help="组织 ID")
    parser.add_argument("--keyword", type=str, default="",
                        help="模型ID模糊匹配关键字")
    parser.add_argument("--category", type=str, default="",
                        help="模型分类过滤")
    parser.add_argument("--page-size", type=int, default=500,
                        help="每页大小（默认500）")
    parser.add_argument("--debug", action="store_true", help="开启调试日志")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        client = EasyOpsClient(host=args.host, org=args.org)
    except FileNotFoundError:
        if not args.host:
            logger.error("未找到 agent 配置文件，请通过 --host/--org 手动指定")
            sys.exit(1)
        raise

    try:
        models = client.list_object_basic(
            keyword=args.keyword, category=args.category,
            page_size=args.page_size
        )
        print(json.dumps(models, ensure_ascii=False, indent=2))
    except requests.HTTPError as e:
        logger.error(f"请求失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"获取模型列表异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
