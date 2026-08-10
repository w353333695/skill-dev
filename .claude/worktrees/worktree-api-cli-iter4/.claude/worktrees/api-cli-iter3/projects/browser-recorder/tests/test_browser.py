# tests/test_browser.py
"""browser.py 的默认上下文配置：locale/viewport/证书策略（mock，不起真浏览器）。"""
import asyncio
from browser_recorder.browser import new_context


class FakeBrowser:
    def __init__(self):
        self.kwargs = None

    async def new_context(self, **kwargs):
        self.kwargs = kwargs
        return self


def test_new_context_defaults():
    b = FakeBrowser()
    asyncio.run(new_context(b))
    assert b.kwargs["locale"] == "zh-CN"                         # 默认中文
    assert b.kwargs["viewport"] == {"width": 1280, "height": 720}
    assert b.kwargs["ignore_https_errors"] is False             # 安全默认


def test_new_context_locale_overridable():
    b = FakeBrowser()
    asyncio.run(new_context(b, locale="en-US"))
    assert b.kwargs["locale"] == "en-US"


def test_new_context_insecure_opt_in():
    b = FakeBrowser()
    asyncio.run(new_context(b, ignore_https_errors=True))
    assert b.kwargs["ignore_https_errors"] is True
