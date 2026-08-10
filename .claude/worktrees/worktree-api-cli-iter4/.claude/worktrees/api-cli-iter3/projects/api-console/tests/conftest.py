"""pytest 共享配置。

包以 editable 安装（``uv sync``）后，测试直接 ``from api_console.xxx import ...``，
不再需要旧的 scripts/ sys.path hack。

integration 标记的测试默认 skip（连真实平台、依赖 cookie/网络/已注册卡片，
非主干单测范畴）；需显式 ``-m integration`` 启用。
"""
from __future__ import annotations
import pytest


def pytest_collection_modifyitems(config, items):
    """未在命令行选 integration 时，跳过所有 integration 标记的测试。"""
    markexpr = config.getoption("-m") or ""
    if "integration" not in markexpr:
        skip_integration = pytest.mark.skip(
            reason="integration 测试需真实平台环境，默认 skip（-m integration 启用）"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)
