"""勘察（干净版）：General tab 登录 → 成功后检查 step1 XPath。"""
import asyncio
import pathlib
import socket
import subprocess

from browser_recorder.cdp import CDPClient

LOGIN_URL = "http://172.30.0.90/next/auth/login"
XP1 = ('//*[@id="main-mount-point"]/base-layout-v3.tpl-page-layout/eo-page-view/'
       'base-layout-v3.tpl-navigation-bar-widget/base-layout-v3.tpl-navigation-var-base-view/'
       'eo-app-bar-wrapper/eo-easy-view[2]/eo-launchpad-button-v2//a')

FILL_JS = (
    "(()=>{const vis=Array.from(document.querySelectorAll('input[type=text]'))"
    ".filter(i=>i.offsetParent);const us=vis[0];"
    "const pw=Array.from(document.querySelectorAll('input[type=password]'))"
    ".filter(i=>i.offsetParent)[0];"
    "const set=(el,v)=>{const d=Object.getOwnPropertyDescriptor("
    "el.__proto__,'value').set;el.focus();d.call(el,v);"
    "el.dispatchEvent(new Event('input',{bubbles:true}));};"
    "set(us,FMT);set(pw,'easyops');return 'filled:'+us.value;})()")

NET_JS = (
    "window.__netLog=[];"
    "const _f=window.fetch;"
    "window.fetch=function(...a){window.__netLog.push(['fetch',String(a[0]).slice(0,90)]);"
    "return _f.apply(this,a).then(r=>{window.__netLog.push(['done',r.status]);return r;});};")


async def main():
    chrome = pathlib.Path.home() / ".cache/ms-playwright/chromium-1208/chrome-linux/chrome"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([str(chrome), f"--remote-debugging-port={port}",
                          "--user-data-dir=/tmp/easyops-recon2-profile", "--no-first-run",
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
        if await ev("document.querySelector('input[type=password]') ? 'y' : 'n'") == "y":
            break
        await asyncio.sleep(0.5)

    # General tab（默认即 General——不点任何 tab）
    await ev(NET_JS)
    await ev(FILL_JS.replace("FMT", repr("easyops")))
    r = await ev(
        "(()=>{const btn=Array.from(document.querySelectorAll('button'))"
        ".find(b=>/sign in/i.test(b.textContent));btn&&btn.click();"
        "return btn?'clicked':'no';})()")
    print("General 提交:", r)
    for i in range(20):
        await asyncio.sleep(1)
        url = await ev("location.href")
        if "auth/login" not in str(url):
            break
    print("url:", url)
    print("net:", await ev("JSON.stringify(window.__netLog||[])"))
    if "auth/login" in str(url):
        print("!! General 登录失败")
        print("text:", str(await ev("document.body.innerText.slice(0,300)"))[:300])
    else:
        # 登录成功：等主页面渲染，验 step1 XPath
        for i in range(15):
            await asyncio.sleep(1)
            v = await ev(
                "(()=>{const e=document.evaluate(%r,document,null,9,null).singleNodeValue;"
                "return e ? 'FOUND' : document.querySelector('#main-mount-point') ? 'MM-ONLY' : 'NONE';})()" % XP1)
            print(f"t={i+1}s step1={v}")
            if v == "FOUND":
                break
        # 结构勘察：main-mount-point 下两层 + 所有含 launchpad 的元素
        print("mm html:", str(await ev(
            "document.querySelector('#main-mount-point').innerHTML.slice(0,400)"))[:400])
        print("launchpad:", str(await ev(
            "JSON.stringify(Array.from(document.querySelectorAll('*'))"
            ".filter(e=>/launchpad/i.test(e.tagName+e.id+e.className))"
            ".slice(0,8).map(e=>e.tagName+'#'+e.id+'.'+String(e.className).slice(0,40)))")))
        # 大小写不敏感 XPath 验证（lowercase 全部 tag）
        print("ci-xpath:", await ev(
            "(()=>{const e=document.evaluate("
            "'//*[@id=\"main-mount-point\"]/*[translate(name(),\"ABCDEFGHIJKLMNOPQRSTUVWXYZ\","
            "\"abcdefghijklmnopqrstuvwxyz\")=\"base-layout-v3.tpl-page-layout\"]',"
            "document,null,9,null).singleNodeValue;"
            "return e ? 'CI-FOUND' : 'CI-MISS';})()"))
        # launchpad button 内的可点元素（用户 XPath 末尾是 //a）
        print("lp inner:", str(await ev(
            "const lp=document.querySelector('eo-launchpad-button-v2')||"
            "Array.from(document.querySelectorAll('*')).find(e=>/^eo-launchpad-button-v2$/i.test(e.tagName));"
            "lp?JSON.stringify({tag:lp.tagName,html:lp.innerHTML.slice(0,200)}):'none'")))
        print("全部按钮:", str(await ev(
            "JSON.stringify(Array.from(document.querySelectorAll('button,a,[role=button]'))"
            ".filter(e=>e.offsetParent).slice(0,15).map(e=>"
            "e.tagName+':'+(e.textContent||'').trim().slice(0,20)))")))
    await b.send("Browser.close")
    await b.close()
    p.terminate()

asyncio.run(asyncio.wait_for(main(), 150))
