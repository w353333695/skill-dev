"""runtime 被动暴露：编排执行失败时把缺口写进 _gaps.yaml。

execute_dag.execute 接受可选 on_error 回调；本模块产出该回调，
在 ExecutionError 抛出前记一条 source=runtime 的缺口（带 triggered_by=step_id）。
失败信息是否真为「知识缺口」由人/LLM 在 report 时复核（severity 默认 medium）。
"""
from __future__ import annotations
from api_console.gaps_store import Gap, add_gap


def make_runtime_sink(workdir, platform):
    """返回 on_error(step_id, error_msg) 回调，供 execute(on_error=...) 注入。"""
    def sink(step_id: str, error_msg: str) -> None:
        add_gap(workdir, platform, Gap(
            source="runtime",
            title=f"编排失败（step={step_id}）",
            detail=error_msg[:300],
            severity="medium",
            triggered_by=step_id or "",
        ))
    return sink
