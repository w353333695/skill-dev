"""CLI 子命令冒烟测试（不触发实际重转换）。"""
from click.testing import CliRunner

from doc_converter.cli import main


def test_version():
    r = CliRunner().invoke(main, ["version"])
    assert r.exit_code == 0
    assert r.output.strip()  # 有版本号输出


def test_list():
    r = CliRunner().invoke(main, ["list"])
    assert r.exit_code == 0
    assert "csv-excel" in r.output
    assert "json-csv" in r.output


def test_check_supported():
    r = CliRunner().invoke(main, ["check", "csv", "xlsx"])
    assert r.exit_code == 0
    assert "csv-excel" in r.output


def test_check_unsupported():
    r = CliRunner().invoke(main, ["check", "xxx", "yyy"])
    assert r.exit_code == 1  # 不支持的转换 -> 非零退出


def test_check_accepts_file_path():
    """check 传文件路径时自动取扩展名（容错用法）。"""
    r = CliRunner().invoke(main, ["check", "tmp/a.md", "docx"])
    assert r.exit_code == 0
    assert "md-docx" in r.output


def test_doctor():
    r = CliRunner().invoke(main, ["doctor"])
    assert r.exit_code == 0
    assert "转换器依赖" in r.output
    assert "chromium" in r.output  # 大件检测段
