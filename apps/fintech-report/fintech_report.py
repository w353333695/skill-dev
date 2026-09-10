#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人行金融科技信息报送 —— 单文件可执行脚本（fintech_data Go 服务 P0+P1 能力迁移）.

能力（对应 Go 版模块）:
  report   全量/增量上报: CMDB 拉规则+实例 → 转换(枚举码/bool/精度/omitempty/PK翻译)
           → FICS HTTP(gzip+base64+OAuth token, 中信变体) → 任务历史落 CMDB → 数据原文落磁盘
           （Go: report_rule.Converter + report_center.Service + report_task.ReportService）
  rollback 仅回滚本地状态: 任务标记 rolledBack（不动人行侧），下次上报该模型当全量 new 重报
  cleanup  历史清理: 按 FINTECH_REPORT_CLEANUP 规则（条数 AND 天数同时超出才清），
           删 CMDB 任务记录 + 数据原文文件 + 级联回滚记录

元数据与历史全部在 CMDB（不放 Mongo/SQLite/外挂配置文件）:
  FINTECH_REPORT_CONFIG@EASYOPS   全局连接配置（clientId/Secret/ip/port/机构号）
  FINTECH_REPORT_OBJ@EASYOPS      上报规则（每模型一条: objectId/crontab/enable/batchNum/mappingRule...）
  FINTECH_REPORT_TASK@EASYOPS     任务历史（含人行批次号/统计/回执码/dataFile 原文路径）
  FINTECH_REPORT_ROLLBACK@EASYOPS 回滚记录
  FINTECH_REPORT_CLEANUP@EASYOPS  清理规则（默认不清理）

用法:
  python3 fintech_report.py report                                   # 全量（所有 enable 规则）
  python3 fintech_report.py report --scope "switches@FINTECHDATA"     # 指定模型（逗号分隔）
  python3 fintech_report.py rollback --task <taskId>
  python3 fintech_report.py cleanup

依赖: 仅 Python3 标准库。触发方式由外部集成方案负责（本脚本不做定时）。
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
import urllib.parse
import uuid
import traceback

import requests
from pathlib import Path
from typing import Any

def _maybe_json(v: Any) -> Any:
    """v 是字符串(含 py2 unicode)则 JSON parse；解析失败/非字符串原样返回。"""
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v

# ============================================================================
# 配置区（仅环境连接 + 运行开关；业务配置全部从 CMDB FINTECH_REPORT_CONFIG 拉取）
# ============================================================================

CMDB_API = {
    "base_url": "http://172.30.0.232:8079",
    "org": "18832008",
    # "base_url": "http://11.66.19.194:8079",
    # "org": "1026123",
    "user": "easyops",
    "timeout": 60,
    "retry": 3,
    "retry_wait": 2,
    "search_page_size": 300,   # Go 版 search_batch=300
}

# 数据原文落盘目录（相对本脚本；taskId.json 一文件）
DATA_DIR = "/data/fintech-report-data"

DEBUG = False          # True = 打印 HTTP 请求/响应摘要

# ---- CMDB 模型 id 常量（本脚本的知识边界，全部元数据在此） ----
OBJ_CONFIG = "FINTECH_REPORT_CONFIG@EASYOPS"    # 全局配置
OBJ_RULE = "FINTECH_REPORT_OBJ@EASYOPS"         # 上报规则
OBJ_TASK = "FINTECH_REPORT_TASK@EASYOPS"        # 任务历史
OBJ_ROLLBACK = "FINTECH_REPORT_ROLLBACK@EASYOPS"
OBJ_CLEANUP = "FINTECH_REPORT_CLEANUP@EASYOPS"
OBJ_FAIL_DETAIL = "FINTECH_REPORT_INSTANCE@EASYOPS"

# ---- 内嵌上报策略（对应 Go conf.default.yaml report_conf 段；行数少，不值得外挂） ----
# 全局字段黑名单: CMDB 系统/管理字段，任何数据元定义里都没有——混进报文会被人行
# 「属性数量校验」拒收（WL-20001 数据元属性数量过多，2026-09-08 现场
# powerSupplyRelation 的 importId 实证：报文 8 字段 vs 人行定义 7 字段）
FIELD_BLACKLIST = {"importId"}
# 唯一键字段翻译（模型特殊 PK → 上报口径 facilityDescriptor/facilityCategory）
PK_TRANSLATE = {
    "basedSoftware@FINTECHDATA": ("softwareDescriptor", "softwareCategory"),
    "application@FINTECHDATA": ("applySystemIdentifiers", "softwareCategory"),
    "dataCenterSpacing@FINTECHDATA": ("relationalIdentifier", "facilityCategory"),
    "powerSupplyRelation@FINTECHDATA": ("relationalIdentifier", "facilityCategory"),
    "applicationRelation@FINTECHDATA": ("relationalIdentifier", "facilityCategory"),
    "networkRelation@FINTECHDATA": ("relationalIdentifier", "facilityCategory"),
    "softwareRelation@FINTECHDATA": ("relationalIdentifier", "facilityCategory"),
}
# 字段编码翻译: CMDB 存中文名/明文，人行要标准编码
# nationalArea: 3位国家码(GB/T 2659)；administrativeArea: 6位行政区划码(GB/T 2260)
NATIONAL_AREA_CODES = {
    "中国": "156", "中国台湾": "158", "中国香港": "344", "中国澳门": "446",
    "日本": "392", "韩国": "410", "美国": "840", "英国": "826", "法国": "250",
    "德国": "276", "新加坡": "702", "其它": "999",
}
ADMIN_AREA_CODES = {
    "北京市": "110000", "天津市": "120000", "河北省": "130000", "山西省": "140000",
    "内蒙古自治区": "150000", "辽宁省": "210000", "吉林省": "220000", "黑龙江省": "230000",
    "上海市": "310000", "江苏省": "320000", "浙江省": "330000", "安徽省": "340000",
    "福建省": "350000", "江西省": "360000", "山东省": "370000", "河南省": "410000",
    "湖北省": "420000", "湖南省": "430000", "广东省": "440000", "广西壮族自治区": "450000",
    "海南省": "460000", "重庆市": "500000", "四川省": "510000", "贵州省": "520000",
    "云南省": "530000", "西藏自治区": "540000", "陕西省": "610000", "甘肃省": "620000",
    "青海省": "630000", "宁夏回族自治区": "640000", "新疆维吾尔自治区": "650000",
    "台湾省": "710000", "香港特别行政区": "810000", "澳门特别行政区": "820000",
    # 市级（河南省——CMDB administrativeArea 存市级名，规则要求 6 位整数码）
    "郑州市": "410100", "开封市": "410200", "洛阳市": "410300",
    "平顶山市": "410400", "安阳市": "410500", "鹤壁市": "410600",
    "新乡市": "410700", "焦作市": "410800", "濮阳市": "410900",
    "许昌市": "411000", "漯河市": "411100", "三门峡市": "411200",
    "南阳市": "411300", "商丘市": "411400", "信阳市": "411500",
    "周口市": "411600", "驻马店市": "411700", "济源市": "419001",
}
# 数值语义字段（校验规则表 DC/GXDC 等"报送数据类型必须为整数型"全集）:
# CMDB 模型多为 str 定义，但人行检核 JSON 值类型——这些字段必须输出 JSON number（非字符串）。
# 含 struct 子字段（按字段名匹配，跨模型通用）。
NUMERIC_FIELDS = {
    "administrativeArea", "nationalArea", "slotNo", "numberOfCards", "designCabinetNumber",
    "usedCabinetNumber", "buildingBearingCapacity", "disasterStatisticsInThePastFiveYears",
    "electricalEquipmentOpsPersonnel", "hvacOpsPersonnel", "itEquipmentOpsPersonnel",
    "networkOpsPersonnel", "operationNumbers", "otherSupportingOpsPersonnel",
    "outsourcedNumber", "networkOperatorNumber", "deviceHeight", "dataSavePeriod",
    "dataSaveCycle", "storagePeriod", "maximumVolume", "numberOfSoftwareInstance",
    "numberOfSoftwareLicenses", "numberOfBatteries", "numberOfCoresPerCpu",
    "numberOfDisks", "numberOfOpticalFiberPorts", "numberOfTapeDrives", "numberOfTunnels",
    "maximumConnections", "maximumNewConnectionRate", "maximumNumberOfConcurrentConnections",
    "handlingCapacity", "dataExchangeRate", "hardwareSwitchingTime", "hddCapability",
    "memoryCapacity", "nominalCapacity", "ratedAlternatingFrequency", "ratedInputCurrent",
    "ratedInputPower", "ratedInputVoltage", "ratedOutputCurrent", "ratedOutputPower",
    "ratedOutputVoltage", "refrigeratingCapacity", "classificationOfAirRefrigerationVolume",
    "backupPowerSupply", "freshAirRate", "surveillanceNumber", "totalNumberOfCpu",
    "totalNumberOfCpuNuclear", "totalStorageCapacity", "rpo", "rto", "number",
    "virtualMachineCpuInformation", "virtualMachineHarddiskSize", "virtualMachineMemorySize",
    "purchaseNumber", "cameraNumber",
}
# 地级市→属地行政区号（人行机构表"XX市分行"属地精确码，如 漯河市→411103 而非
# 行政区划标准 411100——人行按其机构属地口径校验）。郑州=省分行属地 410105。
ADMIN_CITY_AREA_CODES = {
    "三门峡市": "411202",
    "信阳市": "411502",
    "南阳市": "411303",
    "周口市": "411602",
    "商丘市": "411403",
    "安阳市": "410502",
    "平顶山市": "410411",
    "开封市": "410202",
    "新乡市": "410702",
    "洛阳市": "410303",
    "济源市": "419001",
    "漯河市": "411103",
    "濮阳市": "410902",
    "焦作市": "410811",
    "许昌市": "411002",
    "郑州市": "410105",
    "驻马店市": "411702",
    "鹤壁市": "410611",
}
IGNORE_INST_ATTR = "ignoreReport"           # 实例该属性为 true 时跳过上报
IGNORE_ATTR_CATEGORY = ["辅助信息", "ignoreReport"]   # 属性 tag 命中则不上报该属性
OMITEMPTY_FIELDS = ["%_operationsManagement"]        # 为空则整段省略（模糊匹配）
FLOAT_PREC_RULE = {                         # 浮点精度特例（默认 2 位）
    "videoMonitoring@FINTECHDATA": {"dataSavePeriod": 3},
    "entranceGuard@FINTECHDATA": {"dataSaveCycle": 3},
}
REPORT_TYPE_NEW, REPORT_TYPE_UPDATE, REPORT_TYPE_DELETE = "new", "update", "delete"

# 人行状态码（Go report_center/types.go 全量）
CODE_REPORT_SUCCESS = "WL-10000"
CODE_BRANCH_ID_NOT_EXIST = "WL-10004"  # 批次不存在(受理后异步落库延迟，需轮询)
CODE_SAVE_SUCCESS = "WL-10005"      # 已保存（处理中，继续轮询）
CODE_HANDLING = "WL-10006"           # 处理中（继续轮询）
CODE_HANDLE_SUCCESS = "WL-10009"    # 处理成功（终态：成功）
CODE_HANDLE_WITH_WARN = "WL-10013"  # 处理成功有警告（终态：成功）
CHECK_POLL_INTERVAL = 10
CHECK_POLL_MAX = 5
GROUP_POLL_MAX = 30   # 批次组轮询（逻辑检核+入库较慢，30x10s=5min）
CODE_DATA_VALID = "WL-20000"
# TODO Audit 审核流程（Go CreateAuditTask）: 规则实例 autoRequestCheck=true 时，上报成功后
# 应 POST requestCheck（gzip branchIdList）触发人行审核、得 groupId（G 系列批次组）。
# 当前环境 0 规则开启该开关（Go 侧同跳过），故未实现；开启前需补此环节。
CODE_DATA_VALID_WITH_WARNING = "WL-20003"

LOG = logging.getLogger("fintech-report")


# ============================================================================
# 通用层: HTTP / CMDB 客户端
# ============================================================================

_SESSION = requests.Session()
_SESSION.verify = False   # 内网自签证书
try:
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


def _http_json(method: str, url: str, body: Any = None, headers: dict | None = None,
              timeout: int = 30, retry: int = 3, retry_wait: int = 2) -> Any:
    """requests 实现 JSON HTTP 带重试。"""
    last_err = None
    for attempt in range(1, retry + 1):
        if DEBUG:
            LOG.debug("[http] %s %s body=%s", method, url, str(body)[:500])
        try:
            resp = _SESSION.request(method, url, json=body, headers=headers, timeout=timeout)
            if DEBUG:
                LOG.debug("[http] ← %s", resp.text[:500])
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json() if resp.text.strip() else {}
        except RuntimeError as e:
            if "HTTP 4" in str(e) and "HTTP 408" not in str(e) and "HTTP 429" not in str(e):
                raise   # 4xx 不重试
            last_err = e
        except (requests.RequestException, ValueError) as e:
            last_err = RuntimeError(f"网络/解析错误: {e}")
        if attempt < retry:
            time.sleep(retry_wait)
    raise last_err  # type: ignore[misc]


def cmdb_post(path: str, body: dict) -> dict:
    headers = {"org": CMDB_API["org"], "user": CMDB_API["user"]}
    return _http_json("POST", CMDB_API["base_url"] + path, body, headers,
                      CMDB_API["timeout"], CMDB_API["retry"], CMDB_API["retry_wait"])


def cmdb_search_task_v2(object_id_query: str, statuses: list[str] | None = None) -> list[dict]:
    """FINTECH_REPORT_TASK 精确过滤查询（v2 _search query）。

    ⚠️ v3 retrieve.expression 在本 CMDB 实测不生效（任何 expr 都返回全量），
    任务/台账查询必须走 v2 query（$and + 精确值，实测正确过滤）。
    """
    conds = [{"objectId": object_id_query}]
    if statuses:
        conds.append({"status": {"$in": statuses}})
    conds.append({"rolledBack": False})
    out, page = [], 1
    while True:
        body = {"query": {"$and": conds},
                "fields": {"taskId": True, "dataFile": True, "startTime": True,
                           "status": True, "objectId": True, "instanceId": True},
                "page": page, "pageSize": CMDB_API["search_page_size"]}
        d = cmdb_post(f"/v2/object/{urllib.parse.quote(OBJ_TASK, safe='@')}/instance/_search", body)
        data = d.get("data") or {}
        out.extend(data.get("list") or [])
        if len(out) >= (data.get("total") or len(out)):
            return out
        page += 1


def cmdb_search_all(object_id: str, fields: list[str] | None = None,
                    expr: str | None = None) -> list[dict]:
    """v3 实例搜索全量分页。fields 为空时用 ['*']（该端点要求 fields 必填）。"""
    out, page = [], 1
    while True:
        body: dict[str, Any] = {"page": page, "page_size": CMDB_API["search_page_size"],
                                "fields": fields or ["*"]}
        if expr:
            body["retrieve"] = {"expression": expr}
        d = cmdb_post(
            f"/v3/object/{urllib.parse.quote(object_id, safe='@')}/instance/_search", body)
        data = d.get("data") or {}
        lst = data.get("list") or []
        out.extend(lst)
        if len(out) >= (data.get("total") or len(out)):
            return out
        page += 1


def cmdb_import(object_id: str, keys: list[str], datas: list[dict]) -> dict:
    """实例声明式 upsert（keys 命中改/未命中建）。返回 {insert,update,failed,fail_detail}。"""
    if not datas:
        return {"insert": 0, "update": 0, "failed": 0, "fail_detail": []}
    d = cmdb_post(f"/object/{urllib.parse.quote(object_id, safe='@')}/instance/_import",
                  {"keys": keys, "datas": datas})
    if d.get("code") != 0:
        raise RuntimeError(f"_import code={d.get('code')}: {json.dumps(d, ensure_ascii=False)[:400]}")
    data = d.get("data") or {}
    return {"insert": data.get("insert_count", 0), "update": data.get("update_count", 0),
            "failed": data.get("failed_count", 0),
            "fail_detail": (data.get("data") or [])[:10]}


def cmdb_delete(object_id: str, instance_ids: list[str]) -> list[str]:
    """批量删实例，返回删除失败的 id 列表。"""
    if not instance_ids:
        return []
    ids_str = ";".join(instance_ids)
    url = (f"{CMDB_API['base_url']}/object/{urllib.parse.quote(object_id, safe='@')}/instance_batch"
           f"?instanceIds={urllib.parse.quote(ids_str)}")
    resp = _SESSION.delete(url, headers={"org": CMDB_API["org"], "user": CMDB_API["user"]},
                           timeout=CMDB_API["timeout"])
    if resp.status_code >= 400:
        LOG.warning("[cmdb] delete fail: HTTP %s %s", resp.status_code, resp.text[:200])
        return instance_ids
    d = resp.json() if resp.text.strip() else {}
    return [str(x) for x in (d.get("data", {}) or {}).get("deleteFailedInstances", [])]


# ============================================================================
# 配置加载（全部从 CMDB）
# ============================================================================

def load_global_config() -> dict:
    """FINTECH_REPORT_CONFIG 取第一条启用的配置（clientId/Secret/ip/port/机构号）。"""
    rows = cmdb_search_all(OBJ_CONFIG)
    if not rows:
        raise RuntimeError(f"未找到上报全局配置（{OBJ_CONFIG} 无实例）——先在 CMDB 建配置")
    return rows[0]


def load_rules(scope: str = "") -> list[dict]:
    """FINTECH_REPORT_OBJ 取上报规则；scope 非空则过滤（逗号分隔 objectId）。"""
    rows = cmdb_search_all(OBJ_RULE)
    want = {s.strip() for s in scope.split(",") if s.strip()} if scope else None
    rules = []
    for r in rows:
        if want is not None and r.get("objectId") not in want:
            continue
        if str(r.get("abandon", False)) in ("True", "true", True):
            continue  # 废弃模型
        rules.append(r)
    if want:
        found = {r.get("objectId") for r in rules}
        missing = want - found
        if missing:
            raise RuntimeError(f"scope 指定的模型无上报规则或已废弃: {sorted(missing)}")
    return rules


def load_report_objects() -> dict[str, dict]:
    """FINTECH_REPORT_OBJ.objectDefine 缓存了模型定义（attrList）；拉不齐则现查 CMDB 模型详情。"""
    out = {}
    for r in cmdb_search_all(OBJ_RULE):
        oid = r.get("objectId")
        if not oid:
            continue
        define = _maybe_json(r.get("objectDefine"))
        if isinstance(define, dict) and define.get("attrList"):
            out[oid] = define
    return out


# ============================================================================
# 转换器（复刻 Go report_rule.Converter —— 人行口径的属性值变换）
# ============================================================================

def _fuzzy_match(pattern: str, field: str) -> bool:
    """Go stringutil.FuzzyMatch: % 通配。"""
    return re.fullmatch(pattern.replace("%", ".*"), field) is not None


class Converter:
    """一个上报模型一个实例。attrList 来自规则实例的 objectDefine（或 CMDB 模型）。"""

    def __init__(self, object_id: str, report_obj: dict, mapping_rule: list | None = None):
        self.object_id = object_id
        self.attrs = (report_obj or {}).get("attrList") or []
        self.attr_by_id = {a["id"]: a for a in self.attrs}
        # 映射模式（source=mapping）: reportAttrId -> mappingAttrId
        self.mapping: dict[str, str] = {}
        mapping_rule = _maybe_json(mapping_rule)
        if isinstance(mapping_rule, list):
            for m in mapping_rule:
                if isinstance(m, dict) and m.get("reportAttrId"):
                    self.mapping[m["reportAttrId"]] = m.get("mappingAttrId", "")
        self.key_desc, self.key_cate = PK_TRANSLATE.get(
            object_id, ("facilityDescriptor", "facilityCategory"))
        self.prec = FLOAT_PREC_RULE.get(object_id, {})
        self.ignore_tags = set(IGNORE_ATTR_CATEGORY)

    # -- 属性是否上报（tag 忽略 + ignoreReport 实例级单独处理） --
    def _should_report(self, attr: dict) -> bool:
        return not (set(attr.get("tag") or []) & self.ignore_tags)

    def _omitempty(self, attr_id: str) -> bool:
        return any(_fuzzy_match(p, attr_id) for p in OMITEMPTY_FIELDS)

    # -- 主转换: CMDB 实例 -> 人行上报数据（dict，值全为 JSON 标量/容器） --
    def convert(self, inst: dict) -> dict:
        out: dict[str, Any] = {}
        for attr in self.attrs:
            aid = attr["id"]
            if not self._should_report(attr):
                continue
            if aid == IGNORE_INST_ATTR:
                continue  # ignoreReport 标记本身不上报（标记为 true 的实例在外层过滤）
            if aid in FIELD_BLACKLIST:
                continue  # CMDB 系统字段兜底剔除（tag 过滤失效时的保险，人行无此属性）
            # 映射模式取源字段
            src_id = self.mapping.get(aid) or aid
            value = inst.get(src_id)
            atype = (attr.get("value") or {}).get("type", "str")
            if self._is_empty(value):
                if self._omitempty(aid):
                    continue  # 为空且 omitempty → 整个属性省略
                if atype == "struct":
                    # Go transformStructValue: 空 struct → 全子字段空串（字段必须出现）
                    out[aid] = self._empty_struct_obj(attr)
                    continue
                if atype == "structs":
                    # Go transformStructs: 空 structs → 单元素数组（全空子字段），非空数组
                    out[aid] = [self._empty_struct_obj(attr)]
                    continue
                # facilityUpdateDate 空值兜底当天（人行"属性值不能为空"拒绝空串；
                # 语义=信息更新时间，同步当天合理，同 Go utime 处理）
                if aid == "facilityUpdateDate":
                    out[aid] = time.strftime("%Y-%m-%d")
                else:
                    out[aid] = ""   # 人行要求空值传空字符串
                continue
            out[aid] = self._transform(aid, atype, value, attr)
            # 数值语义字段: 人行检核 JSON 值类型，str 定义的字段也要输出 JSON number
            if aid in NUMERIC_FIELDS and isinstance(out[aid], str):
                s = out[aid].strip()
                if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                    out[aid] = int(s)
        return out

    def _is_empty(self, v: Any) -> bool:
        return v is None or v == "" or v == [] or v == {}

    # Go IDFormatRegex: ".+?\[[0-9a-zA-Z_-]{32}\]" —— relation fill 的 name[hex] 残留形态
    _ID_FMT_RE = re.compile(r".+?\[[0-9a-zA-Z_-]{32}\]")

    def _transform(self, attr_id: str, atype: str, value: Any, attr: dict) -> Any:
        if atype == "str":
            s = str(value)
            # Go RecoverValueChange: relation fill 写入的 "name[32hex]" 还原为 "32hex"
            # （Go 限定 selfEffectedIds；Python 读 CMDB 现值防御性全量处理，正则零误伤）
            if self._ID_FMT_RE.fullmatch(s):
                s = s.split("[", 1)[1].replace("]", "")
            # 编码翻译: 人行要求标准编码的字段（CMDB 常存中文名）
            if attr_id == "nationalArea" and s in NATIONAL_AREA_CODES:
                return NATIONAL_AREA_CODES[s]
            if attr_id == "administrativeArea":
                if s in ADMIN_CITY_AREA_CODES:
                    return ADMIN_CITY_AREA_CODES[s]
                if s in ADMIN_AREA_CODES:
                    return ADMIN_AREA_CODES[s]
            return s
        if atype == "bool":
            return "True" if value else "False"
        if atype == "int":
            return str(int(value))
        if atype == "float":
            prec = self.prec.get(attr_id, 2)
            return f"{float(value):.{prec}f}"
        if atype == "date":
            # Go transformDateValue: 非空原样返回（无截断）
            return str(value)
        if atype == "datetime":
            # Go transformTimeValue: Split(":") 去掉最后一段（秒）
            # "2021-03-15 10:33:00" → "2021-03-15 10:33"；无冒号原样
            s = str(value)
            return s.rsplit(":", 1)[0] if ":" in s else s
        if atype == "enum":
            return self._enum_code(value)
        if atype == "enums":
            vals = value if isinstance(value, list) else [value]
            return ",".join(c for c in (self._enum_code(v) for v in vals) if c)
        if atype == "struct":
            subs = (attr.get("value") or {}).get("struct_define") or []
            if isinstance(value, list) and value and isinstance(value[0], dict):
                value = value[0]  # CMDB struct 存单元素数组
            return self._struct_obj(subs, value if isinstance(value, dict) else {})
        if atype == "structs":
            subs = (attr.get("value") or {}).get("struct_define") or []
            items = value if isinstance(value, list) else [value]
            return [self._struct_obj(subs, v) for v in items if isinstance(v, dict)]
        return value

    def _empty_struct_obj(self, attr: dict) -> dict:
        """空 struct → 全子字段空串（Go transformStructValue 空值分支）。"""
        subs = (attr.get("value") or {}).get("struct_define") or []
        # 子字段里嵌套 struct/structs 类型时 Go 走 transformAttrValue → 其空值分支递归全空；
        # FINTECHDATA 模型实际无二层嵌套，这里覆盖一层 + 嵌套层递归
        out = {}
        for s in subs:
            st = s.get("type", "str")
            if st in ("struct", "structs"):
                out[s.get("id", "")] = "" if st == "struct" else [self._empty_struct_obj({"value": {"struct_define": []}})]
            else:
                out[s.get("id", "")] = ""
        return out

    def _struct_obj(self, subs: list, data: dict) -> dict:
        out = {}
        for s in subs:
            sid = s.get("id", "")
            v = data.get(sid)
            st = s.get("type", "str")
            if self._is_empty(v):
                if st in ("struct", "structs"):
                    # Go: 子复合空值同样生成全空结构（递归 transformAttrValue 空值分支）
                    out[sid] = "" if st == "struct" else [self._empty_struct_obj({"id": sid, "value": s})]
                else:
                    out[sid] = ""
                continue
            out[sid] = self._transform(sid, st, v, {"id": sid, "value": s})
            if sid in NUMERIC_FIELDS and isinstance(out[sid], str):
                s2 = out[sid].strip()
                if s2.isdigit() or (s2.startswith("-") and s2[1:].isdigit()):
                    out[sid] = int(s2)
        return out

    @staticmethod
    def _norm_enum_src(value: Any) -> str:
        """枚举源形态归一: JSON 数组 → py2 _text(list) 变 repr 串 "[u'00-xx']"，还原首元素。"""
        if isinstance(value, list):
            return str(value[0]) if value else ""
        s = str(value)
        if s.startswith("[") and s.endswith("]") and "'" in s:
            m = re.search(r"'([^']*)'", s)
            if m:
                return m.group(1)
        return s

    @staticmethod
    def _enum_code(value: Any) -> str:
        """'00-在用'/'00：在用'/'00:在用' → '00'；纯码原样。"""
        s = Converter._norm_enum_src(value)
        for p in ("-", ":", "："):
            if re.fullmatch(rf"\d+{re.escape(p)}.*", s):
                return s.split(p, 1)[0]
        return s

    # -- 实例的业务主键（人行 facilityDescriptor/facilityCategory，按模型翻译） --
    def pk_of(self, inst: dict) -> tuple[str, str]:
        return (str(inst.get(self.key_desc, "") or ""), str(inst.get(self.key_cate, "") or ""))


# ============================================================================
# 报送中心（复刻 Go report_center.Service + 中信变体）
# ============================================================================

class ReportCenter:
    """人行 FICS HTTP 对接。variant: 'pboc'(默认 OAuth+gzip) | 'zhongxin'(免token)"""

    def __init__(self, conf: dict, variant: str = "pboc"):
        self.conf = conf
        self.variant = variant
        self._token: str = ""
        self._token_exp: int = 0

    def _agency(self) -> str:
        """机构号——唯一来源 FINTECH_REPORT_CONFIG.facilityOwnerAgency，未配置直接报错。"""
        agency = str(self.conf.get("facilityOwnerAgency", "") or "").strip()
        if not agency:
            raise RuntimeError(
                "金融机构编码未配置：请在 CMDB FINTECH_REPORT_CONFIG 实例填写 "
                "facilityOwnerAgency（人行机构号，如 A1000141000266）")
        return agency

    def _base(self) -> str:
        ip = self.conf.get("ip") or "127.0.0.1"
        port = self.conf.get("port") or 18002
        schema = self.conf.get("schema") or "https"
        return f"{schema}://{ip}:{port}"

    def _url(self, uri: str) -> str:
        return f"{self._base()}/{uri}"

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 10:
            return self._token
        url = self._url(self.conf.get("tokenUri") or "webproxy/fig2fics/oauth2/v1/pshare/oauth/token")
        resp = _SESSION.post(url, params={
            "client_id": self.conf.get("clientId", ""),
            "client_secret": self.conf.get("clientSecret", ""),
            "grant_type": "client_credentials"},
            headers={"Content-Type": "application/json"}, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"获取 token 失败 (url={url}): HTTP {resp.status_code} {resp.text[:200]}")
        d = resp.json() if resp.text.strip() else {}
        if not d.get("access_token"):
            raise RuntimeError(f"获取 token 失败: {json.dumps(d, ensure_ascii=False)[:200]}")
        self._token = d["access_token"]
        self._token_exp = time.time() + int(d.get("expires_in", 3600))
        return self._token

    def _compress(self, data: Any) -> str:
        """gzip + base64（Go gzipCompress）。"""
        # Go json.Marshal 同款: 中文转义 \uXXXX（与对端字节级一致）
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(gzip.compress(raw)).decode("ascii")

    def _post(self, uri: str, payload: dict) -> dict:
        full_url = self._url(uri)
        headers = {"Content-Type": "application/json", "Charset": "UTF-8"}
        if self.variant == "pboc":
            headers["X-Access-Token"] = self._get_token()
        try:
            resp = _SESSION.post(full_url, json=payload, headers=headers, timeout=60)
            if resp.status_code >= 400:
                raise RuntimeError(f"report post fail (url={full_url}): HTTP {resp.status_code} {resp.text[:200]}")
            return resp.json() if resp.text.strip() else {}
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"report post fail (url={full_url}): {e}")

    def report_data(self, branch_id: str, data: list[dict]) -> dict:
        """上报数据（一批次）。返回 {branchId, code, msg}。"""
        if self.variant == "zhongxin":
            resp = self._post("itsm/httpclient/reportData.action", {
                "branchId": branch_id,
                "facilityOwnerAgency": self._agency(),
                "data": self._compress(data)})
            ok = str(resp.get("code", resp.get("status", ""))) == "1"
            return {"branchId": branch_id,
                    "code": "WL-10000" if ok else str(resp.get("code", "fail")),
                    "msg": str(resp.get("msg", resp.get("message", "")))[:500]}
        resp = self._post(
            self.conf.get("reportDataUri")
            or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/reportData", {
                "branchId": branch_id,
                "facilityOwnerAgency": self._agency(),
                "data": self._compress(data)})
        real_bid = str(resp.get("branchId", "") or "") or branch_id
        return {"branchId": real_bid,          # 人行真批次号（BA开头）——check 必须用它
                "localBranchId": branch_id,
                "code": str(resp.get("code", "")), "msg": str(resp.get("msg", ""))[:500]}

    def request_check(self, branch_ids: list[str]) -> dict:
        """5.2.3 数据元检核请求（时序③）: 触发人行逻辑检核，返回 {groupId, code, msg}。

        参数（规范表7）: facilityOwnerAgency + branchNumber(批次总数) +
        branchIdList(批次号列表 GZIP 压缩串)。返回 groupId 为 G 系列批次组号。
        """
        uri = (self.conf.get("requestCheckUri")
               or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/requestCheck")
        payload = {
            "facilityOwnerAgency": self._agency(),
            "branchNumber": len(branch_ids),
            "branchIdList": self._compress(branch_ids),   # 规范: List 压缩后传串
        }
        resp = self._post(uri, payload)
        if not resp.get("groupId") or not resp.get("code"):
            raise RuntimeError(f"检核请求响应无效: {json.dumps(resp, ensure_ascii=False)[:200]}")
        LOG.info("[report] 检核请求已受理: groupId=%s code=%s",
                 resp.get("groupId", "")[:24], resp.get("code", ""))
        return resp

    # 批次组状态码（接入规范 5.2.5 附录四 + v1.0.29 闭环重分类）
    # 非终态: 40000 等待逻辑检核
    # 在途: 40001 等待入库申请 / 40002 入库处理中——逻辑检核已通过，入库申请/
    #   审批是人行平台人工环节；单次运行到此即返回（任务 inFlight，下次运行结算）
    # 入库终态成功: 40003 入库成功 / 40004 部分成功 / 40006 成功带警告
    # 入库终态失败: 40005 入库处理失败 / 40007 组ID不存在
    _GROUP_PENDING = ("WL-40000", "WL-10005", "WL-10006")
    _GROUP_INFLIGHT = ("WL-40001", "WL-40002")
    _GROUP_STORED = ("WL-40003", "WL-40004", "WL-40006", "WL-10009", "WL-10013")
    _GROUP_FAIL = ("WL-40005", "WL-40007")

    def group_status(self, group_id: str, wait_terminal: bool = True) -> dict:
        """5.2.5 查询批次组处理状态。

        wait_terminal=True 轮询直到终态（入库成功/失败，不停在 WL-40000）：
        非终态码每 CHECK_POLL_INTERVAL 重查，最多 GROUP_POLL_MAX 次；超时返回
        最后响应（调用方按 pendingCheck 处理）。
        """
        uri = (self.conf.get("groupStatusUri")
               or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/getGroupStatus")
        resp = {}
        for _ in range(GROUP_POLL_MAX):
            resp = self._post(uri, {"groupId": group_id, "facilityOwnerAgency": self._agency()})
            if not resp.get("groupId") or not resp.get("code"):
                raise RuntimeError(f"批次组状态响应无效: {json.dumps(resp, ensure_ascii=False)[:200]}")
            code = str(resp.get("code", ""))
            LOG.debug("[report] group poll %s code=%s", group_id[:20], code)
            if not wait_terminal or code not in self._GROUP_PENDING:
                return resp
            time.sleep(CHECK_POLL_INTERVAL)
        LOG.warning("[report] 批次组 %s 轮询 %s 次未到终态 code=%s",
                    group_id[:20], GROUP_POLL_MAX, resp.get("code", ""))
        return resp

    def check_result(self, branch_id: str) -> dict:
        """查批次处理结果；处理中(WL-10005/WL-10006)轮询直到终态或超时(标 pendingCheck 由调用方处理)。"""
        if self.variant == "zhongxin":
            return {"code": CODE_HANDLE_SUCCESS, "msg": "中信变体无结果查询", "data": []}
        uri = (self.conf.get("checkResultUri")
               or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData")
        resp = {}
        for _ in range(CHECK_POLL_MAX):
            resp = self._post(uri, {
                "branchId": branch_id,
                "facilityOwnerAgency": self._agency()})
            if not resp.get("branchId") or not resp.get("code"):
                raise RuntimeError(f"查询上报结果响应无效: {json.dumps(resp, ensure_ascii=False)[:300]}")
            code = str(resp.get("code", ""))
            # 处理中(10005/06) 或 批次尚未可查(10004——受理后异步落库有延迟) → 继续轮询
            if code in (CODE_SAVE_SUCCESS, CODE_HANDLING, CODE_BRANCH_ID_NOT_EXIST):
                LOG.info("[report] 批次 %s 未就绪(%s)，%ss 后重查...",
                         branch_id[:12], code, CHECK_POLL_INTERVAL)
                time.sleep(CHECK_POLL_INTERVAL)
                continue
            return resp   # 终态
        LOG.warning("[report] 批次 %s 检核轮询超时(%s次)", branch_id[:12], CHECK_POLL_MAX)
        return resp

    def check_result_once(self, branch_id: str) -> dict:
        """查批次处理结果（单次，不轮询）——续查补拉行级失败明细用。

        人行检核慢的批次在任务挂 pendingCheck 后行级失败码才出现在
        selectUploadData 的 data[] 里；下次运行续查时组状态已到 40001 等
        OK 终态，但行级明细必须再拉一次才不漏（2026-09-07 现场 switches
        产品序列号重复异常漏记的根因）。任何异常由调用方兜底。
        """
        uri = (self.conf.get("checkResultUri")
               or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData")
        return self._post(uri, {
            "branchId": branch_id, "facilityOwnerAgency": self._agency()})


# ============================================================================
# 数据原文持久化（磁盘）+ 任务历史（CMDB）
# ============================================================================

def _data_dir() -> Path:
    p = Path(DATA_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_report_data(task_id: str, payload: dict) -> str:
    """上报数据原文落磁盘: DATA_DIR/<日期>/<taskId>.json。返回绝对路径。"""
    day_dir = _data_dir() / time.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    f = day_dir / f"{task_id}.json"
    f.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(f)


def load_report_data(data_file: str) -> dict:
    return json.loads(Path(data_file).read_text(encoding="utf-8"))


def upsert_task(task: dict) -> None:
    cmdb_import(OBJ_TASK, ["taskId"], [task])


def find_task(task_id: str) -> dict | None:
    rows = cmdb_search_all(OBJ_TASK, fields=None, expr=f'taskId = "{task_id}"')
    return rows[0] if rows else None


# ============================================================================
# report: 单模型上报管线
# ============================================================================

# 单条数据判定（Go instReportResSuccess 同款 + 非终态码扩展）
# 成功: WL-20000(检核通过)/WL-20003(通过有警告)
_CODE_ROW_OK = ("WL-20000", "WL-20003")
# 非终态（处理中/等待，不算失败也不算成功——后续轮询消化）:
#   WL-20004 等待逻辑检核 / WL-10005 已保存 / WL-10006 处理中
#   WL-10004 批次未落查 / WL-40000 组等待逻辑检核开始
_CODE_ROW_PENDING = ("WL-20004", "WL-10005", "WL-10006", "WL-10004", "WL-40000", "")

# WL-20003 同码双义: 接入规范=「数据入库成功但存在警告」(成功侧)，但人行现场
# 用它返回「处理失败:【数据已存在】不可重复报送」(失败侧, 2026-09-07 现场日志
# dataCenter 19 条全为此)——按 msg 失败关键词判别，避免误当成功漏记失败明细
_ROW_FAIL_MSG_KEYS = ("失败", "不可重复", "已存在")


def _row_failed(code: str, msg: str = "") -> bool:
    """人行单条状态码是否为【终态失败】——既非成功码也非处理中码才算失败。

    WL-20003 特例: msg 含失败关键词(数据已存在/不可重复报送)按失败计，
    否则按规范的「成功带警告」计。
    """
    if code in _CODE_ROW_OK:
        if code == "WL-20003" and any(k in msg for k in _ROW_FAIL_MSG_KEYS):
            return True
        return False
    return code not in _CODE_ROW_PENDING


def _exists_unchanged(desc: str, converted_inst: dict, exists_map: dict[str, str]) -> bool:
    """实例在已存在基准中且内容 hash 与撞墙时一致 → True（跳过上报）。

    数据变了（hash 失配）→ False，恢复上报——新内容人行库没有，重报是
    把人行侧刷成最新版本的机会。
    """
    h = exists_map.get(desc)
    if not h:
        return False
    return h == _inst_content_hash(converted_inst)


def _row_already_exists(code: str, msg: str) -> bool:
    """行级回执是否为「数据已存在」类（WL-20003 + 已存在 msg）。

    人行说「已存在」= 库里已有该实例——这是一次明确的对账信号：数据没变的
    情况下重报必再撞（v1.0.30 前的缺陷：fail 实例不在比对基准里，每次运行
    都重报都失败）。据此把实例纳入 alreadyExists 基准：内容 hash 与撞墙时
    一致 → 下次跳过；变更 → 恢复上报（刷人行库为最新内容的机会）。
    """
    return code == "WL-20003" and any(k in msg for k in ("已存在", "不可重复"))


def _collect_branch_row_fails(center: "ReportCenter", branch_ids: list[str],
                              object_id: str, task_id: str,
                              fail_details: list[dict]) -> set[str]:
    """组终态成功后逐批次补拉行级失败明细（组 OK ≠ 行级全过）。

    人行检核慢：批次级 check_result 轮询(50s)期间行级码多为 20004 处理中，
    行级失败码（20001 检核未通过/20002 入库失败/20003 数据已存在）常在
    轮询超时后才出现——组到 40001 等 OK 终态时必须再拉一次 selectUploadData
    才不漏（v1.0.27 现场 switches 9 条重复异常漏记根因）。单次查询不轮询；
    收集进 fail_details（同实例跨批次去重），返回失败实例 descriptor 集合
    （调用方据此跳过 confirmed/计数，防 clear_fail_details 误删明细——
    v1.0.27 现场 uninterrupted 3 条明细落库后被误删根因）。
    """
    failed_descs: set[str] = set()
    exists_descs: set[str] = set()   # 「数据已存在」实例（v1.0.30 双基准）
    for bid in branch_ids:
        bid = str(bid).strip()
        if not bid:
            continue
        try:
            bd = center.check_result_once(bid)
        except Exception as e:
            LOG.warning("[report] %s 批次 %s 行级明细补拉失败（跳过该批）: %s",
                        object_id, bid[:20], e)
            continue
        for bad in bd.get("data") or []:
            bcode, bmsg = str(bad.get("code", "")), str(bad.get("msg", ""))
            if not _row_failed(bcode, bmsg):
                continue
            bdesc = str(bad.get("facilityDescriptor", ""))
            if bdesc in failed_descs:
                continue   # 同实例跨批次去重
            fail_details.append({
                "objectId": object_id, "taskId": task_id,
                "facilityDescriptor": bdesc,
                "facilityCategory": str(bad.get("facilityCategory", "")),
                "branchId": bid, "code": bcode, "msg": bmsg[:500]})
            failed_descs.add(bdesc)
            if _row_already_exists(bcode, bmsg):
                exists_descs.add(bdesc)
    return failed_descs, exists_descs


def _fail_summary(n_failed: int, details: list[dict],
                  batch_errors: list[dict] = None, group_err: str = "") -> str:
    """T6: 错误摘要——实例明细（前3条 descriptor→msg）+ 批次级错误（前3条）+ 组错误。
    完整实例明细在 INSTANCE 表；批次/组级错误只在此摘要与 branchList 留痕。
    """
    batch_errors = batch_errors or []
    if n_failed == 0 and not details and not batch_errors and not group_err:
        return ""
    parts = [f"{d['facilityDescriptor'][:12]}→{d['msg'][:40]}" for d in details[:3]]
    bparts = [f"批次{b.get('branchId', '')[-12:]}({b.get('type', '')}):"
              f"{b.get('code', '')} {str(b.get('msg', ''))[:40]}"
              for b in batch_errors[:3]]
    head = f"{max(n_failed, len(details))} 条失败"
    segs = []
    if parts:
        segs.append("; ".join(parts))
    if bparts:
        segs.append(" | 批次错误: " + "; ".join(bparts))
    if group_err:
        segs.append(f" | 组: {group_err[:60]}")
    return head + (": " + "".join(segs) if segs else "")


def save_fail_details(details: list[dict]) -> int:
    """T5: 失败明细逐条落 FINTECH_REPORT_INSTANCE（detailId 唯一，幂等覆盖）。"""
    if not details:
        return 0
    import uuid as _uuid
    # detailId = <facilityDescriptor>_<branchId>：按设施标识符+批次定位——用户在
    # INSTANCE 表按 facilityDescriptor 过滤即知哪个实例有问题、什么问题；同实例同批
    # 次重跑幂等覆盖（刷新最新检核结果），不同批次各留一行（失败历史可追溯）
    datas = []
    for d in details:
        row = dict(d)
        row["detailId"] = "%s_%s" % (d.get("facilityDescriptor", "unknown")[:36],
                                     d.get("branchId", "nobranch")[-16:])
        datas.append(row)
    r = cmdb_import(OBJ_FAIL_DETAIL, ["detailId"], datas)
    return r.get("insert", 0) + r.get("update", 0)


def clear_fail_details(object_id: str, descriptors: list[str]) -> int:
    """实例上报成功后自动移除其失败明细（INSTANCE 表按 objectId+descriptor 匹配）。

    detailId 键含批次号无法直接定位，须按字段查 v2（objectId 精确 + descriptor $in）。
    无失败记录时静默跳过。
    """
    if not descriptors:
        return 0
    removed = 0
    for i in range(0, len(descriptors), 50):
        chunk = descriptors[i:i + 50]
        conds = [{"objectId": object_id},
                 {"facilityDescriptor": {"$in": chunk}}]
        out, page = [], 1
        while True:
            body = {"query": {"$and": conds},
                    "fields": {"instanceId": True, "detailId": True},
                    "page": page, "pageSize": 200}
            d = cmdb_post(f"/v2/object/{urllib.parse.quote(OBJ_FAIL_DETAIL, safe='@')}/instance/_search", body)
            data = d.get("data") or {}
            out.extend(data.get("list") or [])
            if len(out) >= (data.get("total") or len(out)):
                break
            page += 1
        ids = [r["instanceId"] for r in out if r.get("instanceId")]
        if ids:
            failed = cmdb_delete(OBJ_FAIL_DETAIL, ids)
            n = len(ids) - len(failed)
            removed += n
            if n:
                LOG.info("[report] %s 成功实例清理失败明细 %d 条", object_id, n)
    return removed


def _data_type(object_id: str) -> str:
    """外层 dataType = 数据元类型标识 = 模型 id 去掉 @命名空间（Go getReportDataType）。

    ⚠️ 与外层 dataType 区分: 行内 reportDataType 才是传输标识(new/update/delete)。
    """
    return object_id.split("@")[0]


def _inst_content_hash(converted: dict) -> str:
    return hashlib.md5(json.dumps(converted, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def report_one_model(rule: dict, report_obj: dict, conf: dict, variant: str) -> dict:
    """单模型一次上报。返回任务记录（已写 CMDB + 原文已落盘）。

    增量逻辑（P1，替代 Go compareWithExisted + fintech_report_data 台账）:
      取该 objectId 最近一次 success 且未回滚的任务 → 读 dataFile 原文 →
      diff 出 new/update/delete；无历史任务（首次）则全量 new。
    """
    object_id = rule["objectId"]
    batch_num = int(rule.get("batchNum") or 100)
    task_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    task = {"taskId": task_id, "objectId": object_id,
            "configId": str(rule.get("instanceId", "")),
            "method": "api", "sponsor": conf.get("sponsor", "script"),
            "status": "reporting", "startTime": now, "insertCount": 0,
            "updateCount": 0, "removeCount": 0, "failedCount": 0,
            "rolledBack": False}
    try:
        converter = Converter(object_id, report_obj, rule.get("mappingRule"))
        # 0) 结算在途组: pendingCheck/inFlight 且带 groupId 的任务先查组现状——
        #    组到入库终态（40003 成功/40005 失败）→ 回写上任务结果；
        #    组仍在途（40001/40002 等人工）→ 任务 inFlight、实例冻结（diff 跳过），
        #    不再全量重报。状态闭环 v1.0.29。
        _settle_inflight_groups(object_id, conf, variant)
        # 1) 拉 CMDB 现值 + 转换 + 过滤 ignoreReport
        instances = cmdb_search_all(object_id)
        converted, pk_set = {}, {}
        ignored = 0
        for inst in instances:
            if str(inst.get(IGNORE_INST_ATTR, False)) in ("True", "true", True):
                ignored += 1
                continue
            data = converter.convert(inst)
            desc, cate = converter.pk_of(data)
            if not desc:
                continue
            converted[desc] = data
            pk_set[desc] = cate
        # 2) 增量 diff（对『成功实例台账』+『已存在基准』双基准；
        #    在途冻结集合内的实例一律跳过——检核已过等人工入库，重发会制造
        #    「数据已存在」，删除人行侧也未落地）
        confirmed, prev_meta, inflight_descs, exists_map = _last_success_data(object_id)
        new_items, update_items, delete_items = [], [], []
        if not confirmed:
            # 无成功台账（首次接入/全回滚后）→ 全部按 new
            new_items = [v for d, v in converted.items()
                         if d not in inflight_descs and not _exists_unchanged(
                             d, converted[d], exists_map)]
        else:
            for desc, data in converted.items():
                if desc in inflight_descs:
                    continue   # 在途冻结：不 new/update
                old = confirmed.get(desc)
                if _exists_unchanged(desc, data, exists_map):
                    continue   # 已存在且数据未变——重报必撞「数据已存在」，跳过
                if old is None:
                    new_items.append(data)              # 台账没有 → new
                elif old.get("_hash") != _inst_content_hash({k: v for k, v in data.items()}):
                    update_items.append(data)           # 内容变了 → update
                # 否则一致 → 不报（已确认且无变化）
            for desc, old in confirmed.items():
                if desc in inflight_descs:
                    continue   # 在途冻结：不生成 delete 行
                if desc not in converted:
                    # Go convertDeleteData: 从该实例上次成功快照取完整字段（人行对
                    # delete 行也校验归属机构等）；快照缺失退两键（Go RecoverReportInst）
                    snap = old.get("_snapshot") or {}
                    if snap:
                        row = dict(snap)
                        row[converter.key_desc] = desc
                        row[converter.key_cate] = old.get("_cate", "")
                    else:
                        row = {converter.key_desc: desc,
                               converter.key_cate: old.get("_cate", "")}
                    row.pop("_hash", None)
                    delete_items.append(row)
        # 3.1) 原文落盘（diff 基石）：本次实例先标 _confirmed=False，
        #      批次回执成功后置 True（见下方批次循环）；未变且历史已 confirmed 的直接继承；
        #      已存在基准未变（hash 一致）的继承 _alreadyExists（跳过的实例本任务
        #      不再上报，标记延续到本任务原文，保持基准连续——v1.0.30）
        payload_instances = {
            d: {**v, "_hash": _inst_content_hash(v), "_cate": pk_set[d], "_confirmed": False,
                "_snapshot": v}   # _snapshot: 转换数据原文（delete 行复用完整字段）
            for d, v in converted.items()}
        for desc in set(confirmed.keys()) & converted.keys():
            old = confirmed[desc]
            if old.get("_hash") == _inst_content_hash({k: v for k, v in converted[desc].items()}):
                payload_instances[desc]["_confirmed"] = True
        for desc in set(exists_map.keys()) & converted.keys():
            if _exists_unchanged(desc, converted[desc], exists_map):
                payload_instances[desc]["_alreadyExists"] = True
        payload = {"objectId": object_id, "taskId": task_id, "exportedAt": now,
                   "instances": payload_instances}
        task["dataFile"] = save_report_data(task_id, payload)
        # 3.2) 分批上报（new/update 各自成批；delete 一批）——批次成功即标记实例 confirmed
        center = ReportCenter(conf, variant)
        branch_ids = []
        branch_meta: list[dict] = []   # T4: 每批次 {branchId,type,count,status,code,msg}
        fail_details: list[dict] = []  # T5: 失败数据明细（人行 data[] 逐条）
        counts = {"insert": 0, "update": 0, "remove": 0, "failed": 0}
        counted: set = set()   # 已计数实例 (rtype, desc)——批次级与组级补计防重
        batch_errors: list[dict] = []   # T4b: 批次级错误留痕（未受理/check异常/检核失败）
        type_count_key = {"new": "insert", "update": "update", "delete": "remove"}
        for rtype, items in ((REPORT_TYPE_NEW, new_items),
                             (REPORT_TYPE_UPDATE, update_items),
                             (REPORT_TYPE_DELETE, delete_items)):
            for i in range(0, len(items), batch_num):
                batch = items[i:i + batch_num]
                branch_id = uuid.uuid4().hex[:16]
                # 外层 dataType = 数据元类型标识(模型名去命名空间)；
                # 行内 reportDataType = 传输标识(new/update/delete)
                for item in batch:
                    item["reportDataType"] = rtype
                resp = center.report_data(branch_id, [{"dataType": _data_type(object_id), "dataList": batch}])
                real_bid = resp["branchId"]      # 人行真批次号（BA开头）——check 用它
                branch_ids.append(real_bid)
                # WL-10000 只表受理——查 check_result 终态才 confirmed
                if resp["code"] != CODE_REPORT_SUCCESS:
                    counts["failed"] += len(batch)
                    batch_errors.append({"branchId": real_bid, "type": rtype,
                                         "count": len(batch), "code": resp["code"],
                                         "msg": f"上报未受理: {resp['msg'][:150]}"})
                    branch_meta.append({"branchId": real_bid, "type": rtype,
                                       "count": len(batch), "status": "fail",
                                       "code": resp["code"], "msg": resp["msg"][:200]})
                    LOG.warning("[report] %s %s 上报未受理: %s %s",
                                object_id, rtype, resp["code"], resp["msg"][:100])
                    continue
                try:
                    chk = center.check_result(real_bid)
                except Exception as ce:
                    LOG.warning("[report] %s %s check 异常: %s → 本批不入 confirmed（下次重报）",
                                object_id, rtype, ce)
                    batch_errors.append({"branchId": real_bid, "type": rtype,
                                         "count": len(batch), "code": "CHECK_ERROR",
                                         "msg": f"结果查询异常(下次重报): {str(ce)[:150]}"})
                    branch_meta.append({"branchId": real_bid, "type": rtype,
                                       "count": len(batch), "status": "fail",
                                       "code": "CHECK_ERROR",
                                       "msg": f"结果查询异常: {str(ce)[:200]}"})
                    task["status"] = "pendingCheck"   # 非终态——下次续查
                    continue
                chk_code = str(chk.get("code", ""))
                # T5: 单条失败明细——只收【终态失败】（成功/处理中/等待检核都不算；
                # WL-20003 数据已存在按失败收，见 _row_failed msg 判别）
                for bad in chk.get("data") or []:
                    if _row_failed(str(bad.get("code", "")), str(bad.get("msg", ""))):
                        fail_details.append({
                            "objectId": object_id, "taskId": task_id,
                            "facilityDescriptor": str(bad.get("facilityDescriptor", "")),
                            "facilityCategory": str(bad.get("facilityCategory", "")),
                            "branchId": real_bid, "code": str(bad.get("code", "")),
                            "msg": str(bad.get("msg", ""))[:500]})
                if chk_code in (CODE_HANDLE_SUCCESS, CODE_HANDLE_WITH_WARN):
                    counts[type_count_key[rtype]] += len(batch)
                    for item in batch:
                        desc = item.get(converter.key_desc)
                        counted.add((rtype, desc))
                        if desc and desc in payload_instances:
                            payload_instances[desc]["_confirmed"] = True
                    branch_meta.append({"branchId": real_bid, "type": rtype,
                                       "count": len(batch), "status": "success",
                                       "code": chk_code})
                elif chk_code in (CODE_SAVE_SUCCESS, CODE_HANDLING, CODE_BRANCH_ID_NOT_EXIST):
                    # 10005/10006=处理中；10004=刚受理尚未可查——均未到终态
                    LOG.info("[report] %s %s 批次 %s 未到终态(%s) → pendingCheck",
                             object_id, rtype, real_bid[:20], chk_code)
                    task["status"] = "pendingCheck"
                    branch_meta.append({"branchId": real_bid, "type": rtype,
                                       "count": len(batch), "status": "pending",
                                       "code": chk_code})
                else:
                    counts["failed"] += len(batch)
                    batch_errors.append({"branchId": real_bid, "type": rtype,
                                         "count": len(batch), "code": chk_code,
                                         "msg": str(chk.get("msg", ""))[:150]})
                    LOG.warning("[report] %s %s 处理失败: %s %s",
                                object_id, rtype, chk_code, str(chk.get("msg", ""))[:100])
                    branch_meta.append({"branchId": real_bid, "type": rtype,
                                       "count": len(batch), "status": "fail",
                                       "code": chk_code, "msg": str(chk.get("msg", ""))[:200]})
        # check 已在批次循环内完成（轮询终态）

        # 5.2.3 检核请求（时序③）: 规则实例 autoRequestCheck=true 且有已受理批次时触发，
        # 得 G 系列批次组号记入任务；随后查批次组状态辅助判定
        group_id = ""
        group_code, group_msg = "", ""
        if str(rule.get("autoRequestCheck", False)) in ("True", "true", True) and branch_ids:
            try:
                audit_resp = center.request_check(branch_ids)
                group_id = audit_resp.get("groupId", "")
                task["groupId"] = group_id
                # 5.2.5 批次组状态（处理中 data 为空；完成 data 只含异常批次）
                gs = center.group_status(group_id, wait_terminal=True)
                group_code, group_msg = str(gs.get("code", "")), str(gs.get("msg", ""))[:200]
                for bad in gs.get("data") or []:
                    LOG.warning("[report] %s 批次组异常批次: %s %s %s", object_id,
                                str(bad.get("branchId", ""))[:24], bad.get("code", ""),
                                str(bad.get("msg", ""))[:100])
                # T5: 组异常批次逐个查 selectUploadData 拿数据级失败原因；
                # 同时回写 branch_meta——批次级 selectUploadData 查成功 ≠ 组级
                # 逻辑检核通过，异常批次在 branchList 里必须从 success 纠正为 fail，
                # 否则多批次组场景任务表看到的批次状态与实际不符（错误记录不全主因）
                for bad_branch in gs.get("data") or []:
                    bad_bid = str(bad_branch.get("branchId", ""))
                    if not bad_bid or str(bad_branch.get("code", "")) in ("WL-10006",):
                        continue   # 处理中的不算
                    bad_code = str(bad_branch.get("code", ""))
                    bad_msg = str(bad_branch.get("msg", ""))[:200]
                    # 回写 branchList: 该批次组级检核失败
                    bm = next((b for b in branch_meta if b.get("branchId") == bad_bid), None)
                    if bm is not None:
                        bm["status"] = "fail"
                        bm["code"] = bad_code
                        bm["msg"] = f"组检核失败: {bad_msg}"
                    else:
                        branch_meta.append({"branchId": bad_bid, "type": "?", "count": 0,
                                           "status": "fail", "code": bad_code, "msg": bad_msg})
                    batch_errors.append({"branchId": bad_bid, "type": (bm or {}).get("type", "?"),
                                         "count": (bm or {}).get("count", 0),
                                         "code": bad_code, "msg": bad_msg})
                    try:
                        bd = center.check_result(bad_bid)
                        for bad in bd.get("data") or []:
                            if _row_failed(str(bad.get("code", "")), str(bad.get("msg", ""))):
                                fail_details.append({
                                    "objectId": object_id, "taskId": task_id,
                                    "facilityDescriptor": str(bad.get("facilityDescriptor", "")),
                                    "facilityCategory": str(bad.get("facilityCategory", "")),
                                    "branchId": bad_bid, "code": str(bad.get("code", "")),
                                    "msg": str(bad.get("msg", ""))[:500]})
                    except Exception as ce:
                        LOG.warning("[report] 异常批次 %s 明细查询失败: %s", bad_bid[:20], ce)
                # 组在途（40001/40002 检核已通过、入库申请等人工）→ 同样补拉
                # 行级明细：40001 = 逻辑检核已完成，行级失败码（20001 重复/
                # 20003 已存在）此刻已在 selectUploadData data[] 可查——不等
                # 入库终态（现场组可能长期停 40001，v1.0.29 曾把补拉推迟到
                # settle 导致 switches 9 条重复异常漏捕，2026-09-08 修正）。
                # 失败实例不确认不计数，也不进冻结集合（settle 解冻后重报/
                # 人工处理）；成功实例保持未 confirmed（等入库终态 settle 确认）。
                if group_code in ReportCenter._GROUP_INFLIGHT:
                    g_fail_descs, g_exists_descs = _collect_branch_row_fails(
                        center, branch_ids, object_id, task_id, fail_details)
                    if g_fail_descs:
                        batch_errors.append({"branchId": group_id, "type": "group",
                                             "count": len(g_fail_descs),
                                             "code": "ROW-FAIL",
                                             "msg": f"组检核通过但 {len(g_fail_descs)} 条实例行级失败"
                                                    f"（详见失败明细）"})
                    # 「数据已存在」实例打标（v1.0.30 双基准）：原文回写时置
                    # _alreadyExists，下次 diff 数据未变则跳过重报
                    for d in g_exists_descs:
                        if d in payload_instances:
                            payload_instances[d]["_alreadyExists"] = True
                    LOG.info("[report] %s 批次组 %s 在途(%s) → 任务 inFlight，"
                             "行级失败 %d 条已留明细（其中已存在 %d 条将跳过重报）",
                             object_id, group_id[:20], group_code,
                             len(g_fail_descs), len(g_exists_descs))
                # 组终态失败码（40005/40007 等）也留痕（在途码 40001/40002 不算失败）
                if group_id and group_code and group_code in ReportCenter._GROUP_FAIL:
                    batch_errors.append({"branchId": group_id, "type": "group",
                                         "count": len(branch_ids), "code": group_code,
                                         "msg": f"批次组终态失败: {group_msg}"})
                # 批次组到入库终态成功（40003/40004/40006）→ 先补拉行级失败
                # 明细再 confirmed。
                # 注: 组 STORED ≠ 行级全过——批次轮询(50s)期间人行检核未出结果的行
                #   全在 data[] 里（如 20004 处理中），行级失败码（20001/20002/
                #   20003 数据已存在）常在批次轮询超时后才出现；组分支若
                #   直接全量 confirmed，会把失败实例误当成功（v1.0.27 现场：
                #   switches 9 条产品序列号重复异常漏记、uninterrupted 3 条
                #   明细落库后被 clear_fail_details 误删——均为此路径）。
                if group_code in ReportCenter._GROUP_STORED and not (gs.get("data") or []):
                    # 组终态成功: 先逐批次补拉行级明细（单次不轮询），失败实例
                    # 计入 fail_details 且不 confirmed（不进台账/clear）
                    g_fail_descs, g_exists_descs = _collect_branch_row_fails(
                        center, branch_ids, object_id, task_id, fail_details)
                    # 「数据已存在」在入库终态成功语境下升级为 confirmed——
                    # 人行正式入库，实例在库是事实（v1.0.30）
                    for d in g_exists_descs:
                        if d in payload_instances:
                            payload_instances[d]["_confirmed"] = True
                    if g_fail_descs:
                        # 行级失败也留批次级错误痕迹（errorMsg 摘要可见）
                        batch_errors.append({"branchId": group_id, "type": "group",
                                             "count": len(g_fail_descs),
                                             "code": "ROW-FAIL",
                                             "msg": f"组检核通过但 {len(g_fail_descs)} 条实例行级失败"
                                                    f"（详见失败明细）"})
                    # counts 补计（只补批次级轮询超时未计的，
                    # 已计过的用 counted 防重——否则快速成功场景翻倍）
                    for rtype, items in ((REPORT_TYPE_NEW, new_items),
                                           (REPORT_TYPE_UPDATE, update_items)):
                        for item in items:
                            desc = item.get(converter.key_desc)
                            if desc in g_fail_descs:
                                continue   # 行级检核失败——不计数不确认
                            if (rtype, desc) in counted:
                                continue   # 批次级已计，不重复
                            counts[type_count_key[rtype]] += 1
                            counted.add((rtype, desc))
                            if desc and desc in payload_instances:
                                payload_instances[desc]["_confirmed"] = True
                    for item in delete_items:
                        desc = item.get(converter.key_desc)
                        if ("delete", desc) in counted:
                            continue
                        counts["remove"] += 1
                        counted.add(("delete", desc))
                    LOG.info("[report] %s 批次组 %s 终态成功 → confirmed %d 实例"
                             "（行级失败 %d 条已留明细）",
                             object_id, group_id[:20],
                             sum(1 for v in payload_instances.values() if v.get("_confirmed")),
                             len(g_fail_descs))
            except Exception as e:
                group_msg = f"检核请求失败: {e}"
                LOG.warning("[report] %s 检核请求异常: %s", object_id, e)
        # 状态优先级: 组入库终态成功 > 组终态失败 > inFlight(检核通过等人工)
        #   > pendingCheck > fail/partial
        # 注: 组终态失败(40005)必须压过批次轮询残留的 pendingCheck——组已终态
        # 失败，批次级"下次续查"已无意义（v1.0.29 现场 run3 实测修正）
        group_ok = (group_code in ReportCenter._GROUP_STORED and not (gs.get("data") or [])) if group_id else False
        group_inflight = (group_id and group_code in ReportCenter._GROUP_INFLIGHT)
        any_confirmed = any(v.get("_confirmed") for v in payload_instances.values())
        if group_ok or any_confirmed:
            final_status = "success" if not fail_details else "partialSuccess"
        elif group_id and group_code in ReportCenter._GROUP_FAIL:
            final_status = "fail"   # 组入库终态失败（驳回等）——不等待续查
        elif group_inflight:
            # 检核已通过，入库申请等人工——下次运行结算；行级有失败则
            # partialSuccess 优先（失败要立刻可见，不能藏在 inFlight 里）
            final_status = "partialSuccess" if fail_details else "inFlight"
        elif task.get("status") == "pendingCheck":
            final_status = "pendingCheck"
        else:
            # 无组信号时: 只有批次级终态计数(counts)才算数; 无失败但也无任何
            # 终态成功计数且有上报动作 → 未获任何终态结论 → pendingCheck
            if not fail_details and not batch_errors \
                    and counts["insert"] + counts["update"] + counts["remove"] == 0 \
                    and (new_items or update_items or delete_items):
                final_status = "pendingCheck"   # 全部批次未到终态,下次续查
            else:
                final_status = ("success" if not fail_details and not batch_errors
                                else ("fail" if counts["insert"] + counts["update"] + counts["remove"] == 0
                                      else "partialSuccess"))
        # 组错误单独判（组终态失败码且无任何实例确认 → 整体失败信号）
        group_fail = (group_id and group_code
                      and group_code in ReportCenter._GROUP_FAIL
                      and not any_confirmed)
        if group_fail and final_status not in ("pendingCheck", "inFlight"):
            final_status = "fail" if not any_confirmed else final_status
        # errorMsg 的组错误段: 组终态失败码才带（成功/等待码不带，避免误导）
        group_err_txt = group_msg if group_fail else ""
        task.update({"status": final_status,
                     "endTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "branchId": ",".join(branch_ids),
                     "insertCount": counts["insert"], "updateCount": counts["update"],
                     "removeCount": counts["remove"],
                     "failedCount": len(fail_details),   # 失败数=失败明细数（实例级终态失败）
                     "checkCode": group_code, "checkMsg": group_msg,
                     "branchList": branch_meta,
                     "errorMsg": _fail_summary(len(fail_details), fail_details,
                                               batch_errors, group_err=group_err_txt)})
        # 无上报项且无任何确认成功 → noReport；有确认（如历史批次刚转成功）保持原状态
        if not new_items and not update_items and not delete_items and \
                not any(v.get("_confirmed") for v in payload_instances.values()):
            task["status"] = "noReport"
        # 回写原文（批次 confirmed 标记已更新，落盘供下次 diff 用）
        save_report_data(task_id, payload)
        n_detail = save_fail_details(fail_details)
        if n_detail:
            LOG.info("[report] %s 失败明细落库 %d 条（FINTECH_REPORT_INSTANCE）", object_id, n_detail)
        # 本轮确认成功的实例 → 自动移除其历史失败明细（修复后重报成功的闭环）
        ok_descs = [d for d, v in payload_instances.items() if v.get("_confirmed")]
        if ok_descs and task.get("status") in ("success", "partialSuccess", "noReport"):
            clear_fail_details(object_id, ok_descs)
        upsert_task(task)
        LOG.info("[report] %s: %d 实例（忽略 %d）→ new %d / update %d / delete %d，失败 %d，任务 %s",
                 object_id, len(converted), ignored, counts["insert"], counts["update"],
                 counts["remove"], len(fail_details), task_id)
        return task
    except Exception as e:
        tb = traceback.format_exc()
        task.update({"status": "fail", "endTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "errorMsg": str(e)[:500]})
        try:
            upsert_task(task)
        except Exception:
            pass
        LOG.error("[report] %s 失败: %s\n%s", object_id, e, tb)
        raise


def _settle_inflight_groups(object_id: str, conf: dict, variant: str) -> None:
    """结算在途任务的批次组（状态闭环的核心，"下次结算"的实现）。

    扫该 objectId 所有 pendingCheck / inFlight 且带 groupId 的任务（时间倒序），
    逐任务查组现状（不轮询，一次）：
      - 组到入库终态成功（40003/40004/40006，data 无异常批次）→ 先逐批次补拉
        行级失败明细（人行检核慢，行级失败码常在批次轮询超时后才出现——组
        STORED 不代表行级全过，不补拉则 INSTANCE 表漏明细）；失败实例从原文
        实例集剔除（不置 _confirmed，防进台账被误当已入库）→ 其余实例落
        _confirmed、任务转 success/partialSuccess、原文回写 + upsert。
        本次运行 diff 基准随之含这些实例 → 增量归零。
      - 组到入库终态失败（40005/40007）→ 任务转 fail + errorMsg 组失败信息；
        行级明细补拉落 INSTANCE；实例保持未 confirmed（下次自然重报，人行侧
        若已存在会以「数据已存在」明细留痕）。
      - 组在途（40001/40002）→ 任务标 inFlight（pendingCheck 的生命周期推进）；
        实例不动、原文不回写——在途冻结（diff 跳过，见 _last_success_data）。
      - 组仍在检核（40000）或查询异常 → 不动，本次正常增量上报。
    """
    rows = cmdb_search_task_v2(object_id, statuses=["pendingCheck", "inFlight"])
    if not rows:
        return
    rows.sort(key=lambda r: str(r.get("startTime", "")), reverse=True)
    pending = [r for r in rows if r.get("groupId")]
    if not pending:
        return   # 无组号（纯批次级超时）——无组可结算
    try:
        center = ReportCenter(conf, variant)
    except Exception as e:
        LOG.warning("[settle] %s ReportCenter 构造失败（跳过结算）: %s", object_id, e)
        return
    for prev in pending:
        _settle_one_group(center, prev, object_id)


def _settle_one_group(center: "ReportCenter", prev: dict, object_id: str) -> None:
    """结算单个在途任务的组（_settle_inflight_groups 的子步骤）。"""
    group_id = str(prev.get("groupId", ""))
    data_file = prev.get("dataFile")
    task_id_str = str(prev.get("taskId", ""))
    if not (group_id and data_file and Path(data_file).exists()):
        return
    try:
        gs = center.group_status(group_id, wait_terminal=False)
    except Exception as e:
        LOG.warning("[settle] %s 组 %s 状态查询失败（跳过，走正常上报）: %s",
                    object_id, group_id[:20], e)
        return
    code = str(gs.get("code", ""))
    if code in ReportCenter._GROUP_INFLIGHT:
        # 入库申请等人工——生命周期推进到 inFlight（幂等），实例冻结不动
        if str(prev.get("status", "")) != "inFlight":
            prev.update({"status": "inFlight",
                         "checkCode": code, "checkMsg": str(gs.get("msg", ""))[:200],
                         "endTime": time.strftime("%Y-%m-%d %H:%M:%S")})
            upsert_task(prev)
            LOG.info("[settle] %s 组 %s 在途(%s) → 任务 %s 转 inFlight（实例冻结）",
                     object_id, group_id[:20], code, task_id_str[:12])
        return
    if code not in ReportCenter._GROUP_STORED or (gs.get("data") or []):
        # 仍在检核 / 组级异常批次未清 / 组终态失败——失败路径走下方统一处理；
        # 检核中（40000 等）不动
        if code in ReportCenter._GROUP_FAIL:
            _settle_group_failed(center, prev, object_id, group_id, code, gs)
        else:
            LOG.info("[settle] %s 组 %s 未到终态(%s)——本次正常上报",
                     object_id, group_id[:20], code)
        return
    # ---- 入库终态成功：行级补拉 → confirmed → 任务收尾 ----
    try:
        payload = load_report_data(data_file)
    except Exception as e:
        LOG.warning("[settle] %s 旧任务原文读取失败: %s", object_id, e)
        return
    instances = payload.get("instances") if isinstance(payload, dict) else None
    if not isinstance(instances, dict):
        return
    fail_details: list[dict] = []
    branch_ids_prev = [b for b in str(prev.get("branchId", "") or "").split(",") if b.strip()]
    failed_descs, exists_descs = _collect_branch_row_fails(center, branch_ids_prev, object_id,
                                                           task_id_str, fail_details)
    if fail_details:
        save_fail_details(fail_details)
        # 失败实例处理: 非「已存在」的从原文剔除（下次重报）；「已存在」的
        # 打 _alreadyExists 保留在原文（v1.0.30 双基准——数据未变跳过重报，
        # 变更后自然恢复），partialSuccess 由任务状态体现
        for desc in failed_descs:
            if desc in exists_descs:
                if desc in instances and isinstance(instances[desc], dict):
                    instances[desc]["_alreadyExists"] = True
                continue
            instances.pop(desc, None)
        LOG.warning("[settle] %s 组 STORED 但补拉到 %d 条行级失败明细——任务转 "
                    "partialSuccess（已存在 %d 条入基准，其余不进台账）",
                    object_id, len(fail_details), len(exists_descs))
    n_conf = 0
    for desc, inst in instances.items():
        if isinstance(inst, dict) and not inst.get("_confirmed"):
            inst["_confirmed"] = True
            n_conf += 1
        if isinstance(inst, dict) and inst.get("_confirmed"):
            # 已确认（含入库终态下的已存在实例）——exists 标记使命完成清除，
            # confirmed 台账优先（避免双基准冗余与 hash 不一致的风险）
            inst.pop("_alreadyExists", None)
    save_report_data(task_id_str, payload)   # 原地回写同一文件
    n_ins = sum(1 for i in instances.values()
                if isinstance(i, dict) and str(i.get("_op", "new")) != "delete")
    if fail_details:
        prev.update({"status": "partialSuccess",
                     "failedCount": len(fail_details),
                     "errorMsg": _fail_summary(len(fail_details), fail_details)})
    else:
        prev.update({"status": "success",
                     "failedCount": 0,
                     "errorMsg": ""})
    prev.update({"endTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "checkCode": code, "checkMsg": str(gs.get("msg", ""))[:200],
                 "insertCount": prev.get("insertCount", 0) or n_ins,
                 "updateCount": prev.get("updateCount", 0),
                 "removeCount": prev.get("removeCount", 0)})
    upsert_task(prev)
    LOG.info("[settle] %s 组 %s 已到 %s → 任务 %s 转 %s（confirmed %d 实例），"
             "本次 diff 将归零", object_id, group_id[:20], code,
             task_id_str[:12], prev.get("status", ""), n_conf)


def _settle_group_failed(center: "ReportCenter", prev: dict, object_id: str,
                         group_id: str, code: str, gs: dict) -> None:
    """组终态失败（40005/40007）结算：任务 fail + 行级明细补拉。

    实例保持未 confirmed（不回写原文）——下次运行自然当 new 重报；人行侧若
    数据已实际存在，重报会以「数据已存在」失败明细留痕（含 alreadyExists 语义）。
    """
    task_id_str = str(prev.get("taskId", ""))
    gs_msg = str(gs.get("msg", ""))[:200]
    fail_details: list[dict] = []
    data_file = prev.get("dataFile")
    if data_file and Path(data_file).exists():
        # 组级异常批次 data[] 里的 branchId 逐个补拉行级失败原因
        for bad_branch in gs.get("data") or []:
            bad_bid = str(bad_branch.get("branchId", ""))
            if not bad_bid:
                continue
            try:
                bd = center.check_result_once(bad_bid)
                for bad in bd.get("data") or []:
                    bcode, bmsg = str(bad.get("code", "")), str(bad.get("msg", ""))
                    if _row_failed(bcode, bmsg):
                        fail_details.append({
                            "objectId": object_id, "taskId": task_id_str,
                            "facilityDescriptor": str(bad.get("facilityDescriptor", "")),
                            "facilityCategory": str(bad.get("facilityCategory", "")),
                            "branchId": bad_bid, "code": bcode, "msg": bmsg[:500]})
            except Exception as e:
                LOG.warning("[settle] %s 异常批次 %s 明细补拉失败: %s",
                            object_id, bad_bid[:20], e)
    if fail_details:
        save_fail_details(fail_details)
    prev.update({"status": "fail",
                 "endTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "checkCode": code, "checkMsg": gs_msg,
                 "failedCount": len(fail_details),
                 "errorMsg": _fail_summary(len(fail_details), fail_details,
                                           group_err=f"批次组终态失败({code}): {gs_msg}")})
    upsert_task(prev)
    LOG.warning("[settle] %s 组 %s 终态失败(%s) → 任务 %s 转 fail（%d 条行级明细），"
                "实例下次重报", object_id, group_id[:20], code,
                task_id_str[:12], len(fail_details))


def _last_success_data(object_id: str) -> tuple[dict, dict | None, set[str], dict[str, str]]:
    """该模型的『成功实例台账』+ 在途冻结集合 + 已存在基准。

    台账来源：扫该 objectId 所有 success/partialSuccess 且未回滚任务（按时间倒序），
    合并各任务原文里 _confirmed=True 的实例（去重，新覆盖旧）。

    漏洞修复（2026-08-26）：
      旧逻辑只取『最近一条 success 任务的整体原文』做 diff——若 T2 失败而 T1 成功，
      基准仍是 T1，T2 已上报成功的批次被误判为『未变化』→ 漏报。
      新逻辑用『实例级 confirmed 标记』，只对确认接收过的实例 diff；
      失败批次（未 confirmed）下次自动当 new 重报。
      partialSuccess 的成功批次也计入 confirmed，不再整任务丢弃。

    v1.0.29 在途冻结：inFlight 任务的原文实例（检核已过、入库申请等人工）
    一律计入 inflight_descs——diff 跳过（不 new/update/delete），防止入库
    申请期间重复报送制造「数据已存在」；结算后按终态自然解冻。

    v1.0.30 已存在基准（双基准防重复上报）：扫所有任务原文（不限状态，
    时间倒序新覆盖旧）里 _alreadyExists=True 的实例 → exists_map{desc: hash}。
    人行「数据已存在」= 库里已有该实例的对账信号——数据未变（hash 一致）
    重报必再撞，diff 跳过；数据变更后 hash 失配 → 自然恢复上报。已存在
    实例后续被 confirmed（组入库终态成功）时以台账优先（新覆盖）。
    """
    confirmed: dict[str, dict] = {}
    inflight_descs: set[str] = set()
    exists_map: dict[str, str] = {}
    # 在途冻结集合（inFlight 任务原文的全部实例）
    for r in cmdb_search_task_v2(object_id, statuses=["inFlight"]):
        f = r.get("dataFile")
        if not (f and Path(f).exists()):
            continue
        try:
            data = load_report_data(f)
        except Exception:
            continue
        instances = data.get("instances") if isinstance(data, dict) else None
        if not isinstance(instances, dict):
            continue
        for desc in instances:
            inflight_descs.add(desc)
    # 已存在基准：扫全部未回滚任务原文（新覆盖旧——最新一次的撞墙 hash 为准）
    for r in cmdb_search_task_v2(object_id, statuses=None):
        f = r.get("dataFile")
        if not (f and Path(f).exists()):
            continue
        try:
            data = load_report_data(f)
        except Exception:
            continue
        instances = data.get("instances") if isinstance(data, dict) else None
        if not isinstance(instances, dict):
            continue
        for desc, inst in instances.items():
            if isinstance(inst, dict) and inst.get("_alreadyExists"):
                h = str(inst.get("_hash") or "")
                if h:
                    exists_map[desc] = h
    # 已存在实例后来被正式确认（confirmed）→ 从 exists 基准移除（台账优先）
    # （先扫 success 台账，再剔除——见下方 confirmed 收集后统一处理）
    prev_meta: dict | None = None
    rows = cmdb_search_task_v2(object_id, statuses=["success", "partialSuccess"])
    rows.sort(key=lambda r: str(r.get("startTime", "")), reverse=True)
    for r in rows:
        f = r.get("dataFile")
        if not (f and Path(f).exists()):
            continue
        try:
            data = load_report_data(f)
        except Exception:
            # 旧版/损坏原文（IO 错、JSON 坏、结构异）——跳过不让单个文件炸整个上报
            LOG.warning("[report] %s 历史原文读取失败，跳过: %s", object_id, f)
            continue
        if not isinstance(data, dict):
            continue
        if prev_meta is None:
            prev_meta = data
        # 合并该任务里 confirmed 的实例（旧任务先放、新任务覆盖 → 取最新 hash）
        # 防御: 历史原文结构可能异常（旧版本落盘/损坏）——instances 非 dict 或
        # 实例 value 非 dict 的条目跳过，不让单个坏文件炸整个上报
        instances = data.get("instances") if isinstance(data, dict) else None
        if not isinstance(instances, dict):
            LOG.warning("[report] %s 历史原文结构异常（instances 非 dict），跳过该文件: %s",
                        object_id, f)
            continue
        for desc, inst in instances.items():
            if isinstance(inst, dict) and inst.get("_confirmed"):
                confirmed[desc] = inst
                exists_map.pop(desc, None)   # 已正式确认——已存在基准让位
    _dbg_ledger(object_id, confirmed, inflight_descs, exists_map)
    return confirmed, prev_meta, inflight_descs, exists_map


def _dbg_ledger(object_id: str, confirmed: dict, inflight: set, exists: dict) -> None:
    LOG.debug("[report] %s 台账: confirmed=%d inflight=%d alreadyExists=%d",
              object_id, len(confirmed), len(inflight), len(exists))


def _confirmed_snapshot(payload: dict) -> dict[str, dict]:
    """从任务原文 payload 提取 confirmed 实例集合（供 diff 用）。"""
    return {d: inst for d, inst in (payload.get("instances") or {}).items()
            if inst.get("_confirmed")}


def cmd_report(scope: str) -> int:
    conf = load_global_config()
    rules = load_rules(scope)
    objects = load_report_objects()
    variant = "pboc"
    LOG.info("[report] 全局配置: %s @ %s:%s | 规则 %d 条%s",
             conf.get("name", ""), conf.get("ip"), conf.get("port"), len(rules),
             f"（scope: {scope}）" if scope else "（全量）")
    rc = 0
    for rule in rules:
        oid = rule.get("objectId", "")
        if not oid:
            continue
        report_obj = objects.get(oid)
        if not report_obj:
            LOG.warning("[report] %s 无 objectDefine（规则实例未同步模型定义），跳过", oid)
            continue
        try:
            report_one_model(rule, report_obj, conf, variant)
        except Exception as e:
            LOG.error("[report] %s 任务失败: %s\n%s", oid, e, traceback.format_exc())
            rc = 1
    # 上报完成后自动清理（v1.0.29 内联）：按 FINTECH_REPORT_CLEANUP 规则执行
    # （默认不启用=不清理）；清理失败只告警，不影响上报结果码
    try:
        cleaned = cleanup_after_report()
        if cleaned:
            LOG.info("[report] 收尾清理完成：%d 条历史任务（含级联明细）", cleaned)
    except Exception as e:
        LOG.warning("[report] 收尾清理失败（不影响上报结果）: %s", e)
    return rc


# ============================================================================
# rollback: 仅回滚本地状态
# ============================================================================

def cmd_rollback(task_id: str) -> int:
    task = find_task(task_id)
    if not task:
        LOG.error("[rollback] 任务不存在: %s", task_id)
        return 2
    if str(task.get("rolledBack", False)) in ("True", "true", True):
        LOG.warning("[rollback] 任务已回滚过: %s", task_id)
        return 0
    rollback_id = uuid.uuid4().hex
    rec = {"rollbackId": rollback_id, "taskId": task_id,
           "objectId": task.get("objectId", ""), "status": "rolling",
           "deleteCount": 0, "operator": CMDB_API["user"],
           "rollbackTime": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        # 本地回滚 = 任务标记 rolledBack（增量基准 _last_success_data 自动跳过它 →
        # 下次上报该模型无基准 → 全量 new 重报）。数据原文保留（回滚可追溯）。
        n = 0
        f = task.get("dataFile")
        if f and Path(f).exists():
            n = len(load_report_data(f).get("instances", {}))
        rec["deleteCount"] = n
        rec["status"] = "success"
        cmdb_import(OBJ_ROLLBACK, ["rollbackId"], [rec])
        upsert_task({**task, "rolledBack": True, "status": "rolledBack"})
        LOG.info("[rollback] 任务 %s（%s，%d 实例）已回滚本地状态；下次上报将全量重报",
                 task_id, task.get("objectId"), n)
        return 0
    except Exception as e:
        rec["status"] = "fail"
        rec["errorMsg"] = str(e)[:500]
        try:
            cmdb_import(OBJ_ROLLBACK, ["rollbackId"], [rec])
        except Exception:
            pass
        LOG.error("[rollback] 失败: %s\n%s", e, traceback.format_exc())
        return 1


# ============================================================================
# cleanup: 历史清理（条数 AND 天数，同时超出才清）
# ============================================================================

def cmd_cleanup(dry_run: bool = False) -> int:
    rules = [r for r in cmdb_search_all(OBJ_CLEANUP)
             if str(r.get("enabled", False)) in ("True", "true", True)]
    if not rules:
        LOG.info("[cleanup] 无启用的清理规则（默认不清理）——结束")
        return 0
    total_cleaned = 0
    for rule in rules:
        name = rule.get("name", "?")
        max_count = int(rule.get("maxCount") or 0)
        max_age = int(rule.get("maxAgeDays") or 0)
        scope = (rule.get("scope") or "").strip()
        if max_count == 0 and max_age == 0:
            # 双 0 = 全清模式：删除 scope 内全部任务（含回滚记录与原文文件）
            LOG.warning("[cleanup] 规则 %s 为全清模式（maxCount=0 且 maxAgeDays=0），"
                        "将删除%s全部任务记录", name, f"【{scope}】" if scope else "所有模型")
        elif max_count <= 0 or max_age <= 0:
            LOG.warning("[cleanup] 规则 %s 的 maxCount/maxAgeDays 未配置完整（需双正数=AND保留，"
                        "或双0=全清），跳过", name)
            continue
        # 目标模型集合
        if scope:
            oids = [s.strip() for s in scope.split(",") if s.strip()]
            tasks = []
            for oid in oids:
                tasks.extend(cmdb_search_all(OBJ_TASK, expr=f'objectId = "{oid}"'))
        else:
            tasks = cmdb_search_all(OBJ_TASK)
        # 按模型分组，各自：先按时间排序，超出「保留最近 N 条」且「早于 N 天前」才删（AND）
        by_obj: dict[str, list[dict]] = {}
        for t in tasks:
            by_obj.setdefault(t.get("objectId", ""), []).append(t)
        to_delete: list[dict] = []
        cutoff = time.time() - max_age * 86400
        purge_all = (max_count == 0 and max_age == 0)
        for oid, lst in by_obj.items():
            lst.sort(key=lambda t: str(t.get("startTime", "")), reverse=True)
            # diff 基准保护: 每模型最新一条 success/partialSuccess 任务的实例
            # 永不删——它是 _last_success_data 的基准来源，删了会基准归零 →
            # 下次全量重报 → 「数据已存在」风暴（v1.0.29 修复）
            base_keep = next((t.get("instanceId") for t in lst
                              if str(t.get("status", "")) in ("success", "partialSuccess")
                              and t.get("instanceId")), None)
            for idx, t in enumerate(lst):
                if t.get("instanceId") and t["instanceId"] == base_keep:
                    continue   # 基准任务保护（全清模式同样生效）
                if str(t.get("status", "")) in ("pendingCheck", "inFlight"):
                    continue   # 活动任务保护：组还可能结算，dataFile 是冻结来源
                if purge_all:
                    to_delete.append(t)   # 全清模式
                    continue
                if idx < max_count:
                    continue  # 还在最近 N 条内 → 保留
                st = t.get("startTime", "")
                try:
                    ts = time.mktime(time.strptime(str(st)[:19], "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    continue
                if ts < cutoff:  # 同时超出天数 → 清理
                    to_delete.append(t)
        LOG.info("[cleanup] 规则 %s: 清理候选 %d 条（已运行 %d 模型任务）",
                 name, len(to_delete), sum(len(v) for v in by_obj.values()))
        if dry_run:
            for t in to_delete:
                LOG.info("  将删: %s %s %s", t.get("taskId", "")[:12], t.get("objectId"), t.get("startTime"))
            continue
        # 级联删失败明细（v1.0.29）: 按被删任务 taskId 删 FINTECH_REPORT_INSTANCE
        detail_removed = _cleanup_fail_details_of_tasks([t.get("taskId", "") for t in to_delete])
        # 删 CMDB 任务 + 数据文件 + 级联回滚记录
        # 回滚记录一次全查建索引（避免每任务一次 CMDB 搜索的 N+1 慢查询）
        rb_index: dict[str, list[str]] = {}
        for r in cmdb_search_all(OBJ_ROLLBACK, fields=["taskId", "instanceId"]):
            rb_index.setdefault(str(r.get("taskId", "")), []).append(r["instanceId"])
        for t in to_delete:
            tid = t.get("taskId", "")
            rb_ids = [i for i in rb_index.get(tid, []) if i]
            if rb_ids:
                cmdb_delete(OBJ_ROLLBACK, rb_ids)
            if t.get("instanceId"):
                cmdb_delete(OBJ_TASK, [t["instanceId"]])
            f = t.get("dataFile")
            if f and Path(f).exists():
                Path(f).unlink()
            total_cleaned += 1
        if detail_removed:
            LOG.info("[cleanup] 级联清理失败明细 %d 条（FINTECH_REPORT_INSTANCE）", detail_removed)
        # 规则执行记录回写
        cmdb_import(OBJ_CLEANUP, ["name"], [{
            **rule, "name": name,
            "lastRunTime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lastCleanedCount": len(to_delete) + detail_removed}])
    LOG.info("[cleanup] 完成，共清理 %d 条任务", total_cleaned)
    return total_cleaned


def _cleanup_fail_details_of_tasks(task_ids: list[str]) -> int:
    """级联清理：按任务号删 FINTECH_REPORT_INSTANCE 失败明细（v1.0.29）。

    任务记录被清理后其明细即成孤儿（detailId 键不含 taskId，无法回查归属），
    必须随任务一并删除。taskId 分块 $in 查 v2（复用 clear_fail_details 模式）。
    """
    tids = [t for t in (str(t).strip() for t in task_ids) if t]
    if not tids:
        return 0
    removed = 0
    for i in range(0, len(tids), 50):
        chunk = tids[i:i + 50]
        out, page = [], 1
        while True:
            body = {"query": {"$and": [{"taskId": {"$in": chunk}}]},
                    "fields": {"instanceId": True, "detailId": True},
                    "page": page, "pageSize": 200}
            d = cmdb_post(f"/v2/object/{urllib.parse.quote(OBJ_FAIL_DETAIL, safe='@')}/instance/_search", body)
            data = d.get("data") or {}
            out.extend(data.get("list") or [])
            if len(out) >= (data.get("total") or len(out)):
                break
            page += 1
        ids = [r["instanceId"] for r in out if r.get("instanceId")]
        if ids:
            failed = cmdb_delete(OBJ_FAIL_DETAIL, ids)
            removed += len(ids) - len(failed)
    return removed


def cleanup_after_report() -> int:
    """上报完成后自动清理（v1.0.29 内联）：按启用规则执行，失败只告警不中断。

    调用方（cmd_report）以 try 包裹——清理异常不影响上报结果码。
    """
    return cmd_cleanup(dry_run=False)


# ============================================================================
# CLI
# ============================================================================

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="人行金融数据上报（单文件，配置在 CMDB）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_report = sub.add_parser("report", help="执行上报（留空 scope=全部启用规则）")
    p_report.add_argument("--scope", default="", help="逗号分隔 objectId；留空=全量")
    p_rb = sub.add_parser("rollback", help="回滚任务本地状态（下次全量重报）")
    p_rb.add_argument("--task", required=True, help="taskId")
    p_cl = sub.add_parser("cleanup", help="按清理规则清理历史（默认规则不启用=不清理）")
    p_cl.add_argument("--dry-run", action="store_true", help="只列不删")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if args.cmd == "report":
        return cmd_report(args.scope)
    if args.cmd == "rollback":
        return cmd_rollback(args.task)
    return cmd_cleanup(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
