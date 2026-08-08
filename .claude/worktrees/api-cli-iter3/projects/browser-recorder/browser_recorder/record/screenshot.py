# browser_recorder/record/screenshot.py
"""截图时机策略：动作类型→截图点、输入聚合、连续重复滤除。

本模块是 spec §5「截图时机 + 输入聚合」的核心，被 Task 16 capture.py 的
EventToAction 消费。

输入聚合语义说明（重要）：
    每个 input 事件回传的 ``value`` 是目标字段当前**全量值**（与浏览器原生
    ``input`` 事件 ``event.target.value`` 一致），而非单字符增量。因此聚合
    采用**覆盖**策略——新 chunk 直接覆盖缓冲区，连续多次 input 事件被合并
    为一条动作，最终落库的 value 为最后一次快照。这与浏览器实际行为一致，
    也使测试 ``consume_input_chunk("k","a")`` → ``("k","b")`` →
    ``("k","ab",finalize=True)`` 后 ``get_input_value()=="ab"`` 成立。
"""
from __future__ import annotations

from ..config import ScreenshotPolicy


class ScreenshotPlanner:
    """决定每个原始事件是否产图、何时产图，并完成输入聚合 / 连续去重。

    状态：
        _last               : 上一次去重判定的 (type, fingerprint, ts)
        _input_buf          : key -> 当前累积的输入全量值快照
        _current_input_key  : 当前正在聚合的输入元素 key
    """

    def __init__(self, policy: ScreenshotPolicy):
        self.policy = policy
        self._last: tuple[str, str, int] | None = None
        self._input_buf: dict[str, str] = {}
        self._current_input_key: str | None = None

    # ------------------------------------------------------------------
    # 截图点映射
    # ------------------------------------------------------------------
    def should_capture(self, event: dict) -> list[str]:
        """根据事件 type 返回应触发的截图点列表（拷贝，避免污染 policy）。"""
        t = event.get("type", "")
        return list(self.policy.points.get(t, []))

    # ------------------------------------------------------------------
    # 输入聚合
    # ------------------------------------------------------------------
    def consume_input_chunk(
        self,
        key: str,
        value: str,
        *,
        finalize: bool = False,
        finalize_prev: bool = False,
    ) -> bool:
        """消费一段输入 chunk，返回 True 表示「该 input 动作可落库 + 产 after 图」。

        - 连续同 key 的 chunk：覆盖缓冲区（取最新全量快照），返回 False。
        - ``finalize=True``：当前聚合结束，返回 True；缓冲区与 current key
          保留，使紧接着的 ``get_input_value()`` 可读到刚落库的值。
        - ``finalize_prev=True`` 且 key 切换：上一段（旧 key）聚合结束（可
          落库），本调用同时开启新 key 的聚合。返回 True 通知调用方「上一
          段已就绪」，调用方应通过 ``get_pending_value(旧 key)`` 取值落库。
        """
        switched = (
            self._current_input_key is not None
            and key != self._current_input_key
        )

        if finalize_prev and switched:
            # 切换元素：旧 key 的聚合结束（可落库 + 产 after 图）。
            # 本调用 value 计入新 key 的聚合开始。
            self._current_input_key = key
            self._input_buf[key] = value
            return True

        # 普通聚合：同 key 续打 / 首次 / 隐式切换，统一覆盖最新快照。
        self._current_input_key = key
        self._input_buf[key] = value

        if finalize:
            # 当前聚合结束（可落库 + 产 after 图）。
            # 保留 _current_input_key 与缓冲区，便于调用方立即读取。
            return True
        return False

    def get_input_value(self) -> str:
        """返回当前正在聚合（或刚 finalize）的元素 value 全量快照。"""
        if self._current_input_key is None:
            return ""
        return self._input_buf.get(self._current_input_key, "")

    def get_pending_value(self, key: str) -> str:
        """取出并移除指定 key 的待落库 value（用于 key 切换后取旧 key 的值）。"""
        return self._input_buf.pop(key, "")

    # ------------------------------------------------------------------
    # 连续重复滤除
    # ------------------------------------------------------------------
    def is_duplicate(self, action_type: str, fingerprint: str, ts_ms: int) -> bool:
        """同 type + 同 fingerprint 在 dedup_window_ms 内视为重复。"""
        if self._last is not None:
            lt, lf, lts = self._last
            if lt == action_type and lf == fingerprint:
                if ts_ms - lts <= self.policy.dedup_window_ms:
                    self._last = (action_type, fingerprint, ts_ms)
                    return True
        self._last = (action_type, fingerprint, ts_ms)
        return False
