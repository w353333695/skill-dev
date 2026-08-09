"""测试网络请求拦截."""
from browser_recorder.network import should_record, DEFAULT_RECORD_TYPES


def test_should_record_xhr():
    """XHR 类型应记录."""
    assert should_record("xhr", "https://api.example.com/data", None) is True


def test_should_record_fetch():
    """fetch 类型应记录."""
    assert should_record("fetch", "https://api.example.com/data", None) is True


def test_should_record_document():
    """document 类型应记录."""
    assert should_record("document", "https://example.com", None) is True


def test_should_ignore_image():
    """image 类型不记录."""
    assert should_record("image", "https://example.com/logo.png", None) is False


def test_should_ignore_script():
    """script 类型不记录."""
    assert should_record("script", "https://example.com/app.js", None) is False


def test_should_ignore_stylesheet():
    """stylesheet 类型不记录."""
    assert should_record("stylesheet", "https://example.com/style.css", None) is False


def test_should_ignore_font():
    """font 类型不记录."""
    assert should_record("font", "https://example.com/font.woff2", None) is False


def test_default_record_types():
    """默认记录类型为 xhr, fetch, document."""
    assert "xhr" in DEFAULT_RECORD_TYPES
    assert "fetch" in DEFAULT_RECORD_TYPES
    assert "document" in DEFAULT_RECORD_TYPES
    assert "image" not in DEFAULT_RECORD_TYPES


def test_custom_filter_glob_match():
    """自定义 glob 过滤 — 匹配."""
    assert should_record("xhr", "https://api.example.com/v1/users", "*.api.example.com/*") is True


def test_custom_filter_glob_no_match():
    """自定义 glob 过滤 — 不匹配."""
    assert should_record("xhr", "https://other.com/data", "*.api.example.com/*") is False


def test_custom_filter_glob_override_resource_type():
    """自定义 glob 覆盖 resource_type 限制."""
    assert should_record("image", "https://api.example.com/logo.png", "*.api.example.com/*") is True
