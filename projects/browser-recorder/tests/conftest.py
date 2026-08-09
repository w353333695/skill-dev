"""测试配置 — 本地 HTTP server + Playwright browser."""
import socket
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import pytest
from playwright.async_api import async_playwright


def _find_free_port() -> int:
    """找到可用端口."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def fixtures_dir():
    """fixture HTML 目录."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def http_server(fixtures_dir):
    """启动本地 HTTP server 托管 fixture HTML."""

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(fixtures_dir), **kwargs)

        def log_message(self, format, *args):
            pass  # 抑制日志

    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # 等待启动
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
async def browser():
    """创建 Playwright browser（headless）."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser):
    """创建新页面."""
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()
