"""内置 demo 测试页：login 表单（用户名/密码/下拉/提交）→ fetch /api/echo → 跳 /welcome。

供 doctor 自检与 e2e 测试使用：本机无 UI 时，用它 + CDP 模式完成录制验证。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>demo login</title></head>
<body>
  <h1>Demo 登录</h1>
  <form id="login-form">
    <label for="username">用户名</label>
    <input id="username" name="username" data-testid="username-input" type="text">
    <label for="password">密码</label>
    <input id="password" name="password" type="password">
    <label for="role">角色</label>
    <select id="role" name="role">
      <option value="viewer">访客</option>
      <option value="admin">管理员</option>
    </select>
    <button id="submit-btn" data-testid="submit" type="submit">登录</button>
  </form>
  <script>
    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      await fetch("/api/echo", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          username: document.getElementById("username").value,
          role: document.getElementById("role").value,
        }),
      });
      location.href = "/welcome";
    });
  </script>
</body>
</html>
"""

WELCOME_HTML = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>welcome</title></head>
<body><h1 id="welcome-title">欢迎回来</h1></body>
</html>
"""

SPA_HTML = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>spa</title></head>
<body>
  <h1>SPA 页</h1>
  <button id="tab-a" data-testid="tab-a">标签A</button>
  <button id="tab-b" data-testid="tab-b">标签B</button>
  <div id="content">当前: A</div>
  <script>
    document.getElementById("tab-a").addEventListener("click", () => {
      history.pushState({}, "", "/spa#a");
      document.getElementById("content").textContent = "当前: A";
    });
    document.getElementById("tab-b").addEventListener("click", () => {
      history.pushState({}, "", "/spa#b");
      document.getElementById("content").textContent = "当前: B";
    });
  </script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/welcome":
            self._send(WELCOME_HTML)
        elif self.path.startswith("/spa"):
            self._send(SPA_HTML)
        else:
            self._send(LOGIN_HTML)

    def do_POST(self) -> None:
        if self.path == "/api/echo":
            length = int(self.headers.get("content-length", 0))
            body = self.rfile.read(length)
            self._send(json.dumps({"echo": json.loads(body or b"{}")}), "application/json")
        else:
            self.send_error(404)

    def _send(self, body: str, content_type: str = "text/html") -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", f"{content_type}; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静默
        pass


class DemoServer:
    """localhost demo 页服务，with 语句或 start/stop 使用。"""

    def __init__(self, port: int = 0):
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> DemoServer:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> DemoServer:
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()


if __name__ == "__main__":
    server = DemoServer().start()
    print(f"demo page: {server.url}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()
