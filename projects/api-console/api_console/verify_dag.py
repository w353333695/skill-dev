"""DAG 校验（12 条规则，确定性，不发请求）。

spec 7.2。LLM 生成 DAG 后先过本模块，失败把 errors 回传 LLM 修正。

12 条规则（标 * 为 MVP-1 简化，标 † 为 MVP-1.5 新增）：
  1. 卡片存在性：step.card 必须在 cards 字典里
  2. 依赖闭环：depends 不能成环（DFS 三色标记）
  3. 参数引用合法性：params/foreach 的 ${...} 引用的 step/bind 必须存在
  4. 必填参数覆盖：card.request_required 必须都在 step.params 里
* 5. 类型粗校：MVP-1 简化为"表达式解析成功 + 引用合法"（合并到规则 3）
  6. MVP-1.5 写卡片标记：side_effect != "read" 不再被拒，置 has_write=True
  7. assert 语法：condition 字符串能解析为 <bind>.length > 0 形式（MVP-1 子集）
* 8. foreach 上游类型：MVP-1 简化为"foreach 表达式合法"（合入规则 3）
  9. 锚点存在性：step.output.anchor 必须在 card.outputs 里（空 anchor "" 除外——
     表示绑定整个 data，用于文件下载/整体绑定场景）
 10. bind 重名：不同 step 的 output.bind 不能重名
†11. when 语法（MVP-1.5）：when 必须是受批准形式（spec §4.2），否则拒
†12. rollback 引用有效（MVP-1.5）：rollback.api 必须在 cards；
       param_from_output 须等于本步 output.bind 或锚点名
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from api_console.schema.dag import DAG
from api_console.schema.card import Card
from api_console.schema.expression import (
    parse as parse_expr,
    eval_when,
    ExprError,
    VarRef,
    JoinCall,
)


@dataclass
class VerifyReport:
    """校验结果。

    Attributes:
        passed: True 表示无 error（warnings 不影响 passed）
        errors: 阻断性错误（必须修正才能执行）
        warnings: 非阻断提醒（如低置信度、潜在风险）
        has_write: DAG 是否含写卡片（side_effect != "read"）；
            MVP-1.5 起 verify 不再拒绝写卡片，改由 execute 阶段读此标记
            触发"写确认闸"等交互（spec §7.2 / §8）。
    """
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    has_write: bool = False  # MVP-1.5：DAG 是否含写卡片（驱动 execute 确认闸）


# assert condition 白名单（MVP-1 子集：<bind>.length > 0）
# 用字符类 [<>=] 避开反斜杠转义。
_ASSERT_RE = re.compile(r"^([a-zA-Z_]\w*)[.]length\s*[>]\s*0$")


def verify(dag: DAG, cards: dict) -> VerifyReport:
    """对 DAG 跑 10 条规则校验。

    Args:
        dag: 待校验的 DAG
        cards: name -> Card 字典（registry 加载后的快照）

    Returns:
        VerifyReport：passed=True 才能交给 execute_dag
    """
    errs: list = []
    warns: list = []
    has_write = False  # MVP-1.5：DAG 是否含写卡片
    step_map = dag.step_map()
    # 收集所有 step 的 bind 名（查重 + 表达式引用校验）
    binds: dict = {}  # bind -> step_id

    for s in dag.steps:
        # 规则1：卡片存在性
        if s.card not in cards:
            errs.append("步骤 " + s.id + "：未知卡片 " + s.card)
            continue
        card = cards[s.card]

        # 规则6（MVP-1.5 改）：不再拒绝写卡片，标记 has_write
        if card.side_effect != "read":
            has_write = True

        # 规则11（MVP-1.5）：when 表达式须是受批准形式（spec §4.2）
        # 只做语法预检：用空 context 调 eval_when 探测是否非受批准形式；
        # 取值失败（键缺失）在 eval_when 内被吞为 None，不算语法错。
        if s.when:
            try:
                eval_when(s.when, {})
            except ValueError as ve:
                errs.append("步骤 " + s.id + "：when 语法非法 - " + str(ve))
            except Exception:
                # 取值失败（非 ValueError，如内部 ExprError 已被吞）
                # 不算语法错，跳过
                pass

        # 规则12（MVP-1.5）：rollback 引用必须有效 + 参数覆盖目标 path 全部占位符
        #   - rollback.api 必须存在于 cards 字典
        #   - 每条 param.param_from_output 须等于本步 output.bind 或锚点名
        #     （对象形态取字段用锚点名；标量形态取 bind）
        #   - rollback.params 的 param_key 集合须 == 目标卡片 path 占位符集合
        #     （多参数 path 如 /form/{formId}/version/{versionId} 必须两个都覆盖，
        #      防 eval1 暴露的"回滚参数填不全→静默失败"）
        if card.rollback:
            if card.rollback.api not in cards:
                errs.append(
                    "步骤 " + s.id + "：rollback 引用未知卡片 "
                    + card.rollback.api
                )
            else:
                # 目标卡片 path 占位符完备性校验（api 存在才能查 path）
                target = cards[card.rollback.api]
                placeholders = set(re.findall(r"\{([^}]+)\}", target.path))
                param_keys = {p.param_key for p in card.rollback.params}
                if placeholders and param_keys != placeholders:
                    missing = placeholders - param_keys
                    extra = param_keys - placeholders
                    parts = []
                    if missing:
                        parts.append("缺 " + ",".join(sorted(missing)))
                    if extra:
                        parts.append("多 " + ",".join(sorted(extra)))
                    errs.append(
                        "步骤 " + s.id + "：rollback 参数未覆盖目标 "
                        + card.rollback.api + " path 占位符（"
                        + "；".join(parts) + "；path=" + target.path + "）"
                    )
            # 每条 from_output 须匹配本步 output.bind 或锚点名
            if s.output:
                for p in card.rollback.params:
                    if p.from_output != s.output.bind \
                            and p.from_output != s.output.anchor:
                        errs.append(
                            "步骤 " + s.id + "：rollback.from_output（"
                            + p.from_output + "）须等于本步 output.bind 或锚点名"
                        )

        # 依赖的 step 必须存在（规则 2 cycle 检测兜底）
        for dep in s.depends:
            if dep not in step_map:
                errs.append(
                    "步骤 " + s.id + "：依赖不存在的步骤 " + dep
                )

        # 规则4：必填参数覆盖
        for req in card.request_required:
            if req not in s.params:
                errs.append(
                    "步骤 " + s.id + "：缺必填参数 " + req
                    + "（卡片 " + s.card + "）"
                )

        # 规则9：锚点存在性 + 规则10：bind 重名
        if s.output:
            # 空 anchor（""）表示绑定整个 data（文件下载/整体绑定场景，
            # 如 export 下载卡片无 outputs），跳过锚点存在性校验；
            # 非空 anchor 仍必须在 card.outputs 里定义。
            if s.output.anchor and s.output.anchor not in card.outputs:
                errs.append(
                    "步骤 " + s.id + "：卡片 " + s.card
                    + " 无锚点 " + s.output.anchor
                )
            if s.output.bind in binds:
                errs.append(
                    "步骤 " + s.id + "：bind " + s.output.bind
                    + " 与步骤 " + binds[s.output.bind] + " 重名"
                )
            else:
                binds[s.output.bind] = s.id

        # 规则3/5/8：params 与 foreach 的 ${...} 表达式
        # —— 解析必须成功，且引用的 step/bind 必须存在
        for v in s.params.values():
            if isinstance(v, str) and v.startswith("${"):
                _check_expr_str(v, s.id, step_map, binds, errs)
        if s.foreach and s.foreach.startswith("${"):
            _check_expr_str(s.foreach, s.id, step_map, binds, errs)

        # 规则7：assert condition 语法（MVP-1 仅 <bind>.length > 0）
        for a in s.asserts:
            if not _ASSERT_RE.match(a.condition.strip()):
                errs.append(
                    "步骤 " + s.id + "：assert 表达式非法（MVP-1 仅支持 "
                    + "<bind>.length > 0）：" + a.condition
                )

    # 规则2：依赖闭环（拓扑排序 / DFS 三色标记）
    cycle = _detect_cycle(dag)
    if cycle:
        errs.append("依赖存在循环：" + " -> ".join(cycle))

    return VerifyReport(passed=not errs, errors=errs, warnings=warns,
                        has_write=has_write)


def _check_expr_str(expr: str, cur_step: str, step_map: dict,
                    binds: dict, errs: list) -> None:
    """校验单个 ${...} 表达式：能解析 + 引用的 step/bind 存在。

    ${item} 放行（foreach 内才合法，verify 阶段不强制 foreach 上下文）。
    """
    try:
        node = parse_expr(expr)
    except ExprError as e:
        errs.append(
            "步骤 " + cur_step + "：表达式非法 " + expr + "：" + str(e)
        )
        return
    _check_expr_refs(node, cur_step, step_map, binds, errs)


def _check_expr_refs(node, cur_step: str, step_map: dict,
                     binds: dict, errs: list) -> None:
    """递归检查 VarRef / JoinCall 引用的 step/bind 是否存在。

    - JoinCall：递归检查 arr_expr
    - VarRef：step=="item" 放行；否则 step 必须在 step_map，
      bind（若有）必须在 binds（即上游 step 已声明 output.bind）
    """
    if isinstance(node, JoinCall):
        _check_expr_refs(node.arr_expr, cur_step, step_map, binds, errs)
        return
    if isinstance(node, VarRef) and node.step != "item":
        if node.step not in step_map:
            errs.append(
                "步骤 " + cur_step + "：表达式引用不存在的步骤 "
                + node.step
            )
        elif node.bind and node.bind not in binds:
            errs.append(
                "步骤 " + cur_step + "：表达式引用未绑定的 "
                + node.step + "." + node.bind
            )


def _detect_cycle(dag: DAG) -> list | None:
    """DFS 三色标记检测依赖环。

    Returns:
        环上的 step id 列表（含首尾重复，便于阅读）；无环返回 None
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s.id: WHITE for s in dag.steps}
    stack: list = []

    def dfs(n):
        color[n] = GRAY
        stack.append(n)
        step = next((s for s in dag.steps if s.id == n), None)
        for dep in (step.depends if step else []):
            if dep not in color:
                # 依赖不存在的 step：交给规则 2 兜底（"依赖不存在"），
                # 这里直接跳过避免 KeyError
                continue
            if color[dep] == GRAY:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == WHITE:
                r = dfs(dep)
                if r:
                    return r
        stack.pop()
        color[n] = BLACK
        return None

    for s in dag.steps:
        if color[s.id] == WHITE:
            r = dfs(s.id)
            if r:
                return r
    return None


def main(argv=None) -> int:
    """verify-dag CLI：读 DAG yaml + 卡片库，跑静态校验（不发请求）。

    LLM 生成 DAG 后先过本命令，失败把 errors 回传 LLM 修正。
    """
    import argparse
    from pathlib import Path
    import yaml
    from api_console.call_card import load_cards

    p = argparse.ArgumentParser(
        prog="api-console verify-dag",
        description="DAG 静态校验（12 条规则，不发请求）")
    p.add_argument("--platform", required=True)
    p.add_argument("--dag", required=True, help="DAG yaml 路径")
    a = p.parse_args(argv)

    dag = DAG.from_dict(yaml.safe_load(Path(a.dag).read_text(encoding="utf-8")) or {})
    rep = verify(dag, load_cards(a.platform))
    print(f"[verify-dag] passed={rep.passed} has_write={rep.has_write} "
          f"errors={len(rep.errors)} warnings={len(rep.warnings)}")
    for e in rep.errors:
        print(f"  ERROR  {e}")
    for w in rep.warnings:
        print(f"  WARN   {w}")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
