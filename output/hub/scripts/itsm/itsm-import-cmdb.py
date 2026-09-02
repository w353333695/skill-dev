#!/usr/local/easyops/python3/bin/python3

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
from pprint import pp
import re
from datetime import datetime
from pprint import pprint


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def convert_datetime(value: Any, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将 ISO 格式时间字符串转为指定格式。"""
    if not isinstance(value, str):
        return value
    return datetime.fromisoformat(value).strftime(fmt)


def convert_size(value: Any, unit: str = "KB") -> float:
    """将带单位的大小字符串转为指定单位的数值。

    Args:
        value: 如 "1238123123KB"、"500MB"、"2TB"，或纯数字
        unit: 目标单位，支持 B/KB/MB/GB/TB，默认 KB

    Returns:
        转换后的浮点数
    """
    units = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}
    target = units.get(unit.upper())
    if target is None:
        raise ValueError(f"不支持的单位: {unit}，可选: {list(units.keys())}")

    s = str(value).strip().upper()
    match = re.match(r"^([\d.]+)\s*([A-Z]*)", s)
    if not match:
        raise ValueError(f"无法解析大小值: {value}")

    num = float(match.group(1))
    src_unit = match.group(2) or "B"
    source = units.get(src_unit)
    if source is None:
        raise ValueError(f"无法识别源单位: {src_unit}")

    return num * (1024 ** (source - target))


def extract_form_value(
    order_data: dict | str,
    path: str,
    first_only: bool = True,
    transform: dict[str, dict] | None = None,
) -> Any:
    """从 orderInfo 数据中按路径提取表单值。

    Args:
        order_data: orderInfo 的完整 JSON 对象或 JSON 字符串
        path: 点分隔路径，格式为:
              - userTaskId.sectionKey.fieldKey — 取指定字段
              - userTaskId.sectionKey — 取该 section 下所有 values
        first_only: 为 True 时只返回第一个匹配值（直接返回值本身），
                    为 False 时返回所有匹配值的列表
        transform: section 级别的数据转换配置，格式为:
                   {
                       "原始key": {
                           "key": "新key名",                  # 可选，重命名 key
                           "converter": convert_datetime,     # 可选，转换函数，支持lambda表达式，如：lambda v: v.upper()
                           "params": {"fmt": "%Y-%m-%d"}      # 可选，传给 converter 的参数
                       }
                   }

    Returns:
        first_only=True:  第一个匹配的值，找不到返回 None
        first_only=False: 所有匹配值的列表

    Raises:
        ValueError: 路径格式错误或找不到对应数据
    """
    if isinstance(order_data, str):
        order_data = json.loads(order_data)

    step_list = order_data.get("stepList", [])
    if not step_list:
        raise ValueError("stepList 为空")

    # 解析路径
    parts = path.split(".")
    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(
            f"路径格式错误: '{path}'，"
            "应为 userTaskId.sectionKey 或 userTaskId.sectionKey.fieldKey"
        )
    user_task_id = parts[0]
    section_key = parts[1]
    field_key = parts[2] if len(parts) == 3 else None

    # 查找 step：同一 userTaskId 可能有多条，取 ctime 最新的
    candidates = [s for s in step_list if s.get("userTaskId") == user_task_id]
    if not candidates:
        raise ValueError(f"未找到 userTaskId: {user_task_id}")
    step = max(candidates, key=lambda s: s.get("ctime", ""))
    
    # 解析 formData
    raw = step.get("formData", "")
    if not raw:
        raise ValueError(f"step '{user_task_id}' 的 formData 为空")
    form_data = json.loads(raw) if isinstance(raw, str) else raw
    
    # 查找 section
    section = None
    for sec in form_data:
        if sec.get("key") == section_key:
            section = sec
            break
    if section is None:
        raise ValueError(f"未找到 sectionKey: {section_key}")
    
    values = section.get("values", [])
    if not values:
        return None if first_only else []

    def apply_transform(row: dict) -> dict:
        """对单行数据应用转换配置：只保留 transform 中配置的 key，取不到值赋 None。"""
        if not transform:
            return row
        new_row = {}
        for orig_key, conf in transform.items():
            new_key = conf.get("key", orig_key)
            v = row.get(orig_key)
            converter = conf.get("converter")
            if v is not None and callable(converter):
                params = conf.get("params") or {}
                v = converter(v, **params)
            new_row[new_key] = v
        return new_row

    # 提取字段值
    if field_key:
        results = [row[field_key] for row in values if field_key in row]
    else:
        results = [apply_transform(row) for row in values]

    if first_only:
        return results[0] if results else None
    return results


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射（仅 OpenAPI 模式需要）
    PORT_APP_MAP = {
        8079: "cmdbservice",
        8069: "notify",
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
    
    def search_instance_v3_admin(self, object_id: Optional[str] = None,
                                  fields: Optional[List[str]] = ["*"],
                                  query: Optional[Dict] = None,
                                  page: int = 1, page_size: int = 30,
                                  sort: Optional[List[Dict]] = None,
                                  only_my_instance: bool = False,
                                  query_context: Optional[Dict] = None,
                                  permission: Optional[List[str]] = None,
                                  relation_limit: Optional[int] = None,
                                  limitations: Optional[List[Dict]] = None,
                                  ignore_missing_field_error: Optional[bool] = None,
                                  metrics_filter: Optional[Dict] = None,
                                  filter_relation: Optional[bool] = None) -> Dict:
        """
        搜索实例V3（含管理员权限）

        EasyOps API: PostSearchV3WithAdmin
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型对象ID
        :param fields: 返回字段列表，e.g. ["name", "instanceId"]
        :param query: 查询条件，e.g. {"name": {"$like": "%q%"}}
        :param page: 页码，默认1
        :param page_size: 页大小，默认30
        :param sort: 排序规则，e.g. [{"key": "instanceId", "order": 1}]
        :param only_my_instance: 仅搜索与我相关的实例
        :param query_context: 查询条件模板上下文
        :param permission: 权限过滤
        :param relation_limit: 关系数量限制
        :param limitations: 单独指定关系的limit与sort
        :param ignore_missing_field_error: 忽略不存在的字段报错
        :param metrics_filter: 指标数据查询
        :param filter_relation: 是否仅返回匹配的对端关系
        :return: {"list": [...], "total": int, "page": int, "page_size": int}
        :rtype: dict
        """
        port = 8079
        body = {
            "page": page,
            "page_size": page_size,
            "only_my_instance": only_my_instance,
        }
        if object_id:
            body["objectId"] = object_id
        if fields:
            body["fields"] = fields
        if query:
            body["query"] = query
        if query_context:
            body["query_context"] = query_context
        if sort:
            body["sort"] = sort
        if permission:
            body["permission"] = permission
        if relation_limit is not None:
            body["relation_limit"] = relation_limit
        if limitations:
            body["limitations"] = limitations
        if ignore_missing_field_error is not None:
            body["ignore_missing_field_error"] = ignore_missing_field_error
        if metrics_filter:
            body["metrics_filter"] = metrics_filter
        if filter_relation is not None:
            body["filter_relation"] = filter_relation

        uri = f"/v3/object/{object_id}/instance/_search" if object_id else "/v3/object//instance/_search"
        resp = self._request("POST", uri, port=port, data=body)
        insts = resp.json().get("data", {}).get("list")
        return insts

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 1000,
                        import_metadata: bool = False,
                        ignore_readonly_fields: bool = False,
                        disable_nested_create_instance: bool = False) -> Dict:
        """
        批量编辑/新增实例

        EasyOps API: ImportInstance
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型对象ID
        :param data_list: 导入数据列表，每项必须包含 keys 中的字段
        :param keys: 联合唯一键列表，用于判断插入/更新
        :param batch_size: 每批处理数量，默认1000
        :param import_metadata: 是否导入 metadata 字段(ctime, creator等)
        :param ignore_readonly_fields: 更新时是否忽略只读字段
        :param disable_nested_create_instance: 是否禁止通过关系嵌套创建实例
        :return: {"insert_count": int, "update_count": int, "failed_count": int, "data": [...]}
        :rtype: dict
        """
        port = 8079
        total_insert = 0
        total_update = 0
        total_failed = 0
        all_failed = []

        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            body = {
                "keys": keys,
                "datas": batch,
            }
            if import_metadata:
                body["importMetadata"] = import_metadata
            if ignore_readonly_fields:
                body["ignoreReadonlyFields"] = ignore_readonly_fields
            if disable_nested_create_instance:
                body["disableNestedCreateInstance"] = disable_nested_create_instance

            result = self._request("POST", f"/object/{object_id}/instance/_import",
                                   port=port, data=body).json()
            result_data = result.get("data", {})

            insert = result_data.get("insert_count", 0)
            update = result_data.get("update_count", 0)
            failed = result_data.get("failed_count", 0)
            total_insert += insert
            total_update += update
            total_failed += failed
            all_failed.extend(result_data.get("data", []))
        logger.info(f"导入{object_id}模型实例完成: "
                    f"新增 {total_insert}, "
                    f"更新 {total_update}, "
                    f"失败 {total_failed}")
        if total_failed > 0:
            logger.warning(f"导入{object_id}模型实例失败: {all_failed},失败数据：{all_failed}")
            exit(1)

        return {
            "insert_count": total_insert,
            "update_count": total_update,
            "failed_count": total_failed,
            "data": all_failed
        }

    def search_instance(self, object_id: str, fields: List[str] = ["*"], query: Dict = {}) -> List[Dict]:
        """
        搜索实例

        EasyOps API: SearchInstance
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型对象ID
        :param fields: 返回字段列表，e.g. ["name", "instanceId"]
        :param query: 查询条件，e.g. {"name": {"$like": "%q%"}}
        :return: [{"name": "xxx", "instanceId": "xxx"}, ...]
        """
        all_insts = []
        for page in range(1, 10000):
            body = {
                "page": page,
                "page_size": 1000,
                "fields": fields,
                "query": query,
            }
            resp = self._request("POST", f"/v3/object/{object_id}/instance/_search",
                                 port=8079, data=body)
            insts = resp.json().get("data", {}).get("list")
            if not insts:
                break
            all_insts.extend(insts)
        logger.info(f"搜索到 {len(all_insts)} 条{object_id}实例数据")
        return all_insts


if __name__ == "__main__":
    orderInfo = r'''{"processInstance":{"instanceId":"64fee79551209","orderNum":"REQ26042100002","flowableInstanceId":"7611","name":"基础环境资源申请表","category":"服务请求","creator":"easyops","creatorShowName":"","ctime":"2026-04-21 09:38:36","etime":"","operationTime":"2026-04-21 09:38:51","status":"running","stepIdList":[],"isSuspended":false,"isCancelled":false,"focusUserList":[],"isSubInstance":false,"isOldProcessInstance":false,"oldProcessInstanceStruct":{"ctime":"","creator":"","oldVersionRelevanceUserTaskInfo":"","pid":"","pname":"","category":"","id":0},"currentAssigneeList":[],"isTimeout":false,"serviceId":"64fdf1bb82839","isDelete":false,"versionRelevanceUserTaskInfo":[{"userTaskId":"Activity_00v2a9q","formVersionId":"64fee41fb41c5","fbFormId":"","fbFormInstanceId":"","formDisplayMode":"side","isDesensitization":false}],"versionRelevanceSubTaskInfo":[],"visibleRange":"operator","isComment":false,"supervisorList":[],"handleWay":"common","influenceScope":"","urgency":"","rTime":"","slaStatus":"","lastDiscussTime":"","source":"ITSC","timeoutTime":"","suspendCost":0,"focusFields":[],"subsequentConf":[],"suspendInfo":null,"suspendTimeLimitConf":[],"suspendTimeLimit":0,"tag":"","expectedDoneTime":"","creatorOrganization":"","creatorOrganizationId":"","scheduledTicketId":""},"processVersion":{"instanceId":"64fee725ecea9","versionName":"1.0.3","bpmnXML":"\u003c?xml version=\"1.0\" encoding=\"UTF-8\"?\u003e\n\u003cbpmn2:definitions xmlns:bpmn2=\"http://www.omg.org/spec/BPMN/20100524/MODEL\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:bpmndi=\"http://www.omg.org/spec/BPMN/20100524/DI\" xmlns:dc=\"http://www.omg.org/spec/DD/20100524/DC\" xmlns:di=\"http://www.omg.org/spec/DD/20100524/DI\" xmlns:flowable=\"http://flowable.org/bpmn\" xmlns:camunda=\"http://camunda.org/schema/1.0/bpmn\" id=\"sample-diagram\" targetNamespace=\"http://bpmn.io/schema/bpmn\" xsi:schemaLocation=\"http://www.omg.org/spec/BPMN/20100524/MODEL BPMN20.xsd\"\u003e\n  \u003cbpmn2:process id=\"ITSC-PROCESS-ID\" name=\"ITSC-PROCESS-NAME\"\u003e\n    \u003cbpmn2:documentation\u003e描述\u003c/bpmn2:documentation\u003e\n    \u003cbpmn2:startEvent id=\"StartEvent_1\" name=\"开始\"\u003e\n      \u003cbpmn2:outgoing\u003eFlow_1wx31tt\u003c/bpmn2:outgoing\u003e\n    \u003c/bpmn2:startEvent\u003e\n    \u003cbpmn2:endEvent id=\"Event_0e4belv\"\u003e\n      \u003cbpmn2:incoming\u003eFlow_16rpk2t\u003c/bpmn2:incoming\u003e\n    \u003c/bpmn2:endEvent\u003e\n    \u003cbpmn2:sequenceFlow id=\"Flow_1wx31tt\" sourceRef=\"StartEvent_1\" targetRef=\"Activity_00v2a9q\" /\u003e\n    \u003cbpmn2:userTask id=\"Activity_00v2a9q\" name=\"发起\" flowable:isFormDecision=\"0\" flowable:strategy=\"emptyAssign\" flowable:handling=\"directly\" flowable:dispatchStrategy=\"\" flowable:assignee=\"\" flowable:assigneeValue=\"\" flowable:assigneeType=\"\" flowable:assigneeList=\"\" flowable:assigneeGroup=\"\" flowable:subsequentConf=\"[]\" flowable:setAssignee=\"false\" flowable:formExpressionName=\"\" flowable:customType=\"\"\u003e\n      \u003cbpmn2:incoming\u003eFlow_1wx31tt\u003c/bpmn2:incoming\u003e\n      \u003cbpmn2:outgoing\u003eFlow_141a0yu\u003c/bpmn2:outgoing\u003e\n    \u003c/bpmn2:userTask\u003e\n    \u003cbpmn2:sequenceFlow id=\"Flow_141a0yu\" sourceRef=\"Activity_00v2a9q\" targetRef=\"Activity_163q90r\" /\u003e\n    \u003cbpmn2:userTask id=\"Activity_163q90r\" name=\"部门领导审批\" flowable:isFormDecision=\"0\" flowable:strategy=\"emptyAssign\" flowable:handling=\"directly\" flowable:dispatchStrategy=\"\" flowable:assignee=\"{{.lastExecLeader}}\" flowable:subsequentConf=\"[]\" flowable:setAssignee=\"false\" flowable:formExpressionName=\"\" flowable:customType=\"\" flowable:assigneeValue=\"\" flowable:assigneeType=\"\" flowable:assigneeList=\"\" flowable:assigneeGroup=\"\"\u003e\n      \u003cbpmn2:incoming\u003eFlow_141a0yu\u003c/bpmn2:incoming\u003e\n      \u003cbpmn2:outgoing\u003eFlow_1fjncll\u003c/bpmn2:outgoing\u003e\n    \u003c/bpmn2:userTask\u003e\n    \u003cbpmn2:sequenceFlow id=\"Flow_1fjncll\" sourceRef=\"Activity_163q90r\" targetRef=\"Activity_1dzwmdh\" /\u003e\n    \u003cbpmn2:userTask id=\"Activity_1dzwmdh\" name=\"科技部门审批\" flowable:isFormDecision=\"0\" flowable:strategy=\"emptyAssign\" flowable:handling=\"directly\" flowable:dispatchStrategy=\"\" flowable:assignee=\"\" flowable:assigneeValue=\"\" flowable:assigneeType=\"\" flowable:assigneeList=\"\" flowable:assigneeGroup=\"\" flowable:subsequentConf=\"[]\" flowable:setAssignee=\"false\" flowable:formExpressionName=\"\" flowable:customType=\"\"\u003e\n      \u003cbpmn2:incoming\u003eFlow_1fjncll\u003c/bpmn2:incoming\u003e\n      \u003cbpmn2:outgoing\u003eFlow_0aqq44o\u003c/bpmn2:outgoing\u003e\n    \u003c/bpmn2:userTask\u003e\n    \u003cbpmn2:sequenceFlow id=\"Flow_0aqq44o\" sourceRef=\"Activity_1dzwmdh\" targetRef=\"Activity_0a9hwjg\" /\u003e\n    \u003cbpmn2:userTask id=\"Activity_0a9hwjg\" name=\"验收\" flowable:isFormDecision=\"0\" flowable:strategy=\"emptyAssign\" flowable:handling=\"directly\" flowable:dispatchStrategy=\"\" flowable:assignee=\"{{.loginUser}}\" flowable:subsequentConf=\"[]\" flowable:setAssignee=\"false\" flowable:formExpressionName=\"\" flowable:customType=\"\" flowable:assigneeValue=\"\" flowable:assigneeType=\"\" flowable:assigneeList=\"\" flowable:assigneeGroup=\"\"\u003e\n      \u003cbpmn2:incoming\u003eFlow_0aqq44o\u003c/bpmn2:incoming\u003e\n      \u003cbpmn2:outgoing\u003eFlow_16rpk2t\u003c/bpmn2:outgoing\u003e\n    \u003c/bpmn2:userTask\u003e\n    \u003cbpmn2:sequenceFlow id=\"Flow_16rpk2t\" sourceRef=\"Activity_0a9hwjg\" targetRef=\"Event_0e4belv\" /\u003e\n  \u003c/bpmn2:process\u003e\n  \u003cbpmndi:BPMNDiagram id=\"BPMNDiagram_1\"\u003e\n    \u003cbpmndi:BPMNPlane id=\"BPMNPlane_1\" bpmnElement=\"ITSC-PROCESS-ID\"\u003e\n      \u003cbpmndi:BPMNEdge id=\"Flow_16rpk2t_di\" bpmnElement=\"Flow_16rpk2t\"\u003e\n        \u003cdi:waypoint x=\"430\" y=\"90\" /\u003e\n        \u003cdi:waypoint x=\"462\" y=\"90\" /\u003e\n      \u003c/bpmndi:BPMNEdge\u003e\n      \u003cbpmndi:BPMNEdge id=\"Flow_0aqq44o_di\" bpmnElement=\"Flow_0aqq44o\"\u003e\n        \u003cdi:waypoint x=\"300\" y=\"90\" /\u003e\n        \u003cdi:waypoint x=\"330\" y=\"90\" /\u003e\n      \u003c/bpmndi:BPMNEdge\u003e\n      \u003cbpmndi:BPMNEdge id=\"Flow_1fjncll_di\" bpmnElement=\"Flow_1fjncll\"\u003e\n        \u003cdi:waypoint x=\"170\" y=\"90\" /\u003e\n        \u003cdi:waypoint x=\"200\" y=\"90\" /\u003e\n      \u003c/bpmndi:BPMNEdge\u003e\n      \u003cbpmndi:BPMNEdge id=\"Flow_141a0yu_di\" bpmnElement=\"Flow_141a0yu\"\u003e\n        \u003cdi:waypoint x=\"40\" y=\"90\" /\u003e\n        \u003cdi:waypoint x=\"70\" y=\"90\" /\u003e\n      \u003c/bpmndi:BPMNEdge\u003e\n      \u003cbpmndi:BPMNEdge id=\"Flow_1wx31tt_di\" bpmnElement=\"Flow_1wx31tt\"\u003e\n        \u003cdi:waypoint x=\"-82\" y=\"90\" /\u003e\n        \u003cdi:waypoint x=\"-60\" y=\"90\" /\u003e\n      \u003c/bpmndi:BPMNEdge\u003e\n      \u003cbpmndi:BPMNShape id=\"_BPMNShape_StartEvent_2\" bpmnElement=\"StartEvent_1\"\u003e\n        \u003cdc:Bounds x=\"-118\" y=\"72\" width=\"36\" height=\"36\" /\u003e\n        \u003cbpmndi:BPMNLabel\u003e\n          \u003cdc:Bounds x=\"-111\" y=\"48\" width=\"22\" height=\"14\" /\u003e\n        \u003c/bpmndi:BPMNLabel\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n      \u003cbpmndi:BPMNShape id=\"Event_0e4belv_di\" bpmnElement=\"Event_0e4belv\"\u003e\n        \u003cdc:Bounds x=\"462\" y=\"72\" width=\"36\" height=\"36\" /\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n      \u003cbpmndi:BPMNShape id=\"Activity_00v2a9q_di\" bpmnElement=\"Activity_00v2a9q\"\u003e\n        \u003cdc:Bounds x=\"-60\" y=\"50\" width=\"100\" height=\"80\" /\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n      \u003cbpmndi:BPMNShape id=\"Activity_163q90r_di\" bpmnElement=\"Activity_163q90r\"\u003e\n        \u003cdc:Bounds x=\"70\" y=\"50\" width=\"100\" height=\"80\" /\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n      \u003cbpmndi:BPMNShape id=\"Activity_1dzwmdh_di\" bpmnElement=\"Activity_1dzwmdh\"\u003e\n        \u003cdc:Bounds x=\"200\" y=\"50\" width=\"100\" height=\"80\" /\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n      \u003cbpmndi:BPMNShape id=\"Activity_0a9hwjg_di\" bpmnElement=\"Activity_0a9hwjg\"\u003e\n        \u003cdc:Bounds x=\"330\" y=\"50\" width=\"100\" height=\"80\" /\u003e\n      \u003c/bpmndi:BPMNShape\u003e\n    \u003c/bpmndi:BPMNPlane\u003e\n  \u003c/bpmndi:BPMNDiagram\u003e\n\u003c/bpmn2:definitions\u003e","isJumpable":true},"process":{"instanceId":"64fded18e93a1","name":"基础环境资源申请表","category":""},"serviceInstance":{"owner":"easyops","ownerList":["easyops"],"ownerGroupList":[],"slaEnabled":false,"priority":null,"instanceId":"64fdf1bb82839","name":"基础环境资源申请表","category":"服务请求","hideTicketTemplateDraft":false},"serviceRelevanceOrder":[],"userTaskList":[{"type":"assignee","formDefinition":"[{\"key\":\"hhry6siln5\",\"modelField\":\"hhry6siln5\",\"name\":\"基本信息\",\"condition\":true,\"layout\":[0,1,12,1],\"type\":\"row\",\"displayCondition\":\"\",\"propertys\":[{\"key\":\"hhry6siln6\",\"type\":\"DEPARTMENT_SELECTOR\",\"label\":\"申请部门\",\"modelField\":\"hhry6siln6\",\"options\":{\"extraProps\":{\"objectId\":\"ORGANIZATION@EASYOPS\"},\"layout\":[0,0,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":{\"scope\":\"user_in_dept\",\"value\":[]},\"required\":true,\"dataType\":\"objectarray\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"limitNum\":20,\"frontKey\":[\"namePath\"],\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6siln5\"},{\"key\":\"hhry6siln7\",\"type\":\"USER_SELECTOR\",\"label\":\"申请人\",\"modelField\":\"hhry6siln7\",\"options\":{\"extraProps\":{\"objectId\":\"USER\"},\"layout\":[0,1,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":{\"scope\":\"login_user\",\"value\":[]},\"required\":true,\"dataType\":\"objectarray\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"limitNum\":20,\"frontKey\":[\"nickname\",\"user_tel\"],\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6siln5\"},{\"key\":\"hhry6siln8\",\"type\":\"COMMONDATE\",\"label\":\"申请日期\",\"modelField\":\"hhry6siln8\",\"options\":{\"extraProps\":{\"format\":\"YYYY年MM月DD日\",\"disabledPast\":false,\"presetValue\":{\"type\":\"add\",\"y\":0,\"M\":0,\"d\":0,\"h\":0,\"m\":0,\"s\":0}},\"layout\":[0,2,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"moment\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6siln5\"},{\"key\":\"hhry6siln9\",\"type\":\"TEXTAREA\",\"label\":\"说明\",\"modelField\":\"hhry6siln9\",\"options\":{\"extraProps\":{\"fieldAttr\":[]},\"layout\":[0,3,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":false,\"dataType\":\"string\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":false,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6siln5\"},{\"key\":\"hhry6silna\",\"type\":\"RADIO\",\"label\":\"操作类型\",\"modelField\":\"hhry6silna\",\"options\":{\"extraProps\":{\"options\":[{\"key\":\"option-29\",\"label\":\"新增\",\"value\":\"0\",\"isDefault\":true},{\"key\":\"option-30\",\"label\":\"变更\",\"value\":\"1\",\"isDefault\":false},{\"key\":\"option-31\",\"label\":\"撤销\",\"value\":\"2\",\"isDefault\":false}]},\"layout\":[0,4,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"0\",\"required\":true,\"dataType\":\"object\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"dataIndex\":\"label\",\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6siln5\"},{\"key\":\"hhry6silni\",\"type\":\"CMDBINSTANCESELECT\",\"label\":\"撤销主机\",\"modelField\":\"hhry6silni\",\"options\":{\"extraProps\":{\"objectId\":\"HOST\",\"url\":\"\",\"user\":\"\",\"listMode\":false,\"advancedPreQuery\":{\"objectId\":\"HOST\",\"instances\":{\"type\":\"all\",\"query\":{}}},\"defaultValue\":{\"objectId\":\"HOST\",\"instances\":{\"type\":\"null\",\"query\":{}}},\"sort\":{\"listMode\":false,\"sort\":[]}},\"layout\":[0,5,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":[],\"required\":true,\"dataType\":\"objectarray\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"#{hhry6siln5.hhry6silna}.value == '2'\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"primaryKey\":[\"instanceId\"],\"frontKey\":[\"hostname\",\"ip\"],\"enableFieldLinkage\":true},\"belongToSection\":\"hhry6siln5\"}],\"layoutConfig\":{\"layout\":\"vertical\",\"columns\":12}},{\"key\":\"hhry6silnj\",\"modelField\":\"hhry6silnj\",\"name\":\"变更主机\",\"condition\":true,\"layout\":[0,3,12,1],\"type\":\"row\",\"displayCondition\":\"#{hhry6siln5.hhry6silna}.value == '1'\",\"propertys\":[{\"key\":\"hhry6silnk\",\"type\":\"CMDBINSTANCESELECT\",\"label\":\"主机\",\"modelField\":\"hhry6silnk\",\"options\":{\"extraProps\":{\"objectId\":\"HOST\",\"url\":\"\",\"user\":\"\",\"listMode\":false,\"advancedPreQuery\":{\"objectId\":\"HOST\",\"instances\":{\"type\":\"all\",\"query\":{}}},\"defaultValue\":{\"objectId\":\"HOST\",\"instances\":{\"type\":\"null\",\"query\":{}}},\"sort\":{\"listMode\":false,\"sort\":[]},\"fieldAttr\":[\"required\"]},\"layout\":[0,0,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":[],\"required\":true,\"dataType\":\"objectarray\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":false,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"primaryKey\":[\"instanceId\"],\"frontKey\":[\"ip\",\"cpus\",\"memSize\",\"diskSize\"],\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnj\"},{\"key\":\"hhry6silnl\",\"type\":\"INPUT\",\"label\":\"变更说明\",\"modelField\":\"hhry6silnl\",\"options\":{\"extraProps\":{},\"layout\":[0,1,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"\",\"placeholder\":\"示例： CPU增加5c，/data分区增加500GB\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":false,\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnj\"}],\"layoutConfig\":{\"layout\":\"vertical\",\"columns\":12},\"enableContainerLinkage\":true,\"displayUserTaskId\":\"\"},{\"key\":\"hhry6silnb\",\"modelField\":\"hhry6silnb\",\"name\":\"新增主机\",\"condition\":true,\"layout\":[0,2,12,1],\"type\":\"row\",\"displayCondition\":\"#{hhry6siln5.hhry6silna}.value == '0'\",\"propertys\":[{\"key\":\"hhry6silnc\",\"type\":\"INPUT\",\"label\":\"主机名\",\"modelField\":\"hhry6silnc\",\"options\":{\"extraProps\":{},\"layout\":[0,0,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":false,\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"},{\"key\":\"hhrydc4aox\",\"type\":\"INPUT\",\"label\":\"IP\",\"modelField\":\"hhrydc4aox\",\"options\":{\"extraProps\":{},\"layout\":[0,1,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"((^\\\\s*((([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\\\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))\\\\s*$)|(^\\\\s*((([0-9A-Fa-f]{1,4}:){7}([0-9A-Fa-f]{1,4}|:))|(([0-9A-Fa-f]{1,4}:){6}(:[0-9A-Fa-f]{1,4}|((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){5}(((:[0-9A-Fa-f]{1,4}){1,2})|:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){4}(((:[0-9A-Fa-f]{1,4}){1,3})|((:[0-9A-Fa-f]{1,4})?:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){3}(((:[0-9A-Fa-f]{1,4}){1,4})|((:[0-9A-Fa-f]{1,4}){0,2}:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){2}(((:[0-9A-Fa-f]{1,4}){1,5})|((:[0-9A-Fa-f]{1,4}){0,3}:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){1}(((:[0-9A-Fa-f]{1,4}){1,6})|((:[0-9A-Fa-f]{1,4}){0,4}:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3}))|:))|(:(((:[0-9A-Fa-f]{1,4}){1,7})|((:[0-9A-Fa-f]{1,4}){0,5}:((25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)(\\\\.(25[0-5]|2[0-4]\\\\d|1\\\\d\\\\d|[1-9]?\\\\d)){3}))|:)))(%.+)?\\\\s*$))\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":true,\"patternErrorHint\":\"填入合法IP\",\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"},{\"key\":\"hhryhozacx\",\"type\":\"INPUT\",\"label\":\"CPU核心数\",\"modelField\":\"hhryhozacx\",\"options\":{\"extraProps\":{},\"layout\":[0,2,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"^\\\\d+$\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":true,\"patternErrorHint\":\"仅支持整型\",\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"},{\"key\":\"hhryi7c941\",\"type\":\"INPUT\",\"label\":\"内存（GB）\",\"modelField\":\"hhryi7c941\",\"options\":{\"extraProps\":{},\"layout\":[0,3,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"^\\\\d+$\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":true,\"patternErrorHint\":\"仅支持整型\",\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"},{\"key\":\"hhryiha4ll\",\"type\":\"INPUT\",\"label\":\"磁盘（GB）\",\"modelField\":\"hhryiha4ll\",\"options\":{\"extraProps\":{},\"layout\":[0,4,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":true,\"dataType\":\"string\",\"pattern\":\"^\\\\d+$\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":true,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":true,\"patternErrorHint\":\"仅支持整型\",\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"},{\"key\":\"hhryirdt6x\",\"type\":\"INPUT\",\"label\":\"说明\",\"modelField\":\"hhryirdt6x\",\"options\":{\"extraProps\":{\"fieldAttr\":[]},\"layout\":[0,5,12,1],\"layoutSpan\":12,\"labelCol\":3,\"defaultValue\":\"\",\"required\":false,\"dataType\":\"string\",\"pattern\":\"\",\"placeholder\":\"\",\"disabled\":false,\"enabled\":true,\"highLight\":false,\"isMore\":false,\"only\":false,\"note\":\"\",\"question\":[],\"displayCondition\":\"\",\"remoteFunc\":{\"toolId\":\"\",\"scriptInputs\":[]},\"rules\":[],\"isEnablePattern\":false,\"enableFieldLinkage\":false},\"belongToSection\":\"hhry6silnb\"}],\"layoutConfig\":{\"layout\":\"vertical\",\"columns\":12},\"enableContainerLinkage\":true,\"displayUserTaskId\":\"\"}]","formVersionId":"64fee41fb41c5","formName":"基础环境资源申请表-发起","fbForm":null,"standardFields":[],"id":"Activity_00v2a9q","name":"发起","isFormDecision":"0","formExpressionName":"","handling":"directly","isNextPar":false,"assigneeListUser":[],"assigneeGroups":[],"jumpableNodes":[],"labelViews":[],"subsequentConf":[],"operationConf":[],"processOp":[{"name":"跳转至部门领导审批","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_163q90r","isSubProcess":false}],"formDisplayMode":"side"},{"type":"assignee","formDefinition":"","formVersionId":"","formName":"","fbForm":null,"standardFields":[],"id":"Activity_163q90r","name":"部门领导审批","isFormDecision":"0","formExpressionName":"","handling":"directly","isNextPar":false,"assigneeListUser":[],"assigneeGroups":[],"jumpableNodes":[],"labelViews":[],"subsequentConf":[],"operationConf":[],"processOp":[{"name":"跳转至科技部门审批","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_1dzwmdh","isSubProcess":false}],"formDisplayMode":"side"},{"type":"assignee","formDefinition":"","formVersionId":"","formName":"","fbForm":null,"standardFields":[],"id":"Activity_1dzwmdh","name":"科技部门审批","isFormDecision":"0","formExpressionName":"","handling":"directly","isNextPar":false,"assigneeListUser":[],"assigneeGroups":[],"jumpableNodes":[],"labelViews":[],"subsequentConf":[],"operationConf":[],"processOp":[{"name":"跳转至验收","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_0a9hwjg","isSubProcess":false}],"formDisplayMode":"side"},{"type":"assignee","formDefinition":"","formVersionId":"","formName":"","fbForm":null,"standardFields":[],"id":"Activity_0a9hwjg","name":"验收","isFormDecision":"0","formExpressionName":"","handling":"directly","isNextPar":false,"assigneeListUser":[],"assigneeGroups":[],"jumpableNodes":[],"labelViews":[],"subsequentConf":[],"operationConf":[],"processOp":[{"name":"跳转至结束","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Event_0e4belv","isSubProcess":false}],"formDisplayMode":"side"}],"subTaskList":[],"nodeList":[{"id":"Activity_00v2a9q","name":"发起","links":{"incoming":["Flow_1wx31tt"],"outgoing":["Flow_141a0yu"]},"handling":"directly","approveType":"single","countersignRate":0,"skipStragety":"emptyAssign","userType":"specifyUser","assigneeValue":"","assigneeListUser":[],"assigneeGroups":[],"processOp":[{"name":"跳转至部门领导审批","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_163q90r","isSubProcess":false}],"isNextPar":false,"isFirst":true,"isLast":false,"isFormDecision":"0","formExpressionName":"","subProcess":{"isSub":false,"subProcessId":""},"Setting":{"userTaskId":"Activity_00v2a9q","triggerIdList":["5c9a95cd583c2"],"memoLevel":0,"rejectNodes":[],"allowedOps":["done","SLAChange"],"labelViews":[],"suspendSetting":{"isAutoActivate":false,"activateTime":1},"candidateSettings":[],"groupTodoSetting":null,"autoCCSetting":{"enable":false,"userList":[],"groupList":[],"roleList":[],"department":[]},"scriptSettings":{"preScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]},"postScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]}},"nextAssigneeSetting":{"enabled":false,"nextAssignees":[]},"revokeRoles":["admin"],"cancelRoles":["admin"],"holidayHandleConf":{"enabled":false,"groupId":"","groupV2Id":""},"userStrategyId":"","autoSetting":{"enabled":false,"toolSetting":{"toolId":"","toolArgs":[]},"actionExecutionSetting":{"actionType":"","executionTimeSetting":null},"exceptionNotice":{"receivers":null,"method":[],"subject":"","content":""}},"buttonSetting":[]}},{"id":"Activity_163q90r","name":"部门领导审批","links":{"incoming":["Flow_141a0yu"],"outgoing":["Flow_1fjncll"]},"handling":"directly","approveType":"single","countersignRate":0,"skipStragety":"emptyAssign","userType":"lastExecLeader","assigneeValue":"","assigneeListUser":[],"assigneeGroups":[],"processOp":[{"name":"跳转至科技部门审批","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_1dzwmdh","isSubProcess":false}],"isNextPar":false,"isFirst":false,"isLast":false,"isFormDecision":"0","formExpressionName":"","subProcess":{"isSub":false,"subProcessId":""},"Setting":{"userTaskId":"Activity_163q90r","triggerIdList":["5c9a95cd583c2"],"memoLevel":0,"rejectNodes":[],"allowedOps":["done","SLAChange"],"labelViews":[],"suspendSetting":{"isAutoActivate":false,"activateTime":1},"candidateSettings":[],"groupTodoSetting":null,"autoCCSetting":{"enable":false,"userList":[],"groupList":[],"roleList":[],"department":[]},"scriptSettings":{"preScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]},"postScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]}},"nextAssigneeSetting":{"enabled":false,"nextAssignees":[]},"revokeRoles":["admin"],"cancelRoles":["admin"],"holidayHandleConf":{"enabled":false,"groupId":"","groupV2Id":""},"userStrategyId":"","autoSetting":{"enabled":false,"toolSetting":{"toolId":"","toolArgs":[]},"actionExecutionSetting":{"actionType":"","executionTimeSetting":null},"exceptionNotice":{"receivers":null,"method":[],"subject":"","content":""}},"buttonSetting":[]}},{"id":"Activity_1dzwmdh","name":"科技部门审批","links":{"incoming":["Flow_1fjncll"],"outgoing":["Flow_0aqq44o"]},"handling":"directly","approveType":"single","countersignRate":0,"skipStragety":"emptyAssign","userType":"specifyUser","assigneeValue":"","assigneeListUser":[],"assigneeGroups":[],"processOp":[{"name":"跳转至验收","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Activity_0a9hwjg","isSubProcess":false}],"isNextPar":false,"isFirst":false,"isLast":false,"isFormDecision":"0","formExpressionName":"","subProcess":{"isSub":false,"subProcessId":""},"Setting":{"userTaskId":"Activity_1dzwmdh","triggerIdList":["5c9a95cd583c2"],"memoLevel":0,"rejectNodes":[],"allowedOps":["done","SLAChange"],"labelViews":[],"suspendSetting":{"isAutoActivate":false,"activateTime":1},"candidateSettings":[],"groupTodoSetting":null,"autoCCSetting":{"enable":false,"userList":[],"groupList":[],"roleList":[],"department":[]},"scriptSettings":{"preScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]},"postScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]}},"nextAssigneeSetting":{"enabled":false,"nextAssignees":[]},"revokeRoles":["admin"],"cancelRoles":["admin"],"holidayHandleConf":{"enabled":false,"groupId":"","groupV2Id":""},"userStrategyId":"","autoSetting":{"enabled":false,"toolSetting":{"toolId":"","toolArgs":[]},"actionExecutionSetting":{"actionType":"","executionTimeSetting":null},"exceptionNotice":{"receivers":null,"method":[],"subject":"","content":""}},"buttonSetting":[]}},{"id":"Activity_0a9hwjg","name":"验收","links":{"incoming":["Flow_0aqq44o"],"outgoing":["Flow_16rpk2t"]},"handling":"directly","approveType":"single","countersignRate":0,"skipStragety":"emptyAssign","userType":"loginUser","assigneeValue":"","assigneeListUser":[],"assigneeGroups":[],"processOp":[{"name":"跳转至结束","conditionExpression":{"name":"pass","value":"0"},"targetTaskId":"Event_0e4belv","isSubProcess":false}],"isNextPar":false,"isFirst":false,"isLast":false,"isFormDecision":"0","formExpressionName":"","subProcess":{"isSub":false,"subProcessId":""},"Setting":{"userTaskId":"Activity_0a9hwjg","triggerIdList":["5c9a95cd583c2"],"memoLevel":0,"rejectNodes":[],"allowedOps":["done","SLAChange"],"labelViews":[],"suspendSetting":{"isAutoActivate":false,"activateTime":1},"candidateSettings":[],"groupTodoSetting":null,"autoCCSetting":{"enable":false,"userList":[],"groupList":[],"roleList":[],"department":[]},"scriptSettings":{"preScript":{"name":"","desc":"","scriptIdList":["07efacdbc60ce282f6792e646c4d5502"],"isAsync":false,"operations":["pass"]},"postScript":{"name":"","desc":"","scriptIdList":[],"isAsync":true,"operations":[]}},"nextAssigneeSetting":{"enabled":false,"nextAssignees":[]},"revokeRoles":["admin"],"cancelRoles":["admin"],"holidayHandleConf":{"enabled":false,"groupId":"","groupV2Id":""},"userStrategyId":"","autoSetting":{"enabled":false,"toolSetting":{"toolId":"","toolArgs":[]},"actionExecutionSetting":{"actionType":"","executionTimeSetting":null},"exceptionNotice":{"receivers":null,"method":[],"subject":"","content":""}},"buttonSetting":[]}}],"finishedStepList":["Activity_00v2a9q","Activity_163q90r","Activity_1dzwmdh"],"userTaskInfo":[{"instanceId":"64fee7a31d095","userTaskId":"Activity_0a9hwjg","taskName":"验收","assignee":["easyops"],"assigneeGroup":[],"assigneeDepts":[],"role":"assignee","status":"running","type":"assignee","operator":"","oTime":""}],"stepList":[{"assignees":{"role":"assignee","assigneeList":["easyops"],"assigneeGroupList":[]},"subProcessInstanceStepId":"","fileInfo":"","instanceId":"64fee7a31d095","userTaskId":"Activity_0a9hwjg","taskName":"验收","operator":"","otime":"","ctime":"2026-04-21 09:38:51","etime":"","mtime":"","action":"","memo":"","status":"running","type":"assignee","isSubStep":false,"subProcessInstanceId":"","formData":"","consignors":[],"toolStatus":"","isExtraAssignee":false},{"assignees":null,"subProcessInstanceStepId":"","fileInfo":"","instanceId":"64fee7955bbf5","userTaskId":"Activity_00v2a9q","taskName":"发起","operator":"easyops","otime":"2026-04-21 09:38:36","ctime":"2026-04-21 09:38:36","etime":"2026-04-21 09:38:36","mtime":"","action":"","memo":"","status":"done","type":"assignee","isSubStep":false,"subProcessInstanceId":"","formData":"[{\"key\":\"hhry6siln5\",\"values\":[{\"hhry6siln6\":[{\"departmentId\":\"64f904290d225\",\"namePath\":\"河南省分行/科技处\"}],\"hhry6siln7\":[{\"nickname\":\"超管\",\"user_tel\":\"13721056647\",\"instanceId\":\"64d481a5b58b5\"}],\"hhry6siln8\":\"2026-04-21T09:27:28+08:00\",\"hhry6siln9\":\"\",\"hhry6silna\":{\"key\":\"option-29\",\"label\":\"新增\",\"value\":\"0\",\"isDefault\":true}}]},{\"key\":\"hhry6silnb\",\"values\":[{\"hhry6silnc\":\"test1\",\"hhrydc4aox\":\"1.1.1.2\",\"hhryhozacx\":\"32\",\"hhryi7c941\":\"64\",\"hhryiha4ll\":\"1024\",\"hhryirdt6x\":\"\"}]}]","consignors":[],"toolStatus":"","isExtraAssignee":false},{"assignees":null,"subProcessInstanceStepId":"","fileInfo":"","instanceId":"64fee7958ab21","userTaskId":"Activity_163q90r","taskName":"部门领导审批","operator":"easyops","otime":"2026-04-21 09:38:45","ctime":"2026-04-21 09:38:36","etime":"2026-04-21 09:38:45","mtime":"","action":"","memo":"","status":"done","type":"assignee","isSubStep":false,"subProcessInstanceId":"","formData":"[]","consignors":[],"toolStatus":"","isExtraAssignee":false},{"assignees":null,"subProcessInstanceStepId":"","fileInfo":"","instanceId":"64fee79dc2b95","userTaskId":"Activity_1dzwmdh","taskName":"科技部门审批","operator":"easyops","otime":"2026-04-21 09:38:51","ctime":"2026-04-21 09:38:45","etime":"2026-04-21 09:38:51","mtime":"","action":"","memo":"","status":"done","type":"assignee","isSubStep":false,"subProcessInstanceId":"","formData":"[]","consignors":[],"toolStatus":"","isExtraAssignee":false}],"stopAts":["Activity_0a9hwjg"],"allowedOp":{"canDone":true,"canWithdraw":false,"canAssignee":false,"canCc":false,"canDistribute":false,"canClaim":false,"canNextAssignee":false,"canComment":false,"canSLAChange":true,"canClose":false,"canSuspend":true,"canRevoke":false,"canAddExtraAssignee":false,"canConvert":false,"CanCreateRelevanceTicket":false,"CanRelevanceTicket":false,"CanCancel":false,"CanTaskHistory":false,"CanShareLink":false,"CanSaveDraft":false,"CanSaveTemplate":false,"CanUseTemplate":false},"stepOperationRecord":[{"operationId":"69e6d51c51a4a0a03ed95474","processInstanceId":"64fee79551209","stepId":"64fee7955bbf5","isExtraAssignee":false,"extraAssigneeType":"","operator":{"instanceId":"64d481a5b58b5","username":"easyops","nickname":"超管","state":"","userIcon":"","showName":"easyops(超管)"},"consignors":[],"recordCtime":"2026-04-21 09:38:36","operationTime":"2026-04-21 09:38:36","userTaskId":"Activity_00v2a9q","taskName":"发起","memo":"","isSubProcess":false,"subProcessInstanceId":"","formData":"","toUser":[],"toUserGroup":[],"action":"done","comments":[],"extendedFieldValues":[]},{"operationId":"69e6d52551a4a0a03ed95476","processInstanceId":"64fee79551209","stepId":"64fee7958ab21","isExtraAssignee":false,"extraAssigneeType":"","operator":{"instanceId":"64d481a5b58b5","username":"easyops","nickname":"超管","state":"","userIcon":"","showName":"easyops(超管)"},"consignors":[],"recordCtime":"2026-04-21 09:38:45","operationTime":"2026-04-21 09:38:45","userTaskId":"Activity_163q90r","taskName":"部门领导审批","memo":"","isSubProcess":false,"subProcessInstanceId":"","formData":"","toUser":[],"toUserGroup":[],"action":"done","comments":[],"extendedFieldValues":[]},{"operationId":"69e6d52b51a4a0a03ed95477","processInstanceId":"64fee79551209","stepId":"64fee79dc2b95","isExtraAssignee":false,"extraAssigneeType":"","operator":{"instanceId":"64d481a5b58b5","username":"easyops","nickname":"超管","state":"","userIcon":"","showName":"easyops(超管)"},"consignors":[],"recordCtime":"2026-04-21 09:38:51","operationTime":"2026-04-21 09:38:51","userTaskId":"Activity_1dzwmdh","taskName":"科技部门审批","memo":"","isSubProcess":false,"subProcessInstanceId":"","formData":"","toUser":[],"toUserGroup":[],"action":"done","comments":[],"extendedFieldValues":[]}],"userInfoMap":{"easyops":"超管"},"instanceId":"64fee7a31d095","userTaskId":"Activity_0a9hwjg","taskName":"验收","executionId":"","flowableTaskId":"","creator":"easyops","creatorShowName":"","ctime":"2026-04-21 09:38:51","etime":"","mtime":"","operator":"","operatorShowName":"","operatorLeader":"","status":"running","type":"","nrOfInstances":0,"otime":"","action":"","memo":"","variables":[],"formData":"[]","isSubStep":false,"subProcessInstanceId":"","isTimeout":false,"isDelete":false,"isAck":false,"rTime":"","consignors":[],"slaStatus":"","toolStatus":"","isExtraAssignee":false,"extraAssigneeType":"","timeoutTime":"","unassigned":false,"extraAssigneeList":[],"oldProcessInstanceTaskStruct":null}'''

    logger.setLevel(logging.INFO)
    client = EasyOpsClient()
    transform = {
        "hhry6silnc": {
            "key": "hostname",
        },
        "hhrydc4aox": {
            "key": "ip",
        },
        "hhryhozacx": {
            "key": "cpus",
        },
        "hhryi7c941": {
            "key": "memSize",
            "converter": lambda x: int(x) * 1024**2,
        },
        "hhryiha4ll": {
            "key": "diskSize",
            "converter": lambda x: int(x) * 1024**2,
        },
        "hhryirdt6x": {
            "key": "use",
        },
    }
    insts = extract_form_value(orderInfo,"Activity_00v2a9q.hhry6silnb",transform=transform,first_only=False)  
    # pprint(insts)
    client.import_instance("HOST", insts, ["ip"])