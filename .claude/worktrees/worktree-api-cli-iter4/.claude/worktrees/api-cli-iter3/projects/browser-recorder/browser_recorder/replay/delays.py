# browser_recorder/replay/delays.py
"""回放延迟解析：按动作类型查表，default 兜底。"""
from __future__ import annotations
from ..config import ReplayPolicy


class DelayResolver:
    def __init__(self, policy: ReplayPolicy):
        self.policy = policy

    def _by(self, table: dict[str, int], action_type: str) -> int:
        return table.get(action_type, table.get("default", 0))

    def before(self, action_type: str) -> int:
        return self._by(self.policy.before_action, action_type)

    def after(self, action_type: str) -> int:
        return self._by(self.policy.after_action, action_type)

    def idle(self) -> int:
        return self.policy.idle_for_visibility
