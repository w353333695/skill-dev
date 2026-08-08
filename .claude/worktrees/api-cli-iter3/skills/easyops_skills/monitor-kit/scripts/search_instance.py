#!/usr/bin/env python3
"""
搜索 CMDB 模型实例

使用方式:
    python search_instance.py --model-id _COLLECTOR_EASYOPS_PLUGIN \
        --query '{"name":"插件名称"}' --host 172.30.0.90 --org 8888
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

    def search_instance(self, model_id: str, query: dict = None,
                        fields: list = None, page_size: int = 1000) -> list:
        """搜索 CMDB 模型实例

        :param model_id: 模型ID
        :param query: 查询条件 dict
        :param fields: 返回字段列表
        :param page_size: 每页大小
        :return: 实例列表
        """
        url = f"http://{self.host}:8079/v3/object/{model_id}/instance/_search"
        data = {
            "query": query or {},
            "fields": fields or ["*"],
            "page_size": page_size
        }
        logger.info(f"POST {url}")
        logger.debug(f"Body: {json.dumps(data, ensure_ascii=False)}")
        response = requests.post(
            url, headers=self.headers, json=data, timeout=30, verify=False
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(
                f"API 返回错误: code={result.get('code')}, "
                f"error={result.get('error', '')}"
            )
        return result.get("data", {}).get("list", [])


def main():
    parser = argparse.ArgumentParser(
        description="搜索 CMDB 模型实例"
    )
    parser.add_argument("--host", type=str, help="EasyOps 服务器地址")
    parser.add_argument("--org", type=str, help="组织 ID")
    parser.add_argument("--model-id", required=True, type=str,
                        help="模型ID，如 '_COLLECTOR_EASYOPS_PLUGIN'")
    parser.add_argument("--query", type=str, default="{}",
                        help="查询条件 JSON，如 '{\"name\":\"插件名\"}'")
    parser.add_argument("--fields", type=str, default="*",
                        help="返回字段，逗号分隔，默认 '*'")
    parser.add_argument("--page-size", type=int, default=1000,
                        help="每页大小（默认1000）")
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
        query = json.loads(args.query) if isinstance(args.query, str) else args.query
        fields = args.fields.split(",") if args.fields != "*" else ["*"]
        instances = client.search_instance(
            model_id=args.model_id, query=query,
            fields=fields, page_size=args.page_size
        )
        print(json.dumps(instances, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        logger.error(f"--query JSON 解析失败: {e}")
        sys.exit(1)
    except requests.HTTPError as e:
        logger.error(f"请求失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"搜索实例异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
