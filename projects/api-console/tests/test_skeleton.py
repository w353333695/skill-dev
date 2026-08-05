"""骨架冒烟测试：conftest 的 sys.path 注入生效，scripts/ 可被导入；manifest 可加载。"""
from __future__ import annotations


def test_scripts_dir_on_path():
    import sys
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    assert str(scripts) in sys.path


def test_manifest_loads():
    """manifest 可加载（新/旧形态皆可，不绑死结构）。"""
    from pathlib import Path
    from api_console.manifest_loader import load_manifest
    platform_dir = Path(__file__).resolve().parents[3] / "platforms" / "easyops"
    m = load_manifest(platform_dir)
    assert m["name"] == "easyops"
    assert m["host"], "manifest 选定环境 host 不能为空"
    assert "auth" in m
    assert m["gateway_base"].startswith("http://")
