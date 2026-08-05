# browser_recorder/auth/scope.py
"""登录态 scope 匹配：按 registrable domain + host 范围匹配，端口/子域/路径变化可容。"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse

# 已知多段公共后缀（简化表；生产可换 tldextract）
_MULTI_SUFFIXES = {
    "co.uk", "ac.uk", "gov.uk", "com.cn", "net.cn", "org.cn", "com.au", "co.jp",
}


@dataclass
class ParsedUrl:
    scheme: str
    host: str
    port: int | None
    path: str


def parse_url(url: str) -> ParsedUrl:
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port
    return ParsedUrl(scheme=p.scheme or "", host=host, port=port, path=p.path or "/")


def registrable_domain(host: str) -> str:
    """公共后缀 +1。已知多段后缀取三段，否则取两段。"""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last2 = ".".join(parts[-2:])
    if last2 in _MULTI_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last2


def matches(target_url: str, scope_dict: dict) -> bool:
    """判断 target_url 是否落在 profile 的 scope 内。"""
    u = parse_url(target_url)

    # 协议
    allowed_schemes = scope_dict.get("scheme") or ["https"]
    if u.scheme not in allowed_schemes:
        return False

    # host 匹配
    host_match = scope_dict.get("host_match", "suffix")
    hosts = scope_dict.get("hosts") or []
    if host_match == "exact":
        host_ok = u.host in hosts
    else:  # suffix：同 registrable domain 或精确后缀命中
        reg = scope_dict.get("registrable_domain")
        if reg:
            host_ok = registrable_domain(u.host) == reg or any(
                u.host == h or u.host.endswith("." + h) for h in hosts)
        else:
            host_ok = any(u.host == h or u.host.endswith("." + h) for h in hosts)
    if not host_ok:
        return False

    # 端口：cookie 不区分端口 → 不作为强约束（ports 字段仅记录，不影响匹配）

    # 路径前缀：可选收窄
    prefixes = scope_dict.get("path_prefix")
    if prefixes:
        if not any(u.path == p or u.path.startswith(p.rstrip("/") + "/") or u.path == p.rstrip("/")
                   for p in prefixes):
            return False
    return True
