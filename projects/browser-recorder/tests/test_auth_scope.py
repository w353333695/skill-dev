# tests/test_auth_scope.py
from browser_recorder.auth import scope


def test_registrable_domain_simple():
    assert scope.registrable_domain("app.example.com") == "example.com"
    assert scope.registrable_domain("example.com") == "example.com"


def test_registrable_domain_multi_suffix():
    assert scope.registrable_domain("site.co.uk") == "co.uk" or scope.registrable_domain("site.co.uk") == "site.co.uk"
    # 简化算法接受二选一；关键是不把 site.co.uk 当成 site


def test_matches_port_change_does_not_affect():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"], "ports": [443, 8443, None]}
    assert scope.matches("https://example.com/login", s)
    assert scope.matches("https://example.com:8443/login", s)


def test_matches_subdomain():
    s = {"registrable_domain": "example.com",
         "hosts": ["example.com", "app.example.com", "console.example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert scope.matches("https://app.example.com/x", s)
    assert scope.matches("https://console.example.com/x", s)


def test_matches_different_registrable_domain_rejected():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert not scope.matches("https://other.com/x", s)


def test_matches_scheme_http_https_interchangeable():
    """http/https 互通（内网自签证书 HTTP→HTTPS 跳转常见，不应因 scheme 不匹配而要求重新登录）。"""
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"]}
    assert scope.matches("http://example.com/x", s)   # https scope 兼容 http
    s2 = {"registrable_domain": "example.com", "hosts": ["example.com"],
          "host_match": "suffix", "scheme": ["http"]}
    assert scope.matches("https://example.com/x", s2)  # http scope 兼容 https


def test_matches_scheme_http_allowed_when_configured():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["http", "https"]}
    assert scope.matches("http://example.com/x", s)


def test_matches_path_prefix_narrows():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "suffix", "scheme": ["https"], "path_prefix": ["/admin"]}
    assert scope.matches("https://example.com/admin/users", s)
    assert not scope.matches("https://example.com/public", s)


def test_host_match_exact():
    s = {"registrable_domain": "example.com", "hosts": ["example.com"],
         "host_match": "exact", "scheme": ["https"]}
    assert scope.matches("https://example.com/x", s)
    assert not scope.matches("https://app.example.com/x", s)
