# browser_recorder/marker.py
"""视频内联标记：在页面上注入「序号气泡 + 描边框」浮层，随页面被录进视频，
使视频也能像画标截图一样标注每个动作的位置。

设计：
- ``MARKER_INJECT`` 经 ``ctx.add_init_script`` 注入，对所有当前及未来导航生效；
  暴露 ``window.__br_flash_marker(bbox,label,color)`` 与 ``window.__br_clear_marker()``。
- 采用 ``display`` 切换（block / none），**无过渡**，clear 立即生效——保证截图前
  能彻底清掉，不污染截图。
- replay 场景：动作【前】flash（真 lead，"先标后点"），截图前 clear。
- record 场景：事件在 capture 阶段才到，无法真正 lead；改为截图后 flash（近瞬时），
  下次截图前 clear。

平台中性：纯前端浮层 + 通用 DOM API，不耦合任何系统。
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

# 动作类型 → 标记颜色（与 export/annotator 的配色一致）
MARKER_COLOR = {
    "click": "#dc2828",
    "submit": "#dc2828",
    "input": "#285adc",
    "fill": "#285adc",
    "select": "#8c28c8",
    "scroll": "#dcaa1e",
    "navigation": "#148c50",
    "hover": "#787878",
}
_DEFAULT_COLOR = "#dc2828"


MARKER_INJECT = r"""
(function(){
  if (window.__br_marker_installed) return;
  window.__br_marker_installed = true;
  function host(){
    var h = document.getElementById('__br_vmarker');
    if(!h){
      h = document.createElement('div');
      h.id='__br_vmarker';
      h.style.cssText='position:fixed;left:0;top:0;z-index:2147483600;pointer-events:none;'
        +'font-family:Arial,sans-serif;display:none;';   // 默认隐藏；display 切换无过渡、立即生效
      document.documentElement.appendChild(h);
    }
    return h;
  }
  window.__br_flash_marker = function(bbox, label, color){
    try{
      if(!bbox) return;
      var h = host();
      var c = color || '#dc2828';
      h.style.left = bbox.x + 'px';
      h.style.top  = bbox.y + 'px';
      h.innerHTML =
        '<div style="position:relative;width:'+bbox.w+'px;height:'+bbox.h+'px;">'
        + '<div style="position:absolute;inset:0;border:3px solid '+c+';border-radius:5px;background:'+c+'22;"></div>'
        + '<div style="position:absolute;left:'+(bbox.w+6)+'px;top:'+(bbox.h+6)+'px;min-width:24px;height:24px;padding:0 5px;border-radius:12px;'
          + 'background:'+c+';color:#fff;font-size:13px;font-weight:700;line-height:24px;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.45);">'+label+'</div>'
        + '</div>';
      h.style.display='block';   // 立即显示，常驻到 clear
    }catch(e){}
  };
  window.__br_clear_marker = function(){
    try{ var h=document.getElementById('__br_vmarker'); if(h){ h.style.display='none'; h.innerHTML=''; } }catch(e){}
  };
})();
"""


def color_for(kind: str) -> str:
    return MARKER_COLOR.get(kind, _DEFAULT_COLOR)


async def flash_marker(page: "Page", bbox: dict | None, label, kind: str) -> None:
    """在目标位置闪现标记。``label`` 通常是动作序号。

    尽力而为：页面正在关闭/导航（execution context destroyed）时静默跳过——
    标记只是视频里的可视化辅助，不应让收尾抛错或刷警告。
    """
    if not bbox:
        return
    try:
        await page.evaluate(
            "(a)=>{ if(window.__br_flash_marker) window.__br_flash_marker(a.bbox, a.label, a.color); }",
            {"bbox": bbox, "label": str(label), "color": color_for(kind)},
        )
    except Exception:
        pass


async def clear_marker(page: "Page") -> None:
    """清掉标记（立即生效，截图前调用以保证截图干净）。页面已关闭时静默跳过。"""
    try:
        await page.evaluate("() => { if(window.__br_clear_marker) window.__br_clear_marker(); }")
    except Exception:
        pass


__all__ = ["MARKER_INJECT", "MARKER_COLOR", "color_for", "flash_marker", "clear_marker"]
