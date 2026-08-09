"""JS 注入器 — 浏览器端事件捕获脚本."""
from __future__ import annotations

import json
from typing import Callable, Awaitable
from playwright.async_api import Page

# JS 注入脚本：监听所有 DOM 交互事件，缓冲批量 push 到 Python
RECORDER_JS = r"""
(function() {
    if (window.__recorder_injected__) return;
    window.__recorder_injected__ = true;

    const BATCH_SIZE = 10;
    const FLUSH_INTERVAL_MS = 50;
    let buffer = [];
    let flushTimer = null;

    function getSelector(target, evt) {
        try {
            const path = evt && evt.composedPath ? evt.composedPath() : [];
            for (const el of path) {
                if (el.nodeType !== 1) continue;
                if (el.id) return '#' + CSS.escape(el.id);
            }
            // fallback: build path from target
            const parts = [];
            let el = target;
            while (el && el.nodeType === 1) {
                let seg = el.tagName.toLowerCase();
                if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
                if (el.className && typeof el.className === 'string') {
                    const cls = el.className.trim().split(/\s+/)[0];
                    if (cls) seg += '.' + CSS.escape(cls);
                }
                parts.unshift(seg);
                el = el.parentElement;
            }
            return parts.join(' > ');
        } catch(e) {
            return '';
        }
    }

    function getText(target) {
        try {
            const t = (target.textContent || '').trim();
            return t.substring(0, 100);
        } catch(e) { return ''; }
    }

    function getCoords(event) {
        if (event.clientX !== undefined) {
            return {x: Math.round(event.clientX), y: Math.round(event.clientY)};
        }
        return null;
    }

    function push(type, event, value) {
        const target = event.target;
        if (!target) return;
        const record = {
            type: type,
            timestamp: Date.now(),
            selector: getSelector(target, event),
            value: value || null,
            tagName: target.tagName ? target.tagName.toLowerCase() : '',
            text: getText(target),
            coords: getCoords(event),
            url: location.href,
            pageId: window.__recorder_page_id__ || 'main',
            frameId: null
        };
        buffer.push(record);
        if (buffer.length >= BATCH_SIZE) {
            doFlush();
        } else if (!flushTimer) {
            flushTimer = setTimeout(doFlush, FLUSH_INTERVAL_MS);
        }
    }

    function doFlush() {
        if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
        if (buffer.length === 0) return;
        const batch = buffer;
        buffer = [];
        if (window.__recorder_push__) {
            try {
                window.__recorder_push__(JSON.stringify(batch));
            } catch(e) { console.error('[recorder] push error:', e); }
        }
    }

    // click 监听
    document.addEventListener('click', function(e) {
        push('CLICK', e, null);
    }, true);

    // input 监听
    document.addEventListener('input', function(e) {
        const el = e.target;
        const value = (el && (el.value !== undefined)) ? el.value : null;
        push('INPUT', e, value);
    }, true);

    // change 监听
    document.addEventListener('change', function(e) {
        const el = e.target;
        const value = (el && (el.value !== undefined)) ? el.value : null;
        push('CHANGE', e, value);
    }, true);

    // submit 监听
    document.addEventListener('submit', function(e) {
        push('SUBMIT', e, null);
    }, true);

    // scroll 监听 (debounced)
    let scrollDebounce = null;
    document.addEventListener('scroll', function(e) {
        if (scrollDebounce) return;
        scrollDebounce = setTimeout(function() {
            scrollDebounce = null;
            push('SCROLL', e, null);
        }, 300);
    }, true);

    // SPA 路由变化
    window.addEventListener('popstate', function(e) {
        doFlush();
        push('NAV', e, location.href);
    });
    window.addEventListener('hashchange', function(e) {
        doFlush();
        push('NAV', e, location.href);
    });

    // 页面卸载前 flush
    window.addEventListener('beforeunload', function() {
        doFlush();
    });

    // MutationObserver — DOM 稳定检测（供外部查询）
    window.__recorder_mutation_count__ = 0;
    window.__recorder_mutation_timer__ = null;
    const observer = new MutationObserver(function(mutations) {
        window.__recorder_mutation_count__ += mutations.length;
        if (window.__recorder_mutation_timer__) {
            clearTimeout(window.__recorder_mutation_timer__);
        }
        window.__recorder_mutation_timer__ = setTimeout(function() {
            window.__recorder_stable__ = true;
        }, 300);
    });
    observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true, characterData: true
    });

    // 对外 API
    window.__recorder_flush__ = doFlush;
    window.__recorder_stable__ = false;
})();
"""


async def inject(page: Page, page_id: str = "main") -> None:
    """注入录制脚本到页面."""
    await page.evaluate(f"window.__recorder_page_id__ = {json.dumps(page_id)};")
    await page.evaluate(RECORDER_JS)


async def setup_recorder_callback(
    page: Page,
    callback: Callable[[str], Awaitable[None]],
) -> None:
    """暴露 __recorder_push__ 回调给 JS."""
    await page.expose_function("__recorder_push__", callback)


async def flush(page: Page) -> None:
    """强制 flush JS 侧缓冲区."""
    try:
        await page.evaluate("if(window.__recorder_flush__) window.__recorder_flush__()")
    except Exception:
        pass  # 页面可能已关闭


async def wait_dom_stable(page: Page, timeout_ms: int = 5000) -> bool:
    """等待 DOM 稳定（MutationObserver 300ms 无变化）."""
    try:
        await page.evaluate("window.__recorder_stable__ = false;")
        await page.wait_for_function(
            "window.__recorder_stable__ === true",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False
