"""e2e fixtures：demo http server + CDP chromium。"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from browser_recorder.demo_page import DemoServer

CHROMIUM_CACHE = Path.home() / ".cache" / "ms-playwright"


def _chromium_binary() -> Path:
    patterns = [
        "chromium-*/chrome-linux*/chrome",
        "chromium-*/chrome-linux*/chrome-headless-shell",
        "chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell",
    ]
    for pattern in patterns:
        candidates = sorted(CHROMIUM_CACHE.glob(pattern))
        if candidates:
            return candidates[-1]
    pytest.skip("未找到 chromium 缓存")


@pytest.fixture(scope="session")
def demo_server():
    with DemoServer() as server:
        yield server


@pytest.fixture(scope="session")
def cdp_browser():
    """起一个带 --remote-debugging-port 的 headless chromium，返回 http CDP endpoint。

    chromium 以 about:blank 启动时会自动创建 default context，
    保证 connect_over_cdp 后有可 attach 的 context。
    """
    """起一个带 --remote-debugging-port 的 headless chromium，返回 http CDP endpoint。"""
    binary = _chromium_binary()
    args = [str(binary), "--remote-debugging-port=0", "--no-sandbox", "--disable-gpu", "about:blank"]
    if "headless-shell" not in binary.name:
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    endpoint = None
    deadline = time.monotonic() + 15
    # "DevTools listening on ws://..." 打在 stderr
    while time.monotonic() < deadline:
        line = proc.stderr.readline()
        m = re.search(r"DevTools listening on (ws://\S+)", line)
        if m:
            ws = m.group(1)
            host_port = ws.split("//")[1].split("/")[0]
            endpoint = f"http://{host_port}"
            break
    if endpoint is None:
        proc.kill()
        pytest.fail("chromium CDP 端口未就绪")

    yield endpoint

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
