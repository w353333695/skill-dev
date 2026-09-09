#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人行双平台数据统一到 CMDB。spec: tmp/fintech-sync/spec.md"""
import json, re, subprocess, sys
from datetime import datetime, date
from pathlib import Path
import openpyxl

# ============================== CONFIG ==============================
SIDES = {'report': Path('/workspace/tmp/人行上报'), 'mgmt': Path('/workspace/tmp/人行管理')}

# excel主名(上报侧) → {'model_id','key'(唯一键中文列名),'mgmt_alias'(管理侧文件主名,缺省同名)}
MODEL_MAP = {
    '交换机':               {'model_id': 'switches@FINTECHDATA',              'key': '设施标识符'},
    '路由器':               {'model_id': 'router@FINTECHDATA',                'key': '设施标识符'},
    '防火墙':               {'model_id': 'firewall@FINTECHDATA',              'key': '设施标识符'},
    '负载均衡设备':           {'model_id': 'loadBalancing@FINTECHDATA',        'key': '设施标识符'},
    '上网行为管理设备':       {'model_id': 'onlineBehavior@FINTECHDATA',       'key': '设施标识符'},
    '入侵检测与防御设备（IDS_IPS）': {'model_id': 'idsIps@FINTECHDATA',        'key': '设施标识符', 'mgmt_alias': '入侵检测与防御设备'},
    '运维审计设备':          {'model_id': 'opsAudit@FINTECHDATA',              'key': '设施标识符'},
    '虚拟机资源':            {'model_id': 'virtualMachine@FINTECHDATA',       'key': '设施标识符', 'mgmt_alias': '虚拟机'},
    '机架式服务器':          {'model_id': 'rackServer@FINTECHDATA',           'key': '设施标识符'},
    '基础软件':             {'model_id': 'basedSoftware@FINTECHDATA',         'key': '设施标识符'},
    '光纤交换机':            {'model_id': 'fiberSwitch@FINTECHDATA',          'key': '设施标识符'},
    '机柜':                {'model_id': 'commonCabinet@FINTECHDATA',         'key': '设施标识符', 'mgmt_alias': '普通机柜'},
    '视频监控类':            {'model_id': 'videoMonitoring@FINTECHDATA',      'key': '设施标识符', 'mgmt_alias': '视频监控系统'},
    '动环监控系统':          {'model_id': 'environmentalMonitoring@FINTECHDATA','key': '设施标识符'},
    '门禁系统':             {'model_id': 'entranceGuard@FINTECHDATA',         'key': '设施标识符'},
    '消防系统':             {'model_id': 'fireProtection@FINTECHDATA',        'key': '设施标识符'},
    '中央空调':             {'model_id': 'centralAirCondition@FINTECHDATA',   'key': '设施标识符'},
    '普通空调':             {'model_id': 'commonAirCondition@FINTECHDATA',    'key': '设施标识符'},
    '精密空调':             {'model_id': 'precisionAirCondition@FINTECHDATA', 'key': '设施标识符'},
    '新风系统':             {'model_id': 'freshAir@FINTECHDATA',              'key': '设施标识符'},
    '加湿系统':             {'model_id': 'humidification@FINTECHDATA',        'key': '设施标识符'},
    '发电机':               {'model_id': 'generator@FINTECHDATA',             'key': '设施标识符'},
    '不间断配电':            {'model_id': 'uninterrupted@FINTECHDATA',        'key': '设施标识符'},
    '精密配电设备':          {'model_id': 'precisionPower@FINTECHDATA',       'key': '设施标识符'},
    '高压配电设备':          {'model_id': 'highVoltage@FINTECHDATA',          'key': '设施标识符'},
    '低压配电':             {'model_id': 'lowVoltage@FINTECHDATA',            'key': '设施标识符'},
    '变压器设备':           {'model_id': 'transformer@FINTECHDATA',          'key': '设施标识符'},
    '波分复用设备':          {'model_id': 'wdm@FINTECHDATA',                  'key': '设施标识符'},
    '数据中心':             {'model_id': 'dataCenter@FINTECHDATA',           'key': '设施标识符'},   # 仅上报
    '数据中心间距':          {'model_id': 'dataCenterSpacing@FINTECHDATA',    'key': '设施标识符'},
    '应用系统':             {'model_id': 'application@FINTECHDATA',          'key': '设施标识符'},
    '供电关联关系':          {'model_id': 'powerSupplyRelation@FINTECHDATA',  'key': '关系标识符'},
    '网络线路':             {'model_id': 'networkLine@FINTECHDATA',           'key': '设施标识符'},
    '网络线路关联关系':       {'model_id': 'networkRelation@FINTECHDATA',     'key': '关系标识符'},
    '应用系统关联关系':       {'model_id': 'applicationRelation@FINTECHDATA', 'key': '关系标识符'},
    '应用系统软件关联关系':    {'model_id': 'applicationSoftRelation@FINTECHDATA','key': '关系标识符'},
    '软件实例关联关系':       {'model_id': 'softwareRelation@FINTECHDATA',    'key': '关系标识符'},
}

# model_id → [(上报列名|None, 管理列名|None, cmdb属性id), ...]
# 初始为空：investigate() 生成骨架（out/config-skeleton.py），人工核对后粘贴此处
FIELD_MAP = {}

# cmdb属性id → {excel侧裸值 → cmdb合法值(regex 中的值)}
ENUM_MAP = {
    'facilityUseState': {'设施在用': '00-设施在用', '设施已停用': '01-设施已停用',
                         '设施专用于开发或测试': '02-设施专用于开发或测试',
                         '设施已拆除或报废': '03-设施已拆除或报废', '备用设施': '04-备用设施', '其它': '99-其它'},
    'supportIpv6':      {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'wirelessFunction': {'是': 'True', '否': 'False', '1-True': 'True', '0-False': 'False'},
    'brandLand':        {'国内': '00-国内', '国外': '01-国外', '其它': '99-其它'},
}

RULES = {
    'invalid_values': ['******'],
    'skip_sheets':  ['维修信息'],
    'skip_columns': ['记录ID', '拥有者', '创建者', '创建时间', '最近修改时间', '数据校验结果'],
}

RUN_SH     = '/workspace/.claude/skills/api-orchestrator/scripts/run.sh'
CMDB_SPEC  = '/workspace/.api-orchestrator/platforms/easyops/easyops-cmdb.yaml'
OUT        = Path('/workspace/tmp/fintech-sync/out')

# ============================== 基础层 ==============================
def norm_text(s):
    """比较用归一：去空白、全角括号→半角。"""
    return str(s).replace('（', '(').replace('）', ')').replace('\t', '').strip()

def find_file(side, main_name):
    """side∈{report,mgmt}；report 文件名=<主名>_YYYYMMDDHHMMSS.xlsx，mgmt=<别名>YYYYMMDDHHMMSS.xlsx"""
    alias = main_name
    if side == 'mgmt':
        for k, cfg in MODEL_MAP.items():
            if k == main_name and 'mgmt_alias' in cfg:
                alias = cfg['mgmt_alias']
    # report 侧时间戳 14 位（<主名>_YYYYMMDDHHMMSS）；mgmt 侧实测 17 位（YYYYMMDDHHMMSS+3位毫秒）
    pat = re.compile(re.escape(alias) + r'_?\d{14,17}\.xlsx$')
    for p in sorted(SIDES[side].glob('*.xlsx')):
        if pat.match(p.name):
            return p
    return None

def read_excel_rows(path):
    """读主 sheet（第一个），表头行 1；剔除 skip_columns；返回 [{列名:值}]，空行跳过。"""
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    rows, header = [], None
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        if i == 1:
            header = [norm_text(c) if c is not None else None for c in row]
            continue
        d = {}
        for col, v in zip(header, row):
            if col and col not in RULES['skip_columns']:
                d[col] = v
        if any(v is not None and str(v).strip() for v in d.values()):
            rows.append(d)
    wb.close()
    return rows

def api_cli(resource, verb, *args, body=None, body_file=None, yes=False):
    """调 run.sh（cwd 必须 /workspace）。body=内联 json 串，body_file=文件路径。返回 (rc, stdout, stderr)。"""
    cmd = [RUN_SH, '--spec', CMDB_SPEC, resource, verb] + [str(a) for a in args]
    if body:      cmd += ['--body', body]
    if body_file: cmd += ['--body-file', str(body_file)]
    if yes:       cmd += ['--yes']
    r = subprocess.run(cmd, capture_output=True, text=True, cwd='/workspace')
    return r.returncode, r.stdout, r.stderr

# ============================== investigate ==============================
SCHEMA_CACHE = OUT / 'schema-cache.json'

def _attr_brief(a):
    v = a.get('value') or {}
    return {'name': a.get('name'), 'type': v.get('type'), 'regex': v.get('regex') or None}

def fetch_schema(model_id, refresh=False):
    """detail → {attrs:{id:{name,type,regex}}, key_attr}；缓存到 out/schema-cache.json"""
    cache = {}
    if SCHEMA_CACHE.exists():
        cache = json.loads(SCHEMA_CACHE.read_text())
    if model_id in cache and not refresh:
        return cache[model_id]
    rc, out, err = api_cli('object_model', 'detail', model_id)
    if rc != 0:
        raise RuntimeError(f'detail {model_id} 失败: {err.strip()[:200]}')
    data = json.loads(out)['data']
    schema = {'attrs': {a['id']: _attr_brief(a) for a in data.get('attrList', [])},
              'key_attr': None}
    cfg = next(c for c in MODEL_MAP.values() if c['model_id'] == model_id)
    schema['key_attr'] = resolve_key_attr(schema['attrs'], cfg['key'])
    cache[model_id] = schema
    OUT.mkdir(exist_ok=True)
    SCHEMA_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return schema

def resolve_key_attr(attrs, key_name):
    for aid, a in attrs.items():
        if norm_text(a['name']) == norm_text(key_name):
            return aid
    return None

def match_field_map(schema, report_headers, mgmt_headers):
    """按属性中文名自动配 excel 列（norm 后比较）；产出三元组骨架 + 未匹配清单。"""
    pairs, used_r, used_m = [], set(), set()
    for aid, a in sorted(schema['attrs'].items()):
        if aid in ('_dataSource', '_diffDetail', 'memo'):
            continue  # CUSTOM 继承属性/差异字段不参与列映射
        n = norm_text(a['name'])
        rc_ = next((h for h in report_headers if norm_text(h) == n), None)
        mc_ = next((h for h in mgmt_headers if norm_text(h) == n), None)
        if rc_: used_r.add(rc_)
        if mc_: used_m.add(mc_)
        pairs.append((rc_, mc_, aid))
    uh = [h for h in report_headers if h not in used_r and h not in RULES['skip_columns']]
    uh += [h for h in mgmt_headers if h not in used_m and h not in RULES['skip_columns']]
    ua = [aid for r, m, aid in pairs if r is None and m is None]
    return pairs, uh, ua

def build_custom_attrs_body(detail):
    """CUSTOM 缺 _dataSource/_diffDetail 时产出 import body；已全有→None。"""
    ids = {a['id'] for a in detail.get('attrList', [])}
    if {'_dataSource', '_diffDetail'} <= ids:
        return None
    attrs = list(detail['attrList'])
    if '_dataSource' not in ids:
        attrs.append({'id': '_dataSource', 'name': '数据来源',
                      'value': {'type': 'enum', 'regex': ['上报', '管理', '双源', '双源(有差异)'],
                                'default': None, 'mode': 'default'}})
    if '_diffDetail' not in ids:
        attrs.append({'id': '_diffDetail', 'name': '差异明细',
                      'value': {'type': 'struct', 'default': None, 'mode': 'default',
                                'struct_define': [
                                    {'id': 'attr', 'name': '属性ID', 'type': 'str'},
                                    {'id': 'reportValue', 'name': '上报值', 'type': 'str'},
                                    {'id': 'mgmtValue', 'name': '管理值', 'type': 'str'}]}})
    obj = {k: v for k, v in detail.items() if k != 'attrList'}
    obj['attrList'] = attrs
    if 'parentObjectIds' in obj:
        obj.pop('parentObjectId', None)   # 已弃用字段不回写
    return {'object_list': [obj]}

def ensure_custom_attrs():
    rc, out, err = api_cli('object_model', 'detail', 'CUSTOM@FINTECHDATA')
    if rc != 0:
        raise RuntimeError(f'detail CUSTOM@FINTECHDATA 失败: {err.strip()[:200]}')
    body = build_custom_attrs_body(json.loads(out)['data'])
    if body is None:
        return False
    p = OUT / 'custom-attrs-import.json'
    p.write_text(json.dumps(body, ensure_ascii=False))
    rc2, out2, err2 = api_cli('object_model', 'import', body_file=p, yes=True)
    if rc2 != 0:
        raise RuntimeError(f'补建 CUSTOM 属性失败: {err2.strip()[:300]}')
    return True

def investigate():
    OUT.mkdir(exist_ok=True)
    lines, skel = ['# 模型 schema 调研报告', '', '| 模型 | 属性数 | key属性 | 上报表头 | 管理表头 | 未匹配列 | 未匹配属性 |',
                   '|---|---|---|---|---|---|---|'], {}
    key_missing = []
    for main, cfg in sorted(MODEL_MAP.items()):
        schema = fetch_schema(cfg['model_id'])
        if not schema['key_attr']:
            key_missing.append(f"{cfg['model_id']}: 找不到名为「{cfg['key']}」的属性")
        rp, mp = find_file('report', main), find_file('mgmt', main)
        rh = list(read_excel_rows(rp)[0].keys()) if rp else []
        mh = list(read_excel_rows(mp)[0].keys()) if mp else []
        pairs, uh, ua = match_field_map(schema, rh, mh)
        skel[cfg['model_id']] = {'pairs': pairs, 'report_only_cols': [r for r, m, a in pairs if r and not m],
                                 'mgmt_only_cols': [m for r, m, a in pairs if m and not r]}
        lines.append(f"| {cfg['model_id']} | {len(schema['attrs'])} | {schema['key_attr']} "
                     f"| {len(rh)} | {len(mh)} | {uh} | {ua} |")
    created = ensure_custom_attrs()
    lines += ['', f'## CUSTOM 属性', f'_dataSource/_diffDetail: {"本次补建" if created else "已存在"}']
    if key_missing:
        lines += ['', '## ⚠️ key 属性缺失'] + key_missing
    (OUT / 'investigate.md').write_text('\n'.join(lines))
    (OUT / 'config-skeleton.py').write_text(
        '# FIELD_MAP 骨架（investigate 自动生成，人工核对后整体粘贴回 sync.py 的 FIELD_MAP）\n'
        'FIELD_MAP = ' + json.dumps({m: [list(p) for p in v['pairs']] for m, v in skel.items()},
                                    ensure_ascii=False, indent=1))
    print('investigate 完成 →', OUT / 'investigate.md')

# ============================== transform ==============================
def clean_value(v, attr_id, attr_def, ctx):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s in ctx['invalid'] or s == '':
        return None
    if attr_def.get('type') == 'enum':
        m = ctx['enums'].get(attr_id, {})
        if s in m:
            return m[s]
        if attr_def.get('regex') and s in attr_def['regex']:
            return s
        ctx['errors'].append(f'{attr_id}: 枚举值「{s}」不在合法集 {attr_def.get("regex")} 且 ENUM_MAP 未映射')
        return s
    return s

def normalize_row(raw, pairs, side, ctx):
    """excel行 → {cmdb属性id: 值}。单边列（该侧为 None）不产出键。"""
    out = {}
    attrs = ctx.get('_attr', {})                              # {attr_id: 属性定义}
    for rcol, mcol, aid in pairs:
        col = rcol if side == 'report' else mcol
        if col is None:
            continue
        # 简报笔误修正：按 aid 取单个属性定义传入（而非整个 attrs dict）
        out[aid] = clean_value(raw.get(col), aid, attrs.get(aid, {'name': '', 'type': 'str'}), ctx)
    return out

def transform(side):
    assert FIELD_MAP, 'FIELD_MAP 为空：先跑 investigate 并把 out/config-skeleton.py 核对后粘回'
    outdir = OUT / 'transformed' / side
    outdir.mkdir(parents=True, exist_ok=True)
    stats, all_errors = {}, []
    for main, cfg in sorted(MODEL_MAP.items()):
        p = find_file(side, main)
        if p is None:
            continue                                    # 该侧无此文件（单边模型）
        schema = fetch_schema(cfg['model_id'])
        rows = read_excel_rows(p)
        ctx = {'enums': ENUM_MAP, 'invalid': RULES['invalid_values'],
               'errors': [], '_attr': schema['attrs']}
        unified = [normalize_row(r, FIELD_MAP[cfg['model_id']], side, ctx) for r in rows]
        (outdir / f"{cfg['model_id'].split('@')[0]}.json").write_text(
            json.dumps(unified, ensure_ascii=False, indent=1))
        stats[cfg['model_id']] = {'rows': len(unified), 'enum_errors': len(ctx['errors'])}
        all_errors += ctx['errors']
    (OUT / f'transform-{side}-errors.json').write_text(json.dumps(all_errors, ensure_ascii=False, indent=1))
    print(f'transform({side}):', json.dumps(stats, ensure_ascii=False)[:400], '... 枚举错误', len(all_errors))
    return stats

# ============================== compare ==============================
def merge_model(r_rows, m_rows, key_attr, attr_ids):
    r = {row[key_attr]: row for row in r_rows if row.get(key_attr)}
    m = {row[key_attr]: row for row in m_rows if row.get(key_attr)}
    orphan = [row for row in r_rows + m_rows if not row.get(key_attr)]
    merged, stats = [], {'both_same': 0, 'both_diff': 0, 'report_only': 0, 'mgmt_only': 0}
    for k in sorted(set(r) | set(m), key=str):
        if k in r and k in m:
            row, diffs = {key_attr: k}, []
            for a in attr_ids:
                if a == key_attr:
                    continue
                rv, mv = r[k].get(a), m[k].get(a)
                if rv is None and mv is None:
                    continue
                if mv is None:   row[a] = rv
                elif rv is None: row[a] = mv
                elif str(rv) == str(mv): row[a] = rv
                else:
                    row[a] = rv
                    diffs.append({'attr': a, 'reportValue': str(rv), 'mgmtValue': str(mv)})
            row['_dataSource'] = '双源(有差异)' if diffs else '双源'
            row['_diffDetail'] = diffs
            stats['both_diff' if diffs else 'both_same'] += 1
        else:
            src = r if k in r else m
            row = dict(src[k]); row['_dataSource'] = '上报' if k in r else '管理'
            row['_diffDetail'] = []
            stats['report_only' if k in r else 'mgmt_only'] += 1
        merged.append(row)
    return merged, stats, orphan

def compare():
    mdir = OUT / 'merged'
    mdir.mkdir(parents=True, exist_ok=True)
    lines = ['# 两源差异报告', '', '| 模型 | 上报 | 管理 | 合并 | 双源一致 | 双源差异 | 仅上报 | 仅管理 | 孤儿 |',
             '|---|---|---|---|---|---|---|---|---|']
    detail_lines, orphans = [], {}
    for main, cfg in sorted(MODEL_MAP.items()):
        mid = cfg['model_id']
        rp, mp_ = OUT / 'transformed/report' / f"{mid.split('@')[0]}.json", OUT / 'transformed/mgmt' / f"{mid.split('@')[0]}.json"
        if not rp.exists() and not mp_.exists():
            continue
        r_rows = json.loads(rp.read_text()) if rp.exists() else []
        m_rows = json.loads(mp_.read_text()) if mp_.exists() else []
        schema = fetch_schema(mid)
        attr_ids = [a for _, _, a in FIELD_MAP[mid]] + ['_dataSource', '_diffDetail']
        merged, stats, orphan = merge_model(r_rows, m_rows, schema['key_attr'], attr_ids)
        (mdir / f"{mid.split('@')[0]}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1))
        if orphan:
            orphans[mid] = orphan
        lines.append(f"| {mid} | {len(r_rows)} | {len(m_rows)} | {len(merged)} | {stats['both_same']} "
                     f"| {stats['both_diff']} | {stats['report_only']} | {stats['mgmt_only']} | {len(orphan)} |")
        for row in merged:                                   # 明细节
            if row.get('_diffDetail'):
                detail_lines.append(f"- **{row.get(schema['key_attr'])}** ({mid})")
                for d in row['_diffDetail']:
                    detail_lines.append(f"  - {d['attr']}: 上报={d['reportValue']} | 管理={d['mgmtValue']}")
    if detail_lines:                                         # 两遍收集：主表连续，明细节分段在后
        lines += [''] + detail_lines
    (OUT / 'orphan.json').write_text(json.dumps(orphans, ensure_ascii=False, indent=1))
    (OUT / 'diff-report.md').write_text('\n'.join(lines))
    print('compare 完成 →', OUT / 'diff-report.md')

if __name__ == '__main__':
    print('use --stage investigate|transform|compare|import')
