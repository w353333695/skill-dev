#!/usr/bin/env python3
"""
配置基线检查脚本

基于 EasyOps CMDB 平台的声明式规则引擎，从 CMDB 读取基线规则，
对目标实例执行合规检查，并将不合规结果写回 CMDB。

支持两种运行模式:
    1. 内网模式（Agent 部署环境）: 自动读取 agent 配置
    2. OpenAPI 模式: 使用 AK/SK 签名认证

使用方法:
    1. 配置参数（环境变量或脚本顶部配置区）
    2. 运行: python baseline_checker.py
"""

import re
import json
import time
import hashlib
import hmac
import logging
import platform
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Union
from urllib.parse import urlencode
from functools import wraps

import requests
import yaml

# =============================================================================
# 配置区域
# =============================================================================

# 基线规则实例 ID 列表，为空列表则检查全部规则
BASELINE_INSTANCEIDS = []

# 检查结果保留天数
RESULT_RETENTION_DAYS = 30

# OpenAPI 模式参数（不配置则使用内网模式）
EASYOPS_HOST = ""
EASYOPS_ORG = ""
EASYOPS_AK = ""
EASYOPS_SK = ""

# CMDB 模型 ID
RULE_MODEL_ID = "BASELINE_RULE@BASELINE"
RESULT_MODEL_ID = "BASELINE_RESULT@BASELINE"

# =============================================================================
# 日志配置
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("baseline_checker")


# =============================================================================
# EasyOps API 客户端
# =============================================================================

class EasyOpsClient:
    """EasyOps API 客户端，支持内网调用和 OpenAPI 签名认证"""

    # OpenAPI 端口到应用名的映射
    PORT_APP_MAP = {
        8079: "cmdbservice",
    }

    # 重试配置
    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 2, 4]  # 退避间隔（秒）

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
        with open(conf_path, "r") as f:
            dic = yaml.load(f, Loader=yaml.FullLoader)
        org = dic["base"]["client_id"]
        host = dic["command"]["server_groups"][0]["hosts"][0]["ip"].split(",")[0]
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
        发送 HTTP 请求，支持自动重试和双模式认证

        :param method: HTTP 方法
        :param path: API 路径
        :param port: 服务端口
        :return: requests.Response 对象
        """
        data = kwargs.pop("data", None)
        params = kwargs.pop("params", None)
        request_body = json.dumps(data) if data else None
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
            sign_params = self.__signature(
                method, uri, params=params, data=request_body or "{}"
            )
            url = url + "?" + urlencode(sign_params)
            params = None
            if method in ("GET", "DELETE"):
                headers.pop("Content-Type", None)
            headers.pop("org", None)
        else:
            # 内网模式：直接使用 host:port
            url = f"http://{self.host}:{port}/{path.lstrip('/')}"

        # 带重试的请求
        last_exc = None
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.debug(
                    f">>> [{'OpenAPI' if self.is_openapi else '内网'}] "
                    f"{method} {url} (尝试 {attempt + 1}/{self.MAX_RETRIES})"
                )
                logger.debug(f">>> Body: {request_body[:2000] if request_body else 'None'}")
                response = requests.request(
                    method=method, url=url, headers=headers,
                    data=request_body, params=params, timeout=30, **kwargs
                )
                logger.debug(f"<<< Status: {response.status_code}")
                logger.debug(f"<<< Response: {response.text[:2000]}")
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.RETRY_BACKOFF[attempt]
                    logger.warning(f"请求失败: {e}，{wait}s 后重试...")
                    time.sleep(wait)
                else:
                    logger.error(f"请求失败，已达最大重试次数: {e}")
        raise last_exc

    def search_instance(self, object_id: str, query: Dict = None,
                        fields: List[str] = None,
                        page_size: int = 200) -> List[Dict]:
        """
        分页查询实例

        API: PostSearchV3WithAdmin
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param query: 查询条件
        :param fields: 返回字段列表
        :param page_size: 每页大小
        :return: 实例列表
        """
        port = 8079
        path = f"v3/object/{object_id}/instance/_search"
        data = {
            "fields": fields or ["*"],
            "query": query or {},
            "page": 1,
            "page_size": page_size
        }
        instances = []
        for page in range(1, 10000):
            data["page"] = page
            response = self._request("POST", path, port=port, data=data)
            batch = response.json()["data"]["list"]
            instances.extend(batch)
            if len(batch) < page_size:
                break
        if instances:
            logger.info(f"查询到 {len(instances)} 个 {object_id} 实例")
        else:
            logger.info(f"未查询到 {object_id} 实例，查询条件: {data['query']}")
        return instances

    def import_instance(self, object_id: str, data_list: List[Dict],
                        keys: List[str], batch_size: int = 1000) -> Dict:
        """
        批量导入实例

        API: PostImportInstanceApi
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param data_list: 数据列表
        :param keys: 唯一键
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
            data = {"keys": keys, "datas": batch}
            result = self._request("POST", path, port=port, data=data).json()
            result_data = result.get("data", {})
            total_insert += result_data.get("insert_count", 0)
            total_update += result_data.get("update_count", 0)
            total_failed += result_data.get("failed_count", 0)
            logger.info(
                f"导入批次 {i // batch_size + 1}: "
                f"新增 {result_data.get('insert_count', 0)}, "
                f"更新 {result_data.get('update_count', 0)}, "
                f"失败 {result_data.get('failed_count', 0)}"
            )

        return {
            "insert_count": total_insert,
            "update_count": total_update,
            "failed_count": total_failed
        }

    def delete_instance_batch(self, object_id: str, instance_ids: List[str],
                              batch_size: int = 1000) -> Dict:
        """
        批量删除实例

        API: DeleteInstanceBatch
        服务: logic.cmdb.service
        端口: 8079

        :param object_id: 模型 ID
        :param instance_ids: 实例 ID 列表
        :param batch_size: 每批次数量
        :return: 删除结果统计
        """
        port = 8079
        path = f"object/{object_id}/instance/_batch"
        total_deleted = 0
        total_failed = 0

        for i in range(0, len(instance_ids), batch_size):
            batch = instance_ids[i:i + batch_size]
            params = {"instanceIds": ";".join(batch)}
            response = self._request("DELETE", path, port=port, params=params)
            result = response.json()
            if result.get("code") == 0:
                failed_list = result.get("data", {}).get("deleteFailedInstances", [])
                total_deleted += len(batch) - len(failed_list)
                total_failed += len(failed_list)
            else:
                total_failed += len(batch)
                logger.error(f"批量删除失败: {result.get('message')}")

        logger.info(f"删除 {object_id} 实例: 成功 {total_deleted}, 失败 {total_failed}")
        return {"deleted": total_deleted, "failed": total_failed}


# =============================================================================
# 预处理器
# =============================================================================

def preprocess_extract_number(value: str, arg: str = None) -> str:
    """提取字符串中的第一个数字（含小数点）

    示例: "v7.0" → "7.0", "内存 16GB" → "16"
    """
    match = re.search(r"[\d.]+", str(value))
    return match.group() if match else str(value)


def preprocess_extract_version(value: str, arg: str = None) -> str:
    """提取版本号（数字+点号组合）

    示例: "version 8.1.2-rc1" → "8.1.2", "CentOS 7.9.2009" → "7.9.2009"
    """
    match = re.search(r"[\d]+(?:\.[\d]+)*", str(value))
    return match.group() if match else str(value)


def preprocess_extract_regex(value: str, arg: str = None) -> str:
    """使用自定义正则提取第一个匹配

    :param arg: 正则表达式
    示例: arg=r"v(\\d+)", value="v7.0" → "7"（取第一个捕获组或整个匹配）
    """
    if not arg:
        logger.warning("extract_regex 预处理器缺少 preprocess_arg 参数")
        return str(value)
    match = re.search(arg, str(value))
    if not match:
        return str(value)
    # 优先返回第一个捕获组，否则返回整个匹配
    return match.group(1) if match.groups() else match.group()


def preprocess_strip(value: str, arg: str = None) -> str:
    """去除首尾空格"""
    return str(value).strip()


def preprocess_lower(value: str, arg: str = None) -> str:
    """转小写"""
    return str(value).lower()


def preprocess_upper(value: str, arg: str = None) -> str:
    """转大写"""
    return str(value).upper()


def preprocess_split_nth(value: str, arg: str = None) -> str:
    """按分隔符分割取第 N 段

    :param arg: 格式 "分隔符,N"（N 从 0 开始）
    示例: arg=",;1", value="a;b;c" → "b"
    注意: arg 的第一个字符为分隔符，逗号后为索引
    """
    if not arg or "," not in arg:
        logger.warning(f"split_nth 预处理器参数格式错误: {arg}，期望格式: '分隔符,N'")
        return str(value)
    # 第一个逗号前为分隔符，逗号后为索引
    sep_end = arg.index(",")
    sep = arg[:sep_end]
    try:
        idx = int(arg[sep_end + 1:])
    except ValueError:
        logger.warning(f"split_nth 索引不是整数: {arg}")
        return str(value)
    parts = str(value).split(sep)
    if 0 <= idx < len(parts):
        return parts[idx]
    logger.warning(f"split_nth 索引 {idx} 超出范围，共 {len(parts)} 段")
    return str(value)


# 预处理器注册表
PREPROCESSORS = {
    "extract_number": preprocess_extract_number,
    "extract_version": preprocess_extract_version,
    "extract_regex": preprocess_extract_regex,
    "strip": preprocess_strip,
    "lower": preprocess_lower,
    "upper": preprocess_upper,
    "split_nth": preprocess_split_nth,
}


def apply_preprocess(value: Any, preprocess: Union[str, List[str], None],
                     preprocess_arg: str = None) -> Any:
    """
    对值应用预处理器，支持链式处理

    :param value: 原始值
    :param preprocess: 预处理器名称（字符串或列表）
    :param preprocess_arg: 预处理器参数（仅对最后一个需要参数的预处理器生效）
    :return: 处理后的值
    """
    if not preprocess:
        return value

    # 统一为列表
    if isinstance(preprocess, str):
        preprocess = [preprocess]

    for proc_name in preprocess:
        func = PREPROCESSORS.get(proc_name)
        if not func:
            logger.error(f"不支持的预处理器: {proc_name}，跳过")
            continue
        original = value
        try:
            value = func(str(value), preprocess_arg)
            logger.debug(f"预处理 {proc_name}: '{original}' → '{value}'")
        except Exception as e:
            logger.warning(f"预处理器 {proc_name} 执行失败: {e}，使用原始值")
    return value


# =============================================================================
# 操作符
# =============================================================================

def _compare_version(v1: str, v2: str) -> int:
    """
    语义化版本比较

    按 . 分割后逐段比较整数值，缺失段视为 0。
    返回: 正数(v1>v2), 0(相等), 负数(v1<v2)
    """
    def to_parts(v):
        parts = []
        for p in str(v).split("."):
            try:
                parts.append(int(p))
            except ValueError:
                # 处理非数字部分，如 "rc1"
                num = re.match(r"(\d+)", p)
                parts.append(int(num.group(1)) if num else 0)
        return parts

    parts1 = to_parts(v1)
    parts2 = to_parts(v2)
    # 补齐长度
    max_len = max(len(parts1), len(parts2))
    parts1.extend([0] * (max_len - len(parts1)))
    parts2.extend([0] * (max_len - len(parts2)))

    for a, b in zip(parts1, parts2):
        if a != b:
            return a - b
    return 0


def _is_empty_value(value: Any) -> bool:
    """判断值是否为空: None、空字符串、空列表"""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def evaluate_condition(actual_value: Any, op: str, expected_value: Any) -> bool:
    """
    执行单个条件判断

    :param actual_value: 实例的实际属性值（已预处理）
    :param op: 操作符
    :param expected_value: 规则中定义的期望值
    :return: 条件是否满足
    """
    # 空值判断（不需要转换类型）
    if op == "is_empty":
        return _is_empty_value(actual_value)
    if op == "is_not_empty":
        return not _is_empty_value(actual_value)

    # 如果实际值为空，非空值判断类操作符一律不通过
    if _is_empty_value(actual_value):
        return False

    actual_str = str(actual_value)

    # 数值比较
    if op in ("gt", "gte", "lt", "lte"):
        try:
            a = float(actual_str)
            b = float(expected_value)
        except (ValueError, TypeError):
            logger.warning(f"数值比较类型转换失败: actual={actual_str}, expected={expected_value}")
            return False
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b

    # 版本比较
    if op in ("version_gt", "version_gte", "version_lt", "version_lte"):
        cmp = _compare_version(actual_str, str(expected_value))
        if op == "version_gt":
            return cmp > 0
        if op == "version_gte":
            return cmp >= 0
        if op == "version_lt":
            return cmp < 0
        if op == "version_lte":
            return cmp <= 0

    # 字符串匹配
    if op == "eq":
        return actual_str == str(expected_value)
    if op == "neq":
        return actual_str != str(expected_value)
    if op == "contains":
        return str(expected_value) in actual_str
    if op == "not_contains":
        return str(expected_value) not in actual_str
    if op == "regex":
        try:
            return bool(re.search(str(expected_value), actual_str))
        except re.error as e:
            logger.error(f"正则表达式错误: {expected_value}, {e}")
            return False
    if op == "in":
        if not isinstance(expected_value, list):
            logger.warning(f"in 操作符期望 list 类型的 value，实际: {type(expected_value)}")
            return False
        return actual_str in [str(v) for v in expected_value]
    if op == "not_in":
        if not isinstance(expected_value, list):
            logger.warning(f"not_in 操作符期望 list 类型的 value，实际: {type(expected_value)}")
            return False
        return actual_str not in [str(v) for v in expected_value]

    logger.error(f"不支持的操作符: {op}")
    return False


# =============================================================================
# 嵌套属性取值
# =============================================================================

def get_nested_value(instance: Dict, attr_path: str) -> List[Any]:
    """
    从实例数据中按路径取值，支持嵌套和列表展开

    路径语法: attr1.attr2.attr3
    - 简单嵌套: 逐层取 dict key
    - 列表展开: 遇到 list[dict] 时自动轮巡，返回所有匹配值

    :param instance: 实例数据字典
    :param attr_path: 属性路径，如 "disks.usagePercent"
    :return: 取到的值列表（即使是单值也包装为列表）
    """
    parts = attr_path.split(".")
    # 当前层的候选值列表
    current = [instance]

    for part in parts:
        next_values = []
        for item in current:
            if isinstance(item, dict):
                val = item.get(part)
                if val is None:
                    # 属性不存在，保留 None 以便后续 is_empty 判断
                    next_values.append(None)
                elif isinstance(val, list):
                    # 列表展开：如果是 list[dict]，展开为多个候选值
                    if val and isinstance(val[0], dict):
                        next_values.extend(val)
                    else:
                        # 普通列表（如 list[str/int]），每个元素独立参与判断
                        next_values.extend(val)
                else:
                    next_values.append(val)
            elif isinstance(item, list):
                # 上一层已经是列表，继续展开
                for sub in item:
                    if isinstance(sub, dict):
                        val = sub.get(part)
                        if val is not None:
                            next_values.append(val)
                        else:
                            next_values.append(None)
            else:
                # 非 dict/list，无法继续取值
                next_values.append(None)
        current = next_values

    logger.debug(f"属性取值 '{attr_path}': {current}")
    return current


# =============================================================================
# 规则引擎
# =============================================================================

def check_condition(instance: Dict, condition: Dict) -> Tuple[bool, str]:
    """
    检查单个 condition 是否满足

    :param instance: 实例数据
    :param condition: 条件定义 {"attr": ..., "op": ..., "value": ..., "preprocess": ..., "preprocess_arg": ...}
    :return: (是否通过, 失败原因描述)
    """
    attr = condition.get("attr", "")
    op = condition.get("op", "")
    expected = condition.get("value")
    preprocess = condition.get("preprocess")
    preprocess_arg = condition.get("preprocess_arg")

    # 取属性值（可能是多个值）
    raw_values = get_nested_value(instance, attr)

    # 空值判断类操作符特殊处理
    if op in ("is_empty", "is_not_empty"):
        # 所有值都为空才算 is_empty 通过
        if op == "is_empty":
            passed = all(_is_empty_value(v) for v in raw_values)
        else:
            passed = any(not _is_empty_value(v) for v in raw_values)
        if not passed:
            return False, f"{attr} {op} 检查未通过"
        return True, ""

    # 对每个值执行预处理和条件判断
    failed_details = []
    for raw_val in raw_values:
        if _is_empty_value(raw_val):
            failed_details.append(f"{attr}=<空值>")
            continue

        # 预处理
        processed_val = apply_preprocess(raw_val, preprocess, preprocess_arg)
        logger.debug(f"条件判断: {attr}={processed_val} {op} {expected}")

        # 条件判断
        if not evaluate_condition(processed_val, op, expected):
            failed_details.append(f"{attr}={raw_val}")

    if failed_details:
        reason = f"{', '.join(failed_details)} 不满足 {op} {expected}"
        return False, reason

    return True, ""


def check_rule(instance: Dict, rule: Dict) -> Tuple[bool, List[str]]:
    """
    检查单个 rule（包含多个 conditions）

    :param instance: 实例数据
    :param rule: 规则定义 {"ruleName": ..., "ruleDesc": ..., "logic": "AND/OR", "conditions": [...]}
    :return: (是否通过, 失败原因列表)
    """
    logic = rule.get("logic", "AND").upper()
    conditions = rule.get("conditions", [])
    rule_name = rule.get("ruleName", "")

    if not conditions:
        logger.warning(f"规则 '{rule_name}' 中 conditions 为空，视为通过")
        return True, []

    results = []
    reasons = []
    for cond in conditions:
        passed, reason = check_condition(instance, cond)
        results.append(passed)
        if not passed:
            reasons.append(reason)

    if logic == "AND":
        # 所有条件都通过才算通过
        return all(results), reasons
    elif logic == "OR":
        # 任一条件通过即通过
        if any(results):
            return True, []
        return False, reasons
    else:
        logger.error(f"不支持的逻辑运算符: {logic}，默认使用 AND")
        return all(results), reasons


def check_instance(instance: Dict, rules: List[Dict]) -> Tuple[bool, List[Dict], List[str]]:
    """
    对单个实例执行所有规则检查

    多个 rule 之间是 OR 关系：任一 rule 通过即视为合规。
    所有 rule 都不通过时记录为不合规。

    :param instance: 实例数据
    :param rules: 规则列表
    :return: (是否合规, 未通过的规则列表, 失败原因列表)
    """
    if not rules:
        return True, [], []

    all_failed_rules = []
    all_reasons = []

    for i, rule in enumerate(rules):
        passed, reasons = check_rule(instance, rule)
        rule_label = rule.get("ruleName") or f"#{i + 1}"
        if passed:
            # 任一 rule 通过即合规
            logger.debug(f"实例通过规则 '{rule_label}'")
            return True, [], []
        else:
            all_failed_rules.append(rule)
            all_reasons.extend(reasons)

    # 所有 rule 都不通过
    return False, all_failed_rules, all_reasons


# =============================================================================
# 业务逻辑：结果管理
# =============================================================================

def build_result_record(baseline_rule: Dict, instance: Dict,
                        failed_rules: List[Dict], reasons: List[str],
                        check_time: str) -> Dict:
    """
    构建一条不合规结果记录

    :param baseline_rule: 基线规则实例
    :param instance: 不合规的目标实例
    :param failed_rules: 未通过的规则列表
    :param reasons: 失败原因列表
    :param check_time: 检查时间（ISO 格式）
    :return: BASELINE_RESULT 实例数据
    """
    target_model = baseline_rule.get("targetModelId", "")
    inst_id = instance.get("instanceId", "")
    # 实例名称：优先取 name，其次 hostname，再次 instanceId
    inst_name = (instance.get("name")
                 or instance.get("hostname")
                 or inst_id)

    # 构建可读的失败规则摘要（包含规则名称和说明）
    failed_summary = []
    for r in failed_rules:
        item = {}
        if r.get("ruleName"):
            item["ruleName"] = r["ruleName"]
        if r.get("ruleDesc"):
            item["ruleDesc"] = r["ruleDesc"]
        item["logic"] = r.get("logic", "AND")
        item["conditions"] = r.get("conditions", [])
        failed_summary.append(item)

    return {
        "baselineRuleId": baseline_rule.get("instanceId", ""),
        "baselineName": baseline_rule.get("name", ""),
        "targetModelId": target_model,
        "targetInstanceId": inst_id,
        "instanceName": str(inst_name),
        "instanceUrl": f"/next/cmdb-instances/{target_model}/instance/{inst_id}",
        "failedRule": json.dumps(failed_summary, ensure_ascii=False),
        "failedReason": "; ".join(reasons),
        "checkTime": check_time,
    }


def cleanup_rule_results(client: EasyOpsClient, rule_instance_id: str) -> int:
    """
    删除指定基线规则的所有旧结果（幂等性保证）

    每次执行前清理该规则的全部历史结果，再写入本次检查的不合规记录。
    确保已合规的实例不会残留旧的不合规记录。

    :param client: EasyOps 客户端
    :param rule_instance_id: 基线规则实例 ID
    :return: 删除的记录数
    """
    query = {"baselineRuleId": rule_instance_id}
    old_results = client.search_instance(
        RESULT_MODEL_ID, query=query, fields=["instanceId"]
    )
    if not old_results:
        return 0

    ids = [r["instanceId"] for r in old_results]
    result = client.delete_instance_batch(RESULT_MODEL_ID, ids)
    count = result.get("deleted", 0)
    logger.info(f"清理基线 {rule_instance_id} 旧结果: {count} 条")
    return count


def cleanup_expired_results(client: EasyOpsClient, retention_days: int) -> int:
    """
    清理过期的检查结果

    :param client: EasyOps 客户端
    :param retention_days: 保留天数
    :return: 清理的记录数
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%S")
    query = {
        "checkTime": {"$lt": cutoff}
    }
    expired = client.search_instance(
        RESULT_MODEL_ID, query=query, fields=["instanceId"]
    )
    if not expired:
        logger.info("无过期结果需要清理")
        return 0

    ids = [r["instanceId"] for r in expired]
    result = client.delete_instance_batch(RESULT_MODEL_ID, ids)
    count = result.get("deleted", 0)
    logger.info(f"清理过期结果（>{retention_days} 天）: {count} 条")
    return count


# =============================================================================
# 主流程
# =============================================================================

def main():
    """
    基线检查主入口

    执行流程:
        1. 初始化 EasyOpsClient
        2. 查询基线规则实例
        3. 遍历规则，逐实例检查
        4. 删除当天旧结果（幂等）
        5. 写入新结果
        6. 清理过期结果
        7. 输出摘要
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("配置基线检查 开始执行")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 1. 初始化客户端
    # ------------------------------------------------------------------
    try:
        if EASYOPS_HOST and EASYOPS_AK and EASYOPS_SK:
            client = EasyOpsClient(
                host=EASYOPS_HOST, org=EASYOPS_ORG,
                ak=EASYOPS_AK, sk=EASYOPS_SK
            )
            logger.info("使用 OpenAPI 模式连接")
        else:
            client = EasyOpsClient()
            logger.info("使用内网模式连接")
    except Exception as e:
        logger.error(f"初始化 EasyOpsClient 失败: {e}")
        return

    # ------------------------------------------------------------------
    # 2. 查询基线规则实例
    # ------------------------------------------------------------------
    if BASELINE_INSTANCEIDS:
        # 按指定 ID 查询
        query = {"instanceId": {"$in": BASELINE_INSTANCEIDS}}
        logger.info(f"按指定 ID 查询基线规则: {BASELINE_INSTANCEIDS}")
    else:
        query = {}
        logger.info("查询全部基线规则")

    try:
        baseline_rules = client.search_instance(RULE_MODEL_ID, query=query)
    except Exception as e:
        logger.error(f"查询基线规则失败: {e}")
        return

    if not baseline_rules:
        logger.warning("未查询到任何基线规则，仅执行过期结果清理")
        try:
            cleanup_expired_results(client, RESULT_RETENTION_DAYS)
        except Exception as e:
            logger.error(f"清理过期结果失败: {e}")
        return

    logger.info(f"共查询到 {len(baseline_rules)} 条基线规则")

    # ------------------------------------------------------------------
    # 3. 遍历每条基线规则执行检查
    # ------------------------------------------------------------------
    check_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # 汇总统计
    summary = {
        "total_rules": len(baseline_rules),
        "rules_checked": 0,
        "rules_skipped": 0,
        "total_instances": 0,
        "total_noncompliant": 0,
        "total_written": 0,
        "total_cleaned": 0,
        "total_cleaned_expired": 0,
    }

    all_results = []  # 本次所有不合规结果
    checked_rule_ids = []  # 已检查的规则 ID（用于幂等清理）

    for idx, rule in enumerate(baseline_rules, 1):
        rule_name = rule.get("name", "未命名")
        rule_id = rule.get("instanceId", "")
        target_model = rule.get("targetModelId", "")
        logger.info(f"--- 规则 [{idx}/{len(baseline_rules)}] {rule_name} (目标: {target_model}) ---")

        # 解析 query（json 类型，CMDB 返回时已是 dict）
        raw_query = rule.get("query", {})
        if isinstance(raw_query, str):
            # 兼容字符串格式
            try:
                target_query = json.loads(raw_query) if raw_query else {}
            except json.JSONDecodeError as e:
                logger.error(f"规则 {rule_name} 的 query 解析失败: {e}，跳过")
                summary["rules_skipped"] += 1
                continue
        else:
            target_query = raw_query if raw_query else {}

        # 解析 rules（structs 类型，CMDB 返回时已是 list[dict]）
        # 每个元素结构: {"ruleName": ..., "ruleDesc": ..., "logic": ..., "conditions": "JSON字符串"}
        raw_rules = rule.get("rules", [])
        if isinstance(raw_rules, str):
            # 兼容旧的纯 JSON 字符串格式
            try:
                raw_rules = json.loads(raw_rules) if raw_rules else []
            except json.JSONDecodeError as e:
                logger.error(f"规则 {rule_name} 的 rules 解析失败: {e}，跳过")
                summary["rules_skipped"] += 1
                continue

        if not raw_rules:
            logger.warning(f"规则 {rule_name} 的 rules 为空，跳过")
            summary["rules_skipped"] += 1
            continue

        # 将 structs 格式转换为规则引擎格式
        rules_def = []
        for r in raw_rules:
            conditions_raw = r.get("conditions", "[]")
            if isinstance(conditions_raw, str):
                try:
                    conditions = json.loads(conditions_raw) if conditions_raw else []
                except json.JSONDecodeError as e:
                    logger.error(
                        f"规则 {rule_name} 子规则 '{r.get('ruleName', '')}' "
                        f"的 conditions 解析失败: {e}，跳过该子规则"
                    )
                    continue
            else:
                conditions = conditions_raw if conditions_raw else []
            rules_def.append({
                "ruleName": r.get("ruleName", ""),
                "ruleDesc": r.get("ruleDesc", ""),
                "logic": r.get("logic", "AND"),
                "conditions": conditions
            })

        if not rules_def:
            logger.warning(f"规则 {rule_name} 解析后无有效子规则，跳过")
            summary["rules_skipped"] += 1
            continue

        # 查询目标实例
        try:
            target_instances = client.search_instance(
                target_model, query=target_query, page_size=200
            )
        except Exception as e:
            logger.error(f"查询目标实例失败 ({target_model}): {e}，跳过")
            summary["rules_skipped"] += 1
            continue

        if not target_instances:
            logger.info(f"规则 {rule_name} 未匹配到目标实例，跳过")
            checked_rule_ids.append(rule_id)
            summary["rules_checked"] += 1
            continue

        logger.info(f"匹配到 {len(target_instances)} 个目标实例")
        summary["total_instances"] += len(target_instances)

        # 逐实例检查
        rule_noncompliant = 0
        for inst in target_instances:
            inst_id = inst.get("instanceId", "")
            try:
                compliant, failed_rules, reasons = check_instance(inst, rules_def)
                if not compliant:
                    rule_noncompliant += 1
                    record = build_result_record(
                        rule, inst, failed_rules, reasons, check_time
                    )
                    all_results.append(record)
                    logger.debug(
                        f"不合规: {inst_id} - {'; '.join(reasons)}"
                    )
            except Exception as e:
                logger.error(f"检查实例 {inst_id} 时异常: {e}，跳过该实例")
                continue

        logger.info(
            f"规则 {rule_name}: 检查 {len(target_instances)} 个实例，"
            f"不合规 {rule_noncompliant} 个"
        )
        summary["total_noncompliant"] += rule_noncompliant
        summary["rules_checked"] += 1
        checked_rule_ids.append(rule_id)

    # ------------------------------------------------------------------
    # 4. 删除旧结果（幂等性保证）
    # ------------------------------------------------------------------
    logger.info("--- 清理旧结果 ---")
    for rule_id in checked_rule_ids:
        try:
            cleaned = cleanup_rule_results(client, rule_id)
            summary["total_cleaned"] += cleaned
        except Exception as e:
            logger.error(f"清理规则 {rule_id} 旧结果失败: {e}")

    # ------------------------------------------------------------------
    # 5. 批量写入新结果
    # ------------------------------------------------------------------
    if all_results:
        logger.info(f"--- 写入检查结果: {len(all_results)} 条 ---")
        try:
            write_result = client.import_instance(
                RESULT_MODEL_ID, all_results,
                keys=["baselineRuleId", "targetInstanceId"]
            )
            summary["total_written"] = (
                write_result.get("insert_count", 0)
                + write_result.get("update_count", 0)
            )
            if write_result.get("failed_count", 0) > 0:
                logger.warning(
                    f"写入结果部分失败: {write_result['failed_count']} 条"
                )
        except Exception as e:
            logger.error(f"写入检查结果失败: {e}")
    else:
        logger.info("本次检查无不合规结果，无需写入")

    # ------------------------------------------------------------------
    # 6. 清理过期结果
    # ------------------------------------------------------------------
    logger.info("--- 清理过期结果 ---")
    try:
        summary["total_cleaned_expired"] = cleanup_expired_results(
            client, RESULT_RETENTION_DAYS
        )
    except Exception as e:
        logger.error(f"清理过期结果失败: {e}")

    # ------------------------------------------------------------------
    # 7. 输出执行摘要
    # ------------------------------------------------------------------
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("执行摘要:")
    logger.info(f"  基线规则总数: {summary['total_rules']}")
    logger.info(f"  已检查规则数: {summary['rules_checked']}")
    logger.info(f"  跳过规则数:   {summary['rules_skipped']}")
    logger.info(f"  检查实例总数: {summary['total_instances']}")
    logger.info(f"  不合规实例数: {summary['total_noncompliant']}")
    logger.info(f"  写入结果数:   {summary['total_written']}")
    logger.info(f"  清理旧结果:   {summary['total_cleaned']}")
    logger.info(f"  清理过期结果: {summary['total_cleaned_expired']}")
    logger.info(f"  耗时: {elapsed:.2f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
