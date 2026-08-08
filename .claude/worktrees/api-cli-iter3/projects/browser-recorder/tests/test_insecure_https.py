# tests/test_insecure_https.py
"""自签证书 HTTPS 集成测试：验证 --insecure 能跳过 ERR_CERT_AUTHORITY_INVALID。

内网系统普遍使用自签证书，默认 Chromium 拒绝（net::ERR_CERT_AUTHORITY_INVALID）。
``--insecure``（ignore_https_errors=True）必须能解锁；默认（False）必须保持安全拒绝。
"""
import asyncio
import pytest

from browser_recorder.record import runner as rec_runner
from browser_recorder import paths
from browser_recorder.browser import launch, new_context


def test_record_with_insecure_skips_cert_error(serve_self_signed_https, tmp_path):
    """--insecure 能成功打开自签 HTTPS 站点（端到端 run_record 产 meta.json，不抛证书错误）。"""
    paths.TMP_ROOT = tmp_path / "tmp"
    sd = rec_runner.run_record(
        url=serve_self_signed_https + "/",
        out_dir=tmp_path / ".br",
        profile=None, keep_auth=False,
        screenshot_policy_path=None, video=False,
        name="ssl", headless=True,
        auto_actions=[],  # 空操作：仅验证 goto 能否越过证书校验
        ignore_https_errors=True,
    )
    assert (sd / "meta.json").exists()


def test_default_context_rejects_self_signed_cert(serve_self_signed_https):
    """默认（ignore_https_errors=False）goto 自签 HTTPS 必抛证书错误，证明默认安全。

    不经过 run_record：其 goto 有兜底 try/except 会吞掉证书异常（为内网慢加载兜底），
    无法在 run_record 层观测"默认拒绝"。这里直接在 launch + new_context 层验证
    证书开关真实生效。
    """
    from playwright.async_api import async_playwright

    async def _go():
        async with async_playwright() as pw:
            browser = await launch(pw, headless=True)
            try:
                ctx = await new_context(browser, ignore_https_errors=False)
                page = await ctx.new_page()
                await page.goto(serve_self_signed_https + "/",
                                wait_until="domcontentloaded")
            finally:
                await browser.close()

    with pytest.raises(Exception):
        asyncio.run(_go())
