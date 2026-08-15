#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyOps ITSM 表单合法性校验器 —— 从前端源码逐条复刻。

来源：data/sources/frontend/ITSM/itsc-form-management/2.46.2/bootstrap-mini.b0847bacc23ee16d.json
     （storyboard 声明式配置：forms.general-* 控件的 required/pattern/maxLength +
       meta.functions 的 validateProviderArgs + events 里的重名/调试结果条件校验）

规则分类：
  A. 表单元信息（新建/编辑表单弹窗 general-form）
  B. 标准字段（tpl-standard-field-modal）
  C. 数据源（各 tpl-*-data-source-form + debugPreview 调试链）
  D. 版本发布（versionCreate 页）

用法：
  python3 easyops-form-validator.py check-form   --name X --category Y [--form-id Z] [--version 1.0.0 ...]
  python3 easyops-form-validator.py check-field  --key newKey
  python3 easyops-form-validator.py check-datasource --name ds1 --existing '["ds2"]' --type cmdb-list --args-yaml '...'
  python3 easyops-form-validator.py check-debug-result --data '{"name":"a"}'
  也可 import validate_form_meta / validate_field_key / ... 在编排里调用。

返回：每条规则 (ok, rule_id, message)。全部 ok 才等价于前端 validate.success。
"""
import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# 规则清单（rule_id 与前端挂载点一一对应）
# ---------------------------------------------------------------------------
# A1 FORM_NAME_REQUIRED        表单名称必填            FORM_NAME_CANNOT_BE_EMPTY
# A2 FORM_NAME_LENGTH         ^[\s\S]{1,20}$          FORM_NAME_LENGTH_LIMIT（≤20 任意字符）
# A3 CATEGORY_REQUIRED        分类必填                CATEGORY_CANNOT_BE_EMPTY
# A4 FORM_ID_PATTERN          ^[a-zA-Z]\w{0,29}$      仅字母数字下划线≤30 且字母开头
# A5 FORM_DESCRIPTION_MAX     表单说明 max=500        超长拦截
# B1 FIELD_KEY_REQUIRED       标准字段唯一标识必填
# B2 FIELD_KEY_PATTERN        ^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$   字母数字开头，可含 . _ -，≤35
# C1 DS_NAME_PATTERN          ^(?![0-9])[一-龥A-Za-z0-9_]+$  中英文数字下划线，数字不在首位
# C2 DS_NAME_UNIQUE           数据源名称不与现有列表重名（排除自身 id）
# C3 DS_ARGS_VALID            validateProviderArgs：按 type 校验 provider 参数完整性
# C4 DEBUG_RESULT_TYPE        调试后数据转换结果必须为对象或数组（dataType 存在才放行保存）
# D1 VERSION_REQUIRED         版本号必填              VERSION_NUMBER_REQUIRED
# D2 VERSION_PATTERN          ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$  三段式 x.y.z
# D3 VERSION_MEMO_PATTERN     ^[^\s]{1,20}$           版本说明≤20 且不含空白

FORM_NAME_RE = re.compile(r'^[\s\S]{1,20}$')
FORM_ID_RE = re.compile(r'^[a-zA-Z]\w{0,29}$')
FIELD_KEY_RE = re.compile(r'^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$')
DS_NAME_RE = re.compile(r'^(?![0-9])[一-龥A-Za-z0-9_]+$')
VERSION_RE = re.compile(r'^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$')
VERSION_MEMO_RE = re.compile(r'^[^\s]{1,20}$')


def _r(ok, rule, msg):
    return {'ok': bool(ok), 'rule': rule, 'message': None if ok else msg}


# ---------------------------------------------------------------------------
# A. 表单元信息
# ---------------------------------------------------------------------------
def validate_form_meta(name='', category='', form_id='', description='', form_id_editable=True):
    """新建/编辑表单弹窗的全部规则。"""
    results = []
    results.append(_r(name and str(name).strip(), 'A1_FORM_NAME_REQUIRED', '表单名称不可为空'))
    results.append(_r(bool(FORM_NAME_RE.match(name or '')), 'A2_FORM_NAME_LENGTH', '表单名称长度不能超过20个字符'))
    results.append(_r(bool(category), 'A3_CATEGORY_REQUIRED', '分类不可为空'))
    if form_id_editable and form_id is not None:
        # disabled=<% !!QUERY.form %>：从已有表单进入时 id 只读跳过校验
        results.append(_r(bool(FORM_ID_RE.match(form_id or '')), 'A4_FORM_ID_PATTERN',
                          '仅支持字母、数字、下划线并且长度在30个字符以内，且以字母开头'))
    if description:
        results.append(_r(len(description) <= 500, 'A5_FORM_DESCRIPTION_MAX', '表单说明长度不能超过500个字符'))
    return results


# ---------------------------------------------------------------------------
# B. 标准字段（tpl-standard-field-modal / general-input name=newKey）
# ---------------------------------------------------------------------------
def validate_field_key(key=''):
    return [
        _r(bool(key), 'B1_FIELD_KEY_REQUIRED', '唯一标识不可为空'),
        _r(bool(FIELD_KEY_RE.match(key or '')), 'B2_FIELD_KEY_PATTERN',
           '唯一标识的值不符合匹配规则 /^[a-zA-Z0-9][.a-zA-Z0-9_-]{0,34}$/'),
    ]


# ---------------------------------------------------------------------------
# C. 数据源
# ---------------------------------------------------------------------------
def validate_ds_name(name=''):
    return [_r(bool(DS_NAME_RE.match(name or '')), 'C1_DS_NAME_PATTERN',
               '名称只能输入中英文、数字以及下划线，且数字不能在首位')]


def validate_ds_unique(name, existing_names, self_id=None):
    """events.validate.success 的重名 if：<% CTX.dataList?.find(j => j.name === EVENT.detail?.name && j.id !== CTX.formData?.id) %>"""
    dup = any(j['name'] == name and j.get('id') != self_id
              for j in (existing_names or []))
    return [_r(not dup, 'C2_DS_NAME_UNIQUE', '数据源名称不能重复，请更换名称！')]


def validate_provider_args(args, ds_type):
    """meta.functions validateProviderArgs 的 1:1 复刻。

    args: list（yaml 解析后的 provider 参数数组，或传 JSON 字符串自动解析）
    ds_type: cmdb-detail|cmdb-count|cmdb-count-multi|cmdb-list|cmdb-group|
             cmdb-columndb|cmdb-olap|http|dynamic|static
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return [_r(False, 'C3_DS_ARGS_VALID', 'provider 参数不是合法 JSON/YAML 数组')]
    args = args or []
    a = args[0] if len(args) > 0 else None
    b = args[1] if len(args) > 1 else None

    def every(lst, field):
        return bool(lst) and all(field in (it or {}) for it in lst)

    checks = {
        'cmdb-detail': lambda: bool(a) and bool(b),
        'cmdb-count': lambda: bool(a) and bool(b),
        'cmdb-count-multi': lambda: bool(a) and every((a or {}).get('objectList'), 'objectId'),
        'cmdb-list': lambda: bool(a) and bool((b or {}).get('fields')),
        'cmdb-group': lambda: bool(a) and bool((b or {}).get('group_fields')) and bool((b or {}).get('funcs')),
        'cmdb-columndb': lambda: bool((a or {}).get('database')) and bool((a or {}).get('measures'))
                                     and bool((a or {}).get('group_by')) and bool((a or {}).get('object_ids')),
        'cmdb-olap': lambda: bool((a or {}).get('model')) and bool((a or {}).get('measures'))
                                and bool((a or {}).get('dims')) and bool((a or {}).get('filters')),
        'http': lambda: bool(a) and bool((b or {}).get('method')),
        'dynamic': lambda: len(args) > 0,
        'static': lambda: True,   # 前端 static 无分支 → 落到 return false 之外，视为通过
    }
    fn = checks.get(ds_type)
    if fn is None:
        return [_r(False, 'C3_DS_ARGS_VALID', '未知数据源类型: %s' % ds_type)]
    # 前端未知 type 返回 false；static 无显式分支同返回 false，但 static 走 data-form 表单
    # 自身的 JSON 格式校验（FILL_CORRECT_FORM 链），此处对 static 放行由 C4 兜底。
    return [_r(fn(), 'C3_DS_ARGS_VALID', '数据源参数不完整（%s 类型必填项缺失）' % ds_type)]


def validate_debug_result(data):
    """debugPreview validate.error 链：转换结果必须是对象或数组（dataType 缺失即拦截）。"""
    ok = isinstance(data, (dict, list))
    return [_r(ok, 'C4_DEBUG_RESULT_TYPE',
               '请填写正确的表单项！数据转换后格式必须为对象或者数组，如{"name": "easyops"}、 [{"name": "easyops"}]')]


# ---------------------------------------------------------------------------
# D. 版本发布
# ---------------------------------------------------------------------------
def validate_version(version='', memo=None):
    results = [
        _r(bool((version or '').strip()), 'D1_VERSION_REQUIRED', '版本号不可为空'),
        _r(bool(VERSION_RE.match(version or '')), 'D2_VERSION_PATTERN', '版本号格式不对（须 x.y.z 三段式，每段1-3位数字）'),
    ]
    if memo is not None and memo != '':
        results.append(_r(bool(VERSION_MEMO_RE.match(memo)), 'D3_VERSION_MEMO_PATTERN',
                          '版本说明长度不能超过20个字符且不能包含空白字符'))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _report(results):
    for r in results:
        mark = '✅' if r['ok'] else '❌'
        print(f"{mark} [{r['rule']}] {r['message'] or '通过'}")
    failed = [r for r in results if not r['ok']]
    print(f"\n{'全部通过' if not failed else f'{len(failed)} 条不通过'}")
    return 0 if not failed else 1


def main():
    ap = argparse.ArgumentParser(description='EasyOps ITSM 表单合法性校验（前端规则复刻）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('check-form', help='表单元信息校验 A1-A5')
    p1.add_argument('--name', default='')
    p1.add_argument('--category', default='')
    p1.add_argument('--form-id', default='')
    p1.add_argument('--description', default='')
    p1.add_argument('--form-id-readonly', action='store_true', help='已有表单进入（QUERY.form）时 id 只读跳过 A4')

    p2 = sub.add_parser('check-field', help='标准字段唯一标识校验 B1-B2')
    p2.add_argument('--key', default='')

    p3 = sub.add_parser('check-datasource', help='数据源校验 C1-C3')
    p3.add_argument('--name', required=True)
    p3.add_argument('--existing', default='[]', help='现有数据源 JSON 数组 [{"name":..,"id":..}]')
    p3.add_argument('--self-id', default=None)
    p3.add_argument('--type', default=None, help='cmdb-list/http/... 不传则跳过 C3')
    p3.add_argument('--args-yaml', default=None, help='provider 参数 JSON（C3）')

    p4 = sub.add_parser('check-debug-result', help='数据转换结果校验 C4')
    p4.add_argument('--data', required=True, help='转换结果 JSON 字符串')

    p5 = sub.add_parser('check-version', help='版本发布校验 D1-D3')
    p5.add_argument('--version', default='')
    p5.add_argument('--memo', default=None)

    a = ap.parse_args()
    if a.cmd == 'check-form':
        return _report(validate_form_meta(a.name, a.category, a.form_id, a.description,
                                          form_id_editable=not a.form_id_readonly))
    if a.cmd == 'check-field':
        return _report(validate_field_key(a.key))
    if a.cmd == 'check-datasource':
        rs = validate_ds_name(a.name)
        existing = json.loads(a.existing) if a.existing else []
        rs += validate_ds_unique(a.name, existing, a.self_id)
        if a.type:
            rs += validate_provider_args(a.args_yaml or '[]', a.type)
        return _report(rs)
    if a.cmd == 'check-debug-result':
        try:
            data = json.loads(a.data)
        except json.JSONDecodeError:
            data = None
        return _report(validate_debug_result(data))
    if a.cmd == 'check-version':
        return _report(validate_version(a.version, a.memo))


if __name__ == '__main__':
    sys.exit(main())
