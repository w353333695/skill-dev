"""浏览器路径解析测试。"""
import os
import pathlib

from browser_recorder import cli


def test_br_chrome_has_priority(monkeypatch, tmp_path):
    chrome = tmp_path / "Chrome"
    chrome.write_text("binary")
    chrome.chmod(0o755)
    monkeypatch.setenv("BR_CHROME", str(chrome))
    assert cli.resolve_chrome() == chrome


def test_br_chrome_invalid_does_not_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("BR_CHROME", str(tmp_path / "missing-chrome"))
    assert cli.resolve_chrome() is None
    assert "BR_CHROME" in cli.chrome_error()


def test_macos_candidates_include_installed_apps(monkeypatch):
    monkeypatch.delenv("BR_CHROME", raising=False)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    candidates = cli.chrome_candidates()
    assert pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") in candidates
    assert pathlib.Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium" in candidates
