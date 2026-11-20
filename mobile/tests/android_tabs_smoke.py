"""Switch the two HTTPS fixture entries through the Android UI and observe their WebSockets."""
import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree import ElementTree

import aiohttp

from android_webview_smoke import PACKAGE, attach, emulator_adb, evaluate, launch, wait_for


@asynccontextmanager
async def tab(session, adb, origin):
    port, ws = await attach(session, adb, origin)
    try:
        yield ws
    finally:
        await ws.close()
        adb("forward", "--remove", "tcp:" + port)


@asynccontextmanager
async def network_trace(session, adb, origin):
    async with tab(session, adb, origin) as ws:
        events = []
        await ws.send_json({"id": 1, "method": "Network.enable"})

        async def record():
            async for msg in ws:
                data = msg.json()
                method, params = data.get("method"), data.get("params", {})
                if method == "Network.webSocketHandshakeResponseReceived" and params["response"]["status"] == 101:
                    events.append("101")
                elif method == "Network.webSocketClosed":
                    events.append("closed")
                elif method == "Network.webSocketFrameReceived":
                    payload = params["response"]["payloadData"]
                    if payload.startswith("{") and json.loads(payload).get("type") == "hello":
                        events.append("hello")
                elif method == "Network.requestWillBeSent" and params["request"]["method"] == "POST":
                    events.append(urlsplit(params["request"]["url"]).path)

        task = asyncio.create_task(record())
        try:
            yield events
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def observed(events, event):
    async with asyncio.timeout(25):
        while event not in events:
            await asyncio.sleep(.1)


async def click_web(ws, selector):
    target = "[...document.querySelectorAll(" + json.dumps(selector) + ")].find(e=>e.offsetWidth && e.offsetHeight)"
    await wait_for(ws, "!!" + target)
    await evaluate(ws, target + ".click()")


async def switch(ws, adb, target):
    await click_web(ws, ".reading-session-switch,.tb-mid")
    await click_web(ws, ".instance-picker")
    await pick(adb, target)


async def pick(adb, target):
    async with asyncio.timeout(25):
        while True:
            raw = await asyncio.to_thread(adb, "exec-out", "uiautomator", "dump", "/dev/tty")
            first, last = raw.find("<hierarchy"), raw.find("</hierarchy>")
            if first >= 0 and last >= 0:
                nodes = ElementTree.fromstring(raw[first:last + len("</hierarchy>")])
                for node in nodes.iter("node"):
                    if node.get("package") == PACKAGE and target in node.get("text", "").splitlines():
                        left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
                        adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                        return
            await asyncio.sleep(.25)


async def prepare(ws, origin, thread, draft, reading):
    previous = await evaluate(ws, "performance.timeOrigin")
    await evaluate(ws, "location.assign(" + json.dumps(origin + "/?focusApp=1&thread=" + thread) + ")")
    await wait_for(ws, "performance.timeOrigin !== " + json.dumps(previous) + " && location.search.includes(" + json.dumps("thread=" + thread) + ") && !!window.__focusSetTabActive && !!document.querySelector('#composer-input:not(:disabled)') && !document.querySelector('.gload')")
    if await evaluate(ws, "!!document.querySelector('.focus-app.reading-mode')"):
        await click_web(ws, ".reading-mode-exit")
    await evaluate(ws, "(()=>{const el=document.querySelector('#composer-input'); el.value=" + json.dumps(draft)
                   + "; el.dispatchEvent(new Event('input',{bubbles:true}));})()")
    await wait_for(ws, "Object.keys(localStorage).some(k=>k.includes('.draft.') && localStorage[k]===" + json.dumps(draft) + ")")
    if reading:
        await click_web(ws, "[data-reading-mode-toggle]")
        await wait_for(ws, "!!document.querySelector('.focus-app.reading-mode')")
    return await evaluate(ws, "performance.timeOrigin")


async def bookmark(ws):
    await wait_for(ws, "document.querySelector('.panes')?.scrollHeight > 2 * document.querySelector('.panes')?.clientHeight")
    before = await evaluate(ws, "document.querySelector('.panes').scrollTop")
    point = await evaluate(ws, """(()=>{const p=document.querySelector('.panes'), r=p.getBoundingClientRect();
      return {x:r.left+r.width/2, y:r.top+r.height/2, deltaX:0, deltaY:Math.round(r.height*(p.scrollTop>p.scrollHeight/2?-1.6:1.6))}})()""")
    await ws.send_json({"id": 7, "method": "Input.dispatchMouseEvent", "params": {"type": "mouseWheel", **point}})
    stored = "JSON.parse(localStorage.getItem('focus-mobile.'+window.__focusMobile.instance+'.focus-web.reading-bookmark'))"
    await wait_for(ws, "(()=>{const a="+stored+"?.anchor,p=document.querySelector('.panes');return a && a.scrollTop>0"
                   + " && Math.abs(p.scrollTop-" + json.dumps(before) + ")>20 && Math.abs(a.scrollTop-p.scrollTop)<1})()")
    saved = await evaluate(ws, stored)
    await check_position(ws, saved)
    return saved


async def check_position(ws, saved):
    anchor = json.dumps(saved["anchor"])
    await wait_for(ws, """(()=>{const a=""" + anchor + """, p=document.querySelector('.panes');
      const row=[...document.querySelectorAll('.turn-anchor[data-turn-id]')].find(r=>r.dataset.turnId===a.id);
      const target=a.chunk ? [...(row?.querySelectorAll('[data-transcript-chunk]')??[])].find(c=>c.dataset.transcriptChunk===a.chunk) : row;
      return p && target && Math.abs(target.getBoundingClientRect().top-p.getBoundingClientRect().top-a.offset)<4})()""")


async def check(ws, thread, draft, reading):
    await wait_for(ws, "location.search.includes(" + json.dumps("thread=" + thread)
                   + ") && document.querySelector('#composer-input')?.value===" + json.dumps(draft)
                   + " && !!document.querySelector('.focus-app.reading-mode')===" + json.dumps(reading))


async def smoke(args):
    sites = json.loads((args.lab / "instances.json").read_text())[:2]
    a, b = [site["origin"] for site in sites]
    if any(urlsplit(site).hostname != "10.0.2.2" for site in (a, b)):
        raise ValueError("Expected the two test gateways")
    adb = emulator_adb(args.adb, args.serial)
    draft_a, draft_b = ("tab-A-" + uuid4().hex, "tab-B-" + uuid4().hex)
    launch(adb)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with tab(session, adb, a) as wa, network_trace(session, adb, a) as events_a:
            start_a = await prepare(wa, a, "thread-1", draft_a, True)
            await observed(events_a, "hello")
            saved = await bookmark(wa)
            events_a.clear()
            await switch(wa, adb, b)
            await observed(events_a, "closed")
            async with tab(session, adb, b) as wb, network_trace(session, adb, b) as events_b:
                start_b = await prepare(wb, b, "thread-2", draft_b, False)
                await observed(events_b, "hello")
                assert "101" not in events_a
                events_b.clear()
                await switch(wb, adb, a)
                await observed(events_b, "closed")
                await observed(events_a, "hello")
                assert events_a.count("101") == 1 and "101" not in events_b
                await check(wa, "thread-1", draft_a, True)
                await check_position(wa, saved)
                assert await evaluate(wa, "performance.timeOrigin") == start_a
                await switch(wa, adb, b)
                await observed(events_b, "hello")
                await check(wb, "thread-2", draft_b, False)
                assert await evaluate(wb, "performance.timeOrigin") == start_b
                assert not any(e.startswith("/") for e in events_a + events_b), (events_a, events_b)
                print("Warm A/B/A/B retained both documents, modes, threads, drafts and the reading anchor. Observed close and 101/hello with no POST.")
        adb("shell", "am", "force-stop", PACKAGE)
        launch(adb)
        async with tab(session, adb, b) as wb:
            await check(wb, "thread-2", draft_b, False)
            rebuilt_b = await evaluate(wb, "performance.timeOrigin")
            assert rebuilt_b != start_b
            await switch(wb, adb, a)
        async with tab(session, adb, a) as wa:
            await check(wa, "thread-1", draft_a, True)
            await check_position(wa, saved)
            assert await evaluate(wa, "performance.timeOrigin") != start_a
            print("After process death both new documents restored their own thread, mode and draft; the reading anchor returned within four CSS pixels.")
            if args.third_origin:
                if urlsplit(args.third_origin).hostname != "127.0.0.1":
                    raise ValueError("The third eviction test entry must be an emulator loopback fixture")
                await switch(wa, adb, args.third_origin)
                # The third entry can still be at its local authorization page.
                # Its creation must already have released the least-recent task.
                async with asyncio.timeout(15):
                    while True:
                        pid = adb("shell", "pidof", PACKAGE)
                        port = adb("forward", "tcp:0", "localabstract:webview_devtools_remote_" + pid)
                        try:
                            async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
                                urls = [p["url"] for p in await response.json()]
                        finally:
                            adb("forward", "--remove", "tcp:" + port)
                        if any(u.startswith(args.third_origin + "/") for u in urls) and not any(u.startswith(b + "/") for u in urls):
                            break
                        await asyncio.sleep(.2)
                adb("shell", "input", "keyevent", "KEYCODE_BACK")
                await pick(adb, b)
                async with tab(session, adb, b) as wb:
                    await check(wb, "thread-2", draft_b, False)
                    assert await evaluate(wb, "performance.timeOrigin") != rebuilt_b
                print("Selecting a third site evicted B. B reopened from its own checkpoint.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--third-origin", help="also select this configured emulator loopback entry to verify eviction")
    parser.add_argument("lab", type=Path)
    asyncio.run(smoke(parser.parse_args()))
