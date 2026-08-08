"""load_manifest 多环境加载测试（中性 fixture，不 import 真实平台）。"""
from __future__ import annotations
from pathlib import Path
import pytest
from api_console.manifest_loader import load_manifest

FIX = Path(__file__).parent / "fixtures" / "manifests"


def _write(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f.parent  # 返回当作 platform_dir 的目录


def test_new_form_selects_env_and_flattens(tmp_path):
    """新形态(environments 字典): 选定环境字段提升到顶层。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: prod
environments:
  prod:
    host: 10.0.0.1
    gateway_base: http://10.0.0.1/gw
    auth:
      internal: {org: "100", user: "admin"}
    call_policy: {default_mode: demo_internal}
    auth_source: tmp/profiles/10.0.0.1/
  dev:
    host: 10.0.0.2
    gateway_base: http://10.0.0.2/gw
    auth:
      internal: {org: "200", user: "dev"}
    call_policy: {default_mode: demo_internal}
    auth_source: tmp/profiles/10.0.0.2/
""")
    m = load_manifest(d, "prod")
    assert m["host"] == "10.0.0.1"
    assert m["auth"]["internal"]["org"] == "100"
    assert m["call_policy"]["default_mode"] == "demo_internal"
    assert m["active_env"] == "prod"
    assert m["auth_source"] == "tmp/profiles/10.0.0.1/"


def test_new_form_defaults_to_default_env(tmp_path):
    """不传 env -> 用 default_env。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: dev
environments:
  dev:
    host: 10.0.0.2
    auth: {internal: {org: "200"}}
    call_policy: {default_mode: demo_internal}
""")
    m = load_manifest(d)
    assert m["host"] == "10.0.0.2"
    assert m["active_env"] == "dev"


def test_new_form_unknown_env_lists_available(tmp_path):
    """--env 传不存在的环境 -> ValueError 列可用环境。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: prod
environments:
  prod: {host: 10.0.0.1, auth: {internal: {org: "1"}}, call_policy: {default_mode: demo_internal}}
""")
    with pytest.raises(ValueError) as e:
        load_manifest(d, "staging")
    assert "prod" in str(e.value)


def test_old_form_treated_as_single_env(tmp_path):
    """旧形态(无 environments, 顶层 host): 当单环境直接用, env 忽略。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
host: 10.0.0.9
gateway_base: http://10.0.0.9/gw
auth: {internal: {org: "999"}}
call_policy: {default_mode: demo_internal}
""")
    m = load_manifest(d, "anything")
    assert m["host"] == "10.0.0.9"
    assert m["active_env"] == "default"


def test_missing_manifest_guides_init(tmp_path):
    """manifest.yaml 不存在 -> ValueError 引导从模板复制。"""
    with pytest.raises(ValueError) as e:
        load_manifest(tmp_path)
    assert "manifest.example.yaml" in str(e.value)


def test_missing_host_in_env_errors(tmp_path):
    """选定环境缺 host -> ValueError。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: prod
environments:
  prod: {auth: {internal: {org: "1"}}, call_policy: {default_mode: demo_internal}}
""")
    with pytest.raises(ValueError) as e:
        load_manifest(d, "prod")
    assert "host" in str(e.value)


def test_call_card_passes_env_to_load_manifest(tmp_path, monkeypatch):
    """call_card --env 透传给 load_manifest（CLI → load_platform → load_manifest）。"""
    from api_console import call_card
    captured = {}

    def fake_load(platform_dir, env=None):
        captured["env"] = env
        # 返回最小合法 manifest（中性，不耦合特定系统）
        return {
            "host": "x",
            "auth": {},
            "call_policy": {"default_mode": "demo_internal"},
        }

    monkeypatch.setattr(call_card, "load_manifest", fake_load)
    # 卡片表为空 -> 卡片查找 die（SystemExit），但 load_platform 已先执行
    monkeypatch.setattr(call_card, "load_cards", lambda platform: {})
    # platform_dir 指向 tmp_path，避免 discover_adapters/manifest 真实路径依赖
    monkeypatch.setattr(call_card, "_platform_dir", lambda platform: tmp_path)
    # discover_adapters 返回一个中性 mock adapter（不 import 真实平台）
    monkeypatch.setattr(call_card, "discover_adapters", lambda path: ["mock_adapter"])

    argv = ["--platform", "demo", "--card", "nope", "--env", "prod"]
    with pytest.raises(SystemExit):
        call_card.main(argv)
    assert captured["env"] == "prod"


# ---------------------------------------------------------------------------
# 占位符未替换 warning（spec §校验与报错：占位符 <...> 未替换 → warning）
# ---------------------------------------------------------------------------

def test_placeholder_in_host_warns(tmp_path):
    """新形态 host 仍含 ``<YOUR_HOST>`` 占位符 → warning（不 raise）。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: prod
environments:
  prod:
    host: <YOUR_HOST>
    auth: {internal: {org: "1"}}
    call_policy: {default_mode: demo_internal}
""")
    with pytest.warns(UserWarning, match="host.*<YOUR_HOST>"):
        m = load_manifest(d, "prod")
    # 仍正常返回（模板复制-然后-填写是预期流程，只 warning 不 raise）
    assert m["host"] == "<YOUR_HOST>"


def test_placeholder_in_old_form_host_warns(tmp_path):
    """旧形态顶层 host 仍含占位符 → warning（覆盖旧形态分支）。"""
    d = _write(tmp_path, "manifest.yaml", """
name: demo
host: <YOUR_HOST>
auth: {internal: {org: "1"}}
call_policy: {default_mode: demo_internal}
""")
    with pytest.warns(UserWarning, match="host.*<YOUR_HOST>"):
        load_manifest(d)


def test_no_placeholder_no_warning(tmp_path):
    """host 已填真实值 → 不产生 warning（避免误报）。"""
    import warnings as _w
    d = _write(tmp_path, "manifest.yaml", """
name: demo
default_env: prod
environments:
  prod:
    host: 10.0.0.1
    auth: {internal: {org: "1"}}
    call_policy: {default_mode: demo_internal}
""")
    with _w.catch_warnings(record=True) as rec:
        _w.simplefilter("always")
        load_manifest(d, "prod")
    assert not any("占位符" in str(w.message) for w in rec)
