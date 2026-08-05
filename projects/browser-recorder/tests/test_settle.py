# tests/test_settle.py
import inspect
from browser_recorder.settle import (
    SettleDecider, SignalState, wait_for_settled, _SETTLE_INJECT,
)


def test_signal_state_all_idle():
    s = SignalState(network_idle=True, dom_idle=True, cpu_idle=True)
    assert s.all_idle()


def test_decider_not_settled_initially():
    d = SettleDecider(debounce_ms=300)
    # 初始信号未知，不算稳定
    assert not d.is_settled(0)


def test_decider_settled_after_debounce_of_all_idle():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1100)          # DOM 此后无变化
    d.on_cpu_change(True, 1000)
    assert not d.is_settled(1200)  # 距最近活动 1100 仅 100ms
    assert d.is_settled(1450)      # 距 1100 过 debounce(300)+余量


def test_decider_resets_on_new_network_activity():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
    # 新请求到来
    d.on_network_change(True, 1500)
    assert not d.is_settled(1600)
    # 再次静默 + debounce
    d.on_network_change(False, 1600)
    assert d.is_settled(2000)


def test_decider_resets_on_dom_change():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)
    d.on_dom_change(1500)  # DOM 突变
    assert not d.is_settled(1600)


def test_decider_requires_all_three():
    d = SettleDecider(debounce_ms=300)
    d.on_network_change(False, 1000)
    d.on_dom_change(1000)
    d.mark_dom_idle(1000)
    # 没报告 cpu idle
    assert not d.is_settled(2000)
    d.on_cpu_change(True, 1000)
    assert d.is_settled(1400)


def test_settle_inject_script_is_exported_and_neutral():
    # _SETTLE_INJECT 必须可 import（runner 在 goto 前一次性 add_init_script）
    assert isinstance(_SETTLE_INJECT, str)
    assert "MutationObserver" in _SETTLE_INJECT
    assert "easyops" not in _SETTLE_INJECT.lower()


def test_wait_for_settled_does_not_add_init_script():
    """wait_for_settled 不得再调 add_init_script（I-4）：每次调用会重复添加，
    且首次调用时 page 已 goto 完成，init_script 只对未来导航生效，导致
    首个非导航动作的 settle 信号未定义 → 空等满 timeout。"""
    import ast
    src = inspect.getsource(wait_for_settled)
    tree = ast.parse(src)
    # 找所有 Attribute 调用，断言没有名为 add_init_script 的方法调用
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "add_init_script", (
                "wait_for_settled 不得调用 add_init_script（应在 runner 创建 ctx 后一次性注入）"
            )
