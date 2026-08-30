"""勘察3：输完 monitor 后，下拉/结果到底渲染在哪。"""
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
                          "--user-data-dir=/tmp/easyops-recon4-profile", "--no-first-run",
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

    # focus 搜索框 + CDP 输入
    await ev(
        "(()=>{const i=Array.from(document.querySelectorAll('#portal-mount-point input'))"
        ".find(i=>i.offsetParent);i&&i.scrollIntoView({block:'center'});"
        "i&&i.focus();return i?'f':'n';})()")
    await b.send("Input.insertText", {"text": "monitor"}, session_id=sid)
    print("typed; input.value =", await ev(
        "(()=>{const i=Array.from(document.querySelectorAll('#portal-mount-point input'))"
        ".find(i=>i.offsetParent);return i?i.value:'gone';})()"))
    await asyncio.sleep(3)

    # 找下拉/结果：所有含 monitor 文本的可见元素
    print("monitor 元素:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('*'))"
        ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
        "&&(e.offsetParent||e.getClientRects().length))"
        ".slice(0,12).map(e=>({tag:e.tagName,cls:String(e.className).slice(0,40),"
        "t:(e.textContent||'').trim().slice(0,30),"
        "rect:(()=>{const r=e.getBoundingClientRect();"
        "return [r.x|0,r.y|0,r.width|0,r.height|0]})()})))"))[:800])
    print("dropdown 类元素:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll("
        "'[class*=dropdown],[class*=option],[class*=result],[class*=list]'))"
        ".filter(e=>e.offsetParent).slice(0,10).map(e=>"
        "e.tagName+'.'+String(e.className).slice(0,50)))"))[:500])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 120))
