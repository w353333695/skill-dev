"""后端资料 adapter 抽象层：Protocol + 目录扫描发现。

设计原则（spec 第 4 章）：
    - 通用层只认 ``BackendAdapter`` 接口，不耦合任何平台；
    - 平台相关解析逻辑以 ``adapters/<name>.py`` 形式落到各 platform 包；
    - discover_adapters 按目录扫描、import、实例化，所有 adapter 共用同一签名；
    - 置信度（Confidence）三级分流：HIGH 直接 parse，LOW 走 LLM 回退，ZERO 诚实反馈。

正则坑规避：本模块刻意不用反斜杠字符类（如 ``\\w``），统一用字符集 ``[a-zA-Z0-9_]``。
"""
from __future__ import annotations
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class Confidence(IntEnum):
    """adapter 对 raw_dir 的识别置信度，数值越大越可信。

    Attributes:
        ZERO: 完全不认识该资料格式（诚实反馈，提示用户提供结构化资料）。
        LOW: 半结构化（markdown / loose swagger），需 LLM 回退。
        HIGH: 强结构化（json 契约 / 标准 swagger），直接 parse。
    """

    ZERO = 0
    LOW = 1
    HIGH = 2


@dataclass
class DetectResult:
    """adapter.detect 返回值。

    Attributes:
        confidence: 识别置信度。
        reason: 人类可读原因（用于日志与诚实反馈）。
        matched_files: 命中的文件名列表（HIGH 时非空，便于回查/调试）。
    """

    confidence: Confidence
    reason: str = ""
    matched_files: list[str] = field(default_factory=list)


@dataclass
class Endpoint:
    """adapter.resolve_endpoint 返回值：execute_dag 直接可用的端点描述。

    spec 1.5 / 4.2：URL 怎么拼、用什么鉴权是平台差异最大的地方，
    全部封装在 adapter 内部，execute_dag 只消费 Endpoint，零平台耦合。

    Attributes:
        url: 完整可请求 URL（adapter 拼好，含网关前缀/端口等）。
        method: HTTP 方法（大写）。
        auth: 鉴权类型（``session_cookie|aksk|bearer|none``），
            execute_dag 按它从 manifest 取凭证。
        headers: 平台特定请求头（adapter 已拼好；execute_dag 只 merge 不改）。
    """

    url: str = ""
    method: str = "GET"
    auth: str = "none"
    headers: dict = field(default_factory=dict)


@runtime_checkable
class BackendAdapter(Protocol):
    """后端资料 adapter 接口契约。

    每个 platform adapter 需提供：
        - ``name``: adapter 标识（如 ``<format>_contract``）。
        - ``detect(raw_dir) -> DetectResult``: 评估对 raw_dir 的识别置信度。
        - ``parse(raw_dir) -> list[dict]``: 把 raw_dir 解析为若干 BackendContract
          字段 dict（由调用方套 dataclass）。
        - ``resolve_endpoint(contract, manifest) -> Endpoint``: 解析可真调端点
          （spec 1.5），把 URL 拼接/鉴权类型选择等平台差异封装在 adapter 内。
        - ``build_auth_headers(auth_mode, manifest, request_ctx=None) -> dict``:
          按鉴权方式构造请求头（spec 1.6），平台签名算法封在这里，execute_dag
          不认识 cookie/签名/org 的细节。

    实现约定：模块内定义 ``class Adapter:`` 满足本 Protocol，由 ``discover_adapters``
    实例化。Adapter 类不继承 Protocol（duck typing），runtime_checkable 仅做结构检查。
    """

    name: str

    def detect(self, raw_dir: Path) -> DetectResult:
        """评估对 raw_dir 的识别置信度。"""
        ...

    def parse(self, raw_dir: Path) -> list[dict]:
        """把 raw_dir 解析为若干 BackendContract 字段 dict。"""
        ...

    def resolve_endpoint(self, contract: dict, manifest: dict) -> Endpoint:
        """解析可真调端点（spec 1.5）。

        Args:
            contract: 单条后端契约 dict（service/method/path 等字段），
                由 execute_dag 从 contracts.yaml 查得；可能附带卡片侧的
                ``endpoint.mode`` 提示。
            manifest: 平台 manifest.yaml 反序列化结果（含 gateway_base/auth 等）。

        Returns:
            :class:`Endpoint`（含 url/method/auth/headers），execute_dag 直接用。
        """
        ...

    def resolve_call_mode(self, card, contracts: dict) -> str:
        """决定卡片调用 mode（spec 1.7，平台特定决策，归 adapter）。

        不同平台有不同的调用模式（如内网直连 / 网关代理 / 签名），「该用哪种」
        是平台特定决策——由各平台 adapter 根据自身能力 + 契约信息决定，
        **主干不做此决策**（主干不认识任何平台的 mode 名）。

        默认实现：沿用卡片注册时自带的 ``endpoint.mode``；若为空返回空串
        （由 adapter 在 ``resolve_endpoint`` 里用自身默认 mode 兜底）。
        需要"按契约信息动态选 mode"的平台（如据端口选直连/网关）override 本方法。

        Args:
            card: Card 对象（可读 card.endpoint / card.service 等）。
            contracts: operation_key -> contract dict（含 service/port 等）。

        Returns:
            mode 字符串（具体取值由各平台 adapter 定义，主干不解释）。
        """
        ep = getattr(card, "endpoint", None) or {}
        return ep.get("mode", "")

    def build_auth_headers(self, auth_mode: str, manifest: dict,
                           request_ctx: dict | None = None) -> dict:
        """按鉴权方式构造请求头（spec 1.6），execute_dag 调用，零平台耦合。

        URL 拼接归 ``resolve_endpoint``，鉴权头构造归本方法，平台签名算法
        （如 HMAC-SHA1）封在这里，execute_dag 不认识 cookie/签名/org 的细节。

        Args:
            auth_mode: 鉴权模式（即 :class:`Endpoint.auth`），如
                ``session_cookie`` / 平台 adapter 自定义的鉴权模式名 /
                ``none``。由 resolve_endpoint 返回值决定。
            manifest: manifest.yaml 反序列化结果（含 ``auth`` 配置：cookie_file
                / internal.org / aksk.ak/sk/port_app_map 等）。
            request_ctx: 签名模式（aksk）用，含 ``{method, url, body}``：
                - method: HTTP 方法（用于决定是否拼 Content-MD5）；
                - url: 完整 URL（用于算签名 uri）；
                - body: 请求体（用于算 Content-MD5）。
                非签名模式忽略此参数。

        Returns:
            鉴权请求头 dict（execute_dag 合并到请求 headers）。

        Raises:
            NotImplementedError: 平台未支持该 auth_mode，或 manifest 缺该模式
                必需的配置项（如 aksk 未配 ak/sk）。
        """
        ...


# 合法 Python 标识符：用字符集替代 \w，规避 Write 工具翻倍反斜斜杠的坑
_IDENT_RE = re.compile("^[a-zA-Z_][a-zA-Z0-9_]*$")


def discover_adapters(adapters_dir: Path) -> list[BackendAdapter]:
    """从 adapters_dir 扫描 *.py 模块，实例化其中的 ``Adapter`` 类。

    约定：
        - 每个 adapter 一个 .py 文件，文件内定义 ``class Adapter:``；
        - 下划线开头的模块（``_xxx.py``）跳过（私有/辅助模块）；
        - ``__init__.py`` 跳过（包标识文件）；
        - 模块不含 ``Adapter`` 类或类无 ``name`` 属性则跳过；
        - 加载失败的模块打印警告、不抛异常（单 adapter 挂不应影响其他 adapter）。

    Args:
        adapters_dir: adapter 目录，如 ``platforms/<platform>/sources/backend/adapters``。

    Returns:
        已实例化的 adapter 列表（按文件名字母序）。
    """
    adapters: list[BackendAdapter] = []
    if not adapters_dir.exists():
        return adapters

    for py in sorted(adapters_dir.glob("*.py")):
        # 跳过下划线开头和 __init__
        if py.name.startswith("_"):
            continue
        if py.name == "__init__.py":
            continue
        mod_name = py.stem
        if not _IDENT_RE.match(mod_name):
            continue
        try:
            cls = _load_adapter_class(py, mod_name)
            if cls is None:
                continue
            inst = cls()
            # 没有 name 属性的当成不合法 adapter 跳过
            if not hasattr(inst, "name"):
                continue
            adapters.append(inst)
        except Exception as e:  # noqa: BLE001
            # 单个 adapter 加载失败不影响其他，给可观察的 stderr 提示
            import traceback
            print(
                f"[adapter_base] 跳过 {py.name}：加载失败 {type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}",
                file=sys.stderr,
            )
            continue
    return adapters


def _load_adapter_class(py_path: Path, mod_name: str) -> Any:
    """按文件路径 import 模块，返回其中的 ``Adapter`` 类（找不到返回 None）。

    用 importlib.util.spec_from_file_location 按路径加载，避免与全局 sys.modules
    中的重名模块冲突。
    """
    spec = importlib.util.spec_from_file_location(mod_name, py_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # 注入 sys.modules 防止 import 时部分场景找不到模块
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return getattr(module, "Adapter", None)
