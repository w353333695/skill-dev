#!/usr/bin/env python3
"""
巡检套件管理脚本 —— 增/删/改/查

    改 = 先删后导（导入失败时自动处理或手动 --force 强制覆盖）

使用方式:
    # 查询
    python manage_suite.py list --keyword "redis"
    python manage_suite.py list --all --json

    # 导入（失败自动查同名→删除→重试）
    python manage_suite.py import --file inspector_redis_v1.0.0.tar.gz --name inspector_redis

    # 强制覆盖（跳过确认，直接先删后导）
    python manage_suite.py import --file suite.tar.gz --name inspector_xxx --force

    # 删除
    python manage_suite.py delete --plugin-id abc123

认证:
    内网: 自动从 agent 配置读取 host/org
    手动: --host 172.30.0.90 --org 1888
    OpenAPI: --ak <AK> --sk <SK>
"""

import argparse
import json
import logging
import os
import sys
import time
import hashlib
import hmac
import platform
from typing import Optional
from urllib.parse import urlencode

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    PORT_APP_MAP = {
        8103: "inspection",
    }

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

    def __signature(self, method: str, uri: str, params: dict = None,
                    data: str = "{}") -> dict:
        params = dict(params) if params else {}
        request_time = str(int(time.time()))
        method = method.upper()
        content_type = "application/json" if method in ("POST", "PUT") else ""
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
        data = kwargs.pop('data', None)
        params = kwargs.get('params')
        timeout = kwargs.pop('timeout', 30)
        request_body = json.dumps(data) if data else None
        method = method.upper()
        headers = self.headers.copy()

        if self.is_openapi:
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(f"端口 {port} 未在 PORT_APP_MAP 中配置")
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

        if kwargs.get('files'):
            headers.pop("Content-Type", None)

        logger.debug(f">>> [{self.is_openapi and 'OpenAPI' or '内网'}] {method} {url}")
        logger.debug(f">>> Body: {request_body[:2000] if request_body else 'None'}")

        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, timeout=timeout, verify=False, **kwargs
        )
        logger.debug(f"<<< Status: {response.status_code}")
        logger.debug(f"<<< Response: {response.text[:2000]}")
        response.raise_for_status()
        return response

    # =========================================================================
    # 巡检套件 API
    # =========================================================================

    def list_suites(self, keyword: str = "", page: int = 1,
                    page_size: int = 20) -> dict:
        """分页查询巡检套件列表"""
        port = 8103
        params = {"page": page, "pageSize": page_size}
        if keyword:
            params["keyword"] = keyword
        result = self._request("GET", "/api/v1/inspection",
                               port=port, params=params).json()
        return result.get("data", {})

    def list_all_suites(self, keyword: str = "", page_size: int = 100) -> list:
        """获取所有巡检套件（自动翻页）"""
        all_data = []
        page = 1
        while True:
            data = self.list_suites(keyword=keyword, page=page, page_size=page_size)
            items = data.get("list", [])
            all_data.extend(items)
            total = data.get("total", 0)
            logger.info(f"已获取 {len(all_data)}/{total} 条")
            if len(all_data) >= total or not items:
                break
            page += 1
        return all_data

    def find_suite_by_name(self, name: str) -> Optional[dict]:
        """按套件 id 或显示名精确查找，返回匹配的套件信息或 None。

        服务端 keyword 走显示名模糊匹配，传入套件 id（如 inspector_svc）时无法命中，
        故先 keyword 查显示名，无果则全量拉取后按 id 精确匹配兜底。
        """
        # 1. 先按 keyword 查显示名（命中显示名或 id 与 keyword 重合的情况）
        suites = self.list_all_suites(keyword=name)
        for s in suites:
            if s.get("name") == name or s.get("id") == name:
                return s

        # 2. keyword 未命中（典型场景：传入的是套件 id），全量拉取后按 id 精确匹配
        if name and not suites:
            logger.info(f"keyword='{name}' 未命中，回退全量拉取按 id 精确匹配...")
            for s in self.list_all_suites(keyword=""):
                if s.get("id") == name or s.get("name") == name:
                    return s
        return None

    def import_suite(self, file_path: str) -> dict:
        """导入巡检套件 tar 包"""
        port = 8103
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/x-tar")}
            result = self._request("POST", "/api/v1/inspection-import",
                                   port=port, timeout=60, files=files).json()
        return result

    def delete_suite(self, plugin_id: str) -> dict:
        """卸载巡检套件"""
        port = 8103
        result = self._request("DELETE", f"/api/v1/inspection/{plugin_id}",
                               port=port).json()
        return result


# =============================================================================
# 业务逻辑
# =============================================================================


def _print_table(suites: list):
    """格式化输出套件列表"""
    if not suites:
        print("没有找到巡检套件")
        return
    print(f"\n{'ID':<30} {'名称':<30} {'状态':<12} {'方法':<8} {'objectId':<25} {'创建时间'}")
    print("-" * 140)
    for s in suites:
        print(f"{s.get('id', ''):<30} "
              f"{s.get('name', ''):<30} "
              f"{s.get('status', ''):<12} "
              f"{s.get('method', ''):<8} "
              f"{s.get('objectId', ''):<25} "
              f"{s.get('ctime', '')}")


def cmd_list(args, client: EasyOpsClient):
    """列表查询"""
    if args.all:
        suites = client.list_all_suites(
            keyword=args.keyword or "", page_size=args.page_size
        )
        total = len(suites)
    else:
        data = client.list_suites(
            keyword=args.keyword or "", page=args.page, page_size=args.page_size
        )
        suites = data.get("list", [])
        total = data.get("total", 0)
        logger.info(f"共 {total} 条，当前页 {len(suites)} 条")

    _print_table(suites)

    if args.json:
        output = {"total": total, "list": suites}
        print(f"\n{json.dumps(output, ensure_ascii=False, indent=2)}")


def _import_with_retry(client: EasyOpsClient, file_path: str,
                        suite_name: str, force: bool = False) -> bool:
    """
    导入巡检套件，失败时自动查同名套件→删除→重试

    :param client: EasyOpsClient 实例
    :param file_path: tar 包路径
    :param suite_name: 套件 id（info.yaml 中的 id 字段）
    :param force: 是否跳过确认直接覆盖
    :return: 是否导入成功
    """
    # 1. 首次尝试导入
    logger.info(f"正在导入: {file_path}")
    try:
        result = client.import_suite(file_path)
    except requests.HTTPError as e:
        logger.error(f"导入请求失败: {e}")
        result = None
    except Exception as e:
        logger.error(f"导入异常: {e}")
        result = None

    if result:
        code = result.get("code")
        if code == 0:
            logger.info("导入成功")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return True
        error_msg = result.get("error", result.get("message", ""))
        logger.warning(f"导入返回错误: code={code}, error={error_msg}")
    else:
        error_msg = "请求失败"

    # 2. 导入失败，尝试查找同名套件
    logger.info(f"导入失败，尝试查找已存在的同名套件 '{suite_name}'...")
    existing = client.find_suite_by_name(suite_name)

    if not existing:
        logger.error(f"未找到同名套件 '{suite_name}'，无法自动覆盖")
        logger.error(f"请检查套件名称是否正确，或使用 list 命令手动确认")
        return False

    existing_id = existing.get("id", "")
    existing_name = existing.get("name", "")
    logger.info(f"找到已存在套件: id={existing_id}, name={existing_name}")

    # 3. 确认是否删除
    if not force:
        print(f"\n检测到同名套件已存在:")
        print(f"  ID:   {existing_id}")
        print(f"  名称: {existing_name}")
        print(f"  状态: {existing.get('status', '')}")
        confirm = input("\n是否删除旧套件并重新导入? (y/N): ").strip().lower()
        if confirm != 'y':
            logger.info("已取消")
            return False

    # 4. 删除旧套件
    logger.info(f"正在删除旧套件: {existing_id}")
    try:
        del_result = client.delete_suite(existing_id)
        del_code = del_result.get("code")
        if del_code != 0:
            logger.error(f"删除失败: {del_result.get('error', del_result.get('message', ''))}")
            return False
        logger.info("旧套件已删除")
    except Exception as e:
        logger.error(f"删除异常: {e}")
        return False

    # 5. 重新导入
    logger.info("正在重新导入...")
    try:
        result = client.import_suite(file_path)
        code = result.get("code")
        if code == 0:
            logger.info("重新导入成功")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return True
        logger.error(f"重新导入失败: {result.get('error', result.get('message', ''))}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return False
    except Exception as e:
        logger.error(f"重新导入异常: {e}")
        return False


def cmd_import(args, client: EasyOpsClient):
    """导入命令，含自动重试逻辑"""
    if not os.path.isfile(args.file):
        logger.error(f"文件不存在: {args.file}")
        sys.exit(1)

    if not args.name:
        logger.error("请通过 --name 指定套件 id（info.yaml 中的 id 字段），用于导入失败时查找同名套件")
        sys.exit(1)

    success = _import_with_retry(
        client, args.file, args.name, force=args.force
    )
    if not success:
        sys.exit(1)


def cmd_delete(args, client: EasyOpsClient):
    """删除命令"""
    plugin_id = args.plugin_id

    if not args.force:
        confirm = input(f"确认删除巡检套件 '{plugin_id}'? (y/N): ").strip().lower()
        if confirm != 'y':
            logger.info("已取消")
            return

    logger.info(f"正在卸载: {plugin_id}")
    try:
        result = client.delete_suite(plugin_id)
        code = result.get("code")
        if code == 0:
            logger.info("卸载成功")
        else:
            logger.error(f"卸载失败: {result.get('error', result.get('message', ''))}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"卸载异常: {e}")
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="巡检套件管理 —— 增/删/改/查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s list --keyword "redis"
  %(prog)s list --all --json
  %(prog)s import --file inspector_redis_v1.0.0.tar.gz --name inspector_redis
  %(prog)s import --file suite.tar.gz --name inspector_xxx --force
  %(prog)s delete --plugin-id abc123
  %(prog)s delete --plugin-id abc123 --force
        """
    )

    # 全局参数
    parser.add_argument("--host", type=str, help="EasyOps 服务器地址")
    parser.add_argument("--org", type=str, help="组织 ID")
    parser.add_argument("--user", type=str, default="defaultUser", help="用户名")
    parser.add_argument("--ak", type=str, help="Access Key（OpenAPI 模式）")
    parser.add_argument("--sk", type=str, help="Secret Key（OpenAPI 模式）")
    parser.add_argument("--debug", action="store_true", help="开启调试日志")

    subparsers = parser.add_subparsers(dest="command", help="操作命令")
    subparsers.required = True

    # ---- list ----
    p = subparsers.add_parser("list", help="查询巡检套件列表")
    p.add_argument("--keyword", type=str, default="", help="模糊过滤关键字")
    p.add_argument("--page", type=int, default=1, help="页码（默认1）")
    p.add_argument("--page-size", type=int, default=20, help="每页大小（默认20）")
    p.add_argument("--all", action="store_true", help="获取全部数据（自动翻页）")
    p.add_argument("--json", action="store_true", help="输出完整 JSON")

    # ---- import ----
    p = subparsers.add_parser("import", help="导入巡检套件（失败自动删旧重试）")
    p.add_argument("--file", required=True, help="套件 tar.gz 包路径")
    p.add_argument("--name", required=True,
                   help="套件 id（info.yaml 中的 id 字段），用于导入失败时查找同名套件")
    p.add_argument("--force", action="store_true",
                   help="强制覆盖：跳过确认，直接删除同名套件后重新导入")

    # ---- delete ----
    p = subparsers.add_parser("delete", help="卸载巡检套件")
    p.add_argument("--plugin-id", required=True, help="套件ID")
    p.add_argument("--force", action="store_true", help="跳过确认直接删除")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        client = EasyOpsClient(
            host=args.host, org=args.org, user=args.user,
            ak=args.ak or "", sk=args.sk or "",
        )
    except FileNotFoundError:
        if not args.host:
            logger.error("未找到 agent 配置文件，请通过 --host/--org 手动指定")
            sys.exit(1)
        raise

    if args.command == "list":
        cmd_list(args, client)
    elif args.command == "import":
        cmd_import(args, client)
    elif args.command == "delete":
        cmd_delete(args, client)


if __name__ == "__main__":
    main()
