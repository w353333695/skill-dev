# browser_recorder/record/injector.py
"""页面注入钩子：捕获用户事件 + 计算元素定位包 + bbox，回传 Python。"""
from __future__ import annotations
import time


def build_event(node_dict: dict, type: str, value: str | None) -> dict:
    return {"type": type, "target_node": node_dict, "value": value, "ts": int(time.time() * 1000)}


INJECT_SCRIPT = r"""
(function(){
  try { console.log('[browser-recorder] INJECT_SCRIPT on', location.href); } catch(_){}
  document.__br_inject_count = (document.__br_inject_count || 0) + 1;
  if (!window.__br_evt_seen) window.__br_evt_seen = new WeakSet();
  function cssPath(el){
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 5){
      var part = el.nodeName.toLowerCase();
      if (el.className && typeof el.className === 'string'){
        var cls = el.className.trim().split(/\s+/)[0];
        if (cls) part += '.' + CSS.escape(cls);
      }
      var sib = el, nth = 1;
      while ((sib = sib.previousElementSibling)) nth++;
      part += ':nth-of-type(' + nth + ')';
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }
  function xpath(el){
    if (el.id) return '//*[@id="' + el.id + '"]';
    var parts = [];
    while (el && el.nodeType === 1){
      var i = 1, sib = el;
      while ((sib = sib.previousElementSibling)){
        if (sib.nodeName === el.nodeName) i++;
      }
      parts.unshift(el.nodeName.toLowerCase() + '[' + i + ']');
      el = el.parentElement;
    }
    return '/' + parts.join('/');
  }
  function nodeInfo(el){
    var r = el.getBoundingClientRect();
    var role = el.getAttribute('role') || null;
    var name = el.getAttribute('aria-label') || el.getAttribute('name') || null;
    var text = (el.innerText || el.value || '').trim().slice(0, 80) || null;
    return {
      tag: el.nodeName.toLowerCase(),
      css: cssPath(el),
      xpath: xpath(el),
      role: role,
      name: name,
      text: text,
      role_selector: role ? role + (name ? '[name=\"' + name + '\"]' : '') : null,
      bbox: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
    };
  }
  function emit(type, el, value){
    if (!window.__br_emit) return;
    try { window.__br_emit({type: type, target_node: nodeInfo(el), value: value, ts: Date.now()}); } catch(e){}
  }
  // 判定元素是否为"可交互元素"——点空白处（body/纯展示 div）不应被记为 click。
  // 取原生交互标签、显式 role、绑定了 onclick、或 CSS cursor:pointer 之一即可，
  // 并向上找最近交互祖先（点按钮内的 <svg>/<span> 时，target 是子节点，祖先是按钮）。
  // 判定单个节点是否"自身可交互"（不向上找祖先；祖先由 composedPath 负责遍历）。
  var INTERACTIVE = /^(A|BUTTON|INPUT|SELECT|TEXTAREA|LABEL|SUMMARY|DETAILS|OPTION|VIDEO|AUDIO)$/i;
  function isInteractiveSelf(node){
    if (!node || node.nodeType !== 1) return false;
    var tag = node.nodeName;
    if (INTERACTIVE.test(tag)) return true;
    if (node.getAttribute && node.getAttribute('role')) return true;
    if (node.getAttribute && node.getAttribute('onclick')) return true;
    if (node.isContentEditable) return true;
    try {
      var cur = window.getComputedStyle(node).cursor;
      if (cur === 'pointer' || cur === 'cell') return true;
    } catch(e) {}
    // B：显式 tabindex（可聚焦）→ 视为交互。捕获带 tabindex 的自定义控件
    // （弥补部分组件不设 role/cursor 的可访问性缺口）。
    if (node.hasAttribute && node.hasAttribute('tabindex')) return true;
    // A：自定义元素标签名以 -button/-link/-tab/-menuitem/-option/-switch 结尾 → 视为交互。
    // 平台中性：按命名约定识别自定义按钮/链接等（如 eo-button、el-button、general-button），
    // 这类组件常缺失 role/tabindex/cursor 却确实可点。
    if (/-(button|link|tab|menuitem|option|switch)$/.test(tag.toLowerCase())) return true;
    return false;
  }
  // 兼容旧名：向上找最近交互祖先（点按钮内 <svg>/<span> 时 target 是子节点）。
  function isInteractive(el){
    var node = el;
    for (var i = 0; node && node.nodeType === 1 && i < 4; i++){
      if (isInteractiveSelf(node)) return true;
      node = node.parentElement;
    }
    return false;
  }
  // 用 composedPath 取事件完整路径（**穿透 shadow DOM**），找路径里第一个自身可交互
  // 的节点作为 click 目标。这样 shadow 自定义元素（如 eo-launchpad-button-v2 把
  // <a role="button"> 放在 shadow 里）内部的可交互元素也能被记——否则事件在 shadow
  // 边界被重定向到宿主，宿主若无 role/cursor 会被当"点空白"丢弃。
  function pickInteractive(e){
    var path = (e.composedPath && e.composedPath()) || [e.target];
    // 先找「自身可交互 且 有真实盒子」的节点——跳过 <slot>/隐藏元素等 0 尺寸节点，
    // 保证标注位置有效（如 eo-button 的 shadow 里有继承 cursor 的 <slot>，0 尺寸）。
    for (var i = 0; i < path.length && i < 12; i++){
      var n = path[i];
      if (!isInteractiveSelf(n)) continue;
      try {
        var r = n.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) return n;
      } catch(e) {}
    }
    // 兜底：所有交互节点都 0 尺寸时，返回第一个交互节点（至少记下点击动作）
    for (var i = 0; i < path.length && i < 12; i++){
      if (isInteractiveSelf(path[i])) return path[i];
    }
    return null;
  }
  // 兜底：路径里无「自身可交互」节点时（点了纯空白/容器），取 composedPath 里最深的、
  // 有真实盒子的节点（用户实际点中的东西），让无效点击也留痕供后期清理。
  // composedPath 从深到浅，故首个有真实盒子的即最深者。
  function pickDeepestWithBox(e){
    var path = (e.composedPath && e.composedPath()) || [e.target];
    for (var i = 0; i < path.length && i < 12; i++){
      var n = path[i];
      if (!n || n.nodeType !== 1) continue;
      try {
        var r = n.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) return n;
      } catch(_) {}
    }
    return null;
  }
  var __br_mark_seq = 0;
  document.addEventListener('click', function(e){
    if (window.__br_evt_seen.has(e)) return; window.__br_evt_seen.add(e);
    // 优先：最小可点击元素（向上找首个自身可交互 + 真实盒子节点，bbox 最准）。
    var target = pickInteractive(e);
    if (!target && !window.__br_interactive_only){
      // 默认全捕：无可交互节点时兜底记「最深有盒节点」；
      // --interactive-only（window.__br_interactive_only）关闭此兜底，恢复「点空白丢弃」。
      target = pickDeepestWithBox(e);
    }
    if (!target) return;
    emit('click', target, null);
  }, true);
  // 仅 <select> 的 change 才记为 select；普通 <input> 的 change（含失焦校验）
  // 不应被误当成"选中值"，避免把用户名文本等当成 select 的 value（spec §5.1）。
  document.addEventListener('change', function(e){
    if (e.target && e.target.tagName === 'SELECT') emit('select', e.target, e.target.value);
  }, true);
  document.addEventListener('input', function(e){ if (window.__br_evt_seen.has(e)) return; window.__br_evt_seen.add(e); emit('input', e.target, e.target.value); }, true);
  // 失焦/切换元素时发 input_finalize，避免最后一段输入因始终未失焦而丢失
  // （spec §5.3.1：按"焦点切换/失焦/提交/超时"边界聚合为一条 input）
  function finalizeInput(e){
    var t = e.target;
    if (!t) return;
    if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable){
      emit('input_finalize', t, t.value || (t.innerText || ''));
    }
  }
  document.addEventListener('focusout', function(e){ finalizeInput(e); }, true);
  document.addEventListener('blur', function(e){ finalizeInput(e); }, true);
  // 表单提交：捕获 form 的 submit 事件本身（比靠 Enter 推断更准）。
  // 这样用户名框里按 Enter 触发登录提交时，记为一条 submit 动作，
  // 而 Enter 键本身不再单独 emit（避免登录页 Enter 误提交后录制中断）。
  document.addEventListener('submit', function(e){
    if (window.__br_evt_seen.has(e)) return; window.__br_evt_seen.add(e);
    var el = e.target || (document.activeElement && document.activeElement.closest ?
                          document.activeElement.closest('form') : null) || e.target;
    if (el) emit('submit', el, null);
  }, true);
  var scrollT = null;
  document.addEventListener('scroll', function(e){
    var t = e.target;
    if (scrollT) return;
    scrollT = setTimeout(function(){
      emit('scroll', t || document.body, null); scrollT = null;
    }, 200);
  }, true);
  // 结束录制：Ctrl/Cmd + Shift + X。按下即 flush 挂起输入并通知
  // Python 端结束主循环——替代"用户名框按 Enter 误提交"这类隐式结束，
  // 意图明确、不与业务页面的按键冲突。preventDefault 避免页面侧副作用。
  // 同时匹配 e.code === 'KeyX'（物理键，不受 macOS 下 Cmd 改变 e.key 的影响）。
  document.addEventListener('keydown', function(e){
    if ((e.ctrlKey || e.metaKey) && e.shiftKey &&
        (e.key === 'X' || e.key === 'x' || e.code === 'KeyX')){
      e.preventDefault();
      if (window.__br_flush){ try { window.__br_flush(); } catch(_){} }
      if (window.__br_stop){ try { window.__br_stop(); } catch(_){} }
    }
  }, true);
  // 页面卸载前调 __br_flush（由 Python 侧 expose_function 提供）触发挂起输入的 finalize
  window.addEventListener('beforeunload', function(){
    if (window.__br_flush){
      try { window.__br_flush(); } catch(e){}
    }
  });
})();
"""
