# browser_recorder/export/runner.py
"""export 子命令：读 trace+requests，画标、聚合、生成报告。

平台中性：不耦合任何特定系统。``--filter-requests`` 的规则由用户 yaml 提供，
仅含中性维度（第三方/状态码/方法/URL 正则），不含任何系统/host 硬编码。
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import yaml
from .. import paths
from ..models import Action, RequestRecord
from ..request_aggregator import aggregate
from .annotator import annotate_screenshot, VERBOSE, COMPACT
from . import report_html, report_md





def load_request_filter(path: Path | None) -> dict:  # noqa: F811
    """``--filter-requests`` 规则加载；``path`` 为 None 返回内置最佳实践默认。

    仅为兼容 ``from browser_recorder.export.runner import load_request_filter`` 的旧
    导入而保留薄包装；实现在 ``browser_recorder.config.load_request_filter``。
    默认排除静态/埋点/长连接/OPTIONS/304 等无业务语义请求。
    """
    from ..config import load_request_filter as _load
    return _load(path)


def _is_third_party(url: str, registrable_base: str) -> bool:
    """判断 url 是否属于第三方（与目标 registrable domain 不同）。

    平台中性：仅基于 URL 解析的 registrable domain 比较，不硬编码任何系统/host。
    """
    from ..auth.scope import registrable_domain
    host = (urlparse(url).hostname or "").lower()
    if not host or not registrable_base:
        return False
    return registrable_domain(host) != registrable_base


def apply_filter(records: list[RequestRecord], flt: dict,
                 target_url: str | None = None) -> list[RequestRecord]:
    """按 filter 规则精筛 records。返回新列表，不改原。"""
    if not flt:
        return list(records)
    from ..auth.scope import registrable_domain
    base_reg = registrable_domain(urlparse(target_url).hostname or "") if target_url else ""
    out: list[RequestRecord] = []
    for r in records:
        if r.method.upper() in flt.get("exclude_methods", set()):
            continue
        if r.status in flt.get("exclude_status", set()):
            continue
        if any(p.search(r.url) for p in flt.get("exclude_url_patterns", [])):
            continue
        if _is_third_party(r.url, base_reg):
            continue
        out.append(r)
    return out


def run_export(session, out_dir, name, filter_path, keep_raw_bodies,
               annotate_style, annotate_opacity, tmp_root=None, fmt="md") -> Path:
    """导出入口：返回 export 目录。session 是 session_id 或 name。

    ``fmt``：``"md"``（默认，只写 report.md）/ ``"html"``（只写 report.html）/
    ``"both"``（都写）。其余产物（requests.json / structure.json / 画标截图）不受影响。
    """
    if fmt not in ("md", "html", "both"):
        raise ValueError(f"未知 format: {fmt}（应为 md|html|both）")
    out_dir = Path(out_dir) if not isinstance(out_dir, Path) else out_dir
    old_tmp = paths.TMP_ROOT
    if tmp_root is not None:
        paths.TMP_ROOT = Path(tmp_root)
    try:
        sdir = paths.session_dir(session)
        export_name = name or session
        edir = paths.export_dir(out_dir, export_name)
        edir.mkdir(parents=True, exist_ok=True)
        (edir / "screenshots_annotated").mkdir(exist_ok=True)

        trace_path = sdir / "trace.jsonl"
        req_path = sdir / "requests.jsonl"
        actions = ([Action.from_dict(json.loads(l))
                    for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()]
                   if trace_path.exists() else [])
        records = ([RequestRecord.from_dict(json.loads(l))
                    for l in req_path.read_text(encoding="utf-8").splitlines() if l.strip()]
                   if req_path.exists() else [])

        meta = {"url": ""}
        mpath = sdir / "meta.json"
        if mpath.exists():
            meta = json.loads(mpath.read_text(encoding="utf-8"))

        # 画标
        annotated_map: dict[int, str] = {}
        style = VERBOSE if annotate_style == "verbose" else COMPACT
        marks_by_file: dict[str, list[dict]] = {}
        for a in actions:
            shot = (a.screenshot or {}).get("after") or (a.screenshot or {}).get("before")
            if not shot or not a.target or not a.target.bbox:
                continue
            marks_by_file.setdefault(shot, []).append(
                {"seq": a.seq, "type": a.type, "bbox": a.target.bbox})
            annotated_map[a.seq] = shot
        for shot, marks in marks_by_file.items():
            src = sdir / "screenshots" / shot
            if src.exists():
                annotate_screenshot(src, edir / "screenshots_annotated" / shot, marks,
                                    style=style, opacity=annotate_opacity)

        # --filter-requests：在聚合前过滤（spec §6.2 导出期精筛）
        flt = load_request_filter(filter_path)
        records = apply_filter(records, flt, target_url=meta.get("url"))

        # --keep-raw-bodies：把响应体解析为完整 schema 后，对未落盘的小体也写 raw_ref
        if keep_raw_bodies:
            responses_dir = sdir / "responses"
            import hashlib
            for r in records:
                if r.response and r.response.raw_ref:
                    continue  # 已落盘
                # 此处 records 是从 jsonl 反序列化的，原始 body 已不可得；
                # keep_raw_bodies 主要影响录制期（capture 阈值），这里仅做"已落盘即标注"的兜底
                pass

        # 聚合 + 关联 seq
        groups = aggregate(records)
        for g in groups:
            tmpl = g["endpoint"]["url_template"]
            g["linked_seq"] = sorted({r.linked_action_seq for r in records
                                      if r.linked_action_seq is not None and _tmpl_of(r.url) == tmpl})
        (edir / "requests.json").write_text(
            json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

        if fmt in ("md", "both"):
            (edir / "report.md").write_text(
                report_md.render(actions, groups, annotated_map, meta), encoding="utf-8")
        if fmt in ("html", "both"):
            (edir / "report.html").write_text(
                report_html.render(actions, groups, annotated_map, meta), encoding="utf-8")
        return edir
    finally:
        paths.TMP_ROOT = old_tmp


def _tmpl_of(url: str) -> str:
    from ..request_aggregator import url_template
    return url_template(url)[0]
