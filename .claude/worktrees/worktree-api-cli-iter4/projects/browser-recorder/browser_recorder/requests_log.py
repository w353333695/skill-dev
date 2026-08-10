"""请求记录：所有 fetch/XHR（过滤静态资源），按步骤序号关联。

架构：page.on("request"/"response"/"requestfailed") 事件驱动，事件回调（CDP 线程）
只做纯内存记录（方法/url/状态/资源类型），headers/post_data/response_body 这类
需要同步 CDP 调用的字段，统一在 drain()（连接线程、页面稳定时）补读。

为什么不在事件回调里读 body：response.body() / request.post_data / request.headers
都是同步 CDP 调用，在 CDP 事件线程（回调里）执行会悬挂或饿死后续事件派发——
M1 调试反复踩中的坑。为什么不用 context.route 拦截记 body：route.fulfill 重建
响应会丢/乱原始 header（content-encoding/set-cookie），实测破坏 easyops SPA 加载
与登录；route.continue_ 导致请求双发（写操作重复提交，不可接受）。事件监听不动
响应流，对页面零侵入，字段后置补读是唯一兼顾"不破坏页面 + 能拿到 body"的方案。
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
    """挂到 page 的 request/response 事件，写 requests.jsonl。

    get_step_seq: 返回当前最新步骤序号的回调，用于步骤关联。
    """

    def __init__(self, session_dir: Path, get_step_seq):
        self._path = Path(session_dir) / "requests.jsonl"
        self._get_step_seq = get_step_seq
        self._seq = 0
        self._events: list[tuple] = []  # (response|None, RequestEvent, failed)
        self._by_request: dict = {}  # request -> RequestEvent（匹配 response）
        self._written = False

    def attach(self, page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)

    def attach_context(self, context) -> None:
        for pg in context.pages:
            self.attach(pg)
        context.on("page", self.attach)

    # ---------- 事件（CDP 线程，纯内存，禁止同步 CDP 调用） ----------

    def _on_request(self, request) -> None:
        try:
            if request.resource_type in _SKIP_TYPES:
                return
            if request.resource_type == "document" and not request.is_navigation_request():
                return
            self._seq += 1
            event = RequestEvent(
                seq=self._seq,
                step_seq=self._get_step_seq(),
                method=request.method,
                url=request.url,
                resource_type=request.resource_type,
            )
            self._by_request[request] = event
            self._events.append((None, event, False))  # response 占位后补
        except Exception:
            pass

    def _on_response(self, response) -> None:
        event = self._by_request.pop(response.request, None)
        if event is None:
            return
        try:
            event.status = response.status  # 本地缓存属性，安全
        except Exception:
            pass
        # 把 response 对象存进 events，供 drain 补读 body
        for i, (r, e, f) in enumerate(self._events):
            if e is event:
                self._events[i] = (response, event, False)
                break

    def _on_failed(self, request) -> None:
        event = self._by_request.pop(request, None)
        if event is not None:
            event.response_body = "[failed]"
            for i, (r, e, f) in enumerate(self._events):
                if e is event:
                    self._events[i] = (None, event, True)
                    break

    # ---------- drain / finish（连接线程，可做同步 CDP 调用） ----------

    def drain(self) -> None:
        """补读各响应的 headers/post_data/body（幂等，读过的跳过）。

        body 的 CDP 调用在导航后可能悬挂（不抛异常），用 watchdog 线程强制超时放弃——
        注意子线程不能真的执行 CDP 调用（greenlet 线程锁），所以这里是在连接线程直接调，
        依赖 playwright 对已完成响应的 body 缓存：有缓存秒回，无缓存的 CDP 调用若悬挂，
        由调用方保证不在导航后立即 drain（录制主循环每 0.3s drain 时响应新鲜、页面未导航）。
        """
        for response, event, failed in self._events:
            if failed or response is None or event.response_body is not None:
                continue
            try:
                req = response.request
                if not event.request_headers:
                    event.request_headers = {k: v for k, v in req.headers.items() if k.lower() in _HEADER_ALLOWLIST}
                if event.post_data is None:
                    event.post_data = self._truncate(req.post_data)
                body, truncated = self._read_body(response)
                if body is not None:
                    event.response_body = body
                    event.truncated = truncated
            except Exception:
                continue

    def close(self) -> None:
        """全量写盘（body 由录制期 drain 补读；close 不再补读，避免页面关闭后 CDP 悬挂/报错）。"""
        if self._written:
            return
        lines = [event.dumps() for _, event, _ in self._events]
        self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self._written = True

    # ---------- 内部 ----------

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
