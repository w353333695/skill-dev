# tests/test_transcode.py
"""mp4 转码：默认宽度 1024、高度按比例自动（mock subprocess，不真转码）。"""
from browser_recorder.export import transcode


def test_to_mp4_applies_default_width(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcode.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    transcode.to_mp4(tmp_path / "a.webm", tmp_path / "a.mp4")
    assert "-vf" in calls[0]
    assert f"scale={transcode.DEFAULT_VIDEO_WIDTH}:-2" in calls[0]


def test_to_mp4_custom_width(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcode.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    transcode.to_mp4(tmp_path / "a.webm", tmp_path / "a.mp4", width=640)
    assert "scale=640:-2" in calls[0]


def test_to_mp4_no_scale_when_width_none(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcode.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    transcode.to_mp4(tmp_path / "a.webm", tmp_path / "a.mp4", width=None)
    assert not any(a == "-vf" for a in calls[0])    # 保持原分辨率
