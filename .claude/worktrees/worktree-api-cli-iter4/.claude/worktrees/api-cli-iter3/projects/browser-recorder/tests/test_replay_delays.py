# tests/test_replay_delays.py
from browser_recorder.replay.delays import DelayResolver
from browser_recorder.config import load_replay_policy, DEFAULT_REPLAY_POLICY


def test_before_resolves_by_type_with_default_fallback():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.before("click") == 300
    assert d.before("unknown") == 500  # default


def test_after_resolves_settle_timeout():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.after("submit") == 15000
    assert d.after("navigation") == 10000
    assert d.after("click") == 5000
    assert d.after("unknown") == 5000


def test_idle_constant():
    d = DelayResolver(DEFAULT_REPLAY_POLICY)
    assert d.idle() == 600


def test_resolver_uses_loaded_policy_with_overrides():
    p = load_replay_policy(None, pace=None, overrides=["submit.before=999"])
    d = DelayResolver(p)
    assert d.before("submit") == 999
