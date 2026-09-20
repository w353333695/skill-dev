# -*- coding: utf-8 -*-
"""
节点后置脚本（识别和发起 postScript）：提交后关联工单与告警批次

入参（平台注入）：
    orderInfo   工单上下文 JSON（含 orderNum/rowId/processInstanceId）
    formData    提交的整张表单 JSON（取 batchId）
行为：
    PUT /api/v1/event_last/order（event_center 服务，ens 发现）
    data=[{rowId, batchIds, op:"append", orderNum}]
运行环境：EasyOps agent py2（ens_api + requests）
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


def get_event_center():
    """ens 服务发现 event_center；返回 host:str 或 None。"""
    try:
        ret = ens_api.get_all_service_by_name("my_name", "logic.event_center")
        if isinstance(ret, (list, tuple)):
            for item in ret:
                if isinstance(item, str) and ":" in item:
                    return item
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    return "%s:%s" % (item[0], item[1])
        if isinstance(ret, str):
            return ret
    except Exception:
        pass
    h = globals().get("EASYOPS_EVENT_CENTER_HOST") or ""
    return h if h else None


def associate(row_id, batch_ids, order_num):
    host = get_event_center()
    if not host:
        print "event_center service not found, skip associate"
        return False
    if ":" not in host:
        host = host + ":8080"
    url = "http://%s/api/v1/event_last/order" % host
    headers = {"org": str(EASYOPS_ORG), "user": EASYOPS_USER,
               "Content-Type": "application/json",
               "giraffe-contract-name": "easyops.api.event_center.event.AssociateEventOrder"}
    body = {"data": [{"rowId": row_id, "batchIds": batch_ids, "op": "append", "orderNum": order_num}]}
    resp = requests.put(url, headers=headers, data=json.dumps(body), timeout=15)
    print "associate:", resp.status_code, resp.text[:200]
    return resp.status_code == 200


def extract_batch_ids(form):
    """从表单 JSON 提取批次 id（sec_base.values[0].batchId——兼容 list/逗号串）。"""
    try:
        for c in (form or []):
            if c.get("key") == "sec_base":
                v = (c.get("values") or [{}])[0]
                b = v.get("batchId")
                if isinstance(b, (list, tuple)):
                    return [str(x).strip() for x in b if str(x).strip()]
                if isinstance(b, str):
                    return [x.strip() for x in b.split(",") if x.strip()]
    except Exception:
        pass
    return []


if __name__ == "__main__":
    oi = {}
    try:
        oi = json.loads(orderInfo) if orderInfo else {}
    except Exception:
        pass
    pi = oi.get("processInstance") or {}
    order_num = pi.get("orderNum") or oi.get("orderNum") or ""
    row_id = oi.get("instanceId") or pi.get("instanceId") or ""
    bids = extract_batch_ids(json.loads(formData) if formData else [])
    print "orderNum:", order_num, "| rowId:", row_id, "| batchIds:", bids
    if not (order_num and bids):
        print "missing orderNum or batchIds, skip"
        sys.exit(0)
    associate(row_id, bids, order_num)
