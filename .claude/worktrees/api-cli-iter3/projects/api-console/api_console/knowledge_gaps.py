"""知识缺口治理 CLI（子命令式，沿用 register_cards.py 范式）。

子命令：
  report    聚合 frontmatter 缺口进 _gaps.yaml，输出表格（--md 另出报告）
  register  人工/runtime 登记一条缺口
  filling   标记某缺口为「补全中」
  close     关闭缺口并回写知识文件 frontmatter
  discover  对照 registry/_index.yaml 发现未覆盖模块（粗粒度）

设计见 references/knowledge.md「缺口治理」章节。
"""
from __future__ import annotations
import argparse
import datetime
from pathlib import Path

import yaml
from api_console.gaps_store import (Gap, load_gaps, save_gaps, add_gap, update_status,
                        find_by_id, _workdir)
from api_console.aggregator import collect_from_index
from api_console.frontmatter import load_file, write_file


def _today() -> str:
    return datetime.date.today().isoformat()


def _knowledge_dir(workdir, platform) -> Path:
    return Path(workdir) / "platforms" / platform / "knowledge"


def cmd_report(workdir, platform, status_filter=None, md_path=None) -> list[Gap]:
    """聚合 frontmatter 缺口进 _gaps.yaml（去重），返回当前缺口列表。

    每次运行：collect_from_index → 逐条 add_gap（去重）→ 读回全量 → 可选过滤/出报告。
    """
    kdir = _knowledge_dir(workdir, platform)
    for g in collect_from_index(kdir / "_index.yaml"):
        add_gap(workdir, platform, g)
    gaps = load_gaps(workdir, platform)
    if status_filter:
        gaps = [g for g in gaps if g.status == status_filter]
    if md_path:
        Path(md_path).write_text(render_md(gaps), encoding="utf-8")
    return gaps


def render_table(gaps: list[Gap]) -> str:
    """CLI 表格：按 module 分组，列 id/module/severity/status/title。"""
    lines = [f"{'id':<8} {'module':<16} {'sev':<6} {'status':<8} title"]
    lines.append("-" * 70)
    # 按 module 分组（空 module 归到末尾）
    for g in sorted(gaps, key=lambda x: (x.module == "", x.module, x.id)):
        lines.append(f"{g.id:<8} {(g.module or '-'):<16} {g.severity:<6} "
                     f"{g.status:<8} {g.title}")
    return "\n".join(lines)


def render_md(gaps: list[Gap]) -> str:
    """md 报告：管理者阅读物，按 severity 分节，含治理建议。"""
    open_gaps = [g for g in gaps if g.status != "closed"]
    lines = ["# 知识缺口治理报告", "",
             f"待处理缺口：{len(open_gaps)} 条（共 {len(gaps)} 条）", ""]
    for sev in ("high", "medium", "low"):
        group = [g for g in open_gaps if g.severity == sev]
        if not group:
            continue
        title = {"high": "高优先级", "medium": "中优先级", "low": "低优先级"}[sev]
        lines.append(f"## {title}（{len(group)}）")
        lines.append("")
        for g in sorted(group, key=lambda x: (x.module, x.id)):
            lines.append(f"### {g.id} {g.title}")
            lines.append(f"- module: `{g.module or '-'}` | 来源: `{g.source}` | "
                         f"状态: `{g.status}` | 发现: {g.discovered_at}")
            if g.detail:
                lines.append(f"- 详情: {g.detail}")
            if g.suggest:
                lines.append("- 治理建议:")
                for s in g.suggest:
                    lines.append(f"  - {s}")
            lines.append("")
    return "\n".join(lines)


def cmd_register(workdir, platform, title, severity="medium", module="",
                 source="manual", triggered_by="", detail="",
                 suggest=None, knowledge_file="") -> str:
    """登记一条缺口（manual/runtime/diff 通用入口），返回稳定 id。"""
    g = Gap(source=source, knowledge_file=knowledge_file, module=module,
            title=title, detail=detail, severity=severity,
            suggest=list(suggest or []), triggered_by=triggered_by)
    return add_gap(workdir, platform, g)


def cmd_filling(workdir, platform, gap_id) -> bool:
    g = update_status(workdir, platform, gap_id, "filling", _today())
    return g is not None


def cmd_close(workdir, platform, gap_id, today: str | None = None) -> bool:
    """关闭缺口：回写知识文件 frontmatter + _index.yaml，再置 status=closed。

    回写规则：从该 gap 的 knowledge_file 的 gaps 删掉 title 匹配项；
    gaps 删空则 completeness→full，否则保持原级；last_verified=today。
    _index.yaml 同名 file 条目同步。找不到知识文件则只置 closed（不阻断）。
    """
    today = today or _today()
    g = find_by_id(workdir, platform, gap_id)
    if g is None:
        return False
    kdir = _knowledge_dir(workdir, platform)
    # 1. 回写知识文件 frontmatter
    if g.knowledge_file:
        kfile = kdir / g.knowledge_file
        if kfile.exists():
            fm, body = load_file(kfile)
            gaps_list = fm.get("gaps", []) or []
            gaps_list = [x for x in gaps_list if str(x) != g.title]
            fm["gaps"] = gaps_list
            if not gaps_list:
                fm["completeness"] = "full"
            fm["last_verified"] = today
            write_file(kfile, fm, body)
    # 2. 同步 _index.yaml 同名 file 条目
    idx_path = kdir / "_index.yaml"
    if idx_path.exists() and g.knowledge_file:
        idx = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
        _sync_index_entry(idx, g.knowledge_file, g.title, today)
        idx_path.write_text(yaml.dump(idx, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
    # 3. 置 closed
    update_status(workdir, platform, gap_id, "closed", today)
    return True


def _sync_index_entry(idx: dict, knowledge_file: str, title: str, today: str) -> None:
    """在 _index.yaml 的 concepts/modules 条目里找 file 匹配项，删 gap + 升级 + last_verified。"""
    def _patch(entry):
        if entry.get("file") != knowledge_file:
            return False
        gaps_list = entry.get("gaps", []) or []
        gaps_list = [x for x in gaps_list if str(x) != title]
        entry["gaps"] = gaps_list
        if not gaps_list:
            entry["completeness"] = "full"
        entry["last_verified"] = today
        return True
    for c in idx.get("concepts", []) or []:
        _patch(c)
    for entries in (idx.get("modules", {}) or {}).values():
        for m in entries or []:
            _patch(m)


def cmd_discover(workdir, platform) -> list[Gap]:
    """对照 registry/_index.yaml 发现知识未覆盖的模块（粗粒度）。

    - registry 有卡片但 knowledge 无该 module → 「模块 X 知识缺失」
    - knowledge 有但 completeness=stub → 「模块 X 知识仅框架(stub)，待补全」
    登记进 _gaps.yaml（source=diff，去重）后返回。
    """
    base = Path(workdir) / "platforms" / platform
    kdir = base / "knowledge"
    ridx_path = base / "registry" / "_index.yaml"

    # knowledge 侧 module → completeness
    k_modules: dict[str, str] = {}
    kidx_path = kdir / "_index.yaml"
    if kidx_path.exists():
        kidx = yaml.safe_load(kidx_path.read_text(encoding="utf-8")) or {}
        for module_name, entries in (kidx.get("modules", {}) or {}).items():
            comp = "stub"
            for m in entries or []:
                comp = m.get("completeness", "stub")
            k_modules[module_name] = comp

    # registry 侧 module 集合（两种 _index 格式：list of {name} 或 dict）
    r_modules: set[str] = set()
    if ridx_path.exists():
        ridx = yaml.safe_load(ridx_path.read_text(encoding="utf-8")) or {}
        mods = ridx.get("modules", [])
        if isinstance(mods, list):
            for m in mods or []:
                if isinstance(m, dict) and m.get("name"):
                    r_modules.add(m["name"])
        elif isinstance(mods, dict):
            r_modules.update(mods.keys())

    new_gaps: list[Gap] = []
    for m in sorted(r_modules):
        if m not in k_modules:
            new_gaps.append(Gap(source="diff", module=m, severity="high",
                                title=f"模块 {m} 知识缺失",
                                detail=f"registry 有 {m} 卡片但 knowledge/ 无对应知识",
                                suggest=[]))
    for m, comp in k_modules.items():
        if comp == "stub":
            new_gaps.append(Gap(source="diff", module=m, severity="medium",
                                title=f"模块 {m} 知识仅框架(stub)，待补全",
                                detail=f"knowledge 已登记 {m} 但 completeness=stub",
                                suggest=[]))
    for g in new_gaps:
        add_gap(workdir, platform, g)
    return new_gaps


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="api-console knowledge-gaps", description="知识缺口治理")
    p.add_argument("--platform", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("report", help="聚合 frontmatter 缺口并输出表格")
    pr.add_argument("--status", default="", help="过滤状态 open/filling/closed")
    pr.add_argument("--md", default="", help="另出 md 报告路径")

    # register/filling/close/discover 在后续 Task 实现，此处先占位 raise
    preg = sub.add_parser("register", help="登记一条缺口")
    preg.add_argument("--title", required=True)
    preg.add_argument("--severity", default="medium", choices=["high", "medium", "low"])
    preg.add_argument("--module", default="")
    preg.add_argument("--source", default="manual",
                      choices=["manual", "runtime", "diff"])
    preg.add_argument("--triggered-by", dest="triggered_by", default="")
    preg.add_argument("--detail", default="")
    preg.add_argument("--suggest", action="append", default=[],
                      help="治理建议，可重复")
    preg.add_argument("--knowledge-file", dest="knowledge_file", default="")

    pfil = sub.add_parser("filling", help="标记缺口为补全中")
    pfil.add_argument("gap_id")

    pclose = sub.add_parser("close", help="关闭缺口并回写 frontmatter")
    pclose.add_argument("gap_id")

    sub.add_parser("discover", help="对照接口发现未覆盖模块（粗粒度）")

    args = p.parse_args(argv)
    workdir = _workdir()

    if args.cmd == "report":
        gaps = cmd_report(workdir, args.platform,
                          status_filter=args.status or None,
                          md_path=args.md or None)
        print(f"[knowledge_gaps] 平台 {args.platform}：{len(gaps)} 条缺口")
        if gaps:
            print(render_table(gaps))
        if args.md:
            print(f"[knowledge_gaps] md 报告: {args.md}")
        return 0

    # 其余子命令后续 Task 实现
    elif args.cmd == "register":
        gid = cmd_register(workdir, args.platform, title=args.title,
                           severity=args.severity, module=args.module,
                           source=args.source, triggered_by=args.triggered_by,
                           detail=args.detail, suggest=args.suggest,
                           knowledge_file=args.knowledge_file)
        print(f"[knowledge_gaps] 已登记 {gid}: {args.title}")
        return 0
    elif args.cmd == "filling":
        ok = cmd_filling(workdir, args.platform, args.gap_id)
        print(f"[knowledge_gaps] {'已标记补全中' if ok else '未找到'} {args.gap_id}")
        return 0 if ok else 1
    elif args.cmd == "close":
        ok = cmd_close(workdir, args.platform, args.gap_id)
        print(f"[knowledge_gaps] {'已关闭并回写 frontmatter' if ok else '未找到'} {args.gap_id}")
        return 0 if ok else 1
    elif args.cmd == "discover":
        gaps = cmd_discover(workdir, args.platform)
        print(f"[knowledge_gaps] 发现 {len(gaps)} 处知识覆盖缺口（已登记）")
        for g in gaps:
            print(f"  {g.severity:<6} {g.title}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
