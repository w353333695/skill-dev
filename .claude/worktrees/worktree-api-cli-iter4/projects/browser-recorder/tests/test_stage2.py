"""阶段 2/4 补充：SPA pushState 导航记录 + 回放录像。"""

from __future__ import annotations

import time

import pytest

from browser_recorder.models import read_steps
from browser_recorder.recorder import Recorder
from browser_recorder.replayer import Replayer

pytestmark = pytest.mark.e2e


def test_spa_pushstate_recorded(tmp_path, demo_server):
    """SPA pushState 路由变化应记录为 navigate 步骤。"""
    recorder = Recorder(url=f"{demo_server.url}/spa", use_auth=False, output_root=str(tmp_path), headless=True)
    recorder.start()
    page = recorder.page

    page.evaluate("() => document.getElementById('tab-b').click()")
    time.sleep(0.8)
    recorder.drain()
    session_dir = recorder.finish()

    steps = read_steps(session_dir)
    nav = [s for s in steps if s.type == "navigate"]
    # 起始导航 + pushState 导航
    assert any(s.value and s.value.endswith("/spa#b") for s in nav), \
        f"应记录 pushState 导航: {[(s.type, s.value) for s in steps]}"


def test_replay_video(tmp_path, demo_server):
    """回放录像：video=True 时 replay/video/ 下应产出视频文件。"""
    recorder = Recorder(url=demo_server.url, use_auth=False, output_root=str(tmp_path), headless=True)
    recorder.start()
    page = recorder.page
    page.evaluate("""() => {
      const u = document.getElementById('username');
      u.value = 'alice';
      u.dispatchEvent(new Event('input', {bubbles: true}));
      u.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    recorder.drain()
    session_dir = recorder.finish()

    report = Replayer(session_dir, video=True).run()
    assert report["failed"] == 0
    video_dir = session_dir / "replay" / "video"
    videos = list(video_dir.glob("*.webm")) if video_dir.exists() else []
    assert videos, f"应有回放录像: {list((session_dir / 'replay').rglob('*'))}"
