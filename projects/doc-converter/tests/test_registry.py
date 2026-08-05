"""注册表与自动发现测试。"""
from doc_converter.converters import (
    get_converter,
    list_converters,
    list_conversions,
)


def test_registry_non_empty():
    """自动发现应注册多个转换器。"""
    convs = list_converters()
    assert len(convs) > 0
    names = {c["name"] for c in convs}
    # 抽查若干已知转换器
    assert "csv-excel" in names
    assert "json-csv" in names
    assert "md-html" in names


def test_get_converter():
    """get_converter 按 (source, target) 返回转换器，大小写不敏感。"""
    c = get_converter("csv", "xlsx")
    assert c is not None
    assert c.name == "csv-excel"
    # 大小写不敏感
    assert get_converter("CSV", "XLSX").name == "csv-excel"
    # 不支持的返回 None
    assert get_converter("xxx", "yyy") is None


def test_list_conversions_contains_known():
    """list_conversions 含已知路径。"""
    paths = list_conversions()
    assert ("json", "csv", "json-csv") in paths
    assert ("csv", "xlsx", "csv-excel") in paths


def test_converter_dependencies_use_pip_names():
    """dependencies 存 pip 包名（python-docx），非 import 名 docx。"""
    c = get_converter("md", "docx")
    assert c is not None
    assert "python-docx" in c.dependencies
    assert "docx" not in c.dependencies  # 不应是 import 名
