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
