"""browser-recorder CLI: record / replay / login / doctor."""

from __future__ import annotations

import click

from . import __version__

DEFAULT_OUTPUT_DIR = ".browser-recorder/sessions"


@click.group()
@click.version_option(__version__, prog_name="browser-recorder")
def main() -> None:
    """录制浏览器操作，生成图文手册 + 结构化记录 + 请求日志，支持回放。"""


@main.command()
@click.option("--url", default=None, help="起始 URL（headed 新开浏览器时使用）")
@click.option("--cdp", default=None, help="CDP endpoint，attach 已开的浏览器，如 http://localhost:9222")
@click.option("--auth/--no-auth", default=True, help="是否自动加载/维护登录态（默认开）")
@click.option("--username", default=None, help="登录账号（配合 --password 自动填表登录，无 UI 可用）")
@click.option("--password", default=None, help="登录密码")
@click.option("--ignore-https-errors", is_flag=True, help="忽略证书错误（自签证书的内网站点）")
@click.option("--headless", is_flag=True, help="无头模式（无 UI 环境调试用；正常录制勿用）")
@click.option("-o", "--output", default=DEFAULT_OUTPUT_DIR, help="session 输出根目录")
@click.option("--video", is_flag=True, help="录制期录像（仅 headed 模式支持）")
def record(url: str | None, cdp: str | None, auth: bool, username: str | None, password: str | None,
           ignore_https_errors: bool, headless: bool, output: str, video: bool) -> None:
    """录制浏览器操作，产出 doc.md / record.jsonl / requests.jsonl。"""
    if not url and not cdp:
        raise click.UsageError("需要 --url 或 --cdp 之一")
    if url and cdp:
        raise click.UsageError("--url 与 --cdp 互斥")

    from .recorder import Recorder

    recorder = Recorder(
        url=url, cdp=cdp, use_auth=auth, output_root=output, video=video, headless=headless,
        username=username, password=password, ignore_https_errors=ignore_https_errors,
    )
    session_dir = recorder.run()
    click.echo(f"\n录制完成，产物目录: {session_dir}")


@main.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--param", multiple=True, help="参数化覆盖，key=value，可多次；对应 record.jsonl 里的 param_key")
@click.option("--on-fail", type=click.Choice(["stop", "skip"]), default="stop", help="步骤失败策略")
@click.option("--video", is_flag=True, help="回放录像（存 session_dir/replay/）")
@click.option("--timeout", default=15000, help="每步元素等待超时 ms")
@click.option("--ignore-https-errors", is_flag=True, help="忽略证书错误（自签证书站点回放）")
def replay(session_dir: str, param: tuple[str, ...], on_fail: str, video: bool, timeout: int,
           ignore_https_errors: bool) -> None:
    """回放指定 session 的操作记录。"""
    from .replayer import Replayer

    params = dict(p.split("=", 1) for p in param)
    replayer = Replayer(session_dir, params=params, on_fail=on_fail, video=video, timeout_ms=timeout,
                        ignore_https_errors=ignore_https_errors)
    report = replayer.run()
    click.echo(f"回放完成: {report['passed']}/{report['total']} 通过, 报告: {report['report_path']}")
    if report["failed"]:
        raise SystemExit(1)


@main.command()
@click.option("--url", required=True, help="目标站点 URL")
@click.option("--username", default=None, help="登录账号（配合 --password 自动填表，无 UI 可用）")
@click.option("--password", default=None, help="登录密码")
@click.option("--ignore-https-errors", is_flag=True, help="忽略证书错误（自签证书站点）")
@click.option("--auth-dir", default=".browser-recorder/auth", help="登录态保存目录")
def login(url: str, username: str | None, password: str | None, ignore_https_errors: bool, auth_dir: str) -> None:
    """登录并保存登录态到 auth/<host>.json。给了账密自动填表，否则人手动登录。"""
    from .auth import AuthManager

    path = AuthManager(auth_dir).login(url, username=username, password=password,
                                       ignore_https_errors=ignore_https_errors)
    click.echo(f"登录态已保存: {path}")


@main.command()
def doctor() -> None:
    """检查运行环境（playwright / chromium / ffmpeg）。"""
    from .doctor import run_doctor

    ok = run_doctor()
    if not ok:
        raise SystemExit(1)
