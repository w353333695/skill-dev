#!/usr/bin/env python3
"""BPMN 自动布局 CLI —— 薄壳入口，实现见 bpmn_relayout_impl.py（唯一实现，勿复制代码到此）。
用法: python3 bpmn-relayout.py <bpmn文件> [-o 输出.bpmn]
库:   from bpmn_relayout import relayout_xml"""
import runpy, sys
if __name__ == '__main__':
    sys.argv[0] = 'bpmn_relayout_impl.py'
    runpy.run_path(__file__.replace('bpmn-relayout.py', 'bpmn_relayout_impl.py'), run_name='__main__')
