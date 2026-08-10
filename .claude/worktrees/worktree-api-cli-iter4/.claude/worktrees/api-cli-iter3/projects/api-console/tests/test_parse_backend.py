"""parse_backend 主干测试（adapter 发现/调度/置信度分流/诚实反馈）。

测试设计：
    - test_run_with_easyops_writes_contracts：用真实 easyops fixture（契约样本
      + ENS 样本）+ 真实 easyops adapter 目录，端到端验证 discover→detect HIGH
      →parse→save，contracts.yaml 含 domain_model 条目。
    - test_run_zero_confidence_raises：用空 adapters_dir 触发"未发现任何 adapter"
      的 ParseError（message 含"不支持"），验证诚实反馈路径。

对计划代码的调整：计划原稿用 adapters_sample（含恒 HIGH 的 hi_adapter）+ 空 raw_dir
来触发 ZERO 分流，但 hi_adapter.detect 不依赖 raw_dir 内容，恒返回 HIGH，根本进不了
ZERO 分支；且 hi_adapter.parse 返回的假 dict 缺 BackendContract 必填字段，会抛
TypeError 而非 ParseError。改用空 adapters_dir 直接命中 run() 开头的"未发现任何
adapter"分支，该 message 同样含"不支持"关键词，断言意图保持一致。
"""
from __future__ import annotations
from pathlib import Path

import pytest
import yaml

from api_console.parse_backend import run, ParseError

# fixtures 目录：含 easyops_contract_sample.json + ens_routing_sample.json
EASYOPS_FIX = Path(__file__).parent / "fixtures"
# 真实 easyops adapter 目录（Task 4 已落地 EasyOpsContractAdapter）
EASYOPS_ADAPTERS = (
    Path(__file__).resolve().parents[3]
    / "platforms" / "easyops" / "sources" / "backend" / "adapters"
)


def test_run_with_easyops_writes_contracts(tmp_path):
    """easyops fixture + 真实 adapter：解析成功，contracts.yaml 含 domain_model。"""
    out = tmp_path / "contracts.yaml"
    run(raw_dir=EASYOPS_FIX, adapters_dir=EASYOPS_ADAPTERS, out=out)

    assert out.exists()
    data = yaml.safe_load(out.read_text())
    assert isinstance(data, list) and len(data) > 0
    # 每条至少有 BackendContract 必填字段
    for d in data:
        assert "operation_key" in d
        assert "service" in d
    # 必须含 domain_model 相关路径
    assert any("domain_model" in d["path"] for d in data)


def test_run_zero_confidence_raises(tmp_path):
    """空 adapters_dir：诚实反馈 ParseError，message 含'不支持'。"""
    empty_adapters = tmp_path / "empty_adapters"
    empty_adapters.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(ParseError, match="不支持"):
        run(raw_dir=raw, adapters_dir=empty_adapters, out=tmp_path / "x.yaml")
