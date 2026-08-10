"""knowledge_gaps CLI 的 report 路径与渲染测试。"""
from __future__ import annotations
from pathlib import Path
from api_console import knowledge_gaps
from api_console.knowledge_gaps import cmd_report, render_table, render_md
from api_console.gaps_store import Gap, save_gaps


def _setup_platform(tmp_path):
    """造一个最小 platform：knowledge/_index.yaml + registry 空目录。"""
    kdir = tmp_path / "platforms/demo/knowledge"
    kdir.mkdir(parents=True)
    (kdir / "_index.yaml").write_text(
        "concepts:\n"
        "  - {name: instance-id, file: concepts/instance-id.md, completeness: partial,\n"
        "     gaps: [生成算法精确性]}\n"
        "modules: {}\n", encoding="utf-8")
    return tmp_path


def test_cmd_report_aggregates_frontmatter_into_gaps(tmp_path):
    wd = _setup_platform(tmp_path)
    gaps = cmd_report(wd, "demo", status_filter=None, md_path=None)
    titles = [g.title for g in gaps]
    assert "生成算法精确性" in titles
    # 已落盘到 _gaps.yaml
    from api_console.gaps_store import load_gaps
    persisted = load_gaps(wd, "demo")
    assert any(g.title == "生成算法精确性" for g in persisted)


def test_cmd_report_idempotent_no_dup(tmp_path):
    wd = _setup_platform(tmp_path)
    cmd_report(wd, "demo", None, None)
    cmd_report(wd, "demo", None, None)  # 再跑一次
    from api_console.gaps_store import load_gaps
    persisted = load_gaps(wd, "demo")
    assert sum(1 for g in persisted if g.title == "生成算法精确性") == 1


def test_render_table_groups_by_module():
    gaps = [
        Gap(id="gap-001", source="manual", module="m1", title="t1",
            severity="high", status="open"),
        Gap(id="gap-002", source="manual", module="m1", title="t2",
            severity="low", status="open"),
        Gap(id="gap-003", source="manual", module="", title="t3",
            severity="medium", status="closed"),
    ]
    table = render_table(gaps)
    assert "gap-001" in table and "t1" in table and "high" in table
    assert "open" in table


def test_render_md_includes_suggest():
    gaps = [Gap(id="gap-001", source="manual", title="t1", severity="high",
                status="open", suggest=["补 kind 下拉框全集", "找后端字段定义"])]
    md = render_md(gaps)
    assert "gap-001" in md
    assert "补 kind 下拉框全集" in md


# ---------- PlanB-T5: register / filling / close ----------
from api_console.knowledge_gaps import cmd_register, cmd_filling, cmd_close
from api_console.gaps_store import load_gaps, find_by_id


def test_cmd_register_manual_returns_id(tmp_path):
    kdir = tmp_path / "platforms/demo/knowledge"
    kdir.mkdir(parents=True)
    (kdir / "_index.yaml").write_text("concepts: []\nmodules: {}\n", encoding="utf-8")
    gid = cmd_register(tmp_path, "demo", title="kind 枚举缺失",
                       severity="high", module="standard_field", source="manual",
                       triggered_by="", detail="仅知 USER_SELECTOR",
                       suggest=["补新建字段表单下拉框"])
    assert gid.startswith("gap-")
    g = find_by_id(tmp_path, "demo", gid)
    assert g.title == "kind 枚举缺失" and g.severity == "high"
    assert g.suggest == ["补新建字段表单下拉框"]


def test_cmd_filling_updates_status(tmp_path):
    kdir = tmp_path / "platforms/demo/knowledge"
    kdir.mkdir(parents=True)
    (kdir / "_index.yaml").write_text("concepts: []\nmodules: {}\n", encoding="utf-8")
    gid = cmd_register(tmp_path, "demo", title="t", severity="low",
                       module="", source="manual", triggered_by="", detail="", suggest=[])
    assert cmd_filling(tmp_path, "demo", gid) is True
    assert find_by_id(tmp_path, "demo", gid).status == "filling"


def test_cmd_close_removes_frontmatter_gap_and_upgrades(tmp_path):
    kdir = tmp_path / "platforms/demo/knowledge"
    kdir.mkdir(parents=True)
    # 知识文件含两条 gap，关掉其中一条
    (kdir / "modules/standard_field").mkdir(parents=True)
    kfile = kdir / "modules/standard_field/standard-field-types.md"
    kfile.write_text(
        "---\nname: standard-field-types\nmodule: standard_field\n"
        "completeness: stub\n"
        "gaps:\n  - kind完整枚举\n  - sourceConfig结构\nlast_verified: \"\"\n---\n"
        "# 正文\n", encoding="utf-8")
    (kdir / "_index.yaml").write_text(
        "concepts: []\n"
        "modules:\n  standard_field:\n"
        "    - {name: standard-field-types, file: modules/standard_field/standard-field-types.md,\n"
        "       completeness: stub, gaps: [kind完整枚举, sourceConfig结构], last_verified: \"\"}\n",
        encoding="utf-8")
    gid = cmd_register(tmp_path, "demo", title="kind完整枚举", severity="medium",
                       module="standard_field", source="frontmatter",
                       knowledge_file="modules/standard_field/standard-field-types.md",
                       triggered_by="", detail="", suggest=[])
    today = _today_fixed()
    assert cmd_close(tmp_path, "demo", gid, today=today) is True

    # _gaps.yaml 该条已 closed
    assert find_by_id(tmp_path, "demo", gid).status == "closed"
    # frontmatter：kind完整枚举 已删，仍剩 sourceConfig结构 → completeness 保持 stub
    from api_console.frontmatter import load_file
    fm, _ = load_file(kfile)
    assert "kind完整枚举" not in fm["gaps"]
    assert fm["gaps"] == ["sourceConfig结构"]
    assert fm["completeness"] == "stub"
    assert fm["last_verified"] == today
    # _index.yaml 同步
    import yaml
    idx = yaml.safe_load((kdir / "_index.yaml").read_text(encoding="utf-8"))
    entry = idx["modules"]["standard_field"][0]
    assert "kind完整枚举" not in entry["gaps"]
    assert entry["last_verified"] == today


def test_cmd_close_last_gap_upgrades_to_full(tmp_path):
    kdir = tmp_path / "platforms/demo/knowledge"
    kdir.mkdir(parents=True)
    (kdir / "concepts").mkdir()
    kfile = kdir / "concepts/instance-id.md"
    kfile.write_text(
        "---\nname: instance-id\ncompleteness: partial\n"
        "gaps:\n  - 生成算法精确性\nlast_verified: \"\"\n---\n# 正文\n",
        encoding="utf-8")
    (kdir / "_index.yaml").write_text(
        "concepts:\n  - {name: instance-id, file: concepts/instance-id.md,\n"
        "     completeness: partial, gaps: [生成算法精确性], last_verified: \"\"}\n"
        "modules: {}\n", encoding="utf-8")
    gid = cmd_register(tmp_path, "demo", title="生成算法精确性", severity="medium",
                       module="", source="frontmatter",
                       knowledge_file="concepts/instance-id.md",
                       triggered_by="", detail="", suggest=[])
    assert cmd_close(tmp_path, "demo", gid, today="2026-07-22") is True
    from api_console.frontmatter import load_file
    fm, _ = load_file(kfile)
    assert fm["gaps"] == []
    assert fm["completeness"] == "full"  # 最后一条关掉 → 升级 full


def _today_fixed():
    import datetime
    return datetime.date.today().isoformat()


# ---------- PlanB-T6: discover ----------
from api_console.knowledge_gaps import cmd_discover


def _setup_discover(tmp_path):
    base = tmp_path / "platforms/demo"
    kdir = base / "knowledge"; kdir.mkdir(parents=True)
    (kdir / "_index.yaml").write_text(
        "concepts: []\n"
        "modules:\n"
        "  standard_field:\n"
        "    - {name: standard-field-types, file: f.md, completeness: stub, gaps: [x]}\n",
        encoding="utf-8")
    rdir = base / "registry"; rdir.mkdir(parents=True)
    # registry 有 standard_field（已在 knowledge，但 stub）+ domain_model（knowledge 完全没有）
    (rdir / "_index.yaml").write_text(
        "modules:\n- name: standard_field\n  cards: []\n"
        "- name: domain_model\n  cards: []\n", encoding="utf-8")
    return tmp_path


def test_cmd_discover_finds_missing_and_stub(tmp_path):
    wd = _setup_discover(tmp_path)
    gaps = cmd_discover(wd, "demo")
    titles = [g.title for g in gaps]
    # domain_model 在 registry 但 knowledge 无 → 缺失
    assert any("domain_model" in t and "缺失" in t for t in titles)
    # standard_field 在 knowledge 但 stub → 仅框架
    assert any("standard_field" in t and "stub" in t.lower() for t in titles)
    assert all(g.source == "diff" for g in gaps)
