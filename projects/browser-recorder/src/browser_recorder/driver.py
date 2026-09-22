"""driver：浏览器驱动原语（locate / wait_for）。

纯原语层：不读 flow、不知道步序。loc 候选前缀（首个命中即返回）：
  css:#id        deepQuery 穿透 open shadow root
  xpath://...    原样求值 + lowercase 兜底（自定义元素大写标签，如
                 EO-LAUNCHPAD-BUTTON-V2 在 DOM 中注册为大写）
  text:词        直接文本包含；^ 前缀=词首锚定（区分 "monitor" 与
                 "Platform Service Monitoring" 这类包含关系）
  dom:tag>tag#id 录制 dom_path 直译：逐段 querySelector 下降
"""
from __future__ import annotations

import asyncio
import json

# easyops_mvp.py FIND_JS 沉库版：单 loc → 四策略候选链。async IIFE，
# 返回 "<JSON数组>|<总命中数>" 字符串（无命中 "[]|0"），配合
# Runtime.evaluate 的 awaitPromise + returnByValue。
# 与 FIND_JS 的差异（沉库时的收敛）：
#   - 多 loc 候选链一次求值（FIND_JS 一 loc 一求值）
#   - text 匹配从"叶子元素"放宽为"直接文本节点命中"（父子不重复命中）
#   - deepAll 支持元素根穿透自身 shadowRoot（dom: 逐段下降跨 shadow 用）
DEEP_QUERY_JS = r"""
(async () => {
  const locs = {locs_json};
  function deepAll(root, css) {
    let out = [];
    try { out = Array.from(root.querySelectorAll(css)); } catch (e) {}
    let all = [];
    try { all = Array.from(root.querySelectorAll('*')); } catch (e) {}
    if (root.shadowRoot) out = out.concat(deepAll(root.shadowRoot, css));
    for (const el of all) {
      if (el.shadowRoot) out = out.concat(deepAll(el.shadowRoot, css));
    }
    return out;
  }
  for (const loc of locs) {
    const kind = loc.split(':', 1)[0];
    const expr = loc.slice(loc.indexOf(':') + 1);
    let els = [];
    if (kind === 'css') {
      els = deepAll(document, expr);
    } else if (kind === 'xpath') {
      let snap = null;
      try { snap = document.evaluate(expr, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); }
      catch (e) { snap = null; }
      if (snap) for (let i = 0; i < snap.snapshotLength; i++) els.push(snap.snapshotItem(i));
      if (!els.length) {  // lowercase 兜底（自定义元素大写标签）
        const low = expr.toLowerCase();
        if (low !== expr) {
          try { snap = document.evaluate(low, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); }
          catch (e) { snap = null; }
          if (snap) for (let i = 0; i < snap.snapshotLength; i++) els.push(snap.snapshotItem(i));
        }
      }
    } else if (kind === 'text') {
      const anchor = expr.startsWith('^');
      const needle = (anchor ? expr.slice(1) : expr).toLowerCase();
      const hit = t => {
        const s = (t || '').trim().toLowerCase();
        if (!anchor) return s.includes(needle);
        if (s.startsWith(needle)) return true;
        try { return new RegExp('\\b' + needle).test(s); } catch (e) { return false; }
      };
      for (const el of deepAll(document, '*')) {
        const direct = Array.from(el.childNodes || []).filter(n => n.nodeType === 3)
          .map(n => n.textContent).join('');
        if (hit(direct)) els.push(el);
      }
    } else if (kind === 'dom') {
      // dom_path 直译：div#app>span.btn → 逐段 querySelector 下降（deepAll 穿透）
      const parts = expr.split('>');
      let cur = [document];
      for (const seg of parts) {
        const nxt = [];
        for (const node of cur) {
          const m = seg.match(/^([a-z0-9_-]+)(#([\w-]+))?((?:\.[\w-]+)*)$/i);
          if (!m) continue;
          let css = m[1];
          if (m[3]) css += '#' + m[3];
          if (m[4]) css += m[4];
          for (const el of deepAll(node, css)) nxt.push(el);
        }
        cur = nxt;
        if (!cur.length) break;
      }
      els = cur;
    }
    if (els.length) {
      const scored = els.filter(el => el.getBoundingClientRect).map(el => {
        const r = el.getBoundingClientRect();
        return {
          el, x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2,
          w: r.width, h: r.height,
        };
      }).filter(s => s.w > 0 && s.h > 0);
      if (scored.length) {
        // 命中多个：取视口内最靠近中心的第一个（可预测），match_count 供上层告警
        const cx = innerWidth / 2, cy = innerHeight / 2;
        scored.sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy));
        return JSON.stringify(scored.slice(0, 10).map(s => ({
          rect: {x: Math.round(s.x - s.w / 2), y: Math.round(s.y - s.h / 2),
                 w: Math.round(s.w), h: Math.round(s.h)},
          tag: s.el.tagName ? s.el.tagName.toLowerCase() : '',
          text: (s.el.textContent || '').trim().slice(0, 40),
          id: s.el.id || null, name: s.el.name || null,
          classes: s.el.classList ? Array.from(s.el.classList).slice(0, 8) : [],
        }))) + '|' + scored.length;   // |N 尾巴带总命中数（截前 10 细节）
      }
    }
  }
  return '[]|0';
})()
"""


def find_elements_js(locs: list[str]) -> str:
    """生成 deepQuery JS（Runtime.evaluate 的 expression）。纯函数。"""
    return DEEP_QUERY_JS.replace("{locs_json}", json.dumps(locs, ensure_ascii=False))


async def locate(client, tabs: dict, tid: str, locs: list[str],
                 timeout: float = 10.0) -> dict | None:
    """候选链按序试：首个命中即返回 {rect, tag, text, id, name, classes,
    match_count}（id/name/classes 供上层拼 descriptor 候选）。全 miss → None。

    200ms 轮询直到 timeout（元素可能晚出现）。evaluate 瞬态失败（导航中
    context 消失）按本轮 miss 处理，不中断轮询。
    """
    sid = _sid_of(tabs, tid)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            r = await client.send("Runtime.evaluate",
                                  {"expression": find_elements_js(locs),
                                   "awaitPromise": True, "returnByValue": True},
                                  session_id=sid)
        except Exception:
            r = {}
        val = (r.get("result") or {}).get("value") or "[]|0"
        arr_txt, _, count = val.rpartition("|")
        if arr_txt not in ("", "[]"):
            arr = json.loads(arr_txt)
            if arr:
                return {**arr[0], "match_count": int(count)}
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.2)


def _sid_of(tabs: dict, tid: str) -> str | None:
    """tid → CDP sessionId 反查。tabs 是 {sid: tab}，tab 带 .tid/.sid。

    优先回 tab.sid（harness 语义下与 dict key 一致）；page target 直连
    （无 flatten 子会话）时 tab.sid 为 None → 定向 session_id=None。
    """
    for tab in tabs.values():
        if tab.tid == tid:
            return getattr(tab, "sid", None)
    return None


async def wait_for_element(client, tabs, tid, locs, timeout: float = 10.0) -> dict | None:
    """轮询 locate 直到命中（locate 自带 200ms 轮询，这里语义化命名）。"""
    return await locate(client, tabs, tid, locs, timeout=timeout)
