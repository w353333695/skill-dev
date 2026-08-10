# browser_recorder/request_aggregator.py
"""请求跨次聚合（B 方案）：按 (method, url_template) 分组合并字段 schema。

标注 always_present / present_in / absent_in；数组元素跨次取并集；数值采样。
"""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
from .models import RequestRecord

_PATH_NUM = re.compile(r"(?<=/)\d+(?=/|$|\?)")


def url_template(url: str) -> tuple[str, list[str]]:
    """把数字路径段参数化为 {id}，提取 query 参数名（并模板化进 query）。"""
    params: list[str] = []
    base = url
    # 分离 query
    if "?" in url:
        base, query = url.split("?", 1)
        from urllib.parse import parse_qsl
        # 解析保留顺序，把 ?k=v → ?k={k}
        pairs = parse_qsl(query, keep_blank_values=True)
        param_names: list[str] = []
        parts: list[str] = []
        for k, _ in pairs:
            if k not in param_names:
                param_names.append(k)
            parts.append(f"{k}={{{k}}}")
        params.extend(param_names)
        query_tmpl = "&".join(parts)
        base = f"{base}?{query_tmpl}"
    # 数字路径段 → {id}
    def _sub(m: re.Match) -> str:
        params.append("id")
        return "{id}"
    tmpl = _PATH_NUM.sub(_sub, base)
    return tmpl, params


def _merge_value_schemas(items: list[dict[str, Any]]) -> dict[str, Any]:
    """合并同一字段的多次 schema。"""
    types = {it.get("type") for it in items if it.get("type")}
    # 数组：合并 items.fields
    if "array" in types:
        item_field_lists = []
        for it in items:
            flds = (it.get("items") or {}).get("fields")
            if flds:
                item_field_lists.append(flds)
        merged_items = {"type": "object", "fields": _merge_field_dicts(item_field_lists)} if item_field_lists else {"type": "unknown"}
        return {"type": "array", "items": merged_items}
    # object：合并 fields
    if "object" in types:
        fld_lists = [it.get("fields", {}) for it in items if it.get("fields")]
        return {"type": "object", "fields": _merge_field_dicts(fld_lists)}
    # 标量：采样
    samples = [it.get("sample") for it in items if "sample" in it]
    out: dict[str, Any] = {"type": sorted(types)[0] if types else "unknown"}
    if samples:
        out["samples"] = samples
        nums = [s for s in samples if isinstance(s, (int, float)) and not isinstance(s, bool)]
        if nums and len(nums) == len(samples):
            out["min"] = min(nums)
            out["max"] = max(nums)
    return out


def _merge_field_dicts(field_dicts: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多个 fields 字典，按字段名聚合，统计出现次数。"""
    total = len(field_dicts)
    names: dict[str, list[dict[str, Any]]] = defaultdict(list)
    present_count: dict[str, int] = defaultdict(int)
    for fd in field_dicts:
        for k, v in fd.items():
            names[k].append(v)
            present_count[k] += 1
    merged: dict[str, Any] = {}
    for k, vs in names.items():
        m = _merge_value_schemas(vs)
        if present_count[k] == total:
            m["always_present"] = True
        else:
            m["always_present"] = False
            m["present_in"] = present_count[k]
            m["absent_in"] = total - present_count[k]
        merged[k] = m
    return merged


def merge_field_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """顶层合并（schemas 是 response.schema 列表，含 type/fields）。

    若 schema 缺少 type 但含 fields，按 object 处理（兼容裸字段字典输入）。
    """
    obj_schemas = [
        s for s in schemas
        if s and (s.get("type") in ("object",) or ("fields" in s and s.get("type") is None))
    ]
    if not obj_schemas:
        return {"type": schemas[0].get("type") if schemas else "unknown"}
    merged = _merge_field_dicts([s.get("fields", {}) for s in obj_schemas])
    return {"type": "object", "fields": merged}


def aggregate(records: list[RequestRecord]) -> list[dict[str, Any]]:
    """按 (method, url_template) 聚合，输出 spec §6.3 结构。"""
    groups: dict[tuple[str, str], list[RequestRecord]] = defaultdict(list)
    templates: dict[tuple[str, str], list[str]] = {}
    for r in records:
        tmpl, params = url_template(r.url)
        key = (r.method, tmpl)
        groups[key].append(r)
        templates[key] = params
    out: list[dict[str, Any]] = []
    for (method, tmpl), recs in groups.items():
        schemas = [r.response.schema for r in recs if r.response and r.response.schema]
        merged = merge_field_schemas(schemas) if schemas else {"type": "unknown"}
        out.append({
            "endpoint": {"method": method, "url_template": tmpl, "param_path": templates[(method, tmpl)]},
            "observations": len(recs),
            "merged_schema": merged,
            "sample_statuses": sorted({r.status for r in recs}),
        })
    return out
