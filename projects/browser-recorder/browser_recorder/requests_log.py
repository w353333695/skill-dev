"""请求记录：所有 fetch/XHR（过滤静态资源），按步骤序号关联。

架构：用 context.route 拦截所有请求。route handler 里 route.fetch() 拿到
真实响应（含 body），记录后 route.fulfill() 回给页面。这是 playwright 记录
response body 的可靠方式——body 在拦截时就在手，不像 page.on("response")
事后用 response.body() 的 CDP 调用在导航后会悬挂。

route handler 运行在 CDP 事件线程，但其中 route.fetch() 是 handler 生命周期内
允许的操作（playwright 设计如此）。记录是纯内存 + 文件写，无额外线程。
"""

from __future__ import annotations

from pathlib import Path

from .models import RequestEvent

# 不记录的资源类型（静态资源/媒体/websocket 等）
_SKIP_TYPES = {"script", "stylesheet", "image", "font", "media", "manifest", "websocket", "other"}
# 只记录这些请求头（cookie/authorization 等敏感头不录）
_HEADER_ALLOWLIST = {"content-type", "accept", "x-requested-with"}
# 只读这些 content-type 的响应体
_BODY_TYPES = ("json", "text", "xml", "html", "javascript")

MAX_BODY = 64 * 1024


class RequestLogger:
    """经 context.route 拦截记录请求，写 requests.jsonl。

    get_step_seq: 返回当前最新步骤序号的回调，用于步骤关联。
    """

    def __init__(self, session_dir: Path, get_step_seq):
        self._path = Path(session_dir) / "requests.jsonl"
        self._get_step_seq = get_step_seq
        self._seq = 0
        self._fp = open(self._path, "a", encoding="utf-8")

    def attach_context(self, context) -> None:
        context.route("**/*", self._handle)

    def attach(self, page) -> None:  # 兼容旧接口，route 在 context 级
        pass

    def close(self) -> None:
        self._fp.close()

    # ---------- route handler（CDP 事件线程） ----------

    def _handle(self, route) -> None:
        request = route.request
        if request.resource_type in _SKIP_TYPES:
            route.continue_()
            return

        try:
            response = route.fetch()
        except Exception:
            route.continue_()
            return

        # 记录
        try:
            self._seq += 1
            event = RequestEvent(
                seq=self._seq,
                step_seq=self._get_step_seq(),
                method=request.method,
                url=request.url,
                resource_type=request.resource_type,
                status=response.status,
                request_headers={k: v for k, v in request.headers.items() if k.lower() in _HEADER_ALLOWLIST},
                post_data=self._truncate(request.post_data),
            )
            event.response_body, event.truncated = self._read_body(response)
            self._write(event)
        except Exception:
            pass

        # 回给页面
        try:
            route.fulfill(response=response)
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    def _read_body(self, response) -> tuple[str | None, bool]:
        try:
            content_type = response.headers.get("content-type", "")
            if not any(t in content_type for t in _BODY_TYPES):
                return None, False
            body = response.body()
            text = body.decode("utf-8", errors="replace")
            if len(text) > MAX_BODY:
                return text[:MAX_BODY], True
            return text, False
        except Exception:
            return None, False

    @staticmethod
    def _truncate(text: str | None) -> str | None:
        if text and len(text) > MAX_BODY:
            return text[:MAX_BODY]
        return text

    def _write(self, event: RequestEvent) -> None:
        self._fp.write(event.dumps() + "\n")
        self._fp.flush()
