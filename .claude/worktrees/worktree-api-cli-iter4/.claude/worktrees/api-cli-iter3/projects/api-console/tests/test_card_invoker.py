"""card_invoker 单测：invoke_card 请求层 + _normalize_contracts。

mock 策略：patch ``card_invoker.http_request``，按 (method, url 后缀) 路由响应体。
adapter 用 FakeAdapter（与 test_execute_dag 同范式），验证 invoke_card 的
path 替换 / GET query / POST json / 鉴权头合并 / __url_query__ 签名伪头行为。
"""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock

from api_console.adapter_base import Endpoint
from api_console.card_invoker import invoke_card, InvokeResult, _normalize_contracts
from api_console.schema.card import Card, OutputAnchor


class FakeAdapter:
    """假 adapter：resolve_endpoint 返回 http://h<card.path> 的 Endpoint，auth=none。"""

    name = "fake"

    def resolve_endpoint(self, contract: dict, manifest: dict) -> Endpoint:
        path = contract.get("path", "")
        method = contract.get("method", "GET").upper()
        return Endpoint(url="http://h" + path, method=method, auth="none", headers={})

    def build_auth_headers(self, auth_mode: str, manifest: dict,
                           request_ctx: dict | None = None) -> dict:
        if auth_mode == "none":
            return {}
        raise NotImplementedError(f"FakeAdapter 不支持 auth_mode={auth_mode}")

    def resolve_call_mode(self, card, contracts: dict) -> str:
        """沿用卡片自带 endpoint.mode（主干默认行为）。"""
        ep = getattr(card, "endpoint", None) or {}
        return ep.get("mode", "")


def _card(name, method="GET", path=None, side_effect="read",
          contract_ref="", mode="fake_mode", service=""):
    """构造极简卡片（mode 用中性占位，主干不依赖具体平台 mode 名）。"""
    return Card(name=name, module="m", method=method, path=path or ("/p/" + name),
                side_effect=side_effect, service=service,
                endpoint={"contract_ref": contract_ref, "mode": mode})


def _ok(body):
    """构造 200 + code:0 的假 resp。"""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"code": 0, "data": body}
    return m


class TestNormalizeContracts:
    """_normalize_contracts：list/dict 两种输入归一化为 dict（从 test_execute_dag 迁入）。"""

    def test_list_indexed_by_operation_key(self):
        cl = [
            {"operation_key": "svc|GET|/a", "method": "GET", "path": "/a"},
            {"operation_key": "svc|POST|/b", "method": "POST", "path": "/b"},
        ]
        out = _normalize_contracts(cl)
        assert set(out.keys()) == {"svc|GET|/a", "svc|POST|/b"}
        assert out["svc|GET|/a"]["path"] == "/a"

    def test_dict_passthrough(self):
        d = {"svc|GET|/a": {"path": "/a"}}
        assert _normalize_contracts(d) is d

    def test_none_and_empty(self):
        assert _normalize_contracts(None) == {}
        assert _normalize_contracts([]) == {}

    def test_skips_entries_without_operation_key(self):
        cl = [{"operation_key": "k1", "path": "/a"}, {"path": "/nokey"}]
        out = _normalize_contracts(cl)
        assert list(out.keys()) == ["k1"]


class TestInvokeCard:
    """invoke_card 请求层：path 替换 / GET query / POST json / 鉴权 / 签名伪头。"""

    def test_get_params_as_query(self):
        """GET 卡片：params 作为 query 传给 http_request。"""
        card = _card("search")
        seen = {}

        def fake(method, url, headers=None, **kw):
            seen.update(kw)
            return _ok({"list": []})
        with patch("api_console.card_invoker.http_request", fake):
            r = invoke_card(card, {"Q": "test", "page": 1}, FakeAdapter(), {}, {})
        assert seen["params"] == {"Q": "test", "page": 1}
        assert r.method == "GET"
        assert r.url == "http://h/p/search"
        assert isinstance(r, InvokeResult)

    def test_post_params_as_json_body(self):
        """非 GET 卡片：params 作为 json body 传给 http_request。"""
        card = _card("create", method="POST")
        seen = {}

        def fake(method, url, headers=None, **kw):
            seen.update(kw)
            seen["method"] = method
            return _ok({"id": "x"})
        with patch("api_console.card_invoker.http_request", fake):
            invoke_card(card, {"name": "n"}, FakeAdapter(), {}, {})
        assert seen["json"] == {"name": "n"}
        assert seen["method"] == "POST"

    def test_path_placeholder_replaced(self):
        """url 中的 {modelId} 占位用 params["modelId"] 替换。"""
        card = _card("get", path="/model/{modelId}")
        seen_url = {}

        def fake(method, url, headers=None, **kw):
            seen_url["url"] = url
            return _ok({})
        with patch("api_console.card_invoker.http_request", fake):
            invoke_card(card, {"modelId": "123"}, FakeAdapter(), {}, {})
        assert seen_url["url"] == "http://h/model/123"

    def test_multi_placeholder_path_replaced(self):
        """url 含多个占位符时，按 {key} 名各自替换（rollback 多参数 path 依赖此）。

        如 deleteFormVersion 的 /form/{formId}/version/{versionId}。
        """
        card = _card("deleteFormVersion", method="DELETE",
                     path="/form/{formId}/version/{versionId}")
        seen_url = {}

        def fake(method, url, headers=None, **kw):
            seen_url["url"] = url
            return _ok({})
        with patch("api_console.card_invoker.http_request", fake):
            invoke_card(card, {"formId": "f1", "versionId": "v9"},
                        FakeAdapter(), {}, {})
        assert seen_url["url"] == "http://h/form/f1/version/v9"

    def test_url_query_pseudo_header_appended_to_url(self):
        """aksk 伪头 __url_query__ 取出附加到 URL，不进入真实 HTTP 头。"""

        class AkskAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                return Endpoint(url="http://h/x", method="POST",
                                auth="aksk", headers={})

            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                return {
                    "user": "tester",
                    "__url_query__": "accesskey=AK&signature=SIG&expires=123",
                }
        card = _card("x", method="POST")
        seen_url = {}
        seen_headers = {}

        def fake(method, url, headers=None, **kw):
            seen_url["url"] = url
            seen_headers.update(headers or {})
            return _ok({})
        with patch("api_console.card_invoker.http_request", fake):
            invoke_card(card, {}, AkskAdapter(), {}, {})
        assert seen_url["url"] == "http://h/x?accesskey=AK&signature=SIG&expires=123"
        assert "__url_query__" not in seen_headers
        assert seen_headers.get("user") == "tester"

    def test_auth_headers_merged_with_endpoint_headers(self):
        """adapter.build_auth_headers 返回的头与 Endpoint.headers 合并到请求。"""

        class HAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                return Endpoint(url="http://h/x", method="GET",
                                auth="custom", headers={"X-Base": "1"})

            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                return {"X-Auth": "2"}
        card = _card("x")
        seen = {}

        def fake(method, url, headers=None, **kw):
            seen.update(headers or {})
            return _ok({})
        with patch("api_console.card_invoker.http_request", fake):
            invoke_card(card, {}, HAdapter(), {}, {})
        assert seen.get("X-Base") == "1"
        assert seen.get("X-Auth") == "2"


class TestResolveCallMode:
    """主干 resolve_call_mode 仅做委托：调 adapter.resolve_call_mode 透传结果。

    「有 port→internal 否则 gateway」这类平台特定决策归各平台 adapter
    （见 easyops adapter 测试），主干不认识任何 mode 名，只负责转发。
    """

    def test_delegates_to_adapter(self):
        from api_console.card_invoker import resolve_call_mode
        from types import SimpleNamespace

        class Stub:
            def resolve_call_mode(self, card, contracts):
                # 记录主干是否把 card/contracts 原样透传给 adapter
                self.seen = (card, contracts)
                return "adapter_decided_mode"

        stub = Stub()
        card = SimpleNamespace(endpoint={"contract_ref": "k", "mode": "x"})
        result = resolve_call_mode(stub, card, {"k": {"port": 9}})
        assert result == "adapter_decided_mode"          # 透传 adapter 返回值
        assert stub.seen == (card, {"k": {"port": 9}})   # card/contracts 原样传入


def _file_card(name, file_keys, other_keys=None):
    """构造含 type:file 参数的卡片。file_keys/other_keys 为参数名列表。"""
    props = {k: {"type": "file", "desc": ""} for k in file_keys}
    props.update({k: {"type": "string", "desc": ""} for k in (other_keys or [])})
    c = _card(name, method="POST")
    c.request_properties = props
    c.request_required = file_keys
    return c


class TestMultipartRequest:
    """含 type:file 参数 → multipart（files+data），否则维持 json。"""

    def test_file_param_builds_multipart(self, tmp_path):
        pkg = tmp_path / "pkg.tar.gz"
        pkg.write_bytes(b"\x1f\x8b fake-tar")
        card = _file_card("importSuite", ["file"], ["note"])
        captured = {}

        def fake_http(method, url, headers=None, **kw):
            captured.update(kw)
            return _ok({"imported": True})

        with patch("api_console.card_invoker.http_request", side_effect=fake_http):
            invoke_card(card, {"file": str(pkg), "note": "n1"},
                        FakeAdapter(), {}, {})
        assert "files" in captured and "data" in captured
        assert "json" not in captured
        assert captured["data"] == {"note": "n1"}
        assert captured["files"]["file"].name == str(pkg)

    def test_file_param_dict_takes_file_path(self, tmp_path):
        """DAG 来的文件对象 dict：取 .file_path 打开。"""
        pkg = tmp_path / "pkg.tar.gz"
        pkg.write_bytes(b"\x1f\x8b x")
        card = _file_card("importSuite", ["file"])
        captured = {}

        def fake_http(method, url, headers=None, **kw):
            captured.update(kw)
            return _ok({})

        fobj = {"file_path": str(pkg), "size": 4, "content_type": "application/gzip"}
        with patch("api_console.card_invoker.http_request", side_effect=fake_http):
            invoke_card(card, {"file": fobj}, FakeAdapter(), {}, {})
        assert captured["files"]["file"].name == str(pkg)

    def test_no_file_param_stays_json(self):
        """回归：无 type:file 参数仍走 json body。"""
        card = _card("createThing", method="POST")
        card.request_properties = {"a": {"type": "string"}}
        captured = {}

        def fake_http(method, url, headers=None, **kw):
            captured.update(kw)
            return _ok({})

        with patch("api_console.card_invoker.http_request", side_effect=fake_http):
            invoke_card(card, {"a": "1"}, FakeAdapter(), {}, {})
        assert captured.get("json") == {"a": "1"}
        assert "files" not in captured

    def test_file_not_found_clear_error(self):
        card = _file_card("importSuite", ["file"])
        with pytest.raises(ValueError) as ei:
            invoke_card(card, {"file": "/nonexistent/x.tar.gz"},
                        FakeAdapter(), {}, {})
        assert "file" in str(ei.value) and "/nonexistent/x.tar.gz" in str(ei.value)

    def test_file_dict_missing_file_path_clear_error(self):
        """dict 缺 file_path 键：抛友好 ValueError，而非 open(None) 的 TypeError。"""
        card = _file_card("importSuite", ["file"])
        with pytest.raises(ValueError) as ei:
            invoke_card(card, {"file": {"size": 1, "content_type": "x"}},
                        FakeAdapter(), {}, {})
        assert "file" in str(ei.value)

    def test_multipart_strips_auth_content_type(self, tmp_path):
        """multipart 时剔除鉴权头里的 Content-Type（防覆盖 httpx boundary 头）。"""
        pkg = tmp_path / "pkg.tar.gz"
        pkg.write_bytes(b"\x1f\x8b fake")
        card = _file_card("importSuite", ["file"])
        captured = {}

        class JsonCTAdapter(FakeAdapter):
            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                return {"user": "u", "org": "1", "Content-Type": "application/json"}

        def fake_http(method, url, headers=None, **kw):
            captured["headers"] = headers or {}
            captured["kw"] = kw
            return _ok({})

        with patch("api_console.card_invoker.http_request", side_effect=fake_http):
            invoke_card(card, {"file": str(pkg)}, JsonCTAdapter(), {}, {})
        # multipart 分支：请求头不得带 application/json 的 Content-Type
        assert "files" in captured["kw"]
        ct = captured["headers"].get("Content-Type", "")
        assert "application/json" not in ct
        # 其余鉴权头保留
        assert captured["headers"].get("user") == "u"
        assert captured["headers"].get("org") == "1"

    def test_file_handles_closed_after_request(self, tmp_path):
        pkg = tmp_path / "pkg.tar.gz"
        pkg.write_bytes(b"\x1f\x8b x")
        card = _file_card("importSuite", ["file"])
        captured = {}

        def fake_http(method, url, headers=None, **kw):
            captured.update(kw)
            return _ok({})

        with patch("api_console.card_invoker.http_request", side_effect=fake_http):
            invoke_card(card, {"file": str(pkg)}, FakeAdapter(), {}, {})
        assert captured["files"]["file"].closed
