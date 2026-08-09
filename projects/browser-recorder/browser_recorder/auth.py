"""登录态管理：storage_state 复用 + 过期检测 + 重登。

登录态获取优先级：
1. auth/<host>.json 存在 → 加载启动
2. 启动后访问目标页被踢回登录页 → 重登：
   a. 提供了 --username/--password → 自动填表登录（无 UI 也能跑）
   b. 否则 headed 提示人手动登录，回车继续
3. --cdp attach 已登录浏览器（不经过本模块，天然带登录态）

自签证书站点（如内网 easyops）需 ignore_https_errors，由调用方在 new_context 传入。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

GITIGNORE_LINE = "*\n!.gitignore\n"

# 常见登录表单的候选选择器（按优先级）
_USERNAME_SELECTORS = [
    "input#general_login_username",  # easyops
    "input[name=username]", "input[name=account]", "input[name=email]",
    "input[type=text]:visible", "input[placeholder*=用户]", "input[placeholder*=User]",
]
_PASSWORD_SELECTORS = [
    "input#general_login_password",  # easyops
    "input[type=password]",
]
_SUBMIT_SELECTORS = [
    "button[type=submit]", "button:has-text('Sign in')", "button:has-text('登录')",
    "button:has-text('登 录')", "input[type=submit]",
]


class AuthManager:
    def __init__(self, auth_dir: str = ".browser-recorder/auth"):
        self.auth_dir = Path(auth_dir)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self.auth_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE_LINE, encoding="utf-8")

    def state_path(self, url: str) -> Path:
        host = (urlparse(url).netloc or "unknown").replace(":", "_")
        return self.auth_dir / f"{host}.json"

    def has_state(self, url: str) -> bool:
        return self.state_path(url).exists()

    # ---------- 登录 ----------

    def login(self, url: str, username: str | None = None, password: str | None = None,
              ignore_https_errors: bool = False) -> Path:
        """headed 登录导出 storage_state。给了账密则自动填表，否则人手动登录。"""
        import click
        from playwright.sync_api import sync_playwright

        path = self.state_path(url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(ignore_https_errors=ignore_https_errors)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            if username and password:
                self._auto_login(page, username, password)
            else:
                click.echo("请在浏览器中完成登录，完成后回到这里按回车…")
                click.pause()
            context.storage_state(path=str(path))
            browser.close()
        return path

    def ensure_valid(self, context, page, url: str,
                     username: str | None = None, password: str | None = None) -> None:
        """加载 state 后已 goto 目标页；若判定失效则重登（自动填表或引导手动）。"""
        import click

        if not self.looks_like_login_page(page, url):
            return
        if username and password:
            click.echo("检测到登录态已失效，正在用账密自动重登…")
            self._auto_login(page, username, password)
        else:
            click.echo("检测到登录态已失效（被重定向到登录页）。")
            click.echo("请在浏览器中重新登录，完成后回到这里按回车，录制将继续…")
            click.pause()
        path = self.state_path(url)
        context.storage_state(path=str(path))
        click.echo(f"登录态已更新: {path}")

    # ---------- 内部 ----------

    def _auto_login(self, page, username: str, password: str) -> None:
        """自动填表登录：多路选择器依次尝试，提交后等跳转。"""
        user_loc = self._first(page, _USERNAME_SELECTORS)
        pass_loc = self._first(page, _PASSWORD_SELECTORS)
        if not user_loc or not pass_loc:
            raise RuntimeError("未找到登录表单的用户名/密码输入框，请改用手动登录")
        user_loc.fill(username)
        pass_loc.fill(password)
        submit = self._first(page, _SUBMIT_SELECTORS)
        if submit:
            submit.click()
        else:
            pass_loc.press("Enter")
        page.wait_for_timeout(4000)  # 等登录跳转

    @staticmethod
    def _first(page, selectors: list[str]):
        for sel in selectors:
            loc = page.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def looks_like_login_page(self, page, target_url: str) -> bool:
        """启发式判定当前页是否登录页（登录态失效被踢回）。"""
        try:
            current = page.url.lower()
            target_host = urlparse(target_url).netloc
            if urlparse(current).netloc != target_host:
                return True  # 被重定向出站点（SSO 等）
            if any(k in current for k in ("login", "signin", "sign-in", "auth")):
                return True
            return page.locator("input[type=password]").count() > 0
        except Exception:
            return False
