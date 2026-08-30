"""勘察B：禁动画后 launchpad 面板 rect 是否正常。"""
import asyncio
import pathlib
import socket
import subprocess

from browser_recorder.cdp import CDPClient

LOGIN_URL = "http://172.30.0.90/next/auth/login"

LP_STATE = (
    "(()=>{"
    "const lp=Array.from(document.querySelectorAll('*'))"
    ".find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));"
    "if(!lp||!lp.shadowRoot)return 'no';"
    "const i=lp.shadowRoot.querySelector('input');"
    "return JSON.stringify({inputVis:i?!!(i.offsetParent||i.getClientRects().length):false,"
    "rect:i?(r=>[r.x|0,r.y|0,r.w|0,r.h|0])(i.getBoundingClientRect()):null,"
    "nLinks:lp.shadowRoot.querySelectorAll('eo-link,li').length});})()")


async def main():
    chrome = pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([str(chrome), f"--remote-debugging-port={port}",
                          "--user-data-dir=/tmp/easyops-reconB-profile", "--no-first-run",
                          "--headless=new", "--no-sandbox",
                          "--force-prefers-reduced-motion", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(2.5)
    b = await CDPClient.connect_browser(port)
    r = await b.send("Target.getTargets")
    page = [t for t in r["targetInfos"] if t["type"] == "page"][0]
    r2 = await b.send("Target.attachToTarget", {"targetId": page["targetId"],
                                                 "flatten": True})
    sid = r2["sessionId"]
    await b.send("Page.navigate", {"url": LOGIN_URL}, session_id=sid)

    async def ev(expr):
        r = await b.send("Runtime.evaluate",
                         {"expression": expr, "returnByValue": True}, session_id=sid)
        return r.get("result", {}).get("value")

    for _ in range(30):
        if await ev("document.querySelector('input[type=password]')?'y':'n'") == "y":
            break
        await asyncio.sleep(0.5)
    # 禁动画：启动参数已带 --force-prefers-reduced-motion；再加 CSS 注入兜底
    await b.send("Page.addScriptToEvaluateOnNewDocument", {"source":
        "const s=document.createElement('style');"
        "s.textContent='*,*::before,*::after{animation:none!important;"
        "transition:none!important}';"
        "document.addEventListener('DOMContentLoaded',()=>"
        "document.head&&document.head.appendChild(s));"}, session_id=sid)
    await ev(
        "(()=>{const us=Array.from(document.querySelectorAll('input[type=text]'))"
        ".filter(i=>i.offsetParent)[0];"
        "const pw=Array.from(document.querySelectorAll('input[type=password]'))"
        ".filter(i=>i.offsetParent)[0];"
        "const set=(el,v)=>{const d=Object.getOwnPropertyDescriptor(el.__proto__,'value').set;"
        "el.focus();d.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));};"
        "set(us,'easyops');set(pw,'easyops');"
        "const btn=Array.from(document.querySelectorAll('button'))"
        ".find(b=>/sign in/i.test(b.textContent));"
        "setTimeout(()=>btn&&btn.click(),200);return 'sent';})()")
    for _ in range(20):
        await asyncio.sleep(1)
        if "auth/login" not in str(await ev("location.href")):
            break
    await asyncio.sleep(3)
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mousePressed", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mouseReleased", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    for ms in (0.5, 1.5, 3.0):
        await asyncio.sleep(ms)
        print(f"t+{ms}s:", str(await ev(LP_STATE))[:130])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
