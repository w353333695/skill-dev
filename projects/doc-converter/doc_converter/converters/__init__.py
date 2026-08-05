"""
转换器自动发现模块。

导入此包时自动扫描 converters/ 下所有 .py 模块，
触发 @register 装饰器完成注册。
"""

import importlib
import pkgutil
from pathlib import Path


def _auto_discover():
    """自动导入本包下所有模块，触发转换器注册"""
    package_dir = Path(__file__).parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_"):
            continue
        importlib.import_module(f".{info.name}", __package__)


_auto_discover()

# 重新导出常用接口
from .base import (  # noqa: E402
    BaseConverter,
    ConvertResult,
    register,
    get_converter,
    list_converters,
    list_conversions,
)
