"""adapter_base Protocol + discover_adapters 测试。"""
from __future__ import annotations
from pathlib import Path
import pytest
from api_console.adapter_base import (
    Confidence, DetectResult, BackendAdapter, Endpoint, discover_adapters,
)

FIX = Path(__file__).parent / "fixtures" / "adapters_sample"


def test_discover_loads_hi():
    """discover_adapters 能从目录扫描并实例化 hi adapter。"""
    adapters = discover_adapters(FIX)
    names = [a.name for a in adapters]
    assert "hi" in names


def test_discover_skips_underscore():
    """下划线开头的 _skip.py 应被跳过。"""
    adapters = discover_adapters(FIX)
    assert all(a.name != "skip" for a in adapters)


def test_hi_adapter_is_protocol_instance():
    """hi adapter 实例满足 BackendAdapter Protocol（runtime_checkable）。"""
    adapters = discover_adapters(FIX)
    hi = [a for a in adapters if a.name == "hi"][0]
    assert isinstance(hi, BackendAdapter)


def test_hi_detect_returns_high():
    """hi adapter.detect 返回 HIGH（置信度分流主干会用）。"""
    adapters = discover_adapters(FIX)
    hi = [a for a in adapters if a.name == "hi"][0]
    r = hi.detect(FIX)
    assert r.confidence == Confidence.HIGH


def test_endpoint_dataclass_defaults():
    """Endpoint dataclass 默认值：url 空、method=GET、auth=none、headers 空。"""
    ep = Endpoint()
    assert ep.url == ""
    assert ep.method == "GET"
    assert ep.auth == "none"
    assert ep.headers == {}


def test_hi_adapter_resolve_endpoint():
    """hi adapter.resolve_endpoint 返回 Endpoint（spec 1.5）。

    hi fixture 用 standard 模式 url=api_base+path；验证 Endpoint 字段齐全。
    """
    adapters = discover_adapters(FIX)
    hi = [a for a in adapters if a.name == "hi"][0]
    ep = hi.resolve_endpoint(
        contract={"service": "svc", "method": "GET", "path": "/x"},
        manifest={"api_base": "http://h"},
    )
    assert isinstance(ep, Endpoint)
    assert ep.url == "http://h/x"
    assert ep.method == "GET"
    assert ep.auth == "none"


def test_hi_adapter_build_auth_headers_none():
    """hi adapter.build_auth_headers 对 auth_mode=none 返回空 dict（spec 1.6）。"""
    adapters = discover_adapters(FIX)
    hi = [a for a in adapters if a.name == "hi"][0]
    h = hi.build_auth_headers("none", manifest={})
    assert h == {}


def test_hi_adapter_build_auth_headers_rejects_unknown():
    """hi fixture 仅支持 none；其他 auth_mode 抛 NotImplementedError。"""
    adapters = discover_adapters(FIX)
    hi = [a for a in adapters if a.name == "hi"][0]
    with pytest.raises(NotImplementedError):
        hi.build_auth_headers("session_cookie", manifest={})
