# browser_recorder/paths.py
"""路径解析：统一约定过程产物、最终产物、登录态的落点。"""
from __future__ import annotations
import secrets
import time
from pathlib import Path

# 过程产物根（可被测试 monkeypatch）。AGENTS.md 约定产物落 tmp/。
TMP_ROOT = Path("tmp")

DEFAULT_OUT_DIR_NAME = ".browser-recorder"


def resolve_out_dir(out_dir: str | None) -> Path:
    """默认 ./.browser-recorder，可被 --out-dir 覆盖。"""
    return Path(out_dir) if out_dir else Path.cwd() / DEFAULT_OUT_DIR_NAME


def session_dir(session_id: str) -> Path:
    """录制过程产物目录。"""
    return TMP_ROOT / session_id


def export_dir(out_dir: Path, name: str) -> Path:
    """最终产物目录。"""
    return out_dir / "exports" / name


def auth_dir(out_dir: Path) -> Path:
    return out_dir / "auth"


def profile_dir(out_dir: Path, profile: str) -> Path:
    return auth_dir(out_dir) / profile


def new_session_id() -> str:
    """时间戳 + 4 位随机，提高可读性同时避免并发碰撞。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(2)  # 4 个十六进制字符
    return f"{ts}-{suffix}"
