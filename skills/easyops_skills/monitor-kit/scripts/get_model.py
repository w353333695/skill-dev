#!/usr/bin/env python3
"""
获取 CMDB 模型描述信息

使用方式:
    # 指定主机和组织
    python get_model.py --model-id REDIS@ONEMODEL --host 172.30.0.90 --org 1888

    # 自动从 agent 配置读取 host/org（需在 EasyOps agent 节点上执行）
    python get_model.py --model-id REDIS@ONEMODEL
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
    """轻量 EasyOps API 客户端，用于获取 CMDB 模型描述"""

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
        """从 EasyOps agent 配置文件读取 host 和 org"""
        if platform.system().lower() == "windows":
            conf_path = "C:\\easyOps\\agent\\conf\\conf.yaml"
        else:
            conf_path = "/usr/local/easyops/agent/conf/conf.yaml"
        with open(conf_path, 'r') as f:
            dic = yaml.load(f, Loader=yaml.FullLoader)
        org = dic['base']['client_id']
        host = dic['command']['server_groups'][0]['hosts'][0]['ip'].split(',')[0]
        return host, str(org)

    def get_model_desc(self, model_id: str) -> dict:
        """获取 CMDB 模型描述信息

        :param model_id: 模型ID，如 'REDIS@ONEMODEL'
        :return: 模型描述 dict，可直接保存为 models.json
        """
        url = f"http://{self.host}:8079/object/{model_id}"
        logger.info(f"GET {url}")
        response = requests.get(
            url, headers=self.headers, timeout=30, verify=False
        )
        response.raise_for_status()
        data = response.json()
        code = data.get("code")
        if code != 0:
            error_msg = data.get("error", data.get("message", "未知错误"))
            raise RuntimeError(f"API 返回错误: code={code}, error={error_msg}")
        return data.get("data", {})


def main():
    parser = argparse.ArgumentParser(
        description="获取 CMDB 模型描述信息"
    )
    parser.add_argument("--host", type=str, help="EasyOps 服务器地址")
    parser.add_argument("--org", type=str, help="组织 ID")
    parser.add_argument("--model-id", required=True, type=str,
                        help="模型ID，如 'REDIS@ONEMODEL'")
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
        desc = client.get_model_desc(args.model_id)
        print(json.dumps(desc, ensure_ascii=False, indent=2))
    except requests.HTTPError as e:
        logger.error(f"请求失败: {e}")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"{e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"获取模型描述异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
