"""runtime 被动暴露：execute 失败钩子把缺口写进 _gaps.yaml。"""
from __future__ import annotations
from unittest.mock import patch, MagicMock

import pytest

from api_console import runtime_gaps
from api_console.runtime_gaps import make_runtime_sink
from api_console.gaps_store import load_gaps
from api_console.execute_dag import execute, ExecutionError
from api_console.schema.dag import DAG, Step, StepOutput, StepAssert
from api_console.schema.card import Card, OutputAnchor
from api_console.adapter_base import Endpoint


class FakeAdapter:
    name = "fake"
    def resolve_endpoint(self, contract, manifest):
        return Endpoint(url="http://h" + contract.get("path", ""),
                        method=contract.get("method", "GET"), auth="none", headers={})
    def build_auth_headers(self, auth_mode, manifest, request_ctx=None):
        return {}
    def resolve_call_mode(self, card, contracts):
        ep = getattr(card, "endpoint", None) or {}
        return ep.get("mode", "")


def _ok_resp():
    """构造 code:0 data:{"list":[]} 的假 resp（patch http_request 用）。

    data={"list":[]} 经锚点 $.data 提取后是 dict（非 list），断言 fields.length>0 必失败。
    """
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"code": 0, "data": {"list": []}}
    return m


def _assert_fail_dag():
    """构造必然断言失败的 DAG（对齐 test_execute_dag 范式：output 绑定 + 锚点）。"""
    card = Card(name="c1", module="m", service="s", method="GET", path="/x",
                endpoint={"contract_ref": "", "mode": "fake_mode"},
                side_effect="read",
                outputs={"list_full": OutputAnchor(name="list_full", jsonpath="$.data")})
    step = Step(id="s1", card="c1",
                output=StepOutput(bind="fields", anchor="list_full"),
                asserts=[StepAssert(condition="fields.length > 0", message="无数据")])
    dag = DAG(goal="g", steps=[step], result="${s1.fields}")
    return dag, {"c1": card}


def test_make_runtime_sink_appends_gap(tmp_path):
    dag, cards = _assert_fail_dag()
    sink = make_runtime_sink(tmp_path, "demo")
    with patch("api_console.card_invoker.http_request", return_value=_ok_resp()):
        with pytest.raises(ExecutionError):
            execute(dag, cards, FakeAdapter(), {}, contracts={}, on_error=sink)
    gaps = load_gaps(tmp_path, "demo")
    assert len(gaps) == 1
    assert gaps[0].source == "runtime"
    assert "s1" in gaps[0].triggered_by


def test_execute_without_on_error_unchanged(tmp_path):
    # 不传 on_error：行为与原版一致，不写 _gaps.yaml
    dag, cards = _assert_fail_dag()
    with patch("api_console.card_invoker.http_request", return_value=_ok_resp()):
        with pytest.raises(ExecutionError):
            execute(dag, cards, FakeAdapter(), {}, contracts={})
    assert load_gaps(tmp_path, "demo") == []
