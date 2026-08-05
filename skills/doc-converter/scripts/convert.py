#!/usr/bin/env python3
"""
文档格式转换主入口。

用法:
    python convert.py <input> -t <target_format> [-o output] [--options key=value ...]
    python convert.py --list                    # 列出所有支持的转换
    python convert.py --check <source> <target> # 检查是否支持 + 依赖状态

示例:
    python convert.py diagram.md -t pdf -o diagram.pdf
    python convert.py diagram.md -t png --extract mermaid -o diagram.png
    python convert.py data.csv -t xlsx -o data.xlsx
    python convert.py report.md -t docx --extract table -o tables.xlsx
"""

import argparse
import json
import sys
from pathlib import Path

# 确保 converters 包可导入
sys.path.insert(0, str(Path(__file__).parent))
from converters import get_converter, list_converters, list_conversions


def parse_options(option_list: list[str] | None) -> dict:
    """解析 key=value 格式的选项"""
    if not option_list:
        return {}
    opts = {}
    for item in option_list:
        if "=" not in item:
            opts[item] = True
            continue
        k, v = item.split("=", 1)
        # 尝试解析为 JSON 值 (数字、布尔等)
        try:
            v = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            pass
        opts[k] = v
    return opts


def cmd_convert(args):
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 文件不存在: {input_path}", file=sys.stderr)
        return 1

    # 推断源格式
    source_fmt = args.source or input_path.suffix.lstrip(".")
    target_fmt = args.target

    converter = get_converter(source_fmt, target_fmt)
    if not converter:
        print(f"[ERROR] 不支持的转换: {source_fmt} → {target_fmt}", file=sys.stderr)
        print("使用 --list 查看支持的转换", file=sys.stderr)
        return 1

    # 检查依赖
    ok, missing = converter.check_dependencies()
    if not ok:
        print(f"[ERROR] 缺少依赖: {', '.join(missing)}", file=sys.stderr)
        print(f"安装: pip install {' '.join(missing)}", file=sys.stderr)
        return 1

    # 输出路径
    output_path = Path(args.output) if args.output else input_path.with_suffix(f".{target_fmt}")

    # 构建选项
    options = parse_options(args.options)
    if args.extract:
        options["extract"] = args.extract

    print(f"[转换] {input_path} ({source_fmt}) → {output_path} ({target_fmt})")
    print(f"[转换器] {converter.name}")

    result = converter.convert(input_path, output_path, **options)

    if result.success:
        print(f"[OK] {result.message or '转换完成'}")
        print(f"[输出] {result.output_path}")
        return 0
    else:
        print(f"[ERROR] {result.message}", file=sys.stderr)
        return 1


def cmd_list(args):
    print("已注册的转换器:\n")
    for conv in list_converters():
        status = "✅" if conv["deps_ok"] else f"❌ 缺少: {', '.join(conv['deps_missing'])}"
        print(f"  {conv['name']}")
        print(f"    {conv['description']}")
        print(f"    {' / '.join(conv['source_formats'])} → {' / '.join(conv['target_formats'])}")
        print(f"    依赖: {status}")
        print()

    print("支持的转换路径:\n")
    for src, tgt, name in list_conversions():
        print(f"  {src:>10} → {tgt:<10} ({name})")


def cmd_check(args):
    converter = get_converter(args.source, args.target)
    if not converter:
        print(f"❌ 不支持: {args.source} → {args.target}")
        return 1
    ok, missing = converter.check_dependencies()
    if ok:
        print(f"✅ {args.source} → {args.target} ({converter.name}) 就绪")
    else:
        print(f"⚠️ {args.source} → {args.target} ({converter.name}) 缺少依赖: {', '.join(missing)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="文档格式转换工具")
    sub = parser.add_subparsers(dest="command")

    # convert (default)
    p_convert = sub.add_parser("convert", help="执行转换")
    p_convert.add_argument("input", help="输入文件路径")
    p_convert.add_argument("-t", "--target", required=True, help="目标格式 (如 pdf, png, xlsx)")
    p_convert.add_argument("-s", "--source", help="源格式 (默认从扩展名推断)")
    p_convert.add_argument("-o", "--output", help="输出文件路径")
    p_convert.add_argument("--extract", help="提取模式 (mermaid/table/code)")
    p_convert.add_argument("--options", nargs="*", help="额外选项 key=value")

    # list
    sub.add_parser("list", help="列出所有支持的转换")

    # check
    p_check = sub.add_parser("check", help="检查转换支持和依赖")
    p_check.add_argument("source", help="源格式")
    p_check.add_argument("target", help="目标格式")

    args = parser.parse_args()

    # 无子命令时，如果有位置参数则当作 convert
    if args.command is None:
        # 重新解析为 convert
        args = p_convert.parse_args(sys.argv[1:])
        args.command = "convert"

    if args.command == "list":
        return cmd_list(args)
    elif args.command == "check":
        return cmd_check(args)
    elif args.command == "convert":
        return cmd_convert(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
