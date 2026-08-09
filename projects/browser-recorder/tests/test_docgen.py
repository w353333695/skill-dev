"""docgen 测试。"""

from browser_recorder import docgen
from browser_recorder.models import SelectorSet, StepEvent


def _write_steps(tmp_path, steps):
    (tmp_path / "record.jsonl").write_text("\n".join(s.dumps() for s in steps), encoding="utf-8")


def test_generate_doc(tmp_path):
    steps = [
        StepEvent(seq=1, type="input", label="用户名", value="alice"),
        StepEvent(seq=2, type="input", label="密码", value="secret", sensitive=True),
        StepEvent(seq=3, type="click", label="登录", selectors=SelectorSet(id="#btn"),
                  screenshot="screenshots/step-003.png"),
    ]
    _write_steps(tmp_path, steps)

    path = docgen.generate(tmp_path)
    md = path.read_text(encoding="utf-8")

    assert "在【用户名】输入 `alice`" in md
    assert "在【密码】输入 ***" in md          # 密码脱敏
    assert "secret" not in md
    assert "点击【登录】" in md
    assert "![步骤3](screenshots/step-003.png)" in md


def test_empty_session(tmp_path):
    path = docgen.generate(tmp_path)
    assert "# 操作手册" in path.read_text(encoding="utf-8")
