"""登录态管理：storage_state 复用 + 过期检测 + 原地重登。

三层策略（record 流程内自动降级）：
1. auth/<host>.json 存在 → 加载启动
2. 启动后访问目标页，启发式检测被踢回登录页 → 提示原地重登 → 重新导出覆盖，继续录制
3. --cdp attach 已登录浏览器（不经过本模块，天然带登录态）
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

GITIGNORE_LINE = "*\n!.gitignore\n"


class AuthManager:
    def __init__(self, auth_dir: str = ".browser-recorder/auth"):
        self.auth_dir = Path(auth_dir)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        # 双保险：目录内全忽略
        gitignore = self.auth_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE_LINE, encoding="utf-8")

    def state_path(self, url: str) -> Path:
        host = urlparse(url).netloc or "unknown"
        host = host.replace(":", "_")
        return self.auth_dir / f"{host}.json"

    def has_state(self, url: str) -> bool:
        return self.state_path(url).exists()

    def login(self, url: str) -> Path:
        """headed 打开浏览器，人手动登录，回车后导出 storage_state。"""
        import click
        from playwright.sync_api import sync_playwright

        path = self.state_path(url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            click.echo("请在浏览器中完成登录，完成后回到这里按回车…")
            click.pause()
            context.storage_state(path=str(path))
            browser.close()
        return path

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

    def ensure_valid(self, context, page, url: str) -> None:
        """加载 state 后已 goto 目标页；若判定失效则引导原地重登并重导。"""
        import click

        if not self.looks_like_login_page(page, url):
            return
        click.echo("检测到登录态已失效（被重定向到登录页）。")
        click.echo("请在浏览器中重新登录，完成后回到这里按回车，录制将继续…")
        click.pause()
        path = self.state_path(url)
        context.storage_state(path=str(path))
        click.echo(f"登录态已更新: {path}")
