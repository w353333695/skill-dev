#!/usr/bin/env python3
"""
EasyOps 插件管理脚本 —— 导入 / 更新 / 激活

使用方式:
    # 导入插件
    python plugin_manage.py import --file plugin_v1.0.0.zip --name 插件名称 --category 自定义

    # 更新插件
    python plugin_manage.py update --file plugin_v1.0.1.zip --plugin-id <instanceId> --version 1.0.1

    # 激活采集套件（默认仅激活插件、不创建采集任务；加 --create-job 同步建任务）
    python plugin_manage.py activate --plugin-id <instanceId> --model-id STORAGE@ONEMODEL

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


def _parse_result(response: requests.Response, action: str = "操作") -> dict:
    """统一解析 EasyOps 响应：HTTP 错误或业务 code!=0 时抛出并附响应体，便于排查。

    平台 4xx 错误体含 codeExplain/error 字段，直接 raise_for_status 会丢失，
    故先读取响应体再决定是否抛错。
    """
    if response.status_code >= 400:
        raise RuntimeError(
            f"{action}失败: HTTP {response.status_code} "
            f"body={response.text[:500]}"
        )
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError(
            f"{action}失败: 响应非 JSON, body={response.text[:500]}"
        )
    # code 不存在视为成功（部分接口直接返回数据）；code==0 为成功
    if "code" in result and result.get("code") != 0:
        raise RuntimeError(
            f"{action}失败: code={result.get('code')}, "
            f"codeExplain={result.get('codeExplain', '')}, "
            f"error={result.get('error', '')}"
        )
    return result.get("data", result)


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
                      version: str = "1.0.0", category: str = "自定义") -> dict:
        """导入插件

        平台 multipart 文件字段名必须为 `attachment`（非 `file`），且需带 `category` 表单字段，
        否则返回 400 ERR_INVALID_ARGUMENT "file不能为空"。
        """
        url = f"http://{self.host}:{self.PORT_8151}/api/v1/plugin/import"
        if not name:
            name = os.path.splitext(os.path.basename(file_path))[0]
        with open(file_path, "rb") as f:
            files = {"attachment": (os.path.basename(file_path), f,
                                    "application/zip")}
            form_data = {"name": name, "version": version, "category": category}
            logger.info(f"POST {url} name={name} version={version} category={category}")
            response = requests.post(
                url, headers={"user": "defaultUser", "org": str(self.org)},
                files=files, data=form_data, timeout=120, verify=False
            )
        return _parse_result(response, action="导入")

    def update_plugin(self, file_path: str, plugin_instance_id: str,
                      version: str = "1.0.1") -> dict:
        """更新插件（multipart 文件字段名同为 `attachment`）"""
        url = (f"http://{self.host}:{self.PORT_8151}"
               f"/api/v1/plugin/import_update/{plugin_instance_id}")
        with open(file_path, "rb") as f:
            files = {"attachment": (os.path.basename(file_path), f,
                                    "application/zip")}
            form_data = {"version": version}
            logger.info(f"PUT {url} version={version}")
            response = requests.put(
                url, headers={"user": "defaultUser", "org": str(self.org)},
                files=files, data=form_data, timeout=120, verify=False
            )
        return _parse_result(response, action="更新")

    def activate_collector_kit(self, plugin_instance_id: str,
                                model_id: str = "",
                                not_require_job: bool = True) -> dict:
        """激活采集套件

        需带 `giraffe-contract-name` 请求头（值为 ActivateCollectorKit 契约名），
        否则返回 400；字段使用 camelCase（instanceId/relateObjectId 等）。
        not_require_job 默认 True：仅激活插件、暂不创建采集任务。
        """
        url = f"http://{self.host}:{self.PORT_12000}/api/v1/collector/kit/activate"
        data = {
            "instanceId": plugin_instance_id,
            "centralizedEnable": False,
            "notRequireJob": not_require_job,
        }
        if model_id:
            data["relateObjectId"] = model_id
        logger.info(f"POST {url} instanceId={plugin_instance_id} "
                    f"relateObjectId={model_id or '(default)'}")
        response = requests.post(
            url,
            headers={
                "user": "defaultUser",
                "org": str(self.org),
                "Content-Type": "application/json",
                "giraffe-contract-name":
                    "easyops.api.collector_service.job.ActivateCollectorKit",
            },
            json=data, timeout=60, verify=False
        )
        return _parse_result(response, action="激活")


def cmd_import(args, client: EasyOpsClient):
    if not os.path.isfile(args.file):
        logger.error(f"文件不存在: {args.file}")
        sys.exit(1)
    result = client.import_plugin(
        file_path=args.file, name=args.name or "",
        version=args.version or "1.0.0",
        category=args.category or "自定义"
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
        plugin_instance_id=args.plugin_id, model_id=args.model_id or "",
        not_require_job=not args.create_job
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
    p.add_argument("--category", default="自定义", help="插件分类（默认 自定义）")

    p = subparsers.add_parser("update", help="更新插件")
    p.add_argument("--file", required=True, help="插件 zip 包路径")
    p.add_argument("--plugin-id", required=True, help="插件实例ID")
    p.add_argument("--version", default="1.0.1", help="版本号（默认1.0.1）")

    p = subparsers.add_parser("activate", help="激活采集套件")
    p.add_argument("--plugin-id", required=True, help="插件实例ID")
    p.add_argument("--model-id", default="", help="目标模型ID（如 HOST / STORAGE@ONEMODEL）")
    p.add_argument("--create-job", action="store_true",
                   help="激活时同时创建采集任务（默认不创建，仅激活插件）")

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
