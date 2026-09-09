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
