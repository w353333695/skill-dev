"""register_cards extract + commit 测试。

extract 阶段对齐用的 contracts 由 ``_fake_contracts`` 构造，service/path 与
真实 ``platforms/<platform>/sources/backend/parsed/contracts.yaml`` 中的
domain_model 契约保持一致（service=``logic.flowable_service``，path 已归一化
为 brace style），用于验证前端 openapi gateway_path → 后端契约的对齐逻辑。
"""
from __future__ import annotations
from pathlib import Path

import pytest
import yaml

from api_console.register_cards import (
    extract, commit, rebuild_index,
    _safe_fallback_name, _gen_outputs_from_contract,
)

FIX = Path(__file__).parent / "fixtures"
OPENAPI = FIX / "openapi_domain_model.yaml"


def _fake_contracts():
    """造一份对齐用的 contracts（与真实 contracts.yaml 中 domain_model 一致）。

    真实契约 service 名带 ``logic.`` 前缀（即 gateway_path 中 ``/api/gateway/<这段>``），
    path 为已归一化的后端真实路径。前端 openapi 中 ``{modelId}`` 与契约
    ``{instanceId}`` 参数名不同——为聚焦 extract/commit 流程测试，这里让
    契约 path 与前端 openapi 参数名保持一致（真实 path 参数名差异由 LLM
    review/后续 Task 处理）。
    """
    from api_console.schema.contracts import BackendContract

    return [
        BackendContract(
            operation_key="logic.flowable_service|POST|/api/flowable_service/v1/domain_model",
            method="POST",
            path="/api/flowable_service/v1/domain_model",
            raw_paths={
                "backend": "/api/flowable_service/v1/domain_model",
                "frontend": "",
            },
            path_source="backend_contract",
            path_confidence="high",
            service="logic.flowable_service",
            request={"fields": []},
            response={"fields": [{"name": "instanceId"}]},
        ),
        BackendContract(
            operation_key="logic.flowable_service|POST|/api/flowable_service/v1/domain_model/_search",
            method="POST",
            path="/api/flowable_service/v1/domain_model/_search",
            raw_paths={
                "backend": "/api/flowable_service/v1/domain_model/_search",
                "frontend": "",
            },
            path_source="backend_contract",
            path_confidence="high",
            service="logic.flowable_service",
            request={"fields": [{"name": "Q"}]},
            response={"fields": [{"name": "list"}]},
        ),
    ]


def _default_rules():
    """与 ``platforms/<platform>/sources/backend/gateway-rules.yaml`` 一致的规则。"""
    return {
        "strip_prefix": ["/next", "/api/gateway/{service}"],
        "service_map": {"logic.flowable_service": "flowable_service"},
    }


class TestExtract:
    """extract：从 openapi 抽骨架 + path 对齐。"""

    def test_extracts_all_paths(self, tmp_path):
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        # openapi 含 5 个 path / 6 个 method（domain_model CRUD + _search + standard_field _search）
        assert len(data) >= 5
        names = [c["name"] for c in data]
        assert "createDomainModel" in names
        assert "searchDomainModel" in names
        assert "deleteDomainModel" in names
        assert "searchStandardFieldForDomainModel" in names

    def test_extract_aligns_path_to_backend(self, tmp_path):
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        create = [c for c in data if c["name"] == "createDomainModel"][0]
        # path 应被对齐到后端契约（backend_contract, high）
        assert create["path"] == "/api/flowable_service/v1/domain_model"
        assert create["path_source"] == "backend_contract"
        assert create["path_confidence"] == "high"
        # service 应保留 gateway 提取出的原值（带 logic. 前缀，与契约 service 对齐）
        assert create["service"] == "logic.flowable_service"

    def test_extract_infers_side_effect(self, tmp_path):
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules={"strip_prefix": [], "service_map": {}},
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        by_name = {c["name"]: c for c in data}
        # createDomainModel: POST 非 search → create
        assert by_name["createDomainModel"]["side_effect"] == "create"
        # searchDomainModel: operationId 含 search → read（即使 method 是 POST）
        assert by_name["searchDomainModel"]["side_effect"] == "read"
        # deleteDomainModel: DELETE → delete
        assert by_name["deleteDomainModel"]["side_effect"] == "delete"
        # getDomainModel: GET → read
        assert by_name["getDomainModel"]["side_effect"] == "read"
        # updateDomainModel: PUT → update
        assert by_name["updateDomainModel"]["side_effect"] == "update"

    def test_extract_fills_endpoint_field(self, tmp_path):
        """extract 产出每张卡片含 endpoint 字段（contract_ref；不写 mode）。

        mode 不固化（spec 5.1）：注册期一律不写 endpoint.mode，主干不决策平台
        特定调用模式，真调时由 adapter.resolve_call_mode 动态决定。
        """
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        for c in data:
            assert "endpoint" in c, f"卡片 {c.get('name')} 缺 endpoint 字段"
            assert "contract_ref" in c["endpoint"], f"卡片 {c['name']} 缺 contract_ref"
            assert "mode" not in c["endpoint"], \
                f"卡片 {c['name']} 不应写 mode（不固化，运行时由 adapter 决策）"

    def test_extract_fills_source_field(self, tmp_path):
        """extract 产出每张卡片含 source 字段（openapi_file/hash/recorded_at）。

        batch-register 增量判断用：openapi_hash 变了→需重注（spec 复盘"监测录制时间"）。
        """
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        for c in data:
            src = c.get("source") or {}
            assert src.get("openapi_file") == OPENAPI.name, \
                f"卡片 {c['name']} source.openapi_file 错"
            assert len(src.get("openapi_hash", "")) == 64, \
                f"卡片 {c['name']} source.openapi_hash 应为 SHA256(64位)"
            assert src.get("recorded_at"), \
                f"卡片 {c['name']} source.recorded_at 应有值（x-recorded-at 或 mtime）"

    def test_extract_endpoint_contract_ref_when_aligned(self, tmp_path):
        """对齐到后端契约的卡片 endpoint.contract_ref 非空（= 契约 operation_key）。"""
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        create = [c for c in data if c["name"] == "createDomainModel"][0]
        # path_source=backend_contract -> contract_ref 应为契约 operation_key
        assert create["path_source"] == "backend_contract"
        assert create["endpoint"]["contract_ref"] == \
            "logic.flowable_service|POST|/api/flowable_service/v1/domain_model"

    def test_extract_endpoint_contract_ref_empty_when_not_aligned(self, tmp_path):
        """未对齐到后端契约（frontend_raw）的卡片 contract_ref 为空。"""
        out = tmp_path / "_draft.yaml"
        # 故意用空 contracts + 空 rules，强制走 frontend_raw 兜底
        extract(
            openapi_path=OPENAPI,
            contracts=[],
            gateway_rules={"strip_prefix": [], "service_map": {}},
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        # frontend_raw 的卡片：contract_ref 空，mode 不写（由 adapter 真调时定）
        raw_cards = [c for c in data if c["path_source"] == "frontend_raw"]
        assert raw_cards, "应至少有一张 frontend_raw 卡片（无契约对齐时）"
        for c in raw_cards:
            assert c["endpoint"]["contract_ref"] == ""
            assert "mode" not in c["endpoint"]


class TestFallbackName:
    """无 operationId 时，用归一化 path 生成文件安全的 name（回归 bug）。

    背景：openapi 缺 operationId 时，曾用 gateway_path 当 name，含 ``/`` 导致
    commit 拆单卡片时 ``<name>.yaml`` 被解析成多级路径（FileNotFoundError）。
    现改用归一化 path 生成安全 name，``/``→``_``，保留 ``{param}``。
    """

    def test_safe_fallback_name_no_slash(self):
        """fallback name 不含 ``/``（可安全做文件名）。"""
        cases = [
            ("GET", "/api/flowable_service/v1/ticket/{ticketId}/task/{taskId}"),
            ("POST", "/api/v1/domain_model"),
            ("DELETE", "/object/USER_GROUP/instance/{instanceId}"),
            ("GET", "/"),  # 根路径兜底
            ("GET", ""),   # 空路径兜底
        ]
        for method, path in cases:
            name = _safe_fallback_name(method, path)
            assert "/" not in name, f"name 含斜杠无法当文件名: {name}"
            assert name, f"name 为空: method={method} path={path}"

    def test_safe_fallback_name_keeps_param_placeholder(self):
        """``{param}`` 占位符保留（其内无斜杠，文件名合法）。"""
        name = _safe_fallback_name("GET", "/api/ticket/{ticketId}/task")
        assert "{ticketId}" in name
        assert name == "get_api_ticket_{ticketId}_task"

    def test_extract_safe_name_when_no_operation_id(self, tmp_path):
        """无 operationId 的 openapi：extract 产出的 name 文件安全，commit 不崩。"""
        # 构造一个无 operationId 的 openapi（含参 path，最易触发原 bug）
        spec = {
            "openapi": "3.0.0", "info": {"title": "t", "version": "1"},
            "paths": {
                "/api/gateway/logic.svc/api/v1/ticket/{ticketId}/task/{taskId}": {
                    "get": {"summary": "任务详情", "description": "",
                            "responses": {"200": {"description": "ok"}}}
                },
            },
        }
        op = tmp_path / "no_opid.yaml"
        op.write_text(yaml.safe_dump(spec, allow_unicode=True))
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=op,
            contracts=[],
            gateway_rules={"strip_prefix": ["/api/gateway/{service}"],
                           "service_map": {}},
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        assert len(data) == 1
        name = data[0]["name"]
        assert "/" not in name, f"无 operationId 的 name 含斜杠: {name}"
        # commit 不应抛 FileNotFoundError
        registry = tmp_path / "registry"
        commit(draft_path=out, registry_dir=registry, platform="demo")
        assert registry.exists()


class TestCommit:
    """commit：校验 _draft → 拆单卡片 → 写 registry + _index.yaml。"""

    def test_commit_writes_cards_and_index(self, tmp_path):
        draft = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules={"strip_prefix": [], "service_map": {}},
            out=draft,
        )
        registry = tmp_path / "registry"
        commit(draft_path=draft, registry_dir=registry, platform="demo")
        # 卡片文件存在（每张一个 yaml）
        cards = list(registry.glob("**/*.yaml"))
        # 排除 _index.yaml
        card_files = [c for c in cards if c.name != "_index.yaml"]
        assert len(card_files) >= 5
        # _index.yaml 存在且含 module 分组
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        assert "modules" in idx
        module_names = [m["name"] for m in idx["modules"]]
        # extract 阶段 module 粗推（domain_model / standard_field / default）
        assert len(idx["modules"]) >= 1
        # 每条 card 索引项含必要字段
        for m in idx["modules"]:
            for c in m["cards"]:
                assert {"name", "method", "path", "side_effect", "file"}.issubset(c.keys())
                # 一致性：索引里的 file 对应实际文件
                assert (registry / c["file"]).exists()

    def test_commit_writes_registered_at(self, tmp_path):
        """commit 时给每张卡片写 registered_at 时间戳。"""
        draft = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),
            gateway_rules={"strip_prefix": [], "service_map": {}},
            out=draft,
        )
        registry = tmp_path / "registry"
        commit(draft_path=draft, registry_dir=registry, platform="demo")
        # 每张卡片文件含 registered_at
        for card_file in registry.glob("*/*.yaml"):
            if card_file.name == "_index.yaml":
                continue
            c = yaml.safe_load(card_file.read_text())
            assert c.get("registered_at"), \
                f"卡片 {c.get('name')} 缺 registered_at（commit 时间戳）"

    def test_commit_merges_existing_modules(self, tmp_path):
        """增量补注册：第二次 commit 不清掉已有 module 的索引。

        场景：先 commit module_a，再 commit module_b（不同 module），
        _index 应同时含两个 module（不能起手重建为空）。
        """
        registry = tmp_path / "registry"

        # 第一次 commit：构造一个 module_a 的 draft
        draft_a = tmp_path / "draft_a.yaml"
        draft_a.write_text(yaml.safe_dump([{
            "name": "searchA", "module": "module_a", "method": "GET",
            "path": "/a/search", "side_effect": "read",
        }], allow_unicode=True, sort_keys=False))
        commit(draft_path=draft_a, registry_dir=registry, platform="demo")

        # 第二次 commit：module_b
        draft_b = tmp_path / "draft_b.yaml"
        draft_b.write_text(yaml.safe_dump([{
            "name": "searchB", "module": "module_b", "method": "GET",
            "path": "/b/search", "side_effect": "read",
        }], allow_unicode=True, sort_keys=False))
        commit(draft_path=draft_b, registry_dir=registry, platform="demo")

        # _index 应同时含 module_a 和 module_b（merge，非重建）
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        module_names = {m["name"] for m in idx["modules"]}
        assert module_names == {"module_a", "module_b"}, \
            f"增量 commit 应 merge，实际 module：{module_names}"

    def test_commit_incremental_merge_within_module(self, tmp_path):
        """同 module 重新 commit：按 name 增量合并，draft 未覆盖的同 module 卡片保留。

        背景：多个 draft 可能共享同一 module（如 form 卡片分散在「工单发起」
        和「表单管理」两个 openapi）。若 commit 对 module 整体替换，后提交的
        draft 会清掉同 module 其他卡片，导致 _index 与卡片文件不一致。
        因此 commit 对每个 module 按 card name 增量合并——同名覆盖（重注），
        draft 未涉及的保留。

        若确需整体替换某 module，先删该 module 目录再 commit。
        """
        registry = tmp_path / "registry"

        # module_a 两张卡 + module_b 一张卡
        draft1 = tmp_path / "d1.yaml"
        draft1.write_text(yaml.safe_dump([
            {"name": "a1", "module": "module_a", "method": "GET",
             "path": "/a1", "side_effect": "read"},
            {"name": "a2", "module": "module_a", "method": "GET",
             "path": "/a2", "side_effect": "read"},
            {"name": "b1", "module": "module_b", "method": "GET",
             "path": "/b1", "side_effect": "read"},
        ], allow_unicode=True, sort_keys=False))
        commit(draft_path=draft1, registry_dir=registry, platform="demo")

        # 重新 commit module_a：a2 重注（同名覆盖）+ a3 新增；a1 应保留
        draft2 = tmp_path / "d2.yaml"
        draft2.write_text(yaml.safe_dump([
            {"name": "a2", "module": "module_a", "method": "GET",
             "path": "/a2_new", "side_effect": "read"},
            {"name": "a3", "module": "module_a", "method": "GET",
             "path": "/a3", "side_effect": "read"},
        ], allow_unicode=True, sort_keys=False))
        commit(draft_path=draft2, registry_dir=registry, platform="demo")

        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        by_mod = {m["name"]: {c["name"]: c for c in m["cards"]} for m in idx["modules"]}
        # a1 保留、a2 重注（path 更新）、a3 新增
        assert set(by_mod["module_a"].keys()) == {"a1", "a2", "a3"}, \
            f"module_a 应增量合并为 a1/a2/a3，实际 {set(by_mod['module_a'].keys())}"
        assert by_mod["module_a"]["a2"]["path"] == "/a2_new", \
            "a2 同名重注应覆盖 path"
        # module_b 不受影响
        assert set(by_mod["module_b"].keys()) == {"b1"}


class TestGenOutputsFromContract:
    """extract 确定性 outputs 生成（固化 A）：从契约 response.fields 出锚点骨架。

    规则只看字段 type（含 []）和通用 name（list/total/instanceId），
    不依赖业务字段名——任何平台的 contracts.response.fields 都适用。
    """

    def _contract(self, fields, method="POST", path="/x",
                  service="logic.svc"):
        from api_console.schema.contracts import BackendContract
        return BackendContract(
            operation_key=f"{service}|{method}|{path}", method=method, path=path,
            raw_paths={"backend": path, "frontend": ""},
            path_source="backend_contract", path_confidence="high",
            service=service, request={"fields": []},
            response={"fields": fields},
        )

    def test_list_query_anchors(self):
        """列表查询：list 数组字段 → list_full + list_ids；total → total。"""
        c = self._contract([
            {"name": "list", "type": "DomainModel[]"},
            {"name": "total", "type": "int"},
            {"name": "page", "type": "page"},
        ])
        out, conf = _gen_outputs_from_contract(c, "read")
        assert conf == "high"
        assert set(out.keys()) == {"list_full", "list_ids", "total"}
        assert out["list_full"]["jsonpath"] == "$.data.list"
        assert out["list_ids"]["jsonpath"] == "$.data.list"

    def test_create_instance_id(self):
        """新建：instanceId 字段 → instanceId 锚点。"""
        c = self._contract([{"name": "instanceId", "type": "instance_id"}])
        out, conf = _gen_outputs_from_contract(c, "create")
        assert conf == "high"
        assert out["instanceId"]["jsonpath"] == "$.data.instanceId"

    def test_generic_plural_list_field(self):
        """业务命名的数组字段（categories/nodes）：按字段名建锚点。"""
        c = self._contract([{"name": "categories", "type": "ServiceCategory[]"}])
        out, conf = _gen_outputs_from_contract(c, "read")
        assert conf == "high"
        assert "categories" in out
        assert out["categories"]["jsonpath"] == "$.data.categories"

    def test_detail_fallback_single_field(self):
        """仅单一非标准字段：detail 兜底锚点。"""
        c = self._contract([{"name": "model", "type": "object", "desc": "模型详情"}])
        out, conf = _gen_outputs_from_contract(c, "read")
        assert conf == "high"
        assert out["detail"]["jsonpath"] == "$.data.model"

    def test_no_contract_returns_empty_low(self):
        """契约未命中：空 outputs + low 置信（待 LLM 推断）。"""
        out, conf = _gen_outputs_from_contract(None, "read")
        assert out == {}
        assert conf == "low"

    def test_extract_fills_outputs_from_contract(self, tmp_path):
        """端到端：extract 命中契约时自动生成 outputs 骨架，confidence.outputs=high。"""
        out = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI,
            contracts=_fake_contracts(),  # domain_model _search 响应含 list
            gateway_rules=_default_rules(),
            out=out,
        )
        data = yaml.safe_load(out.read_text())
        search = [c for c in data if c["name"] == "searchDomainModel"][0]
        assert "list_full" in search["outputs"]
        assert "list_ids" in search["outputs"]
        assert search["confidence"]["outputs"] == "high"


class TestMergeRequestFromContract:
    """契约 request.fields 合并进 openapi request_properties。"""

    def test_fill_empty_desc_from_contract(self):
        from api_console.register_cards import _merge_request_from_contract
        props = {"name": {"type": "string", "desc": ""}}
        fields = [{"name": "name", "type": "string", "desc": "模型名称"}]
        merged, conf = _merge_request_from_contract(props, fields)
        assert merged["name"]["desc"] == "模型名称"
        assert conf == "high"

    def test_keep_openapi_desc_when_nonempty(self):
        from api_console.register_cards import _merge_request_from_contract
        props = {"name": {"type": "string", "desc": "我的说明"}}
        fields = [{"name": "name", "type": "string", "desc": "契约说明"}]
        merged, _ = _merge_request_from_contract(props, fields)
        assert merged["name"]["desc"] == "我的说明"

    def test_upgrade_type_to_more_specific(self):
        from api_console.register_cards import _merge_request_from_contract
        props = {"days": {"type": "array", "desc": ""}}
        fields = [{"name": "days", "type": "WorkDay[]", "desc": "工作日"}]
        merged, _ = _merge_request_from_contract(props, fields)
        assert merged["days"]["type"] == "WorkDay[]"

    def test_add_contract_only_field(self):
        from api_console.register_cards import _merge_request_from_contract
        props = {"name": {"type": "string", "desc": ""}}
        fields = [{"name": "name", "type": "string", "desc": "名称"},
                  {"name": "query", "type": "map", "desc": "查询条件"}]
        merged, conf = _merge_request_from_contract(props, fields)
        assert "query" in merged
        assert merged["query"]["_source"] == "contract"
        assert conf == "medium"


class TestRebuildIndex:
    """rebuild_index（固化 D）：从卡片文件重建 _index.yaml。

    _index 损坏/不一致时的兜底。纯结构操作，保留旧 module 的 desc/tags。
    """

    def test_rebuild_from_files(self, tmp_path):
        """commit 落盘卡片后，删掉 _index 也能从文件重建。"""
        registry = tmp_path / "registry"
        draft = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI, contracts=_fake_contracts(),
            gateway_rules={"strip_prefix": [], "service_map": {}}, out=draft,
        )
        commit(draft_path=draft, registry_dir=registry, platform="demo")
        # 删掉 _index，模拟损坏
        (registry / "_index.yaml").unlink()
        rebuild_index(registry)
        # 重建后 _index 与文件一致
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        idx_cards = {c["name"] for m in idx["modules"] for c in m["cards"]}
        file_cards = {
            yaml.safe_load(f.read_text())["name"]
            for f in registry.glob("*/*.yaml") if f.name != "_index.yaml"
        }
        assert idx_cards == file_cards
        # 每条 file 指向真实文件
        for m in idx["modules"]:
            for c in m["cards"]:
                assert (registry / c["file"]).exists()

    def test_rebuild_preserves_module_meta(self, tmp_path):
        """重建保留旧 _index 里 module 的 desc/tags（人手维护的元信息不丢）。"""
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "domain_model").mkdir()
        # 一张卡片文件
        (registry / "domain_model" / "search.yaml").write_text(yaml.safe_dump({
            "name": "search", "module": "domain_model", "method": "POST",
            "path": "/_search", "side_effect": "read", "tags": ["查询"],
            "summary": "查询",
        }, allow_unicode=True, sort_keys=False))
        # 旧 _index 含 module desc/tags（人手维护）
        (registry / "_index.yaml").write_text(yaml.safe_dump({
            "modules": [{
                "name": "domain_model", "desc": "领域模型功能域",
                "tags": ["核心"], "cards": [],
            }]
        }, allow_unicode=True, sort_keys=False))
        rebuild_index(registry)
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        m = idx["modules"][0]
        assert m["desc"] == "领域模型功能域"  # 保留
        assert m["tags"] == ["核心"]  # 保留
        assert [c["name"] for c in m["cards"]] == ["search"]  # 从文件重建

    def test_rebuild_after_dedup(self, tmp_path):
        """手工删卡后重建：_index 不再含已删卡片（索引与文件同步）。"""
        registry = tmp_path / "registry"
        draft = tmp_path / "_draft.yaml"
        extract(
            openapi_path=OPENAPI, contracts=[],
            gateway_rules={"strip_prefix": [], "service_map": {}}, out=draft,
        )
        commit(draft_path=draft, registry_dir=registry, platform="demo")
        # 删掉一张卡片文件
        files = [f for f in registry.glob("*/*.yaml") if f.name != "_index.yaml"]
        files[0].unlink()
        rebuild_index(registry)
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        idx_names = {c["name"] for m in idx["modules"] for c in m["cards"]}
        assert files[0].stem not in idx_names, "已删卡片不应在重建后的 _index"


class TestCommitDedup:
    """commit 按 contract_ref 去重（第一版：已在库优先，重复跳过）。"""

    def _card(self, name, module, path_source, contract_ref):
        return {
            "name": name, "module": module, "method": "GET", "path": "/x",
            "service": "logic.s", "side_effect": "read",
            "path_source": path_source, "path_confidence": "medium",
            "tags": [], "summary": "", "description": "",
            "request": {"required": [], "properties": {}}, "outputs": {},
            "requires": [], "rollback": None, "examples": [], "confidence": {},
            "endpoint": {"contract_ref": contract_ref, "mode": "fake_mode"},
            "source": {},
        }

    def test_same_contract_ref_skip_duplicate(self, tmp_path):
        """同 contract_ref 两张卡，先入的保留，后入的跳过。"""
        from api_console.register_cards import commit
        import yaml
        drafts = [
            self._card("a", "m1", "gateway_strip", "logic.s|GET|/x"),
            self._card("b", "m2", "backend_contract", "logic.s|GET|/x"),
        ]
        draft = tmp_path / "_draft.yaml"
        draft.write_text(yaml.dump(drafts, allow_unicode=True))
        registry = tmp_path / "registry"
        commit(draft, registry, "demo")
        idx = yaml.safe_load((registry / "_index.yaml").read_text())
        all_names = [c["name"] for m in idx["modules"] for c in m["cards"]]
        assert "a" in all_names
        assert "b" not in all_names

    def test_same_name_no_contract_ref_raises(self, tmp_path):
        """contract_ref 空且同名 → commit 报错。"""
        from api_console.register_cards import commit
        import yaml
        drafts = [
            self._card("dup", "m1", "frontend_raw", ""),
            self._card("dup", "m2", "frontend_raw", ""),
        ]
        draft = tmp_path / "_draft.yaml"
        draft.write_text(yaml.dump(drafts, allow_unicode=True))
        import pytest
        with pytest.raises(ValueError, match="同名"):
            commit(draft, tmp_path / "registry", "demo")

