"""裸 CDP 客户端：单 ws 连接，命令收发 + 事件订阅。

用法：
    client = await CDPClient.connect(port)          # 真浏览器
    client = await CDPClient.connect(0, ws_url=...)  # 测试直连 ws
    client.on("Network.*", cb)                       # cb(params: dict) 同步
    r = await client.send("Page.navigate", {"url": ...})
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import urllib.request

import websockets

log = logging.getLogger(__name__)


class CDPError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"CDP error {code}: {message}")
        self.code = code
        self.message = message


class CDPClient:
    def __init__(self, ws):
        self._ws = ws
        self._id = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list] = []  # 占位，下一行真正初始化
        self._handlers = {}
        self._reader: asyncio.Task | None = None
        self.closed = False

    # ---- 连接 ----
    @classmethod
    async def connect(cls, port: int, host: str = "127.0.0.1", ws_url: str | None = None):
        if ws_url is None:
            ws_url = cls._page_ws_url(host, port)
        ws = await websockets.connect(ws_url, max_size=256 * 1024 * 1024)
        self = cls(ws)
        self._reader = asyncio.create_task(self._pump())
        return self

    @staticmethod
    def _page_ws_url(host: str, port: int) -> str:
        with urllib.request.urlopen(f"http://{host}:{port}/json/list", timeout=5) as r:
            targets = json.loads(r.read())
        for t in targets:
            if t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
        raise CDPError(-1, f"no page target on {host}:{port}")

    # ---- 事件 ----
    def on(self, event: str, callback) -> None:
        self._handlers.setdefault(event, []).append(callback)

    def _dispatch(self, method: str, params: dict) -> None:
        for cb in self._handlers.get(method, []):
            try:
                cb(params)
            except Exception:
                log.exception("handler error on %s", method)
        for cb in self._handlers.get("*", []):
            try:
                cb(method, params)
            except Exception:
                log.exception("handler error on *")

    async def _pump(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(
                                CDPError(msg["error"]["code"], msg["error"].get("message", "")))
                        else:
                            fut.set_result(msg.get("result", {}))
                else:
                    self._dispatch(msg.get("method", ""), msg.get("params", {}))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.closed = True
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()

    # ---- 命令 ----
    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        mid = next(self._id)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout)

    async def wait_closed(self) -> None:
        if self._reader:
            await self._reader

    async def close(self) -> None:
        await self._ws.close()
        if self._reader:
            await self._reader
