# browser_recorder/record/capture.py
"""CDP/Playwright 事件捕获：网络请求采集 + 静态过滤；事件→Action 转换（聚合/去重）。"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Callable, TYPE_CHECKING
from ..models import Action, RequestRecord, Target
from ..selectors import build_target_from_dom, target_fingerprint
from ..response_schema import parse as parse_response
from .screenshot import ScreenshotPlanner

if TYPE_CHECKING:
    from playwright.async_api import Page, Request, Response

_STATIC_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".gif",
                    ".woff", ".woff2", ".ttf", ".ico", ".map", ".webp")
_STATIC_TYPES = {"image", "font", "stylesheet", "media", "manifest"}
_RAW_THRESHOLD = 1_048_576  # 1 MiB：响应原始体超过此阈值则落盘

logger = logging.getLogger(__name__)


def _same_position(a: Target, b: Target) -> bool:
    """同一位置判定（用于「连续同位置点击」去重）：bbox 完全相同，或非退化指纹相同。

    bbox 完全相同 → 同位置（同元素连点，或不同元素恰好重叠）；
    否则比较指纹（含 null-selector 的 bbox 兜底）——退化指纹 ``tag:|text:`` 不算。
    """
    if a.bbox and b.bbox and a.bbox == b.bbox:
        return True
    fpa, fpb = target_fingerprint(a), target_fingerprint(b)
    return bool(fpa) and fpa == fpb and fpa != "tag:|text:"


def is_static(url: str, resource_type: str) -> bool:
    """纯函数判定静态资源：data:/blob: 前缀、ResourceType、后缀三重判定。"""
    u = (url or "").lower().split("?", 1)[0]
    if u.startswith(("data:", "blob:")):
        return True
    rt = (resource_type or "").lower()
    if rt in _STATIC_TYPES:
        return True
    return u.endswith(_STATIC_SUFFIXES)


class EventToAction:
    """注入事件 → Action（含输入聚合、去重）。

    输入聚合自管：input 事件的 value 是目标字段的全量快照（与浏览器原生
    ``input`` 事件一致），连续覆盖累积；input_finalize（focusout/blur）触发
    落库，最终 value 取最后一次快照。与 ScreenshotPlanner 仅共享 is_duplicate
    去重判定，不复用其输入聚合缓冲（避免双份状态）。
    """

    # click+submit 合并窗口（ms）：点击提交按钮会依次触发 click(button)+submit(form)，
    # 窗口内的 submit 视为同一次表单提交、丢弃（保留 click，其 bbox 是按钮更准）。
    # 通用 DOM 行为，不耦合任何系统。
    CLICK_SUBMIT_COALESCE_MS = 800

    def __init__(self, planner: ScreenshotPlanner):
        self.planner = planner
        self._seq = 0
        self._input_node: dict | None = None
        self._input_value: str = ""
        self._pending: list[Action] = []
        self._last_click_ts: int | None = None   # 用于 submit 合并判定
        self._last_click_target: Target | None = None  # 用于「连续同位置点击」去重

    def _flush_input(self, url: str, page_info: dict, ts: int) -> Action | None:
        """结束当前输入聚合，产出一条 input Action；无挂起输入时返回 None。"""
        if self._input_node is None:
            return None
        node = self._input_node
        value = self._input_value
        self._input_node = None
        self._input_value = ""
        self._last_click_target = None  # 输入动作打断「连续同位置点击」
        if value == "":
            # 空输入（focus/JS 置空，从未有实际内容）不落库——避免 launchpad 搜索框等
            # 初始空 input 生成无意义白屏步骤（用户报 step-0010 白屏应并入下一步）。
            return None
        self._seq += 1
        return Action(
            seq=self._seq, ts=ts, type="input", url=url,
            target=build_target_from_dom(node), value=value, page_info=page_info,
        )

    def flush_pending(self, url: str, page_info: dict, ts: int) -> Action | None:
        """显式收尾 flush 挂起的输入。

        录制结束时页面侧 ``__br_flush``（beforeunload/快捷键）是异步派发的，若浏览器
        关闭得快，该 Task 可能未完成 → 最后一段未失焦的输入丢失。runner 在收尾阶段
        调本方法从 Python 侧同步兜底 flush（``_flush_input`` 幂等：无挂起返回 None）。
        """
        return self._flush_input(url, page_info, ts)

    def process(self, event: dict, url: str, page_info: dict) -> Action | None:
        """返回应落库的 Action 或 None（被去重 / 聚合中）。

        若一次 process 同时产生「flush 的 input」与「新 action」，前者作为
        返回值，后者入 ``_pending``，由调用方 ``drain_pending`` 取出。
        """
        t = event.get("type")
        ts = event.get("ts", 0)
        node = event.get("target_node") or {}
        value = event.get("value")

        # 输入聚合（value 为字段全量快照，连续覆盖）
        if t == "input":
            if self._input_node is None or node.get("css") != (self._input_node or {}).get("css"):
                # 切换元素：先 flush 上一段，再开启新一段（新段不立即产出）
                flushed = None
                if self._input_node is not None:
                    flushed = self._flush_input(url, page_info, ts)
                self._input_node = node
                self._input_value = value or ""
                return flushed
            self._input_value = value or self._input_value
            return None
        if t == "input_finalize":
            if node.get("css") == (self._input_node or {}).get("css"):
                self._input_value = value or self._input_value
            return self._flush_input(url, page_info, ts)

        # 非 input 事件：先 flush 挂起的输入
        flushed = self._flush_input(url, page_info, ts) if self._input_node else None

        if t == "scroll":
            # scroll 默认不单独产 Action（截图点为空）；仅可能返回先 flush 的 input
            return flushed

        # click+submit 合并：点击提交按钮会先 click 后 submit，submit 的 target 是整张
        # form（bbox 大、标注不精准）。若 submit 紧跟一次 click，视为同一次表单提交，
        # 丢弃 submit（click 已记录该动作，且 bbox 是按钮）。
        if t == "submit" and self._last_click_ts is not None \
                and (ts - self._last_click_ts) <= self.CLICK_SUBMIT_COALESCE_MS:
            self._last_click_ts = None   # 消费掉，避免后续误合并
            return flushed

        # click / select / keypress / hover / navigation：去重
        target = build_target_from_dom(node)
        fp = target_fingerprint(target)
        # 连续点击同一位置（无视时间间隔，间隔数秒也丢）→ 丢弃，清理无效重复点击。
        # 仅当上一个落库动作是 click 且本 click 与之同位置；中间任何输入/导航等动作
        # 会经 _flush_input 或下方 else 分支把 _last_click_target 置 None，从而打断。
        if t == "click" and self._last_click_target is not None \
                and _same_position(target, self._last_click_target):
            return flushed
        if self.planner.is_duplicate(t, fp, ts):
            # 去重也要刷新 click 时间戳（连点同一按钮，submit 仍应合并到最近一次）
            if t == "click":
                self._last_click_ts = ts
            return flushed  # 去重，但仍可能返回先 flush 的 input
        self._seq += 1
        action = Action(
            seq=self._seq, ts=ts, type=t, url=url,
            target=target, value=value, page_info=page_info,
        )
        if t == "click":
            self._last_click_ts = ts   # 记录最近 click，供后续 submit 合并
            self._last_click_target = target
        else:
            self._last_click_target = None   # 非 click 动作打断「连续同位置」
        if flushed:
            # flush 的 input 优先返回；新 action 暂存，由 drain_pending 取出
            self._pending.append(action)
            return flushed
        return action

    def drain_pending(self) -> list[Action]:
        """取回并清空 process 期间累积的额外 Action（flush input + 新 action 边界）。"""
        out = self._pending
        self._pending = []
        return out


class NetworkCollector:
    """订阅 page 请求/响应事件，过滤静态，流式写 requests.jsonl。

    状态按 ``id(req)`` 维护：request 事件登记，response 事件取出并装配
    RequestRecord（含响应体解析 + 大体落盘）后回调 sink。
    """

    def __init__(self, page: "Page", sink: Callable[[RequestRecord], None],
                 responses_dir: Path, current_action_seq: "Callable[[], int | None]",
                 keep_raw_bodies: bool = False):
        self.page = page
        self.sink = sink
        self.responses_dir = responses_dir
        self.current_action_seq = current_action_seq
        self.keep_raw_bodies = keep_raw_bodies
        self._state: dict[str, dict] = {}  # id(req) -> {url, method, headers, post_data, req_type, ts}

    def attach(self) -> None:
        """绑定 page 的 request / response 事件。

        response 事件需 await ``resp.body()``（async_api 的 body() 返回协程），
        所以 ``_on_response`` 是 async，并通过 ``ensure_future`` 派发——
        不如此处理则未 await 的协程会被下面的 except 吞掉，
        ``response.schema`` 永远为空。
        """
        self.page.on("request", self._on_request)
        self.page.on("response", lambda r: asyncio.ensure_future(self._on_response(r)))

    def _on_request(self, req: "Request") -> None:
        try:
            if is_static(req.url, req.resource_type):
                return
            self._state[id(req)] = {
                "url": req.url, "method": req.method,
                "headers": dict(req.headers),
                "post_data": req.post_data,
                "req_type": req.resource_type,
                "ts": int(time.time() * 1000),
            }
        except Exception as e:
            logger.debug("NetworkCollector._on_request 失败（%s %s）: %s",
                         getattr(req, "method", "?"), getattr(req, "url", "?"), e)

    async def _on_response(self, resp: "Response") -> None:
        try:
            req = resp.request
            key = id(req)
            st = self._state.pop(key, None)
            if st is None:
                # request 事件未登记（如静态过滤漏网或事件丢失），二次校验
                if is_static(req.url, req.resource_type):
                    return
                st = {"url": req.url, "method": req.method, "headers": dict(req.headers),
                      "post_data": req.post_data, "req_type": req.resource_type, "ts": 0}
            # 关键：async_api 下 body() 返回协程，必须 await。
            body = b""
            try:
                body = await resp.body()
            except Exception as e:
                logger.debug("resp.body() 失败（%s）: %s", st.get("url", "?"), e)
            mime = resp.headers.get("content-type", "").split(";")[0].strip()
            ri = parse_response(body, mime)
            # 落盘判定：超阈值 OR --keep-raw-bodies（强制全落盘，spec §6.3）
            should_persist = bool(body) and (
                ri.raw_size > _RAW_THRESHOLD or self.keep_raw_bodies
            )
            if should_persist:
                self.responses_dir.mkdir(parents=True, exist_ok=True)
                fn = hashlib.sha256(st["url"].encode()).hexdigest()[:16] + ".bin"
                (self.responses_dir / fn).write_bytes(body)
                ri.raw_ref = f"responses/{fn}"
            rec = RequestRecord(
                req_id=hex(key), ts=st["ts"], method=st["method"], url=st["url"],
                headers=st["headers"], post_data=st.get("post_data"),
                status=resp.status, response_headers=dict(resp.headers), mime=mime,
                response=ri, duration_ms=None,
                linked_action_seq=self.current_action_seq(),
            )
            self.sink(rec)
        except Exception as e:
            logger.debug("NetworkCollector._on_response 失败: %s", e)
