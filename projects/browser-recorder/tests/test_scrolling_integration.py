# tests/test_scrolling_integration.py
"""scrolling-snapshot 集成验证：click 触发导航时，before 应抓【点击前】画面
（index.html，非纯白屏），而非导航后的 login.html 或白屏。

用 demo_site 的导航链接（index.html → login.html）。auto_actions 脚本 click 与
真人 click 对 scrolling 无本质区别（都触发 DOM click 事件，scrolling 后台取 emit 前帧）。
"""
import json


def _non_white_count(path) -> int:
    """采样统计非白像素点数（>240 视为白）。纯白屏=0；有文字内容>0。"""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            p = px[x, y]
            if not (p[0] > 240 and p[1] > 240 and p[2] > 240):
                n += 1
    return n


def test_scrolling_before_is_pre_click_not_blank(
        serve_demo_site, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from browser_recorder.record import runner as rec_runner
    session_dir = rec_runner.run_record(
        url=serve_demo_site + "/index.html",
        out_dir=tmp_path / ".browser-recorder",
        profile=None, keep_auth=False,
        screenshot_policy_path=None, video=False, name="scroll",
        headless=True,
        auto_actions=[("click", "a")],   # index.html 的"去登录"链接 → 导航 login.html
    )
    trace = [json.loads(l) for l in (session_dir / "trace.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()]
    clicks = [a for a in trace if a.get("type") == "click"]
    assert clicks, "auto_actions 点击未捕获"
    shot = clicks[0].get("screenshot") or {}
    assert shot.get("before"), "click 应有 before（scrolling-snapshot 提供点击前帧）"

    before = session_dir / "screenshots" / shot["before"]
    nwc = _non_white_count(before)
    # before 含文字内容（index.html 的 "Demo Site"），非纯白屏（白屏=0）。
    # 对比：旧 click-before 的导航 before 是 100% 白（0 非白点）。
    assert nwc > 5, (
        f"before 是纯白屏（非白采样点仅 {nwc}），scrolling 没抓到点击前内容；shot={shot}")
