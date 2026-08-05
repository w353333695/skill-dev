"""verify_dag 12 条规则测试。

覆盖 spec 7.2 的核心场景：
- 未知卡片 / 循环 / 缺必填 / 写卡片标记（has_write）/ 未知锚点 / bind 重名 / 合法通过；
- MVP-1.5 新增：规则11（when 语法）/ 规则12（rollback 引用）。
"""
from __future__ import annotations
from api_console.verify_dag import verify, VerifyReport
from api_console.schema.dag import DAG, Step, StepOutput
from api_console.schema.card import Card, Rollback, RollbackParam


def _card(name="searchDomainModel", side_effect="read", required=None, outputs=None):
    """造一张假 Card，便于测试（不依赖真实 registry）。"""
    return Card(name=name, module="m", method="GET", path="/p",
                side_effect=side_effect, request_required=required or [],
                outputs=outputs or {})


def _dag(steps, result="${s1.x}"):
    """造一个 DAG，默认 result 引用 s1（verify 不校验 result 表达式）。"""
    return DAG(goal="g", steps=steps, result=result)


class TestRules:
    def test_unknown_card_rejected(self):
        """规则1：未知卡片必须被拒。"""
        dag = _dag([Step(id="s1", card="nope")])
        r = verify(dag, {})
        assert not r.passed
        assert any("未知卡片" in e for e in r.errors)

    def test_dependency_cycle_rejected(self):
        """规则2：依赖闭环必须被拒。"""
        dag = _dag([Step(id="s1", card="x", depends=["s2"]),
                    Step(id="s2", card="x", depends=["s1"])])
        r = verify(dag, {"x": _card("x")})
        assert any("循环" in e for e in r.errors)

    def test_missing_required_param_rejected(self):
        """规则4：必填参数必须覆盖。"""
        dag = _dag([Step(id="s1", card="x", params={})])
        r = verify(dag, {"x": _card("x", required=["Q"])})
        assert any("必填" in e or "Q" in e for e in r.errors)

    def test_read_only_constraint(self):
        """规则6（MVP-1.5 改）：写卡片不再被拒，但 has_write=True。"""
        dag = _dag([Step(id="s1", card="x")])
        r = verify(dag, {"x": _card("x", side_effect="create")})
        assert r.passed                          # MVP-1.5 起不再拒绝写卡片
        assert r.has_write is True

    def test_unknown_anchor_rejected(self):
        """规则9：output.from 必须在卡片 outputs 里定义。"""
        dag = _dag([Step(id="s1", card="x",
                         output=StepOutput(bind="y", anchor="nope"))])
        r = verify(dag, {"x": _card("x", outputs={"list_full": None})})
        assert any("锚点" in e for e in r.errors)

    def test_empty_anchor_passes_anchor_rule(self):
        """规则9（放行）：from 为空串时跳过锚点存在性校验（文件下载/整体绑定场景）。

        export 下载卡片 outputs 为空 dict，step 声明 output bind=x anchor=""
        表示绑定整个 data；此时规则 9 不应报错。
        """
        dag = _dag([Step(id="s1", card="x",
                         output=StepOutput(bind="y", anchor=""))])
        r = verify(dag, {"x": _card("x", outputs={})})
        assert not any("锚点" in e for e in r.errors)

    def test_duplicate_bind_rejected(self):
        """规则10：不同 step 的 output.bind 不能重名。"""
        dag = _dag([Step(id="s1", card="x", output=StepOutput(bind="y", anchor="a")),
                    Step(id="s2", card="x", output=StepOutput(bind="y", anchor="a"))])
        r = verify(dag, {"x": _card("x", outputs={"a": None})})
        assert any("重名" in e for e in r.errors)

    def test_valid_dag_passes(self):
        """合法 DAG：所有规则通过。"""
        dag = _dag([Step(id="s1", card="x",
                         output=StepOutput(bind="y", anchor="list_full"))])
        r = verify(dag, {"x": _card("x", outputs={"list_full": None})})
        assert r.passed, r.errors


class TestMVP15Rules:
    """MVP-1.5 新增规则：has_write 标记 / 规则11（when 语法）/ 规则12（rollback 引用）。"""

    def test_has_write_flag(self):
        """规则6 改：写卡片不再被拒，但 VerifyReport.has_write=True。"""
        dag = _dag([Step(id="s1", card="createForm", params={"name": "x"})])
        cards = {"createForm": _card("createForm", side_effect="create")}
        r = verify(dag, cards)
        assert r.passed                      # 不再因写卡片而失败
        assert r.has_write is True

    def test_read_dag_has_write_false(self):
        """纯读 DAG：has_write=False。"""
        dag = _dag([Step(id="s1", card="searchDomainModel", params={"q": "x"})])
        cards = {"searchDomainModel": _card("searchDomainModel", side_effect="read")}
        r = verify(dag, cards)
        assert r.passed
        assert r.has_write is False

    def test_rule11_when_syntax_approved(self):
        """规则11：when 必须是受批准形式（合法形式放过）。"""
        dag = _dag([Step(id="s1", card="searchDomainModel",
                         when="${s0.found} == null", params={"q": "x"})])
        r = verify(dag, {"searchDomainModel": _card()})
        assert r.passed, r.errors

    def test_rule11_when_syntax_rejected(self):
        """规则11：when 用 > 操作符（非受批准形式）必须被拒。"""
        dag = _dag([Step(id="s1", card="searchDomainModel",
                         when="${s0.x} > 5", params={"q": "x"})])
        r = verify(dag, {"searchDomainModel": _card()})
        assert not r.passed
        assert any("when" in e for e in r.errors)

    def test_rule12_rollback_api_must_exist(self):
        """规则12：rollback.api 必须存在于 cards。"""
        write_card = Card(name="createForm", module="form", method="POST",
                          path="/f", side_effect="create",
                          rollback=Rollback(api="ghostDelete", params=[
                              RollbackParam(param_key="id", from_output="instanceId")]))
        dag = _dag([Step(id="s1", card="createForm", params={"name": "x"})])
        r = verify(dag, {"createForm": write_card})
        assert not r.passed
        assert any("ghostDelete" in e for e in r.errors)

    def test_rule12_rollback_param_from_output_must_match(self):
        """规则12：from_output 不等于 output.bind 或 anchor 时必须被拒。

        构造一张写卡片，rollback.params[0].from_output 故意写成 wrong_field，
        它既不等于 step.output.bind，也不等于 output.anchor，应当报错。
        """
        write_card = Card(name="createForm", module="form", method="POST",
                          path="/f", side_effect="create",
                          rollback=Rollback(api="deleteForm", params=[
                              RollbackParam(param_key="id", from_output="wrong_field")]))
        dag = _dag([
            Step(id="s1", card="createForm", params={"name": "x"},
                 output=StepOutput(bind="instanceId", anchor="created")),
        ])
        r = verify(dag, {"createForm": write_card, "deleteForm": _card("deleteForm")})
        assert not r.passed
        assert any("from_output" in e for e in r.errors)

    def test_rule12_rollback_params_cover_path_placeholders(self):
        """规则12（L2 完备性）：rollback.params 的 param_key 集合须 == 目标 path 占位符集合。

        deleteFormVersion path=/form/{formId}/version/{versionId}，rollback 给全
        formId+versionId 两参 → 通过。
        """
        write_card = Card(name="createForm", module="form", method="POST",
                          path="/f", side_effect="create",
                          rollback=Rollback(api="deleteFormVersion", params=[
                              RollbackParam(param_key="formId", from_output="o", from_field="formId"),
                              RollbackParam(param_key="versionId", from_output="o", from_field="versionId"),
                          ]))
        target = Card(name="deleteFormVersion", module="form", method="DELETE",
                      path="/form/{formId}/version/{versionId}", side_effect="delete")
        dag = _dag([Step(id="s1", card="createForm", params={"name": "x"},
                         output=StepOutput(bind="o", anchor="detail"))])
        r = verify(dag, {"createForm": write_card, "deleteFormVersion": target})
        # 不应有 path 占位符完备性错误
        assert not any("占位符" in e or "path" in e.lower() for e in r.errors)

    def test_rule12_rollback_missing_placeholder_rejected(self):
        """规则12（L2 完备性）：rollback 少填一个 path 占位符 → 必须被拒。

        deleteFormVersion 需 formId+versionId，rollback 只给 versionId → 报错。
        这正是 eval1 暴露的 createForm bug 的校验拦截点。
        """
        write_card = Card(name="createForm", module="form", method="POST",
                          path="/f", side_effect="create",
                          rollback=Rollback(api="deleteFormVersion", params=[
                              RollbackParam(param_key="versionId", from_output="o", from_field="versionId"),
                          ]))
        target = Card(name="deleteFormVersion", module="form", method="DELETE",
                      path="/form/{formId}/version/{versionId}", side_effect="delete")
        dag = _dag([Step(id="s1", card="createForm", params={"name": "x"},
                         output=StepOutput(bind="o", anchor="detail"))])
        r = verify(dag, {"createForm": write_card, "deleteFormVersion": target})
        assert not r.passed
        assert any("占位符" in e or "formId" in e for e in r.errors)
