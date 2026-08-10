"""环境自检：playwright 可导入、chromium 缓存存在、ffmpeg（录像）可用。"""

from __future__ import annotations

from pathlib import Path

import click


def run_doctor() -> bool:
    ok = True

    try:
        import playwright  # noqa: F401

        click.echo("[ok] playwright 可导入")
    except ImportError:
        click.echo("[fail] playwright 未安装")
        ok = False

    cache = Path.home() / ".cache" / "ms-playwright"
    chromium = list(cache.glob("chromium-*")) if cache.exists() else []
    if chromium:
        click.echo(f"[ok] chromium: {chromium[0].name}")
    else:
        click.echo("[fail] 未找到 chromium 缓存，请运行: playwright install chromium")
        ok = False

    ffmpeg = list(cache.glob("ffmpeg-*")) if cache.exists() else []
    if ffmpeg:
        click.echo(f"[ok] ffmpeg: {ffmpeg[0].name}（回放录像可用）")
    else:
        click.echo("[warn] 未找到 ffmpeg，回放录像不可用（playwright install ffmpeg）")

    return ok
