#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源采集套件脚手架生成脚本。

根据参数自动创建 EasyOps 资源信息采集插件的完整目录结构和配置文件。

用法:
    python generate_scaffold.py \
        --name "插件名称" \
        --model-id "MODEL_ID" \
        --script-name "ScriptName" \
        --params 'params定义JSON' \
        --output-dir "./output"
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

import yaml


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description='生成资源采集套件脚手架')
    parser.add_argument('--name', required=True, help='插件名称，如 "交换机SNMP信息采集"')
    parser.add_argument('--model-id', required=True, help='关联 CMDB 模型 ID，如 PHYSICAL_SERVER@ONEMODEL')
    parser.add_argument('--model-json', default=None, help='模型 JSON 文件路径（可选，将复制到插件目录）')
    parser.add_argument('--script-name', required=True, help='脚本名（大驼峰），如 Physical_Server_Config_Info')
    parser.add_argument('--category', default='自定义', help='插件分类（默认：自定义）')
    parser.add_argument('--memo', default='', help='插件描述')
    parser.add_argument('--install-path', default=None, help='安装路径（默认取 script-name 的小写下划线形式）')
    parser.add_argument('--params', required=True,
                        help='参数定义 JSON 字符串或文件路径。'
                             '格式: [{"name":"ip","defaultValue":"$.ip","isFromSecret":false,'
                             '"displayName":"IP地址","description":"目标IP","display":true,'
                             '"valueType":"string","optional":false,"isEncrypt":false}]')
    parser.add_argument('--discovery-models', default=None,
                        help='资源发现模型列表 JSON。'
                             '格式: [{"objectId":"MODEL_ID","category":"分类","type":"TYPE_ID"}]')
    parser.add_argument('--output-dir', default='./output', help='输出目录（默认：./output）')
    parser.add_argument('--collect-agent', default=None,
                        help='采集 agent 字段（如 $.ip），默认不设置')
    parser.add_argument('--group', default=None,
                        help='分组标签 JSON 数组，如 ["remoteScan","cloudTypePrivateCloud"]')
    return parser.parse_args()


def load_params(params_input):
    """
    加载参数定义。

    Args:
        params_input: JSON 字符串或文件路径

    Returns:
        list: 参数定义列表
    """
    # 尝试作为文件路径读取
    if os.path.isfile(params_input):
        with open(params_input, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 直接解析 JSON
    return json.loads(params_input)


def generate_plugin_yaml(name, model_id, script_name, params, category, memo,
                         install_path, collect_agent, group):
    """
    生成 plugin.yaml 内容。

    Args:
        name: 插件名称
        model_id: 关联模型 ID
        script_name: 脚本名
        params: 参数定义列表
        category: 分类
        memo: 描述
        install_path: 安装路径
        collect_agent: 采集 agent
        group: 分组标签列表

    Returns:
        str: YAML 内容
    """
    param_names = [p['name'] for p in params]
    param_defines = []
    for p in params:
        param_defines.append({
            'name': p['name'],
            'valueType': p.get('valueType', 'string'),
            'defaultValue': p.get('defaultValue', ''),
            'display': p.get('display', True),
            'displayName': p.get('displayName', p['name']),
            'description': p.get('description', ''),
            'use': 'collectParams',
            'optional': p.get('optional', False),
            'isFromSecret': p.get('isFromSecret', False),
            'isEncrypt': p.get('isEncrypt', False),
            'extraArgs': None,
        })

    plugin = {
        'type': 'simple-script',
        'name': name,
        'version': str(int(time.time())),
        'command': {
            'collect': {
                'interpreter': '',
                'scriptPath': ['src', '{}.py'.format(script_name)],
                'type': 'python',
                'user': '',
            }
        },
        'params': param_names,
        'paramDefine': param_defines,
        'agentType': 'easyops',
        'category': category,
        'scriptType': 'python',
        'interpreter': '',
        'memo': memo,
        'icon': None,
        'relateObjectId': model_id,
        'installPath': install_path,
        'samplerType': 'process_sampler',
        'jobFilter': None,
        'protected': False,
        'noPackage': False,
        'collectType': [],
        'collectAgent': collect_agent or '',
        'group': group or [],
        'rating': 0,
        'metricbeatName': '',
        'processors': [],
        'extInfo': None,
    }

    return yaml.dump(plugin, default_flow_style=False, allow_unicode=True, sort_keys=False)


def generate_package_conf_yaml():
    """生成 package.conf.yaml 内容（固定模板）。"""
    return """---
proc_list: []
port_list: []
proc_guard: ~
port_guard: ~
start_script: ""
stop_script: ""
monitor_script: ""
user: ""
restart_script: ""
install_prescript: ""
install_postscript: ""
update_prescript: ""
update_postscript: ""
rollback_prescript: ""
rollback_postscript: ""
user_pre_check: ""
user_check_script: ""
...
"""


def generate_resource_discovery_define(model_id, discovery_models):
    """
    生成 resource_discovery_define.json 内容。

    Args:
        model_id: 主模型 ID
        discovery_models: 资源发现模型列表

    Returns:
        str: JSON 内容
    """
    if not discovery_models:
        # 默认只包含主模型
        discovery_models = [{
            'objectId': model_id,
            'category': '基础设施',
            'type': 'BASE_ASSET@ONEMODEL',
        }]
    return json.dumps(discovery_models, ensure_ascii=False, indent=2)


def generate_readme_template(name, model_id, params):
    """
    生成 readme 模板。

    Args:
        name: 插件名称
        model_id: 关联模型 ID
        params: 参数定义列表

    Returns:
        str: readme 内容
    """
    # 构建参数表格
    param_rows = []
    for p in params:
        default_val = p.get('defaultValue', '')
        if default_val.startswith('$.'):
            remark = '从 CMDB 实例自动获取，不要修改'
        elif p.get('isFromSecret', False):
            remark = '密钥管理获取'
        else:
            remark = ''
        param_rows.append('| {} | {} | {} | {} |'.format(
            p.get('displayName', p['name']),
            p.get('description', p['name']),
            default_val,
            remark,
        ))

    param_table_header = '| 参数名称 | 参数说明 | 参数默认值 | 备注 |\n|------|------|------|------|\n'
    param_table = param_table_header + '\n'.join(param_rows)

    template = """## 一、简介
{memo}

适用模型：

| 模型 | 字段 |
| -- | -- |
| {model_id} | TODO: 补充字段说明 |

采集参数：

{param_table}


## 二、前置配置
### 1. 网络策略
| 源 | 目标 | 备注 |
|------|------|------|
| 采集机器IP | 目标地址 | TODO: 补充说明 |

### 2. 确认配置正确
TODO: 补充验证命令


## 三、问题排查
具体看上一个章节【确认配置正确】
""".format(
        memo='{memo}',
        model_id=model_id,
        param_table=param_table,
    )
    return template


def generate_orig_script(name, script_name, params):
    """
    生成 .orig 脚本模板（不含环境变量获取）。

    Args:
        name: 插件名称
        script_name: 脚本名
        params: 参数定义列表

    Returns:
        str: .orig 脚本内容
    """
    return """#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
# tool_name: {name}
from __future__ import print_function

import os
import sys
import json
import logging
import warnings

warnings.filterwarnings("ignore")
reload(sys)
sys.setdefaultencoding('utf8')

# 日志初始化
current_dir = os.path.dirname(os.path.abspath(__file__))
_SAMPLER_SCRIPTS = os.path.normpath(os.path.join(current_dir, '..', '..', '..', 'easy_process_sampler', 'scripts'))
if _SAMPLER_SCRIPTS not in sys.path:
    sys.path.insert(0, _SAMPLER_SCRIPTS)

FORMAT = '[%(asctime)s (line:%(lineno)d) %(levelname)s] %(message)s'
logging.basicConfig(level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S', format=FORMAT)

# TODO: 在此编写采集逻辑
# 参数通过函数参数或直接赋值（调试用）传入


if __name__ == "__main__":
    # TODO: 采集逻辑入口
    data = []

    # 输出采集结果
    print("-----BEGIN GATHERING DATA-----")
    print(json.dumps(data, indent=4))
    print("-----END GATHERING DATA-----")
""".format(name=name)


def generate_py_script(name, script_name, params):
    """
    生成 .py 运行时脚本（含环境变量获取）。

    Args:
        name: 插件名称
        script_name: 脚本名
        params: 参数定义列表

    Returns:
        str: .py 脚本内容
    """
    # 生成环境变量读取代码
    env_lines = []
    for p in params:
        param_name = p['name']
        var_name = _param_name_to_var(param_name)
        env_var = 'EASYOPS_COLLECTOR_{}'.format(param_name)
        env_lines.append('{var} = os.environ.get("{env}")'.format(var=var_name, env=env_var))

    env_block = '\n'.join(env_lines)

    return """#!/usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
# tool_name: {name}
from __future__ import print_function
import os

{env_block}
import sys
import json
import logging
import warnings

warnings.filterwarnings("ignore")
reload(sys)
sys.setdefaultencoding('utf8')

# 日志初始化
current_dir = os.path.dirname(os.path.abspath(__file__))
_SAMPLER_SCRIPTS = os.path.normpath(os.path.join(current_dir, '..', '..', '..', 'easy_process_sampler', 'scripts'))
if _SAMPLER_SCRIPTS not in sys.path:
    sys.path.insert(0, _SAMPLER_SCRIPTS)


FORMAT = '[%(asctime)s (line:%(lineno)d) %(levelname)s] %(message)s'
logging.basicConfig(level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S', format=FORMAT)

# TODO: 在此编写采集逻辑


if __name__ == "__main__":
    # TODO: 采集逻辑入口
    data = []

    # 输出采集结果
    print("-----BEGIN GATHERING DATA-----")
    print(json.dumps(data, indent=4))
    print("-----END GATHERING DATA-----")
""".format(name=name, env_block=env_block)


def _param_name_to_var(param_name):
    """将参数名转换为 Python 变量名（如 ignoreFields -> ignore_fields）。"""
    import re
    # 驼峰转下划线
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', param_name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def main():
    """主函数：创建脚手架目录和文件。"""
    args = parse_args()

    # 加载参数定义
    params = load_params(args.params)

    # 加载资源发现模型
    discovery_models = None
    if args.discovery_models:
        if os.path.isfile(args.discovery_models):
            with open(args.discovery_models, 'r', encoding='utf-8') as f:
                discovery_models = json.load(f)
        else:
            discovery_models = json.loads(args.discovery_models)

    # 安装路径：脚本名小写，压缩连续下划线
    install_path = args.install_path or re.sub(r'_+', '_', args.script_name.lower())

    # 分组标签
    group = None
    if args.group:
        group = json.loads(args.group) if isinstance(args.group, str) else args.group

    # 创建插件目录
    plugin_dir = os.path.join(args.output_dir, args.name)
    src_dir = os.path.join(plugin_dir, 'src')

    # 创建目录
    os.makedirs(src_dir, exist_ok=True)
    for d in ['alertRule', 'dashboard', 'pic']:
        os.makedirs(os.path.join(plugin_dir, d), exist_ok=True)

    # 生成 plugin.yaml
    plugin_yaml = generate_plugin_yaml(
        args.name, args.model_id, args.script_name, params,
        args.category, args.memo, install_path, args.collect_agent, group
    )
    with open(os.path.join(plugin_dir, 'plugin.yaml'), 'w', encoding='utf-8') as f:
        f.write(plugin_yaml)

    # 生成 package.conf.yaml
    with open(os.path.join(plugin_dir, 'package.conf.yaml'), 'w', encoding='utf-8') as f:
        f.write(generate_package_conf_yaml())

    # 生成 origin_metric.json（空数组）
    with open(os.path.join(plugin_dir, 'origin_metric.json'), 'w', encoding='utf-8') as f:
        f.write('[]')

    # 生成 resource_discovery_define.json
    discovery_json = generate_resource_discovery_define(args.model_id, discovery_models)
    with open(os.path.join(plugin_dir, 'resource_discovery_define.json'), 'w', encoding='utf-8') as f:
        f.write(discovery_json)

    # 复制模型 JSON
    if args.model_json and os.path.isfile(args.model_json):
        model_json_name = os.path.basename(args.model_json)
        shutil.copy2(args.model_json, os.path.join(plugin_dir, model_json_name))

    # 生成 readme
    readme = generate_readme_template(args.name, args.model_id, params)
    with open(os.path.join(plugin_dir, 'readme'), 'w', encoding='utf-8') as f:
        f.write(readme)

    # 生成采集脚本
    orig_content = generate_orig_script(args.name, args.script_name, params)
    py_content = generate_py_script(args.name, args.script_name, params)

    with open(os.path.join(src_dir, '{}.orig'.format(args.script_name)), 'w', encoding='utf-8') as f:
        f.write(orig_content)

    with open(os.path.join(src_dir, '{}.py'.format(args.script_name)), 'w', encoding='utf-8') as f:
        f.write(py_content)

    # 输出结果
    print('脚手架生成完成: {}'.format(plugin_dir))
    print()
    print('目录结构:')
    for root, dirs, files in os.walk(plugin_dir):
        level = root.replace(plugin_dir, '').count(os.sep)
        indent = '  ' * level
        print('{}{}/'.format(indent, os.path.basename(root)))
        sub_indent = '  ' * (level + 1)
        for f in sorted(files):
            print('{}{}'.format(sub_indent, f))

    print()
    print('后续步骤:')
    print('1. 根据模型属性和 API 文档，完善 src/{}.orig 采集逻辑'.format(args.script_name))
    print('2. 同步更新 src/{}.py 的采集逻辑'.format(args.script_name))
    print('3. 完善 readme 使用说明')
    print('4. 进行采集测试')
    print('5. 打包为 zip: cd {} && zip -r {}.zip {}/'.format(
        args.output_dir, args.name, args.name))


if __name__ == '__main__':
    main()
