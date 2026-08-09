"""事件捕获注入：RECORDER_JS + install(context)。

设计要点：
- context 级 add_init_script + expose_function，一次安装，所有导航/新 tab 自动生效
  （CDP attach 已有页面时对"未来导航"生效，调用方需 goto/reload 强制注入）。
- JS 侧算好 SelectorSet 全候选（testid → role+name → id → text → css）。
- input 防抖：change/blur 定稿，或 500ms 静默定稿。
- 防丢：payload 先进 sessionStorage.__br_pending，导航后重跑时 flush 补发（id 去重）。
- iframe：window.__recordEvent 不存在时尝试 parent，跨域 catch 后 console.warn 丢弃。
"""

from __future__ import annotations

from typing import Callable

RECORDER_JS = r"""
(() => {
  if (window.__brInstalled) return;
  window.__brInstalled = true;

  const PENDING_KEY = "__br_pending";
  let seq = 0;

  function bridge() {
    if (typeof window.__recordEvent === "function") return window.__recordEvent;
    try {
      if (window.parent && typeof window.parent.__recordEvent === "function") {
        return window.parent.__recordEvent;
      }
    } catch (e) { /* 跨域 iframe */ }
    return null;
  }

  function enqueue(payload) {
    payload.id = `${Date.now()}-${++seq}`;
    try {
      const pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "[]");
      pending.push(payload);
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending.slice(-200)));
    } catch (e) { /* sessionStorage 不可用时直接发 */ }
    deliver(payload);
  }

  function deliver(payload) {
    const fn = bridge();
    if (fn) {
      try { fn(JSON.stringify(payload)); } catch (e) { /* 页面销毁中 */ }
    } else {
      console.warn("[browser-recorder] 无 __recordEvent 桥，事件暂存: " + payload.type);
    }
  }

  // 导航后重跑时补发暂存事件（幂等靠 Python 侧 payload.id 去重）
  function flushPending() {
    if (typeof window.__recordEvent !== "function") return;
    let pending;
    try {
      pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "[]");
      sessionStorage.removeItem(PENDING_KEY);
    } catch (e) { return; }
    for (const p of pending) deliver(p);
  }

  // ---------- SelectorSet 生成 ----------

  function isDynamicIdent(s) {
    // ember123 / css-1x2y3z / :r0: 这类动态 id/class 不稳定，不采用
    return /(^|[-_:])\d{2,}/.test(s) || /[0-9a-f]{8,}/i.test(s);
  }

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return s.replace(/([^\w-])/g, "\\$1");
  }

  function textOf(el) {
    const t = (el.innerText || el.value || el.getAttribute("aria-label") || "").trim();
    return t.length > 40 ? t.slice(0, 40) : t;
  }

  function roleOf(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "button" || (tag === "input" && ["button", "submit", "reset"].includes(type))) return "button";
    if (tag === "a" && el.href) return "link";
    if (tag === "select") return "combobox";
    if (tag === "textarea" || (tag === "input" && !["checkbox", "radio"].includes(type))) return "textbox";
    if (tag === "input" && type === "checkbox") return "checkbox";
    if (tag === "input" && type === "radio") return "radio";
    return null;
  }

  function labelOf(el) {
    // 关联 label > aria-label > placeholder > 元素自身文本
    if (el.id) {
      const lbl = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (lbl && lbl.innerText.trim()) return lbl.innerText.trim().slice(0, 40);
    }
    return (el.getAttribute("aria-label") || el.getAttribute("placeholder") || textOf(el) || el.name || null);
  }

  function cssPath(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.body) {
      let part = cur.tagName.toLowerCase();
      if (cur.id && !isDynamicIdent(cur.id)) {
        part += "#" + cssEscape(cur.id);
        parts.unshift(part);
        break;
      }
      const stable = [...cur.classList].filter(c => !isDynamicIdent(c)).slice(0, 2);
      if (stable.length) part += "." + stable.map(cssEscape).join(".");
      const parent = cur.parentElement;
      if (parent) {
        const same = [...parent.children].filter(c => c.tagName === cur.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function selectorsFor(el) {
    const out = {};
    const testid = el.getAttribute("data-testid") || el.getAttribute("data-test-id");
    if (testid) out.testid = `[data-testid="${testid}"]`;
    const role = roleOf(el);
    const label = labelOf(el);
    if (role && label) out.role_name = `role=${role}[name="${label.replace(/"/g, '\\"')}"]`;
    else if (role) out.role_name = `role=${role}`;
    if (el.id && !isDynamicIdent(el.id)) out.id = "#" + cssEscape(el.id);
    const text = textOf(el);
    if (text && ["button", "link"].includes(role)) out.text = `text=${text}`;
    out.css = cssPath(el);
    return out;
  }

  // ---------- 事件捕获 ----------

  function basePayload(type, el) {
    return {
      type,
      url: location.href,
      selectors: el ? selectorsFor(el) : {},
      label: el ? labelOf(el) : null,
    };
  }

  document.addEventListener("click", (e) => {
    const el = e.target.closest("button, a, input[type=submit], input[type=button], [role=button], select, summary")
      || e.target;
    const p = basePayload("click", el);
    p.point = { x: Math.round(e.clientX), y: Math.round(e.clientY) };
    enqueue(p);
  }, true);

  // mousedown 提前通知：click 的默认行为/页面响应在 mousedown 之后才发生，
  // 此时截图是"点击前"的干净画面。通过独立的 __recordMouseDown 桥立即通知
  // Python 截图（同步阶段触发，赶在页面响应前）。
  document.addEventListener("mousedown", (e) => {
    const fn = window.__recordMouseDown ||
      (() => { try { return window.parent && window.parent.__recordMouseDown; } catch (err) { return null; } })();
    if (typeof fn !== "function") return;
    try {
      fn(JSON.stringify({ x: Math.round(e.clientX), y: Math.round(e.clientY), url: location.href }));
    } catch (err) { /* 忽略 */ }
  }, true);

  // input 防抖：静默 500ms 或 change/blur 定稿
  let pendingInput = null;
  let inputTimer = null;

  function commitInput() {
    if (pendingInput) {
      enqueue(pendingInput);
      pendingInput = null;
    }
    if (inputTimer) { clearTimeout(inputTimer); inputTimer = null; }
  }

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!el.matches("input, textarea")) return;
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (["checkbox", "radio", "button", "submit", "file"].includes(type)) return;
    const p = basePayload("input", el);
    p.value = el.value;
    p.sensitive = type === "password";
    pendingInput = p;
    if (inputTimer) clearTimeout(inputTimer);
    inputTimer = setTimeout(commitInput, 500);
  }, true);

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.tagName === "SELECT") {
      commitInput();
      const p = basePayload("select", el);
      p.value = el.value;
      p.label = labelOf(el);
      enqueue(p);
    } else if (el.matches("input, textarea")) {
      commitInput(); // input 已有 pending 则定稿（change 拿到的值相同）
    }
  }, true);

  document.addEventListener("blur", commitInput, true);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "Tab") {
      commitInput();
      if (e.key === "Enter") {
        const p = basePayload("key", e.target);
        p.value = "Enter";
        enqueue(p);
      }
    }
  }, true);

  // SPA 路由变化：hook history API，记 navigate 步骤（无整页导航时）
  let lastUrl = location.href;
  function onRouteChange() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    const p = basePayload("navigate", null);
    p.value = location.href;
    enqueue(p);
  }
  for (const m of ["pushState", "replaceState"]) {
    const orig = history[m];
    history[m] = function (...args) {
      const r = orig.apply(this, args);
      onRouteChange();
      return r;
    };
  }
  window.addEventListener("popstate", onRouteChange);
  window.addEventListener("hashchange", onRouteChange);

  // 初次注入（含每次导航后）补发暂存事件
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", flushPending);
  } else {
    flushPending();
  }
})();
"""


def install(context, on_event: Callable[[dict], None], on_mousedown: Callable[[dict], None] | None = None) -> None:
    """在 context 安装事件捕获：注入脚本 + 暴露 __recordEvent 桥。

    重要：binding 用 **page 级** expose_function，不用 context 级。
    实测（playwright 1.62 + CDP attach）：context 级 expose_function 注册的
    binding 在 attach 的 context 上不触发回调（init script 正常，binding 消息
    不回本 session）；page 级正常。因此 install 时对已有 page 逐个暴露，
    并通过 context.on("page") 给未来新 tab 补挂。
    init script 仍用 context 级（对新导航/新 tab 自动生效，实测正常）。

    CDP attach 已有页面时，调用方需在 install 后 goto/reload 一次保证注入。
    """
    import json

    def _make_bridge():
        def _bridge(payload: str) -> None:
            try:
                on_event(json.loads(payload))
            except Exception:
                pass  # 单个事件解析失败不中断录制
        return _bridge

    def _make_mousedown_bridge():
        def _bridge(payload: str) -> None:
            try:
                if on_mousedown:
                    on_mousedown(json.loads(payload))
            except Exception:
                pass
        return _bridge

    def _expose(page) -> None:
        try:
            page.expose_function("__recordEvent", _make_bridge())
        except Exception:
            pass  # 页面关闭中等场景忽略
        try:
            page.expose_function("__recordMouseDown", _make_mousedown_bridge())
        except Exception:
            pass

    for page in context.pages:
        _expose(page)
    context.on("page", _expose)
    context.add_init_script(RECORDER_JS)
