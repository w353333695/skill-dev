# tests/test_popup.py
"""弹窗/新标签页（target=_blank）内的动作应被捕获：__br_emit 走 ctx.expose_binding
（context 级，popup 继承），而非 page.expose_function（page 级，popup 不继承 → 丢失）。
"""
import json


def test_popup_action_captured(tmp_path):
    from browser_recorder.record import runner
    from browser_recorder import paths

    saved = paths.TMP_ROOT
    paths.TMP_ROOT = tmp_path / "tmp"
    try:
        (tmp_path / "index.html").write_text(
            '<html><body><a id="open" href="p.html" target="_blank">开</a></body></html>',
            encoding="utf-8")
        # popup 页加载后自行 click，触发 injector emit（验证 popup 继承 __br_emit）
        (tmp_path / "p.html").write_text(
            '<html><body><button id="act">x</button>'
            '<script>setTimeout(()=>document.getElementById("act").click(),300);</script>'
            '</body></html>', encoding="utf-8")
        sd = runner.run_record(
            url=f"file://{tmp_path / 'index.html'}",
            out_dir=tmp_path / ".br", profile=None, keep_auth=False,
            screenshot_policy_path=None, video=False, name="pop", headless=True,
            auto_actions=[("click", "#open")])
        trace = [json.loads(l) for l in (sd / "trace.jsonl").read_text(encoding="utf-8").splitlines() if l.strip]
        click_urls = [a.get("url", "") for a in trace if a.get("type") == "click"]
        assert any("p.html" in u for u in click_urls), f"popup 内动作未捕获: {click_urls}"
    finally:
        paths.TMP_ROOT = saved
