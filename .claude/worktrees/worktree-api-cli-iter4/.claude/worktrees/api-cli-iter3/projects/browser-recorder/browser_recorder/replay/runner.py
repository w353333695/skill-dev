# browser_recorder/replay/runner.py
"""replay 子命令：读 trace.jsonl，回放，可选录屏/转码/实时浮标。

平台中性：浏览器一律通过 ``browser_recorder.browser.launch`` 启动，
不裸调 ``pw.chromium.launch``。
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from .. import paths
from ..browser import launch, new_context
from ..models import Action
from ..config import load_replay_policy
from ..settle import _SETTLE_INJECT
from .delays import DelayResolver
from .executor import ReplayExecutor


async def _replay_async(trace_path, url, out_dir, profile, policy, video,
                        annotate_during, headless, replay_dir,
                        ignore_https_errors=False):
    from playwright.async_api import async_playwright
    from ..auth import store
    storage_state = None
    if profile:
        loaded = store.load_profile(out_dir, profile)
        if loaded:
            storage_state = loaded[1]
    actions = [Action.from_dict(json.loads(line))
               for line in trace_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    async with async_playwright() as pw:
        browser = await launch(pw, headless=headless)
        ctx_kwargs: dict = {}
        if video:
            # 视频直接落到 replay_dir 本身，避免拾取其他会话的 webm
            ctx_kwargs["record_video_dir"] = str(replay_dir)
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = await new_context(browser, ignore_https_errors=ignore_https_errors, **ctx_kwargs)
        page = await ctx.new_page()
        # settle DOM/CPU 上报脚本：必须在 goto 前注入一次，对所有导航生效
        await ctx.add_init_script(_SETTLE_INJECT)
        # 录视频时注入内联标记脚本，使视频也能标注每个动作位置（动作前 lead 闪现）
        if video:
            from ..marker import MARKER_INJECT
            await ctx.add_init_script(MARKER_INJECT)
        resolver = DelayResolver(policy)
        screenshots = replay_dir / "screenshots"
        ex = ReplayExecutor(page, resolver,
                            screenshot_dir=screenshots if annotate_during else None,
                            mark=video)
        await page.goto(url)
        stats = await ex.replay(actions)
        if video:
            await ctx.close()
        await browser.close()
        return stats


def run_replay(session, out_dir, profile, pace, delay_overrides, policy_path,
               video, video_format, annotate_during_replay, name, headless=False,
               tmp_root=None, ignore_https_errors=False, video_width=None) -> Path:
    """回放入口：返回 replay_dir。session 是 session_id 或 name。"""
    out_dir = Path(out_dir) if not isinstance(out_dir, Path) else out_dir
    # session 解析：name 或 session_id
    old_tmp = paths.TMP_ROOT
    if tmp_root is not None:
        paths.TMP_ROOT = Path(tmp_root)
    try:
        trace_path = paths.session_dir(session) / "trace.jsonl"
        meta_path = paths.session_dir(session) / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"url": ""}
        replay_id = name or paths.new_session_id()
        replay_dir = paths.session_dir(replay_id)
        replay_dir.mkdir(parents=True, exist_ok=True)
        policy = load_replay_policy(policy_path, pace, delay_overrides)
        asyncio.run(_replay_async(trace_path, meta.get("url", "about:blank"), out_dir, profile,
                                  policy, video, annotate_during_replay, headless, replay_dir,
                                  ignore_https_errors=ignore_https_errors))
        # 可选转码：webm 与 video.mp4 都落在 replay_dir 自身（不再写到父目录）
        if video and video_format == "mp4":
            from ..export.transcode import to_mp4
            webm = _find_webm(replay_dir)
            if webm:
                to_mp4(webm, replay_dir / "video.mp4", width=video_width)
        return replay_dir
    finally:
        paths.TMP_ROOT = old_tmp


def _find_webm(d: Path):
    """只在指定目录内搜 webm（不递归到兄弟会话目录，避免拾取他人 webm）。"""
    for f in d.glob("*.webm"):
        return f
    return None
