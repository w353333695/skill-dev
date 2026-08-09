#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tools-sdk-demo.py —— EasyOps 工具脚本示例：CMDB 模型清理。

这是「工具脚本」本身——会被打成 .tar.gz 工具包（config + script），在 agent 的
/usr/local/easyops/python/bin/python（py2 或 py3）下执行。它演示工具脚本如何用
easyops_client.EasyOpsClient 调 cmdb，对应场景② build-cleanup-tool.yaml 的脚本内容。

工具入参（由平台从 inputs 定义注入到环境变量）：
  MODEL_ID  必填 —— 要清理的 CMDB 模型 id（如 TESTWWH@EASYOPS）
  FORCE     选填 —— 'true' 则强删有实例的模型；否则有实例时跳过删除

执行逻辑：
  1. 查该模型的所有实例（search 取 instanceIds）
  2. 有实例且 FORCE != true → 跳过（不删有实例的模型）
  3. 否则：删实例 → 删关系定义 → 删模型（forceDelete=FORCE 绕开『请先删除已有关系 133129』）

⚠️ 内置变量用 $EASYOPS_*（org/user/cmdb host 等），不存在 __instance__/${cmdb.xxx}——
   拿本机 IP 用 $EASYOPS_LOCAL_IP，拿 org/user 用 $EASYOPS_ORG/$EASYOPS_USER。
"""
from __future__ import print_function

import os
import sys

# 工具脚本运行时：easyops_client.py 与本脚本同目录（打成工具包时一起带上）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from easyops_client import EasyOpsClient, EasyOpsError  # noqa: E402

# === 工具入参（平台从 inputs 注入到环境变量）===
MODEL_ID = os.environ.get('MODEL_ID', '').strip()
FORCE = os.environ.get('FORCE', 'false').strip().lower() == 'true'


def _put(name, value):
    """回吐标量输出（对应平台 SDK 的 PutStr）。

    真工具包里由平台注入的 main.py 提供 PutStr；这里是 demo 的简易等价——
    平台解析 ##PARAMETER_<key>:<base64>:... 标记。演示用 print 即可。
    """
    print('##PARAMETER_%s:%s' % (name, value))


def main():
    if not MODEL_ID:
        print('ERROR: MODEL_ID 必填')
        sys.exit(1)

    # 初始化客户端（双模式：internal 直连 cmdb_service，或 openapi 走网关）
    cmdb_host = os.environ.get('EASYOPS_CMDB_SERVICE_HOST') or os.environ.get('EASYOPS_CMDB_HOST', '')
    base_url = 'http://%s:8079' % cmdb_host if cmdb_host else 'http://172.30.0.232:8079'
    c = EasyOpsClient(
        org=os.environ.get('EASYOPS_ORG'),
        user=os.environ.get('EASYOPS_USER'),
        cookie=os.environ.get('EASYOPS_COOKIE'),
        mode='internal',
        base_url=os.environ.get('EASYOPS_CMDB_BACKEND_URL', base_url),
        host='admin.easyops.local',
        verify=False,
    )
    # 反射具名方法（可选；此处直接用通用 call 也行）
    here = os.path.dirname(os.path.abspath(__file__))
    cmdb_spec = os.path.join(here, 'easyops-cmdb.yaml')
    if os.path.exists(cmdb_spec):
        c.load_spec(cmdb_spec)

    # 1. 查实例（fields 必填，否则 100000）
    search = c.call('POST', '/v3/object/%s/instance/_search' % MODEL_ID,
                    body={'fields': ['instanceId', 'name'], 'page': 1, 'page_size': 3000})
    insts = (search.get('data') or {}).get('list') or []
    ids = [it.get('instanceId') for it in insts if it.get('instanceId')]
    print('模型 %s 有 %d 个实例' % (MODEL_ID, len(ids)))

    # 2. 有实例且非强删 → 跳过（不删有实例的模型）
    if ids and not FORCE:
        print('有实例且 FORCE!=true，跳过删除（保护有实例的模型）')
        _put('deleted', '0')
        _put('skipped', '1')
        return

    # 3a. 删实例（instance_batch，分号串）
    if ids:
        c.call('DELETE', '/object/%s/instance_batch' % MODEL_ID,
               params={'instanceIds': ';'.join(ids)})
        print('已删 %d 个实例' % len(ids))

    # 3b. 删关系定义（先取模型详情拿 relation_list，逐条删）
    detail = c.call('GET', '/object/%s' % MODEL_ID)
    rels = (detail.get('data') or {}).get('relation_list') or []
    for r in rels:
        rid = r.get('relation_id')
        if rid:
            try:
                c.call('DELETE', '/object_relation/%s' % rid, params={'force_delete': 'true'})
            except EasyOpsError as e:
                print('warn: 删关系 %s 失败 %s' % (rid, e))
    print('已处理 %d 条关系' % len(rels))

    # 3c. 删模型（forceDelete=FORCE；FORCE=true 绕开『请先删除已有关系 133129』）
    c.call('DELETE', '/object/%s' % MODEL_ID,
           params={'forceDelete': 'true' if FORCE else 'false'})
    print('已删模型 %s' % MODEL_ID)
    _put('deleted', '1')


if __name__ == '__main__':
    main()
