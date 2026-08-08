#!/usr/bin/env python3
"""
用户同步脚本 - 从外部系统同步用户和组织架构到 EasyOps

功能：
1. 获取外部系统用户数据（当前使用 Mock 数据）
2. 从用户所属部门构建4级组织架构
3. 同步组织到 ORGANIZATION@EASYOPS 模型（含父子关系）
4. 同步用户到 USER 模型
5. 新增用户自动注册
6. 离职用户自动禁用

测试环境: host=172.30.0.148 org=8888
"""

import requests
import json
import logging
import time
import platform
import hashlib
import hmac
import yaml
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode
from collections import OrderedDict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# EasyOps API 客户端（模板代码，勿修改 __init__ / __get_host_and_org /
#   __signature / _request 等核心方法）
# =============================================================================


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    PORT_APP_MAP = {}

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
        """
        发送 HTTP 请求，自动根据认证模式选择内网或 OpenAPI 方式

        :param method: HTTP 方法
        :param path: API 路径
        :param port: 服务端口
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
            app_name = self.PORT_APP_MAP.get(port)
            if not app_name:
                raise ValueError(
                    f"端口 {port} 未在 PORT_APP_MAP 中配置，"
                    f"请在类变量 PORT_APP_MAP 中补充映射"
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
        logger.debug(f">>> Body: {request_body[:2000] if request_body else 'None'}")
        response = requests.request(
            method=method, url=url, headers=headers,
            data=request_body, timeout=20, **kwargs
        )

        logger.debug(f"<<< Status: {response.status_code}")
        logger.debug(f"<<< Response: {response.text[:2000]}")

        response.raise_for_status()
        return response

    # =========================================================================
    # 具体 API 方法
    # =========================================================================

    def search_instance(self, object_id: str, query: Dict = None,
                        fields: List[str] = None, page: int = 1,
                        page_size: int = 200) -> Dict:
        """
        搜索实例（PostSearchV3）

        EasyOps API: easyops.api.cmdb.instance@PostSearchV3
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param query: 查询条件，如 {"name": {"$like": "%test%"}}
        :param fields: 返回字段列表，如 ["name", "instanceId"]
        :param page: 页码
        :param page_size: 每页数量
        :return: {"list": [...], "total": int}
        """
        port = 8079
        path = f"/v3/object/{object_id}/instance/_search"
        body: Dict[str, Any] = {
            "page": page,
            "page_size": page_size
        }
        if query:
            body["query"] = query
        if fields:
            body["fields"] = fields

        result = self._request("POST", path, port=port, data=body).json()
        return result.get("data", {})

    def search_all_instances(self, object_id: str, query: Dict = None,
                             fields: List[str] = None,
                             page_size: int = 200) -> List[Dict]:
        """
        搜索全部实例（自动翻页）

        :param object_id: 模型 ID
        :param query: 查询条件
        :param fields: 返回字段列表
        :param page_size: 每页数量
        :return: 实例列表
        """
        all_items = []
        page = 1
        while True:
            result = self.search_instance(object_id, query, fields, page, page_size)
            items = result.get("list", [])
            all_items.extend(items)
            total = result.get("total", 0)
            logger.debug(f"[{object_id}] 已获取 {len(all_items)}/{total}")
            if len(all_items) >= total or not items:
                break
            page += 1
        return all_items

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 200,
                        ignore_readonly: bool = False) -> Dict:
        """
        批量导入实例（ImportInstance）

        EasyOps API: easyops.api.cmdb.instance@ImportInstance
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param data_list: 数据列表
        :param keys: 唯一键列表
        :param batch_size: 每批数量
        :param ignore_readonly: 更新时是否忽略只读字段
        :return: {"insert_count": int, "update_count": int, "failed_count": int}
        """
        port = 8079
        path = f"/object/{object_id}/instance/_import"
        total_insert = 0
        total_update = 0
        total_failed = 0

        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            body: Dict[str, Any] = {
                "keys": keys,
                "datas": batch
            }
            if ignore_readonly:
                body["ignoreReadonlyFields"] = True

            result = self._request("POST", path, port=port, data=body).json()
            data = result.get("data", {})

            ins = data.get("insert_count", 0)
            upd = data.get("update_count", 0)
            fail = data.get("failed_count", 0)

            total_insert += ins
            total_update += upd
            total_failed += fail

            logger.info(f"[{object_id}] 批次 {i // batch_size + 1}: "
                        f"新增 {ins}, 更新 {upd}, 失败 {fail}")
            if fail > 0:
                logger.warning(f"失败详情: {json.dumps(data.get('data', []), ensure_ascii=False)}")

        return {
            "insert_count": total_insert,
            "update_count": total_update,
            "failed_count": total_failed
        }

    def register_user(self, name: str, password: str, email: str,
                      nickname: str = "") -> Dict:
        """
        注册用户（UserRegister）

        EasyOps API: easyops.api.user_service.user_admin@UserRegister
        服务: logic.user_service
        端口: 8111

        :param name: 用户名
        :param password: 密码
        :param email: 邮箱
        :param nickname: 昵称
        :return: {"name": str, "email": str, "org": int, "instanceId": str}
        """
        port = 8111
        path = "/api/v1/users/register"
        body: Dict[str, Any] = {
            "name": name,
            "password": password,
            "email": email,
            "org": int(self.org),
            "isAdmin": False
        }
        if nickname:
            body["nickname"] = nickname

        result = self._request("POST", path, port=port, data=body).json()
        return result.get("data", {})


# =============================================================================
# 数据与业务逻辑
# =============================================================================


# =============================================================================
# 数据获取
# =============================================================================


# ---------- 配置区 ----------

# SOAP 数据源配置
SOAP_WS_URL = "http://IP:PORT/esb_md/service/baseEmployeeService?wsdl"
SOAP_USERNAME = "rtc"
SOAP_PASSWORD = "rtc"

# 数据获取模式: "mock" 使用假数据, "soap" 调用真实接口
DATA_MODE = "mock"


def fetch_users_from_soap(start_date: str = "",
                          end_date: str = "",
                          page_size: int = 1000) -> List[Dict]:
    """
    通过 SOAP 接口获取人员基本信息。

    接口文档: 人员信息V2.0-接口文档
    WSDL: baseEmployeeService?wsdl
    方法: queryBaseEmployee
    分页: 首次返回 tableName，后续用 tableName + pageNo 翻页

    :param start_date: 开始时间（yyyy-MM-dd HH:mm:ss），为空则必填（首次调用）
    :param end_date: 结束时间，为空则默认当前时间
    :param page_size: 每页条数，最大 60000
    :return: 用户数据列表（每条为字段→值的字典）
    """
    from zeep import Client
    from zeep.plugins import HistoryPlugin
    from zeep.wsse.username import UsernameToken

    # 使用 WS-Security 用户名令牌传递 SOAP Header 认证
    client = Client(
        SOAP_WS_URL,
        plugins=[HistoryPlugin()],
        wsse=UsernameToken(SOAP_USERNAME, SOAP_PASSWORD),
    )

    # SOAP 请求参数
    # 首次调用: 传 startDate，不传 tableName
    # 后续调用: 传 tableName + pageNo，不传 startDate
    all_users = []
    table_name = ""
    page_no = 0

    while True:
        params = {}
        if table_name:
            # 后续分页
            params["tableName"] = table_name
            params["pageNo"] = str(page_no)
            params["pageSize"] = str(page_size)
        else:
            # 首次调用
            params["startDate"] = start_date
            if end_date:
                params["endDate"] = end_date

        logger.info("SOAP 请求: %s", params)

        # 调用 SOAP 方法（带 Header 认证）
        response = client.service.queryBaseEmployee(**params)
        if not response:
            logger.warning("SOAP 返回为空")
            break

        # 解析返回的 JSON 字符串
        import json as _json
        result = _json.loads(response)
        if result.get("state") != "success":
            logger.error("SOAP 接口错误: %s", result)
            break

        items = result.get("result", [])
        all_users.extend(items)

        total_count = result.get("totalCount", 0)
        table_name = result.get("tableName", "")
        logger.info("SOAP 已获取 %d/%d 条", len(all_users), total_count)

        if not table_name or len(all_users) >= total_count:
            break
        page_no += 1

    return all_users


def normalize_user_departments(user: Dict) -> Dict:
    """
    将 SOAP 接口返回的平铺部门字段转换为统一的 departments 列表。

    转换规则:
      companyCode/companyName           → departments[0]
      tier1DepartmentCode/tier1Name     → departments[1]
      tier2DepartmentCode/tier2Name     → departments[2]
      teamCode/teamName                 → departments[3]
      （有多少层就放多少层，可以为空）

    :param user: 含平铺部门字段的用户数据
    :return: 追加了 departments 列表的用户数据（原地修改并返回）
    """
    flat_fields = [
        ("companyCode", "companyName"),
        ("tier1DepartmentCode", "tier1DepartmentName"),
        ("tier2DepartmentCode", "tier2DepartmentName"),
        ("teamCode", "teamName"),
    ]
    departments = []
    for code_key, name_key in flat_fields:
        code = user.get(code_key, "")
        name = user.get(name_key, "")
        if code:
            departments.append({"code": code, "name": name})
    user["departments"] = departments
    return user


def generate_mock_users() -> List[Dict]:
    """
    生成测试用 Mock 用户数据，模拟 SOAP 接口返回的人员信息。

    每条用户含 departments 列表，从根到叶依次排列，支持任意层级。
    本示例为 4 级组织架构 (depth 0~3):

      春秋航空 (CQHK)
      ├── 信息技术部 (DEPT-IT)
      │   ├── 运维中心 (DEPT-IT-OPS)
      │   │   └── 运维一组 (DEPT-IT-OPS-G1)
      │   └── 开发中心 (DEPT-IT-DEV)
      │       └── 后端开发组 (DEPT-IT-DEV-BE)
      └── 运行控制部 (DEPT-OC)
          └── 飞行调度室 (DEPT-OC-FD)
              └── 调度一组 (DEPT-OC-FD-G1)

    :return: Mock 用户数据列表
    """
    return [
        {
            "accountNum": "100001", "accountStatus": "A", "psnCode": "P001",
            "psnName": "张三", "employeeGender": "0", "isIncumbent": "1",
            "mailBox": "zhangsan@ch.com", "mobile": "13800000001",
            "departments": [
                {"code": "CQHK", "name": "春秋航空"},
                {"code": "DEPT-IT", "name": "信息技术部"},
                {"code": "DEPT-IT-OPS", "name": "运维中心"},
                {"code": "DEPT-IT-OPS-G1", "name": "运维一组"},
            ],
        },
        {
            "accountNum": "100002", "accountStatus": "A", "psnCode": "P002",
            "psnName": "李四", "employeeGender": "1", "isIncumbent": "1",
            "mailBox": "lisi@ch.com", "mobile": "13800000002",
            "departments": [
                {"code": "CQHK", "name": "春秋航空"},
                {"code": "DEPT-IT", "name": "信息技术部"},
                {"code": "DEPT-IT-DEV", "name": "开发中心"},
                {"code": "DEPT-IT-DEV-BE", "name": "后端开发组"},
            ],
        },
        {
            "accountNum": "100003", "accountStatus": "A", "psnCode": "P003",
            "psnName": "王五", "employeeGender": "0", "isIncumbent": "1",
            "mailBox": "wangwu@ch.com", "mobile": "13800000003",
            "departments": [
                {"code": "CQHK", "name": "春秋航空"},
                {"code": "DEPT-OC", "name": "运行控制部"},
                {"code": "DEPT-OC-FD", "name": "飞行调度室"},
                {"code": "DEPT-OC-FD-G1", "name": "调度一组"},
            ],
        },
        {
            "accountNum": "100004", "accountStatus": "D", "psnCode": "P004",
            "psnName": "赵六", "employeeGender": "0", "isIncumbent": "0",
            "mailBox": "zhaoliu@ch.com", "mobile": "13800000004",
            "departments": [
                {"code": "CQHK", "name": "春秋航空"},
                {"code": "DEPT-IT", "name": "信息技术部"},
                {"code": "DEPT-IT-OPS", "name": "运维中心"},
                {"code": "DEPT-IT-OPS-G1", "name": "运维一组"},
            ],
        },
        {
            "accountNum": "100005", "accountStatus": "A", "psnCode": "P005",
            "psnName": "孙七", "employeeGender": "1", "isIncumbent": "1",
            "mailBox": "sunqi@ch.com", "mobile": "13800000005",
            "departments": [
                {"code": "CQHK", "name": "春秋航空"},
                {"code": "DEPT-IT", "name": "信息技术部"},
                {"code": "DEPT-IT-OPS", "name": "运维中心"},
                {"code": "DEPT-IT-OPS-G1", "name": "运维一组"},
            ],
        },
    ]


def build_org_tree(users: List[Dict]) -> List[Dict]:
    """
    从用户数据中提取部门信息，构建组织架构树。

    通用模式：读取每条用户的 departments 列表（从根到叶），
    按顺序去重生成节点，depth 从 0 开始，支持任意层级。

    departments 示例:
      [{"code":"CQHK","name":"春秋航空"},
       {"code":"DEPT-IT","name":"信息技术部"},
       {"code":"DEPT-IT-OPS","name":"运维中心"}]

    :param users: 用户数据列表，每条含 departments 字段
    :return: 组织节点列表（按 depth 排序，保证父节点先于子节点）
    """
    org_dict = OrderedDict()

    for user in users:
        departments = user.get("departments", [])
        for i, dept in enumerate(departments):
            code = dept.get("code", "")
            name = dept.get("name", "")
            if not code or code in org_dict:
                continue
            parent_code = departments[i - 1]["code"] if i > 0 else None
            org_dict[code] = {
                "name": name,
                "code": code,
                "depth": i,
                "sort": 0,
                "type": "公司" if i == 0 else "部门",
                "parent_code": parent_code,
            }

    # 按 depth 和 code 排序，保证父节点先于子节点
    org_list = sorted(org_dict.values(), key=lambda x: (x["depth"], x["code"]))

    # 为同一父节点下的子节点重新编号 sort
    parent_groups: Dict[str, List[Dict]] = {}
    for org in org_list:
        p = org["parent_code"] or "__root__"
        parent_groups.setdefault(p, []).append(org)

    for group in parent_groups.values():
        for idx, org in enumerate(group, 1):
            org["sort"] = idx

    return org_list


def map_user_to_easyops(user: Dict) -> Dict:
    """
    将源系统用户数据映射为 EasyOps USER 模型字段。

    字段映射:
      - name        ← accountNum (用户名，唯一标识)
      - nickname    ← psnName (职工姓名)
      - user_email  ← mailBox (邮箱)
      - user_tel    ← mobile (手机号)
      - state       ← 根据 isIncumbent 和 accountStatus 计算

    :param user: 源系统用户数据
    :return: EasyOps USER 实例数据
    """
    is_active = (user.get("isIncumbent", "1") == "1"
                 and user.get("accountStatus", "A") == "A")
    email = user.get("mailBox", "")
    if not email:
        email = f"{user['accountNum']}@placeholder.com"

    return {
        "name": user["accountNum"],
        "nickname": user.get("psnName", ""),
        "user_email": email,
        "user_tel": user.get("mobile", ""),
        # EasyOps USER.state 枚举: valid(有效) / invalid(无效)
        "state": "valid" if is_active else "invalid",
    }


# =============================================================================
# 主流程
# =============================================================================


def main():
    """编排用户同步流程"""

    client = EasyOpsClient(host="172.30.0.148", org="8888")

    # =============================================
    # Step 1: 获取用户数据
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 1: 获取用户数据 (mode=%s)", DATA_MODE)

    if DATA_MODE == "soap":
        users = fetch_users_from_soap(
            start_date="1900-01-01 00:00:00",
            page_size=1000,
        )
        # SOAP 返回平铺字段，转换为 departments 列表
        users = [normalize_user_departments(u) for u in users]
    else:
        users = generate_mock_users()

    logger.info("获取到 %d 条用户数据", len(users))

    active_users = [u for u in users if u.get("isIncumbent") == "1"]
    departed_users = [u for u in users if u.get("isIncumbent") == "0"]
    logger.info("在职: %d, 离职: %d", len(active_users), len(departed_users))

    # =============================================
    # Step 2: 构建组织架构
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 2: 构建组织架构")
    org_tree = build_org_tree(users)
    logger.info("共 %d 个组织节点", len(org_tree))

    for org in org_tree:
        indent = "  " * org["depth"]
        parent = org["parent_code"] or "(根)"
        logger.info("%s%s (code=%s, depth=%d, parent=%s)",
                     indent, org["name"], org["code"], org["depth"], parent)

    # =============================================
    # Step 3: 同步组织架构到 ORGANIZATION@EASYOPS
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 3: 同步组织架构")

    # 3.1 导入所有组织节点（不含父部门关系）
    org_data = [
        {
            "name": org["name"],
            "code": org["code"],
            "depth": org["depth"],
            "sort": org["sort"],
            "type": org["type"],
        }
        for org in org_tree
    ]
    org_result = client.import_instance("ORGANIZATION@EASYOPS", org_data,
                                        keys=["code"])
    logger.info("组织导入完成: 新增 %d, 更新 %d, 失败 %d",
                org_result["insert_count"], org_result["update_count"],
                org_result["failed_count"])

    # 3.2 查询所有组织实例，获取 instanceId
    all_orgs = client.search_all_instances(
        "ORGANIZATION@EASYOPS",
        fields=["name", "code", "depth", "sort", "instanceId"]
    )
    code_to_instance_id = {
        o["code"]: o["instanceId"]
        for o in all_orgs if "code" in o
    }
    logger.info("查询到 %d 个组织实例", len(code_to_instance_id))

    # 3.3 更新父部门关系（跳过 L0 根节点）
    parent_updates = []
    for org in org_tree:
        if org["parent_code"] and org["parent_code"] in code_to_instance_id:
            parent_id = code_to_instance_id[org["parent_code"]]
            parent_updates.append({
                "code": org["code"],
                "PARENT_DEPARTMENT": parent_id,
            })

    if parent_updates:
        rel_result = client.import_instance(
            "ORGANIZATION@EASYOPS", parent_updates, keys=["code"])
        logger.info("父部门关系更新: 新增 %d, 更新 %d, 失败 %d",
                     rel_result["insert_count"], rel_result["update_count"],
                     rel_result["failed_count"])

    # =============================================
    # Step 4: 查询现有用户
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 4: 查询现有用户")
    existing_users = client.search_all_instances(
        "USER",
        fields=["name", "nickname", "user_email", "state", "instanceId"]
    )
    existing_user_names = {u["name"] for u in existing_users if "name" in u}
    logger.info("现有用户 %d 个: %s", len(existing_users), existing_user_names)

    # =============================================
    # Step 5: 注册新用户
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 5: 注册新用户")

    default_password = "Ch@2024default"
    registered_count = 0
    for user in active_users:
        username = user["accountNum"]
        if username not in existing_user_names:
            email = user.get("mailBox", "") or f"{username}@placeholder.com"
            try:
                result = client.register_user(
                    name=username,
                    password=default_password,
                    email=email,
                    nickname=user.get("psnName", "")
                )
                logger.info("注册用户成功: %s (%s) -> %s",
                            username, user.get("psnName", ""), result)
                registered_count += 1
                # 注册后加入现有用户集合，避免重复注册
                existing_user_names.add(username)
            except requests.exceptions.HTTPError as e:
                resp = e.response
                if resp is not None and resp.status_code == 400:
                    detail = resp.json() if resp.headers.get(
                        "content-type", "").startswith("application/json") else {}
                    if "已经存在" in detail.get("error", ""):
                        logger.info("用户已注册，跳过: %s", username)
                        existing_user_names.add(username)
                        continue
                logger.error("注册用户失败: %s - %s", username, e)
    logger.info("新注册 %d 个用户", registered_count)

    # =============================================
    # Step 6: 导入用户数据到 USER 模型
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 6: 导入用户数据")

    # 6.1 导入所有用户（在职 + 离职）
    user_data = [map_user_to_easyops(u) for u in users]
    user_result = client.import_instance("USER", user_data, keys=["name"],
                                         ignore_readonly=True)
    logger.info("用户导入完成: 新增 %d, 更新 %d, 失败 %d",
                user_result["insert_count"], user_result["update_count"],
                user_result["failed_count"])

    # 6.2 查询最新用户实例，建立部门关联
    all_easyops_users = client.search_all_instances(
        "USER",
        fields=["name", "instanceId"]
    )
    username_to_instance_id = {
        u["name"]: u["instanceId"]
        for u in all_easyops_users if "name" in u
    }

    # 6.3 建立用户→部门/单位关系
    #   _ORGANIZATION_DEPARTMENT: 指向用户所属的叶子部门（departments 最后一个）
    #   _ORGANIZATION_UNIT: 指向用户所属的公司（departments 第一个）
    user_org_updates = []
    for user in users:
        username = user["accountNum"]
        if username not in username_to_instance_id:
            continue
        inst_id = username_to_instance_id[username]
        departments = user.get("departments", [])
        if not departments:
            continue

        root_code = departments[0].get("code", "")
        leaf_code = departments[-1].get("code", "")

        update = {"instanceId": inst_id}
        need_update = False

        if leaf_code and leaf_code in code_to_instance_id:
            update["_ORGANIZATION_DEPARTMENT"] = code_to_instance_id[leaf_code]
            need_update = True

        if root_code and root_code in code_to_instance_id:
            update["_ORGANIZATION_UNIT"] = code_to_instance_id[root_code]
            need_update = True

        if need_update:
            user_org_updates.append(update)

    if user_org_updates:
        org_rel_result = client.import_instance(
            "USER", user_org_updates, keys=["instanceId"], ignore_readonly=True)
        logger.info("用户组织关系更新: 新增 %d, 更新 %d, 失败 %d",
                     org_rel_result["insert_count"],
                     org_rel_result["update_count"],
                     org_rel_result["failed_count"])

    # =============================================
    # Step 7: 禁用离职用户
    # =============================================
    logger.info("=" * 60)
    logger.info("Step 7: 禁用离职用户")

    disabled_data = [
        {
            "instanceId": username_to_instance_id[user["accountNum"]],
            "state": "invalid",
        }
        for user in departed_users
        if user["accountNum"] in username_to_instance_id
    ]

    if disabled_data:
        disable_result = client.import_instance(
            "USER", disabled_data, keys=["instanceId"], ignore_readonly=True)
        logger.info("离职用户禁用: 更新 %d 个", disable_result["update_count"])

    # =============================================
    # 完成
    # =============================================
    logger.info("=" * 60)
    logger.info("同步完成!")
    logger.info("组织: %d 个节点", len(org_tree))
    logger.info("用户: %d 在职, %d 离职", len(active_users), len(departed_users))
    logger.info("新注册: %d 个", registered_count)


if __name__ == "__main__":
    main()


