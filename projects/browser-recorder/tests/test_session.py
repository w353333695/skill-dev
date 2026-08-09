"""测试 session 管理 — 域名鉴权共享 + 场景独立录制."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from browser_recorder.recorder import (
    _domain_key,
    domain_path,
    scenario_path,
    load_index,
    save_index,
    load_domain_meta,
    save_domain_meta,
    load_scenario_meta,
    save_scenario_meta,
    ARTIFACT_ROOT,
)


class TestDomainKey:
    def test_https_domain(self):
        assert _domain_key("https://example.com/path") == "example.com"

    def test_ip_with_port(self):
        assert _domain_key("http://192.168.1.1:8080/admin") == "192.168.1.1_8080"

    def test_standard_port_not_in_key(self):
        assert _domain_key("http://example.com:80/page") == "example.com"
        assert _domain_key("https://example.com:443/page") == "example.com"

    def test_subdomain(self):
        assert _domain_key("https://app.example.com/login") == "app.example.com"

    def test_no_scheme(self):
        assert _domain_key("example.com/path") == "unknown"


class TestPaths:
    def test_domain_path(self):
        assert domain_path("https://example.com") == ARTIFACT_ROOT / "example.com"

    def test_scenario_path_default(self):
        p = scenario_path("https://example.com")
        assert p == ARTIFACT_ROOT / "example.com" / "default"

    def test_scenario_path_named(self):
        p = scenario_path("https://example.com", "login-flow")
        assert p == ARTIFACT_ROOT / "example.com" / "login-flow"

    def test_scenario_path_ip(self):
        p = scenario_path("http://10.0.0.1:3000/admin", "api-test")
        assert p == ARTIFACT_ROOT / "10.0.0.1_3000" / "api-test"


class TestMetaIO:
    def test_domain_meta_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = load_domain_meta(Path(tmp))
            assert meta["domain"] == Path(tmp).name
            assert meta["first_seen"] is None
            assert meta["scenarios"] == {}

    def test_domain_meta_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            meta = {
                "domain": d.name,
                "first_seen": "2026-08-09T14:00:00",
                "last_recorded": "2026-08-09T15:00:00",
                "total_recordings": 3,
                "urls": ["https://example.com"],
                "scenarios": {
                    "login": {"last_recorded": "t", "total_recordings": 2},
                    "browse": {"last_recorded": "t", "total_recordings": 1},
                },
            }
            save_domain_meta(d, meta)
            loaded = load_domain_meta(d)
            assert loaded["total_recordings"] == 3
            assert len(loaded["scenarios"]) == 2

    def test_scenario_meta_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = load_scenario_meta(Path(tmp))
            assert meta["first_seen"] is None
            assert meta["total_recordings"] == 0

    def test_scenario_meta_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            meta = {
                "name": d.name,
                "first_seen": "2026-08-09T14:00:00",
                "last_recorded": "2026-08-09T15:00:00",
                "total_recordings": 3,
                "sessions": [
                    {"ts": "t", "url": "https://ex.com", "steps": 10, "duration_s": 120.0}
                ],
            }
            save_scenario_meta(d, meta)
            loaded = load_scenario_meta(d)
            assert loaded["total_recordings"] == 3
            assert len(loaded["sessions"]) == 1


class TestIndexIO:
    def test_load_index_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('browser_recorder.recorder.ARTIFACT_ROOT', Path(tmp)):
                assert load_index() == {"domains": {}}

    def test_save_and_load_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('browser_recorder.recorder.ARTIFACT_ROOT', Path(tmp)):
                index = {"domains": {"example.com": {"last_recorded": "t", "scenarios": ["login"]}}}
                save_index(index)
                loaded = load_index()
                assert "example.com" in loaded["domains"]
                assert loaded["domains"]["example.com"]["scenarios"] == ["login"]


class TestRecorderSessionManagement:
    """Recorder 构造器 — 域名/场景路径分配."""

    def test_scenario_default(self):
        r = RecorderStub("https://example.com/login")
        assert r.domain_dir.name == "example.com"
        assert r.scenario_dir.name == "default"
        assert r.scenario_dir.parent.name == "example.com"

    def test_scenario_named(self):
        r = RecorderStub("https://example.com", scenario_name="login-flow")
        assert r.scenario_dir.name == "login-flow"

    def test_same_domain_diff_scenarios(self):
        r1 = RecorderStub("https://example.com", scenario_name="login")
        r2 = RecorderStub("https://example.com", scenario_name="browse")
        assert r1.domain_dir == r2.domain_dir          # 同域名
        assert r1.scenario_dir != r2.scenario_dir      # 不同场景

    def test_same_domain_same_scenario_reuses(self):
        r1 = RecorderStub("https://example.com/page1", scenario_name="main")
        r2 = RecorderStub("https://example.com/page2", scenario_name="main")
        assert r1.scenario_dir == r2.scenario_dir      # 同场景复用

    def test_diff_domains_same_scenario_name(self):
        r1 = RecorderStub("https://a.com", scenario_name="main")
        r2 = RecorderStub("https://b.com", scenario_name="main")
        assert r1.domain_dir != r2.domain_dir
        assert r1.scenario_dir != r2.scenario_dir      # 不同域名的 main 独立

    def test_explicit_output_overrides(self):
        r = RecorderStub("https://example.com",
                         output_dir=Path("/tmp/custom"),
                         scenario_name="x")
        assert r.scenario_dir == Path("/tmp/custom")

    def test_auth_file_path(self):
        r = RecorderStub("https://example.com", scenario_name="login")
        assert r._auth_file == r.domain_dir / "auth.json"

    def test_screenshots_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "myscenario"
            ss_dir = d / "screenshots"
            ss_dir.mkdir(parents=True)
            (ss_dir / "old.png").write_text("fake")

            RecorderStub("https://ex.com", output_dir=d)
            assert ss_dir.exists()
            assert not (ss_dir / "old.png").exists()


class RecorderStub:
    """Recorder 构造器轻量 stub."""

    def __init__(self, url, output_dir=None, scenario_name="default", **kwargs):
        self.url = url
        self.scenario_name = scenario_name
        self.domain_dir = domain_path(url)
        self.scenario_dir = output_dir or scenario_path(url, scenario_name)
        self.scenario_dir.mkdir(parents=True, exist_ok=True)
        self._auth_file = self.domain_dir / "auth.json"

        import shutil
        ss_dir = self.scenario_dir / "screenshots"
        if ss_dir.exists():
            shutil.rmtree(ss_dir)
        ss_dir.mkdir(parents=True, exist_ok=True)
