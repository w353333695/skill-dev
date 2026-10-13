#!/usr/bin/env python3
"""guide 引用图片压缩：就地转 webp（默认宽 1280 / 质量 80），并改写 md 引用。

用法：
    python3 prepare_guide_images.py <guide_dir> [--width 1280] [--quality 80] [--keep-png]

行为：
    1. 扫描 <guide_dir>/guide.md 中所有 `![](screenshots/xxx)` 引用（png/jpg/jpeg）；
    2. 每张图等比缩放到不超过 --width（只缩不放），转 webp（quality），写入 screenshots/ 同名 .webp；
    3. 改写 md 中对应引用为 .webp；
    4. 默认删除转换成功的原图（--keep-png 保留）。
    已是 .webp 的引用跳过；文件缺失则告警但继续（退出码仍为 0，仅输出告警）。
输出：逐图「原体积 → 新体积」对照与汇总（张数 / 总大小 / 压缩比）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from PIL import Image

CONVERT_EXTS = {".png", ".jpg", ".jpeg"}
REF_RE = re.compile(r"!\[[^\]]*\]\((screenshots/[^)]+)\)")


def _fmt_kb(n: int) -> str:
    return f"{n / 1024:.0f}KB"


def main() -> int:
    ap = argparse.ArgumentParser(description="guide 引用图片压缩为 webp 并改写 md 引用")
    ap.add_argument("guide_dir", help="含 guide.md 与 screenshots/ 的指引目录")
    ap.add_argument("--width", type=int, default=1280, help="目标最大宽度（只缩不放，默认 1280）")
    ap.add_argument("--quality", type=int, default=80, help="webp 质量（默认 80）")
    ap.add_argument("--keep-png", action="store_true", help="保留原图（默认转换成功后删除）")
    args = ap.parse_args()

    guide = pathlib.Path(args.guide_dir)
    md_path = guide / "guide.md"
    if not md_path.exists():
        print(f"[错误] 未找到 {md_path}", file=sys.stderr)
        return 1

    md = md_path.read_text(encoding="utf-8")
    refs = REF_RE.findall(md)
    targets = sorted({r for r in refs if pathlib.Path(r).suffix.lower() in CONVERT_EXTS})

    converted, missing = 0, 0
    old_total = new_total = 0
    replaced = md
    for ref in targets:
        src = guide / ref
        if not src.exists():
            print(f"[告警] 缺失引用图: {ref}")
            missing += 1
            continue
        dst = src.with_suffix(".webp")
        im = Image.open(src).convert("RGB")
        if im.width > args.width:  # 只缩不放
            im = im.resize((args.width, round(im.height * args.width / im.width)), Image.LANCZOS)
        im.save(dst, "WEBP", quality=args.quality, method=6)
        old_sz, new_sz = src.stat().st_size, dst.stat().st_size
        old_total += old_sz
        new_total += new_sz
        converted += 1
        ratio = new_sz / old_sz * 100 if old_sz else 0
        print(f"  {pathlib.Path(ref).name[:-len(src.suffix)]}.webp  {im.width}px  "
              f"{_fmt_kb(old_sz)} → {_fmt_kb(new_sz)}（{ratio:.0f}%）")
        if not args.keep_png:
            src.unlink()
        replaced = replaced.replace(f"({ref})", f"({dst.relative_to(guide).as_posix()})")

    if replaced != md:
        md_path.write_text(replaced, encoding="utf-8")

    total_refs = len(set(refs))
    if converted:
        ratio = new_total / old_total * 100 if old_total else 0
        print(f"共 {converted}/{total_refs} 张转 webp（宽 {args.width} / q{args.quality}）："
              f"{_fmt_kb(old_total)} → {_fmt_kb(new_total)}（{ratio:.0f}%）")
    else:
        print(f"无 png/jpg 引用可转换（引用共 {total_refs} 张）")
    if missing:
        print(f"[注意] {missing} 张引用图缺失，未处理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
