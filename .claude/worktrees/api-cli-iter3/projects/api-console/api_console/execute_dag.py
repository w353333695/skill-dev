"""DAG 执行引擎（确定性：发请求 + 锚点提取 + assert + execution.json）。

spec 7.3 / 1.6。LLM 不直接发请求，本模块按 DAG 拓扑序执行：

1. 对每个 step：
   - 调 ``adapter.resolve_endpoint(contract, manifest)`` 拿 :class:`Endpoint`
     （spec 1.5：URL 拼接归 adapter，execute_dag 零平台耦合）；
   - 调 ``adapter.build_auth_headers(endpoint.auth, manifest, request_ctx)``
     拿鉴权头（spec 1.6：鉴权方式全部封在 adapter）；
   - foreach 模式：用 ThreadPoolExecutor 并发执行 N 次（每个 item 独立 context）；
   - 单步模式：解析参数 -> 发请求 -> 业务码校验 -> 按 outputs 锚点提取；
2. asserts 中的 ``<bind>.length > 0`` 失败立即抛 :class:`ExecutionError` 终止 DAG；
3. 末尾按 dag.result 表达式求值得到最终结果。

零平台耦合约束（spec 1.6）：鉴权方式（凭证材料/签名算法/平台特定头）的处理
全部在 adapter，本模块只调 adapter 拿到 headers dict 合并到请求。

adapter 与 execute_dag 之间唯一的约定：build_auth_headers 返回的 dict 里若含
伪头 ``__url_query__``（签名类鉴权方式用），execute_dag 取出后附加到 URL，
不进入真实 HTTP 头。

HTTP 请求由 :mod:`card_invoker` 的 :func:`invoke_card` 发出（单点维护，
execute_dag 与 call_card 共用同一请求层）；单测 patch ``card_invoker.http_request``。
"""
from __future__ import annotations
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from api_console.schema.dag import DAG, Step, extract_jsonpath
from api_console.schema.card import Card
from api_console.schema.expression import parse as parse_expr, eval_expr, eval_when
from api_console.adapter_base import BackendAdapter
from api_console.card_invoker import invoke_card


class ExecutionError(Exception):
    """执行期错误（assert 失败/业务码错/锚点提取失败等）。

    可选属性 ``rollback_log: list | None``：
        默认 ``None``；仅当 execute 主循环触发声明式回滚时才填（由 execute 在
        重抛异常前赋值），结构与 :attr:`ExecutionResult.rollback_log` 一致。
        成功路径无回滚，对应 ``ExecutionResult.rollback_log`` 仍为空 list；
        失败路径调用方应改读异常实例上的此属性拿到回滚记录。
    """
    rollback_log = None


@dataclass
class ExecutionResult:
    """DAG 执行结果。"""
    result: object
    context: dict
    log: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # MVP-1.5：when 跳过的 step id
    rollback_log: list = field(default_factory=list)  # MVP-1.5：回滚记录


# ---------- assert condition 白名单（MVP-1 子集：<bind>.length > 0） ----------
# 用字符类 [a-zA-Z_] [.] [>] 规避反斜杠在 Write/Edit 工具中可能被误转义
_ASSERT_LEN_RE = re.compile(
    r"^([a-zA-Z_]\w*)[.]length\s*[>]\s*0$"
)


def execute(dag: DAG, cards: dict, adapter: BackendAdapter, manifest: dict,
            contracts: Optional[dict] = None, concurrency: int = 5,
            on_error=None,
            has_write: bool = False, yes: bool = False,
            input_fn=input) -> Optional[ExecutionResult]:
    """按拓扑序执行 DAG。

    Args:
        dag: 已通过 verify_dag 校验的 DAG
        cards: name -> Card
        adapter: 平台 adapter 实例（由调用方 discover_adapters 发现后传入），
            用于 ``resolve_endpoint`` 拼 URL（spec 1.5）。
        manifest: manifest.yaml 反序列化结果，含 adapter resolve 与 auth 所需配置；
            adapter resolve 时读，execute_dag 也按 ``Endpoint.auth`` 从中取凭证。
        contracts: 后端契约，接受 list 或 dict（``invoke_card`` 内部归一化）：
            - list：``parse_backend`` 产出的 contracts.yaml 原始格式（每条含 operation_key）
            - dict：``contract_ref -> contract dict`` 映射
            invoke_card 用 ``card.endpoint.contract_ref`` 查后端契约传给 adapter。
            None 或未命中时退化为用 card 自身的 service/method/path 构造 contract dict（兜底）。
        concurrency: foreach 并发上限，默认 5
        on_error: 可选回调 (step_id, error_msg) -> None。execute 抛 ExecutionError 前
            会调用它（若提供），用于 runtime 缺口被动暴露。默认 None 时行为不变。
        has_write: 本 DAG 是否含写操作（由调用方据 VerifyReport.has_write 传入）。
            为 True 且 ``yes`` 非真时，主循环前会打印写计划并等确认输入。
        yes: 为 True 时跳过写计划确认闸直接执行（用户已授权/CI 无人值守场景）。
        input_fn: 确认输入读取函数（默认内置 input），测试可注入 fake。

    Returns:
        ExecutionResult（含 result/context/log）；has_write 且未确认时返回 ``None``
        表示用户取消（主循环未执行）。

    Raises:
        ExecutionError: assert 失败、业务码错、锚点提取失败等
    """
    # context 按 step.id 命名空间存储：context["s1"]["models"] = data，
    # 与 expression.eval_expr 的 ${s1.models} 求值约定对齐
    context: dict = {}
    log: list = []
    skipped: list = []  # MVP-1.5：when 跳过的 step id
    executed_writes: list = []  # MVP-1.5：已成功的写步骤（逆序回滚用）
    rollback_log: list = []     # MVP-1.5：回滚记录（_rollback 填充）
    current_step_id = ""

    # MVP-1.5：写计划确认闸（主循环前）
    # has_write 且用户未授权 yes -> 打印写计划（步骤/卡片/副作用/参数 + 回滚预案），
    # 等用户输入；非 'y' 视为取消，直接返回 None（不进入主循环）。
    if has_write and not yes:
        print("⚠ 本 DAG 含写操作，请确认后执行：\n")
        print("  步骤  卡片              副作用    参数")
        for step in dag.steps:
            c = cards.get(step.card)
            se = c.side_effect if c else "?"
            params = ", ".join(f"{k}={v}" for k, v in step.params.items())
            print(f"  {step.id:<5} {step.card:<18}{se:<10}{params}")
        # 回滚预案（失败时逆序执行）
        rb_lines = []
        for step in dag.steps:
            c = cards.get(step.card)
            if c and c.rollback:
                args = ", ".join(
                    (f"{p.param_key}=${{{step.id}.{p.from_output}.{p.from_field}}}"
                     if p.from_field else
                     f"{p.param_key}=${{{step.id}.{p.from_output}}}")
                    for p in c.rollback.params)
                rb_lines.append(f"  {step.id} → {c.rollback.api}({args})")
        if rb_lines:
            print("\n  回滚预案（失败时逆序执行）：")
            for ln in rb_lines:
                print(ln)
        ans = input_fn("\n输入 y 执行，n 取消：")
        if ans.strip().lower() != "y":
            print("已取消。")
            return None

    try:
        for step in dag.steps:
            current_step_id = step.id
            card = cards[step.card]
            # MVP-1.5：when 条件跳过（空串=无条件执行；为假则记录并跳过该步）
            if step.when and not eval_when(step.when, context):
                skipped.append(step.id)
                continue
            if step.foreach:
                items = eval_expr(parse_expr(step.foreach), context)
                results = []
                with ThreadPoolExecutor(max_workers=concurrency) as ex:
                    futures = [
                        ex.submit(_exec_one, step, card, contracts,
                                  {"item": it, **context},
                                  adapter, manifest, log)
                        for it in items
                    ]
                    for f in futures:
                        results.append(f.result())
                if step.output:
                    context.setdefault(step.id, {})[step.output.bind] = results
            else:
                data = _exec_one(step, card, contracts, context, adapter, manifest, log)
                if step.output:
                    context.setdefault(step.id, {})[step.output.bind] = data
            # MVP-1.5：记录已成功的写步骤（side_effect != read）。
            # 写请求已发出即视为副作用已落库（即便后续 assert 失败也要回滚它），
            # 故在 assert 校验前记录。foreach 与单步两分支统一在此处判定。
            if card.side_effect != "read":
                executed_writes.append(step)
            # assert 校验（MVP-1 子集：仅 <bind>.length > 0）
            # bind 名在当前 step 命名空间下查找（与 step 声明 output.bind 对齐）
            for a in step.asserts:
                if not _eval_assert(a.condition, context, step.id):
                    raise ExecutionError("断言失败：" + a.message)
    except ExecutionError as e:
        # MVP-1.5：声明式回滚（逆序回滚已成功的写步骤，在 on_error 之前）
        if executed_writes:
            rollback_log = _rollback(executed_writes, context, cards,
                                     adapter, manifest, log)
            # 失败路径下调用方拿到的是异常实例（非 ExecutionResult），
            # 把回滚记录挂到异常上，使其与成功路径的 result.rollback_log 对齐。
            e.rollback_log = rollback_log
        if on_error is not None:
            try:
                on_error(current_step_id, str(e))
            except Exception:
                pass  # 埋点失败不影响执行错误传播
        raise

    result = eval_expr(parse_expr(dag.result), context) if dag.result else None
    return ExecutionResult(result=result, context=context, log=log,
                           skipped=skipped, rollback_log=rollback_log)


def _rollback(executed_writes, context, cards, adapter, manifest, log) -> list:
    """MVP-1.5：逆序回滚已成功的写步骤。

    仅当卡片声明了 ``rollback``（:class:`schema.card.Rollback`）才回滚；
    回滚失败不中断流程，记入日志交人复核（best-effort）。

    取值约定（与 execute 主循环的 context 命名空间一致）：
        context[step.id][step.output.bind] = _exec_one 锚点提取结果
    - 结果是 dict：按 ``rb.param_from_output`` 取字段（如 {"instanceId": "x"} -> "x"）
    - 结果是标量：直接用

    Args:
        executed_writes: 已成功的写步骤列表（按执行顺序；本函数逆序遍历）
        context: execute 主循环的上下文（按 step.id 命名空间）
        cards: name -> Card（查回滚目标卡片）
        adapter: 平台 adapter 实例（传给 invoke_card）
        manifest: manifest.yaml 反序列化结果（传给 invoke_card）
        log: execute 主循环的日志（当前未写入，保留参数以备后续扩展）

    Returns:
        rollback_log: list[dict]，每条形如
            {"step": step.id, "card": rb.api, "status": "ok" | "failed", ...}
    """
    # 函数内运行时查表：测试 monkeypatch ``card_invoker.invoke_card`` 可拦截
    from api_console.card_invoker import invoke_card
    rollback_log = []
    for step in reversed(executed_writes):
        card = cards.get(step.card)
        rb = card.rollback if card else None
        if not rb:
            # 卡片未声明回滚 → 跳过（静默，不记入日志）
            continue
        # 取值：context 按 step.id 命名空间，用 step.output.bind 取 bound
        bound = None
        if step.output:
            bound = context.get(step.id, {}).get(step.output.bind)
        # 按 rollback.params 组装多参数 dict，每条独立取值：
        #   - from_field 非空：对象锚点，按 from_field 取字段（多参数主场景）
        #   - from_field 空 + bound 是 dict：旧单参数兼容，按 from_output 取字段
        #     （旧 param_from_output 既是锚点名又是字段名）
        #   - from_field 空 + 标量：直接用 bound（标量锚点单参数）
        if isinstance(bound, list):
            # foreach 步骤的 bound 是 list，foreach 回滚语义待定（多对一映射未定义），
            # 静默跳过（best-effort 不回滚），留待后续 MVP 明确语义。
            continue
        rb_params = {}
        for p in rb.params:
            if p.from_field:
                rb_params[p.param_key] = bound.get(p.from_field) if isinstance(bound, dict) else None
            elif isinstance(bound, dict):
                rb_params[p.param_key] = bound.get(p.from_output)
            else:
                rb_params[p.param_key] = bound
        try:
            # invoke_card 真实签名：(card: Card, params, adapter, manifest, contracts)
            # 第一参数是 Card 对象；contracts 位无默认值，显式传 None（兜底走 card 字段）
            invoke_card(cards[rb.api], rb_params,
                        adapter, manifest, None)
            rollback_log.append({"step": step.id, "card": rb.api, "status": "ok"})
        except Exception as re:
            # 回滚失败不中断：记入日志交人复核（声明式回滚是 best-effort）
            rollback_log.append({"step": step.id, "card": rb.api,
                                 "status": "failed", "error": str(re)})
    return rollback_log


def _exec_one(step: Step, card: Card, contracts, context: dict,
              adapter: BackendAdapter, manifest: dict, log: list) -> object:
    """执行单步一次。

    流程：解析参数 ``${}`` -> 调 invoke_card 发请求 -> 业务码校验 -> 锚点提取。
    请求层（endpoint 解析/path 替换/鉴权/签名伪头）封在 invoke_card（card_invoker）。

    Args:
        step: 待执行的步骤
        card: 步骤对应的卡片
        contracts: 后端契约（list 或 dict，归一化由 invoke_card 完成）
        context: 当前可见的求值上下文（foreach 模式下含 ``item``）
        adapter: 平台 adapter 实例
        manifest: manifest.yaml 反序列化结果
        log: 执行日志（追加 dict）

    Returns:
        按 step.output.anchor 提取后的对象；step.output 为空时返回整个 data
    """
    params = _resolve_params(step.params, context)
    result = invoke_card(card, params, adapter, manifest, contracts)
    ctype = result.resp.headers.get("Content-Type", "")
    # 仅当 Content-Type 是明确字符串且不含 application/json 才走二进制；
    # 缺省/非字符串（旧 mock 的 MagicMock）一律按既有 JSON 路径处理（零影响）。
    is_binary = isinstance(ctype, str) and "application/json" not in ctype
    if is_binary:
        # 二进制下载：跳过业务码校验，http 2xx 即成功，落盘并绑定文件对象。
        # 必须在锚点逻辑之前返回——export 卡片 anchor 为空，勿误入"无锚点"分支。
        if not (200 <= result.resp.status_code < 300):
            raise ExecutionError(
                card.name + " 下载失败 http_status=" + str(result.resp.status_code)
            )
        dl = _download_dir()
        dl.mkdir(parents=True, exist_ok=True)
        path = dl / (step.id + _download_ext(result.resp))
        path.write_bytes(result.resp.content)
        log.append({"card": card.name, "url": result.url,
                    "status": result.resp.status_code, "download": str(path)})
        return {"file_path": str(path), "size": len(result.resp.content),
                "content_type": ctype}
    body = result.resp.json()
    if body.get("code", 0) != 0:
        raise ExecutionError(
            card.name + " 业务码错：code=" + str(body.get("code"))
            + " " + str(body.get("error"))
        )
    data = body.get("data")
    log.append({"card": card.name, "url": result.url,
                "status": result.resp.status_code})
    if step.output:
        if not step.output.anchor:
            # anchor 为空：声明 bind 但不做锚点提取，直接绑整个 data（纯增量，
            # 既有用例均用非空 anchor，行为不变）
            return data
        anchor = card.outputs.get(step.output.anchor)
        if not anchor:
            raise ExecutionError(
                card.name + " 无锚点 " + step.output.anchor + "（卡片 outputs 过时）"
            )
        try:
            # jsonpath 是 $.data.xxx，因此把 data 包一层 {"data": data}
            return extract_jsonpath(anchor.jsonpath, {"data": data})
        except KeyError as e:
            raise ExecutionError(
                card.name + " 锚点提取失败 " + anchor.jsonpath + "：" + str(e)
            )
    return data


# ---------- 非 JSON（二进制下载）分流辅助 ----------
_DAG_DOWNLOAD_EXT = {
    "application/gzip": ".tar.gz",
    "application/x-gzip": ".tar.gz",
    "application/octet-stream": ".bin",
    "application/zip": ".zip",
}


def _workdir():
    """产物根：run.sh 钉的 API_CONSOLE_WORKDIR，缺省当前目录。"""
    return Path(os.environ.get("API_CONSOLE_WORKDIR", os.getcwd()))


def _download_dir():
    """DAG 下载目录：tmp/orchestrate/<时间戳>/download。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    return _workdir() / "tmp" / "orchestrate" / ts / "download"


def _download_ext(resp):
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        name = cd.split("filename=", 1)[1].strip().strip('"').split(";")[0]
        if "." in name:
            return "." + name.rsplit(".", 1)[1]
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    return _DAG_DOWNLOAD_EXT.get(ctype, ".bin")


def _resolve_params(params: dict, context: dict) -> dict:
    """解析 params 中的 ``${...}`` 表达式；字面量原样返回。"""
    out = {}
    for k, v in params.items():
        if isinstance(v, str) and v.startswith("${"):
            out[k] = eval_expr(parse_expr(v), context)
        else:
            out[k] = v
    return out


def _eval_assert(condition: str, context: dict, step_id: str = "") -> bool:
    """极简 assert 求值：MVP-1 仅支持 ``<bind>.length > 0`` 形式。

    Args:
        condition: assert 条件字符串
        context: 执行上下文（按 step.id 命名空间）
        step_id: 当前步骤 id（用于在 context[step_id] 下查 bind）；
            缺省时退回在顶层 context 查找

    无法识别的 condition 不阻断（避免误杀 LLM 写出的更复杂断言，
    复杂断言由后续 MVP 迭代扩展）。
    """
    m = _ASSERT_LEN_RE.match(condition.strip())
    if not m:
        return True
    bind = m.group(1)
    # bind 优先在当前 step 命名空间下查；找不到再退回顶层
    ns = context.get(step_id, {}) if step_id else {}
    val = ns.get(bind) if isinstance(ns, dict) else None
    if val is None:
        val = context.get(bind)
    return isinstance(val, list) and len(val) > 0


def main(argv=None) -> int:
    """execute-dag CLI：加载平台 + 卡片 + 契约，verify 通过后按拓扑序真调执行。

    读 DAG yaml + --platform，复用 call_card 的加载链路（load_platform/load_cards/
    load_contracts），先静态校验再 execute。写操作受 ``--yes`` 确认闸控制。
    """
    import argparse
    import json
    from pathlib import Path
    import yaml
    from api_console.call_card import load_platform, load_cards, load_contracts
    from api_console.verify_dag import verify

    p = argparse.ArgumentParser(
        prog="api-console execute-dag",
        description="按拓扑序真调执行 DAG（verify 通过后）")
    p.add_argument("--platform", required=True)
    p.add_argument("--dag", required=True, help="DAG yaml 路径")
    p.add_argument("--env", default="")
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--yes", action="store_true", help="跳过写计划确认闸（CI/已授权）")
    a = p.parse_args(argv)

    dag = DAG.from_dict(yaml.safe_load(Path(a.dag).read_text(encoding="utf-8")) or {})
    adapter, manifest = load_platform(a.platform, a.env)
    cards = load_cards(a.platform)
    rep = verify(dag, cards)
    if not rep.passed:
        print(f"[execute-dag] 校验未通过（{len(rep.errors)} errors），终止")
        return 1
    result = execute(dag, cards, adapter, manifest, load_contracts(a.platform),
                     concurrency=a.concurrency, has_write=rep.has_write, yes=a.yes)
    if result is None:
        print("[execute-dag] 用户取消（写计划未确认）")
        return 1
    log = getattr(result, "log", [])
    print(f"[execute-dag] 完成，{len(log)} 条 step 日志")
    print(json.dumps(log, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
