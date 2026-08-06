#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSO Provider 生成器

根据 SSO 对接文档和用户参数，生成 EasyOps SSO Adapter 的 Provider 插件代码、
配置文件和对接说明文档。

用法：
    python sso_provider_generator.py --name <provider_name> --output <output_dir> --context <context_json>

    其中 context_json 包含从文档中提取的结构化信息，由调用方（LLM）提供。

注意：此脚本本身由 LLM 调用，context_json 的内容由 LLM 从 SSO 对接文档中分析提取。
"""

import argparse
import json
import os
import sys
import textwrap
import zipfile

from jinja2 import Environment, FileSystemLoader


# Jinja2 模板环境
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')


def _indent(text, indent=8):
    """将多行文本统一缩进

    Args:
        text (str): 多行文本
        indent (int): 缩进空格数

    Returns:
        str: 缩进后的文本
    """
    if not text:
        return ''
    prefix = ' ' * indent
    lines = text.splitlines()
    return '\n'.join(prefix + line if line.strip() else line for line in lines)


def render_template(template_name, context):
    """渲染 Jinja2 模板

    Args:
        template_name (str): 模板文件名
        context (dict): 模板上下文变量

    Returns:
        str: 渲染后的内容
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    return template.render(**context)


def build_provider_context(params):
    """构建 provider 模板上下文

    将 LLM 提取的结构化信息转换为模板所需的上下文变量。

    Args:
        params (dict): LLM 提取的结构化参数

    Returns:
        dict: 模板上下文变量
    """
    protocol_type = params.get('protocol_type', 'custom')
    base_class = params.get('base_class', 'Provider')

    # 自动判断需要的 import
    doc_lower = json.dumps(params).lower()
    needs = {
        'needs_urlencode': 'url' in doc_lower and ('encode' in doc_lower or 'query' in doc_lower),
        'needs_urlparse': 'redirect' in doc_lower or 'urlparse' in doc_lower,
        'needs_time': 'timestamp' in doc_lower or 'time' in doc_lower,
        'needs_hashlib': 'hash' in doc_lower or 'md5' in doc_lower or 'sha' in doc_lower,
        'needs_base64': 'base64' in doc_lower or 'encode' in doc_lower,
        'needs_hmac': 'hmac' in doc_lower or 'sign' in doc_lower,
        'needs_presignin_request': 'post' in params.get('pre_signin_method', 'GET').lower(),
        'needs_redirect_uri_parse': params.get('needs_redirect_uri_parse', False),
    }

    # 配置属性列表
    config_properties = params.get('config_properties', [
        {'name': 'login_url', 'type': 'string'},
        {'name': 'redirect_uri', 'type': 'string'},
    ])

    # 必填配置项
    config_required = params.get('config_required', ['login_url', 'redirect_uri'])

    # 构建上下文
    context = {
        'provider_name': params.get('provider_name', 'demo'),
        'description': params.get('description', ''),
        'protocol_type': protocol_type,
        'base_class': base_class,
        'login_key': params.get('login_key', 'name'),
        'config_properties': config_properties,
        'config_required': config_required,
        'extra_imports': params.get('extra_imports', []),
        # 主逻辑（替换整个方法体）
        'pre_signin_logic': _indent(params.get('pre_signin_logic', '')),
        'signin_logic': _indent(params.get('signin_logic', '')),
        'user_info_logic': _indent(params.get('user_info_logic', '')),
        'sign_out_logic': _indent(params.get('sign_out_logic', '')),
        'sso_global_sign_out_logic': _indent(params.get('sso_global_sign_out_logic', '')),
        # 业务扩展（方法内注入，不替换原有逻辑）
        'user_info_post_logic': _indent(params.get('user_info_post_logic', '')),
        'authorize_post_deal_logic': _indent(params.get('authorize_post_deal_logic', '')),
        'sign_out_pre_logic': _indent(params.get('sign_out_pre_logic', '')),
        # oauth2 方法重写
        'oauth2_overrides': params.get('oauth2_overrides', []),
    }
    context.update(needs)

    return context


def build_setting_context(params):
    """构建配置文件模板上下文

    Args:
        params (dict): LLM 提取的结构化参数

    Returns:
        dict: 模板上下文变量
    """
    config_items = params.get('config_items', [
        {
            'key': 'login_url',
            'value': '"__LOGIN_URL__"',
            'comment': 'SSO 服务端登录地址',
        },
        {
            'key': 'redirect_uri',
            'value': '"__REDIRECT_URI__"',
            'comment': 'EasyOps 回调地址',
        },
    ])

    return {
        'provider_name': params.get('provider_name', 'demo'),
        'config_items': config_items,
    }


def build_doc_context(params):
    """构建对接说明文档模板上下文

    Args:
        params (dict): LLM 提取的结构化参数

    Returns:
        dict: 模板上下文变量
    """
    return {
        'provider_name': params.get('provider_name', 'demo'),
        'sso_name': params.get('sso_name', params.get('provider_name', 'SSO服务')),
        'protocol_type': params.get('protocol_type', 'custom'),
        'config_docs': params.get('config_docs', []),
        'notes': params.get('notes', []),
    }


def generate(params, output_dir):
    """生成 SSO Provider 全部输出物

    根据参数生成 Provider 代码、配置文件、对接说明文档，并打包为 zip。

    Args:
        params (dict): 结构化参数，包含从文档提取的所有信息
        output_dir (str): 输出目录路径

    Returns:
        dict: 生成结果信息，包含生成的文件路径列表
    """
    provider_name = params.get('provider_name', 'demo')
    output_dir = os.path.abspath(output_dir)

    # 创建输出目录结构
    provider_output = os.path.join(output_dir, provider_name + '_sso')
    settings_dir = os.path.join(provider_output, 'settings')
    handlers_dir = os.path.join(provider_output, 'handlers', 'providers', provider_name)

    os.makedirs(settings_dir, exist_ok=True)
    os.makedirs(handlers_dir, exist_ok=True)

    # 构建各模板的上下文
    provider_ctx = build_provider_context(params)
    setting_ctx = build_setting_context(params)
    doc_ctx = build_doc_context(params)

    # 生成 Provider 代码
    provider_code = render_template('provider_template.py.j2', provider_ctx)
    provider_file = os.path.join(handlers_dir, provider_name + '.py')
    with open(provider_file, 'w') as f:
        f.write(provider_code)

    # 生成 __init__.py
    init_file = os.path.join(handlers_dir, '__init__.py')
    with open(init_file, 'w') as f:
        f.write('')

    # 生成配置文件
    setting_code = render_template('setting_custom_template.py.j2', setting_ctx)
    setting_file = os.path.join(settings_dir, 'setting_custom.py')
    with open(setting_file, 'w') as f:
        f.write(setting_code)

    # 生成对接说明文档
    doc_content = render_template('doc_template.md.j2', doc_ctx)
    doc_file = os.path.join(output_dir, provider_name + '_对接说明.md')
    with open(doc_file, 'w') as f:
        f.write(doc_content)

    # 打包为 zip
    zip_file = os.path.join(output_dir, provider_name + '_sso.zip')
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(provider_output):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, provider_output)
                zf.write(file_path, arcname)

    generated_files = [
        provider_file,
        init_file,
        setting_file,
        doc_file,
        zip_file,
    ]

    return {
        'provider_name': provider_name,
        'output_dir': output_dir,
        'generated_files': generated_files,
        'zip_file': zip_file,
    }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='SSO Provider 生成器')
    parser.add_argument('--name', required=True, help='Provider 名称（小写英文）')
    parser.add_argument('--output', required=True, help='输出目录')
    parser.add_argument('--context', required=True, help='上下文 JSON 文件路径或 JSON 字符串')

    args = parser.parse_args()

    # 解析 context
    if os.path.isfile(args.context):
        with open(args.context, 'r') as f:
            params = json.load(f)
    else:
        params = json.loads(args.context)

    # 确保 provider_name 一致
    params['provider_name'] = args.name

    # 生成
    result = generate(params, args.output)

    # 输出结果
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
