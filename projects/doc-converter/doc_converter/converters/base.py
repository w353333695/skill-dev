"""
转换器基类和注册表。

扩展新转换器只需：
1. 在 converters/ 下新建 .py 文件
2. 继承 BaseConverter
3. 实现 convert() 方法
4. 用 @register 装饰器注册

框架会自动发现并注册所有转换器。
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 全局注册表: {(source_fmt, target_fmt): converter_class}
_REGISTRY: dict[tuple[str, str], type["BaseConverter"]] = {}

# pip 包名 -> import 名映射（仅两者不同的）。dependencies 存 pip 包名，
# check_dependencies 据此映射探测，缺失返回 pip 名供用户直接 pip install。
PIP_TO_IMPORT: dict[str, str] = {
    "python-docx": "docx",
    "pymupdf": "fitz",
    "Pillow": "PIL",
}


@dataclass
class ConvertResult:
    """转换结果"""
    success: bool
    output_path: Path | None = None
    message: str = ""
    metadata: dict = field(default_factory=dict)


class BaseConverter(abc.ABC):
    """
    转换器基类。

    子类必须定义:
        name: str           - 转换器名称
        source_formats: list - 支持的源格式 (如 ["md", "markdown"])
        target_formats: list - 支持的目标格式 (如 ["pdf", "html"])

    子类必须实现:
        convert(input_path, output_path, **options) -> ConvertResult
    """

    name: str = ""
    source_formats: list[str] = []
    target_formats: list[str] = []
    description: str = ""
    dependencies: list[str] = []  # 所需 pip 包名（如 python-docx，非 import 名 docx）

    @abc.abstractmethod
    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        """
        执行转换。

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            **options: 转换选项 (由各子类定义)

        Returns:
            ConvertResult
        """
        ...

    def can_convert(self, source_fmt: str, target_fmt: str) -> bool:
        """检查是否支持指定的转换"""
        return (
            source_fmt.lower() in [f.lower() for f in self.source_formats]
            and target_fmt.lower() in [f.lower() for f in self.target_formats]
        )

    def check_dependencies(self) -> tuple[bool, list[str]]:
        """检查依赖是否已安装，返回 (all_ok, missing_list)。

        dependencies 存 pip 包名；经 PIP_TO_IMPORT 映射到 import 名探测，
        缺失时返回 pip 名（用户可直接 ``pip install``）。
        """
        missing = []
        for dep in self.dependencies:
            import_name = PIP_TO_IMPORT.get(dep, dep.replace("-", "_"))
            try:
                __import__(import_name)
            except ImportError:
                missing.append(dep)
        return len(missing) == 0, missing

    def extract_content(self, input_path: Path, selector: str | None = None) -> str:
        """
        从输入文件提取内容。

        Args:
            input_path: 输入文件
            selector: 提取选择器 (如 "mermaid" 提取 mermaid 代码块,
                      "table" 提取表格, None 为全量)
        """
        text = input_path.read_text(encoding="utf-8")
        if selector is None:
            return text
        # 子类可覆盖此方法实现特定提取逻辑
        return text


def register(cls: type[BaseConverter]) -> type[BaseConverter]:
    """装饰器: 注册转换器到全局注册表"""
    instance = cls()
    for src in cls.source_formats:
        for tgt in cls.target_formats:
            key = (src.lower(), tgt.lower())
            if key in _REGISTRY:
                logger.warning(
                    f"转换器冲突: {key} 已由 {_REGISTRY[key].name} 注册, "
                    f"将被 {cls.name} 覆盖"
                )
            _REGISTRY[key] = cls
            logger.debug(f"注册转换器: {src} -> {tgt} ({cls.name})")
    return cls


def get_converter(source_fmt: str, target_fmt: str) -> BaseConverter | None:
    """根据源/目标格式获取转换器实例"""
    key = (source_fmt.lower(), target_fmt.lower())
    cls = _REGISTRY.get(key)
    return cls() if cls else None


def list_converters() -> list[dict]:
    """列出所有已注册的转换器"""
    seen = set()
    result = []
    for (src, tgt), cls in sorted(_REGISTRY.items()):
        if cls.name not in seen:
            seen.add(cls.name)
            inst = cls()
            ok, missing = inst.check_dependencies()
            result.append({
                "name": cls.name,
                "description": cls.description,
                "source_formats": cls.source_formats,
                "target_formats": cls.target_formats,
                "dependencies": cls.dependencies,
                "deps_ok": ok,
                "deps_missing": missing,
            })
    return result


def list_conversions() -> list[tuple[str, str, str]]:
    """列出所有支持的转换路径: [(source, target, converter_name)]"""
    return [
        (src, tgt, cls.name)
        for (src, tgt), cls in sorted(_REGISTRY.items())
    ]


def load_template(name: str) -> str:
    """读取包内 templates/ 下的模板文件；缺失时返回最小 HTML 骨架。

    用 importlib.resources 访问，打包进 whl 后仍可用。
    """
    try:
        from importlib.resources import files
        return (files("doc_converter") / "templates" / name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return "<html><head><title>{{TITLE}}</title>{{EXTRA_HEAD}}</head><body>{{CONTENT}}</body></html>"
