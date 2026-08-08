# browser_recorder/export/report_md.py
"""Markdown 报告：每步序号+类型+描述+画标截图+关联接口。"""
from __future__ import annotations
from ..models import Action

_LEGEND = (
    "**图例**：🔴 click/submit · 🔵 input · 🟣 select · 🟡 scroll · 🟢 navigation · ⚪ hover\n\n"
)


def _step_line(a: Action, img_map: dict[int, str], reqs_for_seq: list[dict]) -> str:
    lines = [f"### 步骤 {a.seq} — `{a.type}`"]
    desc_bits = [f"- 类型: `{a.type}`"]
    if a.target and (a.target.css or a.target.role_selector):
        desc_bits.append(f"- 定位: `{a.target.role_selector or a.target.css}`")
    if a.value:
        desc_bits.append(f"- 输入: `{a.value}`")
    desc_bits.append(f"- URL: `{a.url}`")
    lines.append("\n".join(desc_bits))
    # 与标注图（marks_by_file→annotated_map）同源：img_map[seq] 已由 _pick_shot 决定
    # （click→before，其余→after）。不能硬取 screenshot.after——会与标注图不一致 → 图裂。
    img = img_map.get(a.seq)
    if img:
        lines.append(f"\n![步骤{a.seq}](screenshots_annotated/{img})")
    if reqs_for_seq:
        lines.append("\n**触发的接口：**")
        for g in reqs_for_seq:
            ep = g["endpoint"]
            lines.append(f"- `{ep['method']} {ep['url_template']}`（观测 {g['observations']} 次，状态 {g['sample_statuses']}）")
    return "\n".join(lines)


def render(actions: list[Action], request_groups: list[dict],
           annotated_img_map: dict[int, str], meta: dict) -> str:
    by_seq: dict[int, list[dict]] = {}
    for g in request_groups:
        for s in g.get("linked_seq", []):
            by_seq.setdefault(s, []).append(g)
    parts = ["# 浏览器操作报告", "", _LEGEND]
    parts.append(f"- 目标 URL: `{meta.get('url', '')}`")
    parts.append(f"- 动作数: {len(actions)}")
    parts.append("\n---\n")
    for a in actions:
        parts.append(_step_line(a, annotated_img_map, by_seq.get(a.seq, [])))
        parts.append("\n---\n")
    if request_groups:
        parts.append("## 接口清单（聚合）\n")
        for g in request_groups:
            ep = g["endpoint"]
            parts.append(f"### `{ep['method']} {ep['url_template']}`")
            parts.append(f"- 观测次数: {g['observations']}")
            parts.append(f"- 状态码: {g['sample_statuses']}")
            if ep.get("param_path"):
                parts.append(f"- 路径/查询参数: {', '.join(ep['param_path'])}")
            parts.append(f"- 字段 schema: `{g['merged_schema']}`")
            parts.append("")
    return "\n".join(parts)
