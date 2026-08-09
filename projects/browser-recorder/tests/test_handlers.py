"""Test event handlers."""
import json
import tempfile
from pathlib import Path
from browser_recorder.handlers import JsonlWriter
from browser_recorder.models import Action, ActionTag


def test_jsonl_writer_writes_and_flushes():
    """JsonlWriter writes events.jsonl and flushes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir))
        action = Action(
            step=1,
            timestamp_ms=1000.0,
            tag=ActionTag.CLICK,
            selector="#btn",
            tag_name="button",
            url="https://example.com",
            page_id="main",
            text="Click me",
        )
        writer.write(action)
        writer.flush()

        jsonl_path = Path(tmpdir) / "events.jsonl"
        assert jsonl_path.exists()

        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["step"] == 1
        assert data["tag"] == "CLICK"
        assert data["selector"] == "#btn"


def test_jsonl_writer_multiple_events():
    """JsonlWriter writes multiple events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir))
        for i in range(5):
            action = Action(
                step=i + 1,
                timestamp_ms=1000.0 + i * 100,
                tag=ActionTag.INPUT,
                selector=f"#input{i}",
                tag_name="input",
                url="https://example.com",
                page_id="main",
                value=f"value{i}",
            )
            writer.write(action)
        writer.flush()

        jsonl_path = Path(tmpdir) / "events.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 5


def test_jsonl_writer_batch_flush():
    """JsonlWriter auto-flushes when batch threshold is reached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = JsonlWriter(Path(tmpdir), batch_size=3)
        for i in range(5):
            action = Action(
                step=i + 1,
                timestamp_ms=1000.0 + i * 100,
                tag=ActionTag.CLICK,
                selector="#btn",
                tag_name="button",
                url="https://example.com",
                page_id="main",
            )
            writer.write(action)

        jsonl_path = Path(tmpdir) / "events.jsonl"
        assert jsonl_path.exists()
        # batch_size=3 triggers flush at 3rd and 5th (on close/context exit) items
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) >= 3
