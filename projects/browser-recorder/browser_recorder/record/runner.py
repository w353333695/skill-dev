# browser_recorder/record/runner.py
"""record 子命令主流程：启浏览器、加载 auth、注入钩子、收事件、产 jsonl + 截图。

平台中性：浏览器一律通过 ``browser_recorder.browser.launch`` 启动（自动用
完整 chrome 兜底），不裸调 ``pw.chromium.launch``；不耦合任何特定系统。
"""
from __future__ import annotations
import asyncio
import collections
import json
import logging
import shutil
import time
from pathlib import Path
from .. import paths
from ..browser import launch, new_context
from ..config import load_screenshot_policy
from ..settle import _SETTLE_INJECT, wait_for_settled
from ..auth import scope as auth_scope
from .injector import INJECT_SCRIPT
from .capture import EventToAction, NetworkCollector
from .screenshot import ScreenshotPlanner

logger = logging.getLogger(__name__)


async def _wait_render_settled(page, timeout_ms: int, *, poll_ms: int = 50) -> None:
    """等页面渲染稳定后再截图，避免截到导航/重渲染中的白屏。

    复用 ``_SETTLE_INJECT`` 已注入的 ``__br_dom_idle`` / ``__br_cpu_idle`` 标志
    （DOM MutationObserver 静默 + requestIdleCallback 双信号），轮询至两者皆真，
    或超时兜底退出。不注册额外网络监听器（截图只关心"DOM 还在不在变"，与
    ``settle.wait_for_settled`` 的三信号网络判定不同，故不复用以免监听器累积）。

    附带：在 timeout 预算内等 ``document.fonts.ready``（带兜底），避免 Playwright
    ``page.screenshot()`` 内部因 webfont 加载不出（内网站点常见）而卡满超时。
    fonts.ready 不支持超时参数，故用整体 deadline 包裹，超时即放弃等待。
    """
    # 先等字体（最多占用一半预算，剩下一半留给 DOM/CPU 稳定判定）
    font_budget = max(poll_ms, timeout_ms // 2) / 1000.0
    font_deadline = time.monotonic() + font_budget
    while time.monotonic() < font_deadline:
        try:
            ready = await page.evaluate(
                "() => (document.fonts && document.fonts.status) === 'loaded'")
        except Exception:
            ready = True  # 页面正导航/无 fonts API → 不阻塞，交由 DOM 信号兜底
        if ready:
            break
        await page.wait_for_timeout(poll_ms)

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        try:
            info = await page.evaluate(
                "() => ({dom: window.__br_dom_idle === true, cpu: window.__br_cpu_idle === true})")
        except Exception:
            # 页面正导航/卸载中，evaluate 失败 → 等下一拍再试
            info = {}
        if info.get("dom") and info.get("cpu"):
            return
        await page.wait_for_timeout(poll_ms)


def _scope_from_url(url: str) -> dict:
    """从目标 URL 派生 auth.scope（registrable_domain + hosts + scheme）。

    用于交互式登录后保存 profile。平台中性：仅基于 URL 解析，不耦合任何系统。
    """
    u = auth_scope.parse_url(url)
    reg = auth_scope.registrable_domain(u.host) if u.host else ""
    scheme = [u.scheme] if u.scheme else ["https"]
    return {
        "scheme": scheme,
        "registrable_domain": reg,
        "hosts": [u.host] if u.host else [],
        "host_match": "suffix",
        "path_prefix": ["/"],
        "ports": [u.port],
    }


async def _interactive_login(pw, url, headless, ignore_https_errors=False):
    """启动临时浏览器让用户登录，回车后抓 storage_state。

    headless=True 时（如烟测）不等待 input，直接返回 None（当匿名录制处理）。
    平台中性：纯 Playwright + 标准输入，不耦合任何系统/鉴权细节。
    """
    from playwright.async_api import async_playwright  # noqa: F401
    browser = await launch(pw, headless=headless)
    try:
        ctx = await new_context(browser, ignore_https_errors=ignore_https_errors)
        page = await ctx.new_page()
        try:
            await page.goto(url)
        except Exception:
            pass
        if headless:
            # 无头环境无法人工登录，直接返回 None（按匿名录制）
            return None
        # 有头模式：阻塞等用户在终端回车
        input(f"[record] 请在浏览器中完成登录（目标：{url}），然后回到终端按回车继续...")
        state = await ctx.storage_state()
        await ctx.close()
        return state
    finally:
        await browser.close()


async def _record_async(url, session_dir, out_dir, profile, keep_auth,
                        screenshot_policy_path, video, name, headless, auto_actions,
                        keep_raw_bodies=False, ignore_https_errors=False,
                        record_timeout_s: float = 600.0, interactive_only: bool = False):
    from playwright.async_api import async_playwright
    from ..auth import store

    planner = ScreenshotPlanner(load_screenshot_policy(screenshot_policy_path))
    e2a = EventToAction(planner)

    storage_state = None
    if profile:
        loaded = store.load_profile(out_dir, profile)
        missing_or_expired = (loaded is None
                              or store.is_expired(loaded[0], time.time()))
        if missing_or_expired and not headless:
            # spec §4.3：profile 缺失/过期 → 临时浏览器让用户登录、回车后
            # 抓 storage_state 存入 profile，再正式录制（仅 headless=False）
            print(f"[record] profile '{profile}' 缺失/过期，启动登录窗口...")
            async with async_playwright() as lpw:
                state = await _interactive_login(lpw, url, headless=headless,
                                                 ignore_https_errors=ignore_https_errors)
            if state is not None:
                store.save_profile(
                    out_dir, profile, state,
                    scope=_scope_from_url(url),
                    expires_in_days=7, now_ts=time.time())
                storage_state = state
        elif loaded:
            storage_state = loaded[1]

    trace_path = session_dir / "trace.jsonl"
    req_path = session_dir / "requests.jsonl"
    screenshots = session_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    current_seq_box = {"v": None}
    # scrolling-snapshot 缓冲：(ts_ms, png_bytes) 环形，供 click 取"点击前"帧
    _snapshot_buffer = collections.deque(maxlen=4)

    def _sink_action(a):
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
        current_seq_box["v"] = a.seq

    def _sink_request(r):
        with open(req_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    async with async_playwright() as pw:
        browser = await launch(pw, headless=headless)
        ctx_kwargs: dict = {}
        if video:
            ctx_kwargs["record_video_dir"] = str(session_dir)
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = await new_context(browser, ignore_https_errors=ignore_https_errors, **ctx_kwargs)
        page = await ctx.new_page()

        async def _capture_for_action(a) -> None:
            """按截图策略为 Action 产 before/after 原图，回填 a.screenshot。

            文件名 ``step-{seq:04d}-{before|after}.png``，与 export 侧读取的
            ``screenshot['before'/'after']`` 及 executor 失败截图命名风格一致。
            事件回调在动作发生后触发，"before" 实际捕获的是事件瞬间的页面快照
            （spec §5.2 已说明事件已发生，before 不可得）；"after" 在等渲染稳定后截，
            捕获异步副作用（如 XHR 返回后渲染）。

            关键：截图前用 ``_wait_render_settled`` 等 DOM 渲染完成，避免截到导航/
            重渲染中的白屏（spec §5.2：before 短等保当前帧，after 长等覆盖异步渲染）。

            容错：截图全程 try/except。本回调经 ``ensure_future`` 派发为独立 Task，
            若截图抛异常（如 Playwright 截图等 ``document.fonts.ready`` 时遇到加载
            不出的 webfont，内网站点常见 → 卡满超时）而无人 await，会变成
            "Task exception was never retrieved" 并使后续截图持续失败、录制僵死。
            故任一截图点失败仅跳过该图、不影响动作落库与后续录制。
            """
            points = planner.should_capture({"type": a.type})
            if not points:
                return
            # 录视频时：先清掉上一步常驻的内联标记，保证本步截图干净
            if video:
                from ..marker import clear_marker
                await clear_marker(page)
            shots: dict[str, str] = {}
            for pt in points:
                try:
                    if pt == "after":
                        # after 等渲染稳定。click/submit 用三信号 settle（网络+DOM+CPU）：
                        # 这类动作常触发弹层（如 launchpad）异步加载内容，仅等 DOM/CPU 会截到
                        # 内容未加载的白屏（用户报「截图白屏」）。三信号 settle 会等到 XHR 返回、
                        # DOM 渲染完再截。settle 自带监听器清理，可安全每动作调用。
                        # 其它动作（input/navigation 等）用 _wait_render_settled（DOM/CPU）即可。
                        if a.type in ("click", "submit"):
                            await wait_for_settled(page, timeout_ms=3000, debounce_ms=300)
                        else:
                            await _wait_render_settled(page, timeout_ms=2500)
                    else:
                        # before（scrolling-snapshot）：从后台缓冲取【点击前】最近帧——
                        # _on_event 在 JS handler 后执行，直接截是 click 后帧（导航白屏）；
                        # 后台 _snapshot_loop 持续截图，取 emit 之前最近帧=真点击前画面。
                        prev_png = _pick_pre_click_snapshot(_snapshot_buffer, a.ts)
                        if prev_png is None:
                            continue  # 缓冲空（录制刚开始）→ 跳过 before
                        fn = f"step-{a.seq:04d}-before.png"
                        (screenshots / fn).write_bytes(prev_png)
                        shots[pt] = fn
                        continue  # before 已从缓冲写，跳过下方 page.screenshot
                    fn = f"step-{a.seq:04d}-{pt}.png"
                    # timeout：截图本身限 5s，避免 Playwright 默认等 fonts.ready 卡 30s
                    await page.screenshot(path=str(screenshots / fn), timeout=5000)
                    shots[pt] = fn
                except Exception as e:
                    # 该 pt 的 settle/截图失败（导航中 page 关闭等）→ 跳过此 pt，不阻断
                    # 同次其它 pt 回填（如 click 的 before 已成功时仍回填，避免整条
                    # action 因 after 失败而丢全部截图）。
                    logger.warning("截图失败（%s/%s）: %s", a.seq, pt, e)
                    continue
            if shots:
                a.screenshot = shots
            # 录视频时：截图后再闪现内联标记（事件在 capture 阶段才到，无法真正 lead，
            # 这里做「近瞬时」标注，常驻到下一步 clear），使视频也能标注动作位置。
            if video and a.target and a.target.bbox:
                from ..marker import flash_marker
                await flash_marker(page, a.target.bbox, a.seq, a.type)

        async def _on_event(ev: dict):
            # page.url 在导航中可能抛错（execution context destroyed）→ 容错取空串
            try:
                url = page.url
            except Exception:
                url = ""
            page_info = {"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0}
            try:
                a = e2a.process(ev, url=url, page_info=page_info)
            except Exception as e:
                logger.warning("事件处理失败（type=%s）: %s", ev.get("type"), e)
                return
            # 截图与落库分离：截图抛错（导航中常见）不应丢失 action。emit_actions
            # 内部隔离截图异常，落库无条件执行。
            acts = ([a] if a else []) + e2a.drain_pending()
            await emit_actions(acts, _capture_for_action, _sink_action)

        # expose_function 传 lambda → 把 async 回调派发为 Task，使 _on_event 真正执行
        await page.expose_function("__br_emit", lambda ev: asyncio.ensure_future(_on_event(ev)))
        # __br_flush：beforeunload 时让挂起的输入聚合收尾（spec §5.3.1）
        await page.expose_function("__br_flush",
                                   lambda: asyncio.ensure_future(_on_event({"type": "input_finalize", "ts": int(time.time() * 1000)})))
        # __br_stop：页面侧按 Ctrl/Cmd+Shift+X 结束录制 → set 事件，主循环退出。
        # 与 __br_flush 同风格（同步 lambda 包 ensure_future），保持 expose_function 行为一致。
        stop_event = asyncio.Event()
        await page.expose_function("__br_stop",
                                   lambda: stop_event.set() or None)
        # 关闭浏览器/页面 = 结束录制（兜底，与快捷键等价）
        def _on_close():
            stop_event.set()
        page.on("close", _on_close)
        browser.on("disconnected", _on_close)
        # 注入钩子 + settle DOM/CPU 上报脚本（必须在 goto 前，对所有导航生效）
        await ctx.add_init_script(INJECT_SCRIPT)
        await ctx.add_init_script(_SETTLE_INJECT)
        # 录视频时注入内联标记脚本，使视频也能标注动作位置（截图后近瞬时闪现）
        if video:
            from ..marker import MARKER_INJECT
            await ctx.add_init_script(MARKER_INJECT)
        # --interactive-only：关闭空白点击兜底，恢复「点纯空白丢弃」的旧行为。
        # 新默认（不传）= 全捕：先取最小可点击元素，无果时兜底记最深有盒节点。
        if interactive_only:
            await ctx.add_init_script("window.__br_interactive_only = true;")

        nc = NetworkCollector(page, _sink_request, session_dir / "responses",
                              current_action_seq=lambda: current_seq_box["v"],
                              keep_raw_bodies=keep_raw_bodies)
        nc.attach()

        # wait_until="domcontentloaded"：只等 DOM 解析完即继续，不等"load"事件。
        # 后者要等所有资源（含字体/图片/第三方脚本）加载完，内网站点常有加载不出的
        # 外链资源（如埋点/字体 CDN 不可达）→ load 永不触发 → goto 卡满 30s 超时。
        # 与 replay/executor.py 的导航策略保持一致。
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            # 极端情况（连 DOM 都没解析完）兜底：记录后继续，页面可能已部分可交互
            logger.warning("goto 超时/失败（%s），尝试继续录制: %s", url, e)
        # scrolling-snapshot：后台每 ~300ms 截图入 _snapshot_buffer。click emit 时
        # _capture_for_action 从中取【emit 之前最近帧】作为真·点击前截图（_on_event 在
        # JS handler 后执行，直接截只会拿到 click 后的白屏/跳转后画面）。
        async def _snapshot_loop():
            while not stop_event.is_set():
                try:
                    png = await page.screenshot(timeout=2000)
                    _snapshot_buffer.append((int(time.time() * 1000), png))
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.3)
                except asyncio.TimeoutError:
                    pass
        snapshot_task = asyncio.ensure_future(_snapshot_loop())
        # auto_actions 模式：等 scrolling-snapshot 截首帧（否则首个 click 无点击前截图；
        # 人工 headed 无需等，用户操作慢，loop 早已有帧）
        if auto_actions:
            try:
                await page.wait_for_timeout(500)
            except Exception:
                pass
        # auto_actions（烟测用）：执行若干点击
        for act_type, sel in (auto_actions or []):
            try:
                if act_type == "click":
                    await page.click(sel, timeout=3000)
                await page.wait_for_timeout(800)
            except Exception:
                pass
        if not auto_actions and not headless:
            # 有头人工录制：等到「快捷键 Ctrl/Cmd+Shift+X」或「关闭浏览器/页面」
            # 触发 stop_event；record_timeout_s 为兜底防挂死（默认 10 分钟）。
            # 不再用固定 10s——那会在用户还没操作完就强行收尾。
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=record_timeout_s)
            except asyncio.TimeoutError:
                pass
        # headless + 无 auto_actions：goto 完即收尾。headless 下无人按快捷键、
        # 也无人关浏览器，等 stop_event 必然空等满兜底超时（曾导致烟测/自签 HTTPS
        # 用例卡死 10 分钟）。需要 headless 定时录制时，显式传 auto_actions 或由
        # 调用方自行控制会话时长。

        # 停止 scrolling-snapshot 后台 loop。CancelledError 在 3.8+ 继承 BaseException，
        # except Exception 捕获不到，需显式列出，否则冒泡中断收尾。
        snapshot_task.cancel()
        try:
            await snapshot_task
        except (asyncio.CancelledError, Exception):
            pass

        # 给悬挂中的 response Task（async body()）流出收尾时间，避免丢失 schema。
        # 用户直接关浏览器时 page 可能已关闭 → 全程容错，不让收尾抛错。
        try:
            await page.wait_for_timeout(500)
        except Exception:
            pass

        # 收尾兜底：从 Python 侧显式 flush 挂起的输入。页面侧 __br_flush
        # （beforeunload/快捷键）是异步派发的，浏览器关得快时该 Task 可能未完成 →
        # 最后一段未失焦的输入丢失（"输入没捕获"）。此处幂等兜底（无挂起则 no-op）。
        try:
            final = e2a.flush_pending(page.url, {"viewport": [1280, 720], "scroll_x": 0, "scroll_y": 0},
                                      int(time.time() * 1000))
            if final:
                try:
                    await _capture_for_action(final)
                except Exception as e:
                    logger.warning("收尾截图失败（seq=%s）: %s", final.seq, e)
                _sink_action(final)
        except Exception as e:
            logger.warning("收尾 flush 挂起输入失败: %s", e)

        # 视频落盘 + 关闭。用户已关浏览器时这些是 no-op（异常吞掉）。
        if video:
            try:
                await ctx.close()  # 触发视频落盘
            except Exception:
                pass
        try:
            await browser.close()
        except Exception:
            pass


def _pick_pre_click_snapshot(buffer, emit_ts: int):
    """从滚动截图缓冲取 emit 时间戳【之前】最近的一帧（真·点击前画面）。

    buffer: ``[(ts_ms, png_bytes), ...]`` 按 ts 升序。``emit_ts`` 时刻的帧不算
    （可能已含点击副作用）。返回 png_bytes 或 None（无前帧）。

    解决：录制被动监听，``_on_event`` 在 JS click handler 之后执行，直接截图拿到
    的是 click 后帧（导航中白屏）。改为后台 ``_snapshot_loop`` 持续截图入缓冲，
    click emit 时取 emit 之前最近帧——那才是用户点击时屏幕上的画面。
    """
    prev = None
    for ts, png in buffer:
        if ts < emit_ts:
            prev = png
        else:
            break
    return prev


async def emit_actions(actions, capture_fn, sink_fn) -> None:
    """逐个截图并落库 action；截图抛错不阻断落库。

    点击触发导航（如登录提交）时，``capture_fn`` 内的 settle/screenshot 在导航中
    会抛错（execution context destroyed）。若 sink 紧随 capture 且被同一 try 包裹，
    整条 action 丢失（用户报「step-0006 后面一个点击登陆没有捕获到」——登录 click
    触发导航，截图抛错把 click 一起吞了）。故截图 try/except 隔离，落库无条件执行
    （截图失败时 action.screenshot 为空，但 action 不丢）。
    """
    for act in actions:
        try:
            await capture_fn(act)
        except Exception as e:
            logger.warning("截图失败（seq=%s type=%s）: %s", act.seq, act.type, e)
        sink_fn(act)


def clear_stale_artifacts(session_dir: Path) -> None:
    """复用同名 session 时清空旧产物，避免 trace/requests 以 append 模式叠加（双录）。

    Bug：同名 session 二次录制时，trace.jsonl/requests.jsonl 以 ``"a"`` 打开不清空 →
    两次录制的 action 共享同名 ``step-XXXX-after.png`` → export 在一张图上画多个
    序号/框（用户报「一个点击框两个序号」）。清除：trace.jsonl、requests.jsonl、
    screenshots/、responses/。meta.json 由 run_record 覆盖写、视频由 ctx.close 落盘，
    无需在此处理。
    """
    for name in ("trace.jsonl", "requests.jsonl"):
        p = session_dir / name
        if p.exists():
            p.unlink()
    for sub in ("screenshots", "responses"):
        d = session_dir / sub
        if d.exists():
            shutil.rmtree(d)


def run_record(url, out_dir, profile, keep_auth, screenshot_policy_path,
               video, name, headless=False, auto_actions=None,
               keep_raw_bodies=False, ignore_https_errors=False,
               record_timeout_s: float = 600.0, interactive_only: bool = False) -> Path:
    """录制入口：返回 session_dir。``out_dir`` 为 Path 或 str。"""
    out_dir = Path(out_dir) if not isinstance(out_dir, Path) else out_dir
    session_id = name or paths.new_session_id()
    session_dir = paths.session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    clear_stale_artifacts(session_dir)  # 复用同名 session：清旧 trace/screenshots，防双录
    meta = {"url": url, "started_at": time.time(), "profile": profile,
            "keep_auth": keep_auth, "video": video, "session_id": session_id}
    (session_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    asyncio.run(_record_async(url, session_dir, out_dir, profile, keep_auth,
                              screenshot_policy_path, video, name, headless, auto_actions,
                              keep_raw_bodies=keep_raw_bodies,
                              ignore_https_errors=ignore_https_errors,
                              record_timeout_s=record_timeout_s,
                              interactive_only=interactive_only))
    return session_dir
