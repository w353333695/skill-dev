"""后端资料解析主干（adapter 发现/调度/置信度分流/诚实反馈）。

通用层：不耦合任何平台，只认 ``adapter_base.BackendAdapter`` 接口。
spec 第 4 章约定：
    - HIGH：adapter 全权 parse，直接产出 contracts.yaml；
    - LOW：MVP-1 暂未实现 LLM 回退，报 ParseError 引导人工/LLM 介入；
    - ZERO：诚实反馈，报 ParseError 提示用户提供结构化资料。

用法:
    run.sh parse_backend.py --platform <platform> \\
        --in platforms/<platform>/sources/raw/backend \\
        --out platforms/<platform>/sources/backend/parsed/contracts.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from api_console.adapter_base import Confidence, discover_adapters
from api_console.schema.contracts import BackendContract, save_contracts


class ParseError(Exception):
    """解析失败（携带诚实反馈：不支持的格式 / 缺 adapter / 半结构化）。"""


def run(raw_dir: Path, adapters_dir: Path, out: Path) -> None:
    """主干流程：discover → detect（取最高置信度）→ 分流 → save。

    Args:
        raw_dir: 后端资料目录（契约/路由/文档），交给 adapter 评估。
        adapters_dir: adapter 目录，约定 ``<workdir>/platforms/<platform>/sources/
            backend/adapters/``，discover_adapters 扫描其下 ``*.py``。
        out: contracts.yaml 输出路径。

    Raises:
        ParseError: 未发现任何 adapter / 全部 adapter ZERO / 最高置信度为 LOW。
    """
    adapters = discover_adapters(adapters_dir)
    if not adapters:
        raise ParseError(
            f"未发现任何 adapter（目录 {adapters_dir}），不支持该平台资料。"
            f"请在 platforms/<platform>/sources/backend/adapters/ 下提供 adapter。"
        )

    # 选 detect 置信度最高的 adapter（Confidence 是 IntEnum，HIGH=2 > LOW=1 > ZERO=0）
    best = None
    best_result = None
    for a in adapters:
        r = a.detect(raw_dir)
        if best_result is None or r.confidence > best_result.confidence:
            best, best_result = a, r

    if best_result.confidence == Confidence.ZERO:
        raise ParseError(
            f"不支持的资料格式：{best_result.reason}。"
            f"已尝试 adapter：{[a.name for a in adapters]}。"
            f"需提供该平台支持的契约格式（如 JSON / swagger / 结构化 markdown 之一）。"
        )

    if best_result.confidence == Confidence.LOW:
        # MVP-1 不实现 LLM 回退（留作后续 milestone）
        raise ParseError(
            f"资料为半结构化（{best_result.reason}），"
            f"MVP-1 暂不支持自动解析，需人工介入或后续 LLM 回退。"
        )

    # HIGH：adapter 全权 parse，套 BackendContract dataclass 后写盘
    assert best is not None  #此时 best 必非 None（HIGH 分支必然命中过 best 赋值）
    items = best.parse(raw_dir)
    contracts = [BackendContract(**it) for it in items]
    save_contracts(contracts, out)
    print(
        f"[parse_backend] {best.name} 解析 {len(contracts)} 条契约 → {out} "
        f"(matched_files={best_result.matched_files})"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析 --platform/--in/--out，约定 adapter 目录路径。

    workdir 解析优先用 ``API_CONSOLE_WORKDIR``（run.sh 已 export），
    回退 cwd，避免硬编码项目根。
    """
    p = argparse.ArgumentParser(prog="api-console parse-backend", description="后端资料解析主干")
    p.add_argument("--platform", required=True, help="平台名（对应 platforms/ 下的目录名）")
    p.add_argument("--in", dest="raw_dir", required=True,
                   help="后端资料目录（raw/）")
    p.add_argument("--out", dest="out", required=True,
                   help="contracts.yaml 输出路径")
    args = p.parse_args(argv)

    # adapter 目录约定：<workdir>/platforms/<platform>/sources/backend/adapters/
    workdir = Path(os.environ.get("API_CONSOLE_WORKDIR", os.getcwd()))
    adapters_dir = (
        workdir / "platforms" / args.platform / "sources" / "backend" / "adapters"
    )
    try:
        run(Path(args.raw_dir), adapters_dir, Path(args.out))
    except ParseError as e:
        print(f"[parse_backend] 失败：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
