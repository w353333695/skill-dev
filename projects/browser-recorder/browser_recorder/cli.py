# browser_recorder/cli.py
"""click CLI 入口：record / replay / export / auth / version。

平台中性：不耦合任何特定系统/厂商，登录态匹配等逻辑在 auth 子包内。
"""
from __future__ import annotations
import time
from pathlib import Path
import click


@click.group()
def main() -> None:
    """浏览器操作录制 / 回放 / 导出 / 登录态管理。"""


@main.command()
@click.option("--url", required=True, help="目标 URL")
@click.option("--auth", "profile", default=None,
              help="登录态 profile 名；不传则自动扫描匹配未过期 profile")
@click.option("--keep-auth-events", "keep_auth_events", is_flag=True,
              help="(reserved，暂未生效) 即便走了手动登录环节也保留登录动作")
@click.option("--screenshot-policy", "screenshot_policy", type=click.Path(), default=None,
              help="截图时机策略 yaml；不指定用内置最佳实践默认")
@click.option("--no-video", "no_video", is_flag=True, help="不录屏（默认录 webm）")
@click.option("--out-dir", "out_dir", default=None, help="产物根目录（默认 ./.browser-recorder）")
@click.option("--name", default=None, help="易读会话名（默认时间戳）")
@click.option("--headless/--headed", default=True, help="是否无头（默认无头；人工录制需 --headed）")
@click.option("--keep-raw-bodies", "keep_raw_bodies", is_flag=True,
              help="所有响应原始体落盘（不受 1MB 阈值限制）")
@click.option("--insecure", "ignore_https_errors", is_flag=True,
              help="跳过 HTTPS 自签/无效证书校验（内网 HTTPS 系统需要）")
@click.option("--timeout", "record_timeout_s", type=float, default=None,
              help="人工录制兜底超时（秒）；不传则 headed=600、headless=10。"
                   "结束录制：Ctrl/Cmd+Shift+X，或直接关浏览器")
@click.option("--capture-all-clicks", "capture_all_clicks", is_flag=True,
              help="逃生开关：关掉交互过滤、记录所有 click（含点空白，噪音大）。"
                   "默认关；仅当 A+B（自定义按钮/tabindex 识别）仍漏动作时启用")
def record(url, profile, keep_auth_events, screenshot_policy, no_video, out_dir, name,
           headless, keep_raw_bodies, ignore_https_errors, record_timeout_s,
           capture_all_clicks):
    """录制浏览器操作。"""
    if keep_auth_events:
        # spec §4.3：登录过程默认剔除；保留需识别登录阶段，复杂度高，暂不实现
        click.echo("[record] 警告：--keep-auth-events 当前为 reserved，暂未生效（登录动作仍会被剔除）")
    # 兜底超时：人工录制（headed）给长上限等快捷键/关窗口；脚本化（headless）
    # 保持短兜底，与原"约 10s 后结束"行为一致。
    if record_timeout_s is None:
        record_timeout_s = 10.0 if headless else 600.0
    from . import paths
    from .record import runner
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    # profile 未指定 → 自动扫描匹配
    if profile is None:
        profile = store.find_matching(od, url, now_ts=time.time())
    sd = runner.run_record(url, od, profile, keep_auth_events,
                           Path(screenshot_policy) if screenshot_policy else None,
                           video=not no_video, name=name, headless=headless,
                           keep_raw_bodies=keep_raw_bodies,
                           ignore_https_errors=ignore_https_errors,
                           record_timeout_s=record_timeout_s,
                           capture_all_clicks=capture_all_clicks)
    click.echo(f"录制完成：{sd}")


@main.command()
@click.argument("session")
@click.option("--auth", "profile", default=None,
              help="登录态 profile 名；不传则自动扫描匹配未过期 profile")
@click.option("--pace", type=click.Choice(["faithful", "human", "slow"]), default="human",
              help="回放节奏（默认 human：固定停顿）")
@click.option("--delay", "delay_overrides", multiple=True, help="如 click.before=200ms")
@click.option("--policy", "policy_path", type=click.Path(), default=None,
              help="回放延迟策略 yaml；不指定用内置默认")
@click.option("--video", is_flag=True, help="录屏（webm 或 mp4）")
@click.option("--video-format", type=click.Choice(["webm", "mp4"]), default="webm",
              help="录屏格式（默认 webm）")
@click.option("--video-width", "video_width", type=int, default=1024,
              help="mp4 导出宽度（像素）；高度按原比例自动计算。0=不缩放。默认 1024")
@click.option("--annotate-during-replay", is_flag=True, help="回放期实时截图（含内联标记）")
@click.option("--out-dir", "out_dir", default=None, help="产物根目录（默认 ./.browser-recorder）")
@click.option("--name", default=None, help="易读会话名（默认时间戳）")
@click.option("--headless/--headed", default=True, help="是否无头（默认无头）")
@click.option("--insecure", "ignore_https_errors", is_flag=True,
              help="跳过 HTTPS 自签/无效证书校验（内网 HTTPS 系统需要）")
def replay(session, profile, pace, delay_overrides, policy_path, video, video_format,
           video_width, annotate_during_replay, out_dir, name, headless, ignore_https_errors):
    """回放操作轨迹。"""
    from . import paths
    from .replay import runner
    od = paths.resolve_out_dir(out_dir)
    rd = runner.run_replay(session, od, profile, pace, list(delay_overrides),
                           Path(policy_path) if policy_path else None,
                           video, video_format, annotate_during_replay, name, headless=headless,
                           ignore_https_errors=ignore_https_errors,
                           video_width=video_width)
    click.echo(f"回放完成：{rd}")


@main.command()
@click.argument("session")
@click.option("--filter-requests", "filter_path", type=click.Path(), default=None,
              help="请求过滤规则 yaml；不指定则用内置最佳实践默认"
                   "（排除静态/埋点/长连接/OPTIONS/304 等无业务语义请求）")
@click.option("--keep-raw-bodies", is_flag=True,
              help="导出期保留所有响应原始体引用（不影响录制期，仅标注）")
@click.option("--annotate-style", type=click.Choice(["compact", "verbose"]), default="verbose",
              help="画标风格：verbose（半透明填充+描边+序号）/ compact（仅描边+序号）。默认 verbose")
@click.option("--annotate-opacity", type=int, default=60,
              help="半透明填充透明度 0–100。默认 60")
@click.option("--format", "fmt", type=click.Choice(["md", "html", "both"]), default="md",
              help="导出报告格式：md（默认）/ html / both")
@click.option("--out-dir", "out_dir", default=None, help="产物根目录（默认 ./.browser-recorder）")
@click.option("--name", default=None, help="导出目录名（默认同 session 名）")
def export(session, filter_path, keep_raw_bodies, annotate_style, annotate_opacity, fmt, out_dir, name):
    """导出图文报告 + 接口清单。"""
    from . import paths
    from .export import runner
    od = paths.resolve_out_dir(out_dir)
    ed = runner.run_export(session, od, name,
                           Path(filter_path) if filter_path else None,
                           keep_raw_bodies, annotate_style, annotate_opacity, fmt=fmt)
    click.echo(f"导出完成：{ed}")


@main.group()
def auth():
    """登录态管理。"""


@auth.command("list")
@click.option("--out-dir", "out_dir", default=None)
def auth_list(out_dir):
    from . import paths
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    for n in store.list_profiles(od):
        click.echo(n)


@auth.command("show")
@click.argument("profile")
@click.option("--out-dir", "out_dir", default=None)
def auth_show(profile, out_dir):
    from . import paths
    from .auth import store
    od = paths.resolve_out_dir(out_dir)
    loaded = store.load_profile(od, profile)
    if loaded is None:
        click.echo("not found")
        return
    meta, _ = loaded
    expired = store.is_expired(meta, time.time())
    scope = meta.scope or {}
    reg = scope.get("registrable_domain") or "(unknown)"
    hosts = ",".join(scope.get("hosts") or []) or "(none)"
    schemes = ",".join(scope.get("scheme") or []) or "(none)"
    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(meta.created_at))
    expires_at_ts = meta.created_at + meta.expires_in_days * 86400
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at_ts))
    click.echo(f"profile     : {meta.name}")
    click.echo(f"created_at  : {created}")
    click.echo(f"expires_at  : {expires} ({meta.expires_in_days}d)")
    click.echo(f"expired     : {'是' if expired else '否'}")
    click.echo(f"scope.reg   : {reg}")
    click.echo(f"scope.hosts : {hosts}")
    click.echo(f"scope.scheme: {schemes}")


@auth.command("refresh")
@click.argument("profile")
@click.option("--url", "url", required=True, help="登录目标 URL（用于派生 scope）")
@click.option("--out-dir", "out_dir", default=None)
@click.option("--expires", "expires_in_days", type=int, default=7,
              help="有效期天数（默认 7）")
@click.option("--headless/--headed", default=False,
              help="是否无头（默认有头，便于人工登录）")
@click.option("--insecure", "ignore_https_errors", is_flag=True,
              help="跳过 HTTPS 自签/无效证书校验（内网 HTTPS 系统需要）")
def auth_refresh(profile, url, out_dir, expires_in_days, headless, ignore_https_errors):
    """交互式重新登录并刷新 profile 的 storage_state。

    平台中性：仅启动浏览器让用户登录，回车后抓 storage_state 存入；不耦合
    任何系统/鉴权细节。``headless=False`` 时阻塞等待用户回车；``headless=True``
    时直接退出（无法人工登录，会留一条警告）。
    """
    import asyncio
    from . import paths
    from .auth import store
    from .record.runner import _interactive_login, _scope_from_url
    from playwright.async_api import async_playwright
    od = paths.resolve_out_dir(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    if headless:
        click.echo("[auth refresh] 无头模式无法人工登录，请使用 --headed（默认）")
        return
    async def _do():
        async with async_playwright() as pw:
            return await _interactive_login(pw, url, headless=False,
                                            ignore_https_errors=ignore_https_errors)
    state = asyncio.run(_do())
    if state is None:
        click.echo("[auth refresh] 未抓到 storage_state，profile 未更新")
        return
    store.save_profile(od, profile, state, scope=_scope_from_url(url),
                       expires_in_days=expires_in_days, now_ts=time.time())
    click.echo(f"profile '{profile}' 已刷新，scope={_scope_from_url(url)}")


@main.command()
def version():
    """显示版本。"""
    from . import __version__
    click.echo(__version__)


if __name__ == "__main__":
    main()
