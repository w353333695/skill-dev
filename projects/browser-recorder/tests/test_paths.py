# tests/test_paths.py
import re
from pathlib import Path
from browser_recorder import paths


def test_resolve_out_dir_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = paths.resolve_out_dir(None)
    assert d == tmp_path / ".browser-recorder"


def test_resolve_out_dir_custom(tmp_path):
    d = paths.resolve_out_dir(str(tmp_path / "custom"))
    assert d == tmp_path / "custom"


def test_session_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TMP_ROOT", tmp_path / "tmp")
    d = paths.session_dir("20260802-153012-a1b2")
    assert d == tmp_path / "tmp" / "20260802-153012-a1b2"


def test_export_dir_under_out_dir(tmp_out_dir):
    d = paths.export_dir(tmp_out_dir, "my-rec")
    assert d == tmp_out_dir / "exports" / "my-rec"


def test_auth_dirs(tmp_out_dir):
    assert paths.auth_dir(tmp_out_dir) == tmp_out_dir / "auth"
    assert paths.profile_dir(tmp_out_dir, "demo") == tmp_out_dir / "auth" / "demo"


def test_new_session_id_format():
    sid = paths.new_session_id()
    assert re.fullmatch(r"\d{8}-\d{6}-[a-z0-9]{6}", sid), sid


def test_new_session_id_unique():
    ids = {paths.new_session_id() for _ in range(50)}
    assert len(ids) == 50
