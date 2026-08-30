"""勘察4：三种填值方式对 antd/React 受控 input 的有效性对照实验。
目标：portal 搜索框（rc_select_1）。判据：input.value 变化 + 监听到 input 事件。"""
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
                          "--user-data-dir=/tmp/easyops-recon5-profile", "--no-first-run",
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

    GET_INPUT = ("Array.from(document.querySelectorAll('#portal-mount-point input'))"
                 ".find(i=>i.offsetParent)")

    # 方式A：native setter + InputEvent
    print("A:", await ev(
        "(()=>{const i=" + GET_INPUT + ";if(!i)return 'no';"
        "window.__ev=[];i.addEventListener('input',()=>window.__ev.push('input'));"
        "const d=Object.getOwnPropertyDescriptor(i.__proto__,'value').set;"
        "i.focus();d.call(i,'');d.call(i,'monitor');"
        "i.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'monitor'}));"
        "return 'A:'+i.value+' ev='+window.__ev.length;})()"))
    await asyncio.sleep(2)
    # 搜索结果出现没
    print("A 后结果:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('*'))"
        ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
        "&&(e.offsetParent||e.getClientRects().length)).slice(0,5).map(e=>e.tagName+':'+"
        "(e.textContent||'').trim().slice(0,25)))"))[:300])

    # 方式B：execCommand insertText（清空后）
    print("B:", await ev(
        "(()=>{const i=" + GET_INPUT + ";if(!i)return 'no';"
        "window.__ev2=[];i.addEventListener('input',()=>window.__ev2.push('i'));"
        "i.focus();i.select();document.execCommand('delete');"
        "const ok=document.execCommand('insertText',false,'monitor');"
        "return 'B:'+i.value+' exec='+ok+' ev='+window.__ev2.length;})()"))
    await asyncio.sleep(2)
    print("B 后结果:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('*'))"
        ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
        "&&(e.offsetParent||e.getClientRects().length)).slice(0,5).map(e=>e.tagName+':'+"
        "(e.textContent||'').trim().slice(0,25)))"))[:300])

    # CDP 逐键（对照）
    r = await b.send("Runtime.evaluate",
                     {"expression": "(()=>{const i=" + GET_INPUT + ";"
                      "if(i){i.scrollIntoView({block:'center'});i.focus();"
                      "const r=i.getBoundingClientRect();"
                      "return JSON.stringify([r.x|0,r.y|0,r.width|0,r.height|0]);}return 'no';})()",
                      "returnByValue": True}, session_id=sid)
    import json as _j
    try:
        x, y, w, h = _j.loads(r["result"]["value"])
        cx, cy = x + w // 2, y + h // 2
        await b.send("Input.dispatchMouseEvent",
                     {"type": "mousePressed", "x": cx, "y": cy, "button": "left",
                      "clickCount": 1}, session_id=sid)
        await b.send("Input.dispatchMouseEvent",
                     {"type": "mouseReleased", "x": cx, "y": cy, "button": "left",
                      "clickCount": 1}, session_id=sid)
        await ev("(()=>{const i=" + GET_INPUT + ";window.__ev3=[];"
                 "i&&i.addEventListener('input',()=>window.__ev3.push('i'));return 'armed';})()")
        for ch in "monitor":
            await b.send("Input.dispatchKeyEvent",
                         {"type": "keyDown", "key": ch, "text": ch}, session_id=sid)
            await b.send("Input.dispatchKeyEvent",
                         {"type": "keyUp", "key": ch}, session_id=sid)
            await asyncio.sleep(0.08)
        print("C:", await ev(
            "(()=>{const i=" + GET_INPUT + ";return 'C:'+(i?i.value:'gone')+' ev='+"
            "(window.__ev3||[]).length;})()"))
        await asyncio.sleep(2)
        print("C 后结果:", str(await ev(
            "JSON.stringify(Array.from(document.querySelectorAll('*'))"
            ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
            "&&(e.offsetParent||e.getClientRects().length)).slice(0,5).map(e=>e.tagName+':'+"
            "(e.textContent||'').trim().slice(0,25)))"))[:300])
    except Exception as e:
        print("C err:", e)
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
