"""EasyOpsContractAdapter 测试（用从真实资料挑出的小样本 fixture）。

样本 fixture（tests/fixtures/）：
    - easyops_contract_sample.json：16 条契约（domain_model 5 + standard_field 8 + holiday 3）
    - ens_routing_sample.json：9 条 ENS 路由（含 logic.flowable_service -> port=8134）

关键点（基于真实数据）：
    - 契约 serviceName 形如 ``logic.flowable_service``（带 logic. 前缀）
    - endpoint.uri 含 colon 参数（``:instanceId``），需归一化为 brace style
    - ENS_ROUTING 无 serviceName 字段，靠 contract 字段关联端口

adapter 实例从 ``platforms/easyops/sources/backend/adapters/`` 用
``discover_adapters`` 加载（与 parse_backend 主干一致），不走 sys.path。
"""
from __future__ import annotations
from pathlib import Path
import pytest

from api_console.adapter_base import Confidence, Endpoint, discover_adapters
from api_console.path_align import normalize_path

FIX = Path(__file__).parent / "fixtures"
SAMPLE_DIR = FIX  # detect/parse 接收含样本文件的目录

# adapters 真实落地目录（与 Task 5 parse_backend 一致）
ADAPTERS_DIR = (
    Path(__file__).resolve().parents[3]
    / "platforms" / "easyops" / "sources" / "backend" / "adapters"
)


def _adapter():
    """加载 easyops_contract adapter 实例。"""
    adapters = discover_adapters(ADAPTERS_DIR)
    target = [a for a in adapters if a.name == "easyops_contract"]
    assert target, f"未在 {ADAPTERS_DIR} 找到 easyops_contract adapter，已有: {[a.name for a in adapters]}"
    return target[0]


def test_detect_high():
    """有 *CONTRACT*.json 文件时 detect 返回 HIGH。"""
    a = _adapter()
    r = a.detect(SAMPLE_DIR)
    assert r.confidence == Confidence.HIGH
    assert r.matched_files  # matched_files 非空
    # 应匹配上 fixture 文件名（含 CONTRACT 字样或 easyops_contract 字样）
    names = " ".join(r.matched_files).lower()
    assert "contract" in names or "easyops" in names


def test_parse_outputs_contracts():
    """parse 输出 BackendContract 字段 dict 列表，含必要字段。"""
    a = _adapter()
    items = a.parse(SAMPLE_DIR)
    assert len(items) > 0
    for it in items:
        assert "operation_key" in it
        assert "method" in it and "path" in it
        assert "service" in it
        assert it["path_source"] == "backend_contract"
    # 样本里含 domain_model 相关契约
    paths = [it["path"] for it in items]
    assert any("domain_model" in p for p in paths)


def test_parse_skips_no_service():
    """无 serviceName 的契约条目应被跳过（service 字段必非空）。"""
    a = _adapter()
    items = a.parse(SAMPLE_DIR)
    for it in items:
        assert it["service"]


def test_parse_attaches_port_from_ens():
    """ENS_ROUTING 提供 port 映射，至少有一条带 port。"""
    a = _adapter()
    items = a.parse(SAMPLE_DIR)
    # 样本里 logic.flowable_service -> port=8134，至少有一条带 port
    assert any(it.get("port") for it in items)
    # flowable_service 相关契约应能匹配到 port=8134
    flowable_items = [it for it in items if "flowable_service" in it["service"]]
    assert flowable_items  # 样本必有
    assert any(it.get("port") == 8134 for it in flowable_items)


def test_path_normalized_to_brace():
    """colon style 路径必须归一化为 brace style（:instanceId -> {instanceId}）。"""
    a = _adapter()
    items = a.parse(SAMPLE_DIR)
    for it in items:
        # 用 normalize_path 校验：再归一化应不变（说明已经是 brace style）
        assert normalize_path(it["path"]) == it["path"], \
            f"path 含未归一化的 colon 参数：{it['path']}"


# ---------- resolve_endpoint（spec 1.5 / 1.6 三种模式） ----------

# 与 platforms/easyops/manifest.yaml 一致的测试 manifest（含三种 auth 配置）
_MANIFEST = {
    "name": "easyops",
    "host": "172.30.5.20",
    "gateway_base": "http://172.30.5.20/next/api/gateway",
    "auth": {
        "session_cookie": {"cookie_file": "auth/cookies.json"},
        "internal": {"org": "5910", "user": "defaultUser"},
        # aksk 故意不配（MVP-1 无 AK/SK，build_auth_headers 应抛 NotImplementedError）
    },
}


def test_resolve_endpoint_easyops_gateway():
    """resolve_endpoint 按 gateway_base + service + path 拼完整 URL（spec 1.5）。

    真调验证过的公式：
        http://172.30.5.20/next/api/gateway/logic.flowable_service
            + /api/flowable_service/v1/domain_model/_search
    """
    a = _adapter()
    contract = {
        "service": "logic.flowable_service",
        "method": "POST",
        "path": "/api/flowable_service/v1/domain_model/_search",
        "endpoint": {"mode": "easyops_gateway"},
    }
    ep = a.resolve_endpoint(contract, _MANIFEST)
    assert isinstance(ep, Endpoint)
    assert ep.url == (
        "http://172.30.5.20/next/api/gateway/"
        "logic.flowable_service/api/flowable_service/v1/domain_model/_search"
    )
    assert ep.method == "POST"
    assert ep.auth == "session_cookie"


def test_resolve_endpoint_default_mode_is_easyops_gateway():
    """contract 不带 endpoint.mode 时默认 easyops_gateway。"""
    a = _adapter()
    contract = {
        "service": "logic.flowable_service",
        "method": "GET",
        "path": "/api/flowable_service/v1/domain_model",
    }
    ep = a.resolve_endpoint(contract, _MANIFEST)
    # 默认 mode 走 easyops_gateway 分支
    assert ep.url == (
        "http://172.30.5.20/next/api/gateway/"
        "logic.flowable_service/api/flowable_service/v1/domain_model"
    )
    assert ep.method == "GET"


def test_resolve_endpoint_easyops_internal():
    """resolve_endpoint easyops_internal 模式：http://host:port/path（spec 1.6）。

    已真调验证（Task 13）：org=5910 + 8134 端口查 flowable_service → 200 code:0。
    """
    a = _adapter()
    contract = {
        "service": "logic.flowable_service",
        "method": "POST",
        "path": "/api/flowable_service/v1/domain_model/_search",
        "port": 8134,
        "endpoint": {"mode": "easyops_internal"},
    }
    ep = a.resolve_endpoint(contract, _MANIFEST)
    assert isinstance(ep, Endpoint)
    assert ep.url == (
        "http://172.30.5.20:8134/api/flowable_service/v1/domain_model/_search"
    )
    assert ep.method == "POST"
    assert ep.auth == "easyops_internal"


def test_resolve_endpoint_internal_requires_port():
    """easyops_internal 模式缺 contract.port -> ValueError（ENS 路由表提供）。"""
    a = _adapter()
    contract = {
        "service": "logic.flowable_service",
        "method": "GET",
        "path": "/api/x",
        "endpoint": {"mode": "easyops_internal"},
    }
    with pytest.raises(ValueError, match="port"):
        a.resolve_endpoint(contract, _MANIFEST)


def test_resolve_endpoint_easyops_aksk():
    """resolve_endpoint easyops_aksk 模式：http://host/<app_name><path>（spec 1.6）。

    app_name 从 manifest.auth.aksk.port_app_map 按 port 反查（8079 -> cmdbservice）。
    """
    a = _adapter()
    manifest = dict(_MANIFEST)
    manifest["auth"] = dict(manifest["auth"])
    manifest["auth"]["aksk"] = {
        "ak": "FAKE_AK", "sk": "FAKE_SK",
        "port_app_map": {8079: "cmdbservice"},
    }
    contract = {
        "service": "logic.cmdb.service",
        "method": "POST",
        "path": "/v3/object/HOST/instance/_search",
        "port": 8079,
        "endpoint": {"mode": "easyops_aksk"},
    }
    ep = a.resolve_endpoint(contract, manifest)
    assert ep.url == (
        "http://172.30.5.20/cmdbservice/v3/object/HOST/instance/_search"
    )
    assert ep.method == "POST"
    assert ep.auth == "easyops_aksk"


def test_resolve_endpoint_aksk_requires_port_app_map():
    """easyops_aksk 模式无 port_app_map -> ValueError。"""
    a = _adapter()
    contract = {
        "service": "svc", "method": "GET", "path": "/p",
        "port": 8079,
        "endpoint": {"mode": "easyops_aksk"},
    }
    with pytest.raises(ValueError, match="port_app_map"):
        a.resolve_endpoint(contract, _MANIFEST)


def test_resolve_endpoint_rejects_unsupported_mode():
    """mode 不在三种之列 -> NotImplementedError。"""
    a = _adapter()
    contract = {
        "service": "svc", "method": "GET", "path": "/p",
        "endpoint": {"mode": "easyops_openapi"},
    }
    with pytest.raises(NotImplementedError):
        a.resolve_endpoint(contract, _MANIFEST)


def test_resolve_endpoint_method_uppercased():
    """contract.method 小写时 resolve 返回大写（统一 httpx 调用约定）。"""
    a = _adapter()
    contract = {
        "service": "svc", "method": "post",
        "path": "/p",
    }
    ep = a.resolve_endpoint(contract, _MANIFEST)
    assert ep.method == "POST"


def test_resolve_endpoint_from_real_parsed_contract():
    """对 parse 出的真实契约调 resolve，URL 拼接正确（端到端 parse->resolve）。"""
    a = _adapter()
    items = a.parse(SAMPLE_DIR)
    # 找一条 domain_model 相关契约
    target = [it for it in items if "domain_model" in it["path"]][0]
    ep = a.resolve_endpoint(target, _MANIFEST)
    assert ep.url.startswith(_MANIFEST["gateway_base"] + "/" + target["service"])
    assert ep.url.endswith(target["path"])
    assert ep.auth == "session_cookie"


# ---------- _load_manifest（Task 4：委托 load_manifest，default_env 扁平化） ----------


def test_load_manifest_delegates_to_load_manifest_default_env(monkeypatch):
    """_load_manifest 委托 load_manifest(platform_dir, None)：用 default_env 扁平化。

    Task 4：adapter._load_manifest 不再自己 yaml.safe_load，而是调 load_manifest
    （env=None → 用 default_env）。mock load_manifest 断言传入 env 是 None，
    并返回一个含 call_policy.default_mode 的扁平 manifest，验证 _default_call_mode
    能吃到扁平化后的顶层 call_policy。
    """
    import easyops_contract

    captured = {}

    def fake_load(platform_dir, env=None):
        captured["platform_dir"] = Path(platform_dir)
        captured["env"] = env
        return {
            "call_policy": {"default_mode": "easyops_internal"},
            "active_env": "prod",
        }

    monkeypatch.setattr(easyops_contract, "load_manifest", fake_load)
    a = easyops_contract.Adapter()
    a._manifest_cache = None  # 重置缓存，强制走 fake_load
    # _load_manifest 内部按 __file__ 向上找 manifest.yaml；用 monkeypatch 把
    # _load_manifest 改为直接调 fake_load 不现实，故直接验证 _default_call_mode
    # 链路：monkeypatch load_manifest 后，_load_manifest 会调它（因为 platform_dir
    # 由 __file__ 推导，真实指向 platforms/easyops/，load_manifest 会被调用）。
    # 但为避免依赖真实 manifest，改用直接断言 _default_call_mode 读到扁平 call_policy：
    mode = a._default_call_mode()
    assert captured["env"] is None  # 关键：env=None（用 default_env，不切换）
    assert mode == "easyops_internal"


def test_load_manifest_missing_returns_empty(tmp_path, monkeypatch):
    """_load_manifest 读不到 manifest（load_manifest 抛 ValueError）-> 返回空 dict。

    adapter 的契约：读不到 manifest 不抛错，按未配置处理（_default_call_mode 返回空串，
    回退到契约推断分支）。load_manifest 缺文件抛 ValueError，需被 _load_manifest 吞掉。
    """
    import easyops_contract

    def boom(platform_dir, env=None):
        raise ValueError("未找到 manifest.yaml")

    monkeypatch.setattr(easyops_contract, "load_manifest", boom)
    a = easyops_contract.Adapter()
    a._manifest_cache = None
    # 指向一个无 manifest 的目录，触发 load_manifest 抛错（被 _load_manifest 吞）
    a._load_manifest()
    # 缓存为空 dict（不抛）
    assert a._manifest_cache == {}
    assert a._default_call_mode() == ""


# ---------- build_auth_headers（spec 1.6 三分支） ----------


def test_build_auth_headers_session_cookie(tmp_path):
    """session_cookie 分支：读 cookie_file 拼 Cookie 头。"""
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '[{"name":"sid","value":"abc"},{"name":"u","value":"x"}]'
    )
    manifest = {
        "auth": {"session_cookie": {"cookie_file": str(cookie_file)}}
    }
    a = _adapter()
    h = a.build_auth_headers("session_cookie", manifest)
    assert h == {"Cookie": "sid=abc; u=x"}


def test_build_auth_headers_session_cookie_missing_config():
    """session_cookie 模式无 cookie/cookie_file 配置 -> ValueError。

    新形态（多环境 manifest）：优先 ``manifest.auth.session_cookie.cookie``
    明文字段；两者都缺时抛 ValueError（提示含 cookie 与 cookie_file）。
    """
    a = _adapter()
    with pytest.raises(ValueError, match="cookie"):
        a.build_auth_headers("session_cookie", manifest={"auth": {}})


def test_session_cookie_from_cookie_field():
    """session_cookie 优先取 manifest.auth.session_cookie.cookie 明文字段。

    新形态（多环境 manifest）：cookie 字段存在时直接返回，不读 cookie_file。
    """
    a = _adapter()
    manifest = {"auth": {"session_cookie": {"cookie": "PHPSESSID=abc; x=1"}}}
    h = a.build_auth_headers("session_cookie", manifest)
    assert h == {"Cookie": "PHPSESSID=abc; x=1"}


def test_session_cookie_prefers_cookie_field_over_file(tmp_path):
    """cookie 字段与 cookie_file 同时存在时，优先用 cookie 字段（不读文件）。"""
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text('[{"name": "sid", "value": "from_file"}]')
    a = _adapter()
    manifest = {
        "auth": {
            "session_cookie": {
                "cookie": "PHPSESSID=from_field",
                "cookie_file": str(cookie_file),
            }
        }
    }
    h = a.build_auth_headers("session_cookie", manifest)
    assert h == {"Cookie": "PHPSESSID=from_field"}


def test_session_cookie_fallback_to_cookie_file(tmp_path):
    """无 cookie 字段但有 cookie_file（旧形态）-> 读文件兜底。

    给绝对路径避开 adapter 相对路径解析（兜底扫 platforms/*/）。
    """
    a = _adapter()
    cf = tmp_path / "cookies.json"
    cf.write_text('[{"name": "PHPSESSID", "value": "legacy"}]')
    manifest = {"auth": {"session_cookie": {"cookie_file": str(cf)}}}
    h = a.build_auth_headers("session_cookie", manifest)
    assert h == {"Cookie": "PHPSESSID=legacy"}


def test_build_auth_headers_session_cookie_file_not_found():
    """session_cookie 模式 cookie 文件不存在 -> FileNotFoundError。"""
    a = _adapter()
    manifest = {
        "auth": {"session_cookie": {"cookie_file": "nonexistent/cookies.json"}}
    }
    with pytest.raises(FileNotFoundError):
        a.build_auth_headers("session_cookie", manifest)


def test_build_auth_headers_internal():
    """easyops_internal 分支：返回 user/org/Content-Type 头（spec 1.6）。

    已真调验证（Task 13，org=5910）：三头即可访问 8134 端口 flowable_service。
    """
    a = _adapter()
    h = a.build_auth_headers("easyops_internal", _MANIFEST)
    assert h == {
        "user": "defaultUser",
        "org": "5910",
        "Content-Type": "application/json",
    }


def test_build_auth_headers_internal_default_user():
    """internal 分支缺 user 时用默认 defaultUser（参考 api-samples.py 第 59 行）。"""
    a = _adapter()
    manifest = {"auth": {"internal": {"org": "123"}}}
    h = a.build_auth_headers("easyops_internal", manifest)
    assert h["user"] == "defaultUser"


def test_build_auth_headers_internal_org_from_agent(tmp_path, monkeypatch):
    """manifest 没配 org 时，从 agent conf 兜底读取（base.client_id）。

    spec: org 解析顺序 manifest 优先 + agent 兜底。
    """
    from easyops_contract import _resolve_org_from_agent
    # 造一个 agent conf
    conf = tmp_path / "conf.yaml"
    conf.write_text("base:\n  client_id: 8888\n")
    org = _resolve_org_from_agent(str(conf))
    assert org == "8888"


def test_build_auth_headers_internal_agent_fallback(tmp_path):
    """manifest 缺 org + agent conf 提供 → 用 agent 的 org（兜底生效）。"""
    a = _adapter()
    conf = tmp_path / "agent.yaml"
    conf.write_text("base:\n  client_id: '7777'\n")
    manifest = {"auth": {"internal": {"agent_conf": str(conf)}}}  # 无 org
    h = a.build_auth_headers("easyops_internal", manifest)
    assert h["org"] == "7777"
    assert h["user"] == "defaultUser"  # user 仍走默认


def test_build_auth_headers_internal_no_org_anywhere(tmp_path):
    """manifest 无 org + agent conf 不存在 → 报错（缺 org）。"""
    a = _adapter()
    manifest = {"auth": {"internal": {
        "agent_conf": str(tmp_path / "nonexistent.yaml")
    }}}
    with pytest.raises(NotImplementedError, match="org"):
        a.build_auth_headers("easyops_internal", manifest)


def test_build_auth_headers_internal_requires_org(tmp_path):
    """internal 模式 manifest 无 org + agent conf 也不存在 -> NotImplementedError。

    org 解析三层都失败才报错（manifest 优先 + agent 兜底）。
    指向一个不存在的 agent_conf，避免本机真有 agent conf 时兜底成功。
    """
    a = _adapter()
    manifest = {"auth": {"internal": {
        "agent_conf": str(tmp_path / "no_such_agent.yaml")
    }}}
    with pytest.raises(NotImplementedError, match="org"):
        a.build_auth_headers("easyops_internal", manifest)


def test_build_auth_headers_aksk_without_config():
    """easyops_aksk 分支无 ak/sk 配置 -> NotImplementedError（MVP-1 默认场景）。"""
    a = _adapter()
    with pytest.raises(NotImplementedError, match="ak/sk"):
        a.build_auth_headers(
            "easyops_aksk", _MANIFEST,
            request_ctx={"method": "POST", "url": "http://h/x", "body": {}},
        )


def test_build_auth_headers_aksk_signs_request():
    """easyops_aksk 分支有 ak/sk 时：算 HMAC-SHA1 签名，返回 user/Host/Content-Type/__url_query__。

    验证签名结果通过伪头 __url_query__ 透传（不进入真实 HTTP 头），execute_dag
    附加到 URL。参考 sources/raw/backend/api-samples.py 的 __signature 算法。
    """
    a = _adapter()
    manifest = {
        "auth": {"aksk": {
            "ak": "FAKE_AK", "sk": "FAKE_SK",
            "port_app_map": {8079: "cmdbservice"},
        }}
    }
    h = a.build_auth_headers(
        "easyops_aksk", manifest,
        request_ctx={
            "method": "POST",
            "url": "http://172.30.5.20/cmdbservice/v3/object/HOST/instance/_search",
            "body": {"page": 1},
        },
    )
    # 必含字段
    assert h["user"] == "defaultUser"
    assert h["Host"] == "openapi.easyops-only.com"
    assert h["Content-Type"] == "application/json"
    # __url_query__ 含 accesskey/signature/expires（urlencode 后）
    assert "__url_query__" in h
    q = h["__url_query__"]
    assert "accesskey=FAKE_AK" in q
    assert "signature=" in q
    assert "expires=" in q


def test_build_auth_headers_aksk_get_no_content_type():
    """aksk GET 模式不发 Content-Type（参考 api-samples.py 第 188-189 行）。"""
    a = _adapter()
    manifest = {
        "auth": {"aksk": {"ak": "FAKE_AK", "sk": "FAKE_SK"}}
    }
    h = a.build_auth_headers(
        "easyops_aksk", manifest,
        request_ctx={"method": "GET", "url": "http://h/p", "body": None},
    )
    assert "Content-Type" not in h


def test_build_auth_headers_none():
    """auth_mode=none -> 空 dict（测试场景）。"""
    a = _adapter()
    assert a.build_auth_headers("none", _MANIFEST) == {}


def test_build_auth_headers_unknown_mode():
    """未知 auth_mode -> NotImplementedError。"""
    a = _adapter()
    with pytest.raises(NotImplementedError, match="auth_mode"):
        a.build_auth_headers("bearer", _MANIFEST)


# easyops_contract 通过 discover_adapters 路径加载；为了让模块级 import 生效，
# 把 adapters 目录加入 sys.path（与现有 _resolve_org_from_agent 测试在函数体内
# import 的做法等价，只是放在模块级以便多个测试复用）。
import sys as _sys
if str(ADAPTERS_DIR) not in _sys.path:
    _sys.path.insert(0, str(ADAPTERS_DIR))
from easyops_contract import resolve_service_from_rpc


class TestResolveServiceFromRpc:
    """命名式 RPC 名 → 契约 logic service 解析。"""

    def _contracts(self, items):
        """items: [(service, method, path), ...] → 模拟 BackendContract。"""
        from types import SimpleNamespace
        return [SimpleNamespace(service=s, method=m, path=p) for s, m, p in items]

    def test_unique_method_path_hit(self):
        """method+path 唯一命中 → 返回该契约 service。"""
        cs = self._contracts([("logic.cmdb.service", "GET", "/object/{objectId}")])
        r = resolve_service_from_rpc("cmdb.cmdb_object.GetDetail", "GET",
                                     "/next/api/gateway/cmdb.cmdb_object.GetDetail/object/{objectId}", cs)
        assert r == "logic.cmdb.service"

    def test_rpc_prefix_disambiguation(self):
        """多义时 RPC 名首段匹配候选 service 前缀。"""
        cs = self._contracts([
            ("logic.cmdb.service", "GET", "/object/{objectId}"),
            ("logic.flowable_service", "GET", "/object/{objectId}"),
        ])
        r = resolve_service_from_rpc("cmdb.cmdb_object.GetDetail", "GET",
                                     "/next/api/gateway/cmdb.cmdb_object.GetDetail/object/{objectId}", cs)
        assert r == "logic.cmdb.service"

    def test_no_hit_returns_empty(self):
        """无契约匹配 → 返回空串。"""
        cs = self._contracts([("logic.x", "GET", "/other")])
        r = resolve_service_from_rpc("cmdb.foo.Bar", "GET",
                                     "/next/api/gateway/cmdb.foo.Bar/object/{objectId}", cs)
        assert r == ""

    def test_already_logic_prefix_passthrough(self):
        """service 已是 logic.* → 直接返回。"""
        cs = self._contracts([("logic.cmdb.service", "GET", "/object/{objectId}")])
        r = resolve_service_from_rpc("logic.cmdb.service", "GET",
                                     "/next/api/gateway/logic.cmdb.service/object/{objectId}", cs)
        assert r == "logic.cmdb.service"

