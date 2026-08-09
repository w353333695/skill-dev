"""Event handlers — EventHandler Protocol and built-in implementations."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict
from typing import Protocol, runtime_checkable
from playwright.async_api import Page
from .models import Action


@runtime_checkable
class EventHandler(Protocol):
    """Consumes events, produces artifacts."""

    async def handle(self, action: Action, page: Page) -> None:
        ...

    async def close(self) -> None:
        ...


def _action_to_dict(action: Action) -> dict:
    """Action to JSON-serializable dict."""
    d = asdict(action)
    d["tag"] = d["tag"].value
    return d


class JsonlWriter:
    """Incrementally appends to events.jsonl."""

    def __init__(self, output_dir: Path, batch_size: int = 10) -> None:
        self._path = output_dir / "events.jsonl"
        self._batch_size = batch_size
        self._buffer: list[dict] = []
        self._count = 0

    def write(self, action: Action) -> None:
        """Write an action to the buffer."""
        self._buffer.append(_action_to_dict(action))
        self._count += 1
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """Flush the buffer to disk."""
        if not self._buffer:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            for item in self._buffer:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._buffer.clear()

    async def close(self) -> None:
        """Flush remaining events on close."""
        self.flush()
