"""网络请求拦截 — page.route() 捕获 XHR/Fetch."""
from __future__ import annotations
import time
import fnmatch
from typing import Optional
from playwright.async_api import Page, Route
from .models import RequestRecord

DEFAULT_RECORD_TYPES = {"xhr", "fetch", "document"}
BODY_MAX_LENGTH = 10240  # 10KB 截断


def should_record(
    resource_type: str,
    url: str,
    filter_glob: Optional[str],
) -> bool:
    """判断请求是否应记录.

    Args:
        resource_type: 请求资源类型 (xhr/fetch/document/image/...)
        url: 请求 URL
        filter_glob: 自定义过滤 glob，提供时覆盖 resource_type 判断

    Returns:
        True 表示应记录
    """
    if filter_glob:
        # Match with full URL first (handles `https://...` patterns)
        if fnmatch.fnmatch(url, filter_glob):
            return True
        # Strip scheme and pad with '.' to match host-based patterns like `*.api.example.com/*`
        no_scheme = url.split("://", 1)[-1]
        return fnmatch.fnmatch(f".{no_scheme}", filter_glob)
    return resource_type in DEFAULT_RECORD_TYPES


class NetworkInterceptor:
    """网络请求拦截器."""

    def __init__(self, filter_glob: Optional[str] = None) -> None:
        self._filter_glob = filter_glob
        self.requests: list[RequestRecord] = []

    async def setup(self, page: Page) -> None:
        """在 page 上挂载 route 拦截."""
        await page.route("**/*", self._handle_route)

    async def teardown(self, page: Page) -> None:
        """移除 route 拦截."""
        try:
            await page.unroute("**/*", self._handle_route)
        except Exception:
            pass

    async def _handle_route(self, route: Route) -> None:
        """处理单个请求. 文档请求直接放行，不拦截导航重定向."""
        request = route.request

        # 文档导航（主页面/iframe）不拦截，让浏览器原生处理重定向
        if request.resource_type == "document":
            await route.continue_()
            return

        start_time = time.time() * 1000

        try:
            response = await route.fetch()
        except Exception:
            await route.continue_()
            return

        end_time = time.time() * 1000
        duration_ms = end_time - start_time

        if should_record(request.resource_type, request.url, self._filter_glob):
            record = RequestRecord(
                timestamp_ms=start_time,
                method=request.method,
                url=request.url,
                status=response.status,
                duration_ms=round(duration_ms, 1),
                resource_type=request.resource_type,
                req_headers=dict(request.headers),
                res_headers=dict(response.headers),
                req_body=self._truncate_body(request.post_data_buffer),
                res_body=self._truncate_body(await response.body()),
            )
            self.requests.append(record)

        await route.fulfill(response=response)

    @staticmethod
    def _truncate_body(body: Optional[bytes]) -> Optional[str]:
        if body is None:
            return None
        text = body.decode("utf-8", errors="replace")
        if len(text) > BODY_MAX_LENGTH:
            return text[:BODY_MAX_LENGTH] + "…[truncated]"
        return text
