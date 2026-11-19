#!/usr/bin/env python3
"""从现网导出 ZIP 构建新版，保持原参数及附属资源，离线执行。"""
import argparse
import io
import stat
import zipfile
from pathlib import Path

VERSION = '0.1.1'
ROOT = 'VMWare扫描/'


def main():
    parser = argparse.ArgumentParser(
        description='从原始导出 ZIP 构建按 businessIp 匹配的 VMWare扫描套件；不访问远端。',
        epilog='示例：python build.py --base original.zip --output CMDB采集套件_VMWare扫描_0.1.1.zip')
    parser.add_argument('--base', type=Path, required=True, help='原始现网导出 ZIP（必填，无默认值）')
    parser.add_argument('--output', type=Path, required=True, help='新版输出 ZIP（必填，无默认值；覆盖同路径）')
    parser.add_argument('--version', action='version', version=VERSION)
    args = parser.parse_args()
    here = Path(__file__).parent
    files = {}
    with zipfile.ZipFile(io.BytesIO(args.base.read_bytes())) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or entry.filename == '/':
                continue
            name = entry.filename
            if name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('源包存在不安全路径')
            files[name] = archive.read(entry)
    assert b'1762419597' in files['plugin.yaml']
    files['plugin.yaml'] = files['plugin.yaml'].replace(b'1762419597', VERSION.encode())
    # 其他引用原版本的配置也要同步，防止包版本元数据不一致。
    if 'package.conf.yaml' in files:
        files['package.conf.yaml'] = files['package.conf.yaml'].replace(b'1762419597', VERSION.encode())
    for suffix in ('py', 'orig'):
        files['src/VMWare_Scan.' + suffix] = (here / ('src/VMWare_Scan.' + suffix)).read_bytes()
    files['导入说明.md'] = (here / 'README.md').read_bytes()
    files['readme'] = files['导入说明.md']
    dirs = {ROOT}
    for name in files:
        parent = Path(name).parent
        while str(parent) != '.':
            dirs.add(ROOT + parent.as_posix() + '/')
            parent = parent.parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(dirs, key=lambda x: (x.count('/'), x)):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
            archive.writestr(info, b'')
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(ROOT + name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o664) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(args.output) as archive:
        seen = set()
        for entry in archive.infolist():
            if entry.filename != ROOT:
                assert str(Path(entry.filename.rstrip('/')).parent) + '/' in seen
            assert stat.S_IMODE(entry.external_attr >> 16) == (0o755 if entry.is_dir() else 0o664)
            assert '__pycache__' not in entry.filename
            seen.add(entry.filename)
        for suffix in ('py', 'orig'):
            compile(archive.read(ROOT + 'src/VMWare_Scan.' + suffix), 'VMWare_Scan.' + suffix, 'exec')
    print('构建及包结构检查通过：%s' % args.output)


if __name__ == '__main__':
    main()
