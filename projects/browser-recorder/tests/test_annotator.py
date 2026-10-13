"""annotator 单测：红框几何（无序号标记）+ webp 压缩落盘。"""
from PIL import Image

from browser_recorder.annotator import annotate


def test_annotate_draws_box_and_compresses(tmp_path):
    # 造一张 200x100 灰图
    img = Image.new("RGB", (200, 100), (128, 128, 128))
    p = tmp_path / "0001-before.png"
    img.save(p)
    rect = {"x": 10, "y": 20, "w": 30, "h": 40}
    out = annotate(p, rect, dpr=1.0)
    assert out.suffix == ".webp" and out.exists()
    assert not p.exists()                        # 原 png 已删除
    im = Image.open(out)
    assert im.size == (200, 100)                 # 小于 max_width：不缩放
    # 框线上应有红色像素（矩形边缘中点；webp 有损，按红主导判定）
    def is_red(px):
        r, g, b = px[:3]
        return r > 150 and r - g > 80 and r - b > 80

    edge_pts = [(25, 20), (25, 60), (10, 40), (40, 40)]
    for x, y in edge_pts:
        assert is_red(im.getpixel((x, y))), f"({x},{y})={im.getpixel((x, y))}"
    # 框外远处不受影响（webp 有损，放宽阈值）
    r, g, b = im.getpixel((5, 5))[:3]
    assert abs(r - 128) < 40 and abs(g - 128) < 40
    # 红框上方（原序号标记位置）不应有任何红色像素
    for y in range(0, 16):
        for x in range(0, 200):
            assert not is_red(im.getpixel((x, y))), f"框上方 ({x},{y}) 出现红色：{im.getpixel((x,y))}"


def test_annotate_downscales_and_allows_empty_rect(tmp_path):
    # rect 为空 → 只压缩不画框；超宽图缩到 max_width
    img = Image.new("RGB", (2560, 1576), (200, 200, 200))
    p = tmp_path / "0002-before.png"
    img.save(p)
    out = annotate(p, None, dpr=2.0)
    assert out.suffix == ".webp"
    im = Image.open(out)
    assert im.width == 1280 and im.height == 788
    assert not p.exists()
