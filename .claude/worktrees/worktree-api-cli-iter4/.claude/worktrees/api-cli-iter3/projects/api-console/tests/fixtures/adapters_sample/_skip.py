"""下划线开头模块：discover_adapters 应跳过。"""
from __future__ import annotations


class Adapter:
    """假 adapter，name=skip。不应被加载。"""

    name = "skip"
