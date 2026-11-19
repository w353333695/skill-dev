#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 vCenter监控 套件 zip（顶层目录=plugin.yaml.name，显式目录条目+权限，见
package-format.yaml#package_structure.top_level_rule）。版本号自动递增（同版本重打
pip/平台端不识别，发版必 bump）。产物命名 {类别}_{名称}_{版本}.zip（Hub 新命名规范）。"""
import argparse
import re
import stat
import sys
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "monitor-kits/vcenter-monitoring"
HUB_DIR = Path(__file__).resolve().parents[1] / "hub/monitor-kits"

# zip 内只保留套件运行必需文件；sources.md/build-support/package.conf.yaml 为开发态文件
INCLUDE = [
    "plugin.yaml",
    "origin_metric.json",
    "alias_metric.json",
    "metric_set.json",
    "readme",
    "src/vcenter_monitor.py",
    "src/vcenter_monitor.orig",
]


def read_meta():
    text = (KIT / "plugin.yaml").read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*(.+?)\s*$", text).group(1).strip()
    version = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)", text).group(1).strip()
    return name, version


def bump_version():
    """patch 自增（0.1.0 -> 0.1.1），同步 plugin.yaml 与 package.conf.yaml。"""
    name, version = read_meta()
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    new_version = ".".join(parts)
    plugin_path = KIT / "plugin.yaml"
    text = plugin_path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^version:\s*[\"']?[^\"'\s]+", "version: %s" % new_version, text, count=1)
    plugin_path.write_text(text, encoding="utf-8")
    conf_path = KIT / "package.conf.yaml"
    if conf_path.exists():
        conf_text = conf_path.read_text(encoding="utf-8")
        conf_text = re.sub(r"(?m)^version:\s*[\"']?[^\"'\s]+", 'version: "%s"' % new_version,
                           conf_text, count=1)
        conf_path.write_text(conf_text, encoding="utf-8")
    print("version bumped: %s -> %s" % (version, new_version))
    return name, new_version


def zip_tree(root_name, files, output, compression=zipfile.ZIP_DEFLATED):
    """显式写顶层目录与所有父目录条目（Go 解压器不自动创建父目录，2026-11-02 教训）。"""
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        directory_entries = sorted({"%s/" % root_name, "%s/src/" % root_name})
        for entry in sorted(directory_entries):
            info = zipfile.ZipInfo(entry)
            info.create_system = 3
            info.compress_type = compression
            info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            archive.writestr(info, b"")
        for relative in INCLUDE:
            source = KIT / relative
            data = source.read_bytes()
            info = zipfile.ZipInfo("%s/%s" % (root_name, relative))
            info.create_system = 3
            info.compress_type = compression
            info.external_attr = (stat.S_IFREG | 0o664) << 16
            archive.writestr(info, data)


def main():
    parser = argparse.ArgumentParser(description="打包 vCenter监控 套件")
    parser.add_argument("--no-increment", action="store_true",
                        help="不递增版本号重打同版本（仅离线校验用，禁止交付）")
    parser.add_argument("--out", default=None, help="输出目录（默认 hub/monitor-kits/）")
    args = parser.parse_args()

    if args.no_increment:
        name, version = read_meta()
    else:
        name, version = bump_version()

    output_dir = Path(args.out) if args.out else HUB_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ("监控套件_%s_%s.zip" % (name, version))
    zip_tree(name, INCLUDE, output)
    print("packed: %s" % output)

    validator = Path(__file__).resolve().parent / "validate_monitor_kit.py"
    import subprocess
    result = subprocess.run([sys.executable, str(validator), str(output)],
                            capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stdout.write(result.stderr)
    if result.returncode != 0:
        print("打包后校验失败，禁止交付")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
