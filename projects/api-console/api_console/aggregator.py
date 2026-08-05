"""frontmatter 聚合器：从 knowledge/_index.yaml 提取已登记缺口。

知识文件 frontmatter 的 gaps 是「知识视角」（这条知识缺什么），分散在各文件。
本聚合器读 _index.yaml（frontmatter 的镜像索引），把它们归一为 Gap 列表，
供 knowledge_gaps.report 汇总进 _gaps.yaml（管理者视角）。

纯函数，仅读一个文件，不含 IO 副作用，便于单测。
"""
from __future__ import annotations
from pathlib import Path
import yaml
from api_console.gaps_store import Gap


def collect_from_index(index_path: Path) -> list[Gap]:
    """读 knowledge/_index.yaml，partial/stub 条目的每个 gap → 一个 Gap。

    full 条目跳过。concepts 条目 module 留空，modules 条目取其父 key 作 module。
    """
    if not index_path.exists():
        return []
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    out: list[Gap] = []
    # concepts：全局概念，module 留空
    for c in data.get("concepts", []) or []:
        if c.get("completeness") in ("partial", "stub"):
            for gtitle in c.get("gaps", []) or []:
                out.append(Gap(
                    source="frontmatter",
                    knowledge_file=c.get("file", ""),
                    module="",
                    title=str(gtitle),
                    severity="medium",
                ))
    # modules：父 key 是 module 名
    for module_name, entries in (data.get("modules", {}) or {}).items():
        for m in entries or []:
            if m.get("completeness") in ("partial", "stub"):
                for gtitle in m.get("gaps", []) or []:
                    out.append(Gap(
                        source="frontmatter",
                        knowledge_file=m.get("file", ""),
                        module=str(module_name),
                        title=str(gtitle),
                        severity="medium",
                    ))
    return out
