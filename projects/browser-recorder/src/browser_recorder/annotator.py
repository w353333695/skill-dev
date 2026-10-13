"""截图红框标注 + 压缩落盘：rect × dpr → 像素框；缩至最大宽度后存 webp（原 png 删除）。"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

RED = (255, 0, 0, 255)
MAX_WIDTH = 1280  # 输出最大宽度（只缩不放）
QUALITY = 80      # webp 质量


def annotate(png_path: pathlib.Path, rect: dict | None, dpr: float = 1.0,
             max_width: int = MAX_WIDTH, quality: int = QUALITY) -> pathlib.Path:
    """画红框（rect 为空/零尺寸时只压缩）→ 等比缩至 max_width → 存同名 .webp 并删除原图。

    返回最终 webp 路径。调用方需容错：压缩失败时保留原 png 兜底（见 harness._annotate_safe）。
    """
    src = pathlib.Path(png_path)
    im = Image.open(src).convert("RGB")
    if rect and rect.get("w") and rect.get("h"):
        d = ImageDraw.Draw(im)
        x, y = rect["x"] * dpr, rect["y"] * dpr
        w, h = rect["w"] * dpr, rect["h"] * dpr
        lw = max(2, int(2 * dpr))
        for i in range(lw):
            d.rectangle([x - i, y - i, x + w + i, y + h + i], outline=RED)
    if im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
    dst = src.with_suffix(".webp")
    im.save(dst, "WEBP", quality=quality, method=6)
    src.unlink(missing_ok=True)
    return dst
