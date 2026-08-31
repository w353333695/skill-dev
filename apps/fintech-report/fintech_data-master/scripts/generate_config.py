#!/usr/local/easyops/python/bin/python
# coding=utf-8

import sys
import yaml

sys.path.extend(['/usr/local/easyops'])
from deploy_init.tools import get_env


def generate():
    is_cluster = get_env.get_key('/usr/local/easyops/deploy_init/easy_env.ini', 'redis', 'is_cluster')
    sentinel = is_cluster == 'true'
    conf = {"redis": {"sentinel": sentinel}}

    yaml.safe_dump(conf, stream=sys.stdout, default_flow_style=False, encoding='utf-8', allow_unicode=True)

if __name__ == '__main__':
    generate()
