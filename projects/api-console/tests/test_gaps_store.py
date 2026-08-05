"""_gaps.yaml 读写层测试。"""
from __future__ import annotations
from pathlib import Path
from api_console import gaps_store
from api_console.gaps_store import Gap, load_gaps, save_gaps, add_gap, next_id, update_status


def test_load_empty_when_absent(tmp_path):
    assert load_gaps(tmp_path, "demo") == []


def test_save_then_load_roundtrip(tmp_path):
    gaps = [Gap(id="gap-001", source="manual", title="t1", detail="d1",
                severity="high", status="open", discovered_at="2026-07-22",
                updated_at="2026-07-22")]
    save_gaps(tmp_path, "demo", gaps)
    loaded = load_gaps(tmp_path, "demo")
    assert len(loaded) == 1
    assert loaded[0].id == "gap-001"
    assert loaded[0].title == "t1"


def test_next_id_increments(tmp_path):
    gaps = [Gap(id="gap-003", source="manual", title="x")]
    assert next_id(gaps) == "gap-004"
    assert next_id([]) == "gap-001"


def test_add_gap_dedup_same_file_and_title(tmp_path):
    g1 = Gap(source="frontmatter", knowledge_file="m.md", module="m",
             title="kind 缺失", discovered_at="2026-07-22", updated_at="2026-07-22")
    id1 = add_gap(tmp_path, "demo", g1)
    g2 = Gap(source="frontmatter", knowledge_file="m.md", module="m",
             title="kind 缺失", detail="更多细节", discovered_at="2026-07-23",
             updated_at="2026-07-23")
    id2 = add_gap(tmp_path, "demo", g2)
    assert id1 == id2  # 同 file+title 去重，返回同一 id
    loaded = load_gaps(tmp_path, "demo")
    assert len(loaded) == 1
    assert loaded[0].updated_at == "2026-07-23"  # 只更新 updated_at


def test_update_status_sets_closed_at(tmp_path):
    save_gaps(tmp_path, "demo", [Gap(id="gap-001", source="manual",
              title="t", status="open", updated_at="2026-07-22")])
    g = update_status(tmp_path, "demo", "gap-001", "closed", "2026-07-24")
    assert g.status == "closed"
    assert g.closed_at == "2026-07-24"
    assert g.updated_at == "2026-07-24"
