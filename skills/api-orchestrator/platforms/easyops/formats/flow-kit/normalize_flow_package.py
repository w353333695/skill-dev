#!/usr/bin/env python3
"""校验并规范化 EasyOps Flow V2 tar.gz，使必需文件位于归档根部。"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import tarfile
from pathlib import PurePosixPath

REQUIRED = {"_easyops_flow_info.json", "_easyops_tar_meta.json", "tool_batch_export.tar.gz"}


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _rooted_members(archive: tarfile.TarFile):
    members = [m for m in archive.getmembers() if m.isfile()]
    if not members:
        raise ValueError("归档没有文件")
    if any(not _safe_member(m.name) for m in members):
        raise ValueError("归档含不安全路径")
    prefixes = {m.name.split("/", 1)[0] for m in members}
    top_level = sorted(prefixes)
    if len(top_level) == 1 and all("/" in m.name for m in members):
        prefix = top_level[0] + "/"
        return [(m, m.name[len(prefix):]) for m in members], prefix[:-1]
    return [(m, m.name) for m in members], ""


def normalize(source: str, destination: str) -> None:
    with tarfile.open(source, "r:gz") as archive:
        pairs, prefix = _rooted_members(archive)
        names = {name for _, name in pairs}
        missing = REQUIRED - names
        if missing:
            raise ValueError("缺少必需文件: " + ", ".join(sorted(missing)))
        flow_info = archive.extractfile(next(m for m, name in pairs if name == "_easyops_flow_info.json"))
        meta = archive.extractfile(next(m for m, name in pairs if name == "_easyops_tar_meta.json"))
        json.load(io.TextIOWrapper(flow_info, encoding="utf-8"))
        json.load(io.TextIOWrapper(meta, encoding="utf-8"))
        with tarfile.open(destination, "w:gz") as output:
            for member, name in pairs:
                data = archive.extractfile(member).read()
                clone = tarfile.TarInfo(name)
                clone.size = len(data)
                clone.mode = member.mode & 0o777
                clone.mtime = member.mtime
                output.addfile(clone, io.BytesIO(data))
    print("已规范化: {} -> {}{}".format(source, destination, "（已去除顶层目录 {}）".format(prefix) if prefix else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="原始 .flow.tar.gz")
    parser.add_argument("destination", help="规范化后的 .flow.tar.gz")
    args = parser.parse_args()
    normalize(os.path.abspath(args.source), os.path.abspath(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
