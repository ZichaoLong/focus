"""Exercise real WebView link navigation and Android Back on the isolated emulator fixture."""
import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from xml.etree import ElementTree

import aiohttp

from android_page_retention import choose, nodes, tap
from android_tabs_smoke import click_web, tab
from android_webview_smoke import PACKAGE, emulator_adb, evaluate, launch, wait_for


def resumed(adb):
    return next((line for line in adb("shell", "dumpsys", "activity", "activities").splitlines()
                 if "topResumedActivity=" in line), "")


@asynccontextmanager
async def at_page(session, adb, process, address):
    async with asyncio.timeout(25):
        while True:
            port = ""
            try:
                pid = str(int(adb("shell", "pidof", PACKAGE + process)))
                port = adb("forward", "tcp:0", "localabstract:webview_devtools_remote_" + pid)
                async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
                    pages = await response.json()
                found = next((p for p in pages if p["url"] == address), None)
                if found:
                    ws = await session.ws_connect(found["webSocketDebuggerUrl"])
                    break
            except (subprocess.SubprocessError, ValueError, aiohttp.ClientError):
                pass
            if port:
                adb("forward", "--remove", "tcp:" + port)
            await asyncio.sleep(.25)
    try:
        yield ws
    finally:
        await ws.close()
        adb("forward", "--remove", "tcp:" + port)


async def press_link(ws, text):
    element = "[...(document.querySelector('.file-preview')||document).querySelectorAll('a,button')].find(e=>e.offsetWidth && e.textContent.trim()===" + json.dumps(text) + ")"
    await wait_for(ws, "!!" + element)
    xy = await evaluate(ws, "(async()=>{const e=" + element + ";e.scrollIntoView({block:'center'});"
                        "await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));"
                        "const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2}})()")
    scroll = await evaluate(ws, "document.querySelector('.panes')?.scrollTop")
    for kind in ("mousePressed", "mouseReleased"):
        await ws.send_json({"id": 71, "method": "Input.dispatchMouseEvent", "params": {
            "type": kind, **xy, "button": "left", "clickCount": 1}})
        while (await ws.receive_json(timeout=10)).get("id") != 71:
            pass
    return scroll


def entries(adb):
    prefs = ElementTree.fromstring(adb("shell", "run-as", PACKAGE, "cat", "shared_prefs/instances.xml"))
    return json.loads(prefs.findtext("*[@name='list']", "[]"))


def change_sso(adb, site, enabled):
    choose(adb, "管理实例")
    choose(adb, "管理 " + site["name"])
    choose(adb, "编辑")
    box = next(n for n in nodes(adb) if n.get("class") == "android.widget.CheckBox")
    changed = (box.get("checked") == "true") != enabled
    if changed:
        tap(adb, box)
    choose(adb, "保存")
    choose(adb, "返回对话")
    return changed


@asynccontextmanager
async def ready_tab(session, adb, origin, replaced=None):
    # Changing sign-in policy replaces the WebView. CDP may briefly list the old document.
    async with AsyncExitStack() as stack:
        async with asyncio.timeout(50):
            while True:
                ws = await stack.enter_async_context(tab(session, adb, origin))
                try:
                    started = await evaluate(ws, "!document.hidden && typeof window.__focusBack==='function' && "
                                              "!!document.querySelector('#composer-input:not(:disabled)') && performance.timeOrigin")
                    if started and started != replaced:
                        break
                except (TypeError, aiohttp.ClientError, AssertionError):
                    pass
                await stack.aclose()
                await asyncio.sleep(.25)
        yield ws


async def run(args):
    sites = json.loads((args.lab / "instances.json").read_text())[:2]
    guest = (args.lab / "guest-origin.txt").read_text().strip()
    a, b = (site["origin"] for site in sites)
    assert all(urlsplit(origin).hostname == "10.0.2.2" for origin in (a, b, guest))
    adb = emulator_adb(args.adb, args.serial)
    saved = next(x for x in entries(adb) if x["origin"] == a)
    if args.edge_gesture:
        if adb("shell", "settings", "get", "secure", "navigation_mode") != "2":
            raise ValueError("--edge-gesture requires gesture navigation on the test emulator")
        width, height = map(int, re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1])

    def back():
        if args.edge_gesture:
            adb("shell", "input", "touchscreen", "swipe", "1", str(height // 2), str(width // 2), str(height // 2), "240")
        else:
            adb("shell", "input", "keyevent", "KEYCODE_BACK")

    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-W", "-a", "org.focus.mobile.PICK", "-n", PACKAGE + "/org.focus.mobile.MainActivity")
    await asyncio.to_thread(choose, adb, a)
    async with aiohttp.ClientSession() as session:
        for sso in (False, True):
            async with ready_tab(session, adb, a) as ws:
                previous = await evaluate(ws, "performance.timeOrigin")
                await click_web(ws, ".instance-drawer-trigger,.instance-picker")
            changed = await asyncio.to_thread(change_sso, adb, saved, sso)
            async with ready_tab(session, adb, a, previous if changed else None) as ws:
                if not await evaluate(ws, "location.search.includes('thread=thread-1')"):
                    await evaluate(ws, "location.assign('/?focusApp=1&thread=thread-1')")
                await wait_for(ws, "!!document.querySelector('#composer-input:not(:disabled)') && [...document.links].some(a=>a.textContent.trim()==='Navigation catalog')")
                if await evaluate(ws, "!!document.querySelector('.focus-app.reading-mode')"):
                    await click_web(ws, ".reading-mode-exit")
                document = await evaluate(ws, "performance.timeOrigin")
                await evaluate(ws, "(()=>{const input=document.querySelector('#composer-input');input.value='navigation draft';"
                               "input.dispatchEvent(new Event('input',{bubbles:true}));document.cookie='navigation_source=focus;path=/;secure'})()")
                await press_link(ws, "Navigation catalog")
                await click_web(ws, ".file-download-actions button:nth-last-child(2)")
                await wait_for(ws, "document.querySelector('.file-preview-markdown')?.innerText.includes('Open article')")
                await press_link(ws, "Open article")
                async with at_page(session, adb, ":external", guest + "/article") as external:
                    await wait_for(external, "document.body?.innerText.includes('External article')")
                    assert await evaluate(external, "window.__focusMobile===undefined")
                    assert "ExternalPageActivity" in resumed(adb)
                back()
                await wait_for(ws, "!document.hidden && document.querySelector('.file-preview-markdown')?.innerText.includes('Open child')")
                assert await evaluate(ws, "performance.timeOrigin") == document
                await press_link(ws, "Open child")
                await click_web(ws, ".file-download-actions button:nth-last-child(2)")
                await wait_for(ws, "document.querySelector('.file-preview-filename')?.textContent.includes('sample.txt')")
                back()
                await wait_for(ws, "document.querySelector('.file-preview-markdown')?.innerText.includes('Open child')")
                back()
                await wait_for(ws, "!document.querySelector('.file-preview') && document.querySelector('#composer-input')?.value==='navigation draft'")
                if not await evaluate(ws, "!!document.querySelector('.focus-app.reading-mode')"):
                    await click_web(ws, ".reading-mode-entry")
                await wait_for(ws, "!!document.querySelector('.focus-app.reading-mode')")
                position = await press_link(ws, "Open article")
                async with at_page(session, adb, ":external", guest + "/article") as external:
                    await wait_for(external, "document.body?.innerText.includes('External article')")
                back()
                await wait_for(ws, "!document.hidden && !!document.querySelector('.focus-app.reading-mode')")
                assert abs(await evaluate(ws, "document.querySelector('.panes').scrollTop") - position) < 5
                await click_web(ws, ".reading-mode-exit")
                print(f"SSO={sso}: redirected guest, isolated cookies, preview trail, original document and draft passed", flush=True)
                if sso:
                    await evaluate(ws, "location.assign('/test-sso')")
                else:
                    await ws.send_json({"id": 81, "method": "Page.navigate", "params": {"url": a + "/test-sso"}})
                    while (reply := await ws.receive_json(timeout=15)).get("id") != 81:
                        pass
                    assert reply["result"].get("errorText") == "net::ERR_ABORTED", reply["result"]
                    assert "ExternalPageActivity" not in resumed(adb)
                    print("Unsolicited sign-in redirect blocked with SSO off", flush=True)
            if sso:
                async with at_page(session, adb, "", guest + "/signin-0") as identity:
                    assert await evaluate(identity, "window.__focusMobile===undefined")
                    await press_link(identity, "Continue to Focus")
                async with tab(session, adb, a) as ws:
                    await wait_for(ws, "typeof window.__focusBack==='function' && !!document.querySelector('#composer-input:not(:disabled)')")
                print("Cross-origin sign-in and return passed in the instance WebView", flush=True)

        async with ready_tab(session, adb, a) as ws:
            previous = await evaluate(ws, "performance.timeOrigin")
            await click_web(ws, ".instance-drawer-trigger,.instance-picker")
        if not saved.get("sso"):
            changed = await asyncio.to_thread(change_sso, adb, saved, False)
            async with ready_tab(session, adb, a, previous if changed else None) as ws:
                await click_web(ws, ".instance-drawer-trigger,.instance-picker")
        await asyncio.to_thread(choose, adb, b)
        async with ready_tab(session, adb, b) as ws:
            document = await evaluate(ws, "performance.timeOrigin")
            component = next(word for word in resumed(adb).split() if word.startswith(PACKAGE + "/"))

            async def wait_drawer(visible):
                # Native view dumps avoid UIAutomator's idle wait consuming the double-Back window.
                async with asyncio.timeout(5):
                    while ("android.widget.ScrollView{" in adb("shell", "dumpsys", "activity", component)) != visible:
                        await asyncio.sleep(.05)

            await click_web(ws, ".instance-drawer-trigger,.instance-picker")
            await wait_drawer(True)
            back()
            await wait_drawer(False)
            assert component in resumed(adb)
            back()
            await wait_drawer(True)
            await asyncio.sleep(2.2)
            back()
            await wait_drawer(False)
            assert component in resumed(adb)
            back()
            await wait_drawer(True)
            back()
            async with asyncio.timeout(10):
                while not (activity := resumed(adb)) or PACKAGE in activity:
                    await asyncio.sleep(.2)
            await asyncio.sleep(1)
            assert PACKAGE not in resumed(adb)
            launch(adb)
            await wait_for(ws, "!document.hidden")
            assert await evaluate(ws, "performance.timeOrigin") == document
        print("Manual and expired drawer Back returned to the conversation; double root Back backgrounded the same live instance", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--edge-gesture", action="store_true", help="send system edge swipes instead of KEYCODE_BACK")
    asyncio.run(run(parser.parse_args()))
