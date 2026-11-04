#!/usr/bin/env python3
"""
实例字段同步脚本

从源模型实例读取属性/关系数据，同步到目标模型实例。

支持场景：
- 属性同步：ip → ip（直接复制属性值）
- 关系同步：owner → owner（提取 instanceId 列表）
- 多层关系同步：serviceSets.system → target_rel（展平嵌套关系）
- 多层关系属性同步：serviceSets.system.name → target_attr（展平并聚合）

聚合模式（属性多值场景）：
- first: 取第一个值（默认）
- join: 字符串拼接
- add/sum: 求和
- avg: 平均值
- max: 最大值
- min: 最小值
- count: 计数

使用方式：修改 main() 中的 SYNC_CONFIG 配置后运行
"""

import requests
import json
import logging
import time
import platform
import hashlib
import hmac
import yaml
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlencode

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
                    f"端口 {port} 未在 PORT_APP_MAP 中配置"
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

    def search_instance(self, model_id: str, fields: list = None,
                        query: dict = None, page_size: int = 1000) -> list:
        """
        搜索实例（自动翻页）

        API: PostSearchV3WithAdmin
        服务: logic.cmdb.service (port 8079)

        :param model_id: 模型 ID
        :param fields: 返回字段列表，支持点号分隔的多层路径
        :param query: 查询条件
        :param page_size: 每页大小
        :return: 实例列表
        """
        port = 8079
        path = f"v3/object/{model_id}/instance/_search"
        data = {
            'fields': fields or ['*'],
            'query': query or {},
            'page_size': page_size
        }
        instances = []
        for page in range(1, 10000):
            data['page'] = page
            resp = self._request('POST', path, port=port, data=data).json()
            items = resp.get('data', {}).get('list', [])
            instances.extend(items)
            if len(items) < page_size:
                break
        logger.info(f"搜索到 {len(instances)} 个 {model_id} 实例")
        return instances

    def import_instance(self, object_id: str, data_list: list,
                        keys: list, batch_size: int = 1000) -> dict:
        """
        批量导入实例（upsert 语义）

        API: PostImportInstanceApi
        服务: logic.cmdb.service (port 8079)

        :param object_id: 模型 ID
        :param data_list: 数据列表
        :param keys: 唯一键列表
        :param batch_size: 批量大小
        :return: 导入结果统计
        """
        port = 8079
        path = f"object/{object_id}/instance/_import"
        total_insert = 0
        total_update = 0
        total_failed = 0

        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            body = {"keys": keys, "datas": batch}
            result = self._request("POST", path, port=port, data=body).json()
            result_data = result.get("data", {})
            insert = result_data.get("insert_count", 0)
            update = result_data.get("update_count", 0)
            failed = result_data.get("failed_count", 0)
            total_insert += insert
            total_update += update
            total_failed += failed
            logger.info(
                f"批次 {i // batch_size + 1}: "
                f"新增 {insert}, 更新 {update}, 失败 {failed}"
            )
        return {
            "insert_count": total_insert,
            "update_count": total_update,
            "failed_count": total_failed
        }


# =============================================================================
# 数据处理函数
# =============================================================================

def extract_field_value(instance: dict, field_path: str) -> list:
    """
    从实例数据中按点分隔路径提取值。

    支持多级关系路径，自动展平嵌套列表。

    :param instance: 实例数据
    :param field_path: 字段路径，如 "ip", "owner", "serviceSets.system.name"
    :return: 展平后的值列表

    示例::

        # 属性: extract_field_value(inst, "ip") -> ["192.168.1.1"]
        # 关系: extract_field_value(inst, "owner") -> [{"instanceId": "xxx", ...}]
        # 多层关系: extract_field_value(inst, "serviceSets.system")
        #     -> [{"instanceId": "yyy", "name": "zzz"}, ...]
        # 多层属性: extract_field_value(inst, "serviceSets.system.name")
        #     -> ["电商交易系统", "测试系统1"]
    """
    segments = field_path.split('.')
    current = [instance]

    for segment in segments:
        next_values = []
        for item in current:
            if isinstance(item, dict):
                val = item.get(segment)
                if val is None:
                    continue
                if isinstance(val, list):
                    next_values.extend(val)
                else:
                    next_values.append(val)
        current = next_values

    return current


def is_relationship_data(values: list) -> bool:
    """
    判断提取的值是否为关系数据。

    关系数据特征：所有元素都是包含 instanceId 的字典。

    :param values: 提取的值列表
    :return: 是否为关系数据
    """
    if not values:
        return False
    return all(isinstance(v, dict) and 'instanceId' in v for v in values)


def aggregate_values(values: list, mode: str = "first",
                     separator: str = "") -> Any:
    """
    对多值属性进行聚合。

    :param values: 值列表
    :param mode: 聚合模式
        - first: 取第一个值（默认）
        - join: 字符串拼接
        - add/sum: 求和
        - avg: 平均值
        - max: 最大值
        - min: 最小值
        - count: 计数
        - lambda:表达式: 自定义表达式，x 为值列表
    :param separator: join 模式的分隔符，默认空字符串
    :return: 聚合后的值
    """
    if not values:
        return None

    if mode == "first":
        return values[0]
    elif mode == "join":
        return separator.join(str(v) for v in values)
    elif mode in ("add", "sum"):
        return sum(float(v) for v in values)
    elif mode == "avg":
        return sum(float(v) for v in values) / len(values)
    elif mode == "max":
        return max(float(v) for v in values)
    elif mode == "min":
        return min(float(v) for v in values)
    elif mode == "count":
        return len(values)
    elif mode.startswith("lambda:"):
        expr = mode[7:]
        x = values
        return eval(expr)
    else:
        raise ValueError(
            f"不支持的聚合模式: {mode}，"
            f"可选: first/join/add/sum/avg/max/min/count/lambda:表达式"
        )


def transform_value(values: list, field_type: str,
                    multi_value_mode: str = "first") -> Any:
    """
    将提取的原始值转换为目标写入格式。

    :param values: 提取的原始值列表
    :param field_type: 字段类型，"relation" 或 "attribute"
    :param multi_value_mode: 属性多值聚合模式
    :return: 转换后的值
        - 关系: ["instanceId1", "instanceId2", ...]
        - 属性: 聚合后的标量值
    """
    if not values:
        return [] if field_type == "relation" else None

    if field_type == "relation":
        return [v["instanceId"] for v in values if isinstance(v, dict)]
    else:
        return aggregate_values(values, multi_value_mode)


def detect_field_type(instances: list, field_path: str,
                      force_type: str = None) -> str:
    """
    从实例数据中检测字段类型。

    遍历所有实例，找到第一个非空值来判断类型。
    如果所有值都为空或无法判断，使用 force_type 参数。

    :param instances: 实例列表
    :param field_path: 字段路径
    :param force_type: 强制指定类型，"relation" 或 "attribute"
    :return: "relation" 或 "attribute"
    """
    if force_type in ("relation", "attribute"):
        return force_type

    for inst in instances:
        values = extract_field_value(inst, field_path)
        if values:
            if is_relationship_data(values):
                return "relation"
            else:
                return "attribute"

    # 无法从数据判断，默认 attribute
    logger.warning(f"无法从数据判断字段类型，默认为 attribute。"
                   f"可通过 force_field_type 参数指定。")
    return "attribute"


# =============================================================================
# 核心同步逻辑
# =============================================================================

def sync_instances(client: EasyOpsClient, config: dict) -> dict:
    """
    执行实例字段同步。

    从源模型实例读取字段值，转换格式后写入目标模型实例。

    :param client: EasyOps API 客户端
    :param config: 同步配置字典，包含以下字段：
        - source_model_id (str): 源模型 ID
        - source_field (str): 源字段路径（支持点号分隔的多层路径）
        - source_key (str): 源模型唯一键
        - target_model_id (str, 可选): 目标模型 ID，默认等于源
        - target_field (str, 可选): 目标字段，默认等于源
        - target_key (str, 可选): 目标唯一键，默认等于源
        - multi_value_mode (str, 可选): 多值聚合模式，默认 "first"
        - force_field_type (str, 可选): 强制字段类型 "relation"/"attribute"
        - query (dict, 可选): 源实例查询条件
    :return: 同步结果统计
    """
    source_model = config["source_model_id"]
    source_field = config["source_field"]
    source_key = config["source_key"]
    target_model = config.get("target_model_id", source_model)
    target_field = config.get("target_field", source_field)
    target_key = config.get("target_key", source_key)
    multi_mode = config.get("multi_value_mode", "first")
    force_type = config.get("force_field_type")
    query = config.get("query")

    logger.info("=" * 60)
    logger.info(f"同步配置:")
    logger.info(f"  源: {source_model}.{source_field} (key: {source_key})")
    logger.info(f"  目标: {target_model}.{target_field} (key: {target_key})")
    logger.info(f"  多值模式: {multi_mode}")
    logger.info("=" * 60)

    # 1. 搜索源实例
    search_fields = list(set([source_field, source_key, "instanceId"]))
    instances = client.search_instance(
        source_model, fields=search_fields, query=query
    )

    if not instances:
        logger.warning("未搜索到源实例，同步结束")
        return {"total": 0, "synced": 0, "skipped": 0}

    # 2. 检测字段类型
    field_type = detect_field_type(instances, source_field, force_type)
    type_label = "关系" if field_type == "relation" else "属性"
    logger.info(f"检测到字段类型: {type_label}")

    # 3. 提取、转换数据
    import_data = []
    stats = {"total": len(instances), "synced": 0, "skipped": 0, "details": []}

    for inst in instances:
        key_value = inst.get(source_key)
        if not key_value:
            logger.debug(f"跳过: 实例 {inst.get('instanceId', '?')} 缺少 {source_key}")
            stats["skipped"] += 1
            continue

        # 提取字段值
        values = extract_field_value(inst, source_field)

        # 转换为目标格式
        transformed = transform_value(values, field_type, multi_mode)

        if transformed is None:
            logger.debug(f"跳过: {source_key}={key_value}, 字段值为空")
            stats["skipped"] += 1
            continue

        import_data.append({
            target_key: key_value,
            target_field: transformed
        })
        stats["synced"] += 1
        stats["details"].append({
            source_key: key_value,
            "raw_count": len(values),
            "value": transformed
        })

    # 4. 打印预览
    logger.info(f"数据提取完成: {stats['synced']} 条有效, {stats['skipped']} 条跳过")
    for detail in stats["details"][:5]:
        logger.info(f"  {source_key}={detail[source_key]}, "
                    f"原始{detail['raw_count']}个值 → {detail['value']}")
    if len(stats["details"]) > 5:
        logger.info(f"  ... 共 {len(stats['details'])} 条")

    # 5. 导入到目标模型
    if import_data:
        result = client.import_instance(target_model, import_data, keys=[target_key])
        stats["import_result"] = result
        logger.info(f"导入结果: 新增 {result['insert_count']}, "
                    f"更新 {result['update_count']}, "
                    f"失败 {result['failed_count']}")
    else:
        logger.warning("无有效数据需要导入")

    # 清理 details 避免返回过大
    stats.pop("details", None)
    return stats

def sync_instances_multi(client: EasyOpsClient, config: dict) -> dict:
    """
    多字段实例同步。

    从源模型实例批量读取多个字段值，自动识别属性/关系类型，
    转换格式后写入目标模型实例。

    :param client: EasyOps API 客户端
    :param config: 同步配置字典，包含以下字段：
        - source_model_id (str): 源模型 ID
        - source_unique_key (str): 源唯一键字段
        - target_model_id (str, 可选): 目标模型 ID，默认等于源
        - target_unique_key (str, 可选): 目标唯一键，默认等于源
        - fields (list): 字段映射列表，每项为 dict:
            - source (str): 源字段路径（支持点号分隔多层）
            - target (str, 可选): 目标字段，默认等于 source
            - aggregate (str, 可选): 聚合模式，默认自动检测
                关系字段默认 "list"，属性字段默认 "first"
                可选: first/join/list/add/sum/avg/max/min/count/lambda:表达式
            - separator (str, 可选): join 分隔符，默认空字符串
            - force_type (str, 可选): 强制类型 "relation"/"attribute"
        - query (dict, 可选): 源实例查询条件
    :return: 同步结果统计
    """
    source_model = config["source_model_id"]
    source_key = config["source_unique_key"]
    target_model = config.get("target_model_id", source_model)
    target_key = config.get("target_unique_key", source_key)
    field_configs = config["fields"]
    query = config.get("query")

    # 补全字段配置默认值
    for fc in field_configs:
        fc.setdefault("target", fc["source"])
        fc.setdefault("aggregate", None)
        fc.setdefault("separator", "")
        fc.setdefault("force_type", None)

    logger.info("=" * 60)
    logger.info("多字段同步配置:")
    logger.info(f"  源模型: {source_model}  唯一键: {source_key}")
    logger.info(f"  目标模型: {target_model}  唯一键: {target_key}")
    for fc in field_configs:
        logger.info(f"  {fc['source']} → {fc['target']} "
                     f"(aggregate={fc['aggregate'] or 'auto'})")
    logger.info("=" * 60)

    # 1. 搜索源实例
    search_fields = {source_key}
    for fc in field_configs:
        search_fields.add(fc["source"])
    instances = client.search_instance(
        source_model, fields=list(search_fields), query=query
    )

    if not instances:
        logger.warning("未搜索到源实例，同步结束")
        return {"total": 0, "synced": 0, "skipped": 0}

    # 2. 自动检测字段类型
    for fc in field_configs:
        field_type = detect_field_type(
            instances, fc["source"], fc["force_type"]
        )
        fc["_type"] = field_type
        if fc["aggregate"] is None:
            fc["aggregate"] = "list" if field_type == "relation" else "first"
        logger.info(f"  字段 {fc['source']}: "
                     f"类型={field_type}, 聚合={fc['aggregate']}")

    # 3. 提取、转换数据
    import_data = []
    stats = {"total": len(instances), "synced": 0, "skipped": 0}

    for inst in instances:
        key_value = inst.get(source_key)
        if not key_value:
            logger.debug(f"跳过: 实例 {inst.get('instanceId', '?')} "
                         f"缺少 {source_key}")
            stats["skipped"] += 1
            continue

        row = {target_key: key_value}

        for fc in field_configs:
            values = extract_field_value(inst, fc["source"])

            if fc["_type"] == "relation":
                # 关系数据: 提取 instanceId 列表
                ids = [v["instanceId"] for v in values
                       if isinstance(v, dict) and "instanceId" in v]
                if fc["aggregate"] == "list":
                    row[fc["target"]] = ids
                else:
                    row[fc["target"]] = aggregate_values(
                        ids, fc["aggregate"], fc["separator"]
                    )
            else:
                # 属性数据: 直接聚合
                row[fc["target"]] = aggregate_values(
                    values, fc["aggregate"], fc["separator"]
                )

        import_data.append(row)
        stats["synced"] += 1

    # 4. 打印预览
    logger.info(f"数据转换完成: {stats['synced']} 条有效, "
                f"{stats['skipped']} 条跳过")
    for row in import_data[:5]:
        logger.info(f"  {json.dumps(row, ensure_ascii=False)}")
    if len(import_data) > 5:
        logger.info(f"  ... 共 {len(import_data)} 条")

    # 5. 导入到目标模型
    if import_data:
        result = client.import_instance(
            target_model, import_data, keys=[target_key]
        )
        stats["import_result"] = result
        logger.info(f"导入结果: 新增 {result['insert_count']}, "
                     f"更新 {result['update_count']}, "
                     f"失败 {result['failed_count']}")
    else:
        logger.warning("无有效数据需要导入")

    return stats


if __name__ == "__main__":
    """
    主入口函数。

    修改 SYNC_CONFIG 配置后运行脚本。
    支持两种模式：
    - 多字段同步 (sync_instances_multi)：一次同步多个字段
    - 单字段同步 (sync_instances)：仅同步单个字段
    """
    # ==================== 多字段同步配置 ====================
    SYNC_CONFIG = {
        # 必填
        "source_model_id": "HOST",
        "source_unique_key": "ip",

        # 可选（不填则默认同源）
        "target_model_id": "TEST",
        "target_unique_key": "attr1",

        # 字段映射列表
        "fields": [
            # 场景1: 纯属性 → 自动检测，默认 first
            {"source": "ip",'target':'attr1'},
            # 场景2: 纯关系 → 自动检测，默认 list
            {"source": "owner",'target':'aa'},
            # 场景3: 多层关系 → 自动检测，默认 list
            {"source": "serviceSets.system",'target':'bb'},
            # 场景4: 多层关系+属性 → 自定义聚合
            {
                "source": "serviceSets.system.name",
                "target": "attr2",
                "aggregate": "join",
                "separator": ","
            },
        ],

        # 查询条件（可选）
        "query": {"ip": {"$like": "%192%"}},
    }
    # =================================================

    client = EasyOpsClient(host="192.168.110.25", org="888")
    result = sync_instances_multi(client, SYNC_CONFIG)
    print(json.dumps(result, ensure_ascii=False, indent=2))
