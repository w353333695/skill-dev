#!/usr/bin/env python3
"""
EasyOps 用户批量导入与注册脚本

功能：
    1. 读取用户登记表 Excel（用户_template.xlsx）
    2. 通过 Excel 导入用户实例到 CMDB（ImportInstanceWithExcel）
    3. 批量注册 EasyOps 用户账号（UserRegister）

使用方法：
    1. 修改配置区域的参数
    2. 直接运行: python import_and_register_users.py
"""

import requests
import json
import logging
import os
import time
import platform
import hashlib
import hmac
import yaml
import openpyxl
from functools import wraps
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    PORT_APP_MAP = {
        8079: "cmdbservice",
        8111: "user_service",
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
        """生成 OpenAPI HMAC-SHA1 签名"""
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
            "accesskey": self.ak, "signature": signature, "expires": request_time
        })
        return params

    def _request(self, method: str, path: str, port: int,
                 **kwargs) -> requests.Response:
        """发送 HTTP 请求"""
        data = kwargs.pop('data', None)
        json_data = kwargs.pop('json', None)
        params = kwargs.get('params')
        files = kwargs.pop('files', None)
        form_data = kwargs.pop('form_data', None)
        timeout = kwargs.pop('timeout', 20)

        if json_data:
            request_body = json.dumps(json_data)
        elif data:
            request_body = json.dumps(data)
        else:
            request_body = None

        method = method.upper()
        headers = self.headers.copy()

        if self.is_openapi:
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(f"端口 {port} 未在 PORT_APP_MAP 中配置")
            uri = f"/{app_name}/{path.lstrip('/')}"
            url = f"http://{self.host}{uri}"
            sign_params = self.__signature(method, uri, params=params, data=request_body or "{}")
            url = url + "?" + urlencode(sign_params)
            kwargs.pop('params', None)
            if method in ("GET", "DELETE"):
                headers.pop("Content-Type", None)
            headers.pop('org', None)
        else:
            url = f"http://{self.host}:{port}/{path.lstrip('/')}"

        # 文件上传时不设置 Content-Type，让 requests 自动处理
        if files:
            headers.pop("Content-Type", None)
            response = requests.request(
                method=method, url=url, headers=headers,
                files=files, data=form_data, timeout=timeout, **kwargs
            )
        else:
            response = requests.request(
                method=method, url=url, headers=headers,
                data=request_body, timeout=timeout, **kwargs
            )

        if response.status_code >= 400:
            logger.error(f"请求失败 {response.status_code}: {response.text[:500]}")
        response.raise_for_status()
        return response

    def import_instance_excel(self, object_id: str, file_path: str,
                              keys: List[str] = None) -> dict:
        """
        使用 Excel 文件导入实例到 CMDB

        API: ImportInstanceWithExcel
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param file_path: Excel 文件路径
        :param keys: 唯一键列表
        :return: 导入结果
        """
        port = 8079
        path = f'import/object/{object_id}/instance/excel'
        files = {
            'attachment': (
                os.path.basename(file_path),
                open(file_path, 'rb'),
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        }
        form_data = {}
        if keys:
            for i, key in enumerate(keys):
                form_data[f'keys[{i}]'] = key
        try:
            response = self._request(
                'POST', path, port=port, timeout=120,
                files=files, form_data=form_data if form_data else None
            )
            result = response.json()
            data = result.get('data', result)
            logger.info(
                f"Excel导入完成 [{object_id}]: "
                f"插入 {data.get('insert_count', 0)}, "
                f"更新 {data.get('update_count', 0)}, "
                f"失败 {data.get('failed_count', 0)}"
            )
            return data
        finally:
            files['attachment'][1].close()

    def register_user(self, name: str, password: str, email: str,
                      nickname: str = '', is_admin: bool = False) -> dict:
        """
        注册 EasyOps 用户

        API: UserRegister
        服务: logic.user_service
        端口: 8111

        :param name: 用户名
        :param password: 密码
        :param email: 邮箱
        :param nickname: 昵称
        :param is_admin: 是否管理员
        :return: 注册结果
        """
        port = 8111
        payload = {
            "name": name,
            "password": password,
            "email": email,
            "org": int(self.org),
        }
        if nickname:
            payload["nickname"] = nickname
        if is_admin:
            payload["isAdmin"] = True
        resp = self._request("POST", "/api/v1/users/register", port=port,
                             json=payload)
        return resp.json()


def import_and_register_users(client: EasyOpsClient, file_path: str,
                              email_tpl: str, password_tpl: str,
                              keys: List[str] = None):
    """
    从 Excel 导入用户到 CMDB 并批量注册 EasyOps 账号

    :param client: EasyOpsClient 实例
    :param file_path: 用户登记表 Excel 路径
    :param email_tpl: 邮箱模板，{name} 替换为用户名
    :param password_tpl: 密码模板，{name} 替换为用户名
    :param keys: CMDB 导入唯一键，默认 ['name']
    """
    if not keys:
        keys = ['name']

    # 步骤1：读取 Excel 获取用户列表
    wb = openpyxl.load_workbook(file_path)
    ws = wb.active
    # 第1行表头，第2行子表头，第3行说明，数据从第4行开始
    users = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        name = row[0]
        if not name or not str(name).strip():
            continue
        nickname = row[2] if len(row) > 2 and row[2] else ''
        users.append({
            'name': str(name).strip(),
            'nickname': str(nickname).strip() if nickname else ''
        })
    wb.close()
    logger.info(f"从 Excel 读取到 {len(users)} 个用户")

    if not users:
        logger.warning("Excel 中没有有效用户数据")
        return

    # 步骤2：导入用户实例到 CMDB
    logger.info("开始导入用户到 CMDB...")
    try:
        client.import_instance_excel(
            object_id='USER', file_path=file_path, keys=['name']
        )
    except Exception as e:
        logger.error(f"CMDB 导入失败（不影响后续注册）: {e}");exit()

    # 步骤3：批量注册用户账号
    logger.info("开始注册用户账号...")
    success_count = 0
    fail_count = 0
    for user in users:
        uname = user['name']
        email = email_tpl.format(name=uname)
        password = password_tpl.format(name=uname)
        try:
            result = client.register_user(
                name=uname, password=password, email=email,
                nickname=user.get('nickname', '')
            )
            if result.get('code', -1) == 0:
                success_count += 1
                logger.info(f"注册成功: {uname}")
            else:
                fail_count += 1
                logger.warning(
                    f"注册失败: {uname} - "
                    f"{result.get('error', result.get('message', ''))}"
                )
        except Exception as e:
            fail_count += 1
            logger.error(f"注册异常: {uname} - {e}")

    logger.info(f"注册完成: 成功 {success_count}, 失败 {fail_count}")


if __name__ == "__main__":

    # ============ 配置区域 ============
    HOST = '11.66.19.194'          # EasyOps 地址，None 则从 agent 配置读取
    ORG = '1026123'           # 组织 ID，None 则从 agent 配置读取
    USER = "defaultUser"

    # OpenAPI 认证（留空则使用内网调用）
    AK = ""
    SK = ""

    # 用户登记表路径
    EXCEL_PATH = "./output/用户_template.xlsx"          

    # 邮箱和密码拼接模板（{name} 会被替换为用户名）
    EMAIL_TPL = "{name}@rhhn.com"
    PASSWORD_TPL = "{name}@easyops2026"

    # CMDB 导入唯一键
    IMPORT_KEYS = ["name"]
    # ====================================

    client = EasyOpsClient(HOST, ORG, USER, ak=AK, sk=SK)
    import_and_register_users(
        client, EXCEL_PATH, EMAIL_TPL, PASSWORD_TPL, IMPORT_KEYS
    )
