"""后端契约数据模型测试。"""
from __future__ import annotations
from pathlib import Path
from api_console.schema.contracts import BackendContract, load_contracts, save_contracts


def test_contract_roundtrip(tmp_path):
    c = BackendContract(
        operation_key="flowable_service|GET|/api/x/v1/y",
        method="GET", path="/api/x/v1/y",
        raw_paths={"backend": "/api/x/v1/y", "frontend": "/next/.../api/x/v1/y"},
        path_source="backend_contract", path_confidence="high",
        service="flowable_service", port=8134,
        request={"fields": [{"name": "Q", "type": "string"}]},
        response={"fields": [{"name": "list", "type": "array"}]},
        semantic_gaps=[], source_file="x.json",
    )
    p = tmp_path / "contracts.yaml"
    save_contracts([c], p)
    loaded = load_contracts(p)
    assert len(loaded) == 1
    assert loaded[0].operation_key == c.operation_key
    assert loaded[0].port == 8134
    assert loaded[0].request["fields"][0]["name"] == "Q"
