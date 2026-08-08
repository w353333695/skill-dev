# tests/test_record_emit_actions.py
"""录制期 action 落库必须独立于截图成功——点击触发导航（如登录提交）时，
``_capture_for_action`` 内的 settle/screenshot 在导航中会抛错（execution context
destroyed）；若 sink 紧随 capture 且被同一 try 包，整条 action 丢失
（用户报「step-0006 后面一个点击登陆没有捕获到」）。

提取 ``emit_actions(actions, capture_fn, sink_fn)``：截图 try/except 隔离，
落库无条件执行（截图失败时 screenshot 字段为空，但 action 不丢）。
"""
import pytest
from browser_recorder.record.runner import emit_actions
from browser_recorder.models import Action, Target


def _act(seq, type_="click"):
    return Action(seq=seq, ts=0, type=type_, url="u",
                  target=Target(css="#g", bbox={"x": 1, "y": 1, "w": 2, "h": 2}))


@pytest.mark.asyncio
async def test_emit_actions_sinks_even_when_capture_raises():
    """截图抛错（导航中常见）不应阻断 action 落库——修复「漏了点击登录」。"""
    sunk = []

    async def boom(act):
        raise RuntimeError("execution context destroyed")

    def sink(act):
        sunk.append(act.seq)

    await emit_actions([_act(1)], boom, sink)
    assert sunk == [1]


@pytest.mark.asyncio
async def test_emit_actions_captures_then_sinks_in_order():
    """正常路径：先截图后落库，逐条顺序处理。"""
    order = []

    async def cap(act):
        order.append(("cap", act.seq))

    def sink(act):
        order.append(("sink", act.seq))

    await emit_actions([_act(1), _act(2, "input")], cap, sink)
    assert order == [("cap", 1), ("sink", 1), ("cap", 2), ("sink", 2)]


@pytest.mark.asyncio
async def test_emit_actions_one_capture_failure_doesnt_block_rest():
    """一条截图失败，后续 action 仍正常截图+落库。"""
    sunk = []
    capped = []

    async def cap(act):
        if act.seq == 1:
            raise RuntimeError("boom")
        capped.append(act.seq)

    def sink(act):
        sunk.append(act.seq)

    await emit_actions([_act(1), _act(2)], cap, sink)
    assert sunk == [1, 2]
    assert capped == [2]   # seq1 截图失败，seq2 正常截图


@pytest.mark.asyncio
async def test_emit_actions_empty_list_noop():
    await emit_actions([], lambda a: None, lambda a: None)  # 不抛错
