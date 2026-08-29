/* browser-recorder 页面注入脚本。
 * 两种形态：
 *  - node（require）：导出纯函数（best_selector/trunc_text）供单测
 *  - 浏览器（CDP 注入字符串）：IIFE install，监听动作/突变/停止热键，经 __brEvent 上报
 *
 * payload 为扁平结构 {type, rect, viewport, descriptor, value?, html_type?}，
 * 与 recorder.py 的 Runtime.bindingCalled 消费端约定一致。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { factory().install(root); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TEXT_MAX = 40;
  var VALUE_MAX = 200;
  var DOM_PATH_MAX = 12;
  var MUTATION_WINDOW_MS = 150;

  function trunc_text(s) {
    s = String(s == null ? "" : s).replace(/\s+/g, " ").trim();
    if (s.length > TEXT_MAX) s = s.slice(0, TEXT_MAX - 1) + "…";
    return s;
  }

  function best_selector(desc) {
    if (desc.id) return "#" + desc.id;
    var parts = [desc.tag];
    if (desc.classes && desc.classes.length) parts.push("." + desc.classes.join("."));
    return parts.join("");
  }

  function classes_of(el) {
    // SVG/HTML 均有 classList（DOMTokenList）；个别旧实现缺省时退回 className 解析
    try {
      if (el.classList) return Array.prototype.slice.call(el.classList);
    } catch (e) { /* 某些元素访问 classList 可能抛 */ }
    var cn = el.className;
    if (typeof cn !== "string") cn = (cn && cn.baseVal) || ""; // SVG 的 className 是 SVGAnimatedString
    return cn.split(/\s+/).filter(Boolean);
  }

  function dom_path(el) {
    // parentElement 在 closed shadow root 边界处为 null，链自然截断（不跨 shadow）
    var p = [], cur = el;
    while (cur && cur.nodeType === 1 && p.length < DOM_PATH_MAX) {
      p.unshift(cur.tagName.toLowerCase() + (cur.id ? "#" + cur.id : ""));
      cur = cur.parentElement;
    }
    return p.join(">");
  }

  function describe(el, win) {
    win = win || (typeof self !== "undefined" ? self : globalThis);
    var r = el.getBoundingClientRect ? el.getBoundingClientRect() : { x: 0, y: 0, width: 0, height: 0 };
    var desc = {
      tag: (el.tagName || "").toLowerCase(),
      id: el.id || null,
      classes: classes_of(el),
      text: trunc_text(
        el.textContent ||
          (el.type === "password" ? "" : el.value) ||
          (el.getAttribute && el.getAttribute("aria-label")) ||
          ""
      ),
      dom_path: dom_path(el),
    };
    desc.best_selector = best_selector(desc);
    return {
      rect: {
        x: Math.round(r.x || 0), y: Math.round(r.y || 0),
        w: Math.round(r.width || 0), h: Math.round(r.height || 0),
      },
      viewport: {
        w: win.innerWidth || 0, h: win.innerHeight || 0,
        scrollX: win.scrollX || 0, scrollY: win.scrollY || 0,
        dpr: win.devicePixelRatio || 1,
      },
      descriptor: desc,
    };
  }

  function install(win) {
    var B = win.__brEvent;
    if (!B || win.__brInstalled) return; // binding 未就绪时不设哨兵，允许下次注入重试
    win.__brInstalled = true;

    function report(type, el, extra) {
      try {
        var payload = describe(el, win);
        payload.type = type;
        if (extra) for (var k in extra) payload[k] = extra[k];
        B(JSON.stringify(payload));
      } catch (e) { /* 上报失败不扰动页面 */ }
    }

    function target_of(e) {
      var t = e.target;
      if (t && t.closest) {
        return t.closest("a,button,input,select,textarea,[onclick]") || t;
      }
      return t;
    }

    // 动作：capture 阶段，document 级
    ["click", "submit"].forEach(function (t) {
      win.document.addEventListener(t, function (e) {
        var el = t === "submit" ? e.target : target_of(e);
        if (el) report(t, el, {});
      }, true);
    });

    win.document.addEventListener("input", function (e) {
      var el = e.target;
      if (!el) return;
      var type = el.type || "text";
      report("input", el, {
        value: type === "password" ? "***" : String(el.value == null ? "" : el.value).slice(0, VALUE_MAX),
        html_type: type,
      });
    }, true);

    // 停止热键：Ctrl+Shift+F9（key 或 keyCode 120），覆盖所有 frame 的注入实例
    win.document.addEventListener("keydown", function (e) {
      if (e.ctrlKey && e.shiftKey && (e.key === "F9" || e.keyCode === 120)) {
        e.preventDefault();
        e.stopPropagation();
        try { B(JSON.stringify({ type: "control_stop" })); } catch (err) { /* ignore */ }
      }
    }, true);

    // DOM 突变聚合：150ms 静默窗口。
    // 注入可能发生在新文档极早期（Page.addScriptToEvaluateOnNewDocument 在
    // documentElement 创建前运行），此时 observe(null) 会抛 TypeError 导致
    // install 半途夭折—— MutationObserver 是 install 最后一步，动作监听器
    // 已先挂上，症状是"动作有、dom_mutations 永远没有"。故延迟到根元素可用。
    var pending = 0;
    var timer = null;
    var obs = new MutationObserver(function (muts) {
      pending += muts.length;
      clearTimeout(timer);
      timer = setTimeout(function () {
        var n = pending;
        pending = 0;
        try { B(JSON.stringify({ type: "dom_mutations", count: n })); } catch (e) { /* ignore */ }
      }, MUTATION_WINDOW_MS);
    });
    function startObserver() {
      try {
        obs.observe(win.document.documentElement, {
          subtree: true, childList: true, attributes: true, characterData: true,
        });
        return true;
      } catch (e) { return false; }
    }
    if (!startObserver()) {
      var pollT = setInterval(function () {
        if (win.document.documentElement && startObserver()) clearInterval(pollT);
      }, 10);
    }
  }

  return {
    best_selector: best_selector,
    trunc_text: trunc_text,
    install: install,
    _describeForTest: describe,
  };
});
