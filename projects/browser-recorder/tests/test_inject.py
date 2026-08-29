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
