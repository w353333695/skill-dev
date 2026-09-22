"""driver：浏览器驱动原语（locate / act / save_evidence）。

纯原语层：不读 flow、不知道步序。loc 候选前缀（首个命中即返回）：
  css:#id        deepQuery 穿透 open shadow root
  xpath://...    原样求值 + lowercase 兜底（自定义元素大写标签，如
                 EO-LAUNCHPAD-BUTTON-V2 在 DOM 中注册为大写）
  text:词        直接文本包含；^ 前缀=词首锚定（区分 "monitor" 与
                 "Platform Service Monitoring" 这类包含关系）
  dom:tag>tag#id 录制 dom_path 直译：逐段 querySelector 下降

act 信任派发为主（Input.dispatch*）→ evaluate 复检 → 不等才 JS 直调降级
（原生 setter + 合成 input/change 事件，React 受控输入兼容）。实际派发
方式经 on_dispatch 回调报上层落盘。
"""
from __future__ import annotations

import asyncio
import json
import pathlib

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
      // 可见性（easyops_mvp FIND_JS 沉库版）：offsetParent 或 clientRects
      // 任一命中即算。headless 下动画/transform 进场的弹层 rect 可能为
      // 0×0 但 DOM 就绪可交互——追加"未显式隐藏"的放宽判据；较 FIND_JS
      // 收紧一步：hidden/aria-hidden/display:none/visibility:hidden 祖先
      // 链全排除（FIND_JS 只查元素自身，display:none 子树会漏进放宽层）
      const vis = els.filter(el => {
        if (el.hidden || el.getAttribute('aria-hidden') === 'true') return false;
        for (let a = el; a; a = a.parentElement) {
          if (a.hidden || a.getAttribute('aria-hidden') === 'true') return false;
          const as = getComputedStyle(a);
          if (as.display === 'none' || as.visibility === 'hidden') return false;
        }
        return true;
      });
      const rectOf = el => {
        const r = el.getBoundingClientRect();
        return {
          el, x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2,
          w: r.width, h: r.height,
        };
      };
      const scored = vis.filter(el => el.getBoundingClientRect).map(rectOf);
      // 两级选择：优先有面积命中（主路径）；候选全零面积时放宽到"有盒"
      // （offsetParent/clientRects 命中——transform 动画 mid-flight 的 0×0，
      // 点击落在坍缩点仍可交互；display:none 子树已被上面的祖先链排除）
      const withArea = scored.filter(s => s.w > 0 && s.h > 0);
      const pick = withArea.length ? withArea
        : scored.filter(s => s.el.offsetParent || s.el.getClientRects().length);
      if (pick.length) {
        // 命中多个：取视口内最靠近中心的第一个（可预测），match_count 供上层告警
        const cx = innerWidth / 2, cy = innerHeight / 2;
        pick.sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy));
        return JSON.stringify(pick.slice(0, 10).map(s => ({
          rect: {x: Math.round(s.x - s.w / 2), y: Math.round(s.y - s.h / 2),
                 w: Math.round(s.w), h: Math.round(s.h)},
          tag: s.el.tagName ? s.el.tagName.toLowerCase() : '',
          text: (s.el.textContent || '').trim().slice(0, 40),
          id: s.el.id || null, name: s.el.name || null,
          classes: s.el.classList ? Array.from(s.el.classList).slice(0, 8) : [],
        }))) + '|' + pick.length;   // |N 尾巴带总命中数（截前 10 细节）
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


# ---------------------------------------------------------------------------
# act：施加动作
# ---------------------------------------------------------------------------

# 派发前滚动 + 重取 rect：locate 返回的是滚动前视口坐标，元素在视口外时
# 直接派发会点偏——scrollIntoView({block:'center'}) 后重新读 getBoundingClientRect
# （T6 审查 Minor-4）。deepAll 穿透 shadow（与 DEEP_QUERY_JS 同款）；
# 返回 '' 表示候选 css 未命中（保留旧 rect 降级，坐标可能偏但事件仍派发）。
_SCROLL_RECT_JS = r"""
(() => {
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
  const el = deepAll(document, {sel_json})[0];
  if (!el) return '';
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  return JSON.stringify({x: Math.round(r.x), y: Math.round(r.y),
                         w: Math.round(r.width), h: Math.round(r.height)});
})()
"""

# 受控输入复检靶：读 input/textarea 当前 value（非输入元素/未命中 → ''）。
INPUT_TRUSTED_CHECK_JS = "(document.querySelector({sel_json})||{}).value||''"


def _scroll_rect_js(sel: str) -> str:
    return _SCROLL_RECT_JS.replace("{sel_json}", json.dumps(sel, ensure_ascii=False))


def input_check_js(sel: str) -> str:
    """生成 INPUT_TRUSTED_CHECK_JS 的求值表达式（纯函数）。"""
    return INPUT_TRUSTED_CHECK_JS.replace("{sel_json}", json.dumps(sel, ensure_ascii=False))


def _css_of(locs: list[str]) -> str:
    """候选里第一个 css: 前缀的表达式（复检/降级用，deepAll 可穿透 shadow）；
    无 css 候选退化取首个候选的表达式按 css 试（text:/xpath: 语义在
    querySelector 下不保真——仅兜底，主路径应携带 css: 候选）。"""
    for loc in locs:
        if loc.startswith("css:"):
            return loc[4:]
    return (locs[0].split(":", 1)[1] if locs else "") or "body"


async def act(client, tabs: dict, tid: str, action: dict,
              on_dispatch=None) -> dict:
    """施加动作：信任派发为主，evaluate 复检不通过降级 JS 直调。

    action: {act: click|input|submit|hover, loc: [...], rect?, value?, clear?,
             expect_value?}
    rect 缺失时先 locate 补坐标；click/hover/input 的鼠标派发前先
    scrollIntoView 并重取 rect（视口坐标才是派发坐标系）。
    返回 {dispatch: "trusted"|"js-fallback"|"js", check: bool}；
    on_dispatch(kind) 回调把实际派发方式报上层落盘（降级时报 "js-fallback"）。
    """
    kind = action["act"]
    locs = action.get("loc") or []
    sid = _sid_of(tabs, tid)

    async def _rect() -> dict | None:
        if action.get("rect") and action["rect"].get("w"):
            return action["rect"]
        hit = await locate(client, tabs, tid, locs, timeout=5)
        return hit and hit["rect"]

    async def _scroll_fresh(rt: dict | None) -> dict | None:
        """滚动入视 + 重取 rect；JS 未命中（非 css 主候选）保留旧 rect。"""
        if not rt:
            return rt
        try:
            r = await client.send("Runtime.evaluate",
                                  {"expression": _scroll_rect_js(_css_of(locs)),
                                   "returnByValue": True}, session_id=sid)
            val = (r.get("result") or {}).get("value") or ""
            if val:
                fresh = json.loads(val)
                if fresh.get("w"):
                    return fresh
        except Exception:
            pass
        return rt

    if kind in ("click", "hover"):
        rt = await _scroll_fresh(await _rect())
        if not rt:
            # 定位失败由上层重试协议处理（重试耗尽 → save_evidence）
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": False}
        x, y = rt["x"] + rt["w"] / 2, rt["y"] + rt["h"] / 2
        evs = [{"type": "mouseMoved", "x": x, "y": y}]
        if kind == "click":
            # clickCount（CDP 规范字段，非 clicks）：浏览器据此在
            # pressed+released 后合成 DOM click 事件——写错名不报错但无 click
            evs += [{"type": "mousePressed", "x": x, "y": y,
                     "button": "left", "clickCount": 1},
                    {"type": "mouseReleased", "x": x, "y": y,
                     "button": "left", "clickCount": 1}]
        for ev in evs:
            await client.send("Input.dispatchMouseEvent", ev, session_id=sid)
        # click 复检：dom_mutations 脉冲经 harness.state 感知（flow 层结合
        # wait_stable 判定）；pressed/released 信任派发本身即事实，这里不设阻塞性复检
        if on_dispatch:
            on_dispatch("trusted")
        return {"dispatch": "trusted", "check": True}

    if kind == "input":
        # 聚焦（信任点击）→ 清空（Ctrl+A + Delete）→ 逐键 char
        rt = await _scroll_fresh(await _rect())
        if rt:
            cx, cy = rt["x"] + rt["w"] / 2, rt["y"] + rt["h"] / 2
            for ev in ({"type": "mousePressed", "x": cx, "y": cy,
                        "button": "left", "clickCount": 1},
                       {"type": "mouseReleased", "x": cx, "y": cy,
                        "button": "left", "clickCount": 1}):
                await client.send("Input.dispatchMouseEvent", ev, session_id=sid)
        if action.get("clear", True):
            for ev in ({"type": "keyDown", "modifiers": 2, "key": "a", "code": "KeyA"},
                       {"type": "keyUp", "modifiers": 2, "key": "a", "code": "KeyA"},
                       {"type": "keyDown", "key": "Delete", "code": "Delete",
                        "windowsVirtualKeyCode": 46},
                       {"type": "keyUp", "key": "Delete", "code": "Delete",
                        "windowsVirtualKeyCode": 46}):
                await client.send("Input.dispatchKeyEvent", ev, session_id=sid)
        for ch in action.get("value", ""):
            await client.send("Input.dispatchKeyEvent",
                              {"type": "char", "text": ch}, session_id=sid)
        # 复检：evaluate 读 value == 预期（expect_value 优先，缺省 value）
        expected = action.get("expect_value", action.get("value", ""))
        sel = _css_of(locs)
        try:
            r = await client.send("Runtime.evaluate",
                                  {"expression": input_check_js(sel),
                                   "returnByValue": True}, session_id=sid)
            got = (r.get("result") or {}).get("value") or ""
        except Exception:
            got = ""
        if got == expected:
            if on_dispatch:
                on_dispatch("trusted")
            return {"dispatch": "trusted", "check": True}
        # 降级：原生 setter + 合成事件（React 受控输入兼容——值劫持 value
        # setter 才能绕过框架的重渲染拦截，input/change 冒泡触发框架监听）
        fallback_js = (
            "((sel, val) => {"
            "  const el = document.querySelector(sel);"
            "  if (!el) return 'no-el';"
            "  const proto = el instanceof HTMLTextAreaElement"
            "    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
            "  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;"
            "  setter.call(el, val);"
            "  el.dispatchEvent(new Event('input', {bubbles: true}));"
            "  el.dispatchEvent(new Event('change', {bubbles: true}));"
            "  return el.value;"
            f"}})({json.dumps(sel, ensure_ascii=False)},"
            f" {json.dumps(action.get('value', ''), ensure_ascii=False)})"
        )
        try:
            r = await client.send("Runtime.evaluate",
                                  {"expression": fallback_js,
                                   "returnByValue": True}, session_id=sid)
            got = (r.get("result") or {}).get("value") or ""
        except Exception:
            got = ""
        if on_dispatch:
            on_dispatch("js-fallback")
        return {"dispatch": "js-fallback", "check": got == expected}

    if kind == "submit":
        # 提交按钮优先 click；无按钮 requestSubmit（submit 语义本就依赖 JS 钩子，
        # 此动作固定走 JS 派发——按钮的 click() 是用户等价操作，事件为 untrusted
        # 但 onsubmit 链路不受 isTrusted 门禁的常见实现影响）
        btn_js = (
            "((sel) => {"
            "  const form = document.querySelector(sel);"
            "  if (!form) return 'no-form';"
            "  const btn = form.querySelector("
            "      'button[type=submit],input[type=submit]');"
            "  if (btn) { btn.click(); return 'btn'; }"
            "  form.requestSubmit(); return 'requestSubmit';"
            f"}})({json.dumps(_css_of(locs), ensure_ascii=False)})"
        )
        try:
            r = await client.send("Runtime.evaluate",
                                  {"expression": btn_js, "returnByValue": True},
                                  session_id=sid)
            how = (r.get("result") or {}).get("value") or ""
        except Exception:
            how = ""
        if on_dispatch:
            on_dispatch("js" if how in ("btn", "requestSubmit") else "js-fallback")
        return {"dispatch": "js", "check": how in ("btn", "requestSubmit")}

    raise ValueError(f"unknown act: {kind}")


async def save_evidence(out_dir, client, tabs: dict, tid: str,
                        step: dict) -> pathlib.Path:
    """失败证据包：<out>/evidence/fail-step<N>/{screenshot.png, dom.json, context.json}。

    截图/DOM 抓取各自容错（连接已断/导航中——失败证据不该被采集异常掩盖，
    context.json 无条件落盘）。返回证据目录。
    """
    import base64

    d = pathlib.Path(out_dir) / "evidence" / f"fail-step{step.get('n', 0)}"
    d.mkdir(parents=True, exist_ok=True)
    sid = _sid_of(tabs, tid)
    try:
        shot = await client.send("Page.captureScreenshot", {"format": "png"},
                                 session_id=sid)
        (d / "screenshot.png").write_bytes(base64.b64decode(shot["data"]))
    except Exception:
        pass   # 截图失败不掩盖主错误
    try:
        r = await client.send("Runtime.evaluate",
                              {"expression": "document.documentElement.outerHTML",
                               "returnByValue": True}, session_id=sid)
        html = (r.get("result") or {}).get("value") or ""
        (d / "dom.json").write_text(json.dumps(
            {"url": step.get("url"), "html": html[:512 * 1024]}, ensure_ascii=False))
    except Exception:
        pass
    (d / "context.json").write_text(json.dumps(step, ensure_ascii=False, indent=2))
    return d
