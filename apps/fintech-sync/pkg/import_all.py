#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人行金融数据 CMDB 导入脚本（模型 + 实例，自包含）

用法:
  python3 import_all.py --host 172.30.0.90 [--org 8888] [--user easyops] [--check] [--clean] [--dry-run]

  --host    CMDB 后端地址（必填；端口默认 8079，可用 --port 覆盖）
  --check   只跑模型导入预检（/v2/object_import_check，不落库）
  --clean   冲突环境清理导入：先删 36 模型全部实例 → 删 36 数据模型(forceDelete)
            → 导入模型 → 导入实例。抽象父模型(7个)平台禁删，由导入 upsert 覆盖定义。
  --dry-run 只打印将要执行的步骤，不发起任何写请求

包结构:
  models/_all.json          43 个模型完整定义（7 抽象父模型在前 + 36 数据模型）
                            父引用闭包已核（全部 @FINTECHDATA 内）；
                            唯一外部引用 softwareRelation→USER_GROUP 为平台内置模型，目标环境必存在
  instances/*.json          36 个模型的实例数据（已含 _dataSource/_diffDetail 溯源字段，
                            facilityOwnershipAgency 已统一编号 A1000141000266）

导入顺序: 模型(_all.json 整体一次导入，父模型在前) → 实例(逐模型 upsert, 500/批)
实例 upsert 键: 实体=设施标识符(facilityDescriptor), 关系=关系标识符(relationalIdentifier)
脚本纯 py3 stdlib（urllib），不依赖 api-cli。
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODELS_FILE = BASE / 'models' / '_all.json'
INSTANCES_DIR = BASE / 'instances'
BATCH = 500

# 模型 → 唯一键属性（与源环境写入一致；未列出的实体模型用 facilityDescriptor，关系模型用 relationalIdentifier）
KEY_ATTR = {
    'powerSupplyRelation': 'relationalIdentifier',
    'networkRelation': 'relationalIdentifier',
    'applicationRelation': 'relationalIdentifier',
    'applicationSoftRelation': 'relationalIdentifier',
    'softwareRelation': 'relationalIdentifier',
    'dataCenterSpacing': 'relationalIdentifier',
    'application': 'applySystemIdentifiers',
    'basedSoftware': 'softwareDescriptor',
}
DEFAULT_KEY = 'facilityDescriptor'


def call(base, method, path, payload, headers):
    url = base.rstrip('/') + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8')), e.code
        except Exception:
            return None, e.code
    except Exception as e:
        return None, str(e)


# ---------------- 清理链（--clean）：删实例 → 删数据模型 → 导模型 → 导实例 ----------------
# 删除语义（实测 172.30.0.90）：
#   模型有实例 → 133123「资源模型存在实例数据」；forceDelete=true 连实例强删
#   抽象父模型（CUSTOM/netAsset 等 7 个）→ 130302「Can not drop abstract object」删不掉，
#     也不必删：导入 upsert 会覆盖其定义
#   数据模型互无 parentObjectIds 引用（父引用只指向抽象模型），任意顺序可删；
#     但 softwareRelation 的 relation_list 引用平台内置 USER_GROUP，删除时 forceDelete 连带关系

def clean_instances(base, headers):
    """逐数据模型删全部实例：search(500/页) 取 instanceId → instance_batch 删。"""
    files = sorted(INSTANCES_DIR.glob('*.json'))
    total = 0
    failed_models = []
    for f in files:
        mid = f.stem + '@FINTECHDATA'
        ids = []
        page = 1
        while True:
            res, err = call(base, 'POST', f'/v3/object/{mid}/instance/_search',
                            {'fields': ['instanceId'], 'page': page, 'page_size': 500,
                             'ignore_missing_field_error': True}, headers)
            if err is not None or (res and res.get('code') != 0):
                # 模型不存在（404/133114 等）视为已清空
                break
            rows = (res.get('data') or {}).get('list') or []
            ids += [r.get('instanceId') for r in rows if r.get('instanceId')]
            if len(rows) < 500:
                break
            page += 1
        if not ids:
            print(f"  [跳过] {f.stem}: 0 实例")
            continue
        # instance_batch 删，500 个/批（instanceIds 分号分隔 query）
        deleted = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            qs = ';'.join(chunk)
            path = f'/object/{mid}/instance_batch?instanceIds={qs}'
            res, err = call(base, 'DELETE', path, None, headers)
            if err is not None or (res and res.get('code') != 0):
                print(f"  ✗ {f.stem} 删实例批{i//500+1}: {err or res.get('message')}")
                failed_models.append(f.stem)
                break
            deleted += len(chunk) - len(((res.get('data') or {}).get('deleteFailedInstances') or []))
        total += deleted
        print(f"  [OK] {f.stem}: 删 {deleted}/{len(ids)}")
    print(f"[清实例] 合计删除 {total}")
    return not failed_models


def clean_models(base, headers):
    """删 36 个数据模型（forceDelete=true 连带关系/实例）。抽象父模型不动（平台禁删，导入 upsert 覆盖）。"""
    files = sorted(INSTANCES_DIR.glob('*.json'))
    ok, skip, fail = 0, 0, []
    for f in files:
        mid = f.stem + '@FINTECHDATA'
        res, err = call(base, 'DELETE', f'/object/{mid}?forceDelete=true', None, headers)
        code = (res or {}).get('code')
        if err is None and code == 0:
            ok += 1
        elif res and code == 133114:
            skip += 1  # 模型本就不存在
        else:
            fail.append(f"{f.stem}: {err if err is not None else str(res)[:150]}")
            print(f"  ✗ 删模型 {f.stem}: {fail[-1]}")
    print(f"[清模型] 删除 {ok} / 不存在跳过 {skip} / 失败 {len(fail)}（共 {len(files)} 数据模型；7 抽象父模型保留由导入 upsert 覆盖）")
    return not fail



def import_models(base, headers, check_only=False):
    objs = json.loads(MODELS_FILE.read_text())
    path = '/v2/object_import_check' if check_only else '/v2/object_import'
    print(f"[模型] {'预检' if check_only else '导入'} {len(objs)} 个 ...")
    res, err = call(base, 'POST', path, {'object_list': objs}, headers)
    if err is not None:
        print(f"[模型] 失败: {err} {json.dumps(res, ensure_ascii=False)[:400] if res else ''}")
        return False
    if res.get('code') != 0:
        print(f"[模型] 业务失败 code={res.get('code')} {res.get('message', '')}")
        return False
    results = (res.get('data') or {}).get('import_result') or []
    bad = [r for r in results if r.get('code') != 0]
    for r in bad:
        print(f"  ✗ {r.get('objectId')}: {r.get('code')} {str(r.get('message'))[:120]}")
    print(f"[模型] {'预检' if check_only else '导入'}完成: {len(results)-len(bad)}/{len(results)} 成功")
    return not bad


def import_instances(base, headers, only=None):
    files = sorted(INSTANCES_DIR.glob('*.json'))
    if only:
        files = [f for f in files if f.stem == only]
    total_ins = total_upd = total_fail = 0
    failed_models = []
    for f in files:
        rows = json.loads(f.read_text())
        key = KEY_ATTR.get(f.stem, DEFAULT_KEY)
        # 剔除空值字段（与生成侧 build_import_body 同语义）
        datas = [{k: v for k, v in r.items() if v not in (None, '', [])} for r in rows]
        ins = upd = fail = 0
        for i in range(0, len(datas), BATCH):
            chunk = datas[i:i + BATCH]
            res, err = call(base, 'POST', f"/object/{f.stem}@FINTECHDATA/instance/_import",
                            {'keys': [key], 'datas': chunk}, headers)
            if err is not None or (res and res.get('code') != 0):
                print(f"  ✗ {f.stem} 批{i//BATCH+1}: {err or res.get('message')}")
                fail += len(chunk)
                continue
            d = (res.get('data') or {})
            ins += d.get('insert_count') or 0
            upd += d.get('update_count') or 0
            fail += d.get('failed_count') or 0
            for x in (d.get('data') or [])[:3]:
                print(f"    失败明细: {json.dumps(x, ensure_ascii=False)[:200]}")
        status = 'OK' if fail == 0 else 'FAIL'
        print(f"  [{status}] {f.stem}: {len(rows)} 行 → insert={ins} update={upd} failed={fail}")
        total_ins += ins; total_upd += upd; total_fail += fail
        if fail:
            failed_models.append(f.stem)
    print(f"[实例] 合计: insert={total_ins} update={total_upd} failed={total_fail}")
    if failed_models:
        print(f"[实例] 失败模型: {failed_models}")
    return total_fail == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', required=True, help='CMDB 后端 IP（如 172.30.0.90）')
    ap.add_argument('--port', type=int, default=8079)
    ap.add_argument('--org', default='8888')
    ap.add_argument('--user', default='easyops')
    ap.add_argument('--check', action='store_true', help='只做模型预检（不落库）')
    ap.add_argument('--clean', action='store_true', help='导入前先清理：删实例→删数据模型→再导入（解决模型冲突）')
    ap.add_argument('--only', help='只导某模型实例（模型主名，如 switches）')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    base = f'http://{args.host}:{args.port}'
    headers = {'Host': 'admin.easyops.local', 'org': args.org, 'user': args.user}

    print(f"目标: {base}  org={args.org} user={args.user}")
    if args.dry_run:
        steps = ['模型导入(43)']
        if args.clean:
            steps = ['清实例(36)', '清数据模型(36)'] + steps
        steps.append('实例导入(36 模型, 500/批 upsert)')
        print("DRY-RUN: 将执行 " + ' → '.join(steps))
        return 0

    if args.clean:
        if not clean_instances(base, headers):
            print("[警告] 实例清理有失败，继续删模型（forceDelete 会强删残余）")
        if not clean_models(base, headers):
            print("[警告] 模型清理有失败，继续导入（upsert 会覆盖）")

    if not import_models(base, headers, check_only=args.check):
        return 1
    if args.check:
        return 0

    t0 = time.time()
    ok = import_instances(base, headers, only=args.only)
    print(f"耗时 {time.time()-t0:.0f}s")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
