---
name: doc-converter
description: This skill should be used when the user asks to "转换格式", "转PDF", "转图片", "导出Excel", "MD转PDF", "Word转Markdown", "docx转md", "提取Word图片", "Mermaid转图片", "CSV转Excel", "JSON转表格", "代码高亮", "提取表格", "提取大纲", "提取链接", "提取图片", "MD转JSON", "MD转纯文本", "格式转换", "PDF转Word", "convert to PDF", "export as image", "markdown to word", "docx to markdown", "word to md", "pdf to docx", or needs to convert documents between formats or extract content from files.
---

# 文档格式转换 (Doc Converter)

把文档在格式间互转、或从文档中提取部分内容（mermaid/表格/大纲/链接/图片/代码）。转换能力由 `doc-converter` CLI 提供（能力 project：`projects/doc-converter`）。本 skill 只做意图→CLI 参数的编排，不携带转换代码。

## 何时使用

用户要"转格式""转 PDF""转图片""导出 Excel""MD 转 Word""Word 转 Markdown""提取表格""Mermaid 转图片""CSV 转 Excel""JSON 转表格""代码高亮""PDF 转 Word"等。

## 怎么调

**开发态**（workspace 内，用 dev 壳转发到 project venv）:
```bash
bash skills/doc-converter/scripts/run.sh doc-converter convert <输入> -t <目标格式> [-o 输出] [--extract mermaid|table|outline|links|images|code] [--options k=v]
bash skills/doc-converter/scripts/run.sh doc-converter list           # 列出所有支持的转换
bash skills/doc-converter/scripts/run.sh doc-converter check <源> <目标>   # 检查是否支持 + 依赖
bash skills/doc-converter/scripts/run.sh doc-converter doctor         # 全量依赖自检
```

**分发态**（`scripts/setup.sh` 装好 CLI 后裸调）:
```bash
doc-converter convert <输入> -t <目标格式> [-o 输出] [--extract ...] [--options k=v]
```

## 工作流

1. **识别需求**：源文件路径/格式、目标格式、是否提取部分内容（`--extract mermaid|table|outline|links|images|code`）、额外选项（主题/编码/横向等，用 `--options k=v`）。
2. **检查依赖**：先 `doctor` 或 `check <源> <目标>`。chromium 缺失跑 `doc-converter install-deps`；pandoc 缺失（docx→md 用）提示系统安装（`brew install pandoc` / `apt install pandoc`）。
3. **执行转换**：构造 `convert` 命令；不指定 `-o` 则默认同名换后缀。
4. **产物后处理**：多 mermaid 块会输出多张图到目录；Word→Markdown 的图片默认在输出同目录 `_assets/<文件名>/`，md 内为相对引用（可用 `--options media_dir=...` 自定义）。

## 速查与细节

- 常用转换速查表见 `references/usage.md`。
- 完整支持矩阵、用法、依赖表、扩展指南在能力 project：`projects/doc-converter/README.md`、`projects/doc-converter/docs/converter-guide.md`。

## 依赖

skill 不携带依赖、不建 venv。能力 project **核心包轻量**（纯 python 库）；重依赖按需 extras：md→pdf 主路径装 `[typst]`（pandoc3+typst，原生中文/表格/代码高亮，免 TexLive）、PDF/截图/mermaid 嵌入装 `[render]`、PDF→Word 装 `[pdf]`。md→pdf 引擎链自动回退：pandoc3+typst → 系统 pandoc+xelatex → playwright。分发态由 `scripts/setup.sh` 装 CLI（vendor whl 优先），运行时大件 chromium 用 `doc-converter install-deps` 装（缓存在 `~/.cache/ms-playwright`，全局共享）。
