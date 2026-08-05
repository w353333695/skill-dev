# 转换器扩展指南

如何为 doc-converter 添加新的格式转换支持。

## 添加新转换器

### 步骤

1. 在 `scripts/converters/` 下新建 Python 文件
2. 继承 `BaseConverter`
3. 用 `@register` 装饰器注册
4. 框架自动发现并加载

### 示例：添加 PDF → 文本提取

```python
"""PDF → TXT 转换器"""
from pathlib import Path
from .base import BaseConverter, ConvertResult, register


@register
class PdfToText(BaseConverter):
    name = "pdf-text"
    source_formats = ["pdf"]
    target_formats = ["txt"]
    description = "PDF 提取文本内容"
    dependencies = ["pymupdf"]  # pip install pymupdf

    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult:
        import fitz  # pymupdf

        doc = fitz.open(str(input_path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        output_path.write_text("\n".join(text_parts), encoding="utf-8")
        return ConvertResult(
            True, output_path=output_path,
            message=f"已提取 {len(text_parts)} 页文本"
        )
```

## 关键接口

### BaseConverter

```python
class BaseConverter(abc.ABC):
    # 必须定义
    name: str               # 转换器唯一名称
    source_formats: list    # 支持的源格式扩展名 (不含点)
    target_formats: list    # 支持的目标格式扩展名
    description: str        # 简短描述
    dependencies: list      # 所需 pip 包名 (import 名)

    # 必须实现
    def convert(self, input_path: Path, output_path: Path, **options) -> ConvertResult: ...

    # 可选覆盖
    def can_convert(self, source_fmt, target_fmt) -> bool: ...
    def check_dependencies(self) -> tuple[bool, list[str]]: ...
    def extract_content(self, input_path, selector=None) -> str: ...
```

### ConvertResult

```python
@dataclass
class ConvertResult:
    success: bool                   # 是否成功
    output_path: Path | None = None # 输出文件路径
    message: str = ""               # 结果消息
    metadata: dict = {}             # 额外信息
```

### 工具函数

`renderer.py` 提供共享的 Playwright 渲染能力：

```python
from .renderer import html_to_pdf, html_to_image

# HTML 内容 → PDF
html_to_pdf(html_string, output_path, margin={...}, landscape=False)

# HTML 内容 → 截图
html_to_image(html_string, output_path, selector="body", width=1200, device_scale_factor=2)
```

## 注意事项

### 格式冲突

同一 `(source, target)` 对只能注册一个转换器。后注册的会覆盖先注册的。
如果需要根据内容选择不同转换器（如 `.md` 可以是 Markdown 也可以是代码），
应在更专用的转换器中优先注册。

### 提取模式

转换器可通过 `options.get("extract")` 支持部分内容提取：
- `mermaid`: 提取 Mermaid 代码块
- `table`: 提取表格
- `code`: 提取代码块

### 依赖声明

`dependencies` 列表使用 **import 名**（不是 pip 包名）：
- `python-docx` → 写 `"docx"`
- `pymupdf` → 写 `"fitz"`
- `Pillow` → 写 `"PIL"`

### 文件结构

```
scripts/converters/
├── __init__.py          # 自动发现 (勿修改)
├── base.py              # 基类 + 注册表 (勿修改)
├── renderer.py          # Playwright 渲染工具 (共享)
├── mermaid_image.py     # Mermaid → PNG/SVG
├── md_html.py           # Markdown → HTML
├── md_pdf.py            # Markdown → PDF
├── md_docx.py           # Markdown → Word
├── md_table_excel.py    # MD表格 → Excel
├── html_pdf.py          # HTML → PDF
├── csv_excel.py         # CSV ↔ Excel
├── json_table.py        # JSON/YAML → Excel/CSV
├── code_highlight.py    # 代码 → 高亮HTML/PNG
└── (新转换器).py         # 在此添加
```
