# tests/test_annotator.py
from pathlib import Path
from PIL import Image
from browser_recorder.export import annotator


def _mk_img(p: Path, size=(400, 300), color=(255, 255, 255)):
    img = Image.new("RGB", size, color)
    img.save(p)


def test_annotate_produces_rgba_alpha_composited_output(tmp_path):
    src = tmp_path / "in.png"
    dst = tmp_path / "out.png"
    _mk_img(src)
    marks = [{"seq": 1, "type": "click", "bbox": {"x": 50, "y": 50, "w": 80, "h": 30}}]
    annotator.annotate_screenshot(src, dst, marks, style=annotator.VERBOSE, opacity=40)
    out = Image.open(dst)
    assert out.mode in ("RGBA", "RGB")
    # 画标后应与原图不同（说明叠加了标记层）
    assert list(out.getdata()) != list(Image.open(src).convert(out.mode).getdata())


def test_label_positions_outside_bbox(tmp_path):
    img_size = (400, 300)
    marks = [{"seq": 1, "type": "input",
              "bbox": {"x": 100, "y": 100, "w": 60, "h": 20}}]
    positions = annotator.resolve_label_positions(marks, img_size)
    mark, (lx, ly) = positions[0]
    bx = mark["bbox"]
    # 序号气泡应在元素右下角外侧（x 超出右边 或 y 超出下边）
    right = bx["x"] + bx["w"]
    bottom = bx["y"] + bx["h"]
    assert lx >= right - 2 or ly >= bottom - 2


def test_label_positions_avoid_collision(tmp_path):
    img_size = (600, 200)
    marks = [
        {"seq": 1, "type": "click", "bbox": {"x": 10, "y": 10, "w": 40, "h": 20}},
        {"seq": 2, "type": "click", "bbox": {"x": 55, "y": 10, "w": 40, "h": 20}},
    ]
    positions = annotator.resolve_label_positions(marks, img_size)
    # 两个气泡中心应不重叠（距离 > 气泡尺寸）
    centers = []
    for m, (lx, ly) in positions:
        centers.append((lx, ly))
    dx = abs(centers[0][0] - centers[1][0])
    dy = abs(centers[0][1] - centers[1][1])
    assert dx > 10 or dy > 10


def test_compact_style_fills_less_than_verbose(tmp_path):
    """compact 模式应只有描边+序号；verbose 多半透明填充。

    用填充像素数差异近似断言。"""
    src = tmp_path / "in.png"
    _mk_img(src)
    marks = [{"seq": 1, "type": "click", "bbox": {"x": 50, "y": 50, "w": 100, "h": 60}}]
    v = tmp_path / "v.png"; c = tmp_path / "c.png"
    annotator.annotate_screenshot(src, v, marks, style=annotator.VERBOSE, opacity=60)
    annotator.annotate_screenshot(src, c, marks, style=annotator.COMPACT, opacity=60)
    def colored(p):
        im = Image.open(p).convert("RGB")
        return sum(1 for px in im.getdata() if px != (255, 255, 255))
    assert colored(v) > colored(c)
