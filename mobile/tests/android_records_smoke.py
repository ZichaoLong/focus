"""Verify packaged offline reading across a real Android process and network boundary."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import shlex
import subprocess
from pathlib import Path
import time
from uuid import uuid4
from xml.sax.saxutils import escape

import aiohttp

from android_tabs_smoke import pick, switch, tab
from android_webview_smoke import ACTIVITY, PACKAGE, attach, emulator_adb, evaluate, launch, wait_for


@asynccontextmanager
async def panel(session, adb):
    port = None
    ws = None
    try:
        async with asyncio.timeout(25):
            while ws is None:
                try:
                    pid = str(int(adb("shell", "pidof", PACKAGE)))
                    if not port:
                        port = adb("forward", "tcp:0", "localabstract:webview_devtools_remote_" + pid)
                    async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
                        pages = await response.json()
                    page = next((p for p in pages if p["url"] == "file:///android_asset/records.html"), None)
                    if page:
                        ws = await session.ws_connect(page["webSocketDebuggerUrl"])
                except (ValueError, aiohttp.ClientError, OSError, subprocess.SubprocessError):
                    pass
                if ws is None:
                    await asyncio.sleep(.08)
        yield ws
    finally:
        if ws:
            await ws.close()
        if port:
            adb("forward", "--remove", "tcp:" + port)


def seed(adb, lab, sites):
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "pm", "clear", PACKAGE)
    seed_file = lab / "record-entries.xml"
    seed_file.write_text('<map><string name="list">' + escape(json.dumps(sites)) + '</string></map>')
    adb("push", str(seed_file), "/data/local/tmp/focus-records-seed.xml")
    adb("shell", "run-as", PACKAGE, "mkdir", "-p", "shared_prefs")
    adb("shell", "run-as", PACKAGE, "cp", "/data/local/tmp/focus-records-seed.xml", "shared_prefs/instances.xml")


def choose(adb, site):
    adb("shell", "am", "start", "-n", ACTIVITY, "-a", "org.focus.mobile.PICK",
        "-f", "0x34000000", "--es", "target", site["id"])


def click(label):
    return "[...document.querySelectorAll('button')].find(n=>n.textContent.includes(" + json.dumps(label) + "))?.click()"


async def assert_online_only(session, port):
    async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
        assert all(page["url"] != "file:///android_asset/records.html" for page in await response.json())


async def check_server_cleanup(adb, local, site):
    for thread in ("fixture-external-gone", "fixture-archived"):
        key = sha256(thread.encode()).hexdigest()
        sql = ("INSERT INTO books(site,thread,key,title,touched) VALUES("
               f"'{site['id']}|{site['origin']}','{thread}','{key}','{thread}',{int(time.time()*1000)})")
        adb("shell", shlex.join(["run-as", PACKAGE, "sqlite3", "databases/offline-records-v1.db", sql]))
    await evaluate(local, click("选择要清理的离线记录"))
    for label, thread in (("服务端已找不到", "fixture-external-gone"), ("已归档", "fixture-archived")):
        await wait_for(local, "[...document.querySelectorAll('details[open]')].some(d=>"
                       f"d.querySelector('summary').textContent.includes({json.dumps(label)}) && "
                       f"d.querySelector('input[aria-label={thread}]')?.checked)")
    await evaluate(local, click("清理所选 2 条"))
    await wait_for(local, "document.querySelector('.confirm')?.innerText.includes('最后一份')")
    await evaluate(local, click("确认清理"))
    await wait_for(local, "document.querySelector('#status').innerText.includes('已清理 2 条')")
    assert await evaluate(local, "document.querySelectorAll('.entry').length") == 1
    print("Verified external deletion and archive twice through the entry profile; current copy retained", flush=True)


async def open_reader(live):
    button = "[...document.querySelectorAll('.records-shortcut')].find(el=>el.offsetHeight)"
    if not await evaluate(live,"!!"+button):
        await evaluate(live,"document.querySelector('.tb-mid').click()")
    await wait_for(live,"!!"+button)
    await evaluate(live,button+".click()")


async def smoke(args):
    entries = json.loads((args.lab/"instances.json").read_text())
    if not all(e["origin"].startswith("https://10.0.2.2:") for e in entries[:2]):
        raise ValueError("Expected the isolated emulator HTTPS gateways")
    sites = [dict(id=str(uuid4()), origin=e["origin"], name=f"Fixture {i}", sso=False) for i,e in enumerate(entries[:2])]
    site = sites[1]
    adb = emulator_adb(args.adb,args.serial)
    seed(adb,args.lab,sites)
    adb("shell","cmd","connectivity","airplane-mode","disable")
    async with aiohttp.ClientSession() as session:
        choose(adb,site)
        port, live = await attach(session,adb,site["origin"])
        try:
            await wait_for(live,"!!document.querySelector('textarea:not(:disabled)')")
            await evaluate(live, "location.assign('/?focusApp=1&thread=thread-1')")
            await wait_for(live,"!!document.querySelector('textarea:not(:disabled)') && location.search.includes('thread-1') && !!window.__focusMobile")
            await assert_online_only(session, port)
            await open_reader(live)
            async with panel(session,adb) as local:
                await wait_for(local,"!!document.querySelector('input[type=checkbox]')")
                await evaluate(local,"document.querySelector('input').click()")
                await evaluate(local,"setTimeout(()=>document.querySelector('#back').click(),50);true")
            await asyncio.sleep(5)
            await open_reader(live)
            async with panel(session,adb) as local:
                await wait_for(local,"document.body?.innerText.includes('已完整保存')")
                print("online capture:",await evaluate(local,"document.querySelector('#status').textContent"),flush=True)
                await evaluate(local,click('线程列表'))
                print("stored:",await evaluate(local,"document.querySelector('.entry small').innerText"),flush=True)
                await check_server_cleanup(adb, local, site)
            adb("shell","am","force-stop",PACKAGE)
        finally:
            await live.close()
            adb("forward","--remove","tcp:"+port)
        adb("shell","cmd","connectivity","airplane-mode","enable")
        try:
            await asyncio.sleep(1)
            started=time.monotonic()
            launch(adb)
            await pick(adb,"查看离线副本")
            async with panel(session,adb) as local:
                await wait_for(local,"document.querySelectorAll('[data-item]').length>0")
                print(f"offline cold start until readable: {time.monotonic()-started:.2f}s",flush=True)
                # Navigate only bundled disk pages, all the way past the ordinary Web RAM window.
                for _ in range(90):
                    if await evaluate(local,"document.body?.innerText.includes('site-1 question 0')"):
                        break
                    await evaluate(local,click('更早记录'))
                else:
                    raise AssertionError("Missing never-visited beginning")
                await evaluate(local,"document.querySelector('[data-item]').scrollIntoView()")
                await asyncio.sleep(.4)
                print("earliest item after force-stop with airplane mode enabled",flush=True)
            adb("shell","am","force-stop",PACKAGE)
            launch(adb)
            await pick(adb,"查看离线副本")
            async with panel(session,adb) as local:
                await wait_for(local,"document.body?.innerText.includes('site-1 question 0')")
                print("offline reading position restored",flush=True)
                # Walking from the beginning reaches the left group before the equally sized right one.
                for _ in range(90):
                    if await evaluate(local,"[...document.querySelectorAll('button')].some(n=>n.textContent.startsWith('80 条'))"):
                        break
                    await evaluate(local,click('较新记录'))
                await evaluate(local,click('80 条'))
                await wait_for(local,"document.body.innerText.includes('恢复连接后展开')")
                started=time.monotonic()
                adb("shell","cmd","connectivity","airplane-mode","disable")
                await wait_for(local,"!!document.querySelector('.tool-results button')")
                tool=await evaluate(local,"document.querySelector('.tool-results button').innerText")
                print(f"automatic online expansion: {tool} ({time.monotonic()-started:.2f}s)",flush=True)
                assert "left command 0" in tool
                assert await evaluate(local,"document.querySelectorAll('.tool-results button').length") == 80
                await evaluate(local,"document.querySelector('.tool-results button').click()")
                await wait_for(local,"document.querySelector('.tool-detail')?.innerText.includes('private-output-left-0')")
            # Same stable thread/item ids, independent Basic-auth instance and store.
            choose(adb,sites[0])
            await pick(adb,"用户名")
            adb("shell","input","text","tester")
            await pick(adb,"密码")
            adb("shell","input","text",entries[0]["password"])
            adb("shell","input","keyevent","4")
            await pick(adb,"安全保存凭据")
            await pick(adb,"登录")
            port,live=await attach(session,adb,sites[0]["origin"])
            try:
                await wait_for(live,"!!document.querySelector('textarea:not(:disabled)')")
                await evaluate(live,"location.assign('/?focusApp=1&thread=thread-1')")
                await wait_for(live,"document.body?.innerText.includes('right reply')")
                await open_reader(live)
                async with panel(session,adb) as local:
                    await wait_for(local,"!!document.querySelector('input[type=checkbox]')")
                    assert not await evaluate(local,"document.querySelector('input').checked")
                    await evaluate(local,"document.querySelector('input').click()")
                    await evaluate(local,"setTimeout(()=>document.querySelector('#back').click(),50);true")
                await asyncio.sleep(6)
                adb("shell","am","force-stop",PACKAGE)
            finally:
                await live.close()
                adb("forward","--remove","tcp:"+port)
            started=time.monotonic();launch(adb)
            port,live=await attach(session,adb,sites[0]["origin"])
            try:
                await wait_for(live,"!!document.querySelector('textarea:not(:disabled)') && document.body.innerText.includes('right reply')")
                await assert_online_only(session, port)
                print(f"Basic instance cold start to online composer: {time.monotonic()-started:.2f}s",flush=True)
                document = await evaluate(live, "performance.timeOrigin")
                await switch(live, adb, site["origin"])
                async with tab(session, adb, site["origin"]) as other:
                    await wait_for(other, "document.querySelector('.focus-shell')?.dataset.firstScreen==='ready'")
                    await assert_online_only(session, port)
                    await switch(other, adb, sites[0]["origin"])
                await wait_for(live, "document.visibilityState==='visible' && !!document.querySelector('textarea:not(:disabled)')")
                assert await evaluate(live, "performance.timeOrigin") == document
                await assert_online_only(session, port)
                print("Drawer switched cold and resumed the same online document without an offline WebView", flush=True)
                await open_reader(live)
                async with panel(session,adb) as local:
                    await wait_for(local,"document.body?.innerText.includes('已完整保存')")
                    for _ in range(90):
                        if await evaluate(local,"document.body?.innerText.includes('site-0 question 0')"): break
                        await evaluate(local,click('更早记录'))
                    else: raise AssertionError("Instance-specific earliest message missing")
                    adb("shell","cmd","connectivity","airplane-mode","enable")
                    await evaluate(local,click('线程列表'))
                    await evaluate(local,click('选择要清理的离线记录'))
                    await wait_for(local,"document.body.innerText.includes('没有符合条件的旧线程')")
                    await evaluate(local,"const f=document.querySelector('select[aria-label=记录范围]'); f.value='all'; f.dispatchEvent(new Event('change')); true")
                    await wait_for(local,"!!document.querySelector('details summary')")
                    await evaluate(local,"document.querySelector('details summary').click()")
                    await wait_for(local,"!!document.querySelector('.candidate input')")
                    await evaluate(local,"document.querySelector('.candidate input').click()")
                    await evaluate(local,click('清理所选 1 条'))
                    await wait_for(local,"document.querySelector('.confirm')?.innerText.includes('包含当前在读记录')")
                    await evaluate(local,click('确认清理'))
                    await wait_for(local,"document.body?.innerText.includes('暂无记录')")
                    print("Basic reused; separate first items; single-thread deletion while offline",flush=True)
            finally:
                await live.close()
                adb("forward","--remove","tcp:"+port)
        finally:
            adb("shell","cmd","connectivity","airplane-mode","disable")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab",type=Path,required=True)
    parser.add_argument("--serial",required=True)
    parser.add_argument("--adb",default="adb")
    asyncio.run(smoke(parser.parse_args()))
