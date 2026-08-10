"""知识缺口登记表 _gaps.yaml 的读写纯函数 + Gap dataclass。

_gaps.yaml 是平台包级唯一缺口池（管理者视角），与知识文件 frontmatter 的
gaps（知识视角）分离；两者通过 close 动作联动（见 knowledge_gaps.close）。
所有函数纯磁盘 IO，不含 CLI/LLM 逻辑，便于单测。
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Gap:
    """单条知识缺口。字段对应 _gaps.yaml 一条。"""
    id: str = ""
    source: str = ""          # frontmatter | runtime | manual | diff
    knowledge_file: str = ""  # 来源知识文件相对 knowledge/ 的路径；runtime/manual 可空
    module: str = ""
    title: str = ""
    detail: str = ""
    severity: str = "medium"  # high | medium | low（人/LLM 预填）
    suggest: list[str] = field(default_factory=list)  # 治理建议，人/LLM 预填
    status: str = "open"      # open | filling | closed
    discovered_at: str = ""
    updated_at: str = ""
    closed_at: str = ""
    triggered_by: str = ""    # source=runtime 时记触发场景（step_id/问答关键词）


def _gaps_path(workdir: Path, platform: str) -> Path:
    return Path(workdir) / "platforms" / platform / "knowledge" / "_gaps.yaml"


def _workdir() -> Path:
    """产物根：优先 run.sh 注入的 workdir，回退本进程 cwd。"""
    w = os.environ.get("API_CONSOLE_WORKDIR")
    return Path(w) if w else Path.cwd()


def load_gaps(workdir, platform) -> list[Gap]:
    """读 _gaps.yaml；文件不存在返回空列表。"""
    p = _gaps_path(Path(workdir), platform)
    if not p.exists():
        return []
    import yaml
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [Gap(**d) for d in data.get("gaps", [])]


def save_gaps(workdir, platform, gaps: list[Gap]) -> Path:
    """覆盖式写 _gaps.yaml。返回文件路径。"""
    import yaml
    p = _gaps_path(Path(workdir), platform)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"gaps": [asdict(g) for g in gaps]}
    p.write_text(yaml.dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def next_id(gaps: list[Gap]) -> str:
    """取现有最大编号 +1，格式 gap-NNN。空列表返回 gap-001。"""
    max_n = 0
    for g in gaps:
        m = re.match(r"gap-(\d+)", g.id or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"gap-{max_n + 1:03d}"


def _dedup_key(g: Gap) -> tuple:
    """去重键：knowledge_file + title。frontmatter/diff 同来源同标题视为同一缺口。"""
    return (g.knowledge_file or "", g.title or "")


def add_gap(workdir, platform, gap: Gap) -> str:
    """追加缺口；同 knowledge_file+title 已存在则只更新 updated_at，返回稳定 id。

    保证 frontmatter 聚合重复跑不产生重复条目，id 在生命周期内稳定。
    """
    import datetime
    today = datetime.date.today().isoformat()
    gaps = load_gaps(workdir, platform)
    key = _dedup_key(gap)
    for existing in gaps:
        if _dedup_key(existing) == key and key != ("", ""):
            # 优先用传入 gap 自带的 updated_at（聚合器显式传 frontmatter 的核对
            # 日期）；未提供时回退系统日期。
            existing.updated_at = gap.updated_at or today
            if gap.detail and not existing.detail:
                existing.detail = gap.detail
            save_gaps(workdir, platform, gaps)
            return existing.id
    gap.id = next_id(gaps)
    if not gap.discovered_at:
        gap.discovered_at = today
    if not gap.updated_at:
        gap.updated_at = today
    gaps.append(gap)
    save_gaps(workdir, platform, gaps)
    return gap.id


def update_status(workdir, platform, gap_id: str, status: str, today: str) -> Gap | None:
    """更新某缺口状态；closed 时同步填 closed_at。找不到返回 None。"""
    gaps = load_gaps(workdir, platform)
    for g in gaps:
        if g.id == gap_id:
            g.status = status
            g.updated_at = today
            if status == "closed":
                g.closed_at = today
            save_gaps(workdir, platform, gaps)
            return g
    return None


def find_by_id(workdir, platform, gap_id: str) -> Gap | None:
    for g in load_gaps(workdir, platform):
        if g.id == gap_id:
            return g
    return None
