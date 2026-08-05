# browser_recorder/browser.py
"""浏览器启动 helper：跨环境兼容。

Playwright Python 默认 ``chromium.launch()`` 优先使用独立的 headless shell
二进制；当环境只装了完整 chromium（缺 headless shell）时，自动回退到完整
chrome 二进制（同样支持无头，不需要桌面环境）。集中在此，record/replay/测试共用。
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Playwright


def full_chrome_path() -> str | None:
    """检测已安装的完整 chrome 二进制。

    查找顺序（任一命中即返回）：
    1. ms-playwright/chromium-*/chrome-linux64/chrome（uv ``playwright install`` 装的）
    2. ms-playwright/chromium-*/chrome-linux/chrome（部分环境装的是该布局，
       常为指向 ``/opt/chrome/chrome`` 的软链）
    3. /opt/chrome/chrome-linux64/chrome（系统预装的完整 chrome）

    返回 ``str`` 路径或 ``None``（未找到，交由 Playwright 默认解析）。
    """
    base = Path.home() / ".cache" / "ms-playwright"
    if base.exists():
        for d in sorted(base.glob("chromium-*"), reverse=True):
            for sub in ("chrome-linux64", "chrome-linux"):
                cand = d / sub / "chrome"
                if cand.exists():
                    return str(cand)
    # 系统预装完整 chrome（如镜像内 /opt/chrome）
    sys_chrome = Path("/opt/chrome/chrome-linux64/chrome")
    if sys_chrome.exists():
        return str(sys_chrome)
    return None


def launch(pw: "Playwright", **kwargs: Any):
    """启动 chromium。headless shell 缺失时自动用完整 chrome。

    默认 headless=True（无头，不需要桌面环境）。

    容器/无桌面环境默认注入 ``--no-sandbox`` / ``--disable-dev-shm-usage``
    以保证稳定（共享内存不足或非 root 沙箱受限时 chrome 会崩）；调用方传入
    ``args=`` 时叠加，不覆盖其意图。
    """
    chrome = full_chrome_path()
    if chrome and "executable_path" not in kwargs:
        kwargs["executable_path"] = chrome
    kwargs.setdefault("headless", True)
    extra = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
    existing = list(kwargs.get("args") or [])
    for a in extra:
        if a not in existing:
            existing.append(a)
    kwargs["args"] = existing
    return pw.chromium.launch(**kwargs)


async def new_context(browser, *, ignore_https_errors: bool = False, **kwargs: Any):
    """统一创建 BrowserContext。

    - ``ignore_https_errors=True``：跳过自签/无效证书校验（内网 HTTPS 用），
      默认 ``False``（安全默认，不掩盖中间人攻击）。
    - 统一默认 viewport=1280x720；调用方可覆盖。
    - 默认 locale=zh-CN（中文界面/Accept-Language），便于中文系统录制；
      调用方可传 ``locale=`` 覆盖。

    集中在此，record / replay / auth refresh 共用，避免散落各处的 new_context
    漏配证书策略。
    """
    kwargs.setdefault("viewport", {"width": 1280, "height": 720})
    kwargs.setdefault("locale", "zh-CN")
    kwargs.setdefault("ignore_https_errors", ignore_https_errors)
    return await browser.new_context(**kwargs)
