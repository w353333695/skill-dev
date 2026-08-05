"""path 归一化 + gateway 剥离 + 三级优先级测试。"""
from __future__ import annotations
import pytest
from api_console.path_align import normalize_path, make_operation_key, strip_gateway, align_path
from api_console.schema.contracts import BackendContract


class TestNormalize:
    def test_colon_to_brace(self):
        assert normalize_path("/api/x/:instanceId") == "/api/x/{instanceId}"

    def test_brace_unchanged(self):
        assert normalize_path("/api/x/{modelId}") == "/api/x/{modelId}"

    def test_no_param(self):
        assert normalize_path("/api/x") == "/api/x"

    def test_multi_colon(self):
        assert normalize_path("/a/:x/:y") == "/a/{x}/{y}"


class TestOperationKey:
    def test_three_tuple(self):
        assert make_operation_key("svc", "GET", "/a/{x}") == "svc|GET|/a/{x}"


class TestStripGateway:
    RULES = {"strip_prefix": ["/next", "/api/gateway/{service}"],
             "service_map": {"logic.flowable_service": "flowable_service"}}

    def test_strip_ok(self):
        p = "/next/api/gateway/logic.flowable_service/api/flowable_service/v1/domain_model"
        assert strip_gateway(p, self.RULES) == "/api/flowable_service/v1/domain_model"

    def test_strip_fail_returns_none(self):
        assert strip_gateway("/unrelated/path", self.RULES) is None


class TestAlignPath:
    def _contract(self, path, service="flowable_service", method="GET"):
        return BackendContract(
            operation_key=make_operation_key(service, method, path),
            method=method, path=path, raw_paths={"backend": path, "frontend": ""},
            path_source="backend_contract", path_confidence="high",
            service=service, request={"fields": []}, response={"fields": []})

    def test_priority1_backend_contract(self):
        contracts = [self._contract("/api/x/{id}")]
        rules = {"strip_prefix": [], "service_map": {}}
        path, src, conf, matched = align_path(
            "/next/api/gateway/logic.flowable_service/api/x/{id}",
            "flowable_service", "GET", contracts, rules)
        assert path == "/api/x/{id}"
        assert src == "backend_contract" and conf == "high"
        assert matched == "flowable_service"

    def test_priority2_gateway_strip(self):
        rules = {"strip_prefix": ["/next", "/api/gateway/{service}"],
                 "service_map": {"logic.flowable_service": "flowable_service"}}
        path, src, conf, matched = align_path(
            "/next/api/gateway/logic.flowable_service/api/x", "flowable_service", "GET", [], rules)
        assert path == "/api/x"
        assert src == "gateway_strip" and conf == "medium"
        assert matched == ""

    def test_priority3_frontend_raw(self):
        path, src, conf, matched = align_path("/unrelated", "svc", "GET", [], {"strip_prefix": [], "service_map": {}})
        assert path == "/unrelated"
        assert src == "frontend_raw" and conf == "low"
        assert matched == ""


class TestPlaceholderWildcard:
    """占位符通配：前端 {a} vs 后端 {b} 同位置按占位符通配（不看参数名）。"""

    def _contract(self, path, service="logic.form", method="GET"):
        return BackendContract(
            operation_key=make_operation_key(service, method, path),
            method=method, path=path, raw_paths={"backend": path, "frontend": ""},
            path_source="backend_contract", path_confidence="high",
            service=service, request={"fields": []}, response={"fields": []})

    RULES = {"strip_prefix": ["/next/api/gateway/logic.form"],
             "service_map": {"logic.form": "logic.form"}}

    def test_placeholder_wildcard_matches_renamed_param(self):
        """前端 {modelId} vs 后端 {instanceId} 占位符通配 → 命中 backend_contract/high。"""
        contract = self._contract("/api/form/{instanceId}/version")
        # 前端 gateway_path 剥离后 = /api/form/{modelId}/version
        r = align_path("/next/api/gateway/logic.form/api/form/{modelId}/version",
                       service="logic.form", method="GET",
                       contracts=[contract], rules=self.RULES)
        _, source, conf, _ = r
        assert source == "backend_contract"
        assert conf == "high"
        assert r[3] == "logic.form"

    def test_placeholder_count_mismatch_still_fails(self):
        """占位符数量（段数）不同 → 仍降级（不误匹配）。"""
        contract = self._contract("/api/form/{a}/{b}")
        r = align_path("/next/api/gateway/logic.form/api/form/{a}",
                       service="logic.form", method="GET",
                       contracts=[contract], rules=self.RULES)
        _, source, _, _ = r
        assert source != "backend_contract"   # 段数不同，不命中契约


class TestConcreteVsPlaceholder:
    """具体值 vs 占位符对齐：objectId/instanceId 占位符按强先验形态校验。"""

    def _contract(self, path, service="logic.cmdb.service", method="POST"):
        return BackendContract(
            operation_key=make_operation_key(service, method, path),
            method=method, path=path, raw_paths={"backend": path, "frontend": ""},
            path_source="backend_contract", path_confidence="high",
            service=service, request={"fields": []}, response={"fields": []})

    RULES = {"strip_prefix": ["/next", "/api/gateway/{service}"],
             "service_map": {}}

    def test_objectId_concrete_value_aligns(self):
        """前端具体值 SOME_MODEL@VENDOR 对后端 {objectId} → 命中 backend_contract/high。

        典型场景：录制路径 path 参数位是真实业务值，后端契约同位是占位符。
        """
        contract = self._contract("/object/{objectId}/instance/_search")
        r = align_path("/next/api/gateway/cmdb.instance.PostSearch/"
                       "object/SOME_MODEL@VENDOR/instance/_search",
                       service="cmdb.instance.PostSearch", method="POST",
                       contracts=[contract], rules=self.RULES)
        path, source, conf, matched = r
        assert source == "backend_contract"
        assert path == "/object/{objectId}/instance/_search"
        assert conf == "high"
        assert matched == "logic.cmdb.service"

    def test_objectId_literal_segment_not_misaligned(self):
        """前端字面段 search_collect（不符合 objectId 形态）不误配进 {objectId}。

        强先验消歧：/object/search_collect 不应对齐到 /object/{objectId}。
        """
        contract = self._contract("/object/{objectId}")
        r = align_path("/next/api/gateway/svc/object/search_collect",
                       service="svc", method="GET",
                       contracts=[contract], rules=self.RULES)
        _, source, _, _ = r
        assert source != "backend_contract"

    def test_unknown_placeholder_does_not_match_literal(self):
        """未登记形态的占位符名（如 {toolId}）不通配具体值——只与占位符匹配。

        防止 {toolId} 错配字面段（如 batch/execution）造成 1A 多义误命中。
        """
        contract = self._contract("/tools/{toolId}", method="GET")
        # {toolId} vs abc-123（字面值）→ 不通配，不命中契约
        r = align_path("/next/api/gateway/svc/tools/abc-123",
                       service="svc", method="GET",
                       contracts=[contract], rules=self.RULES)
        _, source, _, _ = r
        assert source != "backend_contract"
        # {toolId} vs {otherId}（双占位符）→ 通配，命中
        contract2 = self._contract("/tools/{toolId}", method="GET")
        r2 = align_path("/next/api/gateway/svc/tools/{anyId}",
                        service="svc", method="GET",
                        contracts=[contract2], rules=self.RULES)
        assert r2[1] == "backend_contract"

    def test_instanceId_shape_check(self):
        """instanceId 占位符要求对端为 13 位十六进制；非该形态判不匹配。"""
        contract = self._contract("/object/USER/instance/{instanceId}", method="GET")
        # 13 位 hex → 通配
        r = align_path("/next/api/gateway/svc/object/USER/instance/0a1b2c3d4e5f6",
                       service="svc", method="GET",
                       contracts=[contract], rules=self.RULES)
        assert r[1] == "backend_contract"
        # 非 13 位 hex（普通词）→ 不匹配
        r2 = align_path("/next/api/gateway/svc/object/USER/instance/notanid",
                        service="svc", method="GET",
                        contracts=[contract], rules=self.RULES)
        assert r2[1] != "backend_contract"
