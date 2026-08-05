"""frontmatter 聚合器测试：从 knowledge/_index.yaml 提取缺口。"""
from __future__ import annotations
from pathlib import Path
from api_console.aggregator import collect_from_index


INDEX_YAML = """\
concepts:
  - name: instance-id
    file: concepts/instance-id.md
    tags: [instanceId]
    completeness: partial
    gaps: [生成算法精确性, 是否严格12位]
    last_verified: ""
modules:
  standard_field:
    - name: standard-field-types
      file: modules/standard_field/standard-field-types.md
      tags: [kind]
      completeness: stub
      gaps: [kind完整枚举, sourceConfig结构]
      last_verified: ""
  fully_known:
    - name: full-one
      file: modules/fully_known/f.md
      completeness: full
      gaps: []
"""


def test_collect_partial_and_stub_skip_full(tmp_path):
    idx = tmp_path / "_index.yaml"
    idx.write_text(INDEX_YAML, encoding="utf-8")
    gaps = collect_from_index(idx)
    titles = sorted(g.title for g in gaps)
    assert titles == ["kind完整枚举", "sourceConfig结构",
                      "是否严格12位", "生成算法精确性"]
    # full 条目不产生缺口
    assert all("full-one" not in (g.knowledge_file or "") for g in gaps)


def test_collect_marks_source_and_module(tmp_path):
    idx = tmp_path / "_index.yaml"
    idx.write_text(INDEX_YAML, encoding="utf-8")
    gaps = collect_from_index(idx)
    by_title = {g.title: g for g in gaps}
    # concept 条目 module 留空
    assert by_title["生成算法精确性"].source == "frontmatter"
    assert by_title["生成算法精确性"].module == ""
    assert by_title["生成算法精确性"].knowledge_file == "concepts/instance-id.md"
    # module 条目带 module
    assert by_title["kind完整枚举"].module == "standard_field"
    assert by_title["kind完整枚举"].severity == "medium"


def test_collect_empty_when_all_full(tmp_path):
    idx = tmp_path / "_index.yaml"
    idx.write_text("concepts: []\nmodules: {}\n", encoding="utf-8")
    assert collect_from_index(idx) == []
