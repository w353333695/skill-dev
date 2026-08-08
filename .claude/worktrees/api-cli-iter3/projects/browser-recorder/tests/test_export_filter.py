# tests/test_export_filter.py
"""I-2 验证：export --filter-requests 真正过滤 records（不静默忽略 flag）。"""
from pathlib import Path
import yaml
from browser_recorder.models import RequestRecord, ResponseInfo
from browser_recorder.export.runner import (
    load_request_filter, apply_filter, run_export,
)


def _mk(url, method="GET", status=200):
    return RequestRecord(
        req_id="x", ts=0, method=method, url=url, headers={},
        status=status, response_headers={}, mime="application/json",
        response=ResponseInfo(),
    )


def test_filter_exclude_by_status(tmp_path: Path):
    yaml_path = tmp_path / "f.yaml"
    yaml_path.write_text("exclude_status: [304]\n", encoding="utf-8")
    flt = load_request_filter(yaml_path)
    kept = apply_filter([_mk("https://app.example.com/a", status=200),
                         _mk("https://app.example.com/b", status=304)], flt,
                        target_url="https://app.example.com/")
    assert len(kept) == 1
    assert kept[0].status == 200


def test_filter_exclude_by_method(tmp_path: Path):
    yaml_path = tmp_path / "f.yaml"
    yaml_path.write_text("exclude_methods: [OPTIONS]\n", encoding="utf-8")
    flt = load_request_filter(yaml_path)
    kept = apply_filter([_mk("https://app.example.com/a", method="GET"),
                         _mk("https://app.example.com/a", method="OPTIONS")], flt,
                        target_url="https://app.example.com/")
    assert len(kept) == 1
    assert kept[0].method == "GET"


def test_filter_exclude_by_url_pattern(tmp_path: Path):
    yaml_path = tmp_path / "f.yaml"
    yaml_path.write_text("exclude_url_patterns: ['\\\\.thirdparty\\\\.com/']\n", encoding="utf-8")
    flt = load_request_filter(yaml_path)
    kept = apply_filter([_mk("https://cdn.thirdparty.com/x.js"),
                         _mk("https://app.example.com/api")], flt,
                        target_url="https://app.example.com/")
    assert len(kept) == 1
    assert "example.com" in kept[0].url


def test_filter_exclude_third_party_by_regdomain():
    # load_request_filter(None) 返回内置默认规则（非空），apply_filter 据此过滤。
    # 同 registrable domain 的记录不被当第三方排除。
    flt = load_request_filter(None)
    assert flt != {}
    kept = apply_filter([_mk("https://app.example.com/a")], flt,
                        target_url="https://app.example.com/")
    assert len(kept) == 1


def test_filter_default_when_no_yaml():
    """不传 yaml 时启用内置最佳实践默认：排除第三方 / OPTIONS / 304 / 静态后缀。"""
    flt = load_request_filter(None)
    assert flt != {}                                   # 内置默认（非空）
    assert "OPTIONS" in flt["exclude_methods"]
    assert 304 in flt["exclude_status"]
    records = [
        _mk("https://x.com/api", method="GET", status=200),    # 保留（目标 + 业务）
        _mk("https://y.com/b", method="GET", status=200),      # 排除（第三方）
        _mk("https://x.com/p", method="OPTIONS"),              # 排除（OPTIONS）
        _mk("https://x.com/q", status=304),                    # 排除（304）
        _mk("https://x.com/a.js"),                             # 排除（静态后缀）
    ]
    kept = apply_filter(records, flt, target_url="https://x.com/")
    assert len(kept) == 1
    assert kept[0].url == "https://x.com/api"
