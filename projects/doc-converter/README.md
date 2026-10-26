# doc-converter

基于 Python 的文档格式转换 CLI，支持全量转换或提取部分内容转换。采用注册表 + 自动发现架构，易扩展新格式。

## 依赖分层（核心轻量）

核心包只依赖纯 python / 小 wheel 库（click / markdown / openpyxl / python-docx / pygments / pyyaml），任意 Python 版本秒装。重依赖按需以 **extras** 提供：

| 范围 | 安装 | 覆盖转换 |
|------|------|---------|
| 核心（默认） | `pip install doc-converter` | md/html/docx/excel/csv/json/代码高亮；**md→pdf 走系统 pandoc+xelatex** |
| `[render]` | `pip install 'doc-converter[render]'` | md/html→pdf 的 playwright 路径、mermaid/代码→图片 |
| `[pdf]` | `pip install 'doc-converter[pdf]'` | PDF→Word（拖 opencv-python ~60MB） |

> **md→pdf 默认走系统 pandoc+xelatex（免 chromium、支持中文）**；缺 pandoc/xelatex 时回退 `[render]` 的 playwright。详见 `doctor`。

## 安装

**开发态**（workspace 内，editable）:
```bash
uv run --project projects/doc-converter doc-converter list
```

**分发态**（`skills/doc-converter/scripts/setup.sh` 装好 CLI 后裸调）:
```bash
doc-converter list
doc-converter doctor          # 自检：核心依赖 + 可选 extras + 运行时大件
```

**运行时大件**（仅 `[render]` 路径需要）:
```bash
doc-converter install-deps    # 封装 playwright install chromium
```

## 支持的转换

| 转换 | 命令示例 | 备注 |
|------|---------|------|
| Mermaid -> PNG/SVG | `convert x.md -t png` | 需 `[render]`；`--extract mermaid` 提取 |
| Markdown -> PDF | `convert x.md -t pdf` | 默认 pandoc+xelatex（核心）；回退 `[render]` |
| Markdown -> HTML | `convert x.md -t html` | 核心，含样式/Mermaid/**代码高亮** |
| Markdown -> Word | `convert x.md -t docx` | 核心 |
| Word -> Markdown | `convert x.docx -t md` | 核心，需系统 pandoc；图片提取到 `_assets/<文件名>/` |
| Markdown -> Excel | `convert x.md -t xlsx` | 核心，`--extract table` |
| Markdown -> 纯文本 | `convert x.md -t txt` | 核心，去标记保留段落结构 |
| Markdown -> JSON | `convert x.md -t json` | 核心，`--extract outline/links/images/code` |
| HTML -> PDF | `convert x.html -t pdf` | 需 `[render]` |
| CSV/TSV -> Excel | `convert x.csv -t xlsx` | 核心 |
| Excel -> CSV | `convert x.xlsx -t csv` | 核心 |
| JSON/YAML -> Excel | `convert x.json -t xlsx` | 核心，自动扁平化嵌套 |
| JSON/YAML -> CSV | `convert x.json -t csv` | 核心，自动扁平化嵌套 |
| PDF -> Word | `convert x.pdf -t docx` | 需 `[pdf]` |
| 代码 -> 高亮HTML | `convert x.py -t html` | 核心（pygments，有 fallback） |
| 代码 -> 高亮图片 | `convert x.py -t png` | 需 `[render]` |

## 用法

```bash
# 基础转换
doc-converter convert <输入文件> -t <目标格式> [-o 输出路径]

# 提取部分内容转换（mermaid/表格/代码；md->json 还可提取大纲/链接/图片）
doc-converter convert <输入文件> -t <目标格式> --extract <mermaid|table|outline|links|images|code>

# 列出所有支持的转换
doc-converter list

# 检查转换支持和依赖
doc-converter check <源格式> <目标格式>

# 环境自检
doc-converter doctor
```

### 常见场景

**MD 含 Mermaid 转 PDF**（走系统 pandoc，免 chromium）:
```bash
doc-converter convert doc.md -t pdf -o doc.pdf
```

**从 MD 中提取 Mermaid 转图片**（需 `[render]`）:
```bash
doc-converter convert doc.md -t png --extract mermaid -o diagram.png
```

**JSON 转 Excel**:
```bash
doc-converter convert data.json -t xlsx -o data.xlsx
```

**从 MD 提取结构化数据 / 纯文本**:
```bash
doc-converter convert doc.md -t json --extract outline -o outline.json  # 标题大纲树
doc-converter convert doc.md -t json --extract code    -o code.json     # 所有代码块（跳过 mermaid）
doc-converter convert doc.md -t txt  -o doc.txt                         # 纯文本（去标记）
```

**Markdown 转 Word（可选封面页 + 自动目录）**:
```bash
doc-converter convert 手册.md -t docx
# 首个 H1 转为封面页；封面页 / 目录页 / 正文之间自动分页
doc-converter convert 手册.md -t docx --options cover=true --options toc=true
# 可调目录标题/深度（默认 目录 / 3 级）
doc-converter convert 手册.md -t docx --options cover=true --options toc=true \
  --options toc_title=目录 --options toc_depth=3
# 标题自动编号 1 / 1.1 / 1.1.1（写入 Heading 样式，增删标题自动重排）
doc-converter convert 手册.md -t docx --options cover=true --options toc=true \
  --options heading_numbering=true
# 封面占用首个 H1 后，正文标题自动上提一级（原 H2 → H1）
# H1 分页写入 Heading 1 样式本身，设置标题一即自动段前分页
# 如需关闭：--options h1_page_break=false
```
> 目录标题自动居中；封面标题、目录标题与各级标题统一使用默认黑色（不走 Word 模板主题蓝）。
> 目录为 Word 原生 TOC 域，页码由 Word/WPS 打开时自动更新（已写入 `updateFields`）；
> 若查看器不自动更新，右键目录 →「更新域」或按 F9。

**Word 转 Markdown（提取图片）**:
```bash
doc-converter convert 手册.docx -t md -o 手册.md
# 图片默认提取到 输出md同目录/_assets/手册/，md 中为相对引用
# 自定义图片目录：
doc-converter convert 手册.docx -t md -o 手册.md --options media_dir=assets/img
```
> 依赖系统 `pandoc`（`doctor` 会检测；缺失时按提示安装：macOS `brew install pandoc`，Debian `apt install pandoc`）。

### 额外选项

通过 `--options` 传递:
```bash
--options landscape=true        # PDF 横向
--options theme=dark            # Mermaid 主题
--options encoding=gbk          # CSV 编码
--options media_dir=assets/img  # Word->MD 图片目录
--options cover=true            # md->Word：首个 H1 转封面页
--options toc=true              # md->Word：生成目录页（原生 TOC 域）
--options toc_title=目录        # md->Word：目录标题
--options toc_depth=3           # md->Word：目录收录级别（1-6）
--options toc_page_break=true   # md->Word：目录后分页（默认 true）
--options h1_page_break=true    # md->Word：H1 段前分页写入 Heading 1 样式（cover=true 时默认开启）
--options heading_numbering=true  # md->Word：标题自动编号 1/1.1/1.1.1（写入样式，增删自动重排）
--options cjk_font="Noto Serif CJK SC"  # md→pdf (pandoc) 中文字体
```

## 架构

转换器采用注册表 + 自动发现模式：`doc_converter/converters/` 下每个模块用 `@register` 装饰器注册，包导入时自动扫描加载。新增格式只需新建文件 + 继承 `BaseConverter` + 实现 `convert()`，详见 [`docs/converter-guide.md`](docs/converter-guide.md)。

## 开发

```bash
cd projects/doc-converter
uv sync                  # 建 venv + 装核心依赖（轻量）
uv sync --extra render   # 额外装 playwright（开发渲染路径时）
uv run pytest            # 跑测试
uv run doc-converter list
uv build                 # 打 whl -> dist/
```
