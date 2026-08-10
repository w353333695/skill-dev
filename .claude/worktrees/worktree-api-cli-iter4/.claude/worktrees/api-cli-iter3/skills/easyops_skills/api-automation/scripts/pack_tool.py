#!/usr/bin/env python3
"""
工具包打包脚本

将生成的脚本和配置文件打包成 tar.gz 格式的工具包。

使用方法:
    python pack_tool.py --name "工具名称" --script "脚本路径" --config "配置文件路径" [--output "输出目录"]

示例:
    python pack_tool.py --name "OCP数据采集" --script "./ocp_collector.py" --config "./ocp_config.json" --output "./"
"""

import argparse
import hashlib
import json
import os
import tarfile
import time
import tempfile
import shutil


def generate_hash():
    """生成 32 位十六进制哈希码"""
    return hashlib.md5(str(time.time()).encode()).hexdigest()


def build_package_dat(name, memo=""):
    """
    生成 ._easyPackageConfig.dat 内容

    :param name: 工具名称
    :param memo: 工具说明
    :return: JSON 字符串
    """
    package_id = generate_hash()
    dat = {
        "package": {
            "authUsers": None,
            "cId": "1",
            "category": "自动采集",
            "conf": None,
            "disable": False,
            "icon": "wrench",
            "installPath": None,
            "memo": memo or name,
            "name": name,
            "packageId": package_id,
            "platform": "linux",
            "repoId": "1",
            "source": "none",
            "style": "default",
            "type": "3"
        },
        "version": {
            "conf": "",
            "memo": "none",
            "name": str(int(time.time())),
            "packageId": package_id,
            "sign": "",
            "source": "",
            "sourceType": "",
            "versionId": generate_hash()
        }
    }
    return json.dumps(dat, ensure_ascii=False, separators=(',', ':'))


def build_config(script_path, extra_inputs=None, version="1.0.0", desc=""):
    """
    根据脚本内容构建 config 配置

    :param script_path: 脚本文件路径
    :param extra_inputs: 额外的 inputs 参数列表
    :param version: 版本号
    :param desc: 版本说明
    :return: config 字典
    """
    config = {
        "batchStrategy": None,
        "blackList": [],
        "containerSandbox": {
            "enable": False,
            "image": ""
        },
        "defaultAgents": [],
        "defaultExecUser": "root",
        "deleteAuthorizers": [],
        "envLinux": None,
        "envWindows": None,
        "execPreAuth": None,
        "execTimeWindowConfig": [],
        "execUser": "",
        "executeAuthorizers": [],
        "forceShutdown": False,
        "functionType": "",
        "inputs": [
            {
                "name": "@agents",
                "type": "cmdbInstances",
                "memo": "",
                "cmdbAttrId": "ip",
                "cmdbObjectId": "HOST",
                "cascade": False,
                "label": "执行目标",
                "multiple": True,
                "required": True,
                "primitive": False
            }
        ],
        "level": 0,
        "listVisible": True,
        "lockAgents": "",
        "outputDefs": [],
        "readAuthorizers": [],
        "readExecutionResultAuthorizers": [],
        "readOnly": False,
        "rootExecuteAuthorizers": [],
        "rootModifyAuthorizers": [],
        "sandboxRun": False,
        "systemHide": False,
        "tableDefs": [],
        "tags": [],
        "templateType": "",
        "timeout": 86400,
        "toolLibs": [],
        "type": "python",
        "updateAuthorizers": [],
        "vDesc": desc,
        "vId": generate_hash(),
        "vName": version,
        "whiteList": [],
        "windowsDefaultExecUser": "System",
        "windowsOnlyActiveSession": False,
        "windowsSession": False
    }

    if extra_inputs:
        config["inputs"].extend(extra_inputs)

    return config


def pack_tool(name, script_path, config_data, output_dir=".", memo=""):
    """
    打包工具为 tar.gz

    :param name: 工具名称
    :param script_path: 脚本文件路径
    :param config_data: config 字典或 JSON 文件路径
    :param output_dir: 输出目录
    :param memo: 工具说明
    :return: 打包后的文件路径
    """
    # 创建临时目录
    tmp_dir = tempfile.mkdtemp()
    tool_dir = os.path.join(tmp_dir, name)
    os.makedirs(tool_dir)

    try:
        # 生成 ._easyPackageConfig.dat
        dat_content = build_package_dat(name, memo=memo)
        with open(os.path.join(tool_dir, "._easyPackageConfig.dat"), 'w', encoding='utf-8') as f:
            f.write(dat_content)

        # 复制脚本为 script（无扩展名）
        shutil.copy2(script_path, os.path.join(tool_dir, "script"))

        # 写入 config（无扩展名）
        if isinstance(config_data, dict):
            config_content = json.dumps(config_data, ensure_ascii=False, separators=(',', ':'))
        elif isinstance(config_data, str) and os.path.isfile(config_data):
            with open(config_data, 'r', encoding='utf-8') as f:
                try:
                    config_content = json.dumps(json.loads(f.read()), ensure_ascii=False, separators=(',', ':'))
                except json.JSONDecodeError:
                    config_content = f.read()
        else:
            config_content = config_data

        with open(os.path.join(tool_dir, "config"), 'w', encoding='utf-8') as f:
            f.write(config_content)

        # 打包为 tar.gz（只打包文件，不包含目录条目）
        output_path = os.path.join(output_dir, f"{name}.tar.gz")
        with tarfile.open(output_path, "w:gz") as tar:
            for filename in ["._easyPackageConfig.dat", "config", "script"]:
                filepath = os.path.join(tool_dir, filename)
                tar.add(filepath, arcname=f"{name}/{filename}")

        print(f"打包完成: {output_path}")
        return output_path

    finally:
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="工具包打包")
    parser.add_argument("--name", required=True, help="工具名称")
    parser.add_argument("--script", required=True, help="脚本文件路径")
    parser.add_argument("--config", help="配置文件路径（JSON），不提供则自动生成")
    parser.add_argument("--output", default=".", help="输出目录")
    parser.add_argument("--version", default="1.0.0", help="版本号")
    parser.add_argument("--desc", default="", help="版本说明")
    parser.add_argument("--memo", default="", help="工具说明")

    args = parser.parse_args()

    # 生成基础配置
    base_config = build_config(args.script, version=args.version, desc=args.desc)

    if args.config:
        # 读取用户配置并合并
        with open(args.config, 'r', encoding='utf-8') as f:
            user_config = json.load(f)

        # 如果用户配置只包含 inputs，则合并到基础配置
        if "inputs" in user_config and "type" not in user_config:
            # 用户只提供了简化配置，合并 inputs
            extra_inputs = [inp for inp in user_config.get("inputs", []) if inp.get("name") != "@agents"]
            base_config["inputs"].extend(extra_inputs)
            # 使用用户配置的其他字段
            for key in ["name", "description", "memo"]:
                if key in user_config:
                    base_config[key] = user_config[key]
            config_data = base_config
        else:
            # 用户提供了完整配置，确保必要字段存在
            if "type" not in user_config:
                user_config["type"] = "python"
            config_data = user_config

        pack_tool(args.name, args.script, config_data, args.output, memo=args.memo)
    else:
        pack_tool(args.name, args.script, base_config, args.output, memo=args.memo)
