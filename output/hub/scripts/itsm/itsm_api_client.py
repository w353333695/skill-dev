#!/usr/bin/env python3
"""
EasyOps ITSM 工单自动化脚本

支持两种认证方式:
    1. 内网调用（默认）: 通过 agent 配置自动获取 host/org
    2. OpenAPI 调用: 使用 AK/SK 签名认证

使用方法:
    1. 修改配置区域的参数（可选，默认从 agent 配置读取）
    2. 直接运行: python itsm_ticket_client.py

功能列表:
    - 查询工单 (ListProcessInstanceFilterV4)
    - 作废工单 (UpdateProcessInstanceState)
    - 删除工单 (DeleteProcessInstance)
    - 发起工单 (StartProcessInstanceV2)
    - 处理工单 (CompleteProcessInstanceV2)
    - 清理工单 (查询 -> 作废 -> 删除)
    - 知识目录管理 (获取目录树/增删改查/权限管理)
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
        # 8134: "flowableservice",
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

    # ==================== ITSM 工单相关方法 ====================

    def list_tickets(self, page_size: int = 20, **kwargs) -> Dict:
        """
        查询工单列表（支持高级搜索，自动翻页）

        API: ListProcessInstanceFilterV4
        服务: logic.flowable_service
        端口: 8134

        :param page_size: 每页数据量，默认 20
        :param Q: 模糊搜索关键词（匹配工单名称、状态、处理人等）
        :param status: 工单状态 (running/done/closed)
        :param name: 工单名称
        :param orderNum: 工单编号
        :param creator: 发起人
        :param st: 开始时间
        :param et: 结束时间
        :param tag: 分类标签 (run待办/cc待阅/done已完成/mine我的工单 等)
        :param serviceCategory: 服务类型 (change/event/req/question/release/config)
        :param serviceId: 服务实例 ID
        :param filter: 高级过滤条件
        :return: {'total': int, 'list': [...]}
        :rtype: dict
        """
        port = 8134
        path = "/api/flowable_service/v4/process_instance_filter"
        all_list = []
        token = ""

        while True:
            data = {
                "pageSize": page_size,
                "token": token,
                "dataSource": "mixed",
            }
            # 附加可选参数
            for key in ['Q', 'status', 'name', 'orderNum', 'creator',
                        'st', 'et', 'tag', 'serviceCategory', 'serviceId',
                        'filter', 'handleWay', 'slaStatus', 'isShowSub',
                        'sortCfg', 'fuzzyNickname', 'score', 'source']:
                if key in kwargs and kwargs[key]:
                    data[key] = kwargs[key]

            result = self._request("POST", path, port=port, data=data).json()

            if result.get("code") != 0:
                raise Exception(f"查询工单失败: {result.get('error', result)}")

            data_body = result.get("data", {})
            items = data_body.get("list", [])
            all_list.extend(items)
            total = data_body.get("total", 0)
            token = data_body.get("nextToken", "")

            logger.info(f"已获取 {len(all_list)}/{total} 条工单")

            if not token or not items:
                break

        return {"total": total, "list": all_list}

    def cancel_tickets(self, instance_ids: List[str], memo: str = "") -> Dict:
        """
        作废工单（批量）

        API: UpdateProcessInstanceState (action=cancel)
        服务: logic.flowable_service
        端口: 8134

        :param instance_ids: 工单实例 ID 列表
        :param memo: 操作说明
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = "/api/flowable_service/v1/process_instance_state"
        data = {
            "instanceIds": ";".join(instance_ids),
            "action": "cancel",
            "memo": memo or "批量作废"
        }
        result = self._request("PUT", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"作废工单失败: {result.get('error', result)}")
        logger.info(f"作废工单成功: {';'.join(instance_ids)}")
        return result

    def delete_tickets(self, instance_ids: List[str]) -> Dict:
        """
        删除工单（批量）

        API: DeleteProcessInstance
        服务: logic.flowable_service
        端口: 8134

        :param instance_ids: 工单实例 ID 列表
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/process_instance/{';'.join(instance_ids)}"
        result = self._request("DELETE", path, port=port).json()
        if result.get("code") != 0:
            raise Exception(f"删除工单失败: {result.get('error', result)}")
        logger.info(f"删除工单成功: {';'.join(instance_ids)}")
        return result

    def start_ticket(self, service_id: str, name: str,
                     visible_range: str = "operator",
                     variables: Optional[List[Dict]] = None,
                     form_data: str = "[]", **kwargs) -> Dict:
        """
        发起工单

        API: StartProcessInstanceV2
        服务: logic.flowable_service
        端口: 8134

        :param service_id: 服务 ID（必填）
        :param name: 工单名称（必填）
        :param visible_range: 可见范围 (operator/mine)，默认 operator
        :param variables: 条件变量列表，如 [{"name": "pass", "value": "0"}]
        :param form_data: 表单数据 JSON 字符串，默认 "[]"
        :param assigneeUsers: 下一步指派人列表
        :param starter: 指定工单发起人
        :param handleWay: 处理方式 (common/priority/emergency)
        :param ITSC_influenceScope: 影响范围 (low/middle/high)
        :param ITSC_urgency: 紧急程度 (low/middle/high)
        :return: API 响应，包含 instanceId
        :rtype: dict
        """
        port = 8134
        path = "/api/flowable_service/v2/process_instance"
        data = {
            "serviceId": service_id,
            "name": name,
            "visibleRange": visible_range,
            "formData": form_data,
            "handleWay": kwargs.get("handleWay", "common"),
            "source": kwargs.get("source", "ITSC"),
            "isSupervision": kwargs.get("isSupervision", False),
        }
        if variables:
            data["variables"] = variables
        for key in ['relevanceInstanceId', 'assigneeUsers', 'assigneeGroups',
                     'starter', 'isManualConfirm', 'departmentId',
                     'ITSC_influenceScope', 'ITSC_urgency',
                     'supervisorUserList', 'subsequentAssignee']:
            if key in kwargs and kwargs[key]:
                data[key] = kwargs[key]

        result = self._request("POST", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"发起工单失败: {result.get('error', result)}")
        instance_id = result.get("data", {}).get("instanceId", "")
        logger.info(f"发起工单成功: instanceId={instance_id}")
        return result

    def complete_ticket_task(self, instance_id: str, task_instance_id: str,
                             variables: List[Dict],
                             memo: str = "", form_data: str = "[]",
                             **kwargs) -> Dict:
        """
        处理工单任务（通过/驳回）

        API: CompleteProcessInstanceV2
        服务: logic.flowable_service
        端口: 8134

        :param instance_id: 工单实例 ID（必填）
        :param task_instance_id: 任务实例 ID（必填）
        :param variables: 条件变量（必填），pass=1 通过，pass=0 驳回
        :param memo: 操作说明，如 "同意"
        :param form_data: 表单数据 JSON 字符串
        :param assigneeUsers: 下一步审批人列表
        :param ITSC_influenceScope: 影响范围
        :param ITSC_urgency: 紧急程度
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v2/process_instance/{instance_id}/task/{task_instance_id}"
        data = {
            "formData": form_data,
            "variables": variables,
            "memo": memo,
        }
        for key in ['assigneeList', 'assigneeUsers', 'assigneeGroups',
                     'ITSC_influenceScope', 'ITSC_urgency', 'departmentId',
                     'canSkip', 'ticketName', 'completer', 'extArgs']:
            if key in kwargs and kwargs[key]:
                data[key] = kwargs[key]

        result = self._request("POST", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"处理工单失败: {result.get('error', result)}")
        logger.info(f"处理工单成功: instance={instance_id}, task={task_instance_id}")
        return result

    def cleanup_tickets(self, status: str = "",
                        cancel_memo: str = "批量清理作废",
                        batch_size: int = 50,
                        dry_run: bool = False, **kwargs) -> Dict:
        """
        批量清理工单（查询 -> 作废 -> 删除）

        流程：
        1. 根据条件查询匹配的工单
        2. 将运行中的工单作废
        3. 删除所有匹配的工单

        :param status: 工单状态过滤，默认 running
        :param cancel_memo: 作废时的操作说明
        :param batch_size: 每批处理的工单数量，默认 50
        :param dry_run: 是否只预览不执行，默认 False
        :param Q: 模糊搜索关键词
        :param creator: 发起人
        :param name: 工单名称
        :param serviceId: 服务 ID
        :param st: 开始时间
        :param et: 结束时间
        :return: 清理结果统计
        :rtype: dict
        """
        # 1. 查询工单
        logger.info("=== 开始清理工单 ===")
        query_params = dict(status=status, **kwargs)
        query_params = {k: v for k, v in query_params.items() if v}

        logger.info(f"查询条件: {query_params}")
        result = self.list_tickets(**query_params)
        tickets = result.get("list", [])
        total = result.get("total", 0)
        logger.info(f"共查询到 {total} 条工单")

        if not tickets:
            logger.info("无需清理的工单")
            return {"total": 0, "cancelled": 0, "deleted": 0}

        instance_ids = [t["instanceId"] for t in tickets]

        # 预览模式
        if dry_run:
            logger.info(f"[DRY-RUN] 将处理以下 {len(instance_ids)} 条工单:")
            for t in tickets:
                logger.info(f"  [{t.get('status')}] {t.get('instanceId')} - "
                            f"{t.get('name', '')} ({t.get('creator', '')})")
            return {"total": len(instance_ids), "cancelled": 0, "deleted": 0, "dry_run": True}

        # 2. 作废运行中的工单
        running_ids = [t["instanceId"] for t in tickets if t.get("status") == "running"]
        cancelled = 0
        if running_ids:
            logger.info(f"作废 {len(running_ids)} 条运行中工单...")
            for i in range(0, len(running_ids), batch_size):
                batch = running_ids[i:i + batch_size]
                try:
                    self.cancel_tickets(batch, memo=cancel_memo)
                    cancelled += len(batch)
                except Exception as e:
                    logger.error(f"作废工单失败 (batch {i // batch_size + 1}): {e}")
            if cancelled > 0:
                logger.info("等待作废状态生效...")
                time.sleep(2)

        # 3. 删除所有工单
        deleted = 0
        logger.info(f"删除 {len(instance_ids)} 条工单...")
        for i in range(0, len(instance_ids), batch_size):
            batch = instance_ids[i:i + batch_size]
            try:
                self.delete_tickets(batch)
                deleted += len(batch)
            except Exception as e:
                logger.error(f"删除工单失败 (batch {i // batch_size + 1}): {e}")

        summary = {"total": len(instance_ids), "cancelled": cancelled, "deleted": deleted}
        logger.info(f"=== 清理完成: 查询 {total}, 作废 {cancelled}, 删除 {deleted} ===")
        return summary

    # ==================== 知识目录管理方法 ====================

    def get_catalog_tree(self) -> List[Dict]:
        """
        获取知识目录树（完整树形结构）

        API: GetCatalogTree
        服务: logic.flowable_service
        端口: 8134

        :return: 目录树列表，每个节点包含 id/name/dirPath/description/parentId/subCatalog
        :rtype: list[dict]
        """
        port = 8134
        path = "/api/flowable_service/v1/knowledge_base/catalog_tree"
        result = self._request("GET", path, port=port).json()
        if result.get("code") != 0:
            raise Exception(f"获取知识目录树失败: {result.get('error', result)}")
        tree = result.get("data", {}).get("catalogTree", [])
        logger.info(f"获取知识目录树成功，顶级目录 {len(tree)} 个")
        return tree

    def get_catalog(self, catalog_id: str) -> Dict:
        """
        获取单个知识目录详情

        API: GetCatalog
        服务: logic.flowable_service
        端口: 8134

        :param catalog_id: 目录 ID
        :return: 目录详情，包含 id/name/dirPath/description/parentId
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/knowledge_base/catalog/{catalog_id}"
        result = self._request("GET", path, port=port).json()
        if result.get("code") != 0:
            raise Exception(f"获取知识目录详情失败: {result.get('error', result)}")
        return result.get("data", {})

    def add_catalog(self, name: str, parent_id: str = "",
                    description: str = "") -> str:
        """
        添加知识目录

        API: AddCatalog
        服务: logic.flowable_service
        端口: 8134

        :param name: 目录名称（必填）
        :param parent_id: 父目录 ID，为空则创建顶级目录
        :param description: 目录描述
        :return: 新建目录的 ID
        :rtype: str
        """
        port = 8134
        path = "/api/flowable_service/v1/knowledge_base/catalog"
        data = {"name": name}
        if parent_id:
            data["parentId"] = parent_id
        if description:
            data["description"] = description
        result = self._request("POST", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"添加知识目录失败: {result.get('error', result)}")
        catalog_id = result.get("data", {}).get("id", "")
        logger.info(f"添加知识目录成功: id={catalog_id}, name={name}")
        return catalog_id

    def update_catalog(self, catalog_id: str, name: str,
                       parent_id: str = "", description: str = "") -> Dict:
        """
        更新知识目录

        API: UpdateCatalog
        服务: logic.flowable_service
        端口: 8134

        :param catalog_id: 目录 ID（必填）
        :param name: 目录名称（必填）
        :param parent_id: 父目录 ID（可选，移动目录时设置）
        :param description: 目录描述（可选）
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/knowledge_base/catalog/{catalog_id}"
        data = {"name": name}
        if parent_id:
            data["parentId"] = parent_id
        if description:
            data["description"] = description
        result = self._request("PUT", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"更新知识目录失败: {result.get('error', result)}")
        logger.info(f"更新知识目录成功: id={catalog_id}, name={name}")
        return result

    def delete_catalog(self, catalog_id: str) -> Dict:
        """
        删除知识目录

        API: DeleteCatalog
        服务: logic.flowable_service
        端口: 8134

        :param catalog_id: 目录 ID
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/knowledge_base/catalog/{catalog_id}"
        result = self._request("DELETE", path, port=port).json()
        if result.get("code") != 0:
            raise Exception(f"删除知识目录失败: {result.get('error', result)}")
        logger.info(f"删除知识目录成功: id={catalog_id}")
        return result

    def get_catalog_perm(self, catalog_id: str) -> Dict:
        """
        获取知识目录的访问权限（用户和用户组）

        API: GetCatalogPerm
        服务: logic.flowable_service
        端口: 8134

        :param catalog_id: 目录 ID
        :return: 权限信息，包含 visitorUser 和 visitorUserGroup 列表
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/knowledge_base/catalog/{catalog_id}/perm"
        result = self._request("GET", path, port=port).json()
        if result.get("code") != 0:
            raise Exception(f"获取知识目录权限失败: {result.get('error', result)}")
        return result.get("data", {})

    def set_catalog_perm(self, catalog_id: str,
                         visitor: List[str]) -> Dict:
        """
        设置知识目录的访问权限

        API: SetCatalogPerm
        服务: logic.flowable_service
        端口: 8134

        :param catalog_id: 目录 ID
        :param visitor: 具有访问权限的用户名和用户组 ID 列表
        :return: API 响应
        :rtype: dict
        """
        port = 8134
        path = f"/api/flowable_service/v1/knowledge_base/catalog/{catalog_id}/perm"
        data = {
            "id": catalog_id,
            "visitor": visitor,
        }
        result = self._request("POST", path, port=port, data=data).json()
        if result.get("code") != 0:
            raise Exception(f"设置知识目录权限失败: {result.get('error', result)}")
        logger.info(f"设置知识目录权限成功: id={catalog_id}, visitors={visitor}")
        return result


if __name__ == "__main__":

    # ============ 使用示例 ============
    logger.setLevel(logging.INFO)
    client = EasyOpsClient(
        host='11.66.19.194', org='1026123',  # 使用内部api，不指定host、org则自动从agent配置获取
        # user=USER, # 手动指定用户，默认为 defaultUser
        # ak=AK, sk=SK # 使用openapi方式
    )

    # --- 查询工单 ---
    # result = client.list_tickets(Q="测试", status="running")
    # pp(result)

    # --- 发起工单 ---
    # result = client.start_ticket(
    #     service_id="YOUR_SERVICE_ID",
    #     name="测试工单",
    #     variables=[{"name": "pass", "value": "0"}],
    # )
    # pp(result)

    # --- 处理工单（通过） ---
    # result = client.complete_ticket_task(
    #     instance_id="YOUR_INSTANCE_ID",
    #     task_instance_id="YOUR_TASK_ID",
    #     variables=[{"name": "pass", "value": "1"}],
    #     memo="同意",
    # )
    # pp(result)

    # --- 作废工单 ---
    # result = client.cancel_tickets(instance_ids=["id1", "id2"], memo="批量作废")
    # pp(result)

    # --- 删除工单 ---
    # result = client.delete_tickets(instance_ids=["id1", "id2"])
    # pp(result)

    # --- 清理工单（先预览再执行） ---
    # summary = client.cleanup_tickets(dry_run=True)
    # pp(summary)
    # summary = client.cleanup_tickets()
    # pp(summary)

    # --- 获取知识目录树 ---
    # tree = client.get_catalog_tree()
    # pp(tree)

    # --- 添加知识目录 ---
    catalog_id = client.add_catalog(name="日常运维", description="日常运维常见问题、故障处理方法")
    # sub_id = client.add_catalog(name="子目录", parent_id=catalog_id)

    # --- 获取知识目录详情 ---
    # detail = client.get_catalog(catalog_id="CATALOG_ID")
    # pp(detail)

    # --- 更新知识目录 ---
    # result = client.update_catalog(catalog_id="CATALOG_ID", name="新名称", description="新描述")

    # --- 删除知识目录 ---
    # result = client.delete_catalog(catalog_id="CATALOG_ID")

    # --- 获取目录访问权限 ---
    # perm = client.get_catalog_perm(catalog_id="CATALOG_ID")
    # pp(perm)

    # --- 设置目录访问权限 ---
    # result = client.set_catalog_perm(catalog_id="CATALOG_ID", visitor=["username1", "group_id1"])
