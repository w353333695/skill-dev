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

    def delete_instance(self, object_id: str, instance_ids: List[str],
                        batch_size: int = 1000) -> Dict:
        """
        批量删除实例（撤销主机场景）

        EasyOps API: DeleteInstanceBatch
        DELETE /object/{object_id}/instance_batch?instanceIds=a;b;c

        :param object_id: 模型对象ID
        :param instance_ids: 实例 instanceId 列表
        :return: 删除结果
        :rtype: dict
        """
        port = 8079
        total = 0
        for i in range(0, len(instance_ids), batch_size):
            batch = instance_ids[i:i + batch_size]
            resp = self._request("DELETE", f"/object/{object_id}/instance_batch",
                                 port=port, params={"instanceIds": ";".join(batch)})
            result = resp.json()
            if result.get("code") not in (0, None):
                logger.error(f"删除{object_id}实例失败: {result}")
                exit(1)
            total += len(batch)
            logger.info(f"已删除 {object_id} 实例 {len(batch)} 个: {batch}")
        return {"deleted_count": total}

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
    logger.setLevel(logging.INFO)
    client = EasyOpsClient()
    transform = {
        "hhry6silnc": {
            "key": "hostname",
        },
        "hhrydc4aox": {
            "key": "ip",
        },
        "hhu7dw2ukx": {
            "key": "osDistro",
            "converter": lambda x: x['label'],
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
    report = []

    # 操作类型分派（表单 RADIO hhry6silna：0=新增 1=变更 2=撤销，displayCondition 互斥）
    op_raw = extract_form_value(orderInfo, "Activity_00v2a9q.hhry6siln5.hhry6silna")
    op_val = op_raw.get("value", "0") if isinstance(op_raw, dict) else "0"

    if op_val == "2":
        # 撤销：删除「撤销主机」（hhry6silni，CMDBINSTANCESELECT→[{instanceId,name}]）选中实例
        raw = extract_form_value(orderInfo, "Activity_00v2a9q.hhry6siln5.hhry6silni")
        if isinstance(raw, dict):
            raw = [raw]
        ids = [x.get("instanceId") for x in (raw or [])
               if isinstance(x, dict) and x.get("instanceId")]
        if ids:
            r = client.delete_instance("HOST", ids)
            report.append(f"撤销：已删除 {r['deleted_count']} 台 HOST 实例 {ids}")
        else:
            report.append("撤销：未选择主机，跳过删除")
    else:
        # 新增/变更：upsert 新增主机 table（keys=ip）
        insts = extract_form_value(orderInfo, "Activity_00v2a9q.hhry6silnb",
                                   transform=transform, first_only=False)
        if insts:
            r = client.import_instance("HOST", insts, ["ip"])
            report.append(f"新增/变更：upsert {len(insts)} 行"
                          f"（insert {r['insert_count']} / update {r['update_count']} / failed {r['failed_count']}）")
        else:
            report.append("新增/变更：无数据，跳过")

    report_text = "\n".join(report)
    logger.info(f"回写完成:\n{report_text}")
    try:
        PutStr("report", report_text)
    except NameError:
        pass