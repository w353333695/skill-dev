# -*- coding: utf-8 -*-
"""
表单加载后脚本：按批次ID自动填告警故障管理单（模拟「通过url填充表单值」机制）

入参（平台注入）：
    batchId    当前表单批次控件的值（currentNode 类型 scriptInputs）
    formData   整张表单 JSON
输出：
    PutStr("formData", ...) —— afterDataLoad 返回改后表单
运行环境：EasyOps agent py2（ens_api 服务发现 + requests 可用）
"""
import json
import sys

import requests

reload(sys)
sys.setdefaultencoding("utf-8")

sys.path.append("/usr/local/easyops/ens_client/sdk/python_sdk")
import ens_api

EASYOPS_ORG = int(globals().get("EASYOPS_ORG") or 8888)
EASYOPS_USER = globals().get("EASYOPS_USER") or "easyops"

SEC_BASE = "sec_base"      # 基础信息容器 key
ALERT_SEC = "sec_alerts"   # 关联告警信息容器 key

# 告警 level → 表单枚举（与告警故障管理单 items 对齐）
LEVEL_P = {"critical": {"key": "p1", "label": "P1", "value": "P1"},
           "warning": {"key": "p2", "label": "P2", "value": "P2"},
           "info": {"key": "p4", "label": "P4", "value": "P4"}}
LEVEL_CN = {"critical": {"key": "critical", "label": "严重", "value": "严重"},
            "warning": {"key": "warning", "label": "警告", "value": "警告"},
            "info": {"key": "notice", "label": "通知", "value": "通知"}}
PRIORITY = {"critical": {"key": "urgent", "label": "紧急", "value": "紧急"},
            "warning": {"key": "urgent", "label": "紧急", "value": "紧急"},
            "info": {"key": "normal", "label": "普通", "value": "普通"}}


def get_alert_service():
    """ens 服务发现 alert_service；失败回退平台注入 host（与 cmdb 同机部署形态）。"""
    try:
        ret = ens_api.get_all_service_by_name("my_name", "logic.alert_service")
        # 返回形态兼容：list[[ip, port]] / (sid, "ip:port") / "ip:port"
        if isinstance(ret, (list, tuple)):
            for item in ret:
                if isinstance(item, str) and ":" in item:
                    return item
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    return "%s:%s" % (item[0], item[1])
        if isinstance(ret, str):
            return ret
    except Exception as e:
        print "ens discover failed:", e
    # 回退链：alert 专用 env > cmdb host（同机部署 8131）> 本机
    for var in ("EASYOPS_ALERT_SERVICE_HOST", "EASYOPS_CMDB_SERVICE_HOST", "EASYOPS_CMDB_HOST"):
        h = globals().get(var) or ""
        if isinstance(h, str) and h:
            return h.split(":")[0]
    return None


def search_alerts(batch_ids):
    host = get_alert_service()
    print "alert_service host:", host
    if not host:
        return []
    if ":" not in host:
        host = host + ":8131"
    url = "http://%s/api/v1/monitor_event/last/_search" % host
    headers = {"org": str(EASYOPS_ORG), "user": EASYOPS_USER}
    params = {"page": 1, "page_size": 100,
              "query": {"batchId": {"$in": batch_ids}}, "st": "now-90d"}
    resp = requests.post(url, headers=headers, json=params, timeout=15)
    if resp.status_code != 200:
        print "search alert failed:", resp.status_code, resp.text[:200]
        return []
    return (resp.json().get("data") or {}).get("list") or []


def fmt_time(ts):
    import time as _t
    if not ts:
        return ""
    return _t.strftime("%Y-%m-%dT%H:%M:%S+08:00", _t.gmtime(int(ts) + 8 * 3600))


def build_form(alerts, cur_form, batch_id=None):
    """告警列表 → 表单 formData（cur_form 空时按表单模板结构生成）。"""
    lv = (alerts[0].get("level") or "info").lower() if alerts else "info"
    receivers = []
    for a in alerts:
        for r in (a.get("alertReceivers") or []):
            n = r.get("name") or ""
            if n and n not in receivers:
                receivers.append(n)
    rows = []
    for a in alerts:
        ev = a.get("eventId") or a.get("_id") or ""
        rows.append({
            "alertTime": fmt_time(a.get("startTime")),
            "alertLevel": LEVEL_CN.get((a.get("level") or "info").lower(), LEVEL_CN["info"]),
            "alertResource": a.get("target") or "",
            "alertInfo": a.get("originContent") or a.get("originTitle") or "",
            "alertSource": a.get("source") or "",
            "alertUrl": {"label": "查看告警", "href": "/next/events/%s/detail" % ev},
            "cmdbURL": {"label": "查看实例", "href": "/next/next-cmdb-instance-management/next/%s/instance/%s" % (
                a.get("objectId") or "HOST", a.get("instanceId") or "")},
        })
    # cur_form 空（无表单上下文注入）→ 按表单模板结构生成两容器
    if not cur_form:
        cur_form = [
            {"key": SEC_BASE, "name": "基础信息", "type": "row", "values": [{}]},
            {"key": ALERT_SEC, "name": "关联告警信息", "type": "table", "values": []},
        ]
    out = []
    for c in cur_form:
        if c.get("key") == SEC_BASE:
            if not c.get("values"):
                c["values"] = [{}]
            vals = c["values"][0]
            # batchId 控件值：透传 list 形态原样写（只读控件展示），串形态原样
            if not vals.get("batchId"):
                vals["batchId"] = batch_id if isinstance(batch_id, (list, tuple)) else (batch_id or "")
            if not vals.get("incidentLevel"):
                vals["incidentLevel"] = LEVEL_P.get(lv, LEVEL_P["info"])
            if not vals.get("priority"):
                vals["priority"] = PRIORITY.get(lv, PRIORITY["info"])
            if not vals.get("incidentType"):
                vals["incidentType"] = {"key": "alert", "label": "告警异常", "value": "告警异常"}
            vals["handler"] = [{"instanceId": "", "name": n} for n in receivers]
        elif c.get("key") == ALERT_SEC and rows and not (c.get("values")):
            c["values"] = rows
        out.append(c)
    return out


if __name__ == "__main__":
    # 平台注入变量可能缺省（正常提单无 formEventArgs 时 batchId/formData 未注入）
    # ——globals().get 取，防 NameError
    _g = globals()
    batchId = _g.get("batchId") or ""
    formData = _g.get("formData") or ""
    print "batchId:", batchId
    # 入参 formData 原样解析（所有出口都要回吐，否则前端报『formData, 或字段值类型不合法』）
    try:
        cur = json.loads(formData) if formData else []
    except Exception:
        cur = []
    # URL 透传形态兼容：list[]（formEventArgs={"batchId":[...]}）或逗号串
    if isinstance(batchId, (list, tuple)):
        bids = [str(b).strip() for b in batchId if str(b).strip()]
    else:
        bids = [b.strip() for b in (batchId or "").split(",") if b.strip()]
    if not bids:
        print "empty batchId, pass-through formData"
        PutStr("formData", json.dumps(cur, ensure_ascii=False))
        sys.exit(0)
    alerts = search_alerts(bids)
    print "alerts found:", len(alerts)
    if not alerts:
        print "no alerts, pass-through formData"
        PutStr("formData", json.dumps(cur, ensure_ascii=False))
        sys.exit(0)
    PutStr("formData", json.dumps(build_form(alerts, cur, batchId), ensure_ascii=False))
