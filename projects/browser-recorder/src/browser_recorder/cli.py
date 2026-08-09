"""CLI 入口 — Typer 命令定义."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console

app = typer.Typer(
    name="recorder",
    help="浏览器操作录制 CLI 工具",
    no_args_is_help=True,
)
console = Console()


@app.command()
def start(
    url: str = typer.Option(..., "--url", help="起始 URL"),
    output: Optional[Path] = typer.Option(
        None, "--output", help="输出目录（默认按域名自动分配，如 .../example.com/）"
    ),
    interval: int = typer.Option(30, "--interval", help="兜底截图间隔（秒）"),
    req_all: bool = typer.Option(False, "--req-all", help="记录所有请求"),
    req_filter: Optional[str] = typer.Option(None, "--req-filter", help="请求过滤 glob"),
    keep_all: bool = typer.Option(False, "--keep-all", help="保留全部过程文件"),
    max_duration: int = typer.Option(0, "--max-duration", help="最大录制时长（秒），0=不限"),
    plugin: Optional[Path] = typer.Option(None, "--plugin", help="自定义 handler 模块"),
) -> None:
    """启动浏览器录制 session."""
    from .recorder import Recorder

    console.print(f"[bold green]▶[/bold green] 启动录制: {url}")
    console.print(f"  按 Ctrl+C 停止录制")

    recorder = Recorder(
        url=url,
        output_dir=output,
        fallback_interval=interval,
        req_all=req_all,
        req_filter=req_filter,
        keep_all=keep_all,
        max_duration=max_duration,
    )

    import asyncio
    try:
        asyncio.run(recorder.run())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⏹[/bold yellow] 录制已停止")


@app.command()
def replay(
    events: Path = typer.Argument(..., help="events.jsonl 文件路径"),
    speed: float = typer.Option(1.0, "--speed", help="人为停顿倍速"),
    repeat: int = typer.Option(1, "--repeat", help="重复回放次数"),
    output: Optional[Path] = typer.Option(None, "--output", help="输出目录"),
    keep_all: bool = typer.Option(False, "--keep-all", help="保留回放的全部过程文件"),
) -> None:
    """回放录制的事件链."""
    from .replay import ReplayEngine

    console.print(f"[bold green]▶[/bold green] 回放: {events}")
    console.print(f"  倍速: {speed}x | 重复: {repeat}")

    engine = ReplayEngine(
        events_path=events,
        speed=speed,
        repeat=repeat,
        output_dir=output,
        keep_all=keep_all,
    )

    import asyncio
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⏹[/bold yellow] 回放已停止")


@app.command()
def doctor() -> None:
    """检查环境（Chromium 是否安装）."""
    console.print("[bold]browser-recorder 环境检查[/bold]\n")

    # 检查 Python 版本
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 9):
        console.print(f"  ✅ Python {py_ver}")
    else:
        console.print(f"  ❌ Python {py_ver} (需要 >= 3.9)")
        return

    # 检查 Playwright
    try:
        import playwright
        from importlib.metadata import version as pkg_version
        console.print(f"  ✅ Playwright {pkg_version('playwright')}")
    except ImportError:
        console.print("  ❌ Playwright 未安装")
        console.print("     安装: pip install playwright")
        return

    # 检查 Chromium
    import subprocess
    result = subprocess.run(
        ["playwright", "install", "--dry-run", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print("  ✅ Chromium 已安装")
    else:
        console.print("  ⚠️  Chromium 未安装")
        console.print("     安装: playwright install chromium")

    # 检查依赖
    for lib, name in [("Pillow", "Pillow"), ("rich", "Rich"), ("typer", "Typer")]:
        try:
            __import__(lib.lower() if lib != "Pillow" else "PIL")
            console.print(f"  ✅ {name}")
        except ImportError:
            console.print(f"  ❌ {name} 未安装")

    console.print("\n[bold green]环境检查完成[/bold green]")


@app.command("list")
def list_sessions() -> None:
    """列出所有录制的域名 session."""
    from .recorder import load_index, load_meta, ARTIFACT_ROOT, session_path

    index = load_index()
    domains = index.get("domains", {})

    if not domains:
        console.print("[dim]暂无录制 session[/dim]")
        return

    console.print(f"\n[bold]录制 Session 列表[/bold] ({ARTIFACT_ROOT})\n")

    for domain, info in sorted(domains.items()):
        sp = session_path(f"https://{domain}")
        meta = load_meta(sp)
        last = info.get("last_recorded", "?")[:19]
        count = info.get("total_recordings", 0)
        urls = meta.get("urls", [])

        console.print(f"  [bold cyan]{domain}[/bold cyan]")
        console.print(f"    录制次数: {count}  |  最近: {last}")
        if urls:
            console.print(f"    URL: {', '.join(urls[:3])}{' ...' if len(urls) > 3 else ''}")
        console.print(f"    目录: {sp}")
        console.print()


@app.command()
def version() -> None:
    """显示版本号."""
    from . import __version__
    console.print(f"browser-recorder v{__version__}")


if __name__ == "__main__":
    app()
