# browser_recorder/export/report_html.py
"""HTML 报告：内联 CSS，左侧步骤列表 + 右侧大图 + 接口折叠。"""
from __future__ import annotations
import html as _h
from ..models import Action

_CSS = """
body{font-family:sans-serif;margin:0;display:flex}
nav{width:280px;overflow:auto;background:#f5f5f5;padding:12px;border-right:1px solid #ddd}
main{padding:16px;flex:1}
.step{margin-bottom:24px;border:1px solid #eee;padding:12px;border-radius:6px}
.step img{max-width:100%;border:1px solid #ccc}
legend span{margin-right:12px;font-size:13px}
details{margin-top:8px;background:#fafafa;padding:8px;border-radius:4px}
.badge{display:inline-block;padding:2px 6px;border-radius:3px;color:#fff;font-size:12px}
.click{background:#dc2828}.input{background:#285adc}.select{background:#8c28c8}
.scroll{background:#dcaa1e}.navigation{background:#148c50}.hover{background:#787878}
"""


def _esc(s: str) -> str:
    return _h.escape(str(s))


def render(actions: list[Action], request_groups: list[dict],
           annotated_img_map: dict[int, str], meta: dict) -> str:
    by_seq: dict[int, list[dict]] = {}
    for g in request_groups:
        for s in g.get("linked_seq", []):
            by_seq.setdefault(s, []).append(g)
    legend = (
        '<legend><span class="badge click">click/submit</span>'
        '<span class="badge input">input</span>'
        '<span class="badge select">select</span>'
        '<span class="badge scroll">scroll</span>'
        '<span class="badge navigation">navigation</span>'
        '<span class="badge hover">hover</span></legend>')
    nav = "\n".join(f'<a href="#step-{a.seq}">步骤 {a.seq} · {_esc(a.type)}</a><br>' for a in actions)
    steps = []
    for a in actions:
        img = (a.screenshot or {}).get("after") or (a.screenshot or {}).get("before")
        img_html = (f'<img src="screenshots_annotated/{_esc(img)}" alt="步骤{a.seq}">'
                    if img and a.seq in annotated_img_map else "")
        reqs = by_seq.get(a.seq, [])
        req_html = ""
        if reqs:
            items = "".join(
                f"<li><code>{_esc(g['endpoint']['method'])} {_esc(g['endpoint']['url_template'])}</code> "
                f"（观测 {g['observations']} 次，状态 {g['sample_statuses']}）</li>" for g in reqs)
            req_html = f"<details><summary>触发的接口</summary><ul>{items}</ul></details>"
        steps.append(
            f'<div class="step" id="step-{a.seq}">'
            f'<span class="badge {_esc(a.type)}">{_esc(a.type)}</span> '
            f'<b>步骤 {a.seq}</b>'
            f'<div>定位: <code>{_esc((a.target.role_selector if a.target else None) or (a.target.css if a.target else ""))}</code></div>'
            f'{f"<div>输入: <code>{_esc(a.value)}</code></div>" if a.value else ""}'
            f'<div>URL: <code>{_esc(a.url)}</code></div>'
            f'{img_html}{req_html}</div>')
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<title>浏览器操作报告</title><style>" + _CSS + "</style></head><body>"
        "<nav><h3>步骤</h3>" + nav + "</nav>"
        "<main><h1>浏览器操作报告</h1><h2>图例</h2>" + legend +
        f"<p>目标 URL: <code>{_esc(meta.get('url', ''))}</code> · 动作数: {len(actions)}</p>"
        + "".join(steps) + "</main></body></html>")
