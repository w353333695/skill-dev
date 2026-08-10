# tests/conftest.py
import pytest


@pytest.fixture
def tmp_out_dir(tmp_path):
    """默认 out-dir 根目录（隔离测试，不污染真实 ./.browser-recorder）。"""
    d = tmp_path / ".browser-recorder"
    d.mkdir()
    return d


import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


@pytest.fixture
def demo_site_dir():
    return Path(__file__).parent / "fixtures" / "demo_site"


@pytest.fixture
def serve_demo_site(demo_site_dir):
    """起一个本地静态服务器serve demo_site，返回 base_url。集成测试用。"""
    import os

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(demo_site_dir), **kw)
        def log_message(self, *a, **kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture
def serve_self_signed_https(tmp_path, demo_site_dir):
    """起一个自签证书的 HTTPS 静态服务器（serve demo_site），返回 base_url。

    用于验证 ``--insecure`` 能跳过 ERR_CERT_AUTHORITY_INVALID。证书用 openssl
    现场生成（CN=localhost），测完随 tmp_path 清理。
    """
    import ssl
    import subprocess

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048",
         "-keyout", str(key), "-out", str(cert),
         "-days", "1", "-nodes", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(demo_site_dir), **kw)
        def log_message(self, *a, **kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)
