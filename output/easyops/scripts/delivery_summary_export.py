#!/usr/bin/env python3
"""
EasyOps 平台交付成果汇总脚本

汇总 EasyOps 平台各模块（CMDB / 监控 / 自动化 / ITSM）的交付成果，
从对应 CMDB 模型搜索实例，为每个成果生成一条记录（模块、类别、名称、URL、描述），
最终输出到 CSV 文件。

支持两种认证方式:
    1. 内网调用（默认）: 通过 agent 配置自动获取 host/org
    2. OpenAPI 调用: 使用 AK/SK 签名认证

使用方法:
    直接运行: python delivery_summary.py
"""

import csv
import json
import logging
import os
import hashlib
import hmac
import platform
import time
from typing import List, Dict, Any, Optional, Callable
from urllib.parse import urlencode

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 脚本所在目录（输出物放同级目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# EasyOps 前端 base 路径（URL 示例中均为 http://172.30.0.90/next/...）
EASYOPS_NEXT_BASE = "/next"

# CSV 输出文件路径（脚本同级目录）
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "delivery_summary.csv")

# CSV 表头
CSV_HEADERS = ["模块", "类别", "名称", "URL", "描述"]

# =============================================================================
# 成果导出配置
# =============================================================================
# 是否在汇总 CSV 的同时，导出各类成果（分目录）：
#   - cmdb 模型 → JSON（model_get_detail，含继承属性/关系/视图）
#   - 工具/监控套件/资源自动发现套件/巡检套件/ITSM服务 → 平台导出接口的压缩包
ENABLE_EXPORT = True
# 导出根目录（脚本同级 exports/）
EXPORT_DIR = os.path.join(SCRIPT_DIR, "exports")
# 文件名中"版本"统一取该字段（CMDB 实例/模型通用系统版本号，6 类成果均含）
VERSION_FIELD = "_version"
# 各导出接口所用内网端口（service→port，源自后端契约 contracts.yaml）
PORT_CMDB = 8079              # logic.cmdb.service
PORT_TOOL = 8181              # logic.tool_service
PORT_COLLECTOR_PLUGIN = 8151  # logic.collector_plugin_service
PORT_INSPECTION = 8103        # logic.inspection
PORT_FLOWABLE = 8134          # logic.flowable_service


class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射（仅 OpenAPI 模式需要）
    PORT_APP_MAP = {
        8079: "cmdbservice",
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

    # =====================================================================
    # 以下为具体 API 方法（端口直接写在方法内）
    # =====================================================================

    def search_instances(self, object_id: str, query: Optional[dict] = None,
                         fields: Optional[List[str]] = None,
                         page_size: int = 1000) -> List[Dict]:
        """
        搜索实例（自动翻页返回全部数据）

        EasyOps API: PostSearchV3
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param query: 查询条件，如 {"name": {"$like": "%xx%"}}
        :param fields: 指定返回字段，None 表示返回全部
        :param page_size: 每页条数，默认 1000
        :return: 实例列表
        """
        port = 8079
        path = f"v3/object/{object_id}/instance/_search"
        body = {
            "fields": fields if fields else ["*"],
            "query": query if query else {},
            "page": 1,
            "page_size": page_size,
        }
        all_list = []
        page = 1
        while True:
            body["page"] = page
            resp = self._request("POST", path, port=port, data=body).json()
            data = resp.get("data", {})
            items = data.get("list", [])
            all_list.extend(items)
            total = data.get("total", 0)
            logger.info(f"[{object_id}] 已获取 {len(all_list)}/{total} 条")
            if len(items) < page_size or not items:
                break
            page += 1
        return all_list

    def count_instances(self, object_id: str, query: Optional[dict] = None) -> int:
        """
        统计指定模型的实例数量（只取一页，从响应的 total 字段读取，不翻页）

        EasyOps API: PostSearchV3
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param query: 查询条件，None 表示统计该模型全部实例
        :return: 实例总数
        :rtype: int
        """
        port = 8079
        path = f"v3/object/{object_id}/instance/_search"
        body = {
            "fields": ["instanceId"],
            "query": query if query else {},
            "page": 1,
            "page_size": 1,
        }
        resp = self._request("POST", path, port=port, data=body).json()
        data = resp.get("data", {})
        return int(data.get("total", 0) or 0)

    def list_object_basic(self, visible: str = "visible",
                          page_size: int = 3000) -> List[Dict]:
        """
        获取模型基本信息列表（非隐藏模型）

        EasyOps API: ListObjectBasic
        服务: logic.cmdb.service
        端口: 8079

        :param visible: 可见性过滤，visible 表示非隐藏
        :param page_size: 每页条数
        :return: 模型基本信息列表（含 objectId、name、category、memo 等）
        """
        port = 8079
        path = "object_basic"
        all_list = []
        page = 1
        while True:
            params = {
                "page": page,
                "page_size": page_size,
                "visible": visible,
                "q": "",
                "category": "",
                "emptyCategory": "false",
            }
            resp = self._request("GET", path, port=port, params=params).json()
            data = resp.get("data", {})
            items = data.get("list", [])
            all_list.extend(items)
            total = data.get("total", 0)
            logger.info(f"[模型列表] 已获取 {len(all_list)}/{total} 个")
            if len(items) < page_size or not items:
                break
            page += 1
        return all_list

    def get_topo_detail(self, topo_instance_id: str) -> Dict:
        """
        获取实例拓扑详情（用于判断链路上是否有实际数据）

        EasyOps API: GetDetail (cmdb.instance)
        服务: logic.cmdb.service
        端口: 8079

        :param topo_instance_id: _TOPO_INSTANCE_VIEW 模型的实例 ID
        :return: 拓扑详情 data（含节点链路数据）
        """
        port = 8079
        path = f"object/_TOPO_INSTANCE_VIEW/instance/{topo_instance_id}"
        params = {"fields": "name,objectId,data"}
        resp = self._request("GET", path, port=port, params=params).json()
        return resp.get("data", {})


# =============================================================================
# 业务逻辑区域
# EasyOpsClient 只负责 HTTP 请求封装；数据处理、流程编排、CSV 输出等
# 业务逻辑一律写在下面的函数与 main() 中。
# =============================================================================

def _safe_get(d: Dict, *keys, default=None):
    """安全地从嵌套字典取值"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


def _first_non_empty(d: Dict, keys: List[str], default: str = "") -> Any:
    """按候选字段顺序取第一个非空值（用于兼容不同模型的名称/描述字段）"""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _has_topo_chain(topo_detail: Dict) -> bool:
    """
    判断拓扑链路是否定义了关系层级（链路上"有数据"）。

    GetDetail 返回的 data 是拓扑视图的链路定义（不含实例数据）：
    {"object_id": "...", "child": [{"parentOut": "...", "child": [...]}, ...]}
    只要 child 链路非空（定义了至少一层关系），即视为有效拓扑示例。

    :param topo_detail: get_topo_detail 返回的 data
    :return: 是否定义了关系链路
    """
    if not topo_detail:
        return False
    data = topo_detail.get("data", topo_detail)
    # data 可能是 JSON 字符串
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return False
    if not isinstance(data, dict):
        return False
    child = data.get("child")
    return isinstance(child, list) and len(child) > 0


# -----------------------------------------------------------------------------
# URL 模板：每个类别一行记录的 URL 生成规则
# -----------------------------------------------------------------------------

def _url_model_detail(host: str, object_id: str) -> str:
    """CMDB 模型详情 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/cmdb-model-management/object/{object_id}/detail"


def _url_instance_list(host: str, object_id: str) -> str:
    """CMDB 实例列表 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/next-cmdb-instance-management/next/{object_id}/list"


def _url_topo_view(host: str, object_id: str, topo_id: str, instance_id: str) -> str:
    """CMDB 实例拓扑 URL"""
    return (f"http://{host}{EASYOPS_NEXT_BASE}/next-cmdb-instance-management/next/"
            f"{object_id}/instance-topology/{instance_id}/view/{topo_id}")


def _url_relation_query(host: str, instance_id: str) -> str:
    """关系查询 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/cmdb-relation-query/BUSINESS/result/{instance_id}"


def _url_data_quality(host: str, instance_id: str, object_id: str = "") -> str:
    """合规性检查 URL"""
    base = f"http://{host}{EASYOPS_NEXT_BASE}/cmdb-data-quality/detail/{instance_id}"
    return f"{base}?objectId={object_id}" if object_id else base


def _url_monitor_kit(host: str, instance_id: str) -> str:
    """监控套件 / 资源自动发现套件 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/monitor-kit/kit/easyops/{instance_id}/detail"


def _url_collect_strategy(host: str, instance_id: str) -> str:
    """监控采集任务 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/collect-platform/data-collection/strategy/{instance_id}/detail"


def _url_auto_discovery_task(host: str, instance_id: str) -> str:
    """资源自动发现采集任务 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/auto-discovery/task-manager/detail/{instance_id}"


def _url_alert_rule(host: str, instance_id: str) -> str:
    """告警规则 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/events/alert-rule/system-rule/{instance_id}/edit"


def _url_tool(host: str, tool_id: str) -> str:
    """工具库 URL（使用工具的 toolId，32位）"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/tool/management/{tool_id}/detail"


def _url_flow(host: str, flow_id: str) -> str:
    """流水线 URL（使用 flowId，32位）"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/flow/{flow_id}/detail"


def _url_scheduler_task(host: str, task_id: str) -> str:
    """定时任务 URL（使用任务 id，32位）"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/schedulers/task/{task_id}/detail?jobType=flow"


def _url_inspection_suite(host: str, suite_id: str) -> str:
    """巡检套件 URL（使用套件的 id，如 host/weblogic，即 inspector_xxx）"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/automatic-inspection/inspection/{suite_id}/history"


def _url_inspection_task(host: str, suite_id: str, task_id: str) -> str:
    """巡检任务 URL（套件 id + 任务 id）"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/automatic-inspection/inspection/{suite_id}/task/{task_id}/detail"


def _url_itsc_service(host: str, instance_id: str) -> str:
    """ITSM 服务 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-service-management/setting-list/{instance_id}"


def _url_itsc_process(host: str, process_id: str, version_id: str) -> str:
    """ITSM 流程 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-process-manage/detail/{process_id}/{version_id}"


def _url_itsc_form(host: str, form_id: str, version_id: str) -> str:
    """ITSM 表单 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-form-management/form-list/{form_id}/{version_id}"


def _url_itsc_duty_group(host: str, instance_id: str) -> str:
    """ITSM 值班组 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-operation-management/duty-group/detail/{instance_id}"


def _url_itsc_sla(host: str, instance_id: str) -> str:
    """ITSM SLA URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-advanced-settings/service-agreement-list/service-agreement-detail?instanceId={instance_id}"


def _url_itsc_trigger(host: str, instance_id: str) -> str:
    """ITSM 触发器 URL"""
    return f"http://{host}{EASYOPS_NEXT_BASE}/itsc-advanced-settings/trigger-manage/update/{instance_id}"


# -----------------------------------------------------------------------------
# 各模块采集函数：每个函数返回若干行记录（dict: 模块/类别/名称/URL/描述）
# -----------------------------------------------------------------------------

def collect_cmdb_models(client: EasyOpsClient, host: str) -> List[Dict]:
    """CMDB - 模型（非隐藏）"""
    rows = []
    for m in client.list_object_basic(visible="visible"):
        object_id = m.get("objectId")
        if not object_id:
            continue
        rows.append({
            "模块": "CMDB",
            "类别": "模型",
            "名称": m.get("name") or object_id,
            "URL": _url_model_detail(host, object_id),
            "描述": m.get("memo") or m.get("category") or "",
        })
    logger.info(f"[CMDB-模型] 生成 {len(rows)} 条")
    return rows


def collect_cmdb_instance_list(client: EasyOpsClient, host: str) -> List[Dict]:
    """CMDB - 实例列表（非隐藏模型），描述为该模型的实例数量"""
    rows = []
    for m in client.list_object_basic(visible="visible"):
        object_id = m.get("objectId")
        if not object_id:
            continue
        try:
            count = client.count_instances(object_id)
        except Exception as e:
            logger.warning(f"[CMDB-实例列表] 统计 {object_id} 实例数失败: {e}")
            count = 0
        rows.append({
            "模块": "CMDB",
            "类别": "实例列表",
            "名称": m.get("name") or object_id,
            "URL": _url_instance_list(host, object_id),
            "描述": f"实例数量: {count}",
        })
    logger.info(f"[CMDB-实例列表] 生成 {len(rows)} 条")
    return rows


def collect_cmdb_topology(client: EasyOpsClient, host: str) -> List[Dict]:
    """
    CMDB - 实例拓扑

    从 _TOPO_INSTANCE_VIEW 获取拓扑，链路上有实际数据的才作为拓扑示例。
    对每个有效拓扑，取其 object_id 下任一实例作为展示入口。
    """
    rows = []
    topos = client.search_instances("_TOPO_INSTANCE_VIEW")
    logger.info(f"[CMDB-拓扑] 待校验拓扑 {len(topos)} 个")
    for topo in topos:
        topo_id = topo.get("instanceId")
        object_id = topo.get("objectId")
        if not topo_id or not object_id:
            continue
        try:
            detail = client.get_topo_detail(topo_id)
        except Exception as e:
            logger.warning(f"[CMDB-拓扑] 获取拓扑 {topo_id} 详情失败: {e}")
            continue
        if not _has_topo_chain(detail):
            logger.debug(f"[CMDB-拓扑] {topo_id} 链路为空，跳过")
            continue
        # 取该模型下任一实例作为拓扑示例入口；模型不存在或无实例则跳过
        try:
            sample = client.search_instances(
                object_id, fields=["instanceId"], page_size=1
            )
        except Exception as e:
            logger.debug(f"[CMDB-拓扑] {object_id} 无示例实例，跳过拓扑 {topo_id}: {e}")
            continue
        if not sample:
            logger.debug(f"[CMDB-拓扑] {object_id} 无示例实例，跳过拓扑 {topo_id}")
            continue
        sample_id = sample[0].get("instanceId")
        rows.append({
            "模块": "CMDB",
            "类别": "实例拓扑",
            "名称": topo.get("name") or f"{object_id} 拓扑",
            "URL": _url_topo_view(host, object_id, topo_id, sample_id),
            "描述": f"拓扑视图（{object_id}）",
        })
    logger.info(f"[CMDB-拓扑] 生成 {len(rows)} 条（链路有数据）")
    return rows


def collect_cmdb_relation_query(client: EasyOpsClient, host: str) -> List[Dict]:
    """CMDB - 关系查询"""
    rows = []
    insts = client.search_instances("CMDB_RELATION_QUERY_STRATEGY@EASYOPS")
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "CMDB",
            "类别": "关系查询",
            "名称": ins.get("name") or iid,
            "URL": _url_relation_query(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[CMDB-关系查询] 生成 {len(rows)} 条")
    return rows


def collect_cmdb_data_quality(client: EasyOpsClient, host: str) -> List[Dict]:
    """CMDB - 合规性检查"""
    rows = []
    insts = client.search_instances("_DATAFILTER_STRATEGY")
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        object_id = ins.get("objectId") or ""
        rows.append({
            "模块": "CMDB",
            "类别": "合规性检查",
            "名称": ins.get("name") or iid,
            "URL": _url_data_quality(host, iid, object_id),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[CMDB-合规性检查] 生成 {len(rows)} 条")
    return rows


def _collect_collector_plugin(client: EasyOpsClient, host: str,
                              sampler_type: str, module: str,
                              category: str, url_fn: Callable) -> List[Dict]:
    """
    采集 _COLLECTOR_EASYOPS_PLUGIN 下指定 samplerType 的套件。

    :param sampler_type: metric_sampler(监控套件) / process_sampler(资源自动发现套件)
    :param module: 所属模块名
    :param category: CSV 类别名
    :param url_fn: URL 生成函数
    """
    rows = []
    query = {"samplerType": sampler_type}
    insts = client.search_instances("_COLLECTOR_EASYOPS_PLUGIN", query=query)
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": module,
            "类别": category,
            "名称": ins.get("name") or iid,
            "URL": url_fn(host, iid),
            "描述": ins.get("description") or ins.get("category") or "",
        })
    logger.info(f"[{module}-{category}] 生成 {len(rows)} 条 (samplerType={sampler_type})")
    return rows


def _collect_collector_job(client: EasyOpsClient, host: str,
                           sampler_type: str, module: str,
                           category: str, url_fn: Callable) -> List[Dict]:
    """
    采集 _COLLECTOR_JOB 下指定 samplerType 的采集任务。

    :param sampler_type: metric_sampler(监控采集任务) / process_sampler(资源自动发现采集任务)
    :param module: 所属模块名
    :param category: CSV 类别名
    :param url_fn: URL 生成函数
    """
    rows = []
    query = {"samplerType": sampler_type}
    insts = client.search_instances("_COLLECTOR_JOB", query=query)
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": module,
            "类别": category,
            "名称": ins.get("name") or iid,
            "URL": url_fn(host, iid),
            "描述": ins.get("description") or ins.get("objectId") or "",
        })
    logger.info(f"[{module}-{category}] 生成 {len(rows)} 条 (samplerType={sampler_type})")
    return rows


def collect_alert_rules(client: EasyOpsClient, host: str) -> List[Dict]:
    """监控 - 告警规则"""
    rows = []
    insts = client.search_instances("ALERT_RULE")
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "监控",
            "类别": "告警规则",
            "名称": ins.get("name") or iid,
            "URL": _url_alert_rule(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[监控-告警规则] 生成 {len(rows)} 条")
    return rows


def collect_tool(client: EasyOpsClient, host: str) -> List[Dict]:
    """自动化 - 工具库（URL 使用 toolId）"""
    rows = []
    insts = client.search_instances("_TOOL_CONFIG@EASYOPS")
    for ins in insts:
        tool_id = ins.get("toolId")
        if not tool_id:
            continue
        rows.append({
            "模块": "自动化",
            "类别": "工具库",
            "名称": ins.get("name") or tool_id,
            "URL": _url_tool(host, tool_id),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[自动化-工具库] 生成 {len(rows)} 条")
    return rows


def collect_flow(client: EasyOpsClient, host: str) -> List[Dict]:
    """自动化 - 流水线（URL 使用 flowId）"""
    rows = []
    insts = client.search_instances("_FLOW_CONFIG@EASYOPS")
    for ins in insts:
        flow_id = ins.get("flowId")
        if not flow_id:
            continue
        rows.append({
            "模块": "自动化",
            "类别": "流水线",
            "名称": ins.get("name") or flow_id,
            "URL": _url_flow(host, flow_id),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[自动化-流水线] 生成 {len(rows)} 条")
    return rows


def collect_scheduler_task(client: EasyOpsClient, host: str) -> List[Dict]:
    """自动化 - 定时任务（URL 使用任务 id）"""
    rows = []
    insts = client.search_instances("_SCHEDULER_TASK@EASYOPS")
    for ins in insts:
        task_id = ins.get("id")
        if not task_id:
            continue
        rows.append({
            "模块": "自动化",
            "类别": "定时任务",
            "名称": ins.get("name") or task_id,
            "URL": _url_scheduler_task(host, task_id),
            "描述": ins.get("memo") or ins.get("description") or "",
        })
    logger.info(f"[自动化-定时任务] 生成 {len(rows)} 条")
    return rows


def collect_inspection_suite(client: EasyOpsClient, host: str) -> List[Dict]:
    """自动化 - 巡检套件（URL 使用套件 id，如 host/weblogic）"""
    rows = []
    insts = client.search_instances("INSPECTION_INFO@EASYOPS")
    for ins in insts:
        suite_id = ins.get("id")
        if not suite_id:
            continue
        rows.append({
            "模块": "自动化",
            "类别": "巡检套件",
            "名称": ins.get("name") or suite_id,
            "URL": _url_inspection_suite(host, suite_id),
            "描述": ins.get("memo") or ins.get("description") or "",
        })
    logger.info(f"[自动化-巡检套件] 生成 {len(rows)} 条")
    return rows


def collect_inspection_task(client: EasyOpsClient, host: str) -> List[Dict]:
    """
    自动化 - 巡检任务

    URL 使用套件 id（pluginId）+ 任务 id（inspectionTaskId）。
    """
    rows = []
    insts = client.search_instances("INSPECTION_TASK_INFO@EASYOPS")
    for ins in insts:
        suite_id = ins.get("pluginId")
        task_id = ins.get("inspectionTaskId")
        if not suite_id or not task_id:
            continue
        rows.append({
            "模块": "自动化",
            "类别": "巡检任务",
            "名称": ins.get("name") or task_id,
            "URL": _url_inspection_task(host, suite_id, task_id),
            "描述": ins.get("memo") or ins.get("description") or "",
        })
    logger.info(f"[自动化-巡检任务] 生成 {len(rows)} 条")
    return rows


def collect_itsc_service(client: EasyOpsClient, host: str) -> List[Dict]:
    """ITSM - 服务"""
    rows = []
    insts = client.search_instances("_ITSC_SERVICE_INSTANCE")
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "ITSM",
            "类别": "服务",
            "名称": ins.get("name") or iid,
            "URL": _url_itsc_service(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[ITSM-服务] 生成 {len(rows)} 条")
    return rows


def collect_itsc_process(client: EasyOpsClient, host: str) -> List[Dict]:
    """
    ITSM - 流程

    以 _ITSC_PROCESS 为主体，通过关系 ITSC_PROCESS_VERSION 带出主版本(isMain=True)，
    URL 使用流程的 instanceId + 流程版本的 instanceId。
    """
    rows = []
    processes = client.search_instances(
        "_ITSC_PROCESS",
        fields=["instanceId", "name",
                "ITSC_PROCESS_VERSION.instanceId",
                "ITSC_PROCESS_VERSION.isMain"],
    )
    for proc in processes:
        proc_id = proc.get("instanceId")
        if not proc_id:
            continue
        versions = proc.get("ITSC_PROCESS_VERSION") or []
        main_versions = [v for v in versions if v.get("isMain") is True]
        if not main_versions:
            continue
        for ver in main_versions:
            version_id = ver.get("instanceId")
            if not version_id:
                continue
            rows.append({
                "模块": "ITSM",
                "类别": "流程",
                "名称": proc.get("name") or proc_id,
                "URL": _url_itsc_process(host, proc_id, version_id),
                "描述": proc.get("category") or proc.get("memo") or "",
            })
    logger.info(f"[ITSM-流程] 生成 {len(rows)} 条 (主版本)")
    return rows


def collect_itsc_form(client: EasyOpsClient, host: str) -> List[Dict]:
    """
    ITSM - 表单

    以 _ITSC_FORM_SCHEMA 为主体，通过关系 ITSC_FORM_VERSION 带出其主版本(isMain=True)，
    schema 的 name 即表单名。URL 用 schema instanceId / version instanceId。
    """
    rows = []
    # 关系字段带出主版本（仅 isMain=True 的版本）
    schemas = client.search_instances(
        "_ITSC_FORM_SCHEMA",
        fields=["instanceId", "name", "ITSC_FORM_VERSION.instanceId",
                "ITSC_FORM_VERSION.isMain"],
    )
    for schema in schemas:
        form_id = schema.get("instanceId")
        if not form_id:
            continue
        versions = schema.get("ITSC_FORM_VERSION") or []
        # 取主版本；若无主版本则跳过该表单
        main_versions = [v for v in versions if v.get("isMain") is True]
        if not main_versions:
            continue
        for ver in main_versions:
            version_id = ver.get("instanceId")
            if not version_id:
                continue
            rows.append({
                "模块": "ITSM",
                "类别": "表单",
                "名称": schema.get("name") or form_id,
                "URL": _url_itsc_form(host, form_id, version_id),
                "描述": schema.get("category") or schema.get("memo") or "",
            })
    logger.info(f"[ITSM-表单] 生成 {len(rows)} 条 (主版本)")
    return rows


def collect_itsc_duty_group(client: EasyOpsClient, host: str) -> List[Dict]:
    """ITSM - 值班组"""
    rows = []
    insts = client.search_instances("_ITSC_DUTY_GROUP_V2@EASYOPS")
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "ITSM",
            "类别": "值班组",
            "名称": ins.get("name") or iid,
            "URL": _url_itsc_duty_group(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[ITSM-值班组] 生成 {len(rows)} 条")
    return rows


def collect_itsc_sla(client: EasyOpsClient, host: str) -> List[Dict]:
    """ITSM - SLA（只取 status=enabled）"""
    rows = []
    insts = client.search_instances("_ITSC_SLA_RULE", query={"status": "enabled"})
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "ITSM",
            "类别": "SLA",
            "名称": ins.get("name") or iid,
            "URL": _url_itsc_sla(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[ITSM-SLA] 生成 {len(rows)} 条 (status=enabled)")
    return rows


def collect_itsc_trigger(client: EasyOpsClient, host: str) -> List[Dict]:
    """ITSM - 触发器（只取 status=enabled）"""
    rows = []
    insts = client.search_instances("_ITSC_TRIGGER", query={"status": "enabled"})
    for ins in insts:
        iid = ins.get("instanceId")
        if not iid:
            continue
        rows.append({
            "模块": "ITSM",
            "类别": "触发器",
            "名称": ins.get("name") or iid,
            "URL": _url_itsc_trigger(host, iid),
            "描述": ins.get("description") or ins.get("memo") or "",
        })
    logger.info(f"[ITSM-触发器] 生成 {len(rows)} 条 (status=enabled)")
    return rows


# -----------------------------------------------------------------------------
# CSV 输出
# -----------------------------------------------------------------------------

def write_csv(rows: List[Dict], output_path: str):
    """
    将汇总记录写入 CSV（UTF-8 BOM，便于 Excel 直接打开）

    :param rows: 记录列表
    :param output_path: 输出文件路径
    """
    import os
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for r in rows:
            # 描述中可能含换行，清洗为单行
            r = {k: str(v).replace("\n", " ").replace("\r", " ").strip() for k, v in r.items()}
            writer.writerow(r)
    logger.info(f"CSV 已写入: {output_path}（共 {len(rows)} 条）")


# -----------------------------------------------------------------------------
# 成果导出（JSON）：每类成果的完整定义按 目录/中文名_v版本_id.json 落盘
# 设计：
#   - cmdb 模型走 model_get_detail（GET /object/{objectId}，含继承属性/关系/视图）
#   - 其余 5 类走 search_instances(fields=["*"])，实例即完整定义
#   - 文件名：{中文名}_v{_version}_{id短}.json（清洗非法字符，防重名）
#   - 每个 JSON 顶部附 _export_meta_（名称/版本/前端URL/来源），便于交付阅读
# -----------------------------------------------------------------------------

# 文件名非法字符（Windows/Linux 通用）
_FILENAME_ILLEGAL = '/\\:*?"<>|\t\n\r'


def _safe_filename(name: Any, max_len: int = 60) -> str:
    """清洗成安全文件名片段：非法字符→下划线，连续空白压缩，限长"""
    if not name:
        return ""
    name = str(name)
    for ch in _FILENAME_ILLEGAL:
        name = name.replace(ch, "_")
    name = "_".join(name.split())  # 任意空白（含全角空格/制表符）压缩为单下划线
    if len(name) > max_len:
        name = name[:max_len]
    return name.strip("._") or ""


def _version_tag(d: Dict) -> str:
    """取版本号字符串（统一用 VERSION_FIELD，无则空串）"""
    v = d.get(VERSION_FIELD)
    if v is None or v == "":
        return ""
    return f"v{v}"


def _short_id(s: Any, n: int = 8) -> str:
    """取标识符前 n 位（文件名防重名用）"""
    if s is None or s == "":
        return ""
    return str(s)[:n]


def _build_filename(name: str, version: str, id_short: str,
                    ext: str = "json") -> str:
    """组装文件名：{name}_{version}_{id_short}.{ext}，各段缺失则省略"""
    parts = [_safe_filename(name), version, id_short]
    fname = "_".join(p for p in parts if p)
    return f"{fname or 'unnamed'}.{ext}"


def write_json(path: str, data: Any):
    """将数据以 UTF-8、缩进 2、中文不转义写入 JSON 文件"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_export_file(out_dir: str, name: str, version: str,
                       id_short: str, meta: Dict, payload: Dict) -> str:
    """落盘单个成果：{out_dir}/{文件名}，顶部附 _export_meta_"""
    fname = _build_filename(name, version, id_short)
    path = os.path.join(out_dir, fname)
    write_json(path, {"_export_meta_": meta, **payload})
    return path


def _guess_ext(resp) -> str:
    """按 Content-Type / magic bytes 猜压缩包扩展名（平台返回格式不一：tar.gz/zip/tar）"""
    ct = (resp.headers.get("Content-Type") or "").lower()
    body = resp.content or b""
    if body[:2] == b"\x1f\x8b" or "gzip" in ct or "compressed-tar" in ct:
        return "tar.gz"
    if body[:4] == b"PK\x03\x04" or "zip" in ct:
        return "zip"
    if len(body) > 262 and body[257:262] == b"ustar":
        return "tar"
    return "bin"


def _write_binary(path: str, content: bytes):
    """写入二进制文件（压缩包）"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _write_index(out_dir: str, title: str, entries: List[Dict]):
    """写目录索引 _索引.md：汇总该目录每个导出物（名称/版本/URL/文件名/大小），便于交付查阅"""
    if not entries:
        return
    lines = [f"# {title}（共 {len(entries)} 个）", "",
             "| 名称 | 版本 | 前端URL | 文件 | 大小 |",
             "|---|---|---|---|---|"]
    for e in entries:
        size = e.get("大小")
        size_kb = f"{size / 1024:.1f}KB" if size else "-"
        lines.append(
            f"| {e.get('名称', '')} | {e.get('版本', '')} | "
            f"{e.get('前端URL', '')} | `{e.get('文件名', '')}` | {size_kb} |")
    with open(os.path.join(out_dir, "_索引.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"[导出-{title}] 索引 → {os.path.join(out_dir, '_索引.md')}")


def _download_export(client: EasyOpsClient, method: str, path: str, port: int,
                     out_dir: str, name: str, version: str, id_short: str,
                     meta: Dict, **kw) -> Optional[Dict]:
    """
    调平台导出接口下载压缩包，按 {name}_v{ver}_{id}.{ext} 落盘。

    文件名用实例中文 name（平台 Content-Disposition 的中文是 latin1 编码乱码，不可用）；
    扩展名按返回体自动判断（_guess_ext）。返回索引条目（含文件名/大小），失败返回 None。
    """
    try:
        resp = client._request(method, path, port=port, **kw)
    except Exception as e:
        logger.warning(f"[导出] {name} 下载失败 ({path}): {e}")
        return None
    content = resp.content or b""
    if not content:
        logger.warning(f"[导出] {name} 返回空内容 ({path})")
        return None
    fname = _build_filename(name, version, id_short, ext=_guess_ext(resp))
    _write_binary(os.path.join(out_dir, fname), content)
    entry = dict(meta)
    entry["文件名"] = fname
    entry["大小"] = len(content)
    return entry


def export_cmdb_models(client: EasyOpsClient, host: str) -> int:
    """
    导出全部可见 CMDB 模型的完整定义（含继承属性/关系/视图）到 exports/CMDB模型/。

    用 model_get_detail（GET /object/{objectId}）逐个取详情——相比 model_export
    (POST /v2/object_export) 它包含继承自父模型的属性，避免继承模型（@ONEMODEL
    体系，自身不定义字段）导出成空壳。
    """
    out_dir = os.path.join(EXPORT_DIR, "CMDB模型")
    basics = client.list_object_basic(visible="visible")
    object_ids = [m["objectId"] for m in basics if m.get("objectId")]
    name_map = {m.get("objectId"): m.get("name") for m in basics}
    logger.info(f"[导出-CMDB模型] 待导出 {len(object_ids)} 个模型")

    entries = []
    for idx, oid in enumerate(object_ids, 1):
        try:
            resp = client._request("GET", f"object/{oid}", port=PORT_CMDB).json()
        except Exception as e:
            logger.warning(f"[导出-CMDB模型] {oid} 详情获取失败: {e}")
            continue
        if resp.get("code") != 0:
            logger.warning(f"[导出-CMDB模型] {oid} code={resp.get('code')} {resp.get('message')}")
            continue
        m = resp.get("data") or {}
        if not m.get("objectId"):
            continue
        name = m.get("name") or name_map.get(oid) or oid
        meta = {
            "名称": name,
            "模型ID": oid,
            "父模型": m.get("parentObjectId") or "",
            "版本": m.get(VERSION_FIELD),
            "属性数": len(m.get("attrList") or []),
            "关系数": len(m.get("relation_list") or []),
            "前端URL": _url_model_detail(host, oid),
            "导出来源": f"{client.host} (org={client.org})",
        }
        path = _write_export_file(out_dir, name, _version_tag(m), oid, meta, m)
        entries.append({**meta, "文件名": os.path.basename(path),
                        "大小": os.path.getsize(path)})
        if idx % 20 == 0:
            logger.info(f"[导出-CMDB模型] 进度 {idx}/{len(object_ids)}")
    _write_index(out_dir, "CMDB模型", entries)
    logger.info(f"[导出-CMDB模型] 写入 {len(entries)}/{len(object_ids)} 个 → {out_dir}")
    return len(entries)


def export_tool_packages(client: EasyOpsClient, host: str) -> int:
    """
    导出全部工具的工具包到 exports/工具/。

    接口：GET :8181/tools/{toolId}/export（无参=最新版本，返回 .tar.gz）。
    """
    out_dir = os.path.join(EXPORT_DIR, "工具")
    tools = client.search_instances("_TOOL_CONFIG@EASYOPS")
    entries = []
    for t in tools:
        tid = t.get("toolId")
        if not tid:
            continue
        name = t.get("name") or tid
        meta = {"名称": name, "工具ID": tid, "版本": t.get(VERSION_FIELD),
                "前端URL": _url_tool(host, tid),
                "导出来源": f"{client.host} (org={client.org})"}
        entry = _download_export(
            client, "GET", f"tools/{tid}/export", PORT_TOOL,
            out_dir, name, _version_tag(t), _short_id(tid), meta)
        if entry:
            entries.append(entry)
    _write_index(out_dir, "工具", entries)
    logger.info(f"[导出-工具] 写入 {len(entries)}/{len(tools)} 个 → {out_dir}")
    return len(entries)


def export_collector_plugins(client: EasyOpsClient, host: str,
                             category_dir: str, sampler_type: str) -> int:
    """
    导出监控套件 / 资源自动发现套件到 exports/<category_dir>/。

    接口：GET :8151/api/v1/plugin/export/{instanceId}（返回 .zip）。
    :param sampler_type: metric_sampler(监控套件) / process_sampler(资源自动发现套件)
    """
    out_dir = os.path.join(EXPORT_DIR, category_dir)
    plugins = client.search_instances(
        "_COLLECTOR_EASYOPS_PLUGIN", query={"samplerType": sampler_type})
    entries = []
    for p in plugins:
        iid = p.get("instanceId")
        if not iid:
            continue
        name = p.get("name") or iid
        meta = {"名称": name, "套件ID": iid, "版本": p.get(VERSION_FIELD),
                "packageVersion": p.get("packageVersion") or "",
                "前端URL": _url_monitor_kit(host, iid),
                "导出来源": f"{client.host} (org={client.org})"}
        entry = _download_export(
            client, "GET", f"api/v1/plugin/export/{iid}", PORT_COLLECTOR_PLUGIN,
            out_dir, name, _version_tag(p), _short_id(iid), meta)
        if entry:
            entries.append(entry)
    _write_index(out_dir, category_dir, entries)
    logger.info(f"[导出-{category_dir}] 写入 {len(entries)}/{len(plugins)} 个 → {out_dir}")
    return len(entries)


def export_inspection_suites(client: EasyOpsClient, host: str) -> int:
    """
    导出全部巡检套件到 exports/巡检套件/。

    接口：GET :8103/api/v1/inspection-export/{pluginId}（返回 .tar.gz）。
    """
    out_dir = os.path.join(EXPORT_DIR, "巡检套件")
    suites = client.search_instances("INSPECTION_INFO@EASYOPS")
    entries = []
    for s in suites:
        pid = s.get("id")
        if not pid:
            continue
        name = s.get("name") or pid
        meta = {"名称": name, "套件ID": pid, "版本": s.get(VERSION_FIELD),
                "前端URL": _url_inspection_suite(host, pid),
                "导出来源": f"{client.host} (org={client.org})"}
        entry = _download_export(
            client, "GET", f"api/v1/inspection-export/{pid}", PORT_INSPECTION,
            out_dir, name, _version_tag(s), pid, meta)
        if entry:
            entries.append(entry)
    _write_index(out_dir, "巡检套件", entries)
    logger.info(f"[导出-巡检套件] 写入 {len(entries)}/{len(suites)} 个 → {out_dir}")
    return len(entries)


def export_itsc_services(client: EasyOpsClient, host: str) -> int:
    """
    导出全部 ITSM 服务到 exports/ITSM服务/。

    接口：GET :8134/api/flowable_service/v1/export/service_instance
         ?instanceIds=<id>&isMain=true（返回 .tar.gz，含流程/表单/绑定/脚本）。
    """
    out_dir = os.path.join(EXPORT_DIR, "ITSM服务")
    services = client.search_instances("_ITSC_SERVICE_INSTANCE")
    entries = []
    for s in services:
        iid = s.get("instanceId")
        if not iid:
            continue
        name = s.get("name") or iid
        meta = {"名称": name, "服务ID": iid, "版本": s.get(VERSION_FIELD),
                "前端URL": _url_itsc_service(host, iid),
                "导出来源": f"{client.host} (org={client.org})"}
        entry = _download_export(
            client, "GET", "api/flowable_service/v1/export/service_instance",
            PORT_FLOWABLE, out_dir, name, _version_tag(s), _short_id(iid), meta,
            params={"instanceIds": iid, "isMain": "true"})
        if entry:
            entries.append(entry)
    _write_index(out_dir, "ITSM服务", entries)
    logger.info(f"[导出-ITSM服务] 写入 {len(entries)}/{len(services)} 个 → {out_dir}")
    return len(entries)


# -----------------------------------------------------------------------------
# 主流程编排
# -----------------------------------------------------------------------------

def main():
    """编排 EasyOps 平台交付成果汇总流程"""
    # 目标环境：留空(默认)则从 agent 配置读取（平台内网部署时自动获取）；
    # 沙箱/外部运行可设环境变量 EASYOPS_HOST / EASYOPS_ORG 指定目标环境。
    host = os.environ.get("EASYOPS_HOST") or None
    org = os.environ.get("EASYOPS_ORG") or None
    client = EasyOpsClient(
        host=host, org=org,           # 内网模式；不指定则自动从 agent 配置获取
        # ak=AK, sk=SK                # 如需 OpenAPI 方式
    )
    host = client.host

    all_rows: List[Dict] = []

    # ---- CMDB ----
    all_rows += collect_cmdb_models(client, host)
    all_rows += collect_cmdb_instance_list(client, host)
    all_rows += collect_cmdb_topology(client, host)
    all_rows += collect_cmdb_relation_query(client, host)
    all_rows += collect_cmdb_data_quality(client, host)
    # 资源自动发现套件 / 采集任务（CMDB 模块）
    all_rows += _collect_collector_plugin(
        client, host, "process_sampler", "CMDB", "资源自动发现套件", _url_monitor_kit)
    all_rows += _collect_collector_job(
        client, host, "process_sampler", "CMDB", "资源自动发现采集任务", _url_auto_discovery_task)

    # ---- 监控 ----
    all_rows += _collect_collector_plugin(
        client, host, "metric_sampler", "监控", "监控套件", _url_monitor_kit)
    all_rows += _collect_collector_job(
        client, host, "metric_sampler", "监控", "监控采集任务", _url_collect_strategy)
    all_rows += collect_alert_rules(client, host)

    # ---- 自动化 ----
    all_rows += collect_tool(client, host)
    all_rows += collect_flow(client, host)
    all_rows += collect_scheduler_task(client, host)
    all_rows += collect_inspection_suite(client, host)
    all_rows += collect_inspection_task(client, host)

    # ---- ITSM ----
    all_rows += collect_itsc_service(client, host)
    all_rows += collect_itsc_process(client, host)
    all_rows += collect_itsc_form(client, host)
    all_rows += collect_itsc_duty_group(client, host)
    all_rows += collect_itsc_sla(client, host)
    all_rows += collect_itsc_trigger(client, host)

    # 输出 CSV 汇总
    write_csv(all_rows, OUTPUT_CSV)

    # 导出成果实体（分目录）：cmdb模型(JSON) + 工具/监控套件/资源自动发现套件/巡检套件/ITSM服务(平台导出接口压缩包)
    export_total = 0
    if ENABLE_EXPORT:
        logger.info("====== 开始导出成果实体 ======")
        export_total += export_cmdb_models(client, host)                              # JSON
        export_total += export_tool_packages(client, host)                            # .tar.gz
        export_total += export_collector_plugins(client, host, "监控套件", "metric_sampler")          # .zip
        export_total += export_collector_plugins(client, host, "资源自动发现套件", "process_sampler")  # .zip
        export_total += export_inspection_suites(client, host)                        # .tar.gz
        export_total += export_itsc_services(client, host)                            # .tar.gz
        print(f"成果导出完成，共 {export_total} 个文件 → {EXPORT_DIR}")

    print(f"\n汇总完成：CSV 共 {len(all_rows)} 条交付成果 → {OUTPUT_CSV}"
          + (f"；成果实体 {export_total} 个 → {EXPORT_DIR}" if ENABLE_EXPORT else ""))


if __name__ == "__main__":
    main()
