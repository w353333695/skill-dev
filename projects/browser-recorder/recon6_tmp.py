"""勘察6：React fiber 直取 props.onChange 直接调用（终极驱动手段）。"""
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
                          "--user-data-dir=/tmp/easyops-recon7-profile", "--no-first-run",
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
    await ev(
        "window.__srq=[];const _f=window.fetch;"
        "window.fetch=function(...a){const u=typeof a[0]==='string'?a[0]:(a[0]&&a[0].url)||'';"
        "window.__srq.push(u.slice(0,100));return _f.apply(this,a);};")

    # fiber 探测：找 input 的 React fiber 与 props 里的 onChange/onSearch
    print("fiber:", str(await ev(
        "(()=>{const i=" + GI + ";if(!i)return 'no-input';"
        "const fk=Object.keys(i).find(k=>k.startsWith('__reactFiber$')"
        "||k.startsWith('__reactInternalInstance$')"
        "||k.startsWith('__reactProps$'));"
        "if(!fk)return 'no-fiber:'+Object.keys(i).join(',');"
        "let out={fk};"
        "if(fk.startsWith('__reactProps$')){const pr=i[fk];"
        "out.props=Object.keys(pr||{});out.onChange=typeof pr.onChange;"
        "out.onSearch=typeof pr.onSearch;}"
        "else{const f=i[fk];let cur=f,d=0;"
        "while(cur&&d<6){const pn=cur.memoizedProps?Object.keys(cur.memoizedProps):[];"
        "out['d'+d]=pn.filter(p=>p.startsWith('on')).join(',');cur=cur.return;d++;}}"
        "return JSON.stringify(out);})()"))[:400])

    # 若有 internalInstance：取 memoizedProps.onChange 直接调
    print("direct:", str(await ev(
        "(()=>{const i=" + GI + ";if(!i)return 'no';"
        "const ik=Object.keys(i).find(k=>k.startsWith('__reactInternalInstance$'));"
        "if(!ik)return 'no-inst';"
        "const f=i[ik];const pr=f&&f.memoizedProps;"
        "if(!pr)return 'no-props';"
        "const set=Object.getOwnPropertyDescriptor(i.__proto__,'value').set;"
        "set.call(i,'monitor');"
        "if(typeof pr.onChange==='function'){pr.onChange({target:{value:'monitor'}});"
        "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,bubbles:true}));"
        "i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',keyCode:13,bubbles:true}));"
        "return 'called-onChange+Enter';}"
        "return 'no-cb:'+Object.keys(pr).join(',');})()")))
    await asyncio.sleep(4)
    print("fetch:", str(await ev("JSON.stringify(window.__srq||[])"))[:400])
    print("结果:", str(await ev(
        "JSON.stringify(Array.from(document.querySelectorAll('*'))"
        ".filter(e=>e.childElementCount===0&&/monitor/i.test(e.textContent||'')"
        "&&(e.offsetParent||e.getClientRects().length)).slice(0,6).map(e=>"
        "e.tagName+':'+(e.textContent||'').trim().slice(0,25)))"))[:300])
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
