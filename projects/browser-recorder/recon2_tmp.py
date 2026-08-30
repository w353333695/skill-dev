"""勘察2：真鼠标点 launchpad 后，页面上新增了什么（input 在哪）。"""
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
                          "--user-data-dir=/tmp/easyops-recon3-profile", "--no-first-run",
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

    # 真鼠标点 launchpad
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mousePressed", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    await b.send("Input.dispatchMouseEvent",
                 {"type": "mouseReleased", "x": 89, "y": 59, "button": "left",
                  "clickCount": 1}, session_id=sid)
    await asyncio.sleep(2)

    # 点后页面状态
    print("所有可见 input:", await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('input'))"
        ".filter(i=>i.offsetParent).map(i=>({type:i.type,ph:i.placeholder||'',"
        "rect:(()=>{const r=i.getBoundingClientRect();return [r.x|0,r.y|0,r.width|0,r.height|0]})()})))"))
    print("body 直接子元素:", await ev(
        "JSON.stringify(Array.from(document.body.children).map(e=>"
        "e.tagName+'#'+(e.id||'')+'.'+String(e.className).slice(0,30)))"))
    print("launchpad attr:", await ev(
        "(()=>{const lp=Array.from(document.querySelectorAll('*'))"
        ".find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));"
        "return lp?JSON.stringify({open:lp.hasAttribute('open'),"
        "expanded:lp.hasAttribute('expanded'),"
        "cls:String(lp.className).slice(0,50)}):'gone';})()"))
    # shadow 内部探
    print("shadow 探测:", await ev(
        "(()=>{const lp=Array.from(document.querySelectorAll('*'))"
        ".find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));"
        "if(!lp)return 'no-lp';"
        "function walk(root,d){let out=[];"
        "for(const el of root.querySelectorAll('*')){"
        "out.push('  '.repeat(d)+el.tagName+'.'+String(el.className).slice(0,25));"
        "if(el.shadowRoot&&d<3)out=out.concat(walk(el.shadowRoot,d+1));}"
        "return out;}"
        "return walk(lp.shadowRoot||lp,0).slice(0,25).join('\\n');})()"))
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 120))
