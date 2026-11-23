"""Verify packaged offline reading across a real Android process and network boundary."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import re
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
async def panel(session, adb, url="file:///android_asset/records.html"):
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
                    page = next((p for p in pages if p["url"] == url), None)
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


def offline_db(adb, sql):
    return adb("shell", shlex.join(["run-as", PACKAGE, "sqlite3", "-cmd", ".timeout 3000",
                                    "databases/offline-records-v1.db", sql]))


def click(label):
    return "[...document.querySelectorAll('button')].find(n=>n.textContent.includes(" + json.dumps(label) + "))?.click()"


async def assert_online_only(session, port):
    async with asyncio.timeout(35):
        while True:
            async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
                urls = {page["url"] for page in await response.json()}
            assert "file:///android_asset/records.html" not in urls
            if "https://conversation.focus.invalid/conversation.html" not in urls:
                return
            await asyncio.sleep(.1)


async def wait_for_online_handoff(session, adb, origin):
    port, live = await attach(session, adb, origin)
    try:
        await assert_online_only(session, port)
        await wait_for(live, """(() => {
          const pane=document.querySelector('.panes'), box=pane?.getBoundingClientRect();
          if (!box) return false;
          return Array.from(pane.querySelectorAll('[data-turn-id^="turn-0:item:"]')).some(node=>{
            const row=node.getBoundingClientRect();
            return row.height>0 && row.bottom>box.top && row.top<box.bottom;
          });
        })()""")
        print("Ordinary online chat resumed at the saved first turn", flush=True)
    finally:
        await live.close()
        adb("forward","--remove","tcp:"+port)


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


async def open_saved_reader(chat):
    await evaluate(chat, "document.querySelector('.tb-mid,.reading-session-switch').click()")
    await wait_for(chat, "!!document.querySelector('.saved-menu .saved-copy-action')")
    await evaluate(chat, "document.querySelector('.saved-copy-action').click()")


PARAGRAPH = """[...document.querySelectorAll('.chat p')].find(p => p.textContent.startsWith('Reading a saved conversation.'))"""
GEOMETRY = """(() => {
  const p=PARAGRAPH, pane=document.querySelector('.chat-scroll').getBoundingClientRect();
  const range=new Range(); range.selectNodeContents(p);
  return [pane.left,pane.top,pane.right,pane.bottom,...Array.from(range.getClientRects()).flatMap(r=>[r.x,r.y,r.width,r.height])];
})()""".replace("PARAGRAPH", PARAGRAPH)


async def check_cold_layout(session, adb, origin, reading):
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "cmd", "connectivity", "airplane-mode", "enable")
    launch(adb)
    async with panel(session, adb, "https://conversation.focus.invalid/conversation.html") as local:
        await wait_for(local, "!!(" + PARAGRAPH + ") && document.fonts.status==='loaded'")
        assert await evaluate(local, "document.documentElement.dataset.colorScheme") == "dark"
        assert await evaluate(local, "getComputedStyle(document.body).fontSize") == "17px"
        assert await evaluate(local, "!!document.querySelector('.reading-mode-controls')") == reading
        assert not await evaluate(local, "!!document.querySelector('textarea:not(:disabled)')")
        assert not await evaluate(local, "!!document.querySelector('.saved-copy-action')")
        # Move within a wrapped reply during the reconnect wait, not just to the beginning of a turn.
        await evaluate(local, """(() => {
          const p=PARAGRAPH, pane=document.querySelector('.chat-scroll');
          p.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
          pane.scrollTop += p.getBoundingClientRect().top-pane.getBoundingClientRect().top+76;
          p.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
        })()""".replace("PARAGRAPH", PARAGRAPH))
        await asyncio.sleep(3)
        before = await evaluate(local, GEOMETRY)
        assert len(before) > 24
        if reading:
            await evaluate(local, "document.querySelector('.chat-scroll').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))")
        else:
            await evaluate(local, "document.querySelector('.tb-mid').click()")
            await wait_for(local, "!!document.querySelector('.saved-copy-action')")
        adb("shell", "cmd", "connectivity", "airplane-mode", "disable")
        async with tab(session, adb, origin) as live:
            await wait_for(live, "!!document.querySelector('.focus-shell[data-online-conversation=ready][data-first-screen=ready] .chat-scroll [data-turn-id]')")
            # The live page is painted behind the ongoing local interaction.
            if reading:
                await evaluate(local, "document.querySelector('.chat-scroll').scrollTop += 32")
                await asyncio.sleep(.25)
                before = await evaluate(local, GEOMETRY)
                await evaluate(local, "window.dispatchEvent(new PointerEvent('pointerup'))")
            else:
                assert await evaluate(local, "!!document.querySelector('.saved-menu')")
                adb("shell", "input", "keyevent", "KEYCODE_BACK")
    port, live = await attach(session, adb, origin)
    try:
        await assert_online_only(session, port)
        await wait_for(live, "!!(" + PARAGRAPH + ") && document.fonts.status==='loaded'")
        await asyncio.sleep(.7)
        assert await evaluate(live, "!!document.querySelector('.reading-mode-controls')") == reading
        after = await evaluate(live, GEOMETRY)
        assert len(after) == len(before), (len(before), len(after))
        difference = max(abs(a - b) for a, b in zip(before, after))
        assert difference <= 1.5, (reading, difference, before[:12], after[:12])
        print(f"{'Reading' if reading else 'Normal'} cold handoff after 3s: {len(after[4:])//4} text rectangles, max change {difference:.2f} CSS px", flush=True)
        if not reading:
            assert await evaluate(live, "document.querySelector('textarea:not(:disabled)').value") == "handoff draft"
            await evaluate(live, "document.querySelector('[data-reading-mode-toggle]').click()")
            await wait_for(live, "!!document.querySelector('.reading-mode-controls')")
        else:
            await evaluate(live, "document.querySelector('.reading-mode-exit').click()")
            await wait_for(live, "!!document.querySelector('.tb-mid')")
        await asyncio.sleep(.5)
    finally:
        await live.close()
        adb("forward", "--remove", "tcp:" + port)


async def switch_with_server_held(live, lab, adb):
    await evaluate(live,"document.querySelector('.tb-mid').click()")
    await wait_for(live,"!!document.querySelector('.srow:not(.cur)')")
    await evaluate(live,"document.querySelector('.srow:not(.cur)').click()")
    await wait_for(live,"location.search.includes('thread-2') && !!document.querySelector('textarea:not(:disabled)')")
    await wait_for(live,"document.querySelector('.panes')?.innerText.includes('First visit saved immediately')")
    await evaluate(live,"""window.testFetch=window.fetch; window.fetch=async (...args)=>{
      if(String(args[0]).includes('/threads/thread-1/open')) await new Promise(r=>window.releaseOpen=r);
      return window.testFetch(...args)};
      document.querySelector('.tb-mid').click()""")
    await wait_for(live,"!!document.querySelector('.srow:not(.cur)')")
    await evaluate(live,"window.tapped=performance.now(); document.querySelector('.srow:not(.cur)').click()")
    await wait_for(live,"!!window.releaseOpen && document.querySelector('.panes')?.innerText.includes('right reply')")
    print("warm tap to readable while server open is held: %.0f ms" %
          await evaluate(live,"performance.now()-window.tapped"),flush=True)
    # The new thread got its first reading window on the foreground read, even after immediately leaving.
    query=shlex.join(["run-as",PACKAGE,"sqlite3","-cmd",".timeout 3000","databases/offline-records-v1.db",
                      "SELECT COUNT(*) FROM reading_pages p JOIN chunks c USING(run) WHERE thread='thread-2' AND instr(body,'First visit saved immediately')"])
    assert int(adb("shell",query))>0
    (lab/"arrived-1").touch()
    await evaluate(live,"window.releaseOpen(); window.fetch=window.testFetch")
    await wait_for(live,"!!document.querySelector('textarea:not(:disabled)') && document.querySelector('.panes')?.innerText.includes('right reply')")
    await wait_for(live,"document.querySelector('.panes')?.innerText.includes('Arrived while away')")
    assert await evaluate(live,"document.querySelectorAll('[data-turn-id*=\"item:after-reopen:0\"]').length") == 1
    assert await evaluate(live,"document.querySelectorAll('[data-turn-id*=\"item:right:0\"]').length") == 1


async def smoke(args):
    (args.lab/"arrived-1").unlink(missing_ok=True)
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
            # The management page shows the edition opened by the user. Wait for durable completion
            # before opening it, including on slow emulators.
            async with asyncio.timeout(60):
                query=shlex.join(["run-as",PACKAGE,"sqlite3","-cmd",".timeout 3000","databases/offline-records-v1.db",
                                  "SELECT complete FROM runs JOIN books ON visible=run WHERE books.thread='thread-1'"])
                while adb("shell",query)!="1":
                    await asyncio.sleep(.2)
            await open_reader(live)
            async with panel(session,adb) as local:
                await wait_for(local,"document.body?.innerText.includes('已完整保存')")
                print("online capture:",await evaluate(local,"document.querySelector('#status').textContent"),flush=True)
                await evaluate(local,click('线程列表'))
                print("stored:",await evaluate(local,"document.querySelector('.entry small').innerText"),flush=True)
                await check_server_cleanup(adb, local, site)
                await evaluate(local,"setTimeout(()=>document.querySelector('#back').click(),50);true")
            await switch_with_server_held(live,args.lab,adb)
            await evaluate(live, """localStorage.setItem('kimi-web.color-scheme','dark');
                localStorage.setItem('kimi-web.ui-font-size','17'); setTimeout(()=>location.reload(),20); true""")
            await wait_for(live, "document.documentElement.dataset.colorScheme==='dark' && !!document.querySelector('textarea:not(:disabled)')")
            await wait_for(live, "!!(" + PARAGRAPH + ")")
            await evaluate(live, """const editor=document.querySelector('textarea:not(:disabled)');
                editor.value='handoff draft'; editor.dispatchEvent(new Event('input',{bubbles:true})); true""")
            await asyncio.sleep(.7)
            adb("shell","am","force-stop",PACKAGE)
        finally:
            await live.close()
            adb("forward","--remove","tcp:"+port)
        await check_cold_layout(session, adb, site["origin"], False)
        await check_cold_layout(session, adb, site["origin"], True)
        adb("shell", "am", "force-stop", PACKAGE)
        # Version 2 has the same record rows and indices, without the per-thread layout column.
        count_chunks = "SELECT count(*) FROM chunks"
        old_chunks = int(offline_db(adb, count_chunks))
        assert old_chunks > 0
        offline_db(adb, "ALTER TABLE books DROP COLUMN layout; PRAGMA user_version=2")
        adb("shell","cmd","connectivity","airplane-mode","enable")
        try:
            await asyncio.sleep(1)
            started=time.monotonic()
            launch(adb)
            async with panel(session,adb,"https://conversation.focus.invalid/conversation.html") as chat:
                await wait_for(chat,"[...document.querySelectorAll('main strong')].some(n=>n.textContent==='Arrived while away')")
                print(f"offline cold start to ordinary chat: {time.monotonic()-started:.2f}s",flush=True)
                assert offline_db(adb, "PRAGMA user_version") == "3"
                assert int(offline_db(adb, count_chunks)) == old_chunks
                print("Upgraded a version 2 database offline and retained every saved chunk", flush=True)
                await open_saved_reader(chat)
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
            async with panel(session,adb,"https://conversation.focus.invalid/conversation.html") as chat:
                await wait_for(chat,"/site-1 (question|answer) 0(\\D|$)/.test(document.querySelector('main')?.innerText)")
                adb("shell","cmd","connectivity","airplane-mode","disable")
            await wait_for_online_handoff(session, adb, site["origin"])
            adb("shell","am","force-stop",PACKAGE)
            adb("shell","cmd","connectivity","airplane-mode","enable")
            launch(adb)
            async with panel(session,adb,"https://conversation.focus.invalid/conversation.html") as chat:
                await wait_for(chat,"!!document.querySelector('main [data-turn-id]')")
                await open_saved_reader(chat)
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
                task = re.search(r"topResumedActivity=.*?" + re.escape(PACKAGE) + r"/\S+ t(\d+)",
                                 adb("shell", "dumpsys", "activity", "activities"))
                assert task, "Expected the fixture conversation in the foreground"
                await evaluate(live, """(() => { const input=document.querySelector('textarea:not(:disabled)');
                    input.value='parked draft'; input.dispatchEvent(new Event('input',{bubbles:true})); })()""")
                await wait_for(live, "Object.keys(localStorage).some(k=>k.includes('.draft.') && localStorage[k]==='parked draft')")
                await switch(live, adb, site["origin"])
                async with tab(session, adb, site["origin"]) as other:
                    await wait_for(other, "document.querySelector('.focus-shell')?.dataset.firstScreen==='ready'")
                    await assert_online_only(session, port)
                    await switch(other, adb, sites[0]["origin"])
                async with tab(session, adb, sites[0]["origin"]) as returned:
                    await assert_online_only(session, port)
                    await wait_for(returned, "document.visibilityState==='visible' && document.querySelector('textarea:not(:disabled)')?.value==='parked draft'")
                    if await evaluate(returned, "performance.timeOrigin") != document:
                        # Android can remove an excluded task from recents while its sibling opens.
                        events = adb("logcat", "-b", "events", "-d", "-s", "wm_destroy_activity:I")
                        assert any(f",{task[1]},{PACKAGE}/" in line and "recent-task-trimmed" in line
                                   for line in events.splitlines()), "Parked page was lost without OS task removal"
                        await wait_for(returned, "location.search.includes('thread=thread-1') && document.querySelector('.chat-scroll')?.innerText.includes('right reply')")
                        print("Restored the thread, messages and draft after Android removed its parked task", flush=True)
                    else:
                        print("Drawer resumed the same online document and draft", flush=True)
                    await open_reader(returned)
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
