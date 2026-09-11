#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
search_artifact_package.py —— CICD artifact 组件「程序包」搜索脚本

场景：在 EasyOps CICD 的 artifact（制品库）组件里按名称搜索程序包，
      支持模糊/精确匹配、类型/创建者/标签过滤、分页。

接口：GET /package/search（名字服务 logic.artifact，制品组件）
      契约来源：FLOW_BUILDER_API_CONTRACT@EASYOPS 模型 Search 契约
      鉴权：免 cookie 直连——org/user/Host 三件 header（平台公约）

字段说明（响应 data.list[] 每项）：
  packageId      制品包全称 ID（如 docker.easyops.local/easyops/xxx）
  name           包名（搜索轴）
  type           包类型（7=镜像 等）
  provider       提供方（harbor 等）
  hostServiceName 制品服务名（如 docker.easyops.local）
  repoName       制品仓库名
  namespace      镜像命名空间
  lastVersionInfo 最新版本信息（name/versionId/env_type/ctime）
  instanceCount  关联实例数
  creator/realUser 创建者
  ctime/mtime    创建/修改时间
  installPath    安装路径
  labels         标签
  configEnvType  配置环境类型
  category       分类

使用（py2/py3 均可）：
  python search_artifact_package.py nginx                    # 模糊搜 name
  python search_artifact_package.py nginx --exact            # 精确匹配
  python search_artifact_package.py --type 7                 # 按类型列包
  python search_artifact_package.py nginx --page 2 --page-size 20
  python search_artifact_package.py nginx --json             # 输出原始 JSON
  python search_artifact_package.py nginx --host 172.30.0.90 --port 8175 --org 8888

环境变量（缺省时读取，agent 环境自带）：
  EASYOPS_HOST / EASYOPS_ORG / EASYOPS_USER / EASYOPS_ARTIFACT_PORT
"""

from __future__ import print_function

import argparse
import json
import logging
import os
import sys

# ---------- py2/3 兼容 ----------
PY2 = sys.version_info[0] == 2
if PY2:
    from urllib import urlencode
    from urllib2 import urlopen, Request, URLError
else:
    from urllib.parse import urlencode
    from urllib.request import urlopen, Request
    from urllib.error import URLError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("search_artifact_package")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_ARTIFACT_PORT = 8175          # 名字服务 logic.artifact 端口
VHOST = "admin.easyops.local"         # 网关按 Host 路由的虚拟主机名

# 表格列：(显示名, 取值 jsonPath 列表, 宽度)
COLUMNS = [
    ("name", ["name"], 34),
    ("type", ["type"], 5),
    ("provider", ["provider"], 9),
    ("repoName", ["repoName"], 16),
    ("lastVersion", ["lastVersionInfo", "name"], 14),
    ("instanceCount", ["instanceCount"], 8),
    ("packageId", ["packageId"], 0),   # 宽度 0 = 弹性列（占剩余宽度）
]


def _getenv(key, default=""):
    v = os.environ.get(key, "")
    return v if v else default


def build_params(args):
    """把 CLI 参数拼成 /package/search 的 query 参数。"""
    params = {"page": args.page, "pageSize": args.page_size}
    if args.name:
        params["name"] = args.name
        if args.exact:
            params["exact"] = "true"
    if args.type:
        params["type"] = args.type
    if args.creator:
        params["creator"] = args.creator
    if args.labels:
        params["packageLabels"] = ",".join(args.labels)
    if args.order:
        params["order"] = args.order
    return params


def search(args):
    """调 /package/search，返回 (total, list)。"""
    base = "http://%s:%s/package/search" % (args.host, args.port)
    qs = urlencode(build_params(args))
    url = "%s?%s" % (base, qs) if qs else base
    logger.debug("GET %s", url)

    req = Request(url)
    req.add_header("Host", VHOST)          # 三件 header 直连（免 cookie）
    req.add_header("org", str(args.org))
    req.add_header("user", args.user)
    try:
        resp = urlopen(req, timeout=args.timeout)
        body = resp.read()
    except URLError as e:
        logger.error("请求失败: %s（检查 host/port/网络）", e)
        sys.exit(2)
    if not isinstance(body, str):
        body = body.decode("utf-8")
    data = json.loads(body)
    if data.get("code") != 0:
        logger.error("接口报错 code=%s error=%s", data.get("code"), data.get("error") or data.get("message"))
        sys.exit(3)
    d = data.get("data") or {}
    return d.get("total", 0), d.get("list") or []


def _pick(row, path):
    o = row
    for k in path:
        if not isinstance(o, dict):
            return ""
        o = o.get(k, "")
    return o if o is not None else ""


def _to_text(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return u"%s" % (v,)


def render_table(rows):
    """无第三方依赖的简易表格渲染（自适应宽度，最后一列弹性）。"""
    extracted = []
    for r in rows:
        extracted.append([_to_text(_pick(r, path)) for _, path, _ in COLUMNS])
    fixed = [w for _, _, w in COLUMNS]
    flex_idx = fixed.index(0)
    widths = [max(len(c) for c in col) if len(col) else 0 for col in zip(*extracted)] if extracted else []
    # 表头参与宽度计算
    header = [t for t, _, _ in COLUMNS]
    for i, h in enumerate(header):
        if i < len(widths):
            widths[i] = max(widths[i], len(h))
    # 固定列截断到声明宽度，弹性列不截
    widths = [min(widths[i], fixed[i]) if fixed[i] else widths[i] for i in range(len(widths))]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep, "|" + "|".join(" %-*s " % (w, h) for w, h in zip(widths, header)) + "|", sep]
    for row in extracted:
        cells = []
        for i, c in enumerate(row):
            c = c[: widths[i]] if widths[i] else c
            cells.append(" %-*s " % (widths[i], c))
        lines.append("|" + "|".join(cells) + "|")
    lines.append(sep)
    out = "\n".join(lines)
    if PY2:
        out = out.encode("utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="CICD artifact 程序包搜索（GET /package/search）")
    ap.add_argument("name", nargs="?", default="", help="包名关键词（默认模糊匹配）")
    ap.add_argument("--exact", action="store_true", help="精确匹配 name（默认模糊）")
    ap.add_argument("--type", dest="type", default="", help="包类型（如 7=镜像）")
    ap.add_argument("--creator", default="", help="创建者过滤")
    ap.add_argument("--labels", nargs="*", default=[], help="标签过滤，格式 key:value（可多个）")
    host_default = _getenv("EASYOPS_HOST", DEFAULT_HOST)
    ap.add_argument("--host", default=host_default, help="EasyOps 服务器地址（默认 env EASYOPS_HOST 或 127.0.0.1）")
    port_default = _getenv("EASYOPS_ARTIFACT_PORT", str(DEFAULT_ARTIFACT_PORT))
    ap.add_argument("--port", default=port_default, help="artifact 组件端口（默认 env EASYOPS_ARTIFACT_PORT 或 8175）")
    ap.add_argument("--org", default=_getenv("EASYOPS_ORG", ""), help="组织 ID（默认 env EASYOPS_ORG）")
    ap.add_argument("--user", default=_getenv("EASYOPS_USER", "easyops"), help="用户名（默认 env EASYOPS_USER）")
    ap.add_argument("--page", type=int, default=1, help="页码（默认 1）")
    ap.add_argument("--page-size", type=int, default=20, help="每页条数（默认 20）")
    ap.add_argument("--order", default="", help="排序：{field} {desc|asc}（如 'name desc'）")
    ap.add_argument("--timeout", type=int, default=10, help="HTTP 超时秒数（默认 10）")
    ap.add_argument("--json", dest="as_json", action="store_true", help="输出原始 JSON（不走表格）")
    args = ap.parse_args()

    if not args.org:
        logger.error("缺少 org：传 --org 或设 EASYOPS_ORG 环境变量")
        sys.exit(4)

    total, rows = search(args)
    if args.as_json:
        print(json.dumps({"total": total, "list": rows}, ensure_ascii=False, indent=2))
        return
    if not rows:
        logger.info("无匹配程序包（total=0）——换关键词/过滤条件，或检查 org")
        return
    logger.info("命中 %d 条（当前页 %d 条）", total, len(rows))
    print(render_table(rows))


if __name__ == "__main__":
    main()
