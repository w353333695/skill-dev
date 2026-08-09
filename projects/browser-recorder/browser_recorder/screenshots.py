"""截图与标注：page.screenshot + Pillow 画点击位置标记。

坐标说明：录制事件里的 point 是 CSS 像素（clientX/Y），截图像素 = CSS 像素 × devicePixelRatio，
标注时按 dpr 缩放（CDP attach 到别人浏览器时 dpr 可能非 1）。
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def annotate(png_bytes: bytes, point: dict | None, seq: int, dpr: float = 1.0) -> bytes:
    """在截图上标注：点击位置红圈 + 箭头，左上角步骤序号徽标。"""
    img = Image.open(io.BytesIO(png_bytes))
    draw = ImageDraw.Draw(img)

    if point:
        x, y = point["x"] * dpr, point["y"] * dpr
        r = 24 * dpr
        w = max(3, int(4 * dpr))
        draw.ellipse([x - r, y - r, x + r, y + r], outline=(220, 38, 38), width=w)
        # 从右上方指过来的箭头
        ax, ay = x + r * 2.2, y - r * 2.2
        draw.line([ax, ay, x + r * 0.5, y - r * 0.5], fill=(220, 38, 38), width=w)
        for dx, dy in [(-14, -2), (-2, -14)]:  # 简单箭头头部
            draw.line(
                [x + r * 0.5, y - r * 0.5, x + r * 0.5 - dx * dpr * 0.3, y - r * 0.5 - dy * dpr * 0.3],
                fill=(220, 38, 38), width=w,
            )

    # 左上角序号徽标
    badge = 20 * dpr
    draw.rectangle([8, 8, 8 + badge * 2.4, 8 + badge * 1.6], fill=(220, 38, 38))
    draw.text((8 + badge * 0.4, 8 + badge * 0.5), f"#{seq}", fill=(255, 255, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def capture(page, path, point: dict | None, seq: int, dpr: float = 1.0) -> bool:
    """对 page 截图并标注后写入 path。失败（如页面正在销毁）返回 False。

    必须在 playwright 连接线程调用（同步 CDP 调用）。
    """
    try:
        png = page.screenshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(annotate(png, point, seq, dpr))
        return True
    except Exception:
        return False
