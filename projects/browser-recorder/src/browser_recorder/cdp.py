"""裸 CDP 客户端：ws 连接，命令收发 + 事件订阅（支持 CDP 扁平会话路由）。

用法：
    client = await CDPClient.connect(port)          # 真浏览器 page target
    client = await CDPClient.connect_browser(port)  # browser-level（多 tab 用）
    client = await CDPClient.connect(0, ws_url=...)  # 测试直连 ws
    client.on("Network.requestWillBeSent", cb)       # 具名事件：cb(params: dict) 单参
    client.on("*", cb)                               # 全部事件：cb(method, params) 两参
    r = await client.send("Page.navigate", {"url": ...})
    r = await client.send("Page.navigate", {...}, session_id=sid)  # 定向子会话

会话语义（flatten 模式）：带 session_id 的 on() 只收该 session 的事件（cb(params) 单参，
与具名事件一致——session 订阅者已知自己属于哪个 tab，无需回传 method）；
未指定 session_id 的订阅收所有会话的事件（含无 session 的 browser 级事件）。
session 订阅不参与 "*" 两参广播（"*" 始终是全局的）。

注：不支持 "Network.*" 之类前缀通配，只认精确事件名或 "*"。
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
        self._handlers: dict[str, list] = {}          # 事件名 -> [(session_id|None, cb)]
        self._reader: asyncio.Task | None = None
        self.closed = False

    # ---- 连接 ----
    @classmethod
    async def connect(cls, port: int, host: str = "127.0.0.1", ws_url: str | None = None):
        if ws_url is None:
            ws_url = cls._page_ws_url(host, port)
        return await cls._from_ws_url(ws_url)

    @classmethod
    async def connect_browser(cls, port: int, host: str = "127.0.0.1"):
        """browser-level ws：能收 Target.* 生命周期、可承载 flatten 子会话。"""
        with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=5) as r:
            ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
        return await cls._from_ws_url(ws_url)

    @classmethod
    async def _from_ws_url(cls, ws_url: str):
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
    def on(self, event: str, callback, session_id: str | None = None) -> None:
        """订阅事件。session_id 非 None 时仅收该 flatten 子会话的事件（单参 cb）。"""
        self._handlers.setdefault(event, []).append((session_id, callback))

    def _dispatch(self, method: str, params: dict, session_id: str | None = None) -> None:
        # flatten 模式下事件都带 sessionId 路由。两层语义：
        #  - session 订阅（sid 非 None）：只收自己会话的事件，单参 cb
        #  - 全局订阅（sid None）：收所有事件（含 Target.* 生命周期——它们也带
        #    归属 session，但 target 生命周期本身是 browser 级关注点）
        for sid, cb in self._handlers.get(method, []):
            if sid is not None and sid != session_id:
                continue
            try:
                cb(params)
            except Exception:
                log.exception("handler error on %s", method)
        if session_id is None:
            # 全局 "*" 订阅只广播 browser 级无 session 事件，避免多 tab 时重复扇出
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
                    self._dispatch(msg.get("method", ""), msg.get("params", {}),
                                   msg.get("sessionId"))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.closed = True
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()

    # ---- 命令 ----
    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0,
                   session_id: str | None = None) -> dict:
        mid = next(self._id)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        msg: dict = {"id": mid, "method": method, "params": params or {}}
        if session_id is not None:
            msg["sessionId"] = session_id
        await self._ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def wait_closed(self) -> None:
        if self._reader:
            await self._reader

    async def close(self) -> None:
        await self._ws.close()
        if self._reader:
            await self._reader
