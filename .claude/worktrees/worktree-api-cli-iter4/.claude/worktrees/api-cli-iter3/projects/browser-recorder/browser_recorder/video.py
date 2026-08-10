# browser_recorder/video.py
"""录屏封装：Playwright record_video 路径管理 + 可选转码。

平台中性：不耦合任何系统/厂商。
"""
from __future__ import annotations
from pathlib import Path


def video_final_path(session_dir: Path, fmt: str = "webm") -> Path:
    """会话目录下最终视频路径（webm 直接由 Playwright 产；mp4 由 transcode 转）。"""
    if fmt == "mp4":
        return session_dir / "video.mp4"
    return session_dir / "video.webm"
