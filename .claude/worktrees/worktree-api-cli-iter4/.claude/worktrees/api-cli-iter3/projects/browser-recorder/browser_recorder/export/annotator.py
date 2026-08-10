"""导出期半透明画标：RGBA + alpha_composite + 描边优先 + 外置序号 + 碰撞避让。

防遮盖小字体：核心信号靠不透明描边/序号，填充压得很淡（半透明）。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw
from .fonts import load_font

COMPACT = "compact"
VERBOSE = "verbose"

# 动作类型 → (描边色, 填充色)
_STYLE = {
    "click":   ((220, 40, 40), (220, 40, 40)),
    "submit":  ((220, 40, 40), (220, 40, 40)),
    "input":   ((40, 90, 220), (40, 90, 220)),
    "select":  ((140, 40, 200), (140, 40, 200)),
    "scroll":  ((220, 170, 30), (220, 170, 30)),
    "navigation": ((20, 140, 80), (20, 140, 80)),
    "hover":   ((120, 120, 120), (120, 120, 120)),
}
_DEFAULT = ((200, 200, 200), (200, 200, 200))

LABEL_SIZE = 18
LABEL_MARGIN = 4


def _color(t: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return _STYLE.get(t, _DEFAULT)


def resolve_label_positions(marks: list[dict[str, Any]],
                            img_size: tuple[int, int]) -> list[tuple[dict, tuple[int, int]]]:
    """序号气泡外置右下角；重叠时沿对角线外推。"""
    out: list[tuple[dict, tuple[int, int]]] = []
    placed: list[tuple[int, int, int, int]] = []  # x,y,w,h
    iw, ih = img_size
    for m in marks:
        b = m["bbox"]
        # 默认放元素右下角外侧
        x = int(b["x"] + b["w"]) + LABEL_MARGIN
        y = int(b["y"] + b["h"]) + LABEL_MARGIN
        w = h = LABEL_SIZE + 6
        # 边界
        x = min(x, iw - w - 2)
        y = min(y, ih - h - 2)
        # 碰撞避让：沿对角线外推
        for _ in range(40):
            collided = any(not (x + w < px or x > px + pw or y + h < py or y > py + ph)
                           for (px, py, pw, ph) in placed)
            if not collided:
                break
            x -= (w + 2); y -= (h + 2)
            x = max(2, x); y = max(2, y)
        placed.append((x, y, w, h))
        out.append((m, (x, y)))
    return out


def annotate_screenshot(src_png: Path, dst_png: Path, marks: list[dict[str, Any]],
                        *, style: str, opacity: int) -> None:
    """读 RGB 原图 → 在透明 RGBA 层画标 → alpha_composite → 存 dst。"""
    base = Image.open(src_png).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_font(LABEL_SIZE)
    alpha_fill = max(0, min(255, int(255 * (opacity / 100.0))))
    positions = resolve_label_positions(marks, base.size)

    for m, (lx, ly) in positions:
        b = m["bbox"]
        stroke, fill = _color(m["type"])
        x0, y0 = int(b["x"]), int(b["y"])
        x1, y1 = int(b["x"] + b["w"]), int(b["y"] + b["h"])
        # 描边（不透明）
        draw.rectangle([x0, y0, x1, y1], outline=stroke + (255,), width=3)
        # 半透明填充：verbose 才填充；compact 仅 click/submit 这种点用极淡
        if style == VERBOSE:
            draw.rectangle([x0, y0, x1, y1], fill=fill + (alpha_fill,))
        elif m["type"] in ("input", "select", "hover"):
            draw.rectangle([x0, y0, x1, y1], fill=fill + (max(40, alpha_fill // 2),))
        # 序号气泡（不透明）
        draw.ellipse([lx, ly, lx + LABEL_SIZE + 6, ly + LABEL_SIZE + 6],
                     fill=stroke + (255,), outline=(255, 255, 255, 255), width=1)
        text = str(m["seq"])
        try:
            tw, th = draw.textbbox((0, 0), text, font=font)[2:]
        except Exception:
            tw, th = (LABEL_SIZE, LABEL_SIZE)
        draw.text((lx + (LABEL_SIZE + 6 - tw) // 2, ly + (LABEL_SIZE + 6 - th) // 2 - 1),
                  text, fill=(255, 255, 255, 255), font=font,
                  stroke_width=1, stroke_fill=(0, 0, 0, 255))

    composited = Image.alpha_composite(base, overlay)
    composited.convert("RGB").save(dst_png)
