"""从 recorder 的 Chromium profile 提取 cookie 写回平台 manifest。

spec 8.1：macOS Chrome Cookies SQLite 加密，用 pycookiecheat 解密。
测试通过 mock get_cookies 避开真实依赖（真实端到端留 Task 12）。

多环境支持：
    - 通过 ``--env`` 选择 manifest 环境（不传用 default_env）。
    - profile 目录从扁平 manifest 的 ``auth_source`` 字段读取（替代从 host 反推）。
    - 提取到的 cookie 字符串经 ``_update_cookie_in_manifest`` 文本级定点写回
      ``manifest.yaml`` 的 ``environments.<env>.auth.session_cookie.cookie``，
      保留其他环境块/注释/键顺序（避免 PyYAML 全量 round-trip 丢内容）。
    - 旧形态（无 environments）无 env 块，cookie 写回不适用 → 维持原
      ``auth/cookies.json`` 落盘行为并打印提示。

用法:
    run.sh extract_auth.py --platform <platform> [--env <env>]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from api_console.manifest_loader import load_manifest


def get_cookies(host: str, profile_dir: Path) -> list[dict]:
    """从 Chromium profile 读取并解密 cookie。

    Args:
        host: 目标 host（如 172.30.5.20），构造 url 过滤同名域 cookie。
        profile_dir: recorder profile 目录（含 Default/Cookies）。

    Returns:
        list[dict]：每条含 name/value/domain 三个键。

    Raises:
        FileNotFoundError: profile 不存在或缺 Cookies 文件。
    """
    cookies_db = profile_dir / "Default" / "Cookies"
    if not cookies_db.exists():
        raise FileNotFoundError(f"profile 不存在或无 Cookies：{cookies_db}")

    # Chrome 运行时 SQLite 被锁，先 copy2 到临时文件再读
    import shutil
    import tempfile
    from pycookiecheat import chrome_cookies

    with tempfile.TemporaryDirectory() as td:
        bak = Path(td) / "Cookies"
        shutil.copy2(cookies_db, bak)
        url = f"http://{host}"
        # pycookiecheat 0.8.0：默认返回 dict；as_cookies=True 返回 list[Cookie]
        # 取 Cookie 对象便于按 name/value/domain 三字段标准化输出。
        # 不同版本 Cookie 的域名字段名不同：0.8.0 用 host_key，老版本用 domain，
        # 用 getattr 兼容两版（取不到返回 None，_cookies_to_session_str 会按需兜底）。
        cookie_objs = chrome_cookies(url, cookie_file=bak, as_cookies=True)
        return [{"name": c.name, "value": c.value,
                 "domain": getattr(c, "domain", None) or getattr(c, "host_key", None)}
                for c in cookie_objs]


def run(host: str, profile_dir: Path, auth_dir: Path) -> None:
    """提取 cookie 写 auth/cookies.json + meta.json。

    Args:
        host: 目标 host。
        profile_dir: recorder profile 目录。
        auth_dir: 输出目录（platforms/<p>/auth/）。
    """
    cookies = get_cookies(host, profile_dir)
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "cookies.json").write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2))
    meta = {
        "host": host,
        "extracted_at": _now_iso(),
        "source_profile": str(profile_dir),
        "count": len(cookies),
    }
    (auth_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"[extract_auth] 提取 {len(cookies)} 条 cookie → {auth_dir}")


def _now_iso() -> str:
    """当前时间 ISO 字符串（运行时脚本，非 workflow，可自由用 datetime.now）。"""
    from datetime import datetime
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# 文本级定点写回（纯函数，无浏览器依赖，可单测）
# ---------------------------------------------------------------------------

# 环境块定位：``  <env>:\n`` 起到下一个同级缩进块或文件尾。
# body 收集 4 空格起的所有子行（即该环境的字段）。支持 2 空格 environments 缩进
# （项目模板用 2 空格）。body 内字段可为任意嵌套层级（cookie 常在 4 层之下）。
_ENV_BLOCK_RE = re.compile(
    r"^(?P<indent>  )(?P<env>[^\s:#][^:\n]*):\n"
    r"(?P<body>(?:    [^\n]*\n)*)",
    re.MULTILINE,
)

# 在环境块内定位首个 ``cookie:`` 行（支持任意前导缩进）。count=1 只改第一条。
_COOKIE_LINE_RE = re.compile(r"^(\s*cookie:\s*).*$", re.MULTILINE)


def _update_cookie_in_manifest(manifest_path, env, cookie_value):
    """文本级定点更新 manifest 指定环境的 ``session_cookie.cookie``。

    只改 ``environments.<env>.auth.session_cookie.cookie`` 行的值，保留其余内容
    （其他环境块、注释、键顺序、空行）。``cookie_value`` 含特殊字符（``;`` ``=``
    等）时统一加双引号并转义内部双引号，避免破坏 YAML。

    纯文本处理 —— **不走 PyYAML 全量 round-trip**（会丢注释 / 重排键顺序）。

    Args:
        manifest_path: manifest.yaml 路径（Path 或 str）。
        env: 环境名（必须存在于 environments 下）。
        cookie_value: 新 cookie 字符串值。

    Raises:
        ValueError: manifest 中未找到该环境块，或环境块内缺 cookie 字段行。
    """
    path = Path(manifest_path)
    text = path.read_text(encoding="utf-8")

    # 逐个匹配环境块，按 env 名筛（避免 env 名作为另一环境字段值误命中）
    # 兼容带引号的环境键（如 "232": 强制字符串键）：正则按 [^\s:#][^:\n]* 会把
    # "232" 连同引号一起捕获，比较时 strip 引号即可（普通键名无引号不受影响）。
    target = None
    for m in _ENV_BLOCK_RE.finditer(text):
        if m.group("env").strip('"') == env:
            target = m
            break
    if target is None:
        raise ValueError("manifest 中未找到环境 {0!r}".format(env))

    body = target.group("body")
    if not _COOKIE_LINE_RE.search(body):
        raise ValueError(
            "环境 {0!r} 缺 auth.session_cookie.cookie 字段".format(env)
        )

    # 加双引号并转义内部双引号（cookie 常含 ; = 等需引号包裹的字符）
    val = '"{0}"'.format(cookie_value.replace('"', '\\"'))
    new_body = _COOKIE_LINE_RE.sub(lambda mm: mm.group(1) + val, body, count=1)
    new_text = text[:target.start("body")] + new_body + text[target.end("body"):]
    path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：读 manifest 拿 host + auth_source，定位 profile 后提取 cookie 写回。

    workdir 解析：优先 API_CONSOLE_WORKDIR env，回退 cwd。
    新形态 manifest：cookie 写回 environments.<env>.auth.session_cookie.cookie。
    旧形态 manifest（无 environments）：无 env 块，落 auth/cookies.json（旧行为）。
    """
    p = argparse.ArgumentParser(prog="api-console extract-auth", description="从 recorder profile 提取 cookie 写回 manifest")
    p.add_argument("--platform", required=True, help="平台名（对应 platforms/ 下的目录名）")
    p.add_argument("--env", default="",
                   help="环境名（多环境 manifest 选环境；不传用 default_env）")
    args = p.parse_args(argv)

    import os
    workdir = Path(os.environ.get("API_CONSOLE_WORKDIR", os.getcwd()))
    platform_dir = workdir / "platforms" / args.platform
    manifest_path = platform_dir / "manifest.yaml"

    manifest = load_manifest(platform_dir, args.env or None)
    host = manifest["host"]
    active_env = manifest.get("active_env")

    # 新旧形态判定：读原始 manifest 是否含顶层 ``environments:`` 键。
    # 不依赖 active_env（旧形态注入 "default"，新形态也可能把环境命名为 default），
    # 避免 env 名为 default 的新形态被误判为旧形态 → 错落 cookies.json。
    import yaml
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    is_multi_env = "environments" in raw

    # profile 目录优先取扁平 manifest 的 auth_source（替代从 host 反推）
    auth_source = manifest.get("auth_source")
    if auth_source:
        profile_dir = Path(auth_source)
        if not profile_dir.is_absolute():
            profile_dir = workdir / profile_dir
    else:
        profile_dir = workdir / "tmp" / "profiles" / host

    cookies = get_cookies(host, profile_dir)

    # cookie 串：取匹配 host 域的首条（session cookie 通常单条），fallback 拼全部
    cookie_str = _cookies_to_session_str(cookies, host)

    if is_multi_env:
        # 新形态：定点写回 manifest 的对应环境 cookie 字段
        _update_cookie_in_manifest(manifest_path, active_env, cookie_str)
        print("[extract_auth] 写回 {0} 的 {1} 环境 cookie（{2} 条）".format(
            manifest_path, active_env, len(cookies)))
    else:
        # 旧形态（无 environments）：维持 auth/cookies.json 落盘行为
        auth_dir = platform_dir / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "cookies.json").write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2))
        meta = {
            "host": host,
            "extracted_at": _now_iso(),
            "source_profile": str(profile_dir),
            "count": len(cookies),
        }
        (auth_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2))
        print("[extract_auth] 旧形态 manifest（无 environments），"
              "cookie 落 {0}/cookies.json（建议转新形态以支持定点写回）".format(auth_dir))
    return 0


def _cookies_to_session_str(cookies: list[dict], host: str) -> str:
    """把 cookie 列表归并为单条 cookie 字符串（``name=value; name=value``）。

    优先取 domain 匹配 host 的条目；无匹配则用全部。多 cookie 用 ``"; "`` 拼接
    全部条目（与旧 cookie_file 路径 ``_load_cookie_header`` 行为一致，避免多
    cookie 站点静默回退为单条）。

    Args:
        cookies: get_cookies 返回的 list[dict]，每条含 name/value/domain。
        host: 目标 host，用于过滤同名域 cookie。

    Returns:
        ``name=value; name=value`` 形式的 cookie 字符串（多条以 ``"; "`` 分隔）。
    """
    if not cookies:
        return ""
    matched = [c for c in cookies if c.get("domain") and host in c["domain"]]
    pool = matched or cookies
    return "; ".join(
        "{0}={1}".format(c.get("name", ""), c.get("value", "")) for c in pool
    )


if __name__ == "__main__":
    sys.exit(main())
