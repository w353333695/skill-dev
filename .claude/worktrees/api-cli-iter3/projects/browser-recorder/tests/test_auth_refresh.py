# tests/test_auth_refresh.py
"""I-3 验证：record --auth <missing> 的 profile 创建路径。

完整交互式登录需 Playwright + 人工输入（CI 不便），这里覆盖纯函数
``_scope_from_url`` 派生 + ``store.save_profile`` 创建 profile 的关键链路
（runner._interactive_login 在 headless=True 时返回 None，runner 会按匿名录制；
store.save_profile 的写盘效果由 test_auth_store 覆盖，此处再补一条
"从 URL 派生 scope 后存盘" 的端到端单元测试）。
"""
import time
from browser_recorder.record.runner import _scope_from_url
from browser_recorder.auth import store


NOW = 1722600000.0


def test_scope_from_url_basic_regdomain():
    s = _scope_from_url("https://app.example.com/list.html")
    assert s["registrable_domain"] == "example.com"
    assert s["hosts"] == ["app.example.com"]
    assert s["scheme"] == ["https"]


def test_scope_from_url_with_port():
    s = _scope_from_url("http://localhost:8080/x")
    assert s["hosts"] == ["localhost"]
    assert s["registrable_domain"] == "localhost"
    assert s["scheme"] == ["http"]
    assert s["ports"] == [8080]


def test_save_profile_with_scope_from_url_creates_profile(tmp_out_dir):
    """模拟 record --auth <missing> 的登录后保存路径：
    从目标 URL 派生 scope → save_profile → load_profile 能读回。"""
    url = "https://app.example.com/list"
    scope = _scope_from_url(url)
    state = {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}
    store.save_profile(tmp_out_dir, "demo", state, scope=scope,
                       expires_in_days=7, now_ts=NOW)
    loaded = store.load_profile(tmp_out_dir, "demo")
    assert loaded is not None
    meta, ss = loaded
    assert meta.scope["registrable_domain"] == "example.com"
    assert ss == state
    # 同一 scope 应被 find_matching 命中
    assert store.find_matching(tmp_out_dir, url, now_ts=NOW + 1) == "demo"


def test_record_runner_headless_skips_interactive_login(monkeypatch):
    """runner._interactive_login 在 headless=True 时必须直接返回 None，
    不阻塞 input()（CI/烟测路径）。"""
    import asyncio
    from browser_recorder.record import runner

    # 阻塞的 input 不应被调用
    def _boom(*a, **kw):
        raise AssertionError("input() 不应在 headless 模式被调用")
    monkeypatch.setattr("builtins.input", _boom)

    async def _do():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            # 传 headless=True，预期直接返回 None
            return await runner._interactive_login(pw, "about:blank", headless=True)
    state = asyncio.run(_do())
    assert state is None
