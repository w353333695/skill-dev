---
name: doc-converter
description: This skill should be used when the user asks to "转换格式", "转PDF", "转图片", "导出Excel", "MD转PDF", "Word转Markdown", "docx转md", "提取Word图片", "Mermaid转图片", "CSV转Excel", "JSON转表格", "代码高亮", "提取表格", "格式转换", "PDF转Word", "convert to PDF", "export as image", "markdown to word", "docx to markdown", "word to md", "pdf to docx", or needs to convert documents between formats or extract content from files.
---

# 文档格式转换器 (Doc Converter)

基于 Python 的文档格式转换工具，支持全量转换或提取部分内容转换。采用插件式架构，易于扩展新格式。

## 支持的转换

| 转换 | 命令示例 | 提取模式 |
|------|---------|---------|
| Mermaid → PNG/SVG | `-t png` | 从 MD 提取 mermaid 块: `--extract mermaid` |
| Markdown → PDF | `-t pdf` | 全量，含 Mermaid 渲染 |
| Markdown → HTML | `-t html` | 全量，含样式和 Mermaid |
| Markdown → Word | `-t docx` | 全量 |
| Word → Markdown | `-t md` | 全量，图片提取到 `_assets/<文件名>/` |
| Markdown → Excel | `-t xlsx` | 提取表格: `--extract table` |
| HTML → PDF | `-t pdf` | 全量 |
| CSV/TSV → Excel | `-t xlsx` | 全量 |
| Excel → CSV | `-t csv` | 全量 |
| JSON/YAML → Excel | `-t xlsx` | 自动扁平化嵌套 |
| JSON/YAML → CSV | `-t csv` | 自动扁平化嵌套 |
| PDF → Word | `-t docx` | 全量，保留排版和表格 |
| 代码 → 高亮HTML | `-t html` | 全量，Pygments 语法高亮 |
| 代码 → 高亮图片 | `-t png` | 全量 |

## 使用方式

```bash
# 基础转换
python scripts/convert.py convert <输入文件> -t <目标格式> [-o 输出路径]

# 提取部分内容转换
python scripts/convert.py convert <输入文件> -t <目标格式> --extract <mermaid|table|code>

# 列出所有支持的转换
python scripts/convert.py list

# 检查转换支持和依赖
python scripts/convert.py check <源格式> <目标格式>
```

## 工作流程

### 1. 识别转换需求

从用户描述中提取：
- **源文件**：路径和格式
- **目标格式**：期望的输出格式
- **提取模式**：全量还是提取部分 (mermaid/table/code)
- **额外选项**：主题、编码、页面方向等

### 2. 检查依赖

执行转换前，先运行 `check` 确认转换器就绪：
```bash
python scripts/convert.py check md pdf
```

缺少依赖时提示安装：
```bash
{项目根目录}/.venv/bin/pip install playwright markdown openpyxl python-docx pygments
```

### 3. 执行转换

根据需求构造命令执行转换。常见场景：

**MD 含 Mermaid 转 PDF**:
```bash
python scripts/convert.py convert doc.md -t pdf -o doc.pdf
```

**从 MD 中提取 Mermaid 转图片**:
```bash
python scripts/convert.py convert doc.md -t png --extract mermaid -o diagram.png
```

**JSON 转 Excel**:
```bash
python scripts/convert.py convert data.json -t xlsx -o data.xlsx
```

**Word 转 Markdown（提取图片）**:
```bash
python scripts/convert.py convert 手册.docx -t md -o 手册.md
# 图片默认提取到 输出md同目录/_assets/手册/，md 中为相对引用
# 自定义图片目录：
python scripts/convert.py convert 手册.docx -t md -o 手册.md --options media_dir=assets/img
```
> 依赖系统 `pandoc`（缺失时按提示安装：macOS `brew install pandoc`）。
> 文档中以绝对路径/外链存在、未真正嵌入的图片会保留引用并在结果中给出警告。

### 4. 额外选项

通过 `--options` 传递:
```bash
# PDF 横向打印
python ... convert doc.md -t pdf --options landscape=true

# 指定 Mermaid 主题
python ... convert doc.md -t png --extract mermaid --options theme=dark

# 指定编码
python ... convert data.csv -t xlsx --options encoding=gbk
```

## 架构说明

转换器采用注册表模式，新增格式只需在 `scripts/converters/` 下创建文件。
详见 `references/converter-guide.md`。

## 依赖

| 库 | 用途 | 安装 |
|----|------|------|
| playwright | PDF/截图渲染 | `pip install playwright && playwright install chromium` |
| markdown | MD→HTML | `pip install markdown` |
| openpyxl | Excel 读写 | `pip install openpyxl` |
| python-docx | Word 生成 | `pip install python-docx` |
| pdf2docx | PDF→Word | `pip install pdf2docx` |
| pygments | 代码高亮 | `pip install pygments` |
| pandoc (系统) | Word→Markdown | `brew install pandoc`（macOS），非 pip 包 |
