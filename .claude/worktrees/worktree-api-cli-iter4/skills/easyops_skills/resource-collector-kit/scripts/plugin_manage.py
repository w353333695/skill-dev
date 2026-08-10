#!/usr/bin/env python3
"""
EasyOps 插件管理脚本 —— 导入 / 更新 / 激活

使用方式:
    # 导入插件
    python plugin_manage.py import --file plugin_v1.0.0.zip --name 插件名称

    # 更新插件
    python plugin_manage.py update --file plugin_v1.0.1.zip --plugin-id <instanceId> --version 1.0.1

    # 激活采集套件
    python plugin_manage.py activate --plugin-id <instanceId> --model-id HOST

认证:
    内网: 自动从 agent 配置读取 host/org
    手动: --host 172.30.0.90 --org 1888
"""

import argparse
import json
import logging
import os
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
    """轻量 EasyOps API 客户端，支持文件上传"""

    PORT_8151 = 8151  # plugin service
    PORT_12000 = 12000  # collector service

    def __init__(self, host: Optional[str] = None, org: Optional[str] = None):
        if not host:
            host, org = self._get_host_and_org_from_agent()
        self.host = host
        self.org = org

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

    def import_plugin(self, file_path: str, name: str = "",
                      version: str = "1.0.0") -> dict:
        """导入插件"""
        url = f"http://{self.host}:{self.PORT_8151}/api/v1/plugin/import"
        if not name:
            name = os.path.splitext(os.path.basename(file_path))[0]
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f,
                              "application/zip")}
            form_data = {"name": name, "version": version}
            logger.info(f"POST {url} name={name} version={version}")
            response = requests.post(
                url, headers={"user": "defaultUser", "org": str(self.org)},
                files=files, data=form_data, timeout=120, verify=False
            )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(
                f"导入失败: code={result.get('code')}, "
                f"error={result.get('error', '')}"
            )
        return result.get("data", {})

    def update_plugin(self, file_path: str, plugin_instance_id: str,
                      version: str = "1.0.1") -> dict:
        """更新插件"""
        url = (f"http://{self.host}:{self.PORT_8151}"
               f"/api/v1/plugin/import_update/{plugin_instance_id}")
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f,
                              "application/zip")}
            form_data = {"version": version}
            logger.info(f"PUT {url} version={version}")
            response = requests.put(
                url, headers={"user": "defaultUser", "org": str(self.org)},
                files=files, data=form_data, timeout=120, verify=False
            )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(
                f"更新失败: code={result.get('code')}, "
                f"error={result.get('error', '')}"
            )
        return result.get("data", {})

    def activate_collector_kit(self, plugin_instance_id: str,
                                model_id: str = "") -> dict:
        """激活采集套件"""
        url = f"http://{self.host}:{self.PORT_12000}/api/v1/collector/kit/activate"
        data = {"pluginInstanceId": plugin_instance_id}
        if model_id:
            data["relateObjectId"] = model_id
        logger.info(f"POST {url} pluginInstanceId={plugin_instance_id}")
        response = requests.post(
            url,
            headers={
                "user": "defaultUser",
                "org": str(self.org),
                "Content-Type": "application/json"
            },
            json=data, timeout=60, verify=False
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(
                f"激活失败: code={result.get('code')}, "
                f"error={result.get('error', '')}"
            )
        return result.get("data", {})


def cmd_import(args, client: EasyOpsClient):
    if not os.path.isfile(args.file):
        logger.error(f"文件不存在: {args.file}")
        sys.exit(1)
    result = client.import_plugin(
        file_path=args.file, name=args.name or "",
        version=args.version or "1.0.0"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info("导入成功")


def cmd_update(args, client: EasyOpsClient):
    if not os.path.isfile(args.file):
        logger.error(f"文件不存在: {args.file}")
        sys.exit(1)
    if not args.plugin_id:
        logger.error("请通过 --plugin-id 指定插件实例ID")
        sys.exit(1)
    result = client.update_plugin(
        file_path=args.file, plugin_instance_id=args.plugin_id,
        version=args.version or "1.0.1"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info("更新成功")


def cmd_activate(args, client: EasyOpsClient):
    if not args.plugin_id:
        logger.error("请通过 --plugin-id 指定插件实例ID")
        sys.exit(1)
    result = client.activate_collector_kit(
        plugin_instance_id=args.plugin_id, model_id=args.model_id or ""
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info("激活成功")


def main():
    parser = argparse.ArgumentParser(
        description="EasyOps 插件管理 —— 导入 / 更新 / 激活",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s import --file plugin_v1.0.0.zip --name 插件名称
  %(prog)s update --file plugin_v1.0.1.zip --plugin-id <instanceId>
  %(prog)s activate --plugin-id <instanceId>
        """
    )
    parser.add_argument("--host", type=str, help="EasyOps 服务器地址")
    parser.add_argument("--org", type=str, help="组织 ID")
    parser.add_argument("--debug", action="store_true", help="开启调试日志")

    subparsers = parser.add_subparsers(dest="command", help="操作命令")
    subparsers.required = True

    p = subparsers.add_parser("import", help="导入插件")
    p.add_argument("--file", required=True, help="插件 zip 包路径")
    p.add_argument("--name", help="插件名称（默认取文件名）")
    p.add_argument("--version", default="1.0.0", help="版本号（默认1.0.0）")

    p = subparsers.add_parser("update", help="更新插件")
    p.add_argument("--file", required=True, help="插件 zip 包路径")
    p.add_argument("--plugin-id", required=True, help="插件实例ID")
    p.add_argument("--version", default="1.0.1", help="版本号（默认1.0.1）")

    p = subparsers.add_parser("activate", help="激活采集套件")
    p.add_argument("--plugin-id", required=True, help="插件实例ID")
    p.add_argument("--model-id", default="", help="目标模型ID")

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
        if args.command == "import":
            cmd_import(args, client)
        elif args.command == "update":
            cmd_update(args, client)
        elif args.command == "activate":
            cmd_activate(args, client)
    except requests.HTTPError as e:
        logger.error(f"请求失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"操作异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
