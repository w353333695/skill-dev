"""annotator 单测：红框几何与序号渲染。"""
import json

from PIL import Image

from browser_recorder.annotator import annotate


def test_annotate_draws_box(tmp_path):
    # 造一张 200x100 灰图
    img = Image.new("RGB", (200, 100), (128, 128, 128))
    p = tmp_path / "0001-before.png"
    img.save(p)
    rect = {"x": 10, "y": 20, "w": 30, "h": 40}
    out = annotate(p, rect, dpr=1.0, seq=1)
    im = Image.open(out)
    assert im.size == (200, 100)
    # 框线上应有红色像素（矩形边缘中点）
    edge_pts = [(25, 20), (25, 60), (10, 40), (40, 40)]
    for x, y in edge_pts:
        r, g, b = im.getpixel((x, y))[:3]
        assert r > 180 and g < 100 and b < 100, f"({x},{y})={r,g,b}"
    # 框外远处不受影响
    r, g, b = im.getpixel((5, 5))[:3]
    assert abs(r - 128) < 30 and abs(g - 128) < 30
