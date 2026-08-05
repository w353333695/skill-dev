"""manifest 统一加载层（多环境支持，方案 A）。

读 platforms/<platform>/manifest.yaml，按 env 选环境并扁平化成旧形态 dict，
使 adapter / execute_dag / invoke_card 零改动。新旧形态自动兼容。
"""
from __future__ import annotations
import re
import warnings
from pathlib import Path
import yaml


# 占位符检测：模板里 ``<YOUR_HOST>``、``<ORG_ID>`` 等尖括号占位符。
# 模板复制-然后-填写是预期流程，发现未替换时只 warning 提示（不 raise）。
_PLACEHOLDER_RE = re.compile(r"<[^>\s]+>")


def _warn_placeholders(flat: dict) -> None:
    """扁平化后扫描关键字段是否仍含模板占位符 ``<...>``，命中则 warning。

    只检查会直接影响调用的字符串字段（host/gateway_base/auth_source/base_url），
    不扫整个 dict（避免误报业务字段里的合法尖括号）。

    Args:
        flat: load_manifest 已经扁平化好的 manifest dict。
    """
    for key in ("host", "gateway_base", "base_url", "auth_source"):
        val = flat.get(key)
        if isinstance(val, str):
            m = _PLACEHOLDER_RE.search(val)
            if m:
                warnings.warn(
                    "manifest 字段 {0!r} 仍含未替换的占位符 {1!r}，"
                    "请按 manifest.example.yaml 填写真实值".format(key, m.group(0)),
                    stacklevel=2,
                )


def load_manifest(platform_dir: Path, env: str | None = None) -> dict:
    """加载 manifest 并按环境扁平化。

    Args:
        platform_dir: platform 目录（含 manifest.yaml），Path。
        env: 环境名；None 用 default_env；旧形态忽略。

    Returns:
        扁平 manifest dict（顶层 host/gateway_base/auth/call_policy/auth_source
        + active_env + name/default_env）。

    Raises:
        ValueError: manifest 不存在 / env 不存在 / 选定环境缺 host。
    """
    path = Path(platform_dir) / "manifest.yaml"
    if not path.exists():
        example = Path(platform_dir) / "manifest.example.yaml"
        raise ValueError(
            "未找到 {0}，请从 {1} 复制并填写：cp {1} {0}".format(path, example)
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # 旧形态：无 environments，顶层即扁平配置，当单环境直接用
    if "environments" not in data:
        if not data.get("host"):
            raise ValueError("manifest 缺 host（旧形态须顶层 host）")
        data.setdefault("active_env", "default")
        _warn_placeholders(data)
        return data

    # 新形态：多环境
    envs = data["environments"]
    chosen = env or data.get("default_env")
    if not chosen:
        raise ValueError("未指定 env 且 manifest 无 default_env")
    if chosen not in envs:
        raise ValueError(
            "环境 {0!r} 不存在，可用环境：{1}".format(chosen, ", ".join(envs.keys()))
        )
    env_cfg = envs[chosen] or {}
    if not env_cfg.get("host"):
        raise ValueError("环境 {0!r} 缺 host".format(chosen))

    # 扁平化：环境字段提升到顶层，保留 name/default_env
    flat = {"name": data.get("name"), "default_env": data.get("default_env")}
    flat.update(env_cfg)
    flat["active_env"] = chosen
    _warn_placeholders(flat)
    return flat
