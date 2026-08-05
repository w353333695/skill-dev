"""卡片请求层（单一职责：卡片 -> HTTP 请求 -> 发出）。

从 execute_dag 抽出，execute_dag（DAG 编排）与 call_card（单步真调）共用。
本模块只负责"把一张卡片变成一次 HTTP 请求并发出"，不碰业务码校验、不碰
outputs 锚点提取——那些是调用方（execute_dag 的 _exec_one / call_card）的事。

零平台耦合（spec 1.6）：URL 拼接归 adapter.resolve_endpoint，鉴权头构造归
adapter.build_auth_headers，本模块只调 adapter 拿 Endpoint + headers 再发请求。

adapter 约定伪头：build_auth_headers 返回的 dict 若含 ``__url_query__``，
值为 urlencode 后的签名 query 字符串（aksk 模式），本模块取出附加到 URL，
不进入真实 HTTP 头。
"""
from __future__ import annotations
from dataclasses import dataclass

import httpx

from api_console.schema.card import Card
from api_console.adapter_base import BackendAdapter, Endpoint


# adapter 与请求层的约定伪头键：build_auth_headers 返回的 dict 若含此键，
# 值为 urlencode 后的签名 query 字符串（aksk 模式），取出附加到 URL，不进入
# 真实 HTTP 头。spec 1.6 的零平台耦合约定。
_URL_QUERY_PSEUDO_HEADER = "__url_query__"


@dataclass
class InvokeResult:
    """invoke_card 返回值：原始 resp + 诊断 meta（调用方据此构造输出）。

    Attributes:
        resp: httpx.Response（调用方取 .json() / .status_code）。
        url: 实际请求 URL（path 占位替换 + 签名 query 附加后的最终 URL）。
        method: HTTP 方法（大写，来自 Endpoint.method）。
    """
    resp: object
    url: str
    method: str


# 模块级请求封装：便于测试 patch（patch("card_invoker.http_request", fake)）
def http_request(method: str, url: str, headers=None, **kw):
    """httpx 同步请求封装（单次 Client，30s 超时）。

    内网平台普遍用自签名证书（如 172.30.x.x），SSL 校验会失败（CERTIFICATE_VERIFY_FAILED）。
    统一 verify=False 放行，不校验证书 —— 鉴权由平台头/cookie 承担，证书信任留给网络层。
    调用方可通过 ``verify`` kwarg 覆盖（测试等）。
    """
    with httpx.Client(timeout=30, verify=kw.pop("verify", False)) as c:
        return c.request(method, url, headers=headers, **kw)


def _normalize_contracts(contracts) -> dict:
    """归一化 contracts 为 contract_ref -> contract dict 映射。

    接受两种输入（调用方省心，不必预处理 contracts.yaml）：
    - list：parse_backend 产出的 contracts.yaml 原始格式（每条含 operation_key）
    - dict：已是映射（原样返回）

    list 转 dict 按 operation_key 建索引。
    """
    if not contracts:
        return {}
    if isinstance(contracts, dict):
        return contracts
    if isinstance(contracts, list):
        out = {}
        for c in contracts:
            if not isinstance(c, dict):
                continue
            key = c.get("operation_key")
            if key:
                out[key] = c
        return out
    return {}


def _build_request_kwargs(card, params, is_get):
    """按卡片与参数构造 httpx 请求 kw（params/json/multipart 三选一）。

    纯增量：GET->params；POST 等无 file 参数->json；含 type:file 参数->multipart。
    type:file 参数值：字符串=本地路径；dict（DAG 文件对象）取 .file_path。
    """
    if is_get:
        return {"params": params}
    file_keys = [
        k for k, p in (card.request_properties or {}).items()
        if (p.get("type") if isinstance(p, dict) else getattr(p, "type", "")) == "file"
    ]
    if not file_keys:
        return {"json": params}
    files, data = {}, {}
    for k, v in params.items():
        if k in file_keys:
            path = v.get("file_path") if isinstance(v, dict) else v
            if not path:
                # dict 缺 file_path 键 / 值为空：给友好错误，而非 open(None) 的 TypeError
                raise ValueError(
                    "卡片 %s 的文件参数 %s 缺少有效的文件路径（值：%r）"
                    % (card.name, k, v)
                )
            try:
                files[k] = open(path, "rb")
            except OSError:
                raise ValueError(
                    "卡片 %s 的文件参数 %s 指向的路径不存在或不可读：%s"
                    % (card.name, k, path)
                )
        else:
            data[k] = v
    return {"files": files, "data": data}


def invoke_card(card: Card, params: dict, adapter: BackendAdapter,
                manifest: dict, contracts) -> InvokeResult:
    """对单张卡片发一次请求，返回原始 resp + 诊断 meta。

    params 已是解析后的字面量 dict（``${}`` 由调用方预先解析；call_card 直接传
    CLI 字面量，execute_dag 的 _exec_one 先 _resolve_params 再传入）。本函数不解析 ``${}``。

    流程：
      1. 归一化 contracts（list/dict -> dict）
      2. _resolve_endpoint(card, adapter, manifest, contracts) -> Endpoint
      3. path 占位替换：url 中 ``{modelId}`` 用 ``params["modelId"]`` 替换
      4. GET -> query；其余 -> json body
      5. adapter.build_auth_headers(endpoint.auth, manifest, request_ctx)
      6. ``__url_query__`` 签名伪头取出附加到 URL
      7. http_request(method, url, headers, ...) -> resp

    Args:
        card: 待调用的卡片。
        params: 解析后的参数 dict（字面量）。
        adapter: 平台 adapter 实例。
        manifest: manifest.yaml 反序列化结果。
        contracts: contract_ref -> contract dict 映射，或 parse_backend 产出的
            list（内部归一化）。

    Returns:
        InvokeResult（resp/url/method），不含业务码判断 / 锚点提取。
    """
    contracts = _normalize_contracts(contracts)
    endpoint = _resolve_endpoint(card, adapter, manifest, contracts)
    url = endpoint.url
    # path 参数替换：url 中的 {modelId} 占位用 params["modelId"] 替换
    for k, v in list(params.items()):
        token = "{" + k + "}"
        if token in url:
            url = url.replace(token, str(v))
    # GET -> query；其余按卡片 request_properties 决定 json 或 multipart
    is_get = endpoint.method == "GET"
    kw = _build_request_kwargs(card, params, is_get)
    # 鉴权头：调 adapter（spec 1.6），平台签名算法封在 adapter，本模块零耦合。
    request_ctx = {
        "method": endpoint.method,
        "url": url,
        "body": None if is_get else params,
    }
    auth_headers = adapter.build_auth_headers(endpoint.auth, manifest, request_ctx)
    # 签名模式（aksk）通过伪头 __url_query__ 透传签名 query 字符串（约定）。
    url_query = auth_headers.pop(_URL_QUERY_PSEUDO_HEADER, None)
    if url_query:
        url = url + ("&" if "?" in url else "?") + url_query
    req_headers = dict(endpoint.headers)
    req_headers.update(auth_headers)
    # multipart 分支：剔除鉴权头里的 Content-Type，让 httpx 自填
    # multipart/form-data; boundary=...（否则覆盖成 application/json 导致服务端拒收）。
    if kw.get("files"):
        req_headers.pop("Content-Type", None)
    try:
        resp = http_request(endpoint.method, url, headers=req_headers, **kw)
    finally:
        # multipart 分支打开的文件句柄在此关闭（无论请求成败）
        for fh in (kw.get("files") or {}).values():
            try:
                fh.close()
            except Exception:
                pass
    return InvokeResult(resp=resp, url=url, method=endpoint.method)


def resolve_call_mode(adapter, card, contracts: dict) -> str:
    """决定卡片调用 mode（委托给 adapter，平台特定决策不归主干）。

    主干不认识任何平台的 mode 名（如内网直连/网关/签名怎么选是平台能力差异）。
    直接调 ``adapter.resolve_call_mode``：adapter 据自身能力 + 契约信息决定；
    adapter 未 override 时基类默认返回卡片自带的 ``endpoint.mode``。

    Args:
        adapter: BackendAdapter 实例（提供 resolve_call_mode）。
        card: Card 对象。
        contracts: operation_key -> contract dict。

    Returns:
        mode 字符串（具体取值由 adapter 定义，主干不解释）。
    """
    return adapter.resolve_call_mode(card, contracts)


def _resolve_endpoint(card: Card, adapter: BackendAdapter,
                      manifest: dict, contracts: dict) -> Endpoint:
    """对单张卡片调 adapter.resolve_endpoint 拿可请求 Endpoint。

    优先用 card.endpoint.contract_ref 从 contracts 查后端契约；未命中或
    contract_ref 为空时，用 card 自身字段构造兜底 contract（service/method/path
    + endpoint.mode），保证 adapter 拿得到 resolve 必需的最小信息。

    mode 由 adapter.resolve_call_mode 决定（平台特定，主干不解释 mode 取值）。
    """
    ep_cfg = dict(card.endpoint or {})
    # mode 选择委托给 adapter（平台特定决策，主干不认识 mode 名）
    ep_cfg["mode"] = resolve_call_mode(adapter, card, contracts)
    # 卡片 method 透传给 adapter：契约 method 可能是平台标记（如 ENS 的 LIST 实为
    # GET），卡片 method 才是标准 HTTP 方法，adapter resolve_endpoint 应优先用之。
    ep_cfg["method"] = card.method
    contract_ref = ep_cfg.get("contract_ref", "")
    contract = contracts.get(contract_ref) if contract_ref else None
    if contract is None:
        # 兜底：用 card 字段构造最小 contract dict（adapter resolve 只读
        # service/method/path/endpoint.mode）
        contract = {
            "service": card.service,
            "method": card.method,
            "path": card.path,
            "endpoint": ep_cfg,
        }
    else:
        # 把卡片侧 endpoint.mode 合并进 contract（adapter 据此选 resolve 分支）
        merged = dict(contract)
        merged["endpoint"] = ep_cfg
        contract = merged
    return adapter.resolve_endpoint(contract, manifest)
