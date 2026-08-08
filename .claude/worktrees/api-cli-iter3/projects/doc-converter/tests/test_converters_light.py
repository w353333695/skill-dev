"""轻量转换测试（纯标准库 / openpyxl，不依赖 playwright/pandoc）。"""
import json
from pathlib import Path

from doc_converter.converters import get_converter


def test_json_to_csv(tmp_path: Path):
    """json->csv 仅用标准库，最轻量。"""
    inp = tmp_path / "data.json"
    inp.write_text(
        json.dumps([
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 25},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "data.csv"

    c = get_converter("json", "csv")
    assert c is not None
    res = c.convert(inp, out)
    assert res.success, res.message

    text = out.read_text(encoding="utf-8")
    assert "name" in text and "age" in text
    assert "alice" in text and "bob" in text


def test_csv_to_xlsx_roundtrip(tmp_path: Path):
    """csv->xlsx->csv 往返，覆盖 openpyxl 读写路径。"""
    inp = tmp_path / "data.csv"
    inp.write_text("name,age\nalice,30\nbob,25\n", encoding="utf-8")
    xlsx = tmp_path / "data.xlsx"

    c = get_converter("csv", "xlsx")
    assert c is not None
    res = c.convert(inp, xlsx)
    assert res.success and xlsx.exists()

    # 往返: xlsx -> csv
    out = tmp_path / "out.csv"
    c2 = get_converter("xlsx", "csv")
    assert c2 is not None
    res2 = c2.convert(xlsx, out)
    assert res2.success, res2.message

    text = out.read_text(encoding="utf-8")
    assert "alice" in text and "30" in text


# ---------- Markdown → 纯文本 ----------

def test_md_to_txt(tmp_path: Path):
    """md->txt 去标记，保留段落/表格/列表结构与图片 alt。"""
    inp = tmp_path / "t.md"
    inp.write_text(
        "# 标题一\n\n"
        "正文，含 [示例链接](https://example.com) 和 ![示意图](pic.png)。\n\n"
        "## 子标题\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "```python\nprint('hi')\n```\n",
        encoding="utf-8",
    )
    out = tmp_path / "t.txt"

    c = get_converter("md", "txt")
    assert c is not None
    res = c.convert(inp, out)
    assert res.success, res.message

    text = out.read_text(encoding="utf-8")
    assert "<" not in text and ">" not in text  # 无 HTML 标签残留
    assert "标题一" in text and "子标题" in text
    assert "示意图" in text          # 图片 alt 保留
    assert "print('hi')" in text     # 代码内容保留
    # 表格单元格在同一行（不被 HTML 源码换行拆散成多行）；空格数不固定
    assert any("A" in ln and "B" in ln for ln in text.splitlines())


# ---------- Markdown → JSON 结构化提取 ----------

def test_md_to_json_code(tmp_path: Path):
    """extract=code 提取代码块（跳过 mermaid）。"""
    inp = tmp_path / "t.md"
    inp.write_text(
        "```python\nprint(1)\n```\n\n"
        "```mermaid\ngraph LR;A-->B\n```\n",
        encoding="utf-8",
    )
    out = tmp_path / "c.json"

    c = get_converter("md", "json")
    assert c is not None
    res = c.convert(inp, out, extract="code")
    assert res.success, res.message

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["extract"] == "code"
    assert data["count"] == 1  # mermaid 被跳过
    assert data["items"][0]["lang"] == "python"
    assert "print(1)" in data["items"][0]["code"]


def test_md_to_json_outline(tmp_path: Path):
    """extract=outline 输出标题层级树。"""
    inp = tmp_path / "t.md"
    inp.write_text("# 一\n\n## 二\n\n# 三\n", encoding="utf-8")
    out = tmp_path / "o.json"

    c = get_converter("md", "json")
    res = c.convert(inp, out, extract="outline")
    assert res.success, res.message

    tree = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert len(tree) == 2  # 两个一级标题
    assert tree[0]["text"] == "一"
    assert tree[0]["children"][0]["text"] == "二"
    assert tree[1]["text"] == "三"


def test_md_to_json_links_and_images(tmp_path: Path):
    """extract=links / images 提取链接与图片。"""
    inp = tmp_path / "t.md"
    inp.write_text("[百度](https://baidu.com) ![logo](x.png)\n", encoding="utf-8")

    c = get_converter("md", "json")
    out_l = tmp_path / "l.json"
    res = c.convert(inp, out_l, extract="links")
    assert res.success, res.message
    links = json.loads(out_l.read_text(encoding="utf-8"))["items"]
    assert any(x["href"] == "https://baidu.com" for x in links)

    out_i = tmp_path / "i.json"
    res = c.convert(inp, out_i, extract="images")
    assert res.success, res.message
    imgs = json.loads(out_i.read_text(encoding="utf-8"))["items"]
    assert any(x["src"] == "x.png" and x["alt"] == "logo" for x in imgs)


def test_md_to_json_empty(tmp_path: Path):
    """无匹配内容时返回 success=False 且不写文件（对齐 md_table_excel 行为）。"""
    inp = tmp_path / "t.md"
    inp.write_text("纯文本，无代码块\n", encoding="utf-8")
    out = tmp_path / "c.json"

    c = get_converter("md", "json")
    res = c.convert(inp, out, extract="code")
    assert not res.success
    assert not out.exists()


# ---------- Markdown → HTML 代码高亮 ----------

def test_md_html_highlight_on(tmp_path: Path):
    """默认开启高亮：代码块带 codehilite class 且注入高亮 <style>。"""
    inp = tmp_path / "t.md"
    inp.write_text("```python\nprint(1)\n```\n", encoding="utf-8")
    out = tmp_path / "t.html"

    c = get_converter("md", "html")
    assert c is not None
    res = c.convert(inp, out)  # 默认 highlight=True
    assert res.success, res.message

    html = out.read_text(encoding="utf-8")
    assert 'class="codehilite"' in html
    assert ".codehilite" in html  # 注入了高亮 CSS 选择器


def test_md_html_highlight_off(tmp_path: Path):
    """highlight=False 时不高亮（回归）。"""
    inp = tmp_path / "t.md"
    inp.write_text("```python\nprint(1)\n```\n", encoding="utf-8")
    out = tmp_path / "t.html"

    c = get_converter("md", "html")
    res = c.convert(inp, out, highlight=False)
    assert res.success, res.message

    html = out.read_text(encoding="utf-8")
    assert "codehilite" not in html


def test_md_html_mermaid_not_highlighted(tmp_path: Path):
    """mermaid 块不被 codehilite 误染（回归）。"""
    inp = tmp_path / "t.md"
    inp.write_text(
        "```mermaid\ngraph LR;A-->B\n```\n\n```python\nx=1\n```\n",
        encoding="utf-8",
    )
    out = tmp_path / "t.html"

    c = get_converter("md", "html")
    res = c.convert(inp, out)
    assert res.success, res.message

    html = out.read_text(encoding="utf-8")
    assert 'class="mermaid"' in html     # mermaid 正确还原
    assert 'class="codehilite"' in html  # 普通代码块被高亮
