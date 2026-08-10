#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源采集套件打包脚本（带版本号自动管理）。

功能:
  - 读取插件目录下 .version 文件获取当前版本号
  - 自动递增 patch 版本号（1.0.3 → 1.0.4）
  - 生成带版本号的 zip 文件：{插件名}_v{版本号}.zip
  - 更新 .version 文件

打包引擎:
  使用 Python zipfile 打包，并强制为每个条目设置 UTF-8 flag（bit 11）。
  解决 macOS 系统 zip 命令不设 UTF-8 flag、中文文件名以 CP437 存储，
  导致平台 Go archive/zip 解压乱码、scriptPath 匹配失败、激活报
  "illegal base64 data at input byte 0" 的问题。

  注意：UTF-8 flag 包对 import_plugin 接口正常；update_plugin 接口
  可能报 "not a valid zip file"，此时建议先删除旧插件再重新导入。

用法:
  python3 pack_plugin.py <插件目录路径> [--no-increment]

示例:
  python3 pack_plugin.py ./output/光纤交换机SNMP信息采集
  python3 pack_plugin.py ./output/光纤交换机SNMP信息采集 --no-increment
"""

import argparse
import os
import sys
import zipfile


def read_version(plugin_dir):
    """读取 .version 文件，不存在则返回 '1.0.0'。"""
    version_file = os.path.join(plugin_dir, '.version')
    if os.path.isfile(version_file):
        with open(version_file, 'r') as f:
            return f.read().strip()
    return '1.0.0'


def increment_version(version):
    """递增 patch 版本号。

    Args:
        version: 当前版本号，如 '1.0.3'

    Returns:
        str: 递增后的版本号，如 '1.0.4'
    """
    parts = version.split('.')
    if len(parts) != 3:
        parts = ['1', '0', '0']
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        parts[2] = '1'
    return '.'.join(parts)


def write_version(plugin_dir, version):
    """写入 .version 文件。"""
    version_file = os.path.join(plugin_dir, '.version')
    with open(version_file, 'w') as f:
        f.write(version + '\n')


def pack_plugin(plugin_dir, no_increment=False):
    """打包插件为带版本号的 zip 文件。

    Args:
        plugin_dir: 插件目录路径
        no_increment: 是否跳过版本递增（使用当前版本号）

    Returns:
        tuple: (zip_path, version)
    """
    plugin_dir = os.path.abspath(plugin_dir)
    if not os.path.isdir(plugin_dir):
        print("错误: 目录不存在: {}".format(plugin_dir))
        sys.exit(1)

    plugin_name = os.path.basename(plugin_dir)
    output_dir = os.path.dirname(plugin_dir)

    # 版本管理
    current_version = read_version(plugin_dir)
    if no_increment:
        version = current_version
    else:
        version = increment_version(current_version)
        write_version(plugin_dir, version)

    # 生成 zip 文件名
    zip_filename = "{}_v{}.zip".format(plugin_name, version)
    zip_path = os.path.join(output_dir, zip_filename)

    # 删除旧 zip（同名）
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # 打包：用 Python zipfile 写入，强制 UTF-8 flag，排除 .version 文件
    entries = []
    for root, dirs, files in os.walk(plugin_dir):
        dirs.sort()
        files.sort()
        if '.version' in files:
            files = [f for f in files if f != '.version']
        # 目录条目（保证空目录也被包含，并保持目录优先顺序）
        for d in dirs:
            full_d = os.path.join(root, d)
            arc_d = os.path.relpath(full_d, output_dir) + '/'
            entries.append(('dir', arc_d, b''))
        # 文件条目
        for fname in files:
            full_path = os.path.join(root, fname)
            arc_name = os.path.relpath(full_path, output_dir)
            with open(full_path, 'rb') as f:
                data = f.read()
            entries.append(('file', arc_name, data))

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for kind, arc_name, data in entries:
            info = zipfile.ZipInfo(arc_name)
            info.flag_bits |= 0x800  # 强制 UTF-8 flag，避免中文文件名乱码
            if kind == 'dir':
                info.external_attr = 0o40755 << 16  # 目录权限
                zf.writestr(info, b'')
            else:
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16  # 文件权限
                zf.writestr(info, data)

    print("打包完成: {}".format(zip_path))
    print("版本号: {}".format(version))
    return zip_path, version


def main():
    parser = argparse.ArgumentParser(
        description='资源采集套件打包（带版本号自动管理）')
    parser.add_argument('plugin_dir', help='插件目录路径')
    parser.add_argument('--no-increment', action='store_true',
                        help='不递增版本号，使用当前版本')
    args = parser.parse_args()

    pack_plugin(args.plugin_dir, args.no_increment)


if __name__ == '__main__':
    main()
