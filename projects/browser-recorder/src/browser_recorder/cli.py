"""CLI 入口：record / export。"""
from __future__ import annotations

import asyncio
import os
import pathlib
import zipfile
from datetime import datetime

import click

from .recorder import record

DEFAULT_CHROME = pathlib.Path(
    os.environ.get("BR_CHROME",
                   str(pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome")))


@click.group()
def main():
    """browser-recorder：浏览器操作录制 → session.jsonl + 双截图 + PROMPT.md。"""


@main.command("record")
@click.argument("start_url", default="about:blank")
@click.option("--out", "-o", "out_root", default="sessions",
              help="session 输出根目录（默认 sessions/，自动建时间戳子目录）")
@click.option("--settle-timeout", default=30.0, show_default=True,
              help="after 截图稳定等待兜底秒数")
@click.option("--port", default=None, type=int, help="调试端口（默认随机）")
@click.option("--headless/--no-headless", default=False,
              help="无头模式（默认有头；CI/无 DISPLAY 用 --headless）")
@click.option("--no-sandbox", is_flag=True, default=False,
              help="透传 --no-sandbox 给 chrome（容器/AppArmor 环境必需；桌面环境默认不降安全边界）")
@click.option("--profile", "-p", default="default", metavar="NAME",
              help="持久登录态 profile 名（~/.browser-recorder/profiles/NAME），默认 default——cookie/登录跨录制存活，免反复登录；多系统隔离用不同名")
@click.option("--incognito", is_flag=True, default=False,
              help="一次性 profile（不落 ~/.browser-recorder，录完即弃，不留登录态——敏感账号场景）")
def record_cmd(start_url, out_root, settle_timeout, port, headless, no_sandbox,
               profile, incognito):
    """录制：拉起 Chromium，开始记录操作与网络请求。

    停止：页面内 Ctrl+Shift+F9 / 关闭浏览器窗口 / 终端输 q+回车
    """
    if incognito:
        profile = None
    out_dir = pathlib.Path(out_root) / datetime.now().strftime("%Y%m%d-%H%M%S")
    click.echo(f"session 目录: {out_dir}")
    if profile:
        click.echo(f"profile: {profile}（登录态保留，下次免登录）")
    else:
        click.echo("profile: 一次性（不留登录态）")
    click.echo("停止方式：页面内 Ctrl+Shift+F9 ｜ 关闭浏览器窗口 ｜ 终端 q+回车")
    chrome = DEFAULT_CHROME
    if not chrome.exists():
        raise click.ClickException(f"chrome 未找到: {chrome}（可用 BR_CHROME 环境变量指定）")
    try:
        result = asyncio.run(record(out_dir, start_url, chrome,
                                    settle_timeout=settle_timeout, port=port,
                                    headless=headless, profile=profile,
                                    extra_chrome_args=["--no-sandbox"] if no_sandbox else None))
    except KeyboardInterrupt:
        # Ctrl-C：record() 内部已完成 session_end(interrupt) + PROMPT.md 收尾
        click.echo("已中断，已录事件已落盘")
        raise SystemExit(130)
    if result.get("io_error"):
        click.echo(f"完成：{result['events']} 事件，abnormal={result['abnormal']}")
        raise click.ClickException(result["io_error"])
    click.echo(f"完成：{result['events']} 事件，abnormal={result['abnormal']}")
    raise SystemExit(2 if result["abnormal"] else 0)


@main.command("export")
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False))
def export(session_dir):
    """导出 session 目录为 zip（jsonl+screenshots+PROMPT.md）。"""
    src = pathlib.Path(session_dir)
    zip_path = src.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and "chrome-profile" not in f.parts:
                z.write(f, f.relative_to(src))
    click.echo(f"导出: {zip_path}")


if __name__ == "__main__":
    main()
