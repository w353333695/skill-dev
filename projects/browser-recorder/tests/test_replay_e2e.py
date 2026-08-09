"""M1 端到端闭环：录制 demo 页 → doc.md → headless 回放全通过。

测试架构：单 playwright 连接自录自驱动（recorder.start/drain/finish 三段式）。
操作用 page.evaluate 在页面里 dispatch 真实 DOM 事件（input/change/click），
触发注入 JS 的监听器，走完整录制管线。

为什么不用 page.fill/click（trusted 输入）或第二连接：
- page.fill/click 内部的 auto-wait 与 binding 回调在单 greenlet 上互等，悬挂；
- 第二 CDP 客户端（线程/进程）与 recorder 共享浏览器时 dispatcher 调度竞争。
两者都是测试工程问题；生产环境是单客户端 headed 录制（人操作），不存在。
dispatchEvent 走同样的 JS 监听器，对录制管线的验证等价。
"""

from __future__ import annotations

import time

import pytest

from browser_recorder.models import read_requests, read_steps
from browser_recorder.recorder import Recorder
from browser_recorder.replayer import Replayer

pytestmark = pytest.mark.e2e

_DISPATCH_INPUTS = """() => {
  const set = (id, v) => {
    const el = document.getElementById(id);
    el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  set('username', 'alice');
  set('password', 's3cret');
  const r = document.getElementById('role');
  r.value = 'admin';
  r.dispatchEvent(new Event('change', {bubbles: true}));
}"""


def test_record_and_replay(tmp_path, demo_server):
    recorder = Recorder(url=demo_server.url, use_auth=False, output_root=str(tmp_path), headless=True)
    recorder.start()
    page = recorder.page

    page.evaluate(_DISPATCH_INPUTS)
    recorder.drain()
    page.evaluate("() => document.getElementById('submit-btn').click()")
    # click 触发 fetch + 导航；导航期间避免访问 page（CDP 调用会悬挂），直接等 + drain
    time.sleep(1.5)
    recorder.drain()

    session_dir = recorder.finish()

    # --- 录制产物断言 ---
    steps = read_steps(session_dir)
    types = [s.type for s in steps]
    assert types.count("input") >= 2, f"应至少有 2 步 input: {types}"
    assert "select" in types
    assert "click" in types

    password_step = next(s for s in steps if s.sensitive)
    assert password_step.value == "s3cret"

    username_step = next(s for s in steps if s.value == "alice")
    assert username_step.selectors.best(), "应有多路 selector 候选"

    requests = read_requests(session_dir)
    echo = [r for r in requests if "/api/echo" in r.url]
    assert echo, "requests.jsonl 应记录 /api/echo"
    assert echo[0].method == "POST"
    assert echo[0].status == 200

    doc = (session_dir / "doc.md").read_text(encoding="utf-8")
    assert "在【密码】输入 ***" in doc
    assert "s3cret" not in doc
    assert "点击【登录】" in doc
    assert "![步骤" in doc
    assert "附：关键请求" in doc and "/api/echo" in doc  # 请求附录

    # --- 回放断言 ---
    report = Replayer(session_dir).run()
    assert report["failed"] == 0, f"回放失败: {report['steps']}"
    assert report["passed"] == report["executed"]
    assert report["final_url"].endswith("/welcome")
