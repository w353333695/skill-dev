# browser_recorder/auth/store.py
"""登录态 profile 存储与引用：storage_state + meta.json，按 scope 匹配。"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from . import scope
from .. import paths


@dataclass
class AuthMeta:
    name: str
    created_at: float
    expires_in_days: int
    scope: dict[str, Any]
    storage_state: str = "storage_state.json"


def _meta_path(out_dir: Path, name: str) -> Path:
    return paths.profile_dir(out_dir, name) / "meta.json"


def _state_path(out_dir: Path, name: str) -> Path:
    return paths.profile_dir(out_dir, name) / "storage_state.json"


def save_profile(out_dir: Path, name: str, storage_state: dict, scope: dict,
                 expires_in_days: int, *, now_ts: float) -> AuthMeta:
    pdir = paths.profile_dir(out_dir, name)
    pdir.mkdir(parents=True, exist_ok=True)
    _state_path(out_dir, name).write_text(
        json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")
    meta = AuthMeta(name=name, created_at=now_ts, expires_in_days=expires_in_days,
                    scope=scope)
    _meta_path(out_dir, name).write_text(
        json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def load_profile(out_dir: Path, name: str) -> "tuple[AuthMeta, dict] | None":
    mp, sp = _meta_path(out_dir, name), _state_path(out_dir, name)
    if not mp.exists() or not sp.exists():
        return None
    d = json.loads(mp.read_text(encoding="utf-8"))
    meta = AuthMeta(**d)
    state = json.loads(sp.read_text(encoding="utf-8"))
    return meta, state


def is_expired(meta: AuthMeta, now_ts: float) -> bool:
    return now_ts > meta.created_at + meta.expires_in_days * 86400


def list_profiles(out_dir: Path) -> list[str]:
    adir = paths.auth_dir(out_dir)
    if not adir.exists():
        return []
    return sorted(p.name for p in adir.iterdir() if p.is_dir())


def find_matching(out_dir: Path, target_url: str, *, now_ts: float) -> "str | None":
    """扫描 auth/，按 scope 匹配，取最新未过期。"""
    candidates: list[tuple[float, str]] = []
    for name in list_profiles(out_dir):
        loaded = load_profile(out_dir, name)
        if loaded is None:
            continue
        meta, _ = loaded
        if is_expired(meta, now_ts):
            continue
        if scope.matches(target_url, meta.scope):
            candidates.append((meta.created_at, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
