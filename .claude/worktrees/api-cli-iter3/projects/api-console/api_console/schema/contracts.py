"""后端契约/manifest/index 数据模型。

parse_backend 写 contracts.yaml；register_cards 读它做 path 对齐。
字段对齐 spec 3.3。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import yaml


@dataclass
class BackendContract:
    """单条后端 API 契约（contracts.yaml 一项）。字段对齐 spec 3.3。

    Attributes:
        operation_key: service|method|normalized_uri 三元组（path_align.make_operation_key 产出）
        method: HTTP 方法（大写）
        path: 归一化（brace style）后的后端真实路径
        raw_paths: 原始路径快照 ``{"backend": ..., "frontend": ...}``
        path_source: ``backend_contract | gateway_strip | frontend_raw``
        path_confidence: ``high | medium | low``
        service: 后端 serviceName（如 flowable_service）
        request: ``{"fields": [{"name","type","desc"}, ...]}``
        response: 同 request
        semantic_gaps: 缺 desc 等的字段名列表（LLM 补语义用）
        port: 服务端口（来自 ENS_ROUTING，可能为空）
        source_file: 源契约文件名（便于回查）
    """
    operation_key: str
    method: str
    path: str
    raw_paths: dict
    path_source: str
    path_confidence: str
    service: str
    request: dict
    response: dict
    semantic_gaps: list = field(default_factory=list)
    port: int | None = None
    source_file: str = ""


def save_contracts(contracts: list[BackendContract], path: Path) -> None:
    """写 contracts.yaml。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(
        [asdict(c) for c in contracts], allow_unicode=True, sort_keys=False))


def load_contracts(path: Path) -> list[BackendContract]:
    """读 contracts.yaml。"""
    data = yaml.safe_load(path.read_text()) or []
    return [BackendContract(**d) for d in data]
