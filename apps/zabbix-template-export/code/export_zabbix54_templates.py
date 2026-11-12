#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zabbix 5.4 全域监控数据导出入口；Python 3.9+，与同目录 Python 2 引擎共用实现。"""
import os
import sys
import export_zabbix54_templates_py2 as engine

VERSION = engine.VERSION
ZABBIX_URL = "https://zabbix.example/zabbix"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = ""
ZABBIX_TOKEN = ""
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
TIMEOUT = 120
INSECURE = False
TEMPLATE_IDS = []
TEMPLATE_NAMES = []
EXPORT_ALL = True
EXPORT_HOSTS = True
HOST_IDS = []
BATCH_SIZE = 25
EXPORT_EXTENDED = True
FAIL_ON_PARTIAL = True
EXPORT_EVENTS = True
EXPORT_HISTORY = False
EXPORT_TRENDS = False
EXPORT_TEXT_HISTORY = False
DATA_TIME_FROM = None
DATA_TIME_TILL = None
PAGE_SIZE = 5000


def main(argv=None):
    for name in ("ZABBIX_URL", "ZABBIX_USER", "ZABBIX_PASSWORD", "ZABBIX_TOKEN", "OUTPUT_DIR",
                 "TIMEOUT", "INSECURE", "TEMPLATE_IDS", "TEMPLATE_NAMES", "EXPORT_ALL",
                 "EXPORT_HOSTS", "HOST_IDS", "BATCH_SIZE", "EXPORT_EXTENDED", "FAIL_ON_PARTIAL",
                 "EXPORT_EVENTS", "EXPORT_HISTORY", "EXPORT_TRENDS", "EXPORT_TEXT_HISTORY",
                 "DATA_TIME_FROM", "DATA_TIME_TILL", "PAGE_SIZE"):
        setattr(engine, name, globals()[name])
    return engine.main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
