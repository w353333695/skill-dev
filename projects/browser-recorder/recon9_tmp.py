"""勘察9：点击 launchpad 后毫秒级追踪面板状态。"""
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
    "if(!lp)return 'no-lp';"
    "const s=lp.shadowRoot;"
    "if(!s)return 'no-shadow';"
    "const i=s.querySelector('input');"
    "return JSON.stringify({open:lp.hasAttribute('open'),"
    "cls:lp.className||'',"
    "inputVis:i?!!(i.offsetParent||i.getClientRects().length):false,"
    "rect:i?(r=>[r.x|0,r.y|0,r.w|0,r.h|0])(i.getBoundingClientRect()):null,"
    "nLinks:s.querySelectorAll('eo-link,li').length});})()")


async def main():
    chrome = pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([str(chrome), f"--remote-debugging-port={port}",
                          "--user-data-dir=/tmp/easyops-reconA-profile", "--no-first-run",
                          "--headless=new", "--no-sandbox", "about:blank"],
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

    print("点前:", await ev(LP_STATE))
    for trial in range(3):
        await b.send("Input.dispatchMouseEvent",
                     {"type": "mousePressed", "x": 89, "y": 59, "button": "left",
                      "clickCount": 1}, session_id=sid)
        await b.send("Input.dispatchMouseEvent",
                     {"type": "mouseReleased", "x": 89, "y": 59, "button": "left",
                      "clickCount": 1}, session_id=sid)
        for ms in (0.3, 1.0, 2.5):
            await asyncio.sleep(ms)
            print(f"  t+{ms}s:", str(await ev(LP_STATE))[:150])
    # 组件 API 探测：lp 有没有 open()/show() 方法
    print("组件方法:", str(await ev(
        "(()=>{const lp=Array.from(document.querySelectorAll('*'))"
        ".find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));"
        "return lp?JSON.stringify(Object.getOwnPropertyNames("
        "Object.getPrototypeOf(lp)).filter(n=>!/^[a-z]+$|^connected|^disconnected|"
        "^attributeChanged/.test(n)===false||/open|show|toggle|launch/i.test(n))):'no';})()"))[:250])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
