"""cdp.py 单测：mock ws 端点模拟 CDP 协议收发。

注：brief 原版测试用 pytest.mark.asyncio，但项目依赖里没有 pytest-asyncio
（不为测试新增依赖），故改为 asyncio.run 包装的同步测试风格，断言逻辑不变。
"""
import asyncio
import json

import pytest
import websockets

from browser_recorder.cdp import CDPClient, CDPError


async def _mock_cdp(ws):
    """模拟 page target ws：回命令结果 + 主动推一个事件。"""
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("id") is not None:
            if msg["method"] == "Runtime.evaluate":
                await ws.send(json.dumps(
                    {"id": msg["id"], "result": {"result": {"type": "string", "value": "ok"}}}))
            else:
                await ws.send(json.dumps(
                    {"id": msg["id"], "error": {"code": -32000, "message": "not found"}}))
        await ws.send(json.dumps(
            {"method": "Network.requestWillBeSent", "params": {"requestId": "1", "url": "x"}}))


def test_send_returns_result():
    async def _run():
        async with websockets.serve(_mock_cdp, "127.0.0.1", 8765):
            client = await CDPClient.connect(8765, ws_url="ws://127.0.0.1:8765")
            r = await client.send("Runtime.evaluate", {"expression": "1"})
            assert r["result"]["value"] == "ok"
            await client.close()

    asyncio.run(_run())


def test_send_error_raises_cdperror():
    async def _run():
        async with websockets.serve(_mock_cdp, "127.0.0.1", 8766):
            client = await CDPClient.connect(8766, ws_url="ws://127.0.0.1:8766")
            try:
                with pytest.raises(CDPError) as ei:
                    await client.send("Nope.nothing")
                assert ei.value.code == -32000
            finally:
                await client.close()

    asyncio.run(_run())


def test_on_event_dispatch():
    got = []

    async def _run():
        async with websockets.serve(_mock_cdp, "127.0.0.1", 8767):
            client = await CDPClient.connect(8767, ws_url="ws://127.0.0.1:8767")
            client.on("Network.requestWillBeSent", lambda p: got.append(p["url"]))
            await client.send("Runtime.evaluate", {"expression": "1"})  # 触发 mock 推事件
            await asyncio.sleep(0.1)
            assert got == ["x"]
            await client.close()

    asyncio.run(_run())
