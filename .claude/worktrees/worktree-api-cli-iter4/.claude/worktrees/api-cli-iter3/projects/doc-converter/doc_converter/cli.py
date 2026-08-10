"""doc_converter.cli:click CLI 入口。

子命令:convert / list / check / doctor / install-deps / version。

平台中性:不耦合任何特定系统/厂商，仅做本地文档格式转换。
"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import click

from .converters import get_converter, list_converters, list_conversions

logger = logging.getLogger(__name__)


def parse_options(option_list: tuple[str, ...] | None) -> dict:
    """解析 key=value 格式的选项（值尝试 JSON 解析为数字/布尔等）。"""
    if not option_list:
        return {}
    opts = {}
    for item in option_list:
        if "=" not in item:
            opts[item] = True
            continue
        k, v = item.split("=", 1)
        try:
            v = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            pass
        opts[k] = v
    return opts


@click.group()
def main() -> None:
    """文档格式转换:md/docx/pdf/html/excel/csv/json/mermaid 互转 + 内容提取。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


@main.command()
@click.argument("input", type=click.Path(exists=True))
@click.option("-t", "--target", required=True, help="目标格式 (如 pdf/png/xlsx)")
@click.option("-s", "--source", default=None, help="源格式 (默认从扩展名推断)")
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.option("--extract", default=None, help="提取模式 (mermaid/table/outline/links/images/code)")
@click.option("--options", "options", multiple=True, help="额外选项 key=value")
def convert(input, target, source, output, extract, options):
    """执行转换。"""
    input_path = Path(input)
    source_fmt = source or input_path.suffix.lstrip(".")
    target_fmt = target

    converter = get_converter(source_fmt, target_fmt)
    if not converter:
        click.echo(f"[ERROR] 不支持的转换: {source_fmt} -> {target_fmt}", err=True)
        click.echo("使用 list 查看支持的转换", err=True)
        raise SystemExit(1)

    ok, missing = converter.check_dependencies()
    if not ok:
        click.echo(f"[ERROR] 缺少依赖: {', '.join(missing)}", err=True)
        click.echo(f"安装: pip install {' '.join(missing)}", err=True)
        raise SystemExit(1)

    output_path = Path(output) if output else input_path.with_suffix(f".{target_fmt}")

    opts = parse_options(options)
    if extract:
        opts["extract"] = extract

    click.echo(f"[转换] {input_path} ({source_fmt}) -> {output_path} ({target_fmt})")
    click.echo(f"[转换器] {converter.name}")

    result = converter.convert(input_path, output_path, **opts)

    if result.success:
        click.echo(f"[OK] {result.message or '转换完成'}")
        if result.output_path:
            click.echo(f"[输出] {result.output_path}")
    else:
        click.echo(f"[ERROR] {result.message}", err=True)
        raise SystemExit(1)


@main.command("list")
def list_cmd():
    """列出所有支持的转换。"""
    click.echo("已注册的转换器:\n")
    for conv in list_converters():
        status = "✅" if conv["deps_ok"] else f"❌ 缺少: {', '.join(conv['deps_missing'])}"
        click.echo(f"  {conv['name']}")
        click.echo(f"    {conv['description']}")
        click.echo(f"    {' / '.join(conv['source_formats'])} -> {' / '.join(conv['target_formats'])}")
        click.echo(f"    依赖: {status}\n")

    click.echo("支持的转换路径:\n")
    for src, tgt, name in list_conversions():
        click.echo(f"  {src:>10} -> {tgt:<10} ({name})")


@main.command()
@click.argument("source")
@click.argument("target")
def check(source, target):
    """检查转换支持和依赖。"""
    converter = get_converter(source, target)
    if not converter:
        click.echo(f"❌ 不支持: {source} -> {target}")
        raise SystemExit(1)
    ok, missing = converter.check_dependencies()
    if ok:
        click.echo(f"✅ {source} -> {target} ({converter.name}) 就绪")
    else:
        click.echo(f"⚠️ {source} -> {target} ({converter.name}) 缺少依赖: {', '.join(missing)}")


@main.command()
def doctor():
    """检查转换器依赖 + 可选 extras + 运行时大件就绪状态。"""
    click.echo("转换器依赖:")
    for conv in list_converters():
        status = "✅" if conv["deps_ok"] else f"❌ 缺: {', '.join(conv['deps_missing'])}"
        click.echo(f"  {conv['name']:<20} {status}")

    click.echo("\n可选 extras（按需安装，核心转换不需要）:")
    try:
        import pypandoc, typst  # noqa: F401
        click.echo("  [typst]  pandoc3+typst ✅   md→pdf 主路径（原生中文/表格/代码高亮）")
    except ImportError:
        click.echo("  [typst]  ❌   pip install 'doc-converter[typst]'  (md→pdf 主路径)")
    try:
        import playwright  # noqa: F401
        click.echo("  [render] playwright ✅   PDF/截图渲染 + md→pdf 的 mermaid 嵌入")
    except ImportError:
        click.echo("  [render] playwright ❌   pip install 'doc-converter[render]'")
    try:
        import pdf2docx  # noqa: F401
        click.echo("  [pdf]    pdf2docx  ✅   PDF→Word")
    except ImportError:
        click.echo("  [pdf]    pdf2docx  ❌   pip install 'doc-converter[pdf]'")

    click.echo("\nmd→pdf 引擎链（自动按优先级选用）:")
    try:
        import pypandoc, typst  # noqa: F401
        click.echo("  ✅ pandoc3+typst（主路径，已就绪）")
    except ImportError:
        click.echo("  ❌ pandoc3+typst 主路径未装 → 将回退")
    if shutil.which("pandoc") and shutil.which("xelatex"):
        click.echo("  ✅ 系统 pandoc+xelatex（回退路径）")
    else:
        click.echo("  ⚠️  系统 pandoc+xelatex 不全（回退不可用；非必需）")

    click.echo("\n运行时大件:")
    cache = Path.home() / ".cache" / "ms-playwright"
    chromium_dirs = list(cache.glob("chromium-*")) if cache.exists() else []
    if chromium_dirs:
        click.echo(f"  chromium ✅ ({chromium_dirs[0].name})")
    else:
        click.echo("  chromium ❌ 未装（装 [render] 后运行: doc-converter install-deps）")
    if shutil.which("pandoc"):
        click.echo("  pandoc ✅ (docx→md 用)")
    else:
        click.echo("  pandoc ❌ 未装（docx→md 需要；brew/apt install pandoc）")


@main.command("install-deps")
def install_deps():
    """安装运行时大件:playwright chromium (pandoc 为系统包，仅给提示)。"""
    try:
        import playwright  # noqa: F401
    except ImportError:
        click.echo("playwright 未安装，先 uv sync 或 pip install playwright", err=True)
        raise SystemExit(1)
    click.echo("安装 chromium...")
    rc = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"]).returncode
    if rc != 0:
        raise SystemExit(rc)
    if not shutil.which("pandoc"):
        click.echo("\n提示:docx->md 还需系统 pandoc (brew install pandoc / apt install pandoc)")
    click.echo("✅ 完成")


@main.command()
def version():
    """显示版本。"""
    from . import __version__
    click.echo(__version__)


if __name__ == "__main__":
    main()
