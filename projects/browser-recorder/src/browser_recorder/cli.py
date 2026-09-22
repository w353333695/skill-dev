"""CLI 入口：record / export / drive / replay。"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
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


@main.command("drive")
@click.argument("flow_file", type=click.Path(exists=True))
@click.option("--out", "-o", "out_root", default="sessions",
              help="session 输出根目录（默认 sessions/，自动建时间戳子目录）")
@click.option("--profile", "-p", default=None, metavar="NAME",
              help="持久登录态 profile 名（默认一次性，录完即弃）")
@click.option("--headless/--no-headless", default=False,
              help="无头模式（默认有头；CI/无 DISPLAY 用 --headless）")
@click.option("--no-record", is_flag=True, default=False,
              help="不保留 session 产物（落临时目录用完即弃，行为与录无别）")
@click.option("--var", "vars_", multiple=True, metavar="KEY=VALUE",
              help="注入 ${env.KEY} 变量（可多次；密码走环境变量，不落盘）")
@click.option("--step-from", default=None, type=int, metavar="N",
              help="从步号 N 开始执行（断点续跑，自动补回起点导航；之前的步不执行）")
@click.option("--dry-run", is_flag=True, default=False,
              help="只 locate 不 act（选择器体检）")
@click.option("--no-sandbox", is_flag=True, default=False,
              help="透传 --no-sandbox 给 chrome（容器/AppArmor 环境必需）")
def drive_cmd(flow_file, out_root, profile, headless, no_record, vars_,
              step_from, dry_run, no_sandbox):
    """驱动浏览器执行动作链 flow.json（默认跑即录）。

    退出码：0 成功 / 3 步失败（证据包已落盘）或运行中断（浏览器崩溃等）/
    4 flow 格式错误（含变量未定义）
    """
    from .flow import FlowError, load_flow, run_flow
    from .harness import SessionHarness

    try:
        flow = load_flow(flow_file)
    except FlowError as e:
        # 4 语义：格式/校验错误——不用 ClickException（那是 exit 1）
        click.echo(f"flow 格式错误: {e}", err=True)
        raise SystemExit(4)
    except (OSError, ValueError) as e:   # 文件不可读 / JSON 解析失败
        click.echo(f"flow 文件不可读: {e}", err=True)
        raise SystemExit(4)

    env = {}
    for kv in vars_:
        k, _, v = kv.partition("=")
        env[k] = v

    if no_record:
        import tempfile
        out_dir = pathlib.Path(tempfile.mkdtemp(prefix="br-drive-"))
    else:
        out_dir = pathlib.Path(out_root) / datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"session 目录: {out_dir}")
    chrome = DEFAULT_CHROME
    if not chrome.exists():
        if no_record:
            shutil.rmtree(out_dir, ignore_errors=True)
        raise click.ClickException(f"chrome 未找到: {chrome}（可用 BR_CHROME 指定）")

    async def _run():
        h = SessionHarness(out_dir, "about:blank", chrome, headless=headless,
                           profile=profile, mode="drive",
                           extra_chrome_args=["--no-sandbox"] if no_sandbox else None)

        async def _closeout(ok: bool, stop_reason: str = "drive_done") -> None:
            """跑即录产物收尾（与 record 同构）：末步 after 截图等完 +
            flush_inputs + session_end + PROMPT.md——session 产物对
            browser-manual 等下游与真人录制无差别。

            stop_reason 语义（与步失败的 "drive_fail" 区分）：
            - drive_done：全部步跑完（ok=True）
            - drive_fail：步失败/热键停止（run_flow 返回 exit 3）
            - invalid：run 期 FlowError（flow 格式级错误，exit 4）
            - interrupt：run 期浏览器侧异常（崩溃/连接断，exit 3）
            """
            if h.body_tasks:  # 在途 _after_shot / response_body 抓取
                await asyncio.wait(set(h.body_tasks),
                                   timeout=h.settle_timeout + 2)
            try:
                await h.flush_inputs()
            except Exception:
                pass
            # M-1：收尾 emit 守卫（对齐 record() 的收尾降级）——磁盘满/文件
            # 已关时 session_end 的 OSError 不冒泡顶掉退出码；emit 前截获的
            # 拷贝（emit 失败即丢弃）同理兜底。
            try:
                h.writer.emit("session_end", {
                    "abnormal": not ok,
                    "stop_reason": "drive_done" if ok else stop_reason,
                    "tabs": [t.tid for t in h.tabs.values()]})
            except (OSError, ValueError):
                pass
            h.copy_prompt()

        # I-2：no_record 临时目录用后即删（含登录态的 session.jsonl/chrome-
        # profile 不留在 /tmp）。try/finally 包住 async with 全路径——步失败/
        # FlowError/进程异常都不泄漏；正常录制目录不在此分支，不会误删。
        # rmtree 前置条件：__aexit__ 已收敛 chrome 进程（Browser.close →
        # terminate → kill），user-data-dir 不再被进程占用。
        try:
            async with h:
                # run 期 resolve_vars 的 FlowError（变量未定义）也是格式级错误
                # → exit 4（不是 ClickException 的 exit 1）；session_end 记
                # invalid（与步失败的 drive_fail 区分——格式问题不是驱动失败）
                try:
                    result = await run_flow(h, flow, env=env, dry_run=dry_run,
                                            step_from=step_from)
                except FlowError as e:
                    click.echo(f"flow 格式错误: {e}", err=True)
                    await _closeout(ok=False, stop_reason="invalid")
                    return {"exit_code": 4}
                except Exception as e:
                    # run 期浏览器侧异常（浏览器被关/崩溃、CDP 连接断）：
                    # 不冒泡裸 traceback——收尾后转 exit 3（运行中断，
                    # 与步失败同码段：都属"这一轮没跑成"）
                    click.echo(f"运行中断: {e}", err=True)
                    await _closeout(ok=False, stop_reason="interrupt")
                    return {"ok": False, "steps_done": 0, "failed_step": None,
                            "exit_code": 3}
                await _closeout(ok=result["exit_code"] == 0)
                return result
        finally:
            if no_record:
                shutil.rmtree(out_dir, ignore_errors=True)

    result = asyncio.run(_run())
    if result["exit_code"] == 3 and result.get("failed_step") is not None:
        click.echo(f"失败于步骤 {result['failed_step']}（证据包已落盘）")
    elif result["exit_code"] == 3:
        pass   # 运行中断（崩溃/连接断）：原因已在 _run 内 echo 到 stderr
    elif result["exit_code"] == 0 and not no_record:
        click.echo(f"完成：{result['steps_done']} 步")
    raise SystemExit(result["exit_code"])


@main.command("replay")
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--out", "-o", default=None,
              help="输出 flow.json 路径（默认 flows/<name>.json）")
@click.option("--name", default=None, help="flow 名（默认 session 目录名）")
@click.option("--keep-fragile", is_flag=True, default=False,
              help="保留仅 dom_path 兜底的步（steps 里附 fragile:true，报告仍列出）")
def replay_cmd(session_dir, out, name, keep_fragile):
    """session → flow.json 转换器（稳定性候选链推导；默认剔除仅 dom_path
    兜底的步并出报告）。产物必须过 load_flow 校验。

    退出码：0 成功 / 1 转换产物未过校验（含 session.jsonl 缺失）
    """
    from .flow import FlowError, load_flow
    from .replay import session_to_flow

    sd = pathlib.Path(session_dir)
    sj = sd / "session.jsonl"
    if not sj.exists():
        raise click.ClickException(f"未找到 {sj}")
    try:
        lines = [json.loads(l) for l in sj.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    except ValueError as e:   # json.JSONDecodeError ⊂ ValueError：坏行不冒裸 traceback
        raise click.ClickException(f"session.jsonl 解析失败: {e}")
    name = name or sd.name
    flow, removed = session_to_flow(lines, name=name, keep_fragile=keep_fragile)
    out_path = pathlib.Path(out) if out else pathlib.Path("flows") / f"{name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(flow, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    report = out_path.with_suffix(".report.md")
    rep = [f"# replay 报告 · {name}", "",
           f"- 转换步数：{len(flow['steps'])}",
           f"- 剔除步数：{len(removed)}"
           + ("（--keep-fragile：已保留在 steps，标注 fragile:true）"
              if keep_fragile else ""),
           ""]
    for r in removed:
        rep.append(f"- 步 {r['n']}：{r['reason']}（seq={r['action'].get('seq')}）")
    report.write_text("\n".join(rep) + "\n", encoding="utf-8")
    click.echo(f"flow: {out_path}")
    click.echo(f"报告: {report}（剔除 {len(removed)} 步）")
    try:
        load_flow(out_path)   # replay 产物必须能过 drive 的同一把尺子
    except FlowError as e:
        raise click.ClickException(f"转换产物未过 flow 校验: {e}")


if __name__ == "__main__":
    main()
