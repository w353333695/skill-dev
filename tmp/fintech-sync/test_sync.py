# tmp/fintech-sync/test_sync.py
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import sync

def test_norm_text():
    assert sync.norm_text('用电设施类型\t') == '用电设施类型'
    assert sync.norm_text('设备高度（U）') == '设备高度(U)'
    assert sync.norm_text('  交换机 ') == '交换机'

def test_find_file_report_side():
    p = sync.find_file('report', '交换机')
    assert p is not None and p.exists() and '交换机_' in p.name

def test_find_file_mgmt_alias():
    # 机柜(上报) ↔ 普通机柜(管理)
    p = sync.find_file('mgmt', '机柜')
    assert p is not None and p.exists() and p.name.startswith('普通机柜')

def test_find_file_report_side_uses_main_name():
    # report 侧永远用主名原名，mgmt_alias 不应影响 report 查找
    p = sync.find_file('report', '机柜')
    assert p is not None and p.exists() and p.name.startswith('机柜_')

def test_read_excel_rows_skips():
    p = sync.find_file('report', '交换机')
    rows = sync.read_excel_rows(p)
    assert len(rows) == 407                       # 调研实测数据行
    assert '记录ID' not in rows[0]                # skip_columns 生效
    assert any('管理IP地址' in r for r in rows[:3])

FAKE_ATTRS = {
    'facilityDescriptor': {'name': '设施标识符', 'type': 'str',  'regex': None},
    'assetCode':          {'name': '资产编码',   'type': 'str',  'regex': None},
    'deviceHeight':       {'name': '设备高度(U)', 'type': 'str', 'regex': None},
    'facilityUseState':   {'name': '设施在用状态', 'type': 'enum', 'regex': ['00-设施在用']},
}

def test_resolve_key_attr():
    assert sync.resolve_key_attr(FAKE_ATTRS, '设施标识符') == 'facilityDescriptor'
    assert sync.resolve_key_attr(FAKE_ATTRS, '不存在') is None

def test_match_field_map():
    pairs, uh, ua = sync.match_field_map(
        {'attrs': FAKE_ATTRS, 'key_attr': 'facilityDescriptor'},
        ['设施标识符', '资产编码', '设备高度(U)', '审计列X'],
        ['设施标识符', '资产编码（可读性标识编码）'])
    pm = {(r, m): a for r, m, a in pairs}
    assert pm[('设施标识符', '设施标识符')] == 'facilityDescriptor'      # 双侧同名直配
    # 去尾部括号注释匹配：管理侧「资产编码（可读性标识编码）」自动配 assetCode（v2 自动化）
    assert pm[('资产编码', '资产编码（可读性标识编码）')] == 'assetCode'
    assert ('设备高度(U)', None) in pm                                  # 管理侧无此列→None（后续人工补）
    assert uh == ['审计列X']                                            # 未匹配列只剩审计列
    # 设施在用状态在两侧 fake 表头均无列→属未匹配属性（真实表头有此列）
    assert ua == ['facilityUseState']

def test_build_custom_attrs_body_missing():
    detail = {'objectId': 'CUSTOM@FINTECHDATA', 'name': '自定义字段',
              'attrList': [{'id': 'memo', 'name': '备注', 'value': {'type': 'str'}}]}
    body = sync.build_custom_attrs_body(detail)
    ids = [a['id'] for a in body['object_list'][0]['attrList']]
    assert '_dataSource' in ids and '_diffDetail' in ids and 'memo' in ids

def test_build_custom_attrs_body_present_noop():
    detail = {'objectId': 'CUSTOM@FINTECHDATA', 'name': '自定义字段', 'attrList': [
        {'id': 'memo', 'name': '备注', 'value': {'type': 'str'}},
        {'id': '_dataSource', 'name': '数据来源', 'value': {'type': 'enum'}},
        {'id': '_diffDetail', 'name': '差异明细', 'value': {'type': 'struct'}}]}
    assert sync.build_custom_attrs_body(detail) is None

def test_fetch_schema_refresh_keeps_other_models(monkeypatch, tmp_path):
    # 缓存重定向到临时目录，避免污染真实 out/schema-cache.json
    monkeypatch.setattr(sync, 'SCHEMA_CACHE', tmp_path / 'schema-cache.json')
    # 预置缓存：别的模型 + 待刷新模型（refresh=True 应绕过命中重拉，但不能清掉别的模型）
    cache = {'other@FINTECHDATA': {'attrs': {'x': {'name': 'X', 'type': 'str', 'regex': None}},
                                   'key_attr': 'x'},
             'switches@FINTECHDATA': {'attrs': {'stale': {'name': '旧', 'type': 'str', 'regex': None}},
                                      'key_attr': 'stale'}}
    sync.SCHEMA_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    fake_detail = {'data': {'attrList': [
        {'id': 'facilityDescriptor', 'name': '设施标识符', 'value': {'type': 'str'}}]}}
    monkeypatch.setattr(sync, 'api_cli', lambda *a, **k: (0, json.dumps(fake_detail), ''))
    schema = sync.fetch_schema('switches@FINTECHDATA', refresh=True)
    assert 'facilityDescriptor' in schema['attrs']            # 确实重拉了
    after = json.loads(sync.SCHEMA_CACHE.read_text())
    assert 'other@FINTECHDATA' in after                       # 别的模型还在（bug 时会被清掉）
    assert 'switches@FINTECHDATA' in after and after['switches@FINTECHDATA'] == schema

CTX = {'enums': {'facilityUseState': {'设施在用': '00-设施在用'}},
       'invalid': ['******'], 'errors': []}

def test_clean_value_date():
    import datetime
    assert sync.clean_value(datetime.date(2022, 8, 31), 'd', {'type': 'date', 'name': ''}, CTX) == '2022-08-31'
    assert sync.clean_value('2022-08-31 ', 'd', {'type': 'date', 'name': ''}, CTX) == '2022-08-31'

def test_clean_value_number_and_enum():
    assert sync.clean_value(123.0, 'v', {'type': 'str', 'name': ''}, CTX) == '123'
    assert sync.clean_value('设施在用', 'facilityUseState',
                            {'type': 'enum', 'name': '', 'regex': ['00-设施在用']}, CTX) == '00-设施在用'
    assert sync.clean_value('00-设施在用', 'facilityUseState',
                            {'type': 'enum', 'name': '', 'regex': ['00-设施在用']}, CTX) == '00-设施在用'
    sync.clean_value('神秘值', 'facilityUseState', {'type': 'enum', 'name': '', 'regex': ['00-设施在用']}, CTX)
    assert any('神秘值' in e for e in CTX['errors'])          # 错误收集不中断

def test_normalize_row_full():
    pairs = [('设施标识符', '设施标识符', 'facilityDescriptor'),
             ('管理IP地址', '管理IP地址', 'ip'),
             (None, '设施信息更新日期', 'facilityUpdateDate')]
    raw = {'设施标识符': ' abc ', '管理IP地址': '******', '设施信息更新日期': '2024-01-01'}
    out = sync.normalize_row(raw, pairs, 'report', CTX)
    assert out == {'facilityDescriptor': 'abc'}        # 脱敏→None 且不产出键；管理独有列报侧不取
    out2 = sync.normalize_row(raw, pairs, 'mgmt', CTX)
    assert out2.get('ip') is None and out2['facilityUpdateDate'] == '2024-01-01'

PAIRS = [('设施标识符', '设施标识符', 'fd'), ('管理IP地址', '管理IP地址', 'ip')]

def test_merge_model_all_branches():
    r = [{'fd': 'a', 'ip': '1.1.1.1'}, {'fd': 'b', 'ip': '2.2.2.2'},
         {'fd': 'c', 'ip': '3.3.3.3'}, {'ip': 'no-key'}]
    m = [{'fd': 'a', 'ip': '1.1.1.1'}, {'fd': 'b', 'ip': '******'},
         {'fd': 'd', 'ip': '4.4.4.4'}, {'fd': 'e', 'ip': '5.5.5.5'}]
    merged, stats, orphan = sync.merge_model(r, m, 'fd', ['fd', 'ip'])
    by = {row['fd']: row for row in merged if row.get('fd')}
    assert by['a']['_dataSource'] == '双源' and by['a']['_diffDetail'] == []      # 一致
    assert by['b']['ip'] == '2.2.2.2' and by['b']['_dataSource'] == '双源(有差异)'  # 脱敏→上报覆盖
    assert by['b']['_diffDetail'] == [{'attr': 'ip', 'reportValue': '2.2.2.2', 'mgmtValue': '******'}]
    assert by['c']['_dataSource'] == '上报' and by['d']['_dataSource'] == '管理'
    assert stats == {'both_same': 1, 'both_diff': 1, 'report_only': 1, 'mgmt_only': 2}
    assert len(orphan) == 1

def test_compare_report_table_not_interrupted(monkeypatch, tmp_path):
    # 多模型差异时，主表（| 行）必须连续且不被明细节 bullet（- 行）中断（GFM 表格遇 bullet 停止渲染）
    monkeypatch.setattr(sync, 'OUT', tmp_path)
    monkeypatch.setattr(sync, 'FIELD_MAP', {
        'switches@FINTECHDATA': [('设施标识符', '设施标识符', 'fd'), ('管理IP地址', '管理IP地址', 'ip')],
        'router@FINTECHDATA':   [('设施标识符', '设施标识符', 'fd'), ('管理IP地址', '管理IP地址', 'ip')],
    })
    monkeypatch.setattr(sync, 'fetch_schema', lambda mid: {'attrs': {}, 'key_attr': 'fd'})
    for name in ('switches', 'router'):                       # 两模型各 1 条差异行
        for side, row in (('report', {'fd': 'a', 'ip': '1.1.1.1'}), ('mgmt', {'fd': 'a', 'ip': '2.2.2.2'})):
            d = tmp_path / 'transformed' / side
            d.mkdir(parents=True, exist_ok=True)
            (d / f'{name}.json').write_text(json.dumps([row], ensure_ascii=False))
    sync.compare()
    kinds = ['T' if l.startswith('|') else ('B' if l.startswith('-') else 'O')
             for l in (tmp_path / 'diff-report.md').read_text().splitlines()]
    assert kinds.count('B') >= 2 and kinds.count('T') >= 4     # 两模型表行+表头都在
    first_b = kinds.index('B')
    tl = [i for i, k in enumerate(kinds) if k == 'T']
    assert all(i < first_b for i in tl)                       # 全部表行在首个 bullet 之前
    assert set(kinds[tl[0]:tl[-1] + 1]) == {'T'}              # 表行区间连续无夹断

def test_match_field_map_struct_sub_field_priority():
    # structs 子字段与顶层属性同名冲突时，excel 列语义=子字段（部署数据中心→xx_deployment.deployDb）
    schema = {'attrs': {
        'facilityDescriptor': {'name': '设施标识符', 'type': 'str', 'regex': None},
        'deployDb':           {'name': '部署数据中心', 'type': 'str', 'regex': None},   # 顶层同名（模拟）
        'x_deployment.deployDb': {'name': '部署数据中心', 'type': 'str', 'regex': None}},  # 子字段
        'key_attr': 'facilityDescriptor'}
    pairs, uh, _ = sync.match_field_map(schema, ['设施标识符', '部署数据中心'], ['设施标识符'])
    pm = {(r, m): a for r, m, a in pairs}
    assert pm[('部署数据中心', None)] == 'x_deployment.deployDb'      # 子字段优先

def test_match_field_map_bare_vs_annotated():
    # 管理裸名「设备高度」自动配上报「设备高度(U)」的属性（v2 双向去注释）
    pairs, uh, _ = sync.match_field_map(
        {'attrs': {'deviceHeight': {'name': '设备高度(U)', 'type': 'str', 'regex': None}},
         'key_attr': None},
        ['设备高度(U)'], ['设备高度'])
    assert pairs == [('设备高度(U)', '设备高度', 'deviceHeight')] and uh == []

def test_clean_value_enum_prefix_match():
    # 裸值=regex 某合法值的后缀（且唯一、排除「其它」）→前缀归一
    d = {'type': 'enum', 'name': '', 'regex': ['01-主机房-网络区', '02-主机房-存储区', '99-其它']}
    assert sync.clean_value('主机房-网络区', 'deployArea', d, {'enums': {}, 'invalid': [], 'errors': []}) == '01-主机房-网络区'
    assert sync.clean_value('01-主机房-网络区', 'deployArea', d, {'enums': {}, 'invalid': [], 'errors': []}) == '01-主机房-网络区'
    # 后缀歧义（两个候选）→不猜，记错误
    ctx = {'enums': {}, 'invalid': [], 'errors': []}
    d2 = {'type': 'enum', 'name': '', 'regex': ['01-主机房-网络区', '02-别的-网络区', '99-其它']}
    assert sync.clean_value('网络区', 'deployArea', d2, ctx) == '网络区'
    assert any('网络区' in e for e in ctx['errors'])

def test_clean_value_enums_multi():
    d = {'type': 'enums', 'name': '', 'regex': ['00-IPSec', '01-MACSec']}
    ctx = {'enums': {}, 'invalid': [], 'errors': []}
    assert sync.clean_value('IPSec, MACSec', 'nsc', d, ctx) == '00-IPSec,01-MACSec'   # 多选拆分逐个归一
    assert sync.clean_value('00-IPSec', 'nsc', d, ctx) == '00-IPSec'

def test_clean_value_float_and_none_values():
    assert sync.clean_value('10.5', 'w', {'type': 'float', 'name': ''}, {'enums': {}, 'invalid': [], 'errors': []}) == 10.5
    assert sync.clean_value('无', 'v', {'type': 'str', 'name': ''}, {'enums': {}, 'invalid': [], 'errors': []}) is None

def test_normalize_row_nested_and_assemble():
    pairs = [('设施标识符', '设施标识符', 'facilityDescriptor'),
             ('部署区域', '部署区域', 'x_deployment.deployArea')]
    ctx = {'enums': {}, 'invalid': [], 'errors': [],
           '_attr': {'x_deployment.deployArea': {'name': '部署区域', 'type': 'enum',
                                                 'regex': ['01-主机房-网络区', '99-其它']}}}
    out = sync.normalize_row({'设施标识符': 'k1', '部署区域': '主机房-网络区'}, pairs, 'report', ctx)
    assert out == {'facilityDescriptor': 'k1', 'x_deployment': {'deployArea': '01-主机房-网络区'}}
    # 空 struct 值 → 组装时剔除
    out2 = sync.normalize_row({'设施标识符': 'k2', '部署区域': '无'}, pairs, 'report', ctx)
    assembled = sync._assemble(out2, {'x_deployment'})
    assert assembled == {'facilityDescriptor': 'k2'}
    # structs 组装为 list[dict]
    assembled2 = sync._assemble(out, {'x_deployment'})
    assert assembled2['x_deployment'] == [{'deployArea': '01-主机房-网络区'}]

def test_merge_model_struct_leaf_diff():
    r = [{'fd': 'a', 'dep': {'area': '01-网络区', 'db': 'D1'}}]
    m = [{'fd': 'a', 'dep': {'area': '01-网络区', 'db': 'D2'}}]
    merged, stats, _ = sync.merge_model(r, m, 'fd', ['fd', 'dep'])
    assert stats['both_diff'] == 1
    assert merged[0]['_diffDetail'] == [{'attr': 'dep.db', 'reportValue': 'D1', 'mgmtValue': 'D2'}]
    assert merged[0]['dep'] == {'area': '01-网络区', 'db': 'D1'}      # 上报优先（子字段级）

def test_build_import_body_structs():
    rows = [{'fd': 'a', 'dep': {'x': '1'}, '_dataSource': '双源', '_diffDetail': []},
            {'fd': 'b', 'dep': {}, '_diffDetail': [{'attr': 'dep.x', 'reportValue': '1', 'mgmtValue': '2'}]}]
    body = sync.build_import_body('fd', rows, structs_attrs={'dep'})
    assert body['datas'][0]['dep'] == [{'x': '1'}]
    assert 'dep' not in body['datas'][1] and body['datas'][1]['_diffDetail'][0]['attr'] == 'dep.x'

def test_loose_eq_basic():
    assert sync._loose_eq('02-Java', 'Java')
    assert sync._loose_eq('99-其他', '其他')
    assert sync._loose_eq('00-IPSec,01-MACSec', '00-IPSec,01-MACSec')
    assert not sync._loose_eq('02-Java', '03-Python')

def test_loose_eq_date_guard():
    # 日期形态（YYYY-MM-DD）不走宽松剥前缀：2024-01-15 与 2023-01-15 剥前缀后同为 '01-15' 会误等
    assert not sync._loose_eq('2024-01-15', '2023-01-15')
    assert sync._loose_eq('2024-01-15', '2024-01-15')     # 同日期仍相等（严格等）
    # 完整日期前带其他文本不属日期守卫范围（正常剥前缀语义）
    assert sync._loose_eq('02-Java', 'Java')              # 修复不影响编码前缀宽松等

def test_build_import_body():
    rows = [{'fd': 'a', 'ip': '1.1.1.1', '_dataSource': '双源', '_diffDetail': []},
            {'fd': 'b', 'ip': None, '_dataSource': '上报', '_diffDetail':
             [{'attr': 'ip', 'reportValue': 'x', 'mgmtValue': '******'}]}]
    body = sync.build_import_body('fd', rows)
    assert body['keys'] == ['fd']
    assert body['datas'][0] == {'fd': 'a', 'ip': '1.1.1.1', '_dataSource': '双源'}   # None/空剔除
    assert body['datas'][1]['_diffDetail'][0]['attr'] == 'ip'

def test_run_import_parses(monkeypatch):
    fake = {'code': 0, 'data': {'insert_count': 10, 'update_count': 5, 'failed_count': 0, 'data': []}}
    monkeypatch.setattr(sync, 'api_cli', lambda *a, **k: (0, json.dumps(fake), ''))
    r = sync.run_import('x@FINTECHDATA', '/dev/null')
    assert r['data']['insert_count'] == 10

def test_search_total(monkeypatch):
    monkeypatch.setattr(sync, 'api_cli', lambda *a, **k: (0, '', '{"_meta":{"total":407}}'))
    assert sync.search_total('x@FINTECHDATA') == 407
    monkeypatch.setattr(sync, 'api_cli', lambda *a, **k: (0, '', ''))   # exit0+空=0
    assert sync.search_total('x@FINTECHDATA') == 0
