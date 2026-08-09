"""智能截图器 — 双帧策略 + Pillow 点击标记."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw
from playwright.async_api import Page


class Screenshoter:
    """截图管理器.

    双帧策略:
      - 前帧 (before): 上一操作的结果帧 + Pillow 在图上画红圈标记点击坐标
      - 结果帧 (after): DOM 稳定后的全页面截图
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._last_screenshot: Optional[Path] = None

    async def take_before(self, page: Page, step: int, coords: Optional[tuple]) -> Optional[Path]:
        """截取前帧（操作前页面），在图上标记点击坐标."""
        try:
            raw_path = self.screenshots_dir / f"step_{step:03d}_raw.png"
            await page.screenshot(path=str(raw_path), full_page=True)

            out_path = self.screenshots_dir / f"step_{step:03d}_click.jpg"
            self.mark_click(raw_path, coords, out_path)

            # 删除原始 png（仅保留标记后 jpg）
            if raw_path.exists():
                raw_path.unlink()

            self._last_screenshot = out_path
            return out_path
        except Exception:
            return None

    async def take_after(
        self, page: Page, step: int,
        wait_stable: bool = True,
        stable_timeout_ms: int = 5000,
    ) -> Optional[Path]:
        """截取结果帧（操作后页面），可选等待 DOM 稳定."""
        try:
            if wait_stable:
                await self._wait_dom_stable(page, stable_timeout_ms)

            out_path = self.screenshots_dir / f"step_{step:03d}_result.jpg"
            await page.screenshot(path=str(out_path), full_page=True)
            self._last_screenshot = out_path
            return out_path
        except Exception:
            return None

    async def take_nav_result(self, page: Page, step: int) -> Optional[Path]:
        """截取导航结果帧（等 networkidle）."""
        try:
            await page.wait_for_load_state("networkidle")
            out_path = self.screenshots_dir / f"step_{step:03d}_result.jpg"
            await page.screenshot(path=str(out_path), full_page=True)
            self._last_screenshot = out_path
            return out_path
        except Exception:
            return None

    def mark_click(
        self, src: Path, coords: Optional[tuple], output: Path,
        radius: int = 15, color: str = "red", width: int = 3,
    ) -> Path:
        """在图片上用 Pillow 画红色圆圈标记点击位置."""
        img = Image.open(src)
        if coords is not None:
            draw = ImageDraw.Draw(img)
            x, y = coords
            draw.ellipse(
                [x - radius, y - radius, x + radius, y + radius],
                outline=color, width=width,
            )
            # 画十字线
            draw.line([x - radius - 5, y, x + radius + 5, y], fill=color, width=2)
            draw.line([x, y - radius - 5, x, y + radius + 5], fill=color, width=2)
        img.save(str(output), quality=85)
        return output

    def get_last_before(self) -> Optional[Path]:
        """返回最近一次截图路径（作为下一步的前帧）."""
        return self._last_screenshot

    async def fallback_shot(self, page: Page, step: int) -> Optional[Path]:
        """兜底定时截图（无操作时）."""
        out_path = self.screenshots_dir / f"step_{step:03d}_shot.jpg"
        try:
            await page.screenshot(path=str(out_path), full_page=True)
            self._last_screenshot = out_path
            return out_path
        except Exception:
            return None

    @staticmethod
    async def _wait_dom_stable(page: Page, timeout_ms: int = 5000) -> None:
        """等待 DOM 稳定."""
        try:
            await page.evaluate("window.__recorder_stable__ = false;")
            await page.wait_for_function(
                "window.__recorder_stable__ === true",
                timeout=timeout_ms,
            )
        except Exception:
            pass  # 超时不报错
