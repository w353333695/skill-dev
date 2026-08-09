#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ⚠️ 工具脚本【不要】用 `from __future__ import ...`——EasyOps 平台下发执行时会在脚本开头
# 注入内部方法/变量，使 __future__ 不在文件首行而触发 SyntaxError:
# from __future__ imports must occur at the beginning of the file。
# py2/3 兼容改用运行时判断（见 PY2）+ logging（不直接 print）。
# 坑详见 platforms/demo/objects.yaml#api_behavior.tool_script_no_future。
"""
tools-sdk-demo.py —— EasyOps 工具脚本示例：CMDB 模型清理（场景② build-cleanup-tool 的 script）。

被打进工具包 .tar.gz（config + script），在 agent /usr/local/easyops/python/bin/python
（py2 或 py3）下执行。演示工具脚本如何用 easyops_client.EasyOpsClient 调 cmdb。

工具入参（平台从 inputs 定义注入到环境变量）：
  MODEL_ID  必填 —— 要清理的 CMDB 模型 id（如 TESTWWH@EASYOPS）
  FORCE     选填 —— 'true' 则强删有实例的模型；否则有实例时跳过

执行逻辑：查实例 → 有实例且非 force 跳过 → 否则删实例 → 删关系定义 → 删模型。

⚠️ 内置变量用 $EASYOPS_*（org/user/cmdb host 等），不存在 __instance__/${cmdb.xxx}。
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from easyops_client import EasyOpsClient, EasyOpsError  # noqa: E402

log = logging.getLogger('cleanup')
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s', stream=sys.stderr)

MODEL_ID = os.environ.get('MODEL_ID', '').strip()
FORCE = os.environ.get('FORCE', 'false').strip().lower() == 'true'


def _put(name, value):
    """回吐标量输出（对应平台 SDK 的 PutStr）。平台解析 ##PARAMETER_<key>:... 标记。"""
    sys.stdout.write('##PARAMETER_%s:%s\n' % (name, value))


def main():
    if not MODEL_ID:
        log.error('MODEL_ID 必填')
        sys.exit(1)

    # 初始化客户端（internal 直连 cmdb_service；外网改 mode='openapi' + AK/SK）
    c = EasyOpsClient(
        mode='internal',
        base_url=os.environ.get('EASYOPS_CMDB_BACKEND_URL', 'http://172.30.0.232:8079'),
        org=os.environ.get('EASYOPS_ORG'),
        user=os.environ.get('EASYOPS_USER'),
        cookie=os.environ.get('EASYOPS_COOKIE'),
        host='admin.easyops.local',
        verify=False,
    )

    # 1. 查实例（fields 必填，否则 100000）
    search = c.call('POST', '/v3/object/%s/instance/_search' % MODEL_ID,
                    body={'fields': ['instanceId', 'name'], 'page': 1, 'page_size': 3000})
    insts = (search.get('data') or {}).get('list') or []
    ids = [it.get('instanceId') for it in insts if it.get('instanceId')]
    log.info('模型 %s 有 %d 个实例', MODEL_ID, len(ids))

    # 2. 有实例且非强删 → 跳过（保护有实例的模型）
    if ids and not FORCE:
        log.info('有实例且 FORCE!=true，跳过删除')
        _put('deleted', '0')
        _put('skipped', '1')
        return

    # 3a. 删实例（instance_batch，分号串）
    if ids:
        c.call('DELETE', '/object/%s/instance_batch' % MODEL_ID,
               params={'instanceIds': ';'.join(ids)})
        log.info('已删 %d 个实例', len(ids))

    # 3b. 删关系定义（取模型详情拿 relation_list，逐条删）
    detail = c.call('GET', '/object/%s' % MODEL_ID)
    rels = (detail.get('data') or {}).get('relation_list') or []
    for r in rels:
        rid = r.get('relation_id')
        if rid:
            try:
                c.call('DELETE', '/object_relation/%s' % rid, params={'force_delete': 'true'})
            except EasyOpsError as e:
                log.warning('删关系 %s 失败: %s', rid, e)
    log.info('已处理 %d 条关系', len(rels))

    # 3c. 删模型（forceDelete=FORCE 绕开『请先删除已有关系 133129』）
    c.call('DELETE', '/object/%s' % MODEL_ID,
           params={'forceDelete': 'true' if FORCE else 'false'})
    log.info('已删模型 %s', MODEL_ID)
    _put('deleted', '1')


if __name__ == '__main__':
    main()
