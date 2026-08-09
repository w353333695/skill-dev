"""清理器 — 录制结束后的临时文件清理."""
import shutil
from pathlib import Path


def cleanup(output_dir: Path, keep_all: bool = False) -> None:
    """清理输出目录中的临时文件.

    默认（keep_all=False）:
      - 保留: record.md, requests.json
      - 删除: screenshots/ 目录及其内容

    keep_all=True:
      - 保留所有文件（包括 events.jsonl, requests_full.json, screenshots/）
    """
    if keep_all:
        return

    screenshots_dir = output_dir / "screenshots"
    if screenshots_dir.exists() and screenshots_dir.is_dir():
        shutil.rmtree(screenshots_dir)
