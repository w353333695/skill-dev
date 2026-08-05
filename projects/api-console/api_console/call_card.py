#!/usr/bin/env python3
"""单步真调 CLI：LLM 反应式探查 / 决策用。

补「极轻问答 -> 单步真调 -> 极重 DAG」中间档。LLM 在对话循环里反复调用本脚本，
每次拿一个接口的原始 ``body.data`` + 诊断 meta，自主分析后决定下一步——无需提前
声明整个 DAG。

设计：
- 参数只接受字面量（不解析 ``${}`` 表达式，单步无上游 step）。
- 默认只读（与 execute_dag 的 MVP-1 边界一致）；``--allow-write`` 受控放行 write。
- 业务码非 0 **不报错**：探查/反应式场景下"查不到"是正常信息，meta 透出 code/message，
  交 LLM 决策，而非当作失败终止。
- 复用 invoke_card（card_invoker）请求层 + discover_adapters/manifest/auth 全链路。

用法：
    run.sh call_card.py --platform <platform> --card <name> [--param k=v]...
                        [--param-json k=<JSON>]... [--allow-write] [--env <env>]

参数类型：
- ``--param k=v`` 值默认为字符串字面量。对卡片声明了标量类型的字段会自动强转：
  bool/boolean -> 真 bool（true/false/1/0/yes/no，大小写不敏感）；
  int/int64/integer/page/page_size/Limit -> int；number -> float。
  其余类型（string/array/object/pseudo_bool 等）原样字符串。
- ``--param-json k=<JSON>`` 用 json.loads 解析为原生值（数组/对象/显式类型），
  覆盖同 key 的 --param。例：--param-json roles='["admin"]'。
  schema 强转管不到的复杂类型走此逃逸口。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

from api_console.schema.card import Card
from api_console.adapter_base import discover_adapters
from api_console.card_invoker import invoke_card, InvokeResult  # noqa: F401  （re-export 供测试）
from api_console.manifest_loader import load_manifest


def parse_args(argv):
    """解析 CLI 参数。"""
    p = argparse.ArgumentParser(
        prog="api-console call-card",
        description="单步真调：调一张卡片，输出原始 body.data + meta",
    )
    p.add_argument("--platform", required=True, help="平台名（platforms/<platform>）")
    p.add_argument("--card", required=True, help="卡片 name（registry/_index.yaml）")
    p.add_argument("--param", action="append", default=[],
                   help="请求参数，key=value 形式，可重复（字面量，不解析 ${}）；"
                        "value 以 @ 开头时读该路径文件内容为值；"
                        "声明了 bool/int/number 类型的字段会自动强转（见文件头）")
    p.add_argument("--param-json", action="append", default=[], metavar="KEY=JSON",
                   help="请求参数，key=JSON 形式，可重复；json.loads 解析为原生值"
                        "（数组/对象/显式类型），覆盖同 key 的 --param")
    p.add_argument("--allow-write", action="store_true",
                   help="放行 side_effect != read 的卡片（默认拒绝 write）")
    p.add_argument("--out", default="",
                   help="非 JSON（二进制）响应的保存路径；缺省 tmp/orchestrate/download/<card>_<时间戳>.<ext>（相对 API_CONSOLE_WORKDIR）")
    p.add_argument("--env", default="",
                   help="环境名（多环境 manifest 选环境；不传用 default_env）")
    return p.parse_args(argv)


def parse_params(param_list):
    """['k=v', 'a=b', 'c=@file'] -> dict。值字面量；``@路径`` 读文件内容为值。

    值里允许含 ``=``（只在第一个 ``=`` 处切分）。非 ``key=value`` 形式 die。
    ``@`` 读文件失败 die。
    """
    out = {}
    for kv in param_list:
        if "=" not in kv:
            die("--param 必须是 key=value 形式：" + kv)
        k, v = kv.split("=", 1)
        if v.startswith("@"):
            fp = Path(v[1:])
            try:
                out[k] = fp.read_text(encoding="utf-8")
            except OSError:
                die("--param " + k + " 的 @文件读不到：" + str(fp))
        else:
            out[k] = v
    return out


# 标量类型强转表：CLI 字符串 -> 卡片声明的原生类型。
# 只转无歧义的标量；array/object/pseudo_bool 等维持字符串（--param-json 逃逸口处理）。
_SCALAR_BOOL = {"bool", "boolean"}
_SCALAR_INT = {"int", "int64", "integer", "page", "page_size", "Limit"}


def _coerce_value(v, declared_type, key=""):
    """按卡片声明的字段类型把 CLI 字符串值转成原生类型。

    不认识 / 无声明 -> 原样字符串（保持旧行为，零回归）。
    值无法转为声明类型 -> die（fail loud，不静默回退成字符串）。
    """
    t = (declared_type or "").strip()
    where = "--param {0}=".format(key) if key else "--param"
    if t in _SCALAR_BOOL:
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "y", "t"):
            return True
        if s in ("false", "0", "no", "n", "f", ""):
            return False
        die("{0} bool 值非法（期望 true/false/1/0/yes/no）：{1!r}".format(where, v))
    if t in _SCALAR_INT:
        try:
            return int(v)
        except (ValueError, TypeError):
            die("{0} int 值非法：{1!r}".format(where, v))
    if t == "number":
        try:
            return float(v)
        except (ValueError, TypeError):
            die("{0} number 值非法：{1!r}".format(where, v))
    return v


def coerce_params(params, card):
    """按卡片 request.properties 把 CLI 字符串参数强转为声明类型。

    只对卡片 schema 里声明了标量类型的 key 生效；未声明的 key 原样透传。
    """
    props = card.request_properties or {}
    out = {}
    for k, v in params.items():
        p = props.get(k)
        t = p.get("type") if isinstance(p, dict) else getattr(p, "type", "")
        out[k] = _coerce_value(v, t, k)
    return out


def parse_param_json(param_json_list):
    """['k=JSON', ...] -> dict。值经 json.loads 解析为原生类型。

    非法 JSON -> die。``=`` 仅在第一个处切分（JSON 值可含 ``=``）。
    """
    out = {}
    for kv in param_json_list:
        if "=" not in kv:
            die("--param-json 必须是 key=JSON 形式：" + kv)
        k, raw = kv.split("=", 1)
        try:
            out[k] = json.loads(raw)
        except json.JSONDecodeError as e:
            die("--param-json " + k + " 的 JSON 解析失败：" + str(e))
    return out


# 常见二进制 Content-Type -> 扩展名映射（推断不出时回退 .bin）
_CONTENT_TYPE_EXT = {
    "application/gzip": ".tar.gz",
    "application/x-gzip": ".tar.gz",
    "application/octet-stream": ".bin",
    "application/zip": ".zip",
}


def _download_base():
    """下载根目录：tmp/orchestrate/download（相对 workdir）。"""
    return _workdir() / "tmp" / "orchestrate" / "download"


def _ext_from_response(resp):
    """从 Content-Disposition filename 或 Content-Type 推断扩展名。"""
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        name = cd.split("filename=", 1)[1].strip().strip('"').split(";")[0]
        if "." in name:
            return "." + name.rsplit(".", 1)[1]
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    return _CONTENT_TYPE_EXT.get(ctype, ".bin")


def _default_download_path(card_name, resp):
    """默认下载路径：<下载根>/<card>_<时间戳>.<ext>。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    return _download_base() / (card_name + "_" + ts + _ext_from_response(resp))


def die(msg, code=1):
    """打印错误到 stderr 并退出。"""
    print(msg, file=sys.stderr)
    sys.exit(code)


def _workdir():
    """产物根：run.sh 钉死的 API_CONSOLE_WORKDIR，缺省回退 cwd。"""
    return Path(os.environ.get("API_CONSOLE_WORKDIR", os.getcwd()))


def _platform_dir(platform):
    return _workdir() / "platforms" / platform


def load_cards(platform):
    """从 registry/_index.yaml 加载全部卡片 -> {name: Card}。"""
    registry = _platform_dir(platform) / "registry"
    idx_path = registry / "_index.yaml"
    if not idx_path.exists():
        die("未找到 registry/_index.yaml：" + str(idx_path))
    idx = yaml.safe_load(idx_path.read_text()) or {}
    cards = {}
    for m in idx.get("modules", []):
        for c in m.get("cards", []):
            name = c["name"]
            if name in cards:
                print(f"[call_card] ⚠️ 卡片 {name} 跨 module 同名，后者覆盖前者"
                      f"（现用 module={m['name']}）", file=sys.stderr)
            cards[name] = Card.from_dict(
                yaml.safe_load((registry / c["file"]).read_text()))
    return cards


def load_platform(platform, env=""):
    """discover_adapters + load_manifest(env) -> (adapter, manifest)。

    Args:
        platform: 平台名（platforms/<platform>）。
        env: 环境名；空串用 manifest 的 default_env（旧形态单环境忽略）。
    """
    platform_dir = _platform_dir(platform)
    adapters = discover_adapters(platform_dir / "sources/backend/adapters")
    if not adapters:
        die("未发现 adapter（" + str(platform_dir / "sources/backend/adapters") + "）")
    try:
        manifest = load_manifest(platform_dir, env or None)
    except ValueError as e:
        die(str(e))
    return adapters[0], manifest


def load_contracts(platform):
    """读 contracts.yaml（list 或 dict，归一化由 invoke_card 完成）。"""
    contracts_path = _platform_dir(platform) / "sources/backend/parsed/contracts.yaml"
    if not contracts_path.exists():
        return []
    return yaml.safe_load(contracts_path.read_text()) or []


def main(argv=None):
    """CLI 入口。"""
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # 先加载平台（adapter + manifest）：env 错误在此暴露，早于卡片解析
    adapter, manifest = load_platform(args.platform, args.env)

    cards = load_cards(args.platform)
    if args.card not in cards:
        die("未知卡片：" + args.card)
    card = cards[args.card]
    # 1) --param：字面量字符串 -> 按卡片声明类型强转（bool/int/number）
    params = coerce_params(parse_params(args.param), card)
    # 2) --param-json：原生 JSON 值覆盖（数组/对象/显式类型，无需强转）
    params.update(parse_param_json(args.param_json))

    # 必填参数校验（--param 与 --param-json 合并后判定）
    missing = [r for r in card.request_required if r not in params]
    if missing:
        die("缺必填参数：" + ",".join(missing) + "（卡片 " + card.name + "）")

    # 只读约束：write 卡片需 --allow-write 显式确认
    if card.side_effect != "read" and not args.allow_write:
        die("卡片 " + card.name + " 是 " + card.side_effect
            + "，加 --allow-write 确认")

    contracts = load_contracts(args.platform)
    result = invoke_card(card, params, adapter, manifest, contracts)
    # 响应分流：仅当 Content-Type 是字符串且明确非 JSON 时才走下载落盘；
    # 其余（含缺省/异常头）维持旧的 JSON 解析行为（零影响既有路径）。
    ctype = result.resp.headers.get("Content-Type", "")
    if not isinstance(ctype, str) or "application/json" in ctype:
        body = result.resp.json()
        out = {
            "meta": {
                "card": card.name,
                "method": result.method,
                "url": result.url,
                "http_status": result.resp.status_code,
                "biz_code": body.get("code"),
                "biz_message": body.get("message") or body.get("error"),
            },
            "data": body.get("data"),
        }
    else:
        # 非 JSON（二进制/文件下载）响应：落盘并输出 {meta, file}
        path = Path(args.out) if args.out else _default_download_path(card.name, result.resp)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(result.resp.content)
        except OSError as e:
            die("下载落盘失败 " + str(path) + "：" + str(e))
        out = {
            "meta": {
                "card": card.name,
                "method": result.method,
                "url": result.url,
                "http_status": result.resp.status_code,
                "biz_code": None,
                "biz_message": "",
            },
            "file": {
                "file_path": str(path),
                "size": len(result.resp.content),
                "content_type": ctype,
            },
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
