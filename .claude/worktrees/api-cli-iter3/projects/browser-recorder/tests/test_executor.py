# tests/test_executor.py
import asyncio
import pytest
from playwright.async_api import async_playwright
from browser_recorder.browser import launch
from browser_recorder.models import Action, Target
from browser_recorder.replay.delays import DelayResolver
from browser_recorder.replay.executor import ReplayExecutor
from browser_recorder.config import DEFAULT_REPLAY_POLICY


pytestmark = pytest.mark.asyncio


async def _new_page(context):
    return await context.new_page()


async def test_replay_click_navigates_and_succeeds(serve_demo_site, tmp_path):
    async with async_playwright() as pw:
        browser = await launch(pw)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(serve_demo_site + "/login.html")
        resolver = DelayResolver(DEFAULT_REPLAY_POLICY)
        ex = ReplayExecutor(page, resolver)
        actions = [
            Action(seq=1, ts=0, type="input", url=serve_demo_site + "/login.html",
                   target=Target(css="#username"), value="alice",
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
            Action(seq=2, ts=0, type="click", url=serve_demo_site + "/login.html",
                   target=Target(css="#login-btn"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
        ]
        stats = await ex.replay(actions)
        await page.wait_for_load_state("networkidle")
        assert "list.html" in page.url
        assert stats.succeeded >= 1
        await browser.close()


async def test_replay_failed_action_does_not_abort(serve_demo_site):
    async with async_playwright() as pw:
        browser = await launch(pw)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(serve_demo_site + "/list.html")
        resolver = DelayResolver(DEFAULT_REPLAY_POLICY)
        ex = ReplayExecutor(page, resolver)
        actions = [
            Action(seq=1, ts=0, type="click", url=serve_demo_site + "/list.html",
                   target=Target(css="#nonexistent"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
            Action(seq=2, ts=0, type="click", url=serve_demo_site + "/list.html",
                   target=Target(css="#search-btn"),
                   page_info={"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}),
        ]
        stats = await ex.replay(actions)
        assert stats.failed == 1
        assert stats.succeeded == 1
        await browser.close()
