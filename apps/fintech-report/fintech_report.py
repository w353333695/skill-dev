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
import urllib.error
import urllib.parse
import urllib.request
import uuid
import ssl
import traceback
from pathlib import Path
from typing import Any

# 内网部署常自签证书——人行 FICS 与 CMDB 网关 https 不校验
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


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

# ---- 内嵌上报策略（对应 Go conf.default.yaml report_conf 段；行数少，不值得外挂） ----
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
CODE_HANDLE_SUCCESS = "WL-10009"
CODE_HANDLE_WITH_WARN = "WL-10013"
CODE_DATA_VALID = "WL-20000"
CODE_DATA_VALID_WITH_WARNING = "WL-20003"

LOG = logging.getLogger("fintech-report")


# ============================================================================
# 通用层: HTTP / CMDB 客户端
# ============================================================================

def _http_json(method: str, url: str, body: Any = None, headers: dict | None = None,
              timeout: int = 30, retry: int = 3, retry_wait: int = 2) -> Any:
    """JSON HTTP 带重试；连接超时快速失败；DEBUG 打印摘要。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_err = None
    for attempt in range(1, retry + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if DEBUG:
            LOG.debug("[http] %s %s body=%s", method, url, (data or b"")[:500])
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            if DEBUG:
                LOG.debug("[http] ← %s", raw[:500])
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            last_err = RuntimeError(f"HTTP {e.code}: {detail or e.reason}")
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, OSError) and "timed out" in str(reason).lower():
                raise RuntimeError(f"对端不可达（连接超时）: {url}") from e
            last_err = RuntimeError(f"网络/解析错误: {e}")
        if attempt < retry:
            time.sleep(retry_wait)
    raise last_err  # type: ignore[misc]


def cmdb_post(path: str, body: dict) -> dict:
    headers = {"org": CMDB_API["org"], "user": CMDB_API["user"]}
    return _http_json("POST", CMDB_API["base_url"] + path, body, headers,
                      CMDB_API["timeout"], CMDB_API["retry"], CMDB_API["retry_wait"])


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
    req = urllib.request.Request(
        f"{CMDB_API['base_url']}/object/{urllib.parse.quote(object_id, safe='@')}/instance_batch"
        f"?instanceIds={urllib.parse.quote(ids_str)}",
        method="DELETE")
    req.add_header("org", CMDB_API["org"])
    req.add_header("user", CMDB_API["user"])
    with urllib.request.urlopen(req, timeout=CMDB_API["timeout"]) as resp:
        d = json.loads(resp.read())
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
            # 映射模式取源字段
            src_id = self.mapping.get(aid) or aid
            value = inst.get(src_id)
            atype = (attr.get("value") or {}).get("type", "str")
            # 人行要求空值传 ""（复合类型除外）
            if self._is_empty(value):
                if self._omitempty(aid):
                    continue  # 为空且 omitempty → 整个属性省略
                if atype in ("struct", "structs"):
                    continue  # 复合为空不上报
                out[aid] = ""
                continue
            out[aid] = self._transform(aid, atype, value, attr)
        return out

    def _is_empty(self, v: Any) -> bool:
        return v is None or v == "" or v == [] or v == {}

    def _transform(self, attr_id: str, atype: str, value: Any, attr: dict) -> Any:
        if atype == "str":
            return str(value)
        if atype == "bool":
            return "True" if value else "False"
        if atype == "int":
            return str(int(value))
        if atype == "float":
            prec = self.prec.get(attr_id, 2)
            return f"{float(value):.{prec}f}"
        if atype == "date":
            return str(value)[:10]
        if atype == "datetime":
            s = str(value)
            return s[:19]  # Go: 去秒（Split(":") 去最后一段）——保 19 位标准形态
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

    def _struct_obj(self, subs: list, data: dict) -> dict:
        out = {}
        for s in subs:
            sid = s.get("id", "")
            v = data.get(sid)
            st = s.get("type", "str")
            if self._is_empty(v):
                if st in ("struct", "structs"):
                    continue
                out[sid] = ""
                continue
            out[sid] = self._transform(sid, st, v, {"id": sid, "value": s})
        return out

    @staticmethod
    def _enum_code(value: Any) -> str:
        """'00-在用'/'00：在用'/'00:在用' → '00'；纯码原样。"""
        s = str(value)
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
        qs = urllib.parse.urlencode({
            "client_id": self.conf.get("clientId", ""),
            "client_secret": self.conf.get("clientSecret", ""),
            "grant_type": "client_credentials"})
        req = urllib.request.Request(f"{url}?{qs}", method="POST")
        req.add_header("Content-Type", "application/json")
        _opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX))
        with _opener.open(req, timeout=30) as resp:
            d = json.loads(resp.read())
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
        req = urllib.request.Request(full_url,
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Charset", "UTF-8")
        if self.variant == "pboc":
            req.add_header("X-Access-Token", self._get_token())
        try:
            _opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX))
            with _opener.open(req, timeout=60) as resp:
                return json.loads(resp.read())
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
        return {"branchId": resp.get("branchId", branch_id),
                "code": str(resp.get("code", "")), "msg": str(resp.get("msg", ""))[:500]}

    def check_result(self, branch_id: str) -> dict:
        """查询人行侧批次处理结果（check_job 用；本脚本 report 完成后自动查一次）。"""
        if self.variant == "zhongxin":
            return {"code": CODE_HANDLE_SUCCESS, "msg": "中信变体无结果查询", "data": []}
        resp = self._post(
            self.conf.get("checkResultUri")
            or "webproxy/fig2fics/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData", {
                "branchId": branch_id,
                "facilityOwnerAgency": self._agency()})
        if not resp.get("branchId") or not resp.get("code"):
            raise RuntimeError(f"查询上报结果响应无效: {json.dumps(resp, ensure_ascii=False)[:300]}")
        return resp


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

def _inst_content_hash(converted: dict) -> str:
    return hashlib.md5(json.dumps(converted, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def report_one_model(rule: dict, report_obj: dict, conf: dict, variant: str,
                     scope_full: bool) -> dict:
    """单模型一次上报。返回任务记录（已写 CMDB + 原文已落盘）。

    增量逻辑（P1，替代 Go compareWithExisted + fintech_report_data 台账）:
      取该 objectId 最近一次 success 且未回滚的任务 → 读 dataFile 原文 →
      diff 出 new/update/delete；无历史任务或 scope_full 则全量 new。
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
        # 2) 增量 diff（对『成功实例台账』: 跨任务合并的 confirmed 实例集合）
        confirmed, prev_meta = _last_success_data(object_id)
        new_items, update_items, delete_items = [], [], []
        if not confirmed or scope_full:
            new_items = list(converted.values())
        else:
            for desc, data in converted.items():
                old = confirmed.get(desc)
                if old is None:
                    new_items.append(data)              # 台账没有 → new
                elif old.get("_hash") != _inst_content_hash({k: v for k, v in data.items()}):
                    update_items.append(data)           # 内容变了 → update
                # 否则一致 → 不报（已确认且无变化）
            for desc, old in confirmed.items():
                if desc not in converted:
                    delete_items.append({converter.key_desc: desc,
                                         converter.key_cate: old.get("_cate", "")})
        # 3.1) 原文落盘（diff 基石）：本次实例先标 _confirmed=False，
        #      批次回执成功后置 True（见下方批次循环）；未变且历史已 confirmed 的直接继承
        payload_instances = {
            d: {**v, "_hash": _inst_content_hash(v), "_cate": pk_set[d], "_confirmed": False}
            for d, v in converted.items()}
        for desc in set(confirmed.keys()) & converted.keys():
            old = confirmed[desc]
            if old.get("_hash") == _inst_content_hash({k: v for k, v in converted[desc].items()}):
                payload_instances[desc]["_confirmed"] = True
        payload = {"objectId": object_id, "taskId": task_id, "exportedAt": now,
                   "instances": payload_instances}
        task["dataFile"] = save_report_data(task_id, payload)
        # 3.2) 分批上报（new/update 各自成批；delete 一批）——批次成功即标记实例 confirmed
        center = ReportCenter(conf, variant)
        branch_ids = []
        counts = {"insert": 0, "update": 0, "remove": 0, "failed": 0}
        type_count_key = {"new": "insert", "update": "update", "delete": "remove"}
        for rtype, items in ((REPORT_TYPE_NEW, new_items),
                             (REPORT_TYPE_UPDATE, update_items),
                             (REPORT_TYPE_DELETE, delete_items)):
            for i in range(0, len(items), batch_num):
                batch = items[i:i + batch_num]
                branch_id = uuid.uuid4().hex[:16]
                resp = center.report_data(branch_id, [{"dataType": rtype, "dataList": batch}])
                branch_ids.append(branch_id)
                if resp["code"] != CODE_REPORT_SUCCESS:
                    counts["failed"] += len(batch)
                    LOG.warning("[report] %s %s 批次失败: %s %s",
                                object_id, rtype, resp["code"], resp["msg"][:100])
                else:
                    counts[type_count_key[rtype]] += len(batch)
                    # 批次确认 → 原文里对应实例标 confirmed（new/update 按主键；delete 标记待剔除）
                    for item in batch:
                        desc = item.get(converter.key_desc)
                        if desc and desc in payload_instances:
                            payload_instances[desc]["_confirmed"] = True
        # 3.3) 查人行处理结果（首批）
        check_code, check_msg = "", ""
        if branch_ids:
            try:
                chk = center.check_result(branch_ids[0])
                check_code, check_msg = str(chk.get("code", "")), str(chk.get("msg", ""))[:200]
            except Exception as e:
                check_code, check_msg = "", f"结果查询失败: {e}"
        task.update({"status": "success" if counts["failed"] == 0 else
                     ("fail" if counts["insert"] + counts["update"] + counts["remove"] == 0
                      else "partialSuccess"),
                     "endTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "branchId": ",".join(branch_ids),
                     "insertCount": counts["insert"], "updateCount": counts["update"],
                     "removeCount": counts["remove"], "failedCount": counts["failed"],
                     "checkCode": check_code, "checkMsg": check_msg,
                     "errorMsg": "" if counts["failed"] == 0 else f"{counts['failed']} 条失败"})
        if not new_items and not update_items and not delete_items:
            task["status"] = "noReport"
        # 回写原文（批次 confirmed 标记已更新，落盘供下次 diff 用）
        save_report_data(task_id, payload)
        upsert_task(task)
        LOG.info("[report] %s: %d 实例（忽略 %d）→ new %d / update %d / delete %d，失败 %d，任务 %s",
                 object_id, len(converted), ignored, counts["insert"], counts["update"],
                 counts["remove"], counts["failed"], task_id)
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


def _last_success_data(object_id: str) -> tuple[dict, dict | None]:
    """该模型的『成功实例台账』: 已确认被人行接收的实例集合。

    台账来源：扫该 objectId 所有 success/partialSuccess 且未回滚任务（按时间倒序），
    合并各任务原文里 _confirmed=True 的实例（去重，新覆盖旧）。

    漏洞修复（2026-08-26）：
      旧逻辑只取『最近一条 success 任务的整体原文』做 diff——若 T2 失败而 T1 成功，
      基准仍是 T1，T2 已上报成功的批次被误判为『未变化』→ 漏报。
      新逻辑用『实例级 confirmed 标记』，只对确认接收过的实例 diff；
      失败批次（未 confirmed）下次自动当 new 重报。
      partialSuccess 的成功批次也计入 confirmed，不再整任务丢弃。
    """
    confirmed: dict[str, dict] = {}
    rows = cmdb_search_all(
        OBJ_TASK, fields=["taskId", "dataFile", "rolledBack", "startTime", "status"],
        expr=f'objectId = "{object_id}" AND status in ["success","partialSuccess"] '
             f'AND rolledBack = false')
    rows.sort(key=lambda r: str(r.get("startTime", "")), reverse=True)
    prev_meta: dict | None = None
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
    return confirmed, prev_meta


def _confirmed_snapshot(payload: dict) -> dict[str, dict]:
    """从任务原文 payload 提取 confirmed 实例集合（供 diff 用）。"""
    return {d: inst for d, inst in (payload.get("instances") or {}).items()
            if inst.get("_confirmed")}


def cmd_report(scope: str, full: bool) -> int:
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
            report_one_model(rule, report_obj, conf, variant, full)
        except Exception as e:
            LOG.error("[report] %s 任务失败: %s\n%s", oid, e, traceback.format_exc())
            rc = 1
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
        if max_count <= 0 or max_age <= 0:
            LOG.warning("[cleanup] 规则 %s 的 maxCount/maxAgeDays 未配置完整，跳过", name)
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
        for oid, lst in by_obj.items():
            lst.sort(key=lambda t: str(t.get("startTime", "")), reverse=True)
            for idx, t in enumerate(lst):
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
        # 删 CMDB 任务 + 数据文件 + 级联回滚记录
        for t in to_delete:
            tid = t.get("taskId", "")
            rb_ids = [r.get("instanceId") for r in cmdb_search_all(
                OBJ_ROLLBACK, expr=f'taskId = "{tid}"') if r.get("instanceId")]
            if rb_ids:
                cmdb_delete(OBJ_ROLLBACK, rb_ids)
            if t.get("instanceId"):
                cmdb_delete(OBJ_TASK, [t["instanceId"]])
            f = t.get("dataFile")
            if f and Path(f).exists():
                Path(f).unlink()
            total_cleaned += 1
        # 规则执行记录回写
        cmdb_import(OBJ_CLEANUP, ["name"], [{
            **rule, "name": name,
            "lastRunTime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lastCleanedCount": len(to_delete)}])
    LOG.info("[cleanup] 完成，共清理 %d 条任务", total_cleaned)
    return 0


# ============================================================================
# CLI
# ============================================================================

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="人行金融数据上报（单文件，配置在 CMDB）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_report = sub.add_parser("report", help="执行上报（留空 scope=全部启用规则）")
    p_report.add_argument("--scope", default="", help="逗号分隔 objectId；留空=全量")
    p_report.add_argument("--full", action="store_true", help="忽略增量直接全量 new")
    p_rb = sub.add_parser("rollback", help="回滚任务本地状态（下次全量重报）")
    p_rb.add_argument("--task", required=True, help="taskId")
    p_cl = sub.add_parser("cleanup", help="按清理规则清理历史（默认规则不启用=不清理）")
    p_cl.add_argument("--dry-run", action="store_true", help="只列不删")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if args.cmd == "report":
        return cmd_report(args.scope, args.full)
    if args.cmd == "rollback":
        return cmd_rollback(args.task)
    return cmd_cleanup(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
