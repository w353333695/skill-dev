"""${...} 表达式解析测试。"""
from __future__ import annotations
import pytest
from api_console.schema.expression import parse, eval_expr, VarRef, JoinCall, ExprError, eval_when


class TestParse:
    def test_varref_step_bind(self):
        node = parse("${s1.fields}")
        assert node == VarRef(step="s1", bind="fields")

    def test_varref_step_bind_field(self):
        node = parse("${s1.fields.instanceId}")
        assert node == VarRef(step="s1", bind="fields", field="instanceId")

    def test_item(self):
        node = parse("${item}")
        assert node == VarRef(step="item")

    def test_join(self):
        node = parse("${join(s1.fields.instanceId, ',')}")
        assert isinstance(node, JoinCall)
        assert node.sep == ","
        assert node.arr_expr == VarRef(step="s1", bind="fields", field="instanceId")


class TestParseReject:
    @pytest.mark.parametrize("bad", [
        "${s1}",                  # 无 bind
        "${s1.a.b.c}",            # 层级过深
        "${__import__('os')}",    # 越界
        "${s1.fields..instanceId}",  # 双点
        "s1.fields",              # 缺 ${}
        "${join(s1.fields)}",     # join 缺 sep
        "${join(s1.fields, x)}",  # sep 非字面量
    ])
    def test_reject_invalid(self, bad):
        with pytest.raises(ExprError):
            parse(bad)


class TestEval:
    def test_varref_whole(self):
        ctx = {"s1": {"fields": [{"instanceId": "a"}]}}
        assert eval_expr(parse("${s1.fields}"), ctx) == [{"instanceId": "a"}]

    def test_varref_project_field(self):
        ctx = {"s1": {"fields": [{"instanceId": "a"}, {"instanceId": "b"}]}}
        assert eval_expr(parse("${s1.fields.instanceId}"), ctx) == ["a", "b"]

    def test_item(self):
        assert eval_expr(parse("${item}"), {"item": "xxx"}) == "xxx"

    def test_join(self):
        ctx = {"s1": {"fields": [{"instanceId": "a"}, {"instanceId": "b"}]}}
        assert eval_expr(parse("${join(s1.fields.instanceId, ',')}"), ctx) == "a,b"

    def test_missing_step(self):
        with pytest.raises(ExprError, match="不存在"):
            eval_expr(parse("${s9.x}"), {"s1": {"x": 1}})

    def test_project_on_non_array(self):
        ctx = {"s1": {"x": "notarray"}}
        with pytest.raises(ExprError, match="不是数组"):
            eval_expr(parse("${s1.x.field}"), ctx)


class TestEvalWhen:
    def _ctx(self, **kw):
        return kw  # 便于造 context["s0"]["found"] 等

    def test_eq_null_true(self):
        # s0 没有 found 键 → ${s0.found} 求值为 None → == null 为真
        ctx = {"s0": {}}
        assert eval_when("${s0.found} == null", ctx) is True

    def test_eq_null_false(self):
        ctx = {"s0": {"found": {"modelId": "H"}}}
        assert eval_when("${s0.found} == null", ctx) is False

    def test_ne_null(self):
        ctx = {"s0": {"found": {"modelId": "H"}}}
        assert eval_when("${s0.found} != null", ctx) is True

    def test_eq_literal(self):
        ctx = {"s0": {"found": {"state": "done"}}}
        assert eval_when("${s0.found.state} == 'done'", ctx) is True
        assert eval_when("${s0.found.state} == 'draft'", ctx) is False

    def test_single_bind_truthy(self):
        ctx = {"s0": {"flag": True}}
        assert eval_when("${s0.flag}", ctx) is True
        ctx2 = {"s0": {"flag": False}}
        assert eval_when("${s0.flag}", ctx2) is False

    def test_reject_unapproved(self):
        # > / && 等未批准形式应抛 ValueError（verify 阶段就拦）
        import pytest
        with pytest.raises(ValueError):
            eval_when("${s0.x} > 5", {"s0": {"x": 10}})
