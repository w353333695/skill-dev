"""inject.js 纯函数逻辑的 node 等价单测。

Task 5 实现 inject.js（CommonJS 头部导出 best_selector/trunc_text 等纯函数，
浏览器注入走 `typeof module` 判断的 IIFE 分支）；在此之前本文件整体 skip。
"""
import json
import pathlib
import shutil
import subprocess

import pytest

INJECT = pathlib.Path(__file__).parent.parent / "src" / "browser_recorder" / "inject.js"
node = shutil.which("node")

pytestmark = pytest.mark.skipif(
    node is None or not INJECT.exists() or INJECT.stat().st_size == 0,
    reason="node/inject.js 未就绪",
)


def _run_node(script: str) -> str:
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_descriptor_helpers():
    script = """
const m = require('%s');
// best_selector：有 id 用 #id；否则 tag.classes；文本截断 40
console.log(JSON.stringify([
  m.best_selector({tag:'button', id:'btn', classes:['a','b'], dom_path:'html>body>button'}),
  m.trunc_text('x'.repeat(80)),
]));
""" % INJECT
    sel, text = json.loads(_run_node(script))
    assert sel == "#btn"
    assert len(text) == 40


def test_install_survives_early_document():
    """回归：新文档极早期（documentElement 尚为 null）install 不得夭折。

    Page.addScriptToEvaluateOnNewDocument 的脚本在 documentElement 创建前运行，
    旧实现 observe(null) 抛 TypeError → MutationObserver 永远挂不上（动作
    监听器先注册所以还活着，症状是 dom_mutations 事件全丢、settle 只能靠
    网络空闲）。node 手搓最小 document 桩验证：install 全程不抛、监听器
    齐全、根元素出现后 observer 补挂、热键上报可用。
    """
    script = """
const m = require('%s');
const reports = [];
const listeners = {};
const fakeDoc = {
  documentElement: null,                      // 新文档极早期
  addEventListener: (t, cb) => { (listeners[t] = listeners[t] || []).push(cb); },
};
let observed = null;
global.MutationObserver = class {             // observe(null) 像真浏览器一样抛
  observe(t) { if (!t) throw new TypeError('observe null'); observed = t; }
  disconnect() {}
};
const win = { document: fakeDoc, __brEvent: (s) => reports.push(JSON.parse(s)) };
m.install(win);                               // 不得抛
setTimeout(() => {
  fakeDoc.documentElement = { tag: 'html' };  // 根元素出现
  setTimeout(() => {                          // 轮询周期 10ms，100ms 足够
    listeners.keydown.forEach(cb => cb({
      ctrlKey: true, shiftKey: true, key: 'F9', keyCode: 120,
      preventDefault() {}, stopPropagation() {},
    }));
    console.log(JSON.stringify({
      installed: !!win.__brInstalled,
      kinds: Object.keys(listeners).sort(),
      observed: !!observed,
      stop: reports.some(r => r.type === 'control_stop'),
    }));
    process.exit(0);
  }, 100);
}, 50);
""" % INJECT
    r = json.loads(_run_node(script))
    assert r["installed"]
    assert r["kinds"] == ["beforeunload", "change", "click", "input", "keydown", "submit"]
    assert r["observed"]          # 根元素可用后 MutationObserver 补挂
    assert r["stop"]              # install 全程跑完：热键上报可用
