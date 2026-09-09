# tmp/fintech-sync/test_sync.py
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
