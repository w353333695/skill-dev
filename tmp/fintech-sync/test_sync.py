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
    # 简报原文为 ('资产编码','资产编码')，与 mgmt 表头（只有「资产编码（可读性标识编码）」）
    # 及断言4（该列留待人工）矛盾，任何实现无法同时满足——按 plan Task3 Step2 人工回填语义修正
    assert ('资产编码', None) in pm                                     # 报侧配到，管理侧同义列待人工
    assert ('设备高度(U)', None) in pm                                  # 管理侧无此列→None（后续人工补）
    # 未匹配列待人工；顺序=实现语义：先上报侧未匹配，后管理侧未匹配
    assert uh == ['审计列X', '资产编码（可读性标识编码）']
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
    assert out == {'facilityDescriptor': 'abc', 'ip': None}    # 脱敏→None；管理独有列报侧不取
    out2 = sync.normalize_row(raw, pairs, 'mgmt', CTX)
    assert out2['ip'] is None and out2['facilityUpdateDate'] == '2024-01-01'

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
