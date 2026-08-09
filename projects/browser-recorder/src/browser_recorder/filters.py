"""事件过滤器 — EventFilter Protocol 及内置实现."""
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class EventFilter(Protocol):
    """过滤/变换原始事件."""

    def process(self, event: dict) -> list[dict]:
        """处理单个事件，返回 0~N 个事件."""
        ...

    def flush(self) -> list[dict]:
        """刷新内部缓冲区."""
        ...


class FilterPipeline:
    """串联多个 EventFilter."""

    def __init__(self) -> None:
        self._filters: list[EventFilter] = []

    def add(self, f: EventFilter) -> "FilterPipeline":
        self._filters.append(f)
        return self

    def process(self, event: dict) -> list[dict]:
        batch = [event]
        for f in self._filters:
            next_batch: list[dict] = []
            for ev in batch:
                next_batch.extend(f.process(ev))
            batch = next_batch
        return batch

    def flush(self) -> list[dict]:
        """刷新所有 filter 的内部缓冲区，结果按顺序依次流经后续 filter."""
        results: list[dict] = []
        for i, f in enumerate(self._filters):
            flushed = f.flush()
            batch = flushed
            for subsequent_f in self._filters[i + 1 :]:
                next_batch: list[dict] = []
                for ev in batch:
                    next_batch.extend(subsequent_f.process(ev))
                batch = next_batch
            results.extend(batch)
        return results


class InputMergeFilter:
    """合并同一 selector 的连续 INPUT 事件，保留第一个和最后一个."""

    def __init__(self) -> None:
        self._pending_selector: Optional[str] = None
        self._first_event: Optional[dict] = None
        self._last_event: Optional[dict] = None

    def process(self, event: dict) -> list[dict]:
        if event.get("type") != "INPUT":
            flushed = self._flush_buffer()
            return flushed + [event]

        selector = event.get("selector", "")

        if self._pending_selector is not None and selector != self._pending_selector:
            flushed = self._flush_buffer()
            self._start_batch(event)
            return flushed

        if self._first_event is None:
            self._start_batch(event)
        else:
            self._last_event = event

        return []

    def flush(self) -> list[dict]:
        return self._flush_buffer()

    def _start_batch(self, event: dict) -> None:
        self._pending_selector = event.get("selector", "")
        self._first_event = event
        self._last_event = event

    def _flush_buffer(self) -> list[dict]:
        result: list[dict] = []
        if self._first_event is not None:
            result.append(self._first_event)
            if self._last_event is not None and self._last_event != self._first_event:
                if self._first_event.get("value") != self._last_event.get("value"):
                    result.append(self._last_event)
                else:
                    # 相同 value，只保留一个位置信息更新
                    pass
        self._pending_selector = None
        self._first_event = None
        self._last_event = None
        return result


class DedupFilter:
    """去重相邻完全相同的重复事件."""

    def __init__(self) -> None:
        self._last_event: Optional[dict] = None

    def process(self, event: dict) -> list[dict]:
        if self._is_duplicate(event):
            return []
        self._last_event = event
        return [event]

    def flush(self) -> list[dict]:
        return []

    def _is_duplicate(self, event: dict) -> bool:
        if self._last_event is None:
            return False
        return (
            self._last_event.get("type") == event.get("type")
            and self._last_event.get("selector") == event.get("selector")
            and self._last_event.get("value") == event.get("value")
        )
