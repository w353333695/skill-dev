# 人行双平台数据统一到 CMDB 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `tmp/人行上报`（36 文件/3312 行）与 `tmp/人行管理`（34 文件/3282 行）的 Excel 数据按唯一键合并（脱敏无效、上报优先），标记来源与差异明细，全量 upsert 写入 EasyOps CMDB 的 `@FINTECHDATA` 模型族。

**Architecture:** 单文件 `tmp/fintech-sync/sync.py`（py3），CONFIG 区（dict/list 嵌套）+ 四阶段函数 `investigate/transform/compare/import_cmdb`，支持 `--stage` 单跑；CMDB 交互全部经 api-cli `run.sh` 子进程；中间产物全落盘 `out/` 可审查。Spec：`tmp/fintech-sync/spec.md`（commit 4748b56）。

**Tech Stack:** python3 + openpyxl（已装）；pytest（缺则 `pip install pytest`）；EasyOps api-cli（`/workspace/.claude/skills/api-orchestrator/scripts/run.sh`）。

## Global Constraints

- 所有产物只写 `/workspace/tmp/fintech-sync/`（脚本/测试/out/），严禁写 skill 目录与 `.api-orchestrator/`
- `run.sh` 用绝对路径调用，且 subprocess **必须 `cwd='/workspace'`**（部署根按 `$PWD/.api-orchestrator` 解析，cd 走即 base URL 为空——实测坑）
- `tmp/` 被 gitignore：每次 commit 用 `git add -f`
- 实体唯一键=设施标识符，关系唯一键=关系标识符（`MODEL_MAP.key` 存中文名，attr id 运行时按 `attr.name` 解析）
- 脱敏值 `******` 无效；有效值冲突上报优先；差异记入 struct 数组 `_diffDetail`
- CUSTOM 新属性 id 带 `_` 前缀：`_dataSource`(enum)/`_diffDetail`(struct)，实例数据字段名同此
- CMDB 枚举合法值在 `attr.value.regex` 数组（enumList 恒空）；excel 值与 regex 相同直通，否则查 `ENUM_MAP`，查不到记错误不中断
- 日期统一 `YYYY-MM-DD`；`RULES.skip_sheets/skip_columns` 不进 CMDB
- import 是 upsert（`keys=[key_attr_id]`），幂等可重跑
- 分页 total 在 stderr `{"_meta":{"total":N}}`；exit 0 + 输出空 = 0 条

---

### Task 1: 脚本骨架 + CONFIG + excel 读取层

**Files:**
- Create: `tmp/fintech-sync/sync.py`
- Test: `tmp/fintech-sync/test_sync.py`

**Interfaces:**
- Produces: `norm_text(s)->str`、`find_file(side,main_name)->Path`、`read_excel_rows(path)->list[dict]`、常量 `SIDES/MODEL_MAP/RULES/RUN_SH/CMDB_SPEC/OUT`、`api_cli(resource,verb,*args,body=None,body_file=None,yes=False)->(rc,stdout,stderr)`

- [ ] **Step 1: 写失败测试**

```python
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

def test_read_excel_rows_skips():
    p = sync.find_file('report', '交换机')
    rows = sync.read_excel_rows(p)
    assert len(rows) == 407                       # 调研实测数据行
    assert '记录ID' not in rows[0]                # skip_columns 生效
    assert any('管理IP地址' in r for r in rows[:3])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -5`（pytest 缺则先 `pip install pytest`）
Expected: FAIL `ModuleNotFoundError: No module named 'sync'`

- [ ] **Step 3: 最小实现**

```python
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
    '变压器设备':            {'model_id': 'transformer@FINTECHDATA',          'key': '设施标识符'},
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
    for k, cfg in MODEL_MAP.items():
        if k == main_name and 'mgmt_alias' in cfg:
            alias = cfg['mgmt_alias']
    pat = re.compile(re.escape(alias) + r'_?\d{14}\.xlsx$')
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

if __name__ == '__main__':
    print('use --stage investigate|transform|compare|import')
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -6`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/test_sync.py
git commit -m "feat(fintech-sync): 脚本骨架+CONFIG+excel读取层"
```

---

### Task 2: investigate()——schema 拉取 + FIELD_MAP 骨架生成 + CUSTOM 属性保障

**Files:**
- Modify: `tmp/fintech-sync/sync.py`（追加）
- Test: `tmp/fintech-sync/test_sync.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `api_cli/read_excel_rows/find_file/norm_text`
- Produces: `fetch_schema(model_id,refresh=False)->dict`（`{'attrs': {attr_id: {'name','type','regex'}}, 'key_attr': str}`，缓存 `out/schema-cache.json`）、`resolve_key_attr(attrs,key_name)->str|None`、`match_field_map(schema,report_headers,mgmt_headers)->(pairs,unmatched_headers,unmatched_attrs)`、`build_custom_attrs_body(detail)->dict|None`、`ensure_custom_attrs()->bool`、`investigate()->None`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_sync.py
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
    assert ('资产编码', '资产编码') in pm                                # 报侧配到
    assert ('设备高度(U)', None) in pm                                  # 管理侧无此列→None（后续人工补）
    assert uh == ['资产编码（可读性标识编码）', '审计列X']                # 未匹配列待人工
    assert ua == []                                                     # 属性全配到

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -5`
Expected: 新增 4 条 FAIL `AttributeError: module 'sync' has no attribute ...`（旧 4 条仍 PASS）

- [ ] **Step 3: 实现**

```python
# ============================== investigate ==============================
SCHEMA_CACHE = OUT / 'schema-cache.json'

def _attr_brief(a):
    v = a.get('value') or {}
    return {'name': a.get('name'), 'type': v.get('type'), 'regex': v.get('regex') or None}

def fetch_schema(model_id, refresh=False):
    """detail → {attrs:{id:{name,type,regex}}, key_attr}；缓存到 out/schema-cache.json"""
    cache = {}
    if SCHEMA_CACHE.exists() and not refresh:
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -10`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/test_sync.py
git commit -m "feat(fintech-sync): investigate阶段-schema拉取+骨架生成+CUSTOM属性保障"
```

---

### Task 3: transform()——通用转换（列映射/枚举归一/脱敏/日期）

**Files:**
- Modify: `tmp/fintech-sync/sync.py`（追加）
- Test: `tmp/fintech-sync/test_sync.py`（追加）

**Interfaces:**
- Consumes: Task 1 `read_excel_rows/find_file`、Task 2 `fetch_schema`
- Produces: `clean_value(v,attr_id,attr_def,ctx)->value`、`normalize_row(raw,pairs,side,ctx)->dict`、`transform(side)->dict`（统计）；产物 `out/transformed/{side}/{model_id}.json`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_sync.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -5`
Expected: 新增 3 FAIL（旧 8 PASS）

- [ ] **Step 3: 实现**

```python
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
    for rcol, mcol, aid in pairs:
        col = rcol if side == 'report' else mcol
        if col is None:
            continue
        out[aid] = clean_value(raw.get(col), aid, ctx['_attr'], ctx)
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -6`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/test_sync.py
git commit -m "feat(fintech-sync): transform阶段-通用转换器"
```

---

### Task 4: compare()——合并比对 + 差异报告

**Files:**
- Modify: `tmp/fintech-sync/sync.py`（追加）
- Test: `tmp/fintech-sync/test_sync.py`（追加）

**Interfaces:**
- Consumes: Task 3 `transform` 产物
- Produces: `merge_model(r_rows,m_rows,key_attr,attr_ids)->(merged,stats,orphan)`、`compare()->None`；产物 `out/merged/{model}.json`、`out/diff-report.md`、`out/orphan.json`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_sync.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -4`
Expected: 新增 1 FAIL（旧 11 PASS）

- [ ] **Step 3: 实现**

```python
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
    orphans = {}
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
                lines.append(f"- **{row.get(schema['key_attr'])}** ({mid})")
                for d in row['_diffDetail']:
                    lines.append(f"  - {d['attr']}: 上报={d['reportValue']} | 管理={d['mgmtValue']}")
    (OUT / 'orphan.json').write_text(json.dumps(orphans, ensure_ascii=False, indent=1))
    (OUT / 'diff-report.md').write_text('\n'.join(lines))
    print('compare 完成 →', OUT / 'diff-report.md')
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -4`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/test_sync.py
git commit -m "feat(fintech-sync): compare阶段-合并比对+差异报告"
```

---

### Task 5: import_cmdb()——写入与对账

**Files:**
- Modify: `tmp/fintech-sync/sync.py`（追加 + `__main__` 改造）
- Test: `tmp/fintech-sync/test_sync.py`（追加）

**Interfaces:**
- Consumes: Task 2 `fetch_schema`、Task 4 `out/merged/*.json`
- Produces: `build_import_body(key_attr,rows)->dict`、`run_import(model_id,body_path)->dict`、`search_total(model_id)->int`、`import_cmdb(only=None)->dict`；产物 `out/import-bodies/*.json`、`out/import-result.json`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_sync.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -4`
Expected: 新增 3 FAIL（旧 12 PASS）

- [ ] **Step 3: 实现**

```python
# ============================== import ==============================
def build_import_body(key_attr, rows):
    datas = [{k: v for k, v in row.items() if v not in (None, '', [])} for row in rows]
    return {'keys': [key_attr], 'datas': datas}

def run_import(model_id, body_path):
    rc, out, err = api_cli('object_instance', 'import', model_id, body_file=body_path, yes=True)
    if rc != 0:
        return {'code': -1, 'error': err.strip()[:300]}
    return json.loads(out)

def search_total(model_id):
    rc, out, err = api_cli('object_instance', 'search', model_id,
                           body='{"fields":["instanceId"],"page":1,"page_size":1,"ignore_missing_field_error":true}')
    m = re.search(r'"total":(\d+)', err)
    return int(m.group(1)) if m else 0

def import_cmdb(only=None):
    """only=模型id 则只写该模型（试点）；None 全量。body 落盘留审计。"""
    bdir = OUT / 'import-bodies'
    bdir.mkdir(parents=True, exist_ok=True)
    result = {}
    for main, cfg in sorted(MODEL_MAP.items()):
        mid = cfg['model_id']
        if only and mid != only:
            continue
        mp_ = OUT / 'merged' / f"{mid.split('@')[0]}.json"
        if not mp_.exists():
            continue
        rows = json.loads(mp_.read_text())
        schema = fetch_schema(mid)
        bp = bdir / f"{mid.split('@')[0]}.json"
        bp.write_text(json.dumps(build_import_body(schema['key_attr'], rows), ensure_ascii=False))
        r = run_import(mid, bp)
        d = r.get('data') or {}
        result[mid] = {'merged': len(rows), 'insert': d.get('insert_count'), 'update': d.get('update_count'),
                       'failed': d.get('failed_count'), 'fail_detail': (d.get('data') or [])[:10],
                       'after_total': search_total(mid), 'error': r.get('error')}
        print(mid, result[mid])
    (OUT / 'import-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result

if __name__ == '__main__':
    stage = sys.argv[sys.argv.index('--stage') + 1] if '--stage' in sys.argv else None
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    if stage == 'investigate': investigate()
    elif stage == 'transform': transform('report'); transform('mgmt')
    elif stage == 'compare':   compare()
    elif stage == 'import':    import_cmdb(only=only)
    else: print('usage: sync.py --stage investigate|transform|compare|import [--only <model_id>]')
```

（`api_cli` 的 `body=` 内联参数已在 Task 1 定义，Task 5 直接使用。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /workspace/tmp/fintech-sync && python3 -m pytest test_sync.py -v 2>&1 | tail -4`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/test_sync.py
git commit -m "feat(fintech-sync): import阶段-写入与对账"
```

---

### Task 6: 真实端到端执行（investigate→补配置→transform→compare→试点→全量→回归）

**Files:**
- Modify: `tmp/fintech-sync/sync.py`（把核对后的 FIELD_MAP 粘回 CONFIG）
- 产物: `out/*` 全套

**Interfaces:**
- Consumes: Task 1-5 全部
- Produces: CMDB 真实数据（~3300 实例 + CUSTOM 两属性）；验收留痕 `out/import-result.json`

- [ ] **Step 1: investigate 真跑（含 CUSTOM 属性补建——真实写操作，先向用户展示 body 再执行）**

```bash
cd /workspace/tmp/fintech-sync && python3 sync.py --stage investigate
```
Expected: `out/investigate.md` 生成；CUSTOM `_dataSource/_diffDetail` 补建成功（或已存在）；key 缺失清单为空

- [ ] **Step 2: 核对并回填 FIELD_MAP**

看 `out/investigate.md` 的「未匹配列/未匹配属性」，把 `out/config-skeleton.py` 内容核对修正后整体粘贴到 `sync.py` 的 `FIELD_MAP =` 处。已知需人工处理的同义映射（交换机样本）：
- 管理 `资产编码（可读性标识编码）` → `assetCode` 的 mgmt 列
- `资产价值`/`设备高度`/`板卡数量`（管理裸名）↔ `资产价值(万元)`/`设备高度(U)`/`板卡数量(个)`（上报带注）——自动 norm 匹配不上的逐条补
- 枚举错误清单 `out/transform-*-errors.json` 非空时回补 `ENUM_MAP`

- [ ] **Step 3: transform + compare 真跑**

```bash
cd /workspace/tmp/fintech-sync && python3 sync.py --stage transform && python3 sync.py --stage compare
```
Expected: 两边 36+34 文件全转无异常；`out/diff-report.md` 总览表中交换机=407/407、机柜≈459/450、防火墙 36/35（1 条仅上报）；孤儿行集中在 orphan.json

- [ ] **Step 4: 人工抽查差异（验收门）**

从 `out/diff-report.md` 交换机小节抽 10 条差异，逐条回两份 excel 核对值一致（换算枚举后）。不符则回修 transform 后重跑 Step 3。

- [ ] **Step 5: 试点写入交换机（真实写操作，向用户确认后执行）**

```bash
cd /workspace/tmp/fintech-sync && python3 sync.py --stage import --only switches@FINTECHDATA
```
Expected: `import-result.json` 中 switches: insert+update=407, failed=0, after_total=407
再人工验证：`run.sh ... object_instance search switches@FINTECHDATA --body '{"fields":["instanceId","_dataSource","facilityDescriptor"],"page":1,"page_size":3,...}'` 抽 3 条看 `_dataSource` 值合理

- [ ] **Step 6: 全量写入（真实写操作，向用户确认后执行）**

```bash
cd /workspace/tmp/fintech-sync && python3 sync.py --stage import
```
Expected: 各模型 failed=0 且 after_total==merged 数（差异>0 的模型列入清单人工复核）

- [ ] **Step 7: 回归幂等验证**

重跑 Step 6 命令。
Expected: 第二轮全部 insert=0、update=merged 数（纯更新，幂等成立）

- [ ] **Step 8: Commit 产物与最终配置**

```bash
cd /workspace && git add -f tmp/fintech-sync/sync.py tmp/fintech-sync/out/investigate.md tmp/fintech-sync/out/diff-report.md tmp/fintech-sync/out/import-result.json
git commit -m "feat(fintech-sync): 端到端执行完成-全量写入+对账"
```

（`out/transformed|merged|import-bodies` 体积大不入库，留本地审查）
