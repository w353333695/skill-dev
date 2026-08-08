"""extract_auth 测试（mock get_cookies，不碰真浏览器）。

mock 策略：直接 patch 模块内的 get_cookies 函数，避免触发真实 pycookiecheat
调用与 Chrome SQLite 读取（真实端到端留 Task 12）。

另含纯函数 ``_update_cookie_in_manifest`` 的文本级定点写回测试（中性 fixture，
不耦合任何真实平台 / agent）。
"""
from __future__ import annotations
from pathlib import Path
import json
from unittest.mock import patch
import pytest
from api_console.extract_auth import (
    run,
    _update_cookie_in_manifest,
    _cookies_to_session_str,
    main as extract_auth_main,
)


def test_run_writes_cookies_and_meta(tmp_path):
    """run 正常路径：写 cookies.json + meta.json，内容与 mock 返回一致。"""
    fake_cookies = [{"name": "session", "value": "abc", "domain": "172.30.5.20"}]
    with patch("api_console.extract_auth.get_cookies") as gc:
        gc.return_value = fake_cookies
        auth_dir = tmp_path / "auth"
        run(host="172.30.5.20",
            profile_dir=tmp_path / "profiles" / "172.30.5.20",
            auth_dir=auth_dir)
    cookies = json.loads((auth_dir / "cookies.json").read_text())
    assert cookies == fake_cookies
    meta = json.loads((auth_dir / "meta.json").read_text())
    assert meta["host"] == "172.30.5.20"
    assert "extracted_at" in meta
    assert meta["count"] == len(fake_cookies)


def test_run_handles_no_profile(tmp_path):
    """profile 不存在时应抛异常（含 'profile' 字样），不静默写空。"""
    with pytest.raises(Exception, match="profile"):
        run(host="172.30.5.20",
            profile_dir=tmp_path / "nonexistent",
            auth_dir=tmp_path / "auth")


# ---------------------------------------------------------------------------
# _update_cookie_in_manifest：文本级定点写回（中性 fixture，不耦合真实平台）
# ---------------------------------------------------------------------------

# 新形态 manifest 样例（两个环境 + 注释 + 多种缩进/字段顺序，覆盖常见变体）
_NEW_FORM_SAMPLE = """name: demo
default_env: prod  # 默认环境
environments:
  prod:
    host: 10.0.0.1
    auth:
      session_cookie:
        cookie: ""  # 占位
      internal: {org: "1"}
  dev:
    host: 10.0.0.2
    auth:
      session_cookie:
        cookie: ""
"""


def test_update_cookie_preserves_other_content(tmp_path):
    """写回 cookie 只改目标字段，保留其他环境块/注释/键顺序。"""
    m = tmp_path / "manifest.yaml"
    m.write_text(_NEW_FORM_SAMPLE, encoding="utf-8")
    _update_cookie_in_manifest(m, "prod", "PHPSESSID=abc123")
    text = m.read_text(encoding="utf-8")
    # prod 的 cookie 被更新（带引号）
    assert 'cookie: "PHPSESSID=abc123"' in text
    # dev 的 cookie 不受影响（仍为空串，全文只剩一处）
    assert text.count('cookie: ""') == 1
    # 注释保留
    assert "# 默认环境" in text
    # host 保留
    assert "10.0.0.1" in text and "10.0.0.2" in text
    # 其他键顺序保留（default_env 仍在 environments 之前）
    assert text.index("default_env") < text.index("environments:")


def test_update_cookie_unknown_env_errors(tmp_path):
    """环境不存在 -> 报错。"""
    m = tmp_path / "manifest.yaml"
    m.write_text(_NEW_FORM_SAMPLE, encoding="utf-8")
    with pytest.raises(ValueError):
        _update_cookie_in_manifest(m, "staging", "c")


def test_update_cookie_writes_dev_env(tmp_path):
    """指定 dev 环境：仅改 dev 块，prod 块保持不变。"""
    m = tmp_path / "manifest.yaml"
    m.write_text(_NEW_FORM_SAMPLE, encoding="utf-8")
    _update_cookie_in_manifest(m, "dev", "SID=xyz")
    text = m.read_text(encoding="utf-8")
    assert 'cookie: "SID=xyz"' in text
    # prod 块 cookie 仍是占位空串
    assert 'cookie: ""' in text


def test_update_cookie_escapes_double_quote(tmp_path):
    """cookie 含双引号时转义，避免破坏 YAML。"""
    m = tmp_path / "manifest.yaml"
    m.write_text(_NEW_FORM_SAMPLE, encoding="utf-8")
    _update_cookie_in_manifest(m, "prod", 'a"b')
    text = m.read_text(encoding="utf-8")
    assert 'cookie: "a\\"b"' in text


def test_update_cookie_missing_field_errors(tmp_path):
    """环境块存在但缺 session_cookie.cookie 字段 -> 报错（不静默跳过）。"""
    m = tmp_path / "manifest.yaml"
    m.write_text(
        "name: demo\ndefault_env: prod\nenvironments:\n"
        "  prod:\n    host: 10.0.0.1\n    auth: {internal: {org: \"1\"}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        _update_cookie_in_manifest(m, "prod", "c")


# ---------------------------------------------------------------------------
# _cookies_to_session_str：多 cookie 拼接（修复 multi-cookie 回归）
# ---------------------------------------------------------------------------

def test_cookies_to_session_str_joins_all_matched():
    """domain 匹配 host 的多条 cookie 全部拼接（``"; "`` 分隔），不只取首条。

    回归覆盖：旧 cookie_file 路径用 ``"; ".join`` 拼，新 cookie-field 路径早期
    实现只取 pool[0]，多 cookie 站点会静默丢条。此测试钉死"全部拼接"行为。
    """
    cookies = [
        {"name": "session", "value": "abc", "domain": "10.0.0.1"},
        {"name": "csrf", "value": "xyz", "domain": "10.0.0.1"},
        {"name": "other", "value": "zzz", "domain": "10.0.0.2"},
    ]
    # host 匹配前两条，按出现顺序拼接（other 不在域内被过滤）
    assert _cookies_to_session_str(cookies, "10.0.0.1") == "session=abc; csrf=xyz"


def test_cookies_to_session_str_single_cookie():
    """单条 cookie 正常返回 ``name=value``（无多余拼接）。"""
    cookies = [{"name": "session", "value": "abc", "domain": "10.0.0.1"}]
    assert _cookies_to_session_str(cookies, "10.0.0.1") == "session=abc"


def test_cookies_to_session_str_empty():
    """空列表返回空串。"""
    assert _cookies_to_session_str([], "10.0.0.1") == ""


# ---------------------------------------------------------------------------
# main：新形态 env 名为 default 的检测（修复 active_env 启发式误判）
# ---------------------------------------------------------------------------

def test_main_new_form_env_named_default_writes_cookie_field(tmp_path, monkeypatch):
    """新形态 manifest 把环境命名为 ``default``：main 应识别为新形态并写 cookie 字段。

    回归覆盖：早期 main 用 ``active_env and active_env != "default"`` 判定新形态，
    会把 env 名为 default 的新形态误判为旧形态 → 错落 cookies.json → adapter 拿
    空 cookie → 401。改用读原始 manifest 是否含 ``environments:`` 键后，env 名不再
    影响判定。本例 default_env=default + environments.default 命中分支。
    """
    workdir = tmp_path
    platform_dir = workdir / "platforms" / "demo"
    platform_dir.mkdir(parents=True)
    manifest = platform_dir / "manifest.yaml"
    manifest.write_text(
        """name: demo
default_env: default
environments:
  default:
    host: 10.0.0.1
    auth:
      session_cookie:
        cookie: ""
    auth_source: tmp/profiles/10.0.0.1/
""",
        encoding="utf-8",
    )
    # 模拟 profile（get_cookies 被 patch，profile 目录无需真实存在）
    (workdir / "tmp" / "profiles" / "10.0.0.1").mkdir(parents=True)

    fake_cookies = [{"name": "session", "value": "abc", "domain": "10.0.0.1"}]
    monkeypatch.setenv("API_CONSOLE_WORKDIR", str(workdir))
    with patch("api_console.extract_auth.get_cookies", return_value=fake_cookies):
        rc = extract_auth_main(["--platform", "demo"])

    assert rc == 0
    # 新形态分支：cookie 字段被定点写回（不再落 cookies.json）
    text = manifest.read_text(encoding="utf-8")
    assert 'cookie: "session=abc"' in text
    # 旧形态分支产物不应出现
    assert not (platform_dir / "auth" / "cookies.json").exists()


def test_main_old_form_writes_cookies_json(tmp_path, monkeypatch):
    """旧形态 manifest（无 environments）：main 落 auth/cookies.json（旧行为）。"""
    workdir = tmp_path
    platform_dir = workdir / "platforms" / "demo"
    platform_dir.mkdir(parents=True)
    manifest = platform_dir / "manifest.yaml"
    manifest.write_text(
        "name: demo\nhost: 10.0.0.1\nauth_source: tmp/profiles/10.0.0.1/\n",
        encoding="utf-8",
    )
    (workdir / "tmp" / "profiles" / "10.0.0.1").mkdir(parents=True)

    fake_cookies = [{"name": "session", "value": "abc", "domain": "10.0.0.1"}]
    monkeypatch.setenv("API_CONSOLE_WORKDIR", str(workdir))
    with patch("api_console.extract_auth.get_cookies", return_value=fake_cookies):
        rc = extract_auth_main(["--platform", "demo"])

    assert rc == 0
    cookies = json.loads((platform_dir / "auth" / "cookies.json").read_text())
    assert cookies == fake_cookies
