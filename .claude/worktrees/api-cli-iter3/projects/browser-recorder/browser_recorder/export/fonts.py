"""随包字体加载：优先 assets/font.ttf，回退 Pillow 默认字体。"""
from __future__ import annotations
from pathlib import Path
from PIL import ImageFont

_ASSET = Path(__file__).parent / "assets" / "font.ttf"


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if _ASSET.exists():
        try:
            return ImageFont.truetype(str(_ASSET), size)
        except Exception:
            pass
    return ImageFont.load_default()
