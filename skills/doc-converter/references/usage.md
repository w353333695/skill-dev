# 常用转换速查

供 skill 编排时快速参考。完整支持矩阵、用法、依赖、扩展指南见能力 project：
`projects/doc-converter/README.md`、`projects/doc-converter/docs/converter-guide.md`。

## 支持的转换

| 转换 | 命令示例 | 提取模式 |
|------|---------|---------|
| Mermaid -> PNG/SVG | `convert x.md -t png` | 从 MD 提取 mermaid 块: `--extract mermaid` |
| Markdown -> PDF | `convert x.md -t pdf` | 全量；Mermaid 需 [render] 嵌入 |
| Markdown -> HTML | `convert x.md -t html` | 全量，含样式/Mermaid/代码高亮 |
| Markdown -> Word | `convert x.md -t docx` | 全量 |
| Word -> Markdown | `convert x.docx -t md` | 全量，图片提取到 `_assets/<文件名>/` |
| Markdown -> Excel | `convert x.md -t xlsx` | 提取表格: `--extract table` |
| Markdown -> 纯文本 | `convert x.md -t txt` | 全量，去标记保留段落结构 |
| Markdown -> JSON | `convert x.md -t json` | `--extract outline/links/images/code` |
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

# 从 MD 提取结构化数据 / 纯文本
doc-converter convert doc.md -t json --extract outline -o outline.json
doc-converter convert doc.md -t txt -o doc.txt

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

核心转换无需重依赖。按需装 extras：
```bash
pip install 'doc-converter[typst]'    # md→pdf 主路径（pandoc3+typst，原生中文/表格/代码高亮）
pip install 'doc-converter[render]'   # PDF/截图渲染、mermaid 嵌入、代码→图片
pip install 'doc-converter[pdf]'      # PDF→Word
```
md→pdf 引擎链自动回退：pandoc3+typst → 系统 pandoc+xelatex → playwright。
mermaid 图嵌入需 `[render]`；未装时 mermaid 优雅回退为代码块，不阻断转换。
