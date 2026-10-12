"""截图红框标注：rect × dpr → 像素框。原地覆写。"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

RED = (255, 0, 0, 255)


def annotate(png_path: pathlib.Path, rect: dict, dpr: float = 1.0) -> pathlib.Path:
    png_path = pathlib.Path(png_path)
    im = Image.open(png_path).convert("RGB")
    d = ImageDraw.Draw(im)
    x, y = rect["x"] * dpr, rect["y"] * dpr
    w, h = rect["w"] * dpr, rect["h"] * dpr
    lw = max(2, int(2 * dpr))
    for i in range(lw):
        d.rectangle([x - i, y - i, x + w + i, y + h + i], outline=RED)
    im.save(png_path)
    return png_path
