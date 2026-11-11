#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线构建物理服务器 IPMI 套件；依赖源码须事先下载并验证官方 SHA256。"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tarfile
import zipfile

VERSION = "0.1.2"
NAME = "物理服务器IPMI监控"
BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "monitor-kits" / "physical-ipmi-monitoring"
PARAMS = ("ip", "bmc_ip", "username", "password", "kg", "port", "timeout", "login_timeout", "privilege")
PACKAGES = (("pyghmi", "1.5.61"), ("pyaes", "1.6.1"), ("six", "1.17.0"))
PYGHMI_MODULES = ("__init__.py", "constants.py", "exceptions.py", "ipmi/__init__.py",
                  "ipmi/sdr.py", "ipmi/private/__init__.py", "ipmi/private/session.py",
                  "ipmi/private/util.py", "ipmi/private/constants.py")


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def zip_tree(root, output, prefix="", compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        directories = [root] + sorted(path for path in root.rglob("*") if path.is_dir())
        files = sorted(path for path in root.rglob("*") if path.is_file())
        for path in directories + files:
            relative = path.relative_to(root).as_posix()
            name = "/".join(part for part in (prefix, "" if relative == "." else relative) if part)
            if not name:
                continue
            directory = path.is_dir()
            info = zipfile.ZipInfo(name + "/" if directory else name)
            info.create_system = 3
            info.compress_type = compression
            info.external_attr = ((stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o664)) << 16
            if directory:
                info.external_attr |= 0x10
            archive.writestr(info, b"" if directory else path.read_bytes())


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("[patch_session] 上游片段不唯一，停止构建: " + before[:60])
    return text.replace(before, after, 1)


def patch_session(text):
    for line in ("from cryptography.hazmat.backends import default_backend\n",
                 "from cryptography.hazmat.primitives.ciphers import algorithms\n",
                 "from cryptography.hazmat.primitives.ciphers import modes\n",
                 "    _crypto_backend = default_backend()\n"):
        text = replace_once(text, line, "")
    text = replace_once(text, "from cryptography.hazmat.primitives.ciphers import Cipher",
                        "from pyghmi.ipmi.private.pureaes import encrypt, decrypt")
    text = replace_once(text, '''                crypter = Cipher(
                    algorithm=algorithms.AES(self.aeskey),
                    mode=modes.CBC(iv),
                    backend=self._crypto_backend
                )
                encryptor = crypter.encryptor()
                message += encryptor.update(payloadtocrypt
                                            ) + encryptor.finalize()''',
                        '''                message += encrypt(self.aeskey, iv, payloadtocrypt)''')
    text = replace_once(text, '''                crypter = Cipher(
                    algorithm=algorithms.AES(self.aeskey),
                    mode=modes.CBC(bytes(iv)),
                    backend=self._crypto_backend
                )
                decryptor = crypter.decryptor()
                payload = bytearray(decryptor.update(bytes(payload[16:])
                                                     ) + decryptor.finalize())''',
                        '''                payload = bytearray(decrypt(self.aeskey, bytes(iv), bytes(payload[16:])))''')
    text = replace_once(text, '''        if self.ipmiversion == 1.5:
            if not (data[1] & 0b100):
                self.onlogon(
                    {'error':
                     "MD5 required but not enabled/available on target BMC"})
                return
            self._get_session_challenge()''',
                        '''        if self.ipmiversion == 1.5:
            self.onlogon({'error': 'IPMI 2.0 required; downgrade disabled'})
            return''')
    marker = '\n\nif __name__ == "__main__":\n'
    if text.count(marker) != 1:
        raise ValueError("[patch_session] 无法定位上游示例入口")
    text = text.split(marker, 1)[0] + "\n"
    text = replace_once(text, """    @classmethod
    def pause(cls, timeout):
        try:
            starttime = _monotonic_time()
            while _monotonic_time() - starttime < timeout:
                cls.wait_for_rsp(timeout - (_monotonic_time() - starttime))
        except Exception as e:
            print(repr(e))""", """    @classmethod
    def pause(cls, timeout):
        starttime = _monotonic_time()
        while _monotonic_time() - starttime < timeout:
            cls.wait_for_rsp(timeout - (_monotonic_time() - starttime))""")
    text = replace_once(text, "            print('Password for {0} is somehow malformed'.format(self.bmc))",
                        "            self.onlogon({'error': 'IPMI password encoding error'})")
    return text


def dependencies(cache, build, root):
    common = build / "dependencies"
    common.mkdir(parents=True, exist_ok=True)
    licenses = common / "LICENSES"
    licenses.mkdir(exist_ok=True)
    lock = []
    pinned = json.loads((SOURCE / "build-support/dependencies.lock.json").read_text())
    for name, version in PACKAGES:
        metadata = next(item for item in pinned if item["name"] == name and item["version"] == version)
        source = cache / metadata["filename"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != metadata["digests"]["sha256"]:
            raise ValueError("[dependencies] 源码校验失败: " + name)
        lock.append({"name": name, "version": version, "source_url": metadata["url"],
                     "source_sha256": digest, "distribution": "source-subset" if name == "pyghmi" else "source"})
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if len(parts) < 2 or not member.isfile():
                    continue
                relative = Path(*parts[1:])
                selected = (name == "pyghmi" and relative.as_posix().startswith("pyghmi/")
                            and relative.as_posix()[7:] in PYGHMI_MODULES)
                selected |= name == "pyaes" and relative.parts[0] == "pyaes" and relative.suffix == ".py"
                selected |= name == "six" and relative.as_posix() == "six.py"
                if selected:
                    target = common / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                if relative.name.upper() in ("LICENSE", "LICENSE.TXT", "COPYING", "NOTICE"):
                    (licenses / (name + "-" + relative.name)).write_bytes(archive.extractfile(member).read())
    target = common / "pyghmi/ipmi/private/session.py"
    original = target.read_text()
    patched = patch_session(original)
    target.write_text(patched)
    (root / "third-party").mkdir(exist_ok=True)
    (root / "third-party/pyghmi-pureaes.patch").write_text("".join(difflib.unified_diff(
        original.splitlines(True), patched.splitlines(True), "upstream/session.py", "patched/session.py")))
    shutil.copyfile(SOURCE / "build-support/pureaes.py.in", common / "pyghmi/ipmi/private/pureaes.py")
    dump(root / "third-party/dependencies.lock.json", lock)
    for architecture in ("x86_64", "arm64"):
        directory = root / "vendor" / architecture
        directory.mkdir(parents=True, exist_ok=True)
        bundle = directory / "dependencies.zip"
        zip_tree(common, bundle)
        dump(directory / "manifest.json", {"architecture": architecture, "python": ">=2.7",
             "native_extensions": False, "bundle": "dependencies.zip",
             "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
             "note": "纯Python依赖，两种架构文件相同；无需pip及原生ABI，pyghmi为已记录补丁的只读采集子集"})


def metadata(root):
    fields = [("ip", "CMDB物理机IP", "$.ip", "用于关联物理机，不用作BMC目标"),
              ("bmc_ip", "BMC管理IP", "$.bmc_ip", "从PHYSICAL_SERVER实例属性读取；创建任务时可改为实际CMDB属性路径"),
              ("username", "IPMI用户名", "$.ipmi_username", "从PHYSICAL_SERVER实例属性读取；创建任务时可改为实际CMDB属性路径"),
              ("password", "IPMI密码", "$.ipmi_password", "从PHYSICAL_SERVER实例属性读取；不走平台加密参数"),
              ("kg", "KG密钥", "$.ipmi_kg", "从PHYSICAL_SERVER实例属性读取；可选，不走平台加密参数"),
              ("port", "IPMI UDP端口", "623", "默认623，范围1..65535"),
              ("timeout", "整轮超时秒数", "60", "默认60，范围5..300；另有最多2秒注销"),
              ("login_timeout", "认证预检查超时秒数", "5", "默认5，范围1..30；一次认证尝试，协议重传受此总时限约束"),
              ("privilege", "会话权限", "2", "默认2 USER；若平台拒绝可改3 OPERATOR，禁止ADMIN")]
    lines = ['type: simple-script', 'name: ' + NAME, 'version: "' + VERSION + '"',
             'command:', '    collect:', '        interpreter: ""', '        scriptPath: [src, ipmi_monitor.py]',
             '        type: python', '        user: ""', 'params: ' + json.dumps(list(PARAMS)), 'paramDefine:']
    for key, label, default, description in fields:
        item = {"name": key, "valueType": "string",
                "defaultValue": default, "display": True, "displayName": label, "description": description,
                "use": "collectParams", "optional": key in ("kg", "port", "timeout", "login_timeout", "privilege"),
                "isFromSecret": False, "isEncrypt": False, "extraArgs": None}
        lines.append("    - " + json.dumps(item, ensure_ascii=False))
    lines.extend(['agentType: easyops', 'category: 基础设施.物理资源', 'scriptType: python',
                  'interpreter: ""', 'samplerType: metric_sampler', 'relateObjectId: PHYSICAL_SERVER@ONEMODEL',
                  'memo: "通用IPMI 2.0只读SDR监控；纯Python离线依赖，不含OEM及远程控制功能"', 'icon: null'])
    (root / "plugin.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "package.conf.yaml").write_text('name: ' + NAME + '\nversion: "' + VERSION + '"\n')
    metrics = [("available", "BMC会话可用", "", False, "double"),
               ("power_on", "机箱开机状态", "", False, "double"),
               ("sensor_count", "SDR可读传感器数", "", False, "double"),
               ("error_count", "采集错误数", "", False, "double"),
               ("collect_complete", "本轮完整采集", "", False, "double"),
               ("error", "采集错误摘要", "", False, "string"),
               ("duration_seconds", "采集耗时", "s", False, "double"),
               ("sensor_available", "传感器读数可用", "", True, "double"),
               ("sensor_health", "传感器健康位掩码", "", True, "double"),
               ("temperature_celsius", "摄氏温度", "℃", True, "double"),
               ("temperature_fahrenheit", "华氏温度", "℉", True, "double"),
               ("fan_rpm", "风扇转速", "rpm", True, "double"),
               ("voltage_volts", "电压", "V", True, "double"),
               ("power_watts", "功率", "W", True, "double"),
               ("current_amperes", "电流", "A", True, "double"),
               ("sensor_percent", "传感器百分比", "%", True, "double")]
    origins, aliases = [], []
    for suffix, display, unit, sensor, data_type in metrics:
        key = "physical_ipmi_" + suffix
        dims = ["ip", "bmc_ip"] + (["sensor_id", "sensor_name", "sensor_type"] if sensor else [])
        origins.append({"key": key, "agentType": "easyops", "dataType": data_type,
                        "metricType": "gauge", "labels": dims, "unit": unit,
                        "tagDefine": [{"name": dim, "readOnly": False} for dim in dims]})
        aliases.append({"name": key, "displayName": "物理机IPMI-" + display,
                        "objectId": "PHYSICAL_SERVER@ONEMODEL", "dataType": data_type, "type": "normal",
                        "description": display, "unit": unit, "expression": "",
                        "originalMetrics": [key], "metricSet": ["物理机IPMI-传感器" if sensor else "物理机IPMI-基础"],
                        "dims": [{"dimName": dim, "dimDisplayName": dim, "originDimName": dim,
                                  "isArray": False} for dim in dims]})
    dump(root / "origin_metric.json", origins)
    dump(root / "alias_metric.json", aliases)
    dump(root / "metric_set.json", [{"name": "物理机IPMI-基础"}, {"name": "物理机IPMI-传感器"}])
    shutil.copyfile(SOURCE / "物理服务器IPMI告警规则模板.xlsx", root / "物理服务器IPMI告警规则模板.xlsx")

def build(cache, output):
    root = output / NAME
    if root.exists():
        raise ValueError("[build] 输出目录已存在，请使用新的构建目录，防止混入旧文件")
    (root / "src").mkdir(parents=True)
    metadata(root)
    original = (SOURCE / "src/ipmi_monitor.orig").read_text(encoding="utf-8")
    header, encoding, body = original.split("\n", 2)
    prefix = "import os\n" + "".join('%s = os.environ.get("EASYOPS_COLLECTOR_%s")\n' % (key, key) for key in PARAMS)
    (root / "src/ipmi_monitor.py").write_text(header + "\n" + encoding + "\n" + prefix + body, encoding="utf-8")
    (root / "src/ipmi_monitor.orig").write_text(original, encoding="utf-8")
    shutil.copyfile(SOURCE / "readme", root / "readme")
    dependencies(cache, output, root)
    archive = output / ("监控套件_物理服务器IPMI监控_" + VERSION + ".zip")
    zip_tree(root, archive, NAME, compression=zipfile.ZIP_STORED)
    print(archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, epilog="示例：python3 build_ipmi_monitor_kit.py --cache <源码缓存> --output <新构建目录>；不联网，不操作平台。失败退出非0。")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--cache", type=Path, required=True, help="包含锁定版本源码tar.gz的目录；无默认值")
    parser.add_argument("--output", type=Path, required=True, help="全新构建目录；禁止复用旧套件子目录，无默认值")
    args = parser.parse_args()
    build(args.cache, args.output)
