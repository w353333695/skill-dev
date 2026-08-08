# tests/test_replay_paths.py
"""I-5 验证：replay webm 仅在 replay_dir 内搜；mp4 写到 replay_dir/video.mp4。

不实际跑回放（需 Playwright + 转码耗时），只断言 _find_webm 不递归兄弟目录、
run_replay 把 replay_dir 传给 record_video_dir。
"""
import inspect
from pathlib import Path
from browser_recorder.replay import runner


def test_find_webm_does_not_recurse():
    """_find_webm 用 glob（不递归），避免拾取兄弟会话的 webm。"""
    src = inspect.getsource(runner._find_webm)
    assert "rglob" not in src, "_find_webm 不得用 rglob（会拾取兄弟会话）"
    assert "glob" in src


def test_find_webm_picks_only_in_dir(tmp_path):
    # replay_dir 内有一个 webm，父目录有另一个会话的 webm
    replay_dir = tmp_path / "replay-1"
    replay_dir.mkdir()
    (replay_dir / "vid.webm").write_bytes(b"x")
    sibling = tmp_path / "replay-2"
    sibling.mkdir()
    (sibling / "vid.webm").write_bytes(b"y")
    found = runner._find_webm(replay_dir)
    assert found is not None
    assert found.parent == replay_dir


def test_replay_async_uses_replay_dir_for_video():
    """_replay_async 的 record_video_dir 必须是 replay_dir 本身（不再用 parent）。"""
    src = inspect.getsource(runner._replay_async)
    # 关键：record_video_dir=str(replay_dir)，不是 replay_dir.parent
    assert "record_video_dir" in src
    assert "replay_dir.parent" not in src


def test_run_replay_writes_mp4_to_replay_dir():
    """run_replay 转码 mp4 写到 replay_dir/video.mp4（不再写到 replay_dir.parent）。"""
    src = inspect.getsource(runner.run_replay)
    assert 'video.mp4' in src
    assert "replay_dir.parent" not in src
