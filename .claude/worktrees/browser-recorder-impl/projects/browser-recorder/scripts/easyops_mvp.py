"""MVP e2e 驱动（正式版）：deepQuery（CSS/XPath + shadow 穿透）驱动 21 步。

用法：uv run python scripts/easyops_mvp.py <out_dir>
- 自动起 recorder 会话（headless），登录 + 21 步，Browser.close 优雅停止
- 产物：<out_dir>/{session.jsonl, screenshots/, PROMPT.md, drive_log.json}
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import socket
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from browser_recorder.cdp import CDPClient  # noqa: E402
from browser_recorder.recorder import record  # noqa: E402

LOGIN_URL = "http://172.30.0.90/next/auth/login"
USER, PASS = "easyops", "easyops"
CHROME = pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome"

# 21 步（来自 docs/MVPe2e.md）。loc 类型：css=CSS 选择器（含 shadow 穿透）、
# xpath=原样 XPath（经 lowercase 兜底）。用户 XPath 的自定义元素标签在 DOM 里
# 是大写（EO-LAUNCHPAD-BUTTON-V2），document.evaluate 大小写敏感 → MISS。
# 故凡能用 CSS 的步骤一律 CSS（querySelector 本身大小写不敏感且可穿透 open shadow）。
STEPS = [
    dict(n=1,  act="click", loc="css:eo-launchpad-button-v2, eo-launchpad-button-v2 a", desc="点击菜单(launchpad)"),
    dict(n=2,  act="input", loc="css:input[placeholder*=Search], input[placeholder*=search][type=text]", val="monitor", desc="输入 monitor"),
    dict(n=3,  act="click", loc="text:^monitor", desc="点击 monitor 应用"),
    dict(n=4,  act="click", loc="xpath://*[@id='main-mount-point']/eo-page-view/div/eo-category/eo-easy-view/basic-bricks.list-container/div/div[1]/basic-bricks.list-container/div/eo-card-item[2]//eo-link/div/div[1]", desc="点击模块卡片"),
    dict(n=5,  act="click", loc="xpath://*[@id='resource-detail-drawer']/eo-category/basic-bricks.list-container/div/eo-card-item[11]//eo-link/div/div[1]/div[1]", desc="点击资源卡片"),
    dict(n=6,  act="click", loc="css:#agentType label:nth-of-type(1) span:nth-of-type(1) input, #portal-mount-point #agentType label:nth-of-type(1) span:nth-of-type(1) input", desc="选择 agentType"),
    dict(n=7,  act="click", loc="css:#create-kit-modal button:nth-of-type(2) span, #portal-mount-point #create-kit-modal button:nth-of-type(2) span", desc="确认(新tab)"),
    dict(n=8,  act="input", loc="css:#name", val="e2e自动录制测试套件", desc="套件名称"),
    dict(n=9,  act="click", loc="css:#rc_select_20", desc="选择 OS 系统"),
    dict(n=10, act="input", loc="css:#rc-tabs-0-panel-1 textarea", val="e2e 自动录制生成的使用说明", desc="使用说明"),
    dict(n=11, act="click", loc="css:#scriptFrom label:nth-of-type(1) span:nth-of-type(1) input", desc="编写脚本"),
    dict(n=12, act="click", loc="css:#scriptType label:nth-of-type(1) span:nth-of-type(2)", desc="选 python"),
    dict(n=13, act="input", loc="css:#content > div:nth-of-type(2) > div", val="print('hello from browser-recorder e2e')", desc="脚本内容"),
    dict(n=14, act="click", loc="css:#foldBrickButton14 span:nth-of-type(2) svg", desc="弹开参数说明"),
    dict(n=15, act="click", loc="css:forms.dynamic-form-item-v2 form button", desc="添加参数"),
    dict(n=16, act="input", loc="css:#dynamicForm_0_name", val="e2e_param", desc="参数名"),
    dict(n=17, act="click", loc="css:forms.general-buttons button:nth-of-type(1) span, forms.general-buttons button", desc="提交保存"),
    dict(n=18, act="click", loc="css:basic-bricks.general-custom-buttons button", desc="更多"),
    dict(n=19, act="click", loc="css:body > div:nth-of-type(6) ul li:nth-of-type(4) div, #portal-mount-point ul li:nth-of-type(4) div", desc="删除套件"),
    dict(n=20, act="input", loc="css:body > div:nth-of-type(7) input, #portal-mount-point input[type=text]:visible", val="e2e自动录制测试套件", desc="确认删除-名称"),
    dict(n=21, act="click", loc="css:body > div:nth-of-type(7) button:nth-of-type(2), #portal-mount-point button:nth-of-type(2)", desc="删除"),
]

FIND_JS = r"""
(()=>{{
  const loc = {loc!r};
  const [kind, expr] = [loc.split(':',1)[0], loc.slice(loc.indexOf(':')+1)];
  // 深度优先穿透 open shadow root 的 querySelectorAll
  function deepAll(root, css) {{
    let out = [];
    let got = [];
    try {{ got = Array.from(root.querySelectorAll(css)); }} catch (e) {{ got = []; }}
    out = out.concat(got);
    for (const el of root.querySelectorAll('*')) {{
      if (el.shadowRoot) out = out.concat(deepAll(el.shadowRoot, css));
    }}
    return out;
  }}
  let els = [];
  if (kind === 'css') {{
    els = deepAll(document, expr);
    if (!els.length) return null;
  }} else if (kind === 'text') {{
    // 文本匹配：叶子元素文本匹配目标（默认包含；^前缀=词首匹配，用于区分
    // "monitor" 与 "Platform Service Monitoring" 这类包含关系），穿透 shadow
    const raw = expr;
    const anchor = raw.startsWith('^');
    const needle = (anchor ? raw.slice(1) : raw).toLowerCase();
    const hit = t => {{
      const s = (t || '').trim().toLowerCase();
      return anchor ? (s.startsWith(needle) || new RegExp('\\\\b' + needle).test(s))
                    : s.includes(needle);
    }};
    function deepText(root) {{
      let out = [];
      for (const el of root.querySelectorAll('*')) {{
        if (el.childElementCount === 0 && el.textContent && hit(el.textContent)) out.push(el);
        if (el.shadowRoot) out = out.concat(deepText(el.shadowRoot));
      }}
      return out;
    }}
    els = deepText(document);
    if (!els.length) return null;
  }} else {{
    // xpath：先原样，再对每段 tag 做 lowercase translate 重写（自定义元素在
    // DOM 中注册为大写，如 EO-LAUNCHPAD-BUTTON-V2）
    let xp = expr;
    const e1 = document.evaluate(xp, document, null, 9, null).singleNodeValue;
    if (e1) {{ els = [e1]; }}
    else {{
      // 全小写化 tag 名（dom 节点 name() 小写比较）
      const lc = xp.replace(/([A-Za-z][\w.-]*)/g, m => m.toLowerCase());
      const e2 = document.evaluate(lc, document, null, 9, null).singleNodeValue;
      els = e2 ? [e2] : [];
    }}
  }}
  // 可见性：offsetParent 或 clientRects 任一命中即算。headless 下动画/transform
  // 进场的弹层 rect 可能为 0×0 但 DOM 就绪可交互——追加"在文档且未显式
  // display:none"的放宽判据（hidden 属性与 display:none 样式仍排除）
  const vis = els.filter(e => {{
    if (e.offsetParent || e.getClientRects().length) return true;
    if (e.hidden || e.getAttribute('aria-hidden') === 'true') return false;
    const st = getComputedStyle(e);
    return st.display !== 'none' && st.visibility !== 'hidden';
  }});
  if (!vis.length && els.length) return {{found:'hidden', n:els.length}};
  if (!vis.length) return null;
  // 可点击祖先优先：text 命中的是叶子，click 语义元素在其祖先
  let e = vis[0];
  if (kind === 'text') {{
    let cur = e;
    for (let i = 0; i < 5 && cur; i++) {{
      const clicky = cur.closest && cur.closest('a, button, [role=button], [role=menuitem], eo-link, [class*=link], [class*=item]');
      if (!clicky || clicky === cur) break;
      cur = clicky;
    }}
    e = cur;
  }}
  e.scrollIntoView({{block: 'center'}});
  const r = e.getBoundingClientRect();
  return {{found:'ok', tag:e.tagName, id:e.id||'', text:(e.textContent||'').trim().slice(0,30),
           x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}};
}})()
"""

ACT_JS = r"""
(()=>{{
  const loc = {loc!r};
  const kind = loc.split(':',1)[0], expr = loc.slice(loc.indexOf(':')+1);
  function deepAll(root, css) {{
    let out = [];
    for (const el of root.querySelectorAll(css)) out.push(el);
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot)
      out = out.concat(deepAll(el.shadowRoot, css));
    return out;
  }}
  let els = [];
  if (kind === 'css') els = deepAll(document, expr);
  else {{
    const e1 = document.evaluate(expr, document, null, 9, null).singleNodeValue;
    if (e1) els = [e1];
    else {{
      const lc = expr.replace(/([A-Za-z][\w.-]*)/g, m => m.toLowerCase());
      const e2 = document.evaluate(lc, document, null, 9, null).singleNodeValue;
      els = e2 ? [e2] : [];
    }}
  }}
  const vis = els.filter(e => e.offsetParent || e.getClientRects().length);
  if (!vis.length) return 'NOT-FOUND';
  const e = vis[0];
  if ({is_input!r}) {{
    e.scrollIntoView({{block:'center'}});
    e.focus();
    const d = Object.getOwnPropertyDescriptor(e.__proto__, 'value');
    const v = {val!r};
    if (d && d.set) {{
      d.set.call(e, v);
      e.dispatchEvent(new Event('input', {{bubbles:true}}));
      e.dispatchEvent(new Event('change', {{bubbles:true}}));
    }} else {{
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, v);
    }}
    // antd Select 等受控搜索框：补 keyup 让下拉刷新
    e.dispatchEvent(new KeyboardEvent('keyup', {{key:v.slice(-1), bubbles:true}}));
    return 'INPUT-OK';
  }}
  e.scrollIntoView({{block:'center'}});
  e.click();
  return 'CLICK-OK';
}})()
"""

LOGIN_FILL = r"""
(()=>{{
  const us = Array.from(document.querySelectorAll('input[type=text]'))
    .filter(i=>i.offsetParent)[0];
  const pw = Array.from(document.querySelectorAll('input[type=password]'))
    .filter(i=>i.offsetParent)[0];
  if(!us||!pw) return 'no-input';
  const set=(el,v)=>{{const d=Object.getOwnPropertyDescriptor(el.__proto__,'value').set;
    el.focus(); d.call(el,v); el.dispatchEvent(new Event('input',{{bubbles:true}}));}};
  set(us, {user!r}); set(pw, {passwd!r});
  const btn = Array.from(document.querySelectorAll('button'))
    .find(b=>/sign in/i.test(b.textContent));
  setTimeout(()=>btn && btn.click(), 200);
  return 'sent';
}})()
"""


FOCUS_JS = r"""
(()=>{{
  const loc = {loc!r};
  const kind = loc.split(':',1)[0], expr = loc.slice(loc.indexOf(':')+1);
  function deepAll(root, css) {{
    let out = [];
    for (const el of root.querySelectorAll(css)) out.push(el);
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot)
      out = out.concat(deepAll(el.shadowRoot, css));
    return out;
  }}
  let els = [];
  if (kind === 'css') els = deepAll(document, expr);
  else {{
    const e1 = document.evaluate(expr, document, null, 9, null).singleNodeValue;
    if (e1) els = [e1];
    else {{
      const lc = expr.replace(/([A-Za-z][\w.-]*)/g, m => m.toLowerCase());
      els = [document.evaluate(lc, document, null, 9, null).singleNodeValue].filter(Boolean);
    }}
  }}
  const vis = els.filter(e => e.offsetParent || e.getClientRects().length);
  if (!vis.length) return 'NOT-FOUND';
  const e = vis[0];
  e.scrollIntoView({{block:'center'}});
  e.focus();
  if (e.select) e.select();  // 全选旧值（输入时覆盖）
  return 'FOCUSED:' + e.tagName;
}})()
"""


async def _real_type(b: CDPClient, sid: str, loc: str, find_js: str, val: str) -> str:
    """真键盘输入：先真鼠标点击元素中心（把合成器焦点给到页面元素——CDP Input
    域的焦点与 DOM focus 无关，headless 下必须真点击），再 insertText 输入。
    React/antd 受控组件对合成 input 事件不一定认，CDP 键盘路径是真实输入。"""
    import json as _json
    r = await b.send("Runtime.evaluate",
                     {"expression": find_js.format(loc=loc), "returnByValue": True},
                     session_id=sid)
    raw = r.get("result", {}).get("value")
    try:
        info = _json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        info = None
    if not info or info.get("found") != "ok":
        return "NOT-FOUND"
    # 0×0 元素（headless 动画残留）用 x+8/y+8 兜底坐标，正常元素用中心
    x = info["x"] + (max(1, info["w"] // 2) if info["w"] > 0 else 8)
    y = info["y"] + (max(1, info["h"] // 2) if info["h"] > 0 else 8)
    base = {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}
    await b.send("Input.dispatchMouseEvent", base, session_id=sid)
    await b.send("Input.dispatchMouseEvent",
                 {**base, "type": "mouseReleased"}, session_id=sid)
    await asyncio.sleep(0.3)
    await b.send("Input.dispatchKeyEvent",
                 {"type": "keyDown", "key": "a", "code": "KeyA",
                  "modifiers": 2}, session_id=sid)  # Ctrl+A
    await b.send("Input.dispatchKeyEvent",
                 {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2},
                 session_id=sid)
    await b.send("Input.dispatchKeyEvent",
                 {"type": "keyDown", "key": "Delete", "code": "Delete"},
                 session_id=sid)
    await b.send("Input.dispatchKeyEvent",
                 {"type": "keyUp", "key": "Delete", "code": "Delete"},
                 session_id=sid)
    # 逐字符 keyDown/keyUp（text 随 keyDown 派发——insertText 不触发 antd
    # 的 onChange 合成 input 监听，逐键路径才是真键盘等价）
    for ch in val:
        await b.send("Input.dispatchKeyEvent",
                     {"type": "keyDown", "key": ch, "text": ch},
                     session_id=sid)
        await b.send("Input.dispatchKeyEvent",
                     {"type": "keyUp", "key": ch}, session_id=sid)
        await asyncio.sleep(0.08)  # 模拟击键间隔，给防抖搜索留触发窗口
    return f"TYPED@{x},{y}:{val[:20]}"


async def _real_click(b: CDPClient, sid: str, loc: str, find_js: str) -> str:
    """用 CDP Input.dispatchMouseEvent 发真鼠标事件（pressed→released）。
    先经 find_js 拿元素中心坐标（视口系），再派发。返回状态串。"""
    import json as _json
    r = await b.send("Runtime.evaluate",
                     {"expression": find_js.format(loc=loc), "returnByValue": True},
                     session_id=sid)
    raw = r.get("result", {}).get("value")
    try:
        info = _json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        info = None
    if not info or info.get("found") != "ok":
        return "NOT-FOUND"
    x = info["x"] + (max(1, info["w"] // 2) if info["w"] > 0 else 8)
    y = info["y"] + (max(1, info["h"] // 2) if info["h"] > 0 else 8)
    base = {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}
    await b.send("Input.dispatchMouseEvent", base, session_id=sid)
    await b.send("Input.dispatchMouseEvent",
                 {**base, "type": "mouseReleased"}, session_id=sid)
    return f"REAL-CLICK@{x},{y}"


async def main():
    out_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(
        "/tmp/br-easyops-mvp/sess")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()

    rec_task = asyncio.create_task(
        record(out_dir, LOGIN_URL, CHROME, settle_timeout=30.0, port=port,
               headless=True, extra_chrome_args=["--no-sandbox"]))
    await asyncio.sleep(4)

    b = await CDPClient.connect_browser(port)
    logs = []

    async def ev(sid, expr):
        r = await b.send("Runtime.evaluate",
                         {"expression": expr, "returnByValue": True}, session_id=sid)
        return r.get("result", {}).get("value")

    # attach 启动 tab（recorder 已导航登录页）
    r = await b.send("Target.getTargets")
    page = [t for t in r["targetInfos"] if t["type"] == "page"
            and "auth/login" in t.get("url", "")]
    if not page:
        page = [t for t in r["targetInfos"] if t["type"] == "page"]
    r2 = await b.send("Target.attachToTarget",
                      {"targetId": page[0]["targetId"], "flatten": True})
    sid = r2["sessionId"]
    # CSS 禁动画兜底（recorder 启动参数已带 reduced-motion，这里双保险）。
    # addScriptToEvaluateOnNewDocument 只对新文档生效——直接 evaluate 到当前页。
    await b.send("Runtime.evaluate", {"expression":
        "(()=>{const s=document.createElement('style');"
        "s.textContent='*,*::before,*::after{animation:none!important;"
        "transition:none!important}';"
        "document.head&&document.head.appendChild(s);return 'css-ok';})()"},
        session_id=sid)

    # 等登录表单
    for _ in range(40):
        if await ev(sid, "document.querySelector('input[type=password]')?'y':'n'") == "y":
            break
        await asyncio.sleep(0.5)
    v = await ev(sid, LOGIN_FILL.format(user=USER, passwd=PASS))
    logs.append(("login", v))
    print("login:", v)
    # 等跳转 + portal 渲染
    for _ in range(30):
        await asyncio.sleep(1)
        url = await ev(sid, "location.href")
        if "auth/login" not in url:
            break
    print("post-login url:", url)
    await asyncio.sleep(3)  # SPA 渲染余量

    active = sid
    for st in STEPS:
        if st["n"] == 8:  # 切新 tab（step7 打开的）
            r = await b.send("Target.getTargets")
            newp = [t for t in r["targetInfos"]
                    if t["type"] == "page" and "about:blank" not in t.get("url", "")
                    and "auth/login" not in t.get("url", "")
                    and t["targetId"] != page[0]["targetId"]]
            if newp:
                r2 = await b.send("Target.attachToTarget",
                                  {"targetId": newp[0]["targetId"], "flatten": True})
                active = r2["sessionId"]
                logs.append(("switch-tab", newp[0].get("url", "")))
                print(f"--- 新 tab: {newp[0].get('url','')[:70]}")
                await asyncio.sleep(3)
        # 快轮询定位（150ms 间隔，总窗 ~12s）：弹层类元素出现即走，
        # 不固定等待——launchpad 面板等弹出层会在长时间无操作后收回
        info, ok = None, False
        deadline = asyncio.get_event_loop().time() + 12
        while asyncio.get_event_loop().time() < deadline:
            info = await ev(active, FIND_JS.format(loc=st["loc"]))
            ok = bool(info and info.get("found") == "ok")
            if ok:
                break
            await asyncio.sleep(0.15)
        act = None
        if ok:
            if st["act"] == "input":
                act = await _real_type(b, active, st["loc"], FIND_JS,
                                       st.get("val", ""))
            else:
                # 真鼠标事件序列（组件框架对合成 click 不总是响应）
                act = await _real_click(b, active, st["loc"], FIND_JS)
        logs.append((f"step{st['n']}", st["desc"], ok, act, info))
        print(f"step{st['n']:>2} [{st['desc']}] {'OK' if ok else 'MISS'}"
              f" {info or ''} -> {act}")
        # 动作后等页面反应：短轮询 DOM 稳定（新元素渲染或导航），
        # 兜底 3s（recorder 自己有 settle 判定不受此影响）
        await asyncio.sleep(st.get("wait", 2.0))

    try:
        await b.send("Browser.close")
    except Exception:
        pass
    result = await asyncio.wait_for(rec_task, 60)
    print("\n==== record ====")
    print(json.dumps(result, ensure_ascii=False))
    (pathlib.Path(result["out_dir"]) / "drive_log.json").write_text(
        json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    await b.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 900))
