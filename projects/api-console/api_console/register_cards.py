"""卡片注册：从前端 openapi 抽骨架卡片（extract）与入库（commit）。

本模块是 spec 第 6 章"卡片注册流程"的确定性部分：

1. ``extract``：读前端 openapi，对每个 path+method 抽出卡片骨架；
   - 调用 ``path_align.align_path`` 做三级优先级对齐（backend_contract >
     gateway_strip > frontend_raw），把前端 gateway_path 映射到后端真实 path；
   - 用 method+operationId 推断 side_effect（``_search`` 这种 POST 但语义
     read 的特例由 operationId 兜底）；
   - 从 tags/文件名粗推 module，标 ``confidence.module=low``（LLM 后续修正）；
   - outputs/requires/rollback/tags/summary/description 留空或最小默认，
     标低置信，待 LLM 补语义。
   产出 ``_draft.yaml``（list[dict]，每项是 ``Card.to_yaml_dict()`` 结果）。

2. ``commit``：读 ``_draft.yaml`` → ``Card.from_dict`` + ``validate`` →
   按 module 分组写 ``registry/<module>/<name>.yaml``，更新
   ``registry/_index.yaml``（每条含 name/method/path/side_effect/tags/
   summary/file）。索引与卡片一致性由 file 字段保证。

CLI 子命令（注意不是 ``--extract`` flag）::

    run.sh register_cards.py extract --platform <platform> \
        --openapi <前端openapi.yaml> \
        --backend-contracts <contracts.yaml> \
        --out <_draft.yaml>
    run.sh register_cards.py commit --platform <platform> --in <_draft.yaml>

重要：本脚本只做确定性脏活；LLM 在 extract 与 commit 之间补语义（module/
outputs/tags/summary 等），不在本模块范围。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

from api_console.path_align import align_path
from api_console.schema.card import Card, OutputAnchor
from api_console.schema.contracts import BackendContract, load_contracts
from api_console.manifest_loader import load_manifest


# ---------- 正则（刻意避开反斜杠字面量，用字符类替代 \w \d） ----------

# /api/gateway/<service-name>/... 中的 service-name 段（不含 /）
_GATEWAY_SVC_PATTERN = re.compile("/api/gateway/([^/]+)")
# 路径段里的参数占位符（{xxx}），用于 module 推断时忽略
_PARAM_PATTERN = re.compile(r"\{[^}]+\}")


# ---------- 推断辅助函数 ----------

def _infer_side_effect(method: str, operation_id: str) -> str:
    """按 method + operationId 推断 side_effect。

    规则（spec 5.1）：
        - operationId 含 ``search``/``list``/``get``/``query`` → read
          （兜底 ``_search`` 这种 POST 但语义是读的特例）
        - GET → read
        - POST（非 search）→ create
        - PUT / PATCH → update
        - DELETE → delete
        - 其他兜底 read
    """
    m = method.upper()
    oid = (operation_id or "").lower()
    if any(kw in oid for kw in ("search", "list", "get", "query", "find")):
        return "read"
    if m == "GET":
        return "read"
    if m == "POST":
        return "create"
    if m in ("PUT", "PATCH"):
        return "update"
    if m == "DELETE":
        return "delete"
    return "read"


def _extract_service_from_gateway(gateway_path: str) -> str:
    """从 gateway_path 提取后端 service 名（保留 ``logic.`` 前缀）。

    真实前端 openapi path 形如
    ``/next/api/gateway/logic.flowable_service/api/flowable_service/v1/...``，
    其中的 ``logic.flowable_service`` 段与真实 contracts.yaml 里
    ``BackendContract.service`` 字段一致（带 ``logic.`` 前缀）。

    Args:
        gateway_path: 前端 openapi 中的 gateway 路径。

    Returns:
        匹配到的 service 段；无法匹配返回空串。
    """
    m = _GATEWAY_SVC_PATTERN.search(gateway_path or "")
    return m.group(1) if m else ""


# 中文 tag → 模块英文 key 映射（spec 第 5 章 module 字段定义）
_TAG_MODULE_MAP = {
    "领域模型": "domain_model",
    "标准字段": "standard_field",
    "流程": "process",
    "表单": "form",
}


def _infer_module(openapi_path: Path, tags: list) -> str:
    """extract 阶段粗推 module（LLM 后续修正，confidence.module=low）。

    优先级：
        1. 中文 tag 关键词匹配（领域模型→domain_model 等）
        2. tag 英文部分匹配（domain_model/standard_field/...）
        3. openapi 文件名匹配（兜底）
        4. 以上都不中：``default``
    """
    # 中文/英文 tag 关键词
    for t in tags or []:
        ts = str(t)
        for cn_key, module in _TAG_MODULE_MAP.items():
            if cn_key in ts:
                return module
        tl = ts.lower()
        for key in ("domain_model", "standard_field", "process", "form"):
            if key in tl:
                return key
    # 兜底用文件名
    name = openapi_path.stem.lower()
    for key in ("domain_model", "standard_field", "process", "form"):
        if key in name:
            return key
    return "default"


# ---------- extract ----------

def extract(openapi_path: Path, contracts: list[BackendContract],
            gateway_rules: dict, out: Path,
            service_resolver=None) -> None:
    """从前端 openapi 抽骨架卡片 + path 对齐，输出 _draft.yaml。

    Args:
        openapi_path: 前端 openapi yaml 路径（必含 ``paths``）。
        contracts: 后端契约列表（已 load_contracts 加载），用于 path 对齐。
        gateway_rules: gateway-rules.yaml 反序列化结果，含
            ``strip_prefix``/``service_map``。
        out: 输出 ``_draft.yaml`` 路径。父目录会自动创建。
        service_resolver: 可选平台特定 service 解析器（``resolve_service_from_rpc``），
            签名 ``(rpc_name, method, gateway_path, contracts) -> str``。当 align_path
            未回填 service（多义或特殊 RPC 名）时，调用它把命名式 RPC 解析成契约
            service；为 None 则跳过。
    """
    spec = yaml.safe_load(openapi_path.read_text()) or {}
    paths = spec.get("paths") or {}
    drafts: list[dict] = []

    for gateway_path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(op, dict):
                continue
            drafts.append(_build_card_dict(
                gateway_path=gateway_path,
                method=method.upper(),
                op=op,
                openapi_path=openapi_path,
                contracts=contracts,
                gateway_rules=gateway_rules,
                service_resolver=service_resolver,
            ))

    out.parent.mkdir(parents=True, exist_ok=True)
    # name 全局去重：同 draft 内 name 冲突时追加 _2/_3...
    # （operationId 一般唯一，但 fallback name 可能撞——如不同 gateway_path
    # 归一化后 path 相同）
    seen: dict[str, int] = {}
    for d in drafts:
        base = d["name"]
        if base not in seen:
            seen[base] = 1
        else:
            seen[base] += 1
            d["name"] = f"{base}_{seen[base]}"
    out.write_text(
        yaml.safe_dump(drafts, allow_unicode=True, sort_keys=False)
    )
    print(f"[register_cards] extract 抽出 {len(drafts)} 张骨架卡片 → {out}")


def _safe_fallback_name(method: str, path: str) -> str:
    """无 operationId 时，用归一化 path 生成文件安全的 name。

    gateway_path 含 ``/`` 不能直接当文件名（commit 拆单卡片时
    ``<name>.yaml`` 会被解析成多级路径）。这里把 ``/`` 折成 ``_``，
    保留 ``{param}`` 占位符（其内无斜杠），结果可安全做文件名且可读。

    Args:
        method: HTTP 方法（大写，如 ``GET``）。
        path: 已对齐归一化的后端 path（brace style，如
            ``/api/flowable_service/v1/ticket/{ticketId}/task``）。

    Returns:
        文件安全 name，如 ``get_api_flowable_service_v1_ticket_ticketId_task``。
    """
    flat = (path or "").strip("/").replace("/", "_")
    flat = flat or "root"
    return f"{method.lower()}_{flat}"


def _match_contract(contracts: list[BackendContract], service: str,
                    method: str, path: str):
    """按 service+method+path 命中后端契约对象（供取 response.fields）。

    与 ``_find_contract_ref`` 同匹配规则，但返回契约对象本身而非 operation_key。
    未命中返回 None。
    """
    for c in contracts:
        if c.service == service and c.method == method and c.path == path:
            return c
    return None


def _gen_outputs_from_contract(contract, side_effect: str) -> tuple[dict, str]:
    """从命中契约的 response.fields 确定性生成 outputs 锚点骨架。

    通用规则（**不依赖业务字段名**，看字段自身的 type/name）：
      - type 含 ``[]``（数组）的 list/*List/*_list 字段 → 主列表锚点
        ``list_full``+``list_ids``（jsonpath ``$.data.<字段名>``）；
        其他数组字段（categories/nodes 等）按字段名建锚点。
      - 字段名/类型含 instanceId/instance_id → ``instanceId`` 锚点；
        create/update 的 id → ``id`` 锚点。
      - 字段名 total/count/*_count → ``total`` 锚点。
      - 仅有单一字段（无列表/id）→ ``detail`` 兜底。

    Args:
        contract: 命中的 BackendContract（含 response.fields）。可为 None。
        side_effect: 卡片 side_effect（read/create/update/delete）。

    Returns:
        (outputs_dict, confidence)：outputs 为 {锚点名: {jsonpath, desc}}，
        confidence 为 "high"（契约命中）/ "low"（无契约/无可用字段）。
        生成的是骨架，LLM 补语义阶段可精修（确认主列表字段、补 desc）。
    """
    if not contract or not isinstance(contract.response, dict):
        return {}, "low"
    fields = contract.response.get("fields") or []
    if not fields:
        return {}, "low"

    out: dict = {}
    list_anchor_field = None  # 主列表字段名（list_full/list_ids 用）
    for f in fields:
        name = f.get("name")
        if not name:
            continue
        ftype = str(f.get("type", ""))
        desc = f.get("desc", "")
        key = f"{name}|{ftype}".lower()
        nl = name.lower()
        is_list_field = "[]" in ftype or "list" in nl

        if "instanceid" in key or "instance_id" in ftype.lower():
            out["instanceId"] = {"jsonpath": f"$.data.{name}",
                                 "desc": desc or "资源 instanceId"}
        elif nl == "id" and side_effect in ("create", "update"):
            out["id"] = {"jsonpath": f"$.data.{name}", "desc": desc or "资源 id"}
        elif nl in ("total", "count") or name.endswith("_count"):
            out["total"] = {"jsonpath": f"$.data.{name}", "desc": desc or "总数"}
        elif is_list_field:
            # 列表字段：list/*_list 名字 → 主列表锚点；其他数组字段按字段名建锚点
            if nl == "list" or nl.endswith("_list"):
                list_anchor_field = list_anchor_field or name
            else:
                out[name.lstrip("_")] = {"jsonpath": f"$.data.{name}",
                                         "desc": desc or "列表"}

    if list_anchor_field:
        out["list_full"] = {"jsonpath": f"$.data.{list_anchor_field}", "desc": "列表全量"}
        out["list_ids"] = {
            "jsonpath": f"$.data.{list_anchor_field}",
            "desc": "列表项id集合（配合 ${s.list_full.instanceId} 投影）",
        }

    if not out and len(fields) == 1:
        f0 = fields[0]
        if f0.get("name"):
            out["detail"] = {"jsonpath": f"$.data.{f0['name']}",
                             "desc": f0.get("desc", "详情全量")}

    return (out, "high") if out else ({}, "low")


def _build_card_dict(gateway_path: str, method: str, op: dict,
                     openapi_path: Path,
                     contracts: list[BackendContract],
                     gateway_rules: dict,
                     service_resolver=None) -> dict:
    """构造单张骨架卡片的 yaml dict。"""
    # service 从 gateway_path 提取（保留 logic. 前缀，与契约 service 一致）
    service = _extract_service_from_gateway(gateway_path)

    # path 三级对齐（先于 name 生成：fallback name 用归一化 path，更短更稳定）
    path, src, conf, matched_service = align_path(
        gateway_path, service, method, contracts, gateway_rules,
    )
    if matched_service:
        service = matched_service  # 命中契约则用真实 logic service 覆盖 RPC 名
    # service_resolver 兜底：align_path 未回填 service 时（多义/特殊），调平台 resolver
    if not matched_service and service_resolver and service and not service.startswith("logic."):
        resolved = service_resolver(service, method, gateway_path, contracts)
        if resolved:
            service = resolved
            path, src, conf, matched_service = align_path(
                gateway_path, service, method, contracts, gateway_rules)
            if matched_service:
                service = matched_service
    op_id = op.get("operationId") or _safe_fallback_name(method, path)
    tags = op.get("tags") or []

    # endpoint 配置（spec 1.5 / 5.1）：
    #   - mode：不固化。注册期**不写** endpoint.mode（主干不决策平台特定调用模式，
    #     也不读 manifest 固化），真调时由 adapter.resolve_call_mode 动态决定
    #     （卡片无 mode → manifest.call_policy.default_mode 兜底 → 契约 port 推断）。
    #     这样 manifest 改 default_mode 立即对所有卡片生效，无"旧卡固化滞后"问题。
    #   - contract_ref: 对齐到后端契约时填 operation_key（service|method|path），
    #     未对齐（frontend_raw）留空，execute_dag 退化为按 card.service+card.path
    #     在 contracts.yaml 现查
    contract_ref = _find_contract_ref(contracts, service, method, path)
    endpoint = {"contract_ref": contract_ref}

    # request schema（POST/PUT/PATCH 从 requestBody 提，GET 从 parameters 提）
    req_required, req_props = _extract_request_schema(op, method)

    # outputs 锚点骨架：从命中契约的 response.fields 确定性生成
    # （type 含 []→列表、instanceId/total 等通用判定，不依赖业务字段名）。
    # LLM 补语义阶段可精修；契约未命中则留空待 LLM 推断。
    matched = _match_contract(contracts, service, method, path)
    out_dict, out_conf = _gen_outputs_from_contract(matched, _infer_side_effect(method, op_id))
    outputs = {
        name: OutputAnchor(name=name, jsonpath=a["jsonpath"], desc=a["desc"])
        for name, a in out_dict.items()
    }

    # request 合并：命中契约时把 request.fields 的 type/desc 补进 properties
    req_conf = "high"
    if matched and isinstance(matched.request, dict):
        req_props, req_conf = _merge_request_from_contract(
            req_props, matched.request.get("fields") or [])

    card = Card(
        name=op_id,
        module=_infer_module(openapi_path, tags),
        method=method,
        path=path,
        gateway_path=gateway_path,
        service=service,
        side_effect=_infer_side_effect(method, op_id),
        path_source=src,
        path_confidence=conf,
        tags=[],  # LLM 补
        summary=op.get("summary", "") or "",
        description=_trim_description(op.get("description", "")),
        request_required=req_required,
        request_properties=req_props,
        outputs=outputs,  # 契约命中→确定性骨架；否则空待 LLM 补
        requires=[],  # LLM 补
        rollback=None,  # LLM 补
        examples=[],
        confidence={
            "request": req_conf,
            "module": "low",
            "outputs": out_conf,  # 契约命中→high，否则 low
            "tags": "low",
            "summary": "low" if not op.get("summary") else "medium",
        },
        endpoint=endpoint,
        source=_openapi_source(openapi_path),  # 来源指纹（batch-register 增量判断用）
    )
    return card.to_yaml_dict()


def _openapi_source(openapi_path: Path) -> dict:
    """计算 openapi 来源指纹（hash + 录制时间），供增量更新判断。

    - openapi_hash: 文件内容 SHA256（变了→接口可能变→需重注）
    - recorded_at: openapi 的 x-recorded-at 字段；无则回退文件 mtime（旧资料兼容）
    """
    import hashlib
    raw = openapi_path.read_bytes()
    h = hashlib.sha256(raw).hexdigest()
    # 录制时间：优先 openapi 的 x-recorded-at，回退 mtime
    recorded_at = ""
    try:
        spec = yaml.safe_load(openapi_path.read_text()) or {}
        recorded_at = spec.get("x-recorded-at") or spec.get("info", {}).get("x-recorded-at") or ""
    except Exception:
        pass
    if not recorded_at:
        import datetime
        recorded_at = datetime.datetime.fromtimestamp(
            openapi_path.stat().st_mtime).isoformat()
    return {
        "openapi_file": openapi_path.name,
        "openapi_hash": h,
        "recorded_at": recorded_at,
    }


def _find_contract_ref(contracts: list[BackendContract], service: str,
                       method: str, path: str) -> str:
    """在 contracts 中按 service+method+path 查对齐契约的 operation_key。

    用于卡片 endpoint.contract_ref：execute_dag 拿到 ref 后可从 contracts.yaml
    直接查到对应契约，无需重新做 path 对齐。

    Args:
        contracts: 后端契约列表。
        service: 卡片 service 字段（带 ``logic.`` 前缀）。
        method: HTTP 方法（大写）。
        path: 已对齐的后端契约 path。

    Returns:
        命中契约的 operation_key；未命中返回空串（前端原始路径未对齐到后端）。
    """
    for c in contracts:
        if c.service == service and c.method == method and c.path == path:
            return c.operation_key
    return ""


def _extract_request_schema(op: dict, method: str) -> tuple[list, dict]:
    """从 openapi operation 抽 request 必填字段 + 属性表。

    POST/PUT/PATCH：从 ``requestBody.content.application/json.schema`` 取；
    GET/DELETE：从 ``parameters[in=query/path]`` 取。
    简化处理，不做 ``$ref`` 展开（LLM 后续会补全）。
    """
    required: list = []
    properties: dict = {}
    if method in ("POST", "PUT", "PATCH"):
        schema = (
            (op.get("requestBody") or {}).get("content", {}).get(
                "application/json", {}
            ).get("schema", {})
        )
        if isinstance(schema, dict):
            required = list(schema.get("required") or [])
            raw_props = schema.get("properties") or {}
            for k, v in raw_props.items():
                properties[k] = {
                    "type": (v or {}).get("type", "string"),
                    "desc": (v or {}).get("description", ""),
                }
    else:
        for p in op.get("parameters") or []:
            if not isinstance(p, dict):
                continue
            if p.get("in") in ("query", "path"):
                name = p.get("name", "")
                if not name:
                    continue
                properties[name] = {
                    "type": (p.get("schema") or {}).get("type", "string"),
                    "desc": p.get("description", ""),
                }
                if p.get("required"):
                    required.append(name)
    return required, properties


def _is_more_specific_type(contract_type: str, openapi_type: str) -> bool:
    """契约 type 是否比 openapi type 更具体（决定是否覆盖）。"""
    ct = (contract_type or "").strip()
    ot = (openapi_type or "").strip()
    if not ct:
        return False
    if ot == "array" and "[]" in ct:
        return True
    if ot in ("string", "") and ct not in ("string", "int", "number",
                                            "bool", "boolean", "object",
                                            "array", ""):
        return True
    return False


def _merge_request_from_contract(openapi_props: dict,
                                 contract_fields: list) -> tuple[dict, str]:
    """合并 openapi request 与后端契约 request.fields。

    - openapi 已有字段：desc 空用契约 desc；type 用更具体的契约 type 覆盖
    - 契约独有字段：加入 properties，标 _source: contract
    - required 不动（契约无此信息）

    Returns: (merged_props, confidence)：含契约补充→medium，否则 high。
    """
    merged: dict = {}
    has_contract_only = False
    contract_by_name = {f.get("name"): f for f in contract_fields if f.get("name")}

    for k, v in (openapi_props or {}).items():
        entry = {"type": (v or {}).get("type", "string"),
                 "desc": (v or {}).get("desc", "")}
        cf = contract_by_name.get(k)
        if cf:
            if not entry["desc"] and cf.get("desc"):
                entry["desc"] = cf["desc"]
            if _is_more_specific_type(cf.get("type", ""), entry["type"]):
                entry["type"] = cf["type"]
        merged[k] = entry

    for name, cf in contract_by_name.items():
        if name in merged:
            continue
        merged[name] = {"type": cf.get("type", "string"),
                        "desc": cf.get("desc", ""),
                        "_source": "contract"}
        has_contract_only = True

    return merged, ("medium" if has_contract_only else "high")


def _trim_description(desc: str) -> str:
    """description 多行时取首段，避免 yaml 字段过长。"""
    if not desc:
        return ""
    # 取首行非空内容
    first = (desc.strip().splitlines() or [""])[0].strip()
    return first


# ---------- commit ----------

def commit(draft_path: Path, registry_dir: Path, platform: str) -> None:
    """校验 _draft → 拆单卡片 → 写 ``registry/<module>/<name>.yaml`` → 更新 _index.yaml。

    Args:
        draft_path: ``extract`` 产出的 ``_draft.yaml``。
        registry_dir: registry 根目录（如
            ``platforms/<platform>/registry``）。
        platform: 平台名（仅用于日志，不参与路径拼接）。

    Raises:
        ValueError: 任一卡片 ``validate()`` 返回非空错误列表。
    """
    drafts = yaml.safe_load(draft_path.read_text()) or []
    if not isinstance(drafts, list):
        raise ValueError(f"_draft.yaml 顶层应为 list，实际为 {type(drafts).__name__}")

    # validate 全部卡片
    all_cards: list[Card] = []
    for d in drafts:
        card = Card.from_dict(d)
        errs = card.validate()
        if errs:
            raise ValueError(f"卡片 {card.name or '<无名>'} 校验失败：{errs}")
        all_cards.append(card)

    # 收集已有 contract_ref + name→module（从 registry 落盘卡片读）。
    # 同名同 module 的重注允许（覆盖旧文件，保留既有"重注"语义），
    # 仅跨 module 同名视为冲突（后者静默不可达的数据完整性 bug）。
    existing_refs: set[str] = set()
    existing_name_modules: dict[str, str] = {}
    for card_file in registry_dir.glob("*/*.yaml"):
        if card_file.name == "_index.yaml":
            continue
        ec = yaml.safe_load(card_file.read_text()) or {}
        cf = (ec.get("endpoint") or {}).get("contract_ref", "")
        if cf:
            existing_refs.add(cf)
        nm = ec.get("name", "")
        if nm:
            existing_name_modules[nm] = ec.get("module") or "default"

    # 去重 + 分组（第一版：已在库/本轮已加优先，重复跳过）。
    # - contract_ref 非空：按 ref 去重，已有则跳过（不做替换，避免抖动）
    # - contract_ref 空：按 name 检测；同名同 module 允许重注，跨 module 报错
    by_module: dict[str, list[Card]] = {}
    seen_refs: set[str] = set(existing_refs)
    name_to_module: dict[str, str] = dict(existing_name_modules)
    skipped: list[str] = []
    for card in all_cards:
        cf = (card.endpoint or {}).get("contract_ref", "")
        cur_module = card.module or "default"
        if cf:
            if cf in seen_refs:
                skipped.append(f"{card.name}（contract_ref={cf} 已有，跳过）")
                continue
            seen_refs.add(cf)
        else:
            prev_module = name_to_module.get(card.name)
            if prev_module is not None and prev_module != cur_module:
                raise ValueError(
                    f"卡片同名跨 module 冲突：{card.name}"
                    f"（已在 module={prev_module}，本次试图入 module={cur_module}；"
                    f"contract_ref 为空，请重命名确保 name 唯一）")
            name_to_module[card.name] = cur_module
        by_module.setdefault(cur_module, []).append(card)

    if skipped:
        print(f"[register_cards] 去重跳过 {len(skipped)} 张：{'; '.join(skipped)}")

    # 写卡片文件 + 索引
    registry_dir.mkdir(parents=True, exist_ok=True)
    index_path = registry_dir / "_index.yaml"
    # merge 已有 _index：本次 commit 的卡片按 name 增量合并进各 module，
    # 同名覆盖（重注）、draft 未涉及的保留。多个 draft 共享同一 module 时
    # 不互相清掉（避免 _index 与卡片文件不一致）。其他 module 原样保留。
    if index_path.exists():
        existing = yaml.safe_load(index_path.read_text()) or {}
        modules_map = {m["name"]: m for m in (existing.get("modules") or [])}
    else:
        modules_map = {}
    total = 0
    import datetime
    registered_at = datetime.datetime.now().isoformat()
    for module_name in sorted(by_module.keys()):
        cards = by_module[module_name]
        mdir = registry_dir / module_name
        mdir.mkdir(exist_ok=True)
        idx_cards = []
        for c in cards:
            c.registered_at = registered_at  # commit 时间戳
            card_file = f"{c.name}.yaml"
            (mdir / card_file).write_text(
                yaml.safe_dump(c.to_yaml_dict(), allow_unicode=True, sort_keys=False)
            )
            idx_cards.append({
                "name": c.name,
                "side_effect": c.side_effect,
                "method": c.method,
                "path": c.path,
                "tags": list(c.tags),
                "summary": c.summary,
                "file": f"{module_name}/{card_file}",
            })
            total += 1
        # 增量合并：本次 commit 的卡片按 name 覆盖旧条目，保留该 module 中
        # 本次未涉及的卡片。多个 draft 共享同一 module 时（如多个 openapi
        # 都产出 form 卡片），后提交者只覆盖同名卡片，不整体清掉同 module
        # 其他卡片——避免 _index 与卡片文件不一致。
        old = modules_map.get(module_name, {})
        old_cards = {c["name"]: c for c in old.get("cards", [])}
        for nc in idx_cards:
            old_cards[nc["name"]] = nc
        modules_map[module_name] = {
            "name": module_name,
            "desc": old.get("desc", ""),
            "tags": old.get("tags", []),
            "cards": list(old_cards.values()),
        }

    # 按 module 名排序输出（稳定）
    index = {"modules": [modules_map[k] for k in sorted(modules_map.keys())]}
    index_path.write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=False)
    )
    print(
        f"[register_cards] commit 写入 {total} 张卡片（{len(by_module)} 个 module，"
        f"索引共 {len(modules_map)} 个 module） → {registry_dir}"
    )


def rebuild_index(registry_dir: Path) -> None:
    """从 registry 已落盘的卡片文件重建 ``_index.yaml``。

    适用场景：``_index.yaml`` 与卡片文件不一致（手工删卡、commit merge bug、
    误改索引）时的兜底恢复。遍历 ``registry/<module>/*.yaml``，按 module 归并
    索引条目，保留旧 ``_index.yaml`` 中各 module 的 ``desc``/``tags``。

    纯结构操作，零系统特定项——只读卡片文件的 name/method/path/side_effect/
    tags/summary 字段。不校验、不改卡片文件内容，只重建索引。

    Args:
        registry_dir: registry 根目录（含各 module 子目录 + ``_index.yaml``）。
    """
    index_path = registry_dir / "_index.yaml"
    old_modules = {}
    if index_path.exists():
        existing = yaml.safe_load(index_path.read_text()) or {}
        old_modules = {m["name"]: m for m in (existing.get("modules") or [])}

    by_module: dict[str, dict[str, dict]] = {}  # module -> {name: idx_entry}
    for card_file in sorted(registry_dir.glob("*/*.yaml")):
        if card_file.name == "_index.yaml":
            continue
        c = yaml.safe_load(card_file.read_text()) or {}
        mod = c.get("module") or "default"
        by_module.setdefault(mod, {})[c.get("name", "")] = {
            "name": c.get("name", ""),
            "side_effect": c.get("side_effect", ""),
            "method": c.get("method", ""),
            "path": c.get("path", ""),
            "tags": list(c.get("tags") or []),
            "summary": c.get("summary", ""),
            "file": f"{mod}/{card_file.name}",
        }

    modules = []
    for mod in sorted(by_module):
        old = old_modules.get(mod, {})
        modules.append({
            "name": mod,
            "desc": old.get("desc", ""),
            "tags": old.get("tags", []),
            "cards": list(by_module[mod].values()),
        })

    total = sum(len(m["cards"]) for m in modules)
    index_path.write_text(
        yaml.safe_dump({"modules": modules}, allow_unicode=True, sort_keys=False)
    )
    print(
        f"[register_cards] rebuild_index 重建索引：{len(modules)} 个 module，"
        f"{total} 张卡片 → {index_path}"
    )


# ---------- CLI ----------

def _load_service_resolver(platform: str, workdir: Path):
    """按 platform 动态加载 adapter 的 resolve_service_from_rpc（找不到返回 None）。"""
    import importlib.util
    adapter_path = (workdir / "platforms" / platform
                    / "sources" / "backend" / "adapters"
                    / f"{platform}_contract.py")
    if not adapter_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"{platform}_contract", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return getattr(mod, "resolve_service_from_rpc", None)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：``extract`` / ``commit`` / ``rebuild_index`` 三个子命令。"""
    p = argparse.ArgumentParser(
        prog="api-console register-cards",
        description="卡片注册：抽骨架(extract) + 入库(commit) + 重建索引(rebuild_index)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="从前端 openapi 抽骨架卡片")
    pe.add_argument("--platform", required=True)
    pe.add_argument("--openapi", required=True)
    pe.add_argument("--backend-contracts", required=True)
    pe.add_argument("--out", required=True)

    pc = sub.add_parser("commit", help="校验 _draft 并写入 registry/")
    pc.add_argument("--platform", required=True)
    pc.add_argument("--in", dest="draft", required=True)

    pri = sub.add_parser(
        "rebuild_index",
        help="从 registry 卡片文件重建 _index.yaml（_index 损坏/不一致时兜底）",
    )
    pri.add_argument("--platform", required=True)

    args = p.parse_args(argv)

    workdir = Path(os.environ.get("API_CONSOLE_WORKDIR", os.getcwd()))

    if args.cmd == "extract":
        contracts = load_contracts(Path(args.backend_contracts))
        gr_path = (
            workdir / "platforms" / args.platform
            / "sources" / "backend" / "gateway-rules.yaml"
        )
        if gr_path.exists():
            gateway_rules = yaml.safe_load(gr_path.read_text()) or {}
        else:
            gateway_rules = {"strip_prefix": [], "service_map": {}}
        service_resolver = _load_service_resolver(args.platform, workdir)
        # endpoint.mode 不固化（spec 5.1）：extract 不写 mode，真调时由
        # adapter.resolve_call_mode 按 manifest.default_mode + 契约 port 动态决策。
        extract(
            Path(args.openapi), contracts, gateway_rules, Path(args.out),
            service_resolver=service_resolver,
        )
    elif args.cmd == "commit":
        registry = workdir / "platforms" / args.platform / "registry"
        commit(Path(args.draft), registry, args.platform)
    elif args.cmd == "rebuild_index":
        registry = workdir / "platforms" / args.platform / "registry"
        rebuild_index(registry)
    else:
        # argparse 已保证 subparser required=True，理论不会到这
        p.error(f"未知子命令：{args.cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
