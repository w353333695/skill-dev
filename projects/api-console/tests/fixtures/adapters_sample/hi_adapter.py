"""测试用假 adapter：detect 恒返回 HIGH。

仅供 adapter_base 单元测试 discover_adapters 使用：验证目录扫描能找到
合法 adapter、跳过下划线开头模块、Protocol runtime check 通过。
"""
from __future__ import annotations
from pathlib import Path
from api_console.adapter_base import Confidence, DetectResult, Endpoint


class Adapter:
    """假 adapter，name=hi，detect/parse/resolve_endpoint/build_auth_headers 返回固定值。"""

    name = "hi"

    def detect(self, raw_dir: Path) -> DetectResult:
        """恒返回 HIGH 置信度，便于测试选最高置信度的分流。"""
        return DetectResult(confidence=Confidence.HIGH, reason="fake hi")

    def parse(self, raw_dir: Path) -> list[dict]:
        """返回单条假契约。"""
        return [{"operation_key": "x|GET|/x", "method": "GET", "path": "/x"}]

    def resolve_endpoint(self, contract: dict, manifest: dict) -> Endpoint:
        """假 resolve：url = api_base + path（standard 模式）。"""
        api_base = manifest.get("api_base", "http://fake")
        path = contract.get("path", "/x")
        return Endpoint(
            url=api_base + path,
            method=contract.get("method", "GET"),
            auth="none",
            headers={},
        )

    def build_auth_headers(self, auth_mode: str, manifest: dict,
                           request_ctx: dict | None = None) -> dict:
        """假 build_auth_headers：none 模式返回空 dict（不注入）。

        spec 1.6：每个 adapter 必须实现本方法（与 resolve_endpoint 并列）。
        """
        if auth_mode == "none":
            return {}
        raise NotImplementedError(f"hi fixture 不支持 auth_mode={auth_mode}")

    def resolve_call_mode(self, card, contracts: dict) -> str:
        """假 resolve_call_mode：沿用卡片自带 endpoint.mode（主干默认行为）。"""
        ep = getattr(card, "endpoint", None) or {}
        return ep.get("mode", "")
