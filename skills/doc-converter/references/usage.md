# 常用转换速查

供 skill 编排时快速参考。完整支持矩阵、用法、依赖、扩展指南见能力 project：
`projects/doc-converter/README.md`、`projects/doc-converter/docs/converter-guide.md`。

## 支持的转换

| 转换 | 命令示例 | 提取模式 |
|------|---------|---------|
| Mermaid -> PNG/SVG | `convert x.md -t png` | 从 MD 提取 mermaid 块: `--extract mermaid` |
| Markdown -> PDF | `convert x.md -t pdf` | 全量，含 Mermaid 渲染 |
| Markdown -> HTML | `convert x.md -t html` | 全量，含样式和 Mermaid |
| Markdown -> Word | `convert x.md -t docx` | 全量 |
| Word -> Markdown | `convert x.docx -t md` | 全量，图片提取到 `_assets/<文件名>/` |
| Markdown -> Excel | `convert x.md -t xlsx` | 提取表格: `--extract table` |
| HTML -> PDF | `convert x.html -t pdf` | 全量 |
| CSV/TSV -> Excel | `convert x.csv -t xlsx` | 全量 |
| Excel -> CSV | `convert x.xlsx -t csv` | 全量 |
| JSON/YAML -> Excel | `convert x.json -t xlsx` | 自动扁平化嵌套 |
| JSON/YAML -> CSV | `convert x.json -t csv` | 自动扁平化嵌套 |
| PDF -> Word | `convert x.pdf -t docx` | 全量，保留排版和表格 |
| 代码 -> 高亮HTML | `convert x.py -t html` | 全量，Pygments 语法高亮 |
| 代码 -> 高亮图片 | `convert x.py -t png` | 全量 |

## 常见场景

```bash
# MD 含 Mermaid 转 PDF
doc-converter convert doc.md -t pdf -o doc.pdf

# 从 MD 提取 Mermaid 转图片
doc-converter convert doc.md -t png --extract mermaid -o diagram.png

# JSON 转 Excel
doc-converter convert data.json -t xlsx -o data.xlsx

# Word 转 Markdown（图片提取）
doc-converter convert 手册.docx -t md -o 手册.md
# 自定义图片目录
doc-converter convert 手册.docx -t md -o 手册.md --options media_dir=assets/img
```

## 额外选项（--options k=v）

```bash
--options landscape=true        # PDF 横向
--options theme=dark            # Mermaid 主题
--options encoding=gbk          # CSV 编码
--options media_dir=assets/img  # Word->MD 图片目录
```

## 依赖自检

```bash
doc-converter doctor          # 核心依赖 + 可选 extras + 运行时大件
doc-converter install-deps    # 装 chromium（装 [render] 后）
```

核心转换无需重依赖。PDF/截图装 `[render]`，PDF→Word 装 `[pdf]`：
```bash
pip install 'doc-converter[render]'   # md/html→pdf(回退)、mermaid/代码→图片
pip install 'doc-converter[pdf]'      # PDF→Word
```
**md→pdf 默认走系统 pandoc+xelatex（免 chromium、支持中文）**，核心包即可用。
