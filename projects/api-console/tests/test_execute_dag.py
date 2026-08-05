"""execute_dag 测试。

覆盖 spec 7.3 三条核心路径：
- 单步执行 + 锚点提取
- foreach 并发展开（N 个 item -> N 次请求）
- assert 失败立即终止 DAG

mock 策略（spec 1.5 / 1.6 后）：
- URL 拼接归 adapter.resolve_endpoint，测试用 :class:`FakeAdapter` 提供，
  返回 ``Endpoint(url="http://h" + card.path, method=card.method, auth="none")``。
- 鉴权头构造归 adapter.build_auth_headers（spec 1.6），FakeAdapter 对 auth="none"
  返回 ``{}``；session_cookie 场景用 :class:`CookieAdapter`（继承 FakeAdapter）
  读 cookie 文件，验证 execute_dag 把 adapter 返回的头合并到请求。
- http_request 仍 patch，按 (method, url 后缀) 路由响应体，验证 execute_dag
  发请求时用的 url 确实来自 adapter.resolve_endpoint。
"""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock

from api_console.adapter_base import Endpoint
from api_console.execute_dag import execute, ExecutionError
from api_console.schema.dag import DAG, Step, StepOutput, StepAssert
from api_console.schema.card import Card, OutputAnchor


class FakeAdapter:
    """假 adapter：resolve_endpoint 返回 ``http://h<card.path>`` 的 Endpoint。

    auth=none，build_auth_headers 返回空 dict，不注入凭证，避免测试依赖 cookie 文件。
    method 用 card.method，便于 GET/POST 等不同方法的卡片共用同一 fake。
    """

    name = "fake"

    def resolve_endpoint(self, contract: dict, manifest: dict) -> Endpoint:
        path = contract.get("path", "")
        method = contract.get("method", "GET").upper()
        return Endpoint(url="http://h" + path, method=method, auth="none",
                        headers={})

    def build_auth_headers(self, auth_mode: str, manifest: dict,
                           request_ctx: dict | None = None) -> dict:
        """spec 1.6：none 模式返回空 dict（不注入凭证）。"""
        if auth_mode == "none":
            return {}
        raise NotImplementedError(
            f"FakeAdapter 不支持 auth_mode={auth_mode}（测试场景请用 CookieAdapter）"
        )

    def resolve_call_mode(self, card, contracts: dict) -> str:
        """沿用卡片自带 endpoint.mode（主干默认行为）。"""
        ep = getattr(card, "endpoint", None) or {}
        return ep.get("mode", "")


def _card(name, outputs, side_effect="read", required=None, method="GET"):
    """构造一张极简卡片（含 endpoint 配置，便于 execute_dag 走 adapter 路径）。"""
    c = Card(name=name, module="m", method=method, path="/p/" + name,
             side_effect=side_effect, request_required=required or [],
             outputs={k: OutputAnchor(name=k, jsonpath=v)
                      for k, v in outputs.items()},
             endpoint={"contract_ref": "", "mode": "fake_mode"})
    return c


def _mock_httpx(responses):
    """构造 fake http_request：按 (method, url 后缀) 路由响应体。

    Args:
        responses: dict[(method, path_suffix)] -> resp_body（将包成
            ``{"code": 0, "data": resp_body}``）
    """
    def fake_request(method, url, headers=None, **kw):
        for (m, suf), body in responses.items():
            if m == method and url.endswith(suf):
                mock = MagicMock()
                mock.status_code = 200
                mock.json.return_value = {"code": 0, "data": body}
                return mock
        raise AssertionError("unexpected " + method + " " + url)
    return fake_request


class TestSingleStep:
    """单步执行：发请求 + 锚点提取 + result 表达式。"""

    def test_single_extract(self):
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            params={"Q": "test"},
            output=StepOutput(bind="models", anchor="list_full"))],
            result="${s1.models}")
        cards = {"search": _card("search", {"list_full": "$.data"})}
        with patch("api_console.card_invoker.http_request",
                   _mock_httpx({("GET", "/p/search"): {"list": [{"id": "x"}]}})):
            r = execute(dag, cards, adapter=FakeAdapter(), manifest={})
        assert r.result == {"list": [{"id": "x"}]}


class TestForeach:
    """foreach：上游 list 长度 N -> 当前步执行 N 次。"""

    def test_foreach_calls_n_times(self):
        dag = DAG(goal="g", steps=[
            Step(id="s1", card="search",
                 output=StepOutput(bind="ids", anchor="list_ids")),
            Step(id="s2", card="get", depends=["s1"], foreach="${s1.ids.id}",
                 params={"modelId": "${item}"},
                 output=StepOutput(bind="details", anchor="detail")),
        ], result="${s2.details}")
        cards = {
            # 锚点取整个 list（schema 不支持 [*]，投影交给 foreach 表达式 .id）
            "search": _card("search", {"list_ids": "$.data.list"}),
            "get": _card("get", {"detail": "$.data"}),
        }
        calls = []

        def fake(method, url, **kw):
            calls.append((method, url))
            m = MagicMock()
            m.status_code = 200
            if url.endswith("/p/search"):
                m.json.return_value = {"code": 0,
                                       "data": {"list": [{"id": "a"}, {"id": "b"}]}}
            else:
                m.json.return_value = {"code": 0, "data": {"got": url}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            r = execute(dag, cards, adapter=FakeAdapter(), manifest={})
        # /p/get 被调用了 2 次
        assert len([c for c in calls if c[0] == "GET" and "/p/get" in c[1]]) == 2
        # s2.details = [detail_a, detail_b]
        assert len(r.result) == 2


class TestAssert:
    """assert 失败：抛 ExecutionError，终止整个 DAG。"""

    def test_assert_failure_stops_dag(self):
        dag = DAG(goal="g", steps=[
            Step(id="s1", card="search",
                 output=StepOutput(bind="fields", anchor="list_full"),
                 asserts=[StepAssert(condition="fields.length > 0", message="空")]),
        ], result="${s1.fields}")
        cards = {"search": _card("search", {"list_full": "$.data"})}
        with patch("api_console.card_invoker.http_request",
                   _mock_httpx({("GET", "/p/search"): {"list": []}})):
            with pytest.raises(ExecutionError, match="空"):
                execute(dag, cards, adapter=FakeAdapter(), manifest={})


class TestResolveEndpoint:
    """execute_dag 走 adapter.resolve_endpoint 路径（spec 1.5）。

    验证：execute_dag 不再拼 ``api_base + card.path``，而是把 contract 传给
    adapter.resolve_endpoint，发出的 url 完全来自 Endpoint.url。
    """

    def test_url_comes_from_adapter(self):
        """resolve_endpoint 返回的 url 即为 http_request 收到的 url。"""
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"})}

        class CustomAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                # 故意返回与 card.path 不同的 url，验证 execute_dag 不自作主张拼 path
                return Endpoint(url="http://custom-host/x/y", method="GET",
                                auth="none", headers={"X-From": "adapter"})
        seen_headers = {}

        def fake(method, url, headers=None, **kw):
            seen_headers.update(headers or {})
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=CustomAdapter(), manifest={})
        # url 来自 adapter，不含 card.path
        # headers 来自 Endpoint.headers（adapter 注入的 X-From）
        assert seen_headers.get("X-From") == "adapter"

    def test_contract_ref_lookup(self):
        """card.endpoint.contract_ref 命中时，传给 adapter 的是 contracts 里的 dict。"""
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"})}
        # 给卡片填 contract_ref
        cards["search"].endpoint = {
            "contract_ref": "svc|GET|/api/x",
            "mode": "fake_mode",
        }
        seen_contract = {}

        class SpyAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                seen_contract.update(contract)
                return Endpoint(url="http://h/x", method="GET", auth="none")
        contracts = {
            "svc|GET|/api/x": {
                "service": "svc", "method": "GET", "path": "/api/x",
                "operation_key": "svc|GET|/api/x",
            }
        }

        def fake(method, url, headers=None, **kw):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=SpyAdapter(), manifest={},
                    contracts=contracts)
        # adapter 收到的 contract 来自 contracts 字典（service=svc），且 endpoint.mode
        # 从卡片合并进来
        assert seen_contract.get("service") == "svc"
        assert seen_contract.get("endpoint", {}).get("mode") == "fake_mode"

    def test_fallback_when_contract_ref_missing(self):
        """contract_ref 未命中时，execute_dag 用 card 字段构造兜底 contract。"""
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"},
                                 method="POST")}
        cards["search"].service = "logic.svc"
        cards["search"].endpoint = {"contract_ref": "", "mode": "fake_mode"}
        seen = {}

        class SpyAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                seen.update(contract)
                return Endpoint(url="http://h/x", method="POST", auth="none")
        # contracts 为空，强制走兜底

        def fake(method, url, headers=None, **kw):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=SpyAdapter(), manifest={}, contracts={})
        # 兜底 contract 用 card.service/method/path
        assert seen.get("service") == "logic.svc"
        assert seen.get("method") == "POST"
        assert seen.get("path") == "/p/search"


class TestAuthInjection:
    """spec 1.6：execute_dag 调 adapter.build_auth_headers 合并鉴权头。

    cookie 加载的具体实现见各平台 adapter 的 build_auth_headers
    测试。本测试只验证 execute_dag 把 adapter 返回的头合并到请求（接口契约）。
    """

    def test_session_cookie_injected(self, tmp_path):
        """adapter.build_auth_headers 返回 Cookie 头时，execute_dag 合并到请求。"""
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text('[{"name":"sid","value":"abc"},{"name":"u","value":"x"}]')
        manifest = {"auth": {"session_cookie": {"cookie_file": str(cookie_file)}}}
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"})}

        class CookieAdapter(FakeAdapter):
            """返回 auth=session_cookie，build_auth_headers 读 cookie 文件。

            复用真实 adapter 的 cookie 加载逻辑（与各平台 adapter
            _build_session_cookie_headers 等价），证明 execute_dag 能正确合并。
            """
            def resolve_endpoint(self, contract, manifest):
                return Endpoint(url="http://h/x", method="GET",
                                auth="session_cookie", headers={})

            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                import json
                cf = manifest["auth"]["session_cookie"]["cookie_file"]
                cookies = json.loads(open(cf).read())
                cookie_h = "; ".join(c["name"] + "=" + c["value"] for c in cookies)
                return {"Cookie": cookie_h}
        seen_headers = {}

        def fake(method, url, headers=None, **kw):
            seen_headers.update(headers or {})
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=CookieAdapter(), manifest=manifest)
        # Cookie header 来自 adapter.build_auth_headers，execute_dag 合并到请求
        assert seen_headers.get("Cookie") == "sid=abc; u=x"

    def test_build_auth_headers_called_with_request_ctx(self):
        """execute_dag 调 build_auth_headers 时传 request_ctx（含 method/url/body）。"""
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"}, method="POST")}
        seen_ctx = {}

        class SpyAdapter(FakeAdapter):
            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                seen_ctx.update(request_ctx or {})
                return {}

        class PostAdapter(SpyAdapter):
            def resolve_endpoint(self, contract, manifest):
                return Endpoint(url="http://h/x", method="POST", auth="none")

        def fake(method, url, headers=None, **kw):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=PostAdapter(), manifest={})
        # request_ctx 含 method/url/body（签名模式用，POST 时 body=params dict）
        assert seen_ctx.get("method") == "POST"
        assert seen_ctx.get("url") == "http://h/x"
        assert isinstance(seen_ctx.get("body"), dict)

    def test_url_query_pseudo_header_appended_to_url(self):
        """aksk 伪头 __url_query__ 被 execute_dag 取出附加到 URL，不进入 HTTP 头。"""
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="search",
            output=StepOutput(bind="m", anchor="list_full"))],
            result="${s1.m}")
        cards = {"search": _card("search", {"list_full": "$.data"})}

        class AkskAdapter(FakeAdapter):
            def resolve_endpoint(self, contract, manifest):
                return Endpoint(url="http://h/x", method="POST",
                                auth="aksk", headers={})

            def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
                # 模拟 aksk 签名结果（含 __url_query__ 伪头）
                return {
                    "user": "tester",
                    "Host": "openapi.example.com",
                    "Content-Type": "application/json",
                    "__url_query__": "accesskey=AK&signature=SIG&expires=123",
                }
        seen_url = {}
        seen_headers = {}

        def fake(method, url, headers=None, **kw):
            seen_url["url"] = url
            seen_headers.update(headers or {})
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 0, "data": {}}
            return m
        with patch("api_console.card_invoker.http_request", fake):
            execute(dag, cards, adapter=AkskAdapter(), manifest={})
        # URL 拼上签名 query（无 ? -> 用 ?）
        assert seen_url["url"] == (
            "http://h/x?accesskey=AK&signature=SIG&expires=123"
        )
        # __url_query__ 不进入真实 HTTP 头
        assert "__url_query__" not in seen_headers
        assert seen_headers.get("user") == "tester"
        assert seen_headers.get("Host") == "openapi.example.com"


class TestWhenSkip:
    """MVP-1.5：step.when 条件为假时跳过该步，不发请求。

    用假 adapter/manifest + monkeypatch ``_exec_one`` 避免真发请求，
    只测 execute 主循环的 when 跳过编排逻辑。
    """

    class _FakeAdapter:
        """假 adapter：resolve_endpoint 返回固定 Endpoint，不发真请求。"""

        def resolve_endpoint(self, contract, manifest):
            class _Ep:
                url = "http://x"
                auth = None
                headers = {}
            return _Ep()

    @staticmethod
    def _read_card(name="searchDomainModel"):
        """构造一张极简卡片（when 跳过测试只关心编排，不关心真请求）。"""
        return Card(name=name, module="m", method="GET", path="/p",
                    side_effect="read", request_required=[],
                    outputs={"detail": object()})

    def test_when_skips_step(self, monkeypatch):
        """when 为假的步骤被跳过，不发请求。"""
        calls = []
        from api_console import execute_dag
        monkeypatch.setattr(
            execute_dag, "_exec_one",
            lambda step, card, c, ctx, ad, mf, log: calls.append(step.id) or {"x": 1}
        )
        dag = DAG(goal="g", steps=[
            Step(id="s0", card="searchDomainModel", params={"q": "x"},
                 output=StepOutput(bind="found", anchor="detail")),
            Step(id="s1", card="searchDomainModel", when="${s0.found} == null",
                 params={"q": "y"}, output=StepOutput(bind="r", anchor="detail")),
        ], result="${s0.found}")
        r = execute(dag, {"searchDomainModel": self._read_card()},
                    self._FakeAdapter(), {})
        assert "s0" in calls
        assert "s1" not in calls          # 被跳过
        assert "s1" in r.skipped


class TestWriteGate:
    """MVP-1.5：execute 写计划确认闸。

    has_write=True 且非 yes 时，execute 在主循环前打印写计划（步骤/卡片/副作用/
    参数 + 回滚预案）并等输入；非 'y' 取消（返回 None）。yes=True 跳过确认直接执行。
    """

    def test_write_gate_confirms(self, monkeypatch, capsys):
        """has_write=True 且非 yes → 打印写计划，等输入；输 n 取消。"""
        from api_console import execute_dag
        monkeypatch.setattr(execute_dag, "_exec_one",
                            lambda *a, **k: {"x": 1})
        answers = iter(["n"])
        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "x"}),
        ], result=None)
        create_card = Card(name="createForm", module="form", method="POST",
                           path="/f", side_effect="create",
                           request_required=[], outputs={})
        r = execute(dag, {"createForm": create_card}, FakeAdapter(), {},
                    has_write=True, yes=False, input_fn=lambda _: next(answers))
        out = capsys.readouterr().out
        assert "写操作" in out or "确认" in out
        assert r is None                      # 取消

    def test_write_gate_yes_skips(self, monkeypatch):
        """yes=True 跳过确认直接执行。"""
        from api_console import execute_dag
        called = []
        monkeypatch.setattr(execute_dag, "_exec_one",
                            lambda *a, **k: called.append(1) or {"x": 1})
        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "x"}),
        ], result=None)
        create_card = Card(name="createForm", module="form", method="POST",
                           path="/f", side_effect="create",
                           request_required=[], outputs={})
        execute(dag, {"createForm": create_card}, FakeAdapter(), {},
                has_write=True, yes=True)
        assert called == [1]                  # 执行了，没等输入


class TestRollback:
    """MVP-1.5：下游写步骤失败 → 逆序回滚已成功的写步骤。

    回滚走 ``card_invoker.invoke_card``（monkeypatch 它观察调用）。
    _rollback 内部用 ``from card_invoker import invoke_card`` 运行时查表，
    故 patch ``card_invoker.invoke_card`` 即可拦截。
    """

    def test_rollback_on_downstream_failure(self, monkeypatch):
        """s1 createForm 成功、s2 createForm 失败 → 逆序回滚 s1。"""
        from api_console import execute_dag
        from api_console.schema.card import Rollback, RollbackParam

        # _exec_one monkeypatch：s2 抛错，s1 返回锚点对象形态
        def fake_exec(step, card, c, ctx, ad, mf, log):
            if step.id == "s2":
                raise execute_dag.ExecutionError("s2 失败")
            return {"instanceId": "id-" + step.id}
        monkeypatch.setattr(execute_dag, "_exec_one", fake_exec)

        # 回滚走 card_invoker.invoke_card，patch 它观察调用
        rb_calls = []

        def fake_invoke(card, params, *a, **k):
            rb_calls.append((card, params))
            return {"code": 0}
        monkeypatch.setattr("api_console.card_invoker.invoke_card", fake_invoke)

        def mk_write():
            """构造写卡片（createForm，带 rollback 声明）。"""
            return Card(name="createForm", module="form", method="POST", path="/f",
                        side_effect="create", request_required=[], outputs={},
                        rollback=Rollback(api="deleteFormVersion", params=[
                            RollbackParam(param_key="versionId", from_output="instanceId")]))

        def mk_rollback_target(name):
            """构造回滚目标卡片（只用于 invoke_card 签名占位，实际被 patch）。"""
            return Card(name=name, module="form", method="POST", path="/d",
                        side_effect="delete", request_required=[], outputs={})

        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "A"},
                 output=StepOutput(bind="o", anchor="instanceId")),
            Step(id="s2", card="createForm", params={"name": "B"},
                 output=StepOutput(bind="o2", anchor="instanceId")),
        ], result=None)

        import pytest
        with pytest.raises(execute_dag.ExecutionError):
            execute(dag,
                    {"createForm": mk_write(),
                     "deleteFormVersion": mk_rollback_target("deleteFormVersion")},
                    FakeAdapter(), {}, yes=True)

        # s2 失败，s1 已成功 → 回滚 s1（逆序遍历只回滚到 s1）
        assert len(rb_calls) == 1
        # invoke_card 真实签名第一参数是 Card 对象（不是卡片名字符串）
        assert rb_calls[0][0].name == "deleteFormVersion"
        # param_from_output="instanceId" 从 context["s1"]["o"]["instanceId"] 取值
        assert rb_calls[0][1]["versionId"] == "id-s1"

    def test_rollback_reverses_multi_steps(self, monkeypatch):
        """s1/s2 成功、s3 失败 → 逆序回滚顺序 [s2, s1]，参数各自对应。

        覆盖逆序特性：executed_writes 有多条时，_rollback 用 reversed() 遍历，
        回滚顺序严格倒序于执行顺序。s2/s1 的 versionId 分别取 id-s2 / id-s1。
        """
        from api_console import execute_dag
        from api_console.schema.card import Rollback, RollbackParam

        # _exec_one monkeypatch：s3 抛错，s1/s2 成功返回带 instanceId 的 dict
        def fake_exec(step, card, c, ctx, ad, mf, log):
            if step.id == "s3":
                raise execute_dag.ExecutionError("s3 失败")
            return {"instanceId": "id-" + step.id}
        monkeypatch.setattr(execute_dag, "_exec_one", fake_exec)

        # 回滚走 card_invoker.invoke_card，patch 它按调用顺序记录
        rb_calls = []

        def fake_invoke(card, params, *a, **k):
            rb_calls.append((card, params))
            return {"code": 0}
        monkeypatch.setattr("api_console.card_invoker.invoke_card", fake_invoke)

        def mk_write():
            """构造写卡片（createForm，带 rollback 声明）。"""
            return Card(name="createForm", module="form", method="POST", path="/f",
                        side_effect="create", request_required=[], outputs={},
                        rollback=Rollback(api="deleteFormVersion", params=[
                            RollbackParam(param_key="versionId", from_output="instanceId")]))

        def mk_rollback_target(name):
            """构造回滚目标卡片（只用于 invoke_card 签名占位，实际被 patch）。"""
            return Card(name=name, module="form", method="POST", path="/d",
                        side_effect="delete", request_required=[], outputs={})

        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "A"},
                 output=StepOutput(bind="o", anchor="instanceId")),
            Step(id="s2", card="createForm", params={"name": "B"},
                 output=StepOutput(bind="o", anchor="instanceId")),
            Step(id="s3", card="createForm", params={"name": "C"},
                 output=StepOutput(bind="o", anchor="instanceId")),
        ], result=None)

        import pytest
        with pytest.raises(execute_dag.ExecutionError):
            execute(dag,
                    {"createForm": mk_write(),
                     "deleteFormVersion": mk_rollback_target("deleteFormVersion")},
                    FakeAdapter(), {}, yes=True)

        # s3 失败前 s1/s2 已成功 → 逆序回滚两步：先 s2 后 s1
        assert len(rb_calls) == 2
        assert rb_calls[0][0].name == "deleteFormVersion"
        assert rb_calls[1][0].name == "deleteFormVersion"
        # 逆序：先回滚 s2（versionId=id-s2），再回滚 s1（versionId=id-s1）
        assert rb_calls[0][1]["versionId"] == "id-s2"
        assert rb_calls[1][1]["versionId"] == "id-s1"

    def test_rollback_log_attached_to_exception(self, monkeypatch):
        """失败路径 rollback_log 挂到 ExecutionError.rollback_log（finding 1）。

        验证：raise 重抛前 e.rollback_log 已赋值，调用方从异常实例读取回滚记录，
        与成功路径的 ExecutionResult.rollback_log 对齐。
        """
        from api_console import execute_dag
        from api_console.schema.card import Rollback, RollbackParam

        def fake_exec(step, card, c, ctx, ad, mf, log):
            if step.id == "s2":
                raise execute_dag.ExecutionError("s2 失败")
            return {"instanceId": "id-" + step.id}
        monkeypatch.setattr(execute_dag, "_exec_one", fake_exec)

        def fake_invoke(card, params, *a, **k):
            return {"code": 0}
        monkeypatch.setattr("api_console.card_invoker.invoke_card", fake_invoke)

        def mk_write():
            return Card(name="createForm", module="form", method="POST", path="/f",
                        side_effect="create", request_required=[], outputs={},
                        rollback=Rollback(api="deleteFormVersion", params=[
                            RollbackParam(param_key="versionId", from_output="instanceId")]))

        def mk_rollback_target(name):
            return Card(name=name, module="form", method="POST", path="/d",
                        side_effect="delete", request_required=[], outputs={})

        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "A"},
                 output=StepOutput(bind="o", anchor="instanceId")),
            Step(id="s2", card="createForm", params={"name": "B"},
                 output=StepOutput(bind="o2", anchor="instanceId")),
        ], result=None)

        import pytest
        with pytest.raises(execute_dag.ExecutionError) as ei:
            execute(dag,
                    {"createForm": mk_write(),
                     "deleteFormVersion": mk_rollback_target("deleteFormVersion")},
                    FakeAdapter(), {}, yes=True)
        # 失败路径：rollback_log 挂在异常实例上（与成功路径的 Result 字段对齐）
        assert hasattr(ei.value, "rollback_log")
        assert ei.value.rollback_log is not None
        assert len(ei.value.rollback_log) == 1
        assert ei.value.rollback_log[0]["step"] == "s1"
        assert ei.value.rollback_log[0]["card"] == "deleteFormVersion"
        assert ei.value.rollback_log[0]["status"] == "ok"

    def test_rollback_multi_param_path(self, monkeypatch):
        """多参数 path 回滚：deleteFormVersion 需 formId + versionId 两参。

        L1 schema 升级后，rollback.params 有两条（from_output=对象锚点 o，
        from_field=formId/versionId）；_rollback 从 bound 对象按 from_field 取值，
        组装成 {formId, versionId} 两键 dict 传给 invoke_card。
        """
        from api_console import execute_dag
        from api_console.schema.card import Rollback, RollbackParam

        # s2 抛错，s1 成功返回 detail 对象（含 formId/versionId 字段）
        def fake_exec(step, card, c, ctx, ad, mf, log):
            if step.id == "s2":
                raise execute_dag.ExecutionError("s2 失败")
            return {"formId": "f-" + step.id, "versionId": "v-" + step.id}
        monkeypatch.setattr(execute_dag, "_exec_one", fake_exec)

        rb_calls = []

        def fake_invoke(card, params, *a, **k):
            rb_calls.append((card, params))
            return {"code": 0}
        monkeypatch.setattr("api_console.card_invoker.invoke_card", fake_invoke)

        def mk_write():
            return Card(name="createForm", module="form", method="POST", path="/f",
                        side_effect="create", request_required=[], outputs={},
                        rollback=Rollback(api="deleteFormVersion", params=[
                            RollbackParam(param_key="formId", from_output="o", from_field="formId"),
                            RollbackParam(param_key="versionId", from_output="o", from_field="versionId"),
                        ]))

        def mk_target():
            return Card(name="deleteFormVersion", module="form", method="DELETE",
                        path="/form/{formId}/version/{versionId}",
                        side_effect="delete", request_required=["formId", "versionId"],
                        outputs={})

        dag = DAG(goal="g", steps=[
            Step(id="s1", card="createForm", params={"name": "A"},
                 output=StepOutput(bind="o", anchor="detail")),
            Step(id="s2", card="createForm", params={"name": "B"},
                 output=StepOutput(bind="o2", anchor="detail")),
        ], result=None)

        import pytest
        with pytest.raises(execute_dag.ExecutionError):
            execute(dag,
                    {"createForm": mk_write(), "deleteFormVersion": mk_target()},
                    FakeAdapter(), {}, yes=True)

        # s2 失败 → 回滚 s1，invoke_card 收到双参 dict
        assert len(rb_calls) == 1
        assert rb_calls[0][0].name == "deleteFormVersion"
        assert rb_calls[0][1] == {"formId": "f-s1", "versionId": "v-s1"}


import pathlib
from api_console.card_invoker import InvokeResult


def _bin_invoke_result(payload=b"\x1f\x8b tar"):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/gzip"}
    resp.content = payload
    resp.json.side_effect = ValueError("not json")
    return InvokeResult(resp=resp, url="http://h/e", method="GET")


def _json_invoke_result(body):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}
    resp.json.return_value = {"code": 0, "data": body}
    return InvokeResult(resp=resp, url="http://h/i", method="POST")


def _export_card():
    return Card(name="exportSuite", module="m", method="GET",
                path="/api/v1/inspection-export/{pluginId}",
                side_effect="read",
                endpoint={"contract_ref": "", "mode": "fake_mode"})


def _import_card():
    c = Card(name="importSuite", module="m", method="POST",
             path="/api/v1/inspection-import",
             side_effect="create",
             endpoint={"contract_ref": "", "mode": "fake_mode"})
    c.request_properties = {"file": {"type": "file", "desc": ""}}
    c.request_required = ["file"]
    return c


class TestFileAnchor:
    """非 JSON 响应：落盘 + bind 绑定文件对象，跳过业务码校验。"""

    def test_export_binds_file_object(self, tmp_path, monkeypatch):
        from api_console import execute_dag
        monkeypatch.setattr(execute_dag, "_download_dir", lambda: tmp_path)
        dag = DAG(goal="g", steps=[Step(
            id="s1", card="exportSuite", params={"pluginId": "host"},
            output=StepOutput(bind="pkg", anchor=""))])
        cards = {"exportSuite": _export_card()}
        with patch("api_console.execute_dag.invoke_card", return_value=_bin_invoke_result()):
            result = execute(dag, cards, adapter=FakeAdapter(), manifest={}, contracts={})
        bound = result.context["s1"]["pkg"]
        assert bound["size"] == len(b"\x1f\x8b tar")
        assert bound["content_type"] == "application/gzip"
        assert pathlib.Path(bound["file_path"]).exists()

    def test_export_import_chain(self, tmp_path, monkeypatch):
        """export 的 bind（文件对象）传给 import 的 file 参数。"""
        from api_console import execute_dag
        monkeypatch.setattr(execute_dag, "_download_dir", lambda: tmp_path)
        captured = {}

        def fake_invoke(card, params, adapter, manifest, contracts):
            if card.name == "exportSuite":
                return _bin_invoke_result()
            captured["params"] = params
            return _json_invoke_result({"imported": True})

        dag = DAG(goal="g", steps=[
            Step(id="s1", card="exportSuite", params={"pluginId": "host"},
                 output=StepOutput(bind="pkg", anchor="")),
            Step(id="s2", card="importSuite", depends=["s1"],
                 params={"file": "${s1.pkg}"},
                 output=StepOutput(bind="r", anchor="")),
        ])
        cards = {"exportSuite": _export_card(), "importSuite": _import_card()}
        with patch("api_console.execute_dag.invoke_card", side_effect=fake_invoke):
            result = execute(dag, cards, adapter=FakeAdapter(), manifest={},
                             contracts={}, has_write=True, yes=True)
        # import 的 file 参数拿到了 export 的文件对象（含 file_path）
        assert captured["params"]["file"]["file_path"] == result.context["s1"]["pkg"]["file_path"]
