# tests/test_config.py
from pathlib import Path
from browser_recorder import config


def test_default_screenshot_policy_points():
    # click 截 before+after（before 由 scrolling-snapshot 提供真·点击前帧）；submit 同。
    p = config.DEFAULT_SCREENSHOT_POLICY
    assert p.points["click"] == ["before", "after"]
    assert p.points["submit"] == ["before", "after"]
    assert p.points["input"] == ["after"]
    assert p.points["scroll"] == []
    assert p.points["navigation"] == ["after"]
    assert p.points["hover"] == ["before"]


def test_load_screenshot_policy_none_returns_default():
    # 不传路径时加载内置最佳实践默认（defaults/screenshot_policy.yaml），
    # 其值应与 DEFAULT_SCREENSHOT_POLICY 一致。
    p = config.load_screenshot_policy(None)
    assert p.points == config.DEFAULT_SCREENSHOT_POLICY.points
    assert p.dedup_window_ms == config.DEFAULT_SCREENSHOT_POLICY.dedup_window_ms


def test_load_screenshot_policy_yaml_override(tmp_path):
    yml = tmp_path / "p.yaml"
    yml.write_text(
        "points:\n  click: [after]\n  input: [after]\n  scroll: []\n  navigation: [after]\n  hover: [before]\n"
        "  submit: [before, after]\n  keypress: [after]\n  select: [after]\n"
        "dedup_window_ms: 300\n"
        "input_aggregate_timeout_ms: 1200\n",
        encoding="utf-8",
    )
    p = config.load_screenshot_policy(yml)
    assert p.points["click"] == ["after"]
    assert p.dedup_window_ms == 300


def test_default_replay_policy():
    r = config.DEFAULT_REPLAY_POLICY
    assert r.after_action["default"] == 5000
    assert r.after_action["submit"] == 15000
    assert r.before_action["default"] == 500
    assert r.idle_for_visibility == 600
    assert r.settle_debounce_ms == 300


def test_replay_policy_pace_slow_doubles():
    r = config.load_replay_policy(None, pace="slow", overrides=None)
    assert r.before_action["default"] == 1000  # 500 * 2
    assert r.idle_for_visibility == 1200


def test_replay_policy_pace_faithful_keeps_values():
    r = config.load_replay_policy(None, pace="faithful", overrides=None)
    # faithful 不缩放固定停顿（仅 replay runner 用真实 ts）
    assert r.before_action["default"] == 500


def test_replay_policy_delay_override():
    r = config.load_replay_policy(None, pace=None, overrides=["click.before=200", "input.after=500"])
    assert r.before_action["click"] == 200
    assert r.after_action["input"] == 500


def test_replay_policy_does_not_mutate_default_constant():
    """override 不应污染 DEFAULT_REPLAY_POLICY（模块常量必须保持纯净）。"""
    orig_before_default = config.DEFAULT_REPLAY_POLICY.before_action["default"]
    config.load_replay_policy(None, pace=None, overrides=["default.before=999"])
    assert config.DEFAULT_REPLAY_POLICY.before_action["default"] == orig_before_default
    # 多次调用也不累积
    config.load_replay_policy(None, pace=None, overrides=["click.after=1"])
    config.load_replay_policy(None, pace=None, overrides=["click.after=2"])
    assert config.DEFAULT_REPLAY_POLICY.after_action["click"] == 5000


def test_default_request_filter_is_best_practice():
    """不传路径时返回内置最佳实践默认（非空、含静态/OPTIONS/304 等中性规则）。"""
    import re
    flt = config.load_request_filter(None)
    assert flt != {}                                  # 默认启用过滤
    assert "OPTIONS" in flt["exclude_methods"]
    assert 304 in flt["exclude_status"] and 204 in flt["exclude_status"]
    assert all(isinstance(p, re.Pattern) for p in flt["exclude_url_patterns"])
    # 平台中性：默认规则里不得出现任何具体 host/IP/路由
    blob = " ".join(p.pattern for p in flt["exclude_url_patterns"])
    for bad in ("easyops", "172.", "/next/", "toolId", "aksk"):
        assert bad not in blob, f"默认过滤规则混入非中性串: {bad}"


def test_load_request_filter_yaml_override(tmp_path: Path):
    """传 yaml 时完全覆盖默认规则。"""
    yml = tmp_path / "f.yaml"
    yml.write_text("exclude_status: [500]\nexclude_methods: [DELETE]\n", encoding="utf-8")
    flt = config.load_request_filter(yml)
    assert flt["exclude_status"] == {500}
    assert flt["exclude_methods"] == {"DELETE"}
    assert 304 not in flt["exclude_status"]          # 覆盖，不带默认
