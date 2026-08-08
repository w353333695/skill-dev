"""DAG 数据模型 + JSONPath 子集测试。"""
from __future__ import annotations
import pytest
from api_console.schema.dag import DAG, Step, StepOutput, extract_jsonpath


class TestDAGFromDict:
    def test_basic(self):
        d = {
            "goal": "查模型",
            "steps": [
                {"id": "s1", "card": "searchDomainModel",
                 "params": {"Q": "test"},
                 "output": {"bind": "models", "from": "list_full"},
                 "assert": {"models.length > 0": "空"}},
                {"id": "s2", "card": "getDomainModel", "depends": ["s1"],
                 "foreach": "${s1.model_ids}", "params": {"modelId": "${item}"},
                 "output": {"bind": "details", "from": "detail"}},
            ],
            "result": "${s2.details}",
        }
        dag = DAG.from_dict(d)
        assert dag.goal == "查模型"
        assert len(dag.steps) == 2
        assert dag.steps[0].output == StepOutput(bind="models", anchor="list_full")
        assert dag.steps[0].asserts[0].condition == "models.length > 0"
        assert dag.steps[1].foreach == "${s1.model_ids}"
        assert dag.result == "${s2.details}"

    def test_step_map(self):
        dag = DAG.from_dict({"steps": [{"id": "a", "card": "x"}, {"id": "b", "card": "y"}]})
        assert set(dag.step_map().keys()) == {"a", "b"}


class TestExtractJsonpath:
    def test_scalar(self):
        assert extract_jsonpath("$.data.id", {"data": {"id": "x"}}) == "x"

    def test_nested(self):
        assert extract_jsonpath("$.data.a.b", {"data": {"a": {"b": 1}}}) == 1

    def test_index(self):
        assert extract_jsonpath("$.data.list[0].id", {"data": {"list": [{"id": "x"}]}}) == "x"

    def test_missing(self):
        with pytest.raises(KeyError):
            extract_jsonpath("$.data.none", {"data": {}})

    def test_bad_prefix(self):
        with pytest.raises(KeyError):
            extract_jsonpath("data.id", {"data": {"id": "x"}})

    def test_wildcard_rejected(self):
        # [*] 不支持，引导用 outputs 锚点 + DAG 投影
        with pytest.raises(KeyError):
            extract_jsonpath("$.data[*].id", {"data": [{"id": "x"}]})


def test_step_when_parsed():
    """Step.when 从 dict 解析，缺省为空串。"""
    from api_console.schema.dag import Step
    s = Step.from_dict({
        "id": "s1", "card": "createForm",
        "when": "${s0.found} == null",
        "params": {"name": "x"},
    })
    assert s.when == "${s0.found} == null"
    # 缺省
    s2 = Step.from_dict({"id": "s2", "card": "createForm", "params": {}})
    assert s2.when == ""
