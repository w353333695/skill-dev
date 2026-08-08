"""Card 数据模型测试。"""
from __future__ import annotations
import pytest
from api_console.schema.card import Card, OutputAnchor


class TestCardRoundtrip:
    def test_from_dict_and_to_yaml_dict(self):
        d = {
            "name": "createDomainModel", "module": "domain_model",
            "method": "POST", "path": "/api/flowable_service/v1/domain_model",
            "gateway_path": "/next/api/gateway/logic.flowable_service/api/flowable_service/v1/domain_model",
            "service": "flowable_service", "side_effect": "create",
            "path_source": "backend_contract", "path_confidence": "high",
            "tags": ["领域模型"], "summary": "新建领域模型", "description": "创建模型",
            "request": {"required": ["key", "name"],
                        "properties": {"key": {"type": "string"}}},
            "outputs": {"instanceId": {"jsonpath": "$.data.instanceId"}},
            "confidence": {"request": "high"},
        }
        card = Card.from_dict(d)
        assert card.name == "createDomainModel"
        assert card.outputs["instanceId"] == OutputAnchor(name="instanceId", jsonpath="$.data.instanceId")
        out = card.to_yaml_dict()
        assert out["name"] == "createDomainModel"
        assert out["outputs"]["instanceId"]["jsonpath"] == "$.data.instanceId"


class TestCardValidate:
    def _base(self, **over):
        d = {"name": "x", "module": "m", "method": "GET", "path": "/p"}
        d.update(over)
        return Card.from_dict(d)

    def test_valid(self):
        assert self._base().validate() == []

    def test_bad_side_effect(self):
        assert any("side_effect" in e for e in self._base(side_effect="explode").validate())

    def test_bad_path_source(self):
        assert any("path_source" in e for e in self._base(path_source="guess").validate())

    def test_bad_jsonpath_prefix(self):
        c = self._base()
        c.outputs = {"x": OutputAnchor(name="x", jsonpath="data.id")}
        assert any("$. 开头" in e for e in c.validate())

    def test_missing_required_fields(self):
        errs = Card(name="", module="m", method="GET", path="/p").validate()
        assert any("必填" in e for e in errs)


class TestCardEndpoint:
    """endpoint 字段（spec 1.5 / 5.1）：contract_ref + mode。"""

    def test_endpoint_roundtrip(self):
        """from_dict/to_yaml_dict 保留 endpoint 字段。"""
        d = {
            "name": "x", "module": "m", "method": "GET", "path": "/p",
            "endpoint": {
                "contract_ref": "svc|GET|/p",
                "mode": "fake_mode",
            },
        }
        card = Card.from_dict(d)
        assert card.endpoint["contract_ref"] == "svc|GET|/p"
        assert card.endpoint["mode"] == "fake_mode"
        out = card.to_yaml_dict()
        assert out["endpoint"]["contract_ref"] == "svc|GET|/p"
        assert out["endpoint"]["mode"] == "fake_mode"

    def test_endpoint_default_empty(self):
        """未提供 endpoint 时默认空 dict，校验通过。"""
        card = Card(name="x", module="m", method="GET", path="/p")
        assert card.endpoint == {}
        assert card.validate() == []

    def test_endpoint_mode_optional(self):
        """endpoint 已提供但 mode 为空 -> 校验通过（mode 由 adapter.resolve_call_mode 动态决定）。"""
        c = Card(name="x", module="m", method="GET", path="/p")
        c.endpoint = {"contract_ref": "svc|GET|/p", "mode": ""}
        assert c.validate() == []

    def test_endpoint_with_mode_passes(self):
        """endpoint 有非空 mode -> 校验通过。"""
        c = Card(name="x", module="m", method="GET", path="/p")
        c.endpoint = {"contract_ref": "svc|GET|/p", "mode": "fake_mode"}
        assert c.validate() == []


def test_rollback_parsed_and_validated():
    """Rollback 结构化解析 + params 必填校验（多参数 schema）。

    旧测试覆盖：from_dict 解析多参数 rollback，缺 param_key 的条目 → validate 报错。
    """
    from api_console.schema.card import Card, Rollback, RollbackParam
    c = Card.from_dict({
        "name": "createForm", "module": "form", "method": "POST", "path": "/f",
        "side_effect": "create",
        "rollback": {"api": "deleteFormVersion", "params": [
            {"param_key": "formId", "from_output": "detail", "from_field": "formId"},
            {"param_key": "versionId", "from_output": "detail", "from_field": "versionId"},
        ]},
    })
    assert isinstance(c.rollback, Rollback)
    assert c.rollback.api == "deleteFormVersion"
    assert len(c.rollback.params) == 2
    assert isinstance(c.rollback.params[0], RollbackParam)
    assert c.rollback.params[0].param_key == "formId"
    assert c.rollback.params[1].from_field == "versionId"

    # 缺 param_key 的条目 → validate 报错
    c2 = Card.from_dict({
        "name": "createForm", "module": "form", "method": "POST", "path": "/f",
        "side_effect": "create",
        "rollback": {"api": "deleteFormVersion", "params": [
            {"from_output": "detail", "from_field": "versionId"},
        ]},
    })
    errs = c2.validate()
    assert any("param_key" in e for e in errs)


class TestRollbackMultiParamSchema:
    """rollback schema 多参数升级（L1）。"""

    def test_multi_params_parsed(self):
        """新格式 params 列表解析为 RollbackParam 列表。"""
        from api_console.schema.card import Card, Rollback, RollbackParam
        c = Card.from_dict({
            "name": "createForm", "module": "form", "method": "POST", "path": "/f",
            "rollback": {"api": "deleteFormVersion", "params": [
                {"param_key": "formId", "from_output": "detail", "from_field": "formId"},
                {"param_key": "versionId", "from_output": "detail", "from_field": "versionId"},
            ]},
        })
        assert isinstance(c.rollback, Rollback)
        assert [p.param_key for p in c.rollback.params] == ["formId", "versionId"]
        assert all(isinstance(p, RollbackParam) for p in c.rollback.params)
        assert c.rollback.params[0].from_field == "formId"

    def test_legacy_single_param_compat(self):
        """旧格式（顶层 param_key + param_from_output 单值）自动迁移为 params:[{...}]。

        存量 16 张单参数卡片磁盘仍是旧格式，from_dict 必须兼容读入。
        旧 param_from_output → 新 from_output；标量锚点场景 from_field 留空。
        """
        from api_console.schema.card import Card, Rollback
        c = Card.from_dict({
            "name": "createDomainModel", "module": "dm", "method": "POST", "path": "/d",
            "rollback": {"api": "deleteDomainModel",
                         "param_key": "modelId", "param_from_output": "instanceId"},
        })
        assert isinstance(c.rollback, Rollback)
        assert len(c.rollback.params) == 1
        assert c.rollback.params[0].param_key == "modelId"
        assert c.rollback.params[0].from_output == "instanceId"
        assert c.rollback.params[0].from_field == ""  # 标量锚点，无字段

    def test_legacy_param_from_output_only_compat(self):
        """card-schema.md 示例形态（仅 param_from_output，无 param_key）也能读入。

        param_key 缺省为空串（validate 会报 param_key 必填，提示补全）。
        """
        from api_console.schema.card import Card
        c = Card.from_dict({
            "name": "x", "module": "m", "method": "POST", "path": "/p",
            "rollback": {"api": "deleteX", "param_from_output": "instanceId"},
        })
        assert len(c.rollback.params) == 1
        assert c.rollback.params[0].from_output == "instanceId"
        # param_key 空 → validate 报错
        assert any("param_key" in e for e in c.validate())

    def test_to_yaml_dict_emits_new_format(self):
        """序列化统一输出新格式 params（不论构造来源）。"""
        from api_console.schema.card import Card
        c = Card.from_dict({
            "name": "x", "module": "m", "method": "POST", "path": "/p",
            # 旧格式输入
            "rollback": {"api": "deleteX", "param_key": "id",
                         "param_from_output": "instanceId"},
        })
        out = c.to_yaml_dict()
        assert "params" in out["rollback"]
        assert "param_key" not in out["rollback"]  # 顶层旧字段不再出现
        assert out["rollback"]["params"] == [
            {"param_key": "id", "from_output": "instanceId", "from_field": ""}]

    def test_validate_empty_params_rejected(self):
        """rollback 声明了但 params 为空 → validate 报错。"""
        from api_console.schema.card import Card, Rollback
        c = Card(name="x", module="m", method="POST", path="/p",
                 side_effect="create", rollback=Rollback(api="deleteX", params=[]))
        errs = c.validate()
        assert any("params" in e or "param" in e for e in errs)
