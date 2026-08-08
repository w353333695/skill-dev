# browser_recorder/marker.py
"""视频可视化：注入模拟鼠标光标（跟随 mousemove），使 webm 录屏能看到鼠标位置。

Playwright 的 record_video 不捕获 OS 光标 → webm 里看不到鼠标在哪点。
注入一个跟随 mousemove 的 DOM 元素（SVG 箭头），它会被 webm 捕获。
仅在 video=true 时注入。
"""


CURSOR_INJECT = r"""
(function(){
  if (document.__br_cursor_done) return;
  document.__br_cursor_done = true;
  var c = document.createElement('div');
  c.id = '__br_vcursor';
  c.style.cssText = 'position:fixed;left:-100px;top:-100px;z-index:2147483646;'
    + 'pointer-events:none;width:28px;height:28px;transition:transform 0.06s;';
  c.style.background = 'url(data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22'
    + ' width=%2228%22 height=%2228%22 viewBox=%220 0 28 28%22%3E'
    + '%3Cpath d=%22M3 1L3 22L9 17L13 26L17 24L13 15L21 15Z%22'
    + ' fill=%22white%22 stroke=%22black%22 stroke-width=%222%22 stroke-linejoin=%22round%22/%3E'
    + '%3C/svg%3E) no-repeat';
  document.documentElement.appendChild(c);
  document.addEventListener('mousemove', function(e){
    c.style.left = e.clientX + 'px';
    c.style.top = e.clientY + 'px';
  }, true);
  document.addEventListener('mousedown', function(){ c.style.transform = 'scale(0.85)'; }, true);
  document.addEventListener('mouseup', function(){ c.style.transform = 'scale(1)'; }, true);
})();
"""


__all__ = ["CURSOR_INJECT"]
