"""测试截图器."""
import os
import tempfile
from pathlib import Path
from PIL import Image
from browser_recorder.screenshoter import Screenshoter


def test_mark_click_creates_image():
    """mark_click 在图片上画圆标记并输出."""
    s = Screenshoter()
    # 创建一张 200x100 白色测试图
    img = Image.new("RGB", (200, 100), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        result = s.mark_click(src, (100, 50), out)
        assert result == out
        assert out.exists()
        # 验证输出是有效图片
        marked = Image.open(out)
        assert marked.size == (200, 100)


def test_mark_click_circle_visible():
    """标记图片上应有红色像素（圆圈）."""
    s = Screenshoter()
    img = Image.new("RGB", (100, 100), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        s.mark_click(src, (50, 50), out)
        marked = Image.open(out)
        # 检查中心附近有红色像素
        pixels = []
        for x in range(40, 61):
            for y in range(40, 61):
                pixels.append(marked.getpixel((x, y)))
        has_red = any(p[0] > 200 and p[1] < 100 and p[2] < 100 for p in pixels)
        assert has_red, "应在点击坐标附近找到红色圆圈标记"


def test_mark_click_none_coords_noop():
    """coords 为 None → 不标记，直接复制."""
    s = Screenshoter()
    img = Image.new("RGB", (50, 50), color="white")
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.png"
        img.save(src)
        out = Path(tmpdir) / "out.png"
        result = s.mark_click(src, None, out)
        assert result == out
        assert out.exists()
