"""勘察8：launchpad 组件 shadowRoot 内部结构（搜索框/结果列表真实位置）。"""
import asyncio
import pathlib
import socket
import subprocess

from browser_recorder.cdp import CDPClient

LOGIN_URL = "http://172.30.0.90/next/auth/login"


async def main():
    chrome = pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([str(chrome), f"--remote-debugging-port={port}",
                          "--user-data-dir=/tmp/easyops-recon9-profile", "--no-first-run",
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
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mousePressed", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mouseReleased", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    await asyncio.sleep(1.5)

    PROBE = (
        "(()=>{"
        "function findLp(){return Array.from(document.querySelectorAll('*'))"
        ".find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));}"
        "const lp=findLp();"
        "if(!lp)return JSON.stringify({err:'no-lp'});"
        "if(!lp.shadowRoot)return JSON.stringify({err:'no-shadow',"
        "html:lp.innerHTML.slice(0,150)});"
        "const s=lp.shadowRoot;"
        "const inputs=Array.from(s.querySelectorAll('input'));"
        "const links=Array.from(s.querySelectorAll('eo-link, li, [role=option]'));"
        "return JSON.stringify({"
        "inputs:inputs.map(i=>({type:i.type,ph:i.placeholder||'',"
        "rect:(()=>{const r=i.getBoundingClientRect();return [r.x|0,r.y|0];})()})),"
        "links:links.slice(0,10).map(e=>e.tagName+':'+"
        "(e.textContent||'').trim().slice(0,18)),"
        "attrs:{open:lp.hasAttribute('open')},"
        "htmlHead:s.innerHTML.slice(0,300)});})()")
    print("shadow:", str(await ev(PROBE))[:600])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
