# browser_recorder/config.py
"""配置：截图时机策略、回放间隔策略。

策略对象是纯数据，方便单测；加载函数负责合并默认值 + yaml + CLI 覆盖。
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class ScreenshotPolicy:
    points: dict[str, list[str]]      # 动作类型 -> ["before"]/["after"]/["before","after"]/[]
    dedup_window_ms: int = 500
    input_aggregate_timeout_ms: int = 1500


@dataclass
class ReplayPolicy:
    after_action: dict[str, int]      # type -> ms（settle 上限）；含 "default"
    before_action: dict[str, int]     # type -> ms（固定停顿）；含 "default"
    idle_for_visibility: int = 600
    settle_debounce_ms: int = 300


# 内置最佳实践默认 conf 的目录（用户未传 --screenshot-policy / --filter-requests
# 时加载这里的 yaml，便于拷贝、按需定制）。
DEFAULTS_DIR = Path(__file__).parent / "defaults"


DEFAULT_SCREENSHOT_POLICY = ScreenshotPolicy(
    points={
        # click 截 before+after：before 在 emit→handler 后立即截（_capture_for_action），
        # 抢在导航/异步渲染前——保留点击瞬间上下文（如 launchpad 菜单+被点项）；after
        # 等加载完。标注优先用 before（见 export._pick_shot），避免落在跳转后页面。
        "click": ["before", "after"],
        "submit": ["before", "after"],
        "input": ["after"],
        "select": ["after"],
        "keypress": ["after"],
        "scroll": [],
        "navigation": ["after"],
        "hover": ["before"],
    },
)

DEFAULT_REPLAY_POLICY = ReplayPolicy(
    after_action={"default": 5000, "click": 5000, "submit": 15000, "navigation": 10000},
    before_action={"default": 500, "click": 300, "input": 200, "submit": 1000},
    idle_for_visibility=600,
    settle_debounce_ms=300,
)


def load_screenshot_policy(path: Path | None) -> ScreenshotPolicy:
    """加载截图策略。``path`` 为 None 时用内置最佳实践默认（defaults/screenshot_policy.yaml，
    缺失/解析失败则回退到 DEFAULT_SCREENSHOT_POLICY）。"""
    src = path if path is not None else (DEFAULTS_DIR / "screenshot_policy.yaml")
    try:
        data = yaml.safe_load(Path(src).read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError):
        return DEFAULT_SCREENSHOT_POLICY
    points = {**DEFAULT_SCREENSHOT_POLICY.points, **(data.get("points") or {})}
    return ScreenshotPolicy(
        points=points,
        dedup_window_ms=data.get("dedup_window_ms", DEFAULT_SCREENSHOT_POLICY.dedup_window_ms),
        input_aggregate_timeout_ms=data.get(
            "input_aggregate_timeout_ms", DEFAULT_SCREENSHOT_POLICY.input_aggregate_timeout_ms),
    )


# 内置最佳实践默认的请求过滤规则（与 defaults/filter_requests.yaml 等价的硬编码兜底，
# 便于无文件环境/单测直接引用；yaml 缺失时回退到此）。
DEFAULT_REQUEST_FILTER = {
    "exclude_url_patterns": [
        r"\.(js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|webp|map)(\?|$)",
        r"/sourcemap",
        r"/(sentry|beacon|track|log|report)",
        r"^wss?://",
        r"/(healthz|ping|version)$",
        r"/(fonts|icons)/",
    ],
    "exclude_methods": ["OPTIONS"],
    "exclude_status": [304, 204],
    "exclude_resource_types": ["ping", "beacon"],
}


def load_request_filter(path: Path | None) -> dict:
    """加载请求过滤规则，编译为可执行的 dict。

    ``path`` 为 None 时用内置最佳实践默认（defaults/filter_requests.yaml，缺失则回退
    DEFAULT_REQUEST_FILTER）：自动排除静态资源/埋点/长连接/心跳/OPTIONS/304/204 等
    无业务语义的请求，只保留有意义的接口。用户传 ``--filter-requests`` 则完全覆盖默认。

    返回结构（已编译）::

        exclude_url_patterns: list[re.Pattern]
        exclude_status: set[int]
        exclude_methods: set[str]          # 大写
        exclude_resource_types: set[str]   # 小写
    """
    import re
    src = path if path is not None else (DEFAULTS_DIR / "filter_requests.yaml")
    try:
        data = yaml.safe_load(Path(src).read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError):
        data = DEFAULT_REQUEST_FILTER
    return {
        "exclude_url_patterns": [re.compile(p) for p in (data.get("exclude_url_patterns") or [])],
        "exclude_status": set(data.get("exclude_status") or []),
        "exclude_methods": set((m.upper() for m in (data.get("exclude_methods") or []))),
        "exclude_resource_types": set((rt.lower() for rt in (data.get("exclude_resource_types") or []))),
    }


def _scale_fixed(policy: ReplayPolicy, factor: float) -> ReplayPolicy:
    return ReplayPolicy(
        after_action=policy.after_action,  # 不缩放
        before_action={k: int(v * factor) for k, v in policy.before_action.items()},
        idle_for_visibility=int(policy.idle_for_visibility * factor),
        settle_debounce_ms=policy.settle_debounce_ms,
    )


def _parse_ms(s: str) -> int:
    s = s.strip()
    for suffix, mult in [("ms", 1), ("s", 1000)]:
        if s.endswith(suffix):
            return int(float(s[: -len(suffix)]) * mult)
    return int(s)


def load_replay_policy(
    path: Path | None, pace: str | None, overrides: list[str] | None
) -> ReplayPolicy:
    if path is not None:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        delays = data.get("delays") or {}
        after = {**DEFAULT_REPLAY_POLICY.after_action,
                 **{k: _parse_ms(str(v)) for k, v in (delays.get("after_action") or {}).items()}
                 } if isinstance(delays.get("after_action"), dict) else dict(DEFAULT_REPLAY_POLICY.after_action)
        before = {**DEFAULT_REPLAY_POLICY.before_action,
                  **{k: _parse_ms(str(v)) for k, v in (delays.get("before_action") or {}).items()}
                  } if isinstance(delays.get("before_action"), dict) else dict(DEFAULT_REPLAY_POLICY.before_action)
        base = ReplayPolicy(
            after_action=after,
            before_action=before,
            idle_for_visibility=_parse_ms(str(delays.get("idle_for_visibility", DEFAULT_REPLAY_POLICY.idle_for_visibility))),
            settle_debounce_ms=int(data.get("settle_debounce_ms", DEFAULT_REPLAY_POLICY.settle_debounce_ms)),
        )
    else:
        # 关键：拷贝默认常量，避免后续 override 就地污染 DEFAULT_REPLAY_POLICY
        base = ReplayPolicy(
            after_action=dict(DEFAULT_REPLAY_POLICY.after_action),
            before_action=dict(DEFAULT_REPLAY_POLICY.before_action),
            idle_for_visibility=DEFAULT_REPLAY_POLICY.idle_for_visibility,
            settle_debounce_ms=DEFAULT_REPLAY_POLICY.settle_debounce_ms,
        )

    if pace == "slow":
        base = _scale_fixed(base, 2.0)
    # faithful / human 不缩放固定停顿；faithful 的真实间隔在 runner 里按 trace ts 处理

    if overrides:
        for ov in overrides:
            key, val = ov.split("=", 1)
            ftype, scope = key.split(".", 1)  # e.g. click.before / input.after
            if scope == "before":
                base.before_action[ftype] = _parse_ms(val)
            elif scope == "after":
                base.after_action[ftype] = _parse_ms(val)
            elif scope == "idle":
                base.idle_for_visibility = _parse_ms(val)
            else:
                raise ValueError(f"未知 delay scope: {scope}")
    return base
