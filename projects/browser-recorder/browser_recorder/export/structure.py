# browser_recorder/export/structure.py
"""结构化分章输入：按 navigation 动作 / URL path 变化把 actions 切成页面段。

确定性「脏活」：export 产 structure.json，供 skill 里的 Claude 据段做语义分章、
起层级标题。规则可解释、可单测，无语义判断。
"""
from __future__ import annotations
from urllib.parse import urlparse
from ..models import Action


def _path_of(url: str) -> str:
    return urlparse(url or "").path


def build_segments(actions: list[Action], groups: list[dict]) -> dict:
    """返回 ``{url, segments, actions_total, endpoints_total}``。

    分段：首个动作起一段；遇 ``type=="navigation"`` 或 URL path 变化开新段。
    每段 ``linked_endpoints`` = 该段动作命中的接口组（按 method+url_template 去重）。

    ``groups`` 元素需含 ``endpoint.{method,url_template}``、``observations``、
    ``linked_seq``（见 ``request_aggregator.aggregate`` + ``export.runner`` 装配）。
    """
    # (method, tmpl) -> observations；seq -> 命中的接口 key 列表
    ep_obs: dict[tuple[str, str], int] = {}
    seq_to_eps: dict[int, list[tuple[str, str]]] = {}
    ep_keys: set[tuple[str, str]] = set()
    for g in groups:
        ep = g["endpoint"]
        key = (ep["method"], ep["url_template"])
        ep_keys.add(key)
        ep_obs[key] = g.get("observations", 0)
        for s in g.get("linked_seq", []):
            seq_to_eps.setdefault(s, []).append(key)

    segments: list[dict] = []
    cur: dict | None = None
    for a in actions:
        start_new = (cur is None or a.type == "navigation"
                     or _path_of(a.url) != _path_of(cur["page_url"]))
        if start_new:
            cur = {"index": len(segments), "page_url": a.url,
                   "entry_action_seq": a.seq, "action_seqs": [], "_eps": []}
            segments.append(cur)
        cur["action_seqs"].append(a.seq)
        for key in seq_to_eps.get(a.seq, []):
            if key not in cur["_eps"]:
                cur["_eps"].append(key)

    out_segs = [{
        "index": s["index"],
        "page_url": s["page_url"],
        "entry_action_seq": s["entry_action_seq"],
        "action_seqs": s["action_seqs"],
        "linked_endpoints": [
            {"method": k[0], "url_template": k[1], "observations": ep_obs.get(k, 0)}
            for k in s["_eps"]],
    } for s in segments]

    return {
        "url": actions[0].url if actions else "",
        "segments": out_segs,
        "actions_total": len(actions),
        "endpoints_total": len(ep_keys),
    }
