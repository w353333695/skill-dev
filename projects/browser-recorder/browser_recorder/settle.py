# browser_recorder/settle.py
"""页面稳定判定：网络空闲 + DOM 稳定 + 主线程空闲 三信号 + debounce。

状态机 SettleDecider 是纯逻辑，便于单测；wait_for_settled 是在真实 page 上的封装。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class SignalState:
    network_idle: bool = False
    dom_idle: bool = False
    cpu_idle: bool = False

    def all_idle(self) -> bool:
        return self.network_idle and self.dom_idle and self.cpu_idle


@dataclass
class SettleResult:
    settled: bool
    settled_by: str  # "network_dom_cpu" | "timeout"
    elapsed_ms: int


class SettleDecider:
    """三信号稳定判定状态机。任一信号活动 → 重置静默计时。"""

    def __init__(self, debounce_ms: int):
        self.debounce_ms = debounce_ms
        self.state = SignalState()
        self._last_activity_ts: int | None = None
        self._have_signals = False  # 三个信号是否都至少报告过一次

    def _touch(self, ts_ms: int) -> None:
        self._last_activity_ts = ts_ms

    def on_network_change(self, has_inflight: bool, ts_ms: int) -> None:
        self.state.network_idle = not has_inflight
        if has_inflight:
            self._touch(ts_ms)
        self._have_signals = True

    def on_dom_change(self, ts_ms: int) -> None:
        # DOM 突变视为活动；之后需要等再次静默
        self.state.dom_idle = False
        self._touch(ts_ms)
        self._have_signals = True
        # 立即标记为 idle 由后续无变化推定（见 is_settled 的 dom_idle 维护）
        # 这里不直接置 True，避免突变即判稳

    def mark_dom_idle(self, ts_ms: int) -> None:
        """DOM 无突变时调用，标记 dom_idle。"""
        self.state.dom_idle = True

    def on_cpu_change(self, idle: bool, ts_ms: int) -> None:
        self.state.cpu_idle = idle
        if not idle:
            self._touch(ts_ms)
        self._have_signals = True

    def is_settled(self, ts_ms: int) -> bool:
        if not self._have_signals:
            return False
        if not self.state.all_idle():
            return False
        if self._last_activity_ts is None:
            return True
        return (ts_ms - self._last_activity_ts) >= self.debounce_ms


async def wait_for_settled(page: "Page", *, timeout_ms: int,
                           debounce_ms: int) -> SettleResult:
    """在真实 page 上跑三信号判定，超时兜底。

    通过注入 JS（MutationObserver + requestIdleCallback）上报 DOM/CPU；
    网络空闲通过 page 的 requestfinished/response 事件近似。

    **重要**：DOM/CPU 上报脚本（``_SETTLE_INJECT``）必须在创建 context 后、
    首次 ``goto`` **之前**通过 ``ctx.add_init_script(_SETTLE_INJECT)`` 注入一次，
    使其对所有当前及未来导航生效。本函数**不再**调 ``add_init_script``：
    在已 goto 的页面上加 init_script 不会立即执行（只对未来导航生效），
    会导致首个非导航动作的 settle 信号未定义 → 空等满 timeout_ms。
    集成测试在 Task 17 覆盖。
    """
    import time
    decider = SettleDecider(debounce_ms=debounce_ms)
    start = time.monotonic()
    inflight = 0

    def _on_request(_req):
        nonlocal inflight
        inflight += 1
        decider.on_network_change(True, int((time.monotonic() - start) * 1000))

    def _on_done(_x):
        nonlocal inflight
        inflight = max(0, inflight - 1)
        ts = int((time.monotonic() - start) * 1000)
        decider.on_network_change(inflight > 0, ts)

    page.on("request", _on_request)
    page.on("requestfinished", _on_done)
    page.on("requestfailed", _on_done)

    deadline = start + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        ts = int((time.monotonic() - start) * 1000)
        info = await page.evaluate(
            "() => ({dom_idle: window.__br_dom_idle === true, cpu_idle: window.__br_cpu_idle === true, dom_changed: window.__br_dom_changed})")
        if info.get("dom_changed"):
            decider.on_dom_change(ts)
        else:
            decider.mark_dom_idle(ts)
        decider.on_cpu_change(bool(info.get("cpu_idle")), ts)
        if decider.is_settled(ts):
            return SettleResult(settled=True, settled_by="network_dom_cpu", elapsed_ms=ts)
        await page.wait_for_timeout(50)
    return SettleResult(settled=False, settled_by="timeout", elapsed_ms=timeout_ms)


_SETTLE_INJECT = r"""
(function(){
  window.__br_dom_idle = false;
  window.__br_cpu_idle = false;
  window.__br_dom_changed = false;
  let domTimer = null;
  const obs = new MutationObserver(function(){
    window.__br_dom_changed = true;
    window.__br_dom_idle = false;
    if (domTimer) clearTimeout(domTimer);
    domTimer = setTimeout(function(){ window.__br_dom_idle = true; window.__br_dom_changed = false; }, 300);
  });
  obs.observe(document, {childList:true, subtree:true, attributes:true});
  function tick(){
    window.__br_cpu_idle = true;
    requestIdleCallback(function(){ setTimeout(tick, 200); }, {timeout: 500});
  }
  if ('requestIdleCallback' in window) tick(); else window.__br_cpu_idle = true;
})();
"""

__all__ = ["SignalState", "SettleResult", "SettleDecider",
           "wait_for_settled", "_SETTLE_INJECT"]
