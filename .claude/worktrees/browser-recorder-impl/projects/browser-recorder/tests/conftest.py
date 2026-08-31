"""共享 fixture：本地静态站 + 真浏览器可用性探测。"""
import http.server
import os
import pathlib
import socket
import threading
from functools import partial

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "site"
DEFAULT_CHROME = (pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # 静音，避免污染 pytest 输出
        pass


@pytest.fixture
def local_site():
    """http.server serve fixtures/site，yield base_url。"""
    port = _free_port()
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), partial(_QuietHandler, directory=str(FIXTURES))
    )
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def chrome_path() -> pathlib.Path:
    p = pathlib.Path(os.environ.get("BR_CHROME", str(DEFAULT_CHROME)))
    if not p.exists():
        pytest.skip(f"chrome not found: {p}")
    return p
