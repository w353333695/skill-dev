# browser_recorder/export/transcode.py
"""webm→mp4 跨平台转码：用 imageio-ffmpeg 内置 ffmpeg 二进制。

平台中性：不耦合任何系统/厂商。
"""
from __future__ import annotations
from pathlib import Path
import imageio_ffmpeg
import subprocess

DEFAULT_VIDEO_WIDTH = 1024   # 默认导出宽度；高度按原比例自动决定


def to_mp4(src_webm: Path, dst_mp4: Path, *, width: int | None = DEFAULT_VIDEO_WIDTH) -> None:
    """webm → mp4（H.264 / yuv420p，兼容主流播放器）。

    ``width`` 指定输出宽度（像素），高度按原视频比例自动计算（``-2`` 保证偶数，
    libx264 要求）。``width=None`` 表示保持原分辨率不缩放。
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-i", str(src_webm), "-c:v", "libx264",
           "-preset", "fast", "-pix_fmt", "yuv420p"]
    if width:
        cmd += ["-vf", f"scale={int(width)}:-2"]
    cmd.append(str(dst_mp4))
    subprocess.run(cmd, check=True, capture_output=True)
