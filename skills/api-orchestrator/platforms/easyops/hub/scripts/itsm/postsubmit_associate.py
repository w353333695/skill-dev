# -*- coding: utf-8 -*-
"""
节点后置脚本（识别和发起 postScript）：提交后关联工单与告警批次

数据链路复刻 _batch（incident_management_service.go insertTicketData →
MakeAssociateEventOrderRequest → PUT /api/v1/event_last/order）：
  PUT http://{eventCenterIp}:12006/api/v1/event_last/order
  giraffe-contract-name: easyops.api.event_center.event.AssociateEventOrder
  body: {startTime: 最早批次时间, data: [{rowId: 工单columndb_row_id,
         batchIds: [...], op: "append", orderNum: 工单号}]}
  效果：事件 monitor_event/last 的 orders[] 追加 {orderId, orderNum}
  → 告警列表 hasOrder:true 可见 + 事件页展示关联工单号

入参（平台注入）：orderInfo（前后置脚本唯一数据源——formData 不注入）
运行环境：EasyOps agent py2（requests 可用）
"""
import json
import sys

import requests

reload(sys)
sys.setdefaultencoding("utf-8")

# 平台注入变量可能缺省——globals().get 取，防 NameError
_g = globals()
orderInfo = _g.get("orderInfo") or ""
eventCenterIp = _g.get("eventCenterIp") or ""

EASYOPS_ORG = int(_g.get("EASYOPS_ORG") or 8888)
EASYOPS_USER = _g.get("EASYOPS_USER") or "easyops"


def find_form_data(oi):
    """定位含批次控件的表单 JSON 串（注入无 formData——从 orderInfo 取）。

    优先顶层 formData（触发步骤表单），空则 stepList 最后一个有值步骤。"""
    fd = oi.get("formData") or ""
    if fd:
        return fd
    for s in (oi.get("stepList") or []):
        if s.get("formData"):
            fd = s.get("formData")
    return fd or ""


def get_batch_ids(form_data):
    """遍历全部容器 values 取 batchId（兼容 list/逗号串，多容器合并去重）。"""
    batch_ids = []
    for d in (form_data or []):
        for v in (d.get("values") or []):
            b = v.get("batchId")
            items = b if isinstance(b, (list, tuple)) else (
                [x.strip() for x in (b or "").split(",") if x.strip()] if b else [])
            for x in items:
                x = str(x).strip()
                if x and x not in batch_ids:
                    batch_ids.append(x)
    return batch_ids


def associate(host, batch_ids, order_id, order_num, start_time):
    url = "http://%s/api/v1/event_last/order" % host
    headers = {
        "org": str(EASYOPS_ORG),
        "user": EASYOPS_USER,
        "giraffe-contract-name": "easyops.api.event_center.event.AssociateEventOrder",
    }
    body = {"startTime": start_time,
            "data": [{"rowId": order_id, "batchIds": batch_ids,
                      "op": "append", "orderNum": order_num}]}
    resp = requests.put(url, headers=headers, json=body, timeout=15)
    print "associate:", resp.status_code, resp.text[:200]
    return resp.status_code == 200


if __name__ == "__main__":
    oi = {}
    try:
        oi = json.loads(orderInfo) if orderInfo else {}
    except Exception:
        pass
    pi = oi.get("processInstance") or {}
    process_instance_id = pi.get("instanceId") or ""
    order_num = pi.get("orderNum") or ""
    try:
        form_data = json.loads(find_form_data(oi)) or []
    except Exception:
        form_data = []
    batch_ids = get_batch_ids(form_data)
    # startTime：批次 id 尾段即首次告警时间戳（<batchHash>-<startTime>），取最早
    start_time = 0
    for b in batch_ids:
        try:
            ts = int(b.rsplit("-", 1)[-1])
            if not start_time or ts < start_time:
                start_time = ts
        except ValueError:
            pass
    print "orderNum:", order_num, "| piId:", process_instance_id, "| batchIds:", batch_ids
    if not (process_instance_id and order_num and batch_ids):
        print "missing params, skip"
        sys.exit(0)
    if not eventCenterIp:
        eventCenterIp = (_g.get("EASYOPS_CMDB_SERVICE_HOST") or _g.get("EASYOPS_CMDB_HOST") or "127.0.0.1").split(":")[0]
    associate(eventCenterIp + ":12006", batch_ids, process_instance_id, order_num, start_time)
