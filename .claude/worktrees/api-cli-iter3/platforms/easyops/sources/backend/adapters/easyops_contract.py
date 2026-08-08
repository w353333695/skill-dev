"""EasyOps 契约 adapter（首个平台 adapter，耦合 easyops 数据格式）。

输入（raw_dir 下）：
    - ``*CONTRACT*.json`` 或 ``*easyops_contract*.json``：FLOW_BUILDER_API_CONTRACT
      契约数组（每条含 ``serviceName`` / ``endpoint`` / ``request`` / ``response``）。
    - ``*ROUTING*.json``：ENS_ROUTING_TABLE 路由数组（含 ``contract`` + ``port``）。

输出：``list[dict]``，每条字段对齐 ``schema.contracts.BackendContract``。

关键约定（基于真实数据）：
    - 契约 ``serviceName`` 形如 ``logic.flowable_service``（带 logic. 前缀）。
    - ENS 路由无 ``serviceName``，靠 ``contract`` 字段关联端口
      （契约 serviceName 直接对应 ENS contract，可匹配）。
    - 契约 ``endpoint.uri`` 可能是 colon style（``:instanceId``），必须经
      ``path_align.normalize_path`` 归一化为 brace style。
    - 契约 ``request/response`` 各含 ``fields`` 列表，field 含 ``name``/``type``/
      ``description``，缺 description 的字段记入 ``semantic_gaps`` 供 LLM 补语义。

鉴权三分支（spec 1.6，build_auth_headers）：
    - ``session_cookie``：优先 manifest.auth.session_cookie.cookie（明文），兜底 cookie_file。
    - ``easyops_internal``：内网直连，user/org/Content-Type 头（不依赖 cookie/签名）。
    - ``easyops_aksk``：HMAC-SHA1 签名（参考 sources/raw/backend/api-samples.py），无 ak/sk 抛
      NotImplementedError。

签名算法的 URL query 透传约定：aksk 模式下，``build_auth_headers`` 返回的 dict
里包含伪头 ``__url_query__``（urlencode 后的签名 query 字符串）。execute_dag 取出
后附加到 URL，不进入真实 HTTP 头。这是 adapter 与 execute_dag 之间的约定，便于
execute_dag 保持零平台耦合（不认识 HMAC）。
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import yaml

from api_console.adapter_base import Confidence, DetectResult, Endpoint
from api_console.path_align import normalize_path, make_operation_key
from api_console.manifest_loader import load_manifest

logger = logging.getLogger(__name__)

# 契约文件 glob：覆盖真实名 FLOW_BUILDER_API_CONTRACT@EASYOPS.json 和样本名
# easyops_contract_sample.json 两种风格
_CONTRACT_GLOBS = ("*CONTRACT*.json", "*easyops_contract*.json")
# ENS 路由文件 glob
_ENS_GLOBS = ("*ROUTING*.json", "*ens_routing*.json")

# 伪头键：aksk 签名 query 字符串通过此键透传给 execute_dag（不进入真实 HTTP 头）
_URL_QUERY_KEY = "__url_query__"

# EasyOps OpenAPI 网关 host（参考 sources/raw/backend/api-samples.py 第 84 行）
_OPENAPI_GATEWAY_HOST = "openapi.easyops-only.com"

# 内网模式默认 user（参考 sources/raw/backend/api-samples.py 第 59 行 __init__ 默认值）
_DEFAULT_INTERNAL_USER = "defaultUser"
# agent 配置默认路径（参考 api-samples __get_host_and_org，mac/linux）
_DEFAULT_AGENT_CONF = "/usr/local/easyops/agent/conf/conf.yaml"


def _resolve_org_from_agent(agent_conf: str | None) -> str | None:
    """从 EasyOps agent 配置文件读 org（base.client_id）。

    org 兜底获取：manifest 未配 org 时调用。只在装了 agent 的机器有效。

    Args:
        agent_conf: agent conf.yaml 路径；None 用默认 _DEFAULT_AGENT_CONF。

    Returns:
        org 字符串；文件不存在/读失败/无 client_id 返回 None（让上层报错）。
    """
    path = agent_conf or _DEFAULT_AGENT_CONF
    try:
        with open(path) as f:
            dic = yaml.safe_load(f) or {}
        org = (dic.get("base") or {}).get("client_id")
        return str(org) if org is not None else None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def resolve_service_from_rpc(rpc_name: str, method: str, gateway_path: str,
                             contracts: list) -> str:
    """EasyOps 平台特定：把命名式 gateway RPC 名解析成契约里的 logic 服务名。

    命名式 path 第一段（如 ``cmdb.cmdb_object.GetDetail``）是网关 RPC 名，
    不是后端 service（契约里是 ``logic.cmdb.service``）。按 method+path
    反查 contracts 找真实 logic service。

    解析策略：
        1. service 已是 logic.* 前缀 → 直接返回
        2. (method, path) 在 contracts 唯一命中 → 返回该 service
        3. 多义 → RPC 名首段（split('.')[0]）匹配候选 service 前缀
        4. 都不中 → 返回空串

    Args:
        rpc_name: gateway path 第一段，如 ``cmdb.cmdb_object.GetDetail``，
            也可能是已是 logic.* 的服务名（直接透传）。
        method: HTTP 方法（GET/POST/...），与契约 ``method`` 字段对齐。
        gateway_path: 完整 gateway path，形如
            ``/next/api/gateway/<rpc_name>/object/{objectId}``，从中正则提取
            RPC 名之后的子 path 用于匹配契约 ``path``。
        contracts: BackendContract 列表，每条需有 ``service``/``method``/``path``
            属性（duck typing，不强制具体类型）。

    Returns:
        契约 service（如 ``logic.cmdb.service``）；无法解析返回空串。
    """
    if rpc_name and rpc_name.startswith("logic."):
        return rpc_name

    import re
    m = re.search("/api/gateway/[^/]+(/.*)?$", gateway_path or "")
    path = m.group(1) if (m and m.group(1)) else ""

    def seg_match(a, b):
        sa, sb = a.split("/"), b.split("/")
        if len(sa) != len(sb):
            return False
        for x, y in zip(sa, sb):
            if x == y:
                continue
            if x.startswith("{") and x.endswith("}") and y.startswith("{") and y.endswith("}"):
                continue
            return False
        return True

    hits = [c for c in contracts
            if getattr(c, "method", "") == method and seg_match(path, getattr(c, "path", ""))]

    if len(hits) == 1:
        return hits[0].service
    if len(hits) >= 2 and rpc_name:
        prefix = rpc_name.split(".")[0]  # cmdb.cmdb_object.GetDetail → cmdb
        for c in hits:
            svc = getattr(c, "service", "")
            if prefix in svc.split("."):
                return svc
    return ""


class Adapter:
    """EasyOps 契约 adapter：把 FLOW_BUILDER_API_CONTRACT + ENS_ROUTING 解析为 contracts。"""

    name = "easyops_contract"

    def __init__(self) -> None:
        """初始化实例级缓存（manifest 懒加载，避免每次 resolve_call_mode 重读文件）。"""
        self._manifest_cache: dict | None = None

    # ---- detect -----------------------------------------------------------

    def detect(self, raw_dir: Path) -> DetectResult:
        """评估对 raw_dir 的识别置信度。

        存在任意一个 ``*CONTRACT*.json`` 文件即 HIGH（强结构化，可直接 parse）。
        """
        contracts = self._glob_any(raw_dir, _CONTRACT_GLOBS)
        if not contracts:
            return DetectResult(
                confidence=Confidence.ZERO,
                reason=f"未在 {raw_dir} 找到契约文件 ({'/'.join(_CONTRACT_GLOBS)})",
            )
        return DetectResult(
            confidence=Confidence.HIGH,
            reason=f"找到 {len(contracts)} 个契约文件",
            matched_files=[f.name for f in contracts],
        )

    # ---- parse ------------------------------------------------------------

    def parse(self, raw_dir: Path) -> list[dict]:
        """解析 raw_dir 下的契约 + ENS 路由，输出 BackendContract 字段 dict 列表。

        无 ``serviceName`` 或 ``endpoint.uri`` 的条目跳过。
        """
        port_map = self._load_port_map(raw_dir)
        items: list[dict] = []
        for cf in self._glob_any(raw_dir, _CONTRACT_GLOBS):
            try:
                data = json.loads(cf.read_text())
            except json.JSONDecodeError as e:
                logger.warning("契约文件 %s 解析失败：%s", cf.name, e)
                continue
            if not isinstance(data, list):
                logger.warning("契约文件 %s 顶层不是数组，跳过", cf.name)
                continue
            for d in data:
                item = self._parse_one(d, port_map, cf.name)
                if item is not None:
                    items.append(item)
        return items

    # ---- resolve_call_mode ----------------------------------------------

    def resolve_call_mode(self, card, contracts: dict) -> str:
        """EasyOps 平台特定：决定卡片调用 mode（override 主干默认）。

        优先级（卡片缺 mode 时的兜底链）：
          1. 卡片显式声明 endpoint.mode → 尊重之（不覆盖）。
          2. manifest.call_policy.default_mode → 平台级默认（本环境配 easyops_internal，
             内网直连免 cookie；见 manifest.yaml 注释）。
          3. 契约带 port → ``easyops_internal``（内网直连）；否则 ``easyops_gateway``
             （前端 cookie 网关）。

        Args:
            card: Card 对象（读 card.endpoint）。
            contracts: operation_key -> contract dict（contract 含 port）。

        Returns:
            ``easyops_internal`` 或 ``easyops_gateway``。
        """
        ep = getattr(card, "endpoint", None) or {}
        # 卡片显式声明 mode 时尊重之（不覆盖）
        if ep.get("mode"):
            return ep["mode"]
        # 平台级默认兜底（manifest.call_policy.default_mode）：注册期不固化 mode，
        # 所有卡片在此吃到统一默认（不依赖契约推断的间接性）。
        default_mode = self._default_call_mode()
        if default_mode:
            return default_mode
        contract_ref = ep.get("contract_ref", "")
        if not contract_ref:
            return "easyops_gateway"
        contract = contracts.get(contract_ref)
        if not contract:
            return "easyops_gateway"
        port = contract.get("port") if isinstance(contract, dict) else getattr(contract, "port", None)
        if not port:
            return "easyops_gateway"
        return "easyops_internal"

    # ---- manifest 加载（call_policy 兜底用） -------------------------------

    def _default_call_mode(self) -> str:
        """读 manifest.call_policy.default_mode（平台级默认 mode）。

        Returns:
            配置存在返回其值（如 ``easyops_internal``）；未配置/读不到返回空串
            （回退到契约推断分支）。
        """
        manifest = self._load_manifest()
        policy = (manifest.get("call_policy") or {}) if isinstance(manifest, dict) else {}
        return policy.get("default_mode", "") or ""

    def _load_manifest(self) -> dict:
        """加载所属平台包的 manifest.yaml（实例级缓存，多环境 default_env 扁平化）。

        通过 :func:`manifest_loader.load_manifest`（env=None → 用 default_env）
        加载，使新形态多环境 manifest（``environments.<env>.call_policy``）与
        register_cards / call_card / extract_auth 等所有读取入口行为一致。
        扁平化后顶层即 ``call_policy``，:meth:`_default_call_mode` 直接读。

        定位规则（adapter 不认识平台名，与 :meth:`_load_cookie_header` 同一套
        去平台名耦合思路）：

        1. 按 ``__file__`` 向上 4 级（``platforms/<p>/sources/backend/adapters/x.py``
           → ``platforms/<p>/``）找 ``manifest.yaml``；
        2. 找不到则兜底在 ``platforms/*/manifest.yaml`` 下取第一个存在的。

        adapter 运行时 ``scripts/`` 已在 sys.path（run.sh 以脚本路径启动，
        CPython 把脚本目录设为 sys.path[0]；adapter 自身从该目录 import
        adapter_base / path_align 即依赖此），故跨目录 import 等价于既有依赖。

        Returns:
            扁平 manifest dict；读不到/解析失败返回空 dict（调用方按未配置处理，
            不抛错，回退到契约推断分支）。
        """
        if self._manifest_cache is not None:
            return self._manifest_cache
        platform_dir = self._find_platform_dir()
        result: dict = {}
        if platform_dir is not None:
            try:
                result = load_manifest(platform_dir, None)
            except (ValueError, OSError):
                # manifest 缺失 / 缺 host / 解析失败 → 按未配置处理（不抛错）
                result = {}
        self._manifest_cache = result
        return result

    def _find_platform_dir(self) -> Path | None:
        """按 ``__file__`` 向上找 platform 包根，兜底 ``platforms/*`` glob。

        Returns:
            含 ``manifest.yaml`` 的 platform 目录 Path；都找不到返回 None。
        """
        candidates: list[Path] = []
        try:
            candidates.append(Path(__file__).resolve().parents[3])
        except Exception:  # noqa: BLE001 - __file__ 定位失败不致命
            pass
        try:
            candidates.extend(
                sorted(p.parent for p in Path("platforms").glob("*/manifest.yaml"))
            )
        except Exception:  # noqa: BLE001 - glob 失败（如 CWD 无 platforms）忽略
            pass
        for cand in candidates:
            if (cand / "manifest.yaml").exists():
                return cand
        return None

    # ---- resolve_endpoint -----------------------------------------------

    def resolve_endpoint(self, contract: dict, manifest: dict) -> Endpoint:
        """解析可真调端点（spec 1.5 / 4.2 / 1.6 三种访问方式）。

        三种 ``endpoint.mode`` 分支（同一套契约 path，URL 拼法/鉴权不同）：

        - ``easyops_gateway``（默认）：网关路径 ``<gateway_base>/<service><path>``，
          80 端口，auth=session_cookie。已真调 200 OK（Task 12）。
        - ``easyops_internal``：内网直连 ``http://<host>:<port><path>``，8xxx 端口，
          auth=easyops_internal（user/org 头，不依赖 cookie/签名）。已真调 200 OK
          （Task 13，org=5910 + 8134 端口查 flowable_service）。
        - ``easyops_aksk``：OpenAPI 签名 ``http://<host>/<app_name><path>``，
          auth=easyops_aksk（HMAC-SHA1）。MVP-1 未实测（无 AK/SK）。

        Args:
            contract: 单条后端契约 dict（含 ``service``/``method``/``path``，可能
                还有 ``port``）。execute_dag 调用时把卡片侧的 ``endpoint.mode``
                合并进 ``contract["endpoint"]["mode"]`` 传入。
            manifest: manifest.yaml 反序列化结果。

        Returns:
            :class:`Endpoint`（含 url/method/auth/headers，headers 通常为空，
            鉴权头由 :meth:`build_auth_headers` 单独构造）。

        Raises:
            NotImplementedError: ``endpoint.mode`` 不在上述三种之列。
            ValueError / KeyError: 必填字段缺失（如 internal 模式缺 port、
                aksk 模式缺 port_app_map 映射）。
        """
        mode = (contract.get("endpoint") or {}).get("mode", "easyops_gateway")
        path = contract["path"]
        # method 优先取卡片侧 endpoint.method（卡片是真调权威）；契约 method 可能是
        # ENS 标记（如 LIST 实为 GET），非标准 HTTP 方法会导致 httpx 发不出请求。
        method = ((contract.get("endpoint") or {}).get("method")
                  or contract.get("method", "GET")).upper()

        if mode == "easyops_gateway":
            gateway_base = manifest["gateway_base"]
            service = contract["service"]
            url = f"{gateway_base}/{service}{path}"
            return Endpoint(url=url, method=method, auth="session_cookie", headers={})

        if mode == "easyops_internal":
            port = contract.get("port")
            if not port:
                raise ValueError(
                    "easyops_internal 模式需 contract.port（ENS 路由表提供，"
                    "parse_backend 时关联进 contract）"
                )
            host = manifest["host"]
            url = f"http://{host}:{port}{path}"
            return Endpoint(url=url, method=method,
                            auth="easyops_internal", headers={})

        if mode == "easyops_aksk":
            port = contract.get("port")
            app_name = self._lookup_app_name(manifest, port)
            host = manifest["host"]
            # path 归一化：lstrip 前 / 再拼，保证正好一个分隔符（参考 api-samples 第 177 行）
            # 兼容契约 path（带前导 /，如 /object/...）与硬编码 path（无 /，如 v3/object/...）
            url = f"http://{host}/{app_name}/{path.lstrip('/')}"
            return Endpoint(url=url, method=method,
                            auth="easyops_aksk", headers={})

        raise NotImplementedError(
            f"未支持的 endpoint.mode={mode}（仅支持 easyops_gateway / "
            f"easyops_internal / easyops_aksk）"
        )

    # ---- build_auth_headers（spec 1.6） ----------------------------------

    def build_auth_headers(self, auth_mode: str, manifest: dict,
                           request_ctx: dict | None = None) -> dict:
        """按鉴权方式构造请求头（spec 1.6），execute_dag 调用，零平台耦合。

        三分支（与 resolve_endpoint 返回的 Endpoint.auth 一一对应）：

        - ``session_cookie``：优先 ``manifest.auth.session_cookie.cookie``（明文，
          多环境 manifest 由 extract_auth 按环境写入），兜底读
          ``manifest.auth.session_cookie.cookie_file`` 文件；返回
          ``{"Cookie": "k=v; k2=v2"}``。cookie_file 路径解析逻辑见
          :meth:`_load_cookie_header`（相对 cwd，兜底扫 ``platforms/*/``）。
        - ``easyops_internal``：读 ``manifest.auth.internal``（org/user），
          返回 ``{user, org, Content-Type}``。user 缺省 ``defaultUser``。
        - ``easyops_aksk``：按 sources/raw/backend/api-samples.py 的 HMAC-SHA1 算法签名，
          返回 ``{user, Host, [Content-Type], __url_query__}``，
          ``__url_query__`` 是伪头（签名 query 字符串），由 execute_dag 取出
          附加到 URL，**不进入真实 HTTP 头**。

        Args:
            auth_mode: 鉴权模式（Endpoint.auth）。
            manifest: manifest.yaml 反序列化结果（含 auth 配置）。
            request_ctx: 签名模式用 ``{method, url, body}``，非签名模式忽略。

        Returns:
            鉴权请求头 dict（execute_dag 合并到请求 headers）。

        Raises:
            NotImplementedError: 平台未支持该 auth_mode，或 manifest 缺该模式
                必需的配置（如 aksk 未配 ak/sk）。
        """
        if auth_mode == "session_cookie":
            return self._build_session_cookie_headers(manifest)
        if auth_mode == "easyops_internal":
            return self._build_internal_headers(manifest)
        if auth_mode == "easyops_aksk":
            return self._build_aksk_headers(manifest, request_ctx or {})
        if auth_mode == "none":
            return {}
        raise NotImplementedError(
            f"未支持的 auth_mode={auth_mode}（仅支持 session_cookie / "
            f"easyops_internal / easyops_aksk / none）"
        )

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _glob_any(raw_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
        """对多个 glob pattern 取并集（去重保序）。"""
        seen: set[Path] = set()
        out: list[Path] = []
        for p in patterns:
            for f in raw_dir.glob(p):
                if f not in seen:
                    seen.add(f)
                    out.append(f)
        return out

    def _load_port_map(self, raw_dir: Path) -> dict[str, int]:
        """从 ENS_ROUTING 抽 contract -> port 映射。

        真实 ENS_ROUTING 条目无 ``serviceName`` 字段，靠 ``contract`` 字段关联端口。
        契约的 ``serviceName``（如 ``logic.flowable_service``）直接对应 ENS 的
        ``contract`` 值。
        """
        m: dict[str, int] = {}
        for ef in self._glob_any(raw_dir, _ENS_GLOBS):
            try:
                data = json.loads(ef.read_text())
            except json.JSONDecodeError as e:
                logger.warning("ENS 文件 %s 解析失败：%s", ef.name, e)
                continue
            if not isinstance(data, list):
                continue
            for e in data:
                # 优先 serviceName，回退 contract（真实数据无 serviceName）
                svc = e.get("serviceName") or e.get("contract")
                port = e.get("port")
                if svc and port:
                    m[svc] = int(port)
        return m

    def _parse_one(self, d: dict, port_map: dict[str, int],
                   source_file: str) -> dict | None:
        """解析单条契约为 BackendContract 字段 dict。

        Returns:
            dict 或 None（缺 serviceName / uri 时跳过返回 None）。
        """
        svc = d.get("serviceName")
        if not svc:
            return None
        endpoint = d.get("endpoint") or {}
        method = (endpoint.get("method") or "GET").upper()
        uri = endpoint.get("uri") or ""
        if not uri:
            return None
        norm = normalize_path(uri)
        req = d.get("request") or {}
        resp = d.get("response") or {}
        req_fields = self._fields(req)
        resp_fields = self._fields(resp)
        return {
            "operation_key": make_operation_key(svc, method, norm),
            "method": method,
            "path": norm,
            "raw_paths": {"backend": uri, "frontend": ""},
            "path_source": "backend_contract",
            "path_confidence": "high",
            "service": svc,
            "port": port_map.get(svc),
            "request": {"fields": req_fields},
            "response": {"fields": resp_fields},
            "semantic_gaps": self._gaps(req, resp),
            "source_file": source_file,
        }

    @staticmethod
    def _fields(schema: dict) -> list[dict]:
        """把 raw request/response 的 fields 列表抽成 ``{name, type, desc}`` 标准形。"""
        out: list[dict] = []
        for f in (schema.get("fields") or []):
            out.append({
                "name": f.get("name"),
                "type": f.get("type", "string"),
                "desc": f.get("description", ""),
            })
        return out

    @staticmethod
    def _gaps(req: dict, resp: dict) -> list[str]:
        """收集缺 description 的字段名（供 LLM 补语义用）。"""
        gaps: list[str] = []
        for f in (req.get("fields") or []) + (resp.get("fields") or []):
            name = f.get("name")
            if name and not f.get("description"):
                gaps.append(name)
        return gaps

    # ---- 鉴权头构造（spec 1.6 三分支） ------------------------------------

    @staticmethod
    def _lookup_app_name(manifest: dict, port: int | None) -> str:
        """从 manifest.auth.aksk.port_app_map 按 port 查 app_name。

        port_app_map 的 key 在 YAML 反序列化后可能是 int 也可能是 str（取决于
        YAML 写法），两种都查一遍。命中即返回；未命中抛 ValueError。

        Args:
            manifest: manifest.yaml 反序列化结果。
            port: ENS 路由表里的端口号（contract.port）。

        Returns:
            app_name（如 ``cmdbservice``）。

        Raises:
            ValueError: aksk 未配 port_app_map，或 port 未在其中。
        """
        aksk = (manifest.get("auth") or {}).get("aksk") or {}
        port_app_map: dict = aksk.get("port_app_map") or {}
        if not port_app_map:
            raise ValueError(
                "easyops_aksk 模式需 manifest.auth.aksk.port_app_map（MVP-1 未配置）"
            )
        # YAML 可能反序列化为 int 或 str key，两种都查
        app_name = port_app_map.get(port) or port_app_map.get(str(port))
        if not app_name:
            raise ValueError(
                f"端口 {port} 未在 manifest.auth.aksk.port_app_map 中映射"
                f"（已有: {list(port_app_map.keys())}）"
            )
        return app_name

    def _build_session_cookie_headers(self, manifest: dict) -> dict:
        """session_cookie 分支：优先 manifest 明文 cookie，兜底 cookie_file。

        解析顺序（新形态优先 + 旧形态兼容）：

        1. ``manifest.auth.session_cookie.cookie``（明文字符串，多环境 manifest
           由 extract_auth 按环境写入）→ 直接返回 ``{"Cookie": <cookie>}``；
        2. ``manifest.auth.session_cookie.cookie_file``（旧形态）→ 调
           :meth:`_load_cookie_header` 读文件拼 ``name=value; ...``；
        3. 两者都没有 → 抛 ValueError。

        Args:
            manifest: manifest.yaml 反序列化结果（含 auth 配置）。

        Returns:
            ``{"Cookie": "..."}``，cookie 为空时返回 ``{}``。

        Raises:
            ValueError: 未配 ``cookie`` 也未配 ``cookie_file``。
        """
        sc = (manifest.get("auth") or {}).get("session_cookie") or {}
        # 新形态：cookie 明文字段（多环境 manifest 由 extract_auth 写入）
        cookie = sc.get("cookie")
        if cookie:
            return {"Cookie": cookie}
        # 旧形态兜底：从 cookie_file 读文件
        cookie_file = sc.get("cookie_file")
        if not cookie_file:
            raise ValueError(
                "session_cookie 模式需 manifest.auth.session_cookie.cookie"
                "（明文）或 cookie_file（文件路径）"
            )
        cookie_h = self._load_cookie_header(cookie_file)
        return {"Cookie": cookie_h} if cookie_h else {}

    @staticmethod
    def _build_internal_headers(manifest: dict) -> dict:
        """easyops_internal 分支：内网直连 user/org/Content-Type 头。

        已真调验证（Task 13，org=5910）：``{user: defaultUser, org: 5910,
        Content-Type: application/json}`` 三头即可访问 8134 端口的 flowable_service。

        org 解析顺序（manifest 优先 + agent 兜底）：
        1. ``manifest.auth.internal.org``（配置优先）
        2. agent 配置文件 ``base.client_id``（路径见 ``internal.agent_conf``，
           默认 ``/usr/local/easyops/agent/conf/conf.yaml``，参考 api-samples
           ``__get_host_and_org``）
        3. 都没有 → 报错

        Returns:
            ``{user, org, Content-Type}``。user 缺省 ``defaultUser``。

        Raises:
            NotImplementedError: manifest 与 agent conf 都拿不到 org。
        """
        internal = (manifest.get("auth") or {}).get("internal") or {}
        org = internal.get("org")
        if org is None or org == "":
            # agent 兜底：读 agent conf 的 base.client_id
            org = _resolve_org_from_agent(internal.get("agent_conf"))
        if org is None or org == "":
            raise NotImplementedError(
                "easyops_internal 模式需 org：配 manifest.auth.internal.org，"
                "或提供 agent conf（internal.agent_conf，默认 "
                "/usr/local/easyops/agent/conf/conf.yaml）"
            )
        user = internal.get("user") or _DEFAULT_INTERNAL_USER
        return {
            "user": user,
            "org": str(org),
            "Content-Type": "application/json",
        }

    def _build_aksk_headers(self, manifest: dict,
                            request_ctx: dict) -> dict:
        """easyops_aksk 分支：HMAC-SHA1 签名（参考 sources/raw/backend/api-samples.py）。

        签名串 = ``method\\nuri\\n排序url_param\\ncontent_type\\ncontent_md5
        \\ntimestamp\\nak``，HMAC-SHA1(sk, 签名串) → hex signature。
        详细算法见 :meth:`_sign_hmac_sha1`。

        签名结果作为 URL query（``accesskey/signature/expires``）附加到请求 URL，
        本方法通过伪头 ``__url_query__`` 透传给 execute_dag（约定，不进入真实
        HTTP 头）。

        Args:
            manifest: manifest.yaml 反序列化结果，必须含 ``auth.aksk.ak/sk``。
            request_ctx: ``{method, url, body}``，body 可为 dict/str/None。

        Returns:
            ``{user, Host, [Content-Type], __url_query__}``。

        Raises:
            NotImplementedError: aksk 未配 ak/sk（MVP-1 默认场景）。
        """
        aksk = (manifest.get("auth") or {}).get("aksk")
        if not aksk or not aksk.get("ak") or not aksk.get("sk"):
            raise NotImplementedError(
                "easyops_aksk 模式需 manifest.auth.aksk.ak/sk"
                "（MVP-1 未配置，签名无法生成）"
            )
        ak: str = aksk["ak"]
        sk: str = aksk["sk"]

        method = (request_ctx.get("method") or "GET").upper()
        url = request_ctx.get("url", "")
        body = request_ctx.get("body")

        # uri 取 URL 的 path 部分（签名不包含 host/query，参考 api-samples 第 177 行）
        uri = urlparse(url).path

        # body 序列化：dict -> json 字符串；None -> "{}"；str 原样
        if body is None:
            body_str = "{}"
        elif isinstance(body, str):
            body_str = body
        else:
            body_str = json.dumps(body)

        sign_params = self._sign_hmac_sha1(
            ak=ak, sk=sk, method=method, uri=uri, data=body_str,
        )

        headers: dict = {
            "user": _DEFAULT_INTERNAL_USER,
            "Host": _OPENAPI_GATEWAY_HOST,
            _URL_QUERY_KEY: urlencode(sign_params),
        }
        # OpenAPI 模式：POST/PUT 发 Content-Type，GET/DELETE 不发
        # （参考 api-samples 第 116-119 行 + 188-189 行）
        if method in ("POST", "PUT"):
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _sign_hmac_sha1(ak: str, sk: str, method: str, uri: str,
                        data: str = "{}",
                        params: dict | None = None) -> dict:
        """HMAC-SHA1 签名算法（参考 sources/raw/backend/api-samples.py ``__signature``）。

        签名串字段顺序（逐行 ``\\n`` 拼接）::

            method
            uri                          # 含 app_name 前缀，不含 host/query
            url_param                    # 排序后的 k+v 直接拼接（无分隔符）
            content_type                 # POST/PUT: application/json；其余空串
            content_md5                  # POST/PUT 且 body 非空时算；其余空串
            request_time                 # 服务端用来校验 expires
            ak

        Args:
            ak: Access Key。
            sk: Secret Key（HMAC 密钥）。
            method: HTTP 方法（大写）。
            uri: 请求 URI（含 app_name 前缀，不含 host/query）。
            data: 请求体 JSON 字符串（POST/PUT 时算 Content-MD5）。
            params: URL 查询参数（参与签名，签名结果也合进来）。

        Returns:
            ``{**params, accesskey, signature, expires}``（拼到 URL query）。
        """
        sign_params = dict(params) if params else {}
        request_time = str(int(time.time()))
        method = method.upper()

        # POST/PUT 需要 Content-Type，GET/DELETE 不需要
        content_type = "application/json" if method in ("POST", "PUT") else ""

        # URL 参数排序拼接（参考 api-samples 第 122 行）
        url_param = "".join(f"{k}{sign_params[k]}" for k in sorted(sign_params.keys()))

        # Content-MD5（仅 POST/PUT）
        content_md5 = ""
        if method in ("POST", "PUT") and data:
            md5 = hashlib.md5()
            md5.update(data.encode("utf-8") if isinstance(data, str) else data)
            content_md5 = md5.hexdigest()

        # 构建签名字符串
        string_to_sign = "\n".join([
            method, uri, url_param, content_type,
            content_md5, request_time, ak,
        ]).encode()

        signature = hmac.new(
            sk.encode(), string_to_sign, hashlib.sha1
        ).hexdigest()

        sign_params.update({
            "accesskey": ak,
            "signature": signature,
            "expires": request_time,
        })
        return sign_params

    # ---- session_cookie 的 cookie 文件加载 -------------------------------

    def _load_cookie_header(self, cookie_file: str) -> str:
        """读 cookies.json 拼成 Cookie header 字符串（迁移自 execute_dag）。

        ``cookie_file`` 是相对 platform 包根的路径（如 ``auth/cookies.json``），
        adapter 不认识平台名，路径解析规则：

        1. 绝对路径：直接读；
        2. 相对路径：先按 cwd 解析（用户在 platform 包同级目录调用）；
        3. 都找不到：兜底在 ``platforms/*/`` 下扫一遍匹配路径（去平台名耦合）。

        Args:
            cookie_file: cookie 文件路径（manifest.auth.session_cookie.cookie_file）。

        Returns:
            ``name=value; name2=value2`` 格式字符串。

        Raises:
            FileNotFoundError: cookie 文件不存在。
            ValueError: cookies.json 格式非法。
        """
        p = Path(cookie_file)
        if not p.is_absolute() and not p.exists():
            # 兜底：在 platforms/<*>/ 下找匹配路径（adapter 不认识平台名）
            for cand in Path("platforms").glob("*/" + str(p)):
                if cand.exists():
                    p = cand
                    break
        if not p.exists():
            raise FileNotFoundError(
                f"cookie 文件不存在：{p}（manifest.auth.session_cookie.cookie_file）"
            )
        cookies = json.loads(p.read_text())
        if not isinstance(cookies, list):
            raise ValueError(
                "cookies.json 必须是数组（[{name, value}, ...]），实际类型："
                + type(cookies).__name__
            )
        return "; ".join(c["name"] + "=" + c["value"] for c in cookies)
