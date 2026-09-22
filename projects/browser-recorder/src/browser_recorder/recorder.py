"""录制主循环：SessionHarness 会话壳 + 三层停止协调 + 录制收尾判定。

会话基座（起浏览器→挂域→注入→双截图→稳定等待）在 harness.SessionHarness——
record/drive/probe 三模态共用；本模块只保留录制模态专属的部分：三层停止
（页面热键 / 关浏览器 / 终端 q）、abnormal / io_error 判定、冲刷与
session_end 收尾、Ctrl-C 优雅退出。
"""
from __future__ import annotations

import asyncio
import pathlib
import subprocess

from .harness import SessionHarness, _wait_browser_closed, _wait_terminal_q

__all__ = ["record"]


async def record(
    out_dir: pathlib.Path,
    start_url: str,
    chrome_path: pathlib.Path,
    settle_timeout: float = 30.0,
    port: int | None = None,
    headless: bool = False,
    extra_chrome_args: list[str] | None = None,
    profile: str | None = None,
) -> dict:
    """完成一次录制到停止。返回 {"events", "out_dir", "abnormal", "stop_reason"}。

    stop_reason ∈ {"hotkey", "browser_closed", "terminal_q", "io_error", "interrupt"}；
    abnormal 仅在 browser_closed 且退出码非 0（崩溃/被杀）时为 True。
    extra_chrome_args：追加的浏览器启动参数（容器/受限环境传 ["--no-sandbox"]）。
    多 tab：新开的 page target 自动跟随（事件带 target_id 区分来源 tab）。
    profile：命名持久 profile（~/.browser-recorder/profiles/<名字>）——登录态
    （cookie/localStorage）跨录制存活，免去反复登录。None=一次性（默认）。
    """
    h = SessionHarness(out_dir, start_url, chrome_path, settle_timeout=settle_timeout,
                       port=port, headless=headless,
                       extra_chrome_args=extra_chrome_args, profile=profile)
    finished = False  # 正常收尾（session_end 已 emit）标记；finally 据此补中断收尾
    try:
        async with h:
            # ---- 三层停止等待（页面热键 / 关浏览器 / 终端 q）----
            t_browser = asyncio.create_task(_wait_browser_closed(h.client))
            t_hotkey = asyncio.create_task(h.stop_event.wait())
            t_termq = asyncio.create_task(_wait_terminal_q())
            await asyncio.wait({t_browser, t_hotkey, t_termq},
                               return_when=asyncio.FIRST_COMPLETED)
            for t in (t_browser, t_hotkey, t_termq):
                t.cancel()
            stop_reason = "browser_closed"
            if h.hotkey_fired:
                stop_reason = "hotkey"
            elif (t_termq.done() and not t_termq.cancelled()
                  and t_termq.exception() is None and t_termq.result() == "q"):
                stop_reason = "terminal_q"

            # ws 关闭可能早于进程退出，给浏览器最多 2s 收尸再判 abnormal（崩溃/被杀 → 非 0）
            abnormal = False
            if stop_reason == "browser_closed":
                try:
                    await asyncio.to_thread(h.chrome.wait, 2)
                except subprocess.TimeoutExpired:
                    pass
                abnormal = h.chrome.poll() not in (None, 0)

            # 落盘 IO 致命升级为停止原因（action_loop 每轮 + 停止等待完成后双检）
            io_error = None
            if h.writer.fatal:
                stop_reason = "io_error"
                io_error = "session.jsonl 写入失败（磁盘满/目录被删？），录制中止"

            for t in h.body_tasks:
                t.cancel()
            # 冲刷各 tab 挂起中的输入聚合（Browser.close 不走页面 unload，
            # 未满 1.2s 聚合窗的最后一段输入会丢）
            await h.flush_inputs()
            await asyncio.sleep(0.15)  # 给 binding 上报回程留窗口
            await h.action_q.put(None)
            h.action_loop_task.cancel()
            end_payload = {"abnormal": abnormal, "stop_reason": stop_reason,
                           "tabs": [t.tid for t in h.tabs.values()]}
            if io_error:
                end_payload["error"] = io_error
            try:
                h.writer.emit("session_end", end_payload)
            except (OSError, ValueError):
                # 收尾 emit 也可能撞 IO 致命（文件已关/磁盘满）。不置 finished，
                # 但把停止原因改 io_error 后走 return——CLI 侧据 io_error 字段
                # 走 ClickException 分支提示用户，胜过裸异常冒泡。
                stop_reason = "io_error"
                io_error = io_error or "session.jsonl 写入失败（磁盘满/目录被删？），录制中止"
                h.copy_prompt()
                finished = True
                return {"events": h.writer.events, "out_dir": str(h.out_dir),
                        "abnormal": abnormal, "stop_reason": stop_reason,
                        "io_error": io_error}
            h.copy_prompt()
            finished = True

            return {"events": h.writer.events, "out_dir": str(h.out_dir),
                    "abnormal": abnormal, "stop_reason": stop_reason,
                    "io_error": io_error}
    finally:
        # Ctrl-C 优雅收尾：asyncio.run 收到 SIGINT 会 cancel 主协程（以
        # CancelledError 形态冒泡，except KeyboardInterrupt 在协程内不命中），
        # 故收尾统一放 finally——正常路径由 finished 标记跳过，中断/异常路径
        # 在此补 session_end(interrupt) + PROMPT.md（emit 亦 try 包住防二次异常）。
        # __aexit__（Browser.close 优雅链 + writer.close + terminate/kill 兜底）
        # 由 async with 语义保证执行。
        if not finished:
            h.mark_interrupted()
