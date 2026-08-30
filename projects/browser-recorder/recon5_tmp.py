"""勘察5：A 方式（native setter+InputEvent）补全事件三件套能否触发搜索请求。"""
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
                          "--user-data-dir=/tmp/easyops-recon6-profile", "--no-first-run",
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

    GI = ("Array.from(document.querySelectorAll('#portal-mount-point input'))"
          ".find(i=>i.offsetParent)")
    # 挂 fetch 监听看搜索请求
    await ev(
        "window.__srq=[];const _f=window.fetch;"
        "window.fetch=function(...a){const u=typeof a[0]==='string'?a[0]:(a[0]&&a[0].url)||'';"
        "window.__srq.push(u.slice(0,90));return _f.apply(this,a);};")

    # A+：InputEvent + change + compositionend + keyup(每字符)
    print("A+:", await ev(
        "(()=>{const i=" + GI + ";if(!i)return 'no';"
        "const d=Object.getOwnPropertyDescriptor(i.__proto__,'value').set;"
        "i.focus();d.call(i,'monitor');"
        "i.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'monitor'}));"
        "i.dispatchEvent(new Event('change',{bubbles:true}));"
        "i.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'monitor'}));"
        "for(const ch of 'monitor')i.dispatchEvent("
        "new KeyboardEvent('keyup',{key:ch,bubbles:true}));"
        "return 'A+:set';})()"))
    await asyncio.sleep(4)
    print("fetch 日志:", await ev("JSON.stringify(window.__srq||[])"))
    print("结果元素:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('*'))"
        ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
        "&&(e.offsetParent||e.getClientRects().length)).slice(0,6).map(e=>"
        "e.tagName+'.'+String(e.className).slice(0,30)+':'+"
        "(e.textContent||'').trim().slice(0,20)))"))[:400])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
