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
# E. 设计器保存链（反编译自运行中前端包 bricks/itsc-form-management/1.100.7，2026-08-15 实拉）
#    getFormData 三层：validateSection（容器）→ validateField（控件，跳过 cmdb实例操作容器）→ validateAllForm
#    E-S1 表单内容非空           CANNOT_SAVE_AN_EMPTY_FORM         容器列表为空
#    E-S2 容器标题必填非空白     CONTROL_TITLE_CANNOT_BE_EMPTY     name 空/trim 空报；纯空格≠空但仍走长度
#    E-S3 容器标题≤20           CONTROL_TITLE_LENGTH_EXCEEDS_20   name.length>20（trim 非空前提下）
#    E-S4 容器 id 必填           CONTAINER_ID_CANNOT_BE_EMPTY      modelField 空/trim 空
#    E-S5 容器 id 格式           CONTAINER_ID_NOT_VALID            ^(?![0-9]+$)[a-zA-Z0-9_@]+$（非纯数字）
#    E-S6 容器 id 唯一           CONTAINER_ID_MUST_BE_UNIQUE       跨容器 modelField Set 查重
#    E-S7 容器事件触发对象非空   TRIGGER_OBJECT_FOR_CONTAINER_EVENT_CANNOT_BE_EMPTY（listenStart 时）
#    E-S8 容器事件脚本非空       SCRIPT_FOR_CONTAINER_EVENT_CANNOT_BE_EMPTY（listenEvents[0].remoteFunc.toolId）
#    E-S9 SLA 计算字段非空       FIELDS_PARTICIPATING_IN_CONTAINER_EVENT_CALCULATION_CANNOT_BE_EMPTY（enableSlaCale 时）
#    E-S10 table 容器禁多模型    TABLE_NOT_SUPPORT_CMDB_MULTI_MODEL（含 isMoreModel 的 CMDBINSTANCESELECT）
#    E-S11 cmdb操作容器须模型    CMDB_OPERATE_CONTAINER_NO_MODEL_ID
#    E-S12 cmdb操作容器须展示列  CMDB_OPERATE_CONTAINER_NO_SHOW_FIELDS（options.frontKey 非空）
#    E-F1 字段标题必填           FIELD_TITLE_CANNOT_BE_EMPTY       label 空/trim 空
#    E-F2 字段标题≤20           FIELD_TITLE_LENGTH_CANNOT_EXCEED_20（用户 2026-08-15 前端实测命中）
#    E-F3 字段 id 必填           FIELD_ID_CANNOT_BE_EMPTY
#    E-F4 字段 id 格式           FIELD_ID_NOT_VALID                ^(?![0-9]+$)[a-zA-Z0-9_@]+$
#    E-F5 字段 id 唯一           FIELD_ID_MUST_BE_UNIQUE（同容器内 propertys Set 查重）
#    E-F6 MODALSELECT 须事件脚本 EVENT_SCRIPT_IS_REQUIRED（remoteFunc.toolId）
#    E-F7 脚本必填入参有值       THE_VALUE_OF_INPUT_PARAMETER_IS_REQUIRED（scriptInputs[].required&&!scriptValue）
#    E-F8 CMDBINSTANCESELECT 排序字段至多1个 ONLY_ONE_SORT_FIELD_IS_ALLOWED（sort.sort.length>1）
#    E-F9 单排序字段须选字段     NO_SORT_FIELD_SELECTED（sort[0].field 空）
#    E-P1 属性面板标题规则        （validateAllForm schema 驱动：必填/空格/≤20，同 E-S2/S3 语义）
#    E-P2 Tab 页签至少一个       TAB_PANE_AT_LEAST_ONE（tabs 容器 tabPanes 数组非空）
#    E-P3 Tab 页签标题1-128非空字符 TAB_PANE_TITLE_CHAR_LIMIT（每项 tab 匹配 ^\S{1,128}$）
#    ⚠️后端不拦以上任何一条（2026-08-15 探针实测：label>20/modelField 重复/空 等全部 code=0 放行）——
#    纯前端校验，绕过前端直调 API 时须自跑本校验器兜底。

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
# E. 设计器保存链（validateSection + validateField + 属性面板）——1:1 复刻
# ---------------------------------------------------------------------------
ID_RE = re.compile(r'^(?![0-9]+$)[a-zA-Z0-9_@]+$')   # 字段/容器 id：非纯数字，仅字母数字_@
TAB_PANE_RE = re.compile(r'^\S{1,128}$')             # Tab 页签标题：1-128 个非空字符


def _walk_controls(container):
    """容器的控件平铺：普通容器 propertys；tabs 容器各 tabPanes 的 propertys。"""
    props = list(container.get('propertys') or [])
    for pane in container.get('tabPanes') or []:
        props += pane.get('propertys') or []
    return props


def validate_designer_form(form_definition):
    """设计器保存链全量校验（getFormData 三层的静态可测部分）。

    form_definition: []Container（或 JSON 字符串自动解析）。
    返回 (results, errors)——errors 非空等价于前端保存被拦。
    """
    if isinstance(form_definition, str):
        try:
            form_definition = json.loads(form_definition)
        except json.JSONDecodeError:
            return ([_r(False, 'E_FORM_DEFINITION_PARSE', 'formDefinition 不是合法 JSON')], True)

    results, has_err = [], [False]

    def add(ok, rule, msg, ctx=None):
        if not ok:
            has_err[0] = True
            suffix = '（%s）' % ctx if ctx else ''
            results.append(_r(False, rule, msg + suffix))
        else:
            results.append(_r(True, rule, None))

    # ===== validateSection：容器层 =====
    containers = form_definition or []
    add(bool(containers), 'E-S1_FORM_NOT_EMPTY', '表单内容为空无法保存')
    seen_cids = set()
    for c in containers:
        name, cid = c.get('name') or '', c.get('modelField') or ''
        ctx = '%s' % name
        add(bool(name and name.strip()), 'E-S2_CONTAINER_TITLE_REQUIRED', '容器标题不能为空', ctx)
        if name and name.strip():
            add(len(name) <= 20, 'E-S3_CONTAINER_TITLE_LENGTH', '容器标题长度不能超过20个字符', ctx)
        add(bool(cid and cid.strip()), 'E-S4_CONTAINER_ID_REQUIRED', '容器id不能为空', ctx)
        if cid and cid.strip():
            add(bool(ID_RE.match(cid)), 'E-S5_CONTAINER_ID_PATTERN', '容器id不能为纯数字,不能包含@_外的特殊字符', ctx)
        if cid:
            add(cid not in seen_cids, 'E-S6_CONTAINER_ID_UNIQUE', '容器id不能重复', ctx)
            seen_cids.add(cid)
        opts = c.get('options') or {}
        if opts.get('listenStart'):
            le = (opts.get('listenEvents') or [{}])[0]
            add(bool(le.get('componentList')), 'E-S7_CONTAINER_EVENT_TARGET', '容器事件设置触发对象不能为空', ctx)
            add(bool(((le.get('remoteFunc') or {}).get('toolId'))), 'E-S8_CONTAINER_EVENT_SCRIPT', '容器事件设置脚本不能为空', ctx)
        if opts.get('enableSlaCale'):
            add(bool(opts.get('slaCaleFields')), 'E-S9_SLA_CALC_FIELDS', '容器事件设置参与计算的字段不能为空', ctx)
        ctype = (c.get('type') or '').upper()
        props = _walk_controls(c)
        if ctype == 'TABLE':
            multi = any((p.get('options') or {}).get('extraProps', {}).get('isMoreModel')
                        if p.get('type') == 'CMDBINSTANCESELECT' else False for p in props)
            add(not multi, 'E-S10_TABLE_NO_MULTI_MODEL', 'table容器不支持cmdb多模型选择', ctx)
        if ctype in ('CMDB_INSTANCE_OPERATE_CONTAINER',):
            add(bool((c.get('extraProps') or {}).get('cmdbInstanceChangeModel', {}).get('objectId')),
                'E-S11_CMDB_OP_CONTAINER_MODEL', 'cmdb实例操作容器缺少模型id', ctx)
            add(bool(opts.get('frontKey')), 'E-S12_CMDB_OP_CONTAINER_FIELDS', 'cmdb实例操作容器缺少展示字段', ctx)
        # tabs 容器：页签规则（属性面板，同链路）
        if ctype == 'TABS':
            panes = c.get('tabPanes') or []
            add(bool(panes), 'E-P2_TAB_PANE_AT_LEAST_ONE', 'Tab页签至少填写一个', ctx)
            tabs = [p.get('tab') for p in panes]
            ok = all(isinstance(t, str) and TAB_PANE_RE.match(t) for t in tabs)
            add(ok, 'E-P3_TAB_PANE_TITLE', 'Tab页签标题只能使用1至128个非空字符', ctx)

    # ===== validateField：控件层（前端跳过 cmdb实例操作容器）=====
    checked = [c for c in containers if (c.get('type') or '').upper() != 'CMDB_INSTANCE_OPERATE_CONTAINER']
    for c in checked:
        for p in _walk_controls(c):
            label, mf = p.get('label') or '', p.get('modelField') or ''
            ctx = '%s' % label
            add(bool(label and label.strip()), 'E-F1_FIELD_TITLE_REQUIRED', '字段标题不能为空', ctx)
            if label and label.strip():
                add(len(label) <= 20, 'E-F2_FIELD_TITLE_LENGTH', '字段标题长度不能超过20个字符', ctx)
            add(bool(mf and mf.strip()), 'E-F3_FIELD_ID_REQUIRED', '字段id不能为空', ctx)
            if mf and mf.strip():
                add(bool(ID_RE.match(mf)), 'E-F4_FIELD_ID_PATTERN', '字段id不能为纯数字,不能包含@_外的特殊字符', ctx)
    # 字段 id 唯一（前端逐容器 Set；跨容器不查——按容器分桶复刻）
    for c in checked:
        seen = set()
        for p in _walk_controls(c):
            mf = p.get('modelField') or ''
            if not mf:
                continue
            add(mf not in seen, 'E-F5_FIELD_ID_UNIQUE', '控件字段id不能重复', '%s/%s' % (c.get('name'), mf))
            seen.add(mf)
    # 控件类型特有规则
    for c in checked:
        for p in _walk_controls(c):
            opts = p.get('options') or {}
            ctx = '%s' % (p.get('label') or '')
            if p.get('type') == 'MODALSELECT':
                add(bool((opts.get('remoteFunc') or {}).get('toolId')), 'E-F6_MODALSELECT_SCRIPT',
                    '弹框选择控件必须配置事件脚本', ctx)
                for si in (opts.get('remoteFunc') or {}).get('scriptInputs') or []:
                    if si.get('required') and not si.get('scriptValue'):
                        add(False, 'E-F7_SCRIPT_INPUT_REQUIRED',
                            '输入参数【%s】的值不能为空' % si.get('name'), ctx)
            if p.get('type') == 'CMDBINSTANCESELECT':
                sort = (opts.get('extraProps') or {}).get('sort') or {}
                sort_list = sort.get('sort') if isinstance(sort, dict) else sort
                if isinstance(sort_list, list):
                    add(len(sort_list) <= 1, 'E-F8_SORT_SINGLE', '只允许一个排序字段', ctx)
                    if len(sort_list) == 1:
                        add(bool(sort_list[0].get('field')), 'E-F9_SORT_FIELD_SELECTED', '排序字段未选择', ctx)

    return results, has_err[0]


# 兼容旧入口（只查字段标题长度）
def validate_controls(form_definition):
    results, _ = validate_designer_form(form_definition)
    return [r for r in results if r['rule'] in ('E-F1_FIELD_TITLE_REQUIRED', 'E-F2_FIELD_TITLE_LENGTH')]


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

    p6 = sub.add_parser('check-controls', help='设计器保存链全量校验 E（validateSection+validateField+属性面板）')
    p6.add_argument('--form-definition', required=True, help='formDefinition JSON（[]Container 或字符串）')

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
    if a.cmd == 'check-controls':
        fd = a.form_definition
        try:
            fd = json.loads(fd)
        except json.JSONDecodeError:
            pass   # 传字符串让校验器按 formDefinition 字符串处理
        rs, blocked = validate_designer_form(fd)
        for r in rs:
            if not r['ok']:
                print(f"❌ [{r['rule']}] {r['message']}")
        print(f"\n{'✅ 设计器保存链全部通过' if not blocked else '❌ 前端保存会被拦截（上面 %d 条）' % len([r for r in rs if not r['ok']])}")
        return 0 if not blocked else 1


if __name__ == '__main__':
    sys.exit(main())
