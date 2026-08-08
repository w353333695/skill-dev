# tests/test_auth_store.py
import json
from pathlib import Path
from browser_recorder.auth import store
from browser_recorder import paths

NOW = 1722600000.0  # 固定 now，避免依赖系统时间


def _scope(host="example.com"):
    return {"scheme": ["https"], "registrable_domain": "example.com",
            "hosts": [host], "host_match": "suffix", "path_prefix": ["/"], "ports": [443, None]}


def test_save_and_load_profile(tmp_out_dir):
    meta = store.save_profile(
        tmp_out_dir, "demo",
        storage_state={"cookies": [], "origins": []}, scope=_scope(),
        expires_in_days=7, now_ts=NOW,
    )
    assert meta.name == "demo"
    pdir = paths.profile_dir(tmp_out_dir, "demo")
    assert (pdir / "storage_state.json").exists()
    assert (pdir / "meta.json").exists()

    loaded = store.load_profile(tmp_out_dir, "demo")
    assert loaded is not None
    m, ss = loaded
    assert m.name == "demo"
    assert ss == {"cookies": [], "origins": []}


def test_load_missing_returns_none(tmp_out_dir):
    assert store.load_profile(tmp_out_dir, "nope") is None


def test_is_expired(tmp_out_dir):
    meta = store.save_profile(tmp_out_dir, "demo", {"cookies": []}, _scope(),
                              expires_in_days=7, now_ts=NOW)
    assert not store.is_expired(meta, now_ts=NOW + 1)
    assert store.is_expired(meta, now_ts=NOW + 8 * 86400)


def test_find_matching_picks_unexpired(tmp_out_dir):
    store.save_profile(tmp_out_dir, "old", {"cookies": []}, _scope(),
                       expires_in_days=1, now_ts=NOW - 2 * 86400)  # 已过期
    store.save_profile(tmp_out_dir, "fresh", {"cookies": []}, _scope(),
                       expires_in_days=7, now_ts=NOW)
    name = store.find_matching(tmp_out_dir, "https://example.com/x", now_ts=NOW)
    assert name == "fresh"


def test_find_matching_no_match_returns_none(tmp_out_dir):
    store.save_profile(tmp_out_dir, "fresh", {"cookies": []}, _scope(),
                       expires_in_days=7, now_ts=NOW)
    assert store.find_matching(tmp_out_dir, "https://other.com/x", now_ts=NOW) is None


def test_list_profiles(tmp_out_dir):
    store.save_profile(tmp_out_dir, "a", {"cookies": []}, _scope(), 7, now_ts=NOW)
    store.save_profile(tmp_out_dir, "b", {"cookies": []}, _scope(), 7, now_ts=NOW)
    assert set(store.list_profiles(tmp_out_dir)) == {"a", "b"}
