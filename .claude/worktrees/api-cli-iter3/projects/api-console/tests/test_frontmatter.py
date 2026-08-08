"""md frontmatter 解析/重写工具测试。"""
from __future__ import annotations
from api_console.frontmatter import parse, dump, load_file, write_file

DOC = """\
---
name: instance-id
completeness: partial
gaps:
  - 生成算法精确性
  - 是否严格12位
last_verified: ""
---
# instanceId 概念

正文内容，含 ```yaml``` 代码块也应保留。
"""

def test_parse_returns_fm_and_body():
    fm, body = parse(DOC)
    assert fm["name"] == "instance-id"
    assert fm["completeness"] == "partial"
    assert fm["gaps"] == ["生成算法精确性", "是否严格12位"]
    assert body.startswith("# instanceId 概念")

def test_dump_roundtrip_preserves_body():
    fm, body = parse(DOC)
    out = dump(fm, body)
    fm2, body2 = parse(out)
    assert fm2 == fm
    assert body2 == body

def test_dump_empty_gaps_and_update_completeness():
    fm, body = parse(DOC)
    fm["gaps"] = []
    fm["completeness"] = "full"
    fm["last_verified"] = "2026-07-22"
    out = dump(fm, body)
    fm2, _ = parse(out)
    assert fm2["gaps"] == []
    assert fm2["completeness"] == "full"
    assert fm2["last_verified"] == "2026-07-22"

def test_load_and_write_file(tmp_path):
    f = tmp_path / "k.md"
    f.write_text(DOC, encoding="utf-8")
    fm, body = load_file(f)
    fm["completeness"] = "full"
    write_file(f, fm, body)
    fm2, body2 = load_file(f)
    assert fm2["completeness"] == "full"
    assert body2.startswith("# instanceId")
