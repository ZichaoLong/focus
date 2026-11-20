"""Check configurable page retention, navigation and guest PSS on a dedicated emulator."""
import argparse
import asyncio
import json
import re
import statistics
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import aiohttp

from android_tabs_smoke import click_web, tab
from android_webview_smoke import PACKAGE, emulator_adb, evaluate, wait_for


def nodes(adb):
    raw = adb("exec-out", "uiautomator", "dump", "/dev/tty")
    start, end = raw.find("<hierarchy"), raw.find("</hierarchy>")
    if start < 0 or end < 0:
        return []
    return list(ElementTree.fromstring(raw[start:end + len("</hierarchy>")]).iter("node"))


def tap(adb, node):
    left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
    adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))


def choose(adb, label):
    width, height = map(int, re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1])
    for attempt in range(8):
        for node in nodes(adb):
            labels = node.get("text", "").splitlines() + node.get("content-desc", "").splitlines()
            if label in labels and node.get("package") == PACKAGE:
                tap(adb, node)
                return
        top, bottom = height // 4, height * 3 // 4
        a, b = (bottom, top) if attempt < 4 else (top, bottom)
        adb("shell", "input", "swipe", str(width // 2), str(a), str(width // 2), str(b), "220")
    raise AssertionError("Fixture UI entry not found: " + label)


def manager(adb, sites):
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-W", "-a", "org.focus.mobile.PICK", "-n", PACKAGE + "/org.focus.mobile.MainActivity")
    prefs = ElementTree.fromstring(adb("shell", "run-as", PACKAGE, "cat", "shared_prefs/instances.xml"))
    origins = {entry["origin"] for entry in json.loads(prefs.findtext("*[@name='list']", "[]"))}
    for index, site in enumerate(sites):
        if site["origin"] in origins:
            continue
        choose(adb, "添加实例")
        for position, value in enumerate(("Retention" + str(index), site["origin"])):
            fields = [n for n in nodes(adb) if n.get("class") == "android.widget.EditText"]
            tap(adb, fields[position])
            adb("shell", "input", "text", value)
        adb("shell", "input", "keyevent", "111")
        choose(adb, "保存")
    stored = prefs.find("*[@name='page-limit']")
    count = stored.get("value") if stored is not None else "2"
    choose(adb, "保留实例页面数 · " + count)
    choose(adb, "5")


def memory(adb):
    host = adb("shell", "pidof", PACKAGE)
    services = adb("shell", "dumpsys", "activity", "services", PACKAGE)
    pids = [host]
    for block in re.split(r"(?m)^  \* ServiceRecord", services)[1:]:
        if PACKAGE + "/org.chromium.content.app.SandboxedProcessService" in block.splitlines()[0]:
            found = re.search(r"(?m)^    app=ProcessRecord\{[^ ]+ (\d+):", block)
            if found:
                pids.append(found.group(1))
    return sum(int(re.search(r"TOTAL PSS:\s*(\d+)", adb("shell", "dumpsys", "meminfo", pid)).group(1))
               for pid in set(pids)) / 1024


def rename_in_manager(adb, name, append):
    choose(adb, "管理 " + name)
    choose(adb, "编辑")
    field = next(n for n in nodes(adb) if n.get("class") == "android.widget.EditText")
    tap(adb, field)
    adb("shell", "input", "keyevent", "KEYCODE_MOVE_END")
    if append:
        adb("shell", "input", "text", "R")
    else:
        adb("shell", "input", "keyevent", "KEYCODE_DEL")
    choose(adb, "保存")
    choose(adb, "返回对话")


async def trace(adb, session):
    pid = adb("shell", "pidof", PACKAGE)
    port = adb("forward", "tcp:0", "localabstract:webview_devtools_remote_" + pid)
    try:
        async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
            return {p["url"].split("/?", 1)[0].rstrip("/") for p in await response.json()
                    if urlsplit(p["url"]).path == "/"}
    finally:
        adb("forward", "--remove", "tcp:" + port)


async def run(args):
    sites = json.loads((args.lab / "instances.json").read_text())[:6]
    origins = [s["origin"] for s in sites]
    assert len(origins) == 6 and all(urlsplit(o).hostname == "10.0.2.2" for o in origins)
    adb = emulator_adb(args.adb, args.serial)
    await asyncio.to_thread(manager, adb, sites)
    await asyncio.to_thread(choose, adb, origins[0])
    documents = {}
    previous = origins[0]
    async with aiohttp.ClientSession() as http:
        for index in [0, 1, 2, 3, 4, 0, 5]:
            origin = origins[index]
            if documents:
                async with tab(http, adb, previous) as ws:
                    await click_web(ws, ".instance-drawer-trigger,.instance-picker")
                    await asyncio.to_thread(choose, adb, origin)
            async with tab(http, adb, origin) as ws:
                await wait_for(ws, "!!window.__focusSetTabActive && !!document.querySelector('#composer-input:not(:disabled)')")
                if index not in documents and not await evaluate(ws, "new URL(location.href).searchParams.get('thread')==='thread-1'"):
                    await evaluate(ws, "location.assign(" + json.dumps(origin + "/?focusApp=1&thread=thread-1") + ")")
                await wait_for(ws, "document.body?.innerText.includes('Reading position') && !document.querySelector('.gload')")
                document = await evaluate(ws, "performance.timeOrigin")
                assert documents.get(index, document) == document
                documents[index] = document
            previous = origin
            expected = set(origins[:min(max(documents) + 1, 5)])
            if index == 5:
                expected = set(origins) - {origins[1]}
            async with asyncio.timeout(15):
                while await trace(adb, http) != expected:
                    await asyncio.sleep(.2)
            print("Selected", index, "retained", len(expected), flush=True)
            if index in (0, 1, 4) and len(documents) == index + 1:
                await asyncio.sleep(6)
                samples = []
                for _ in range(5):
                    samples.append(round(await asyncio.to_thread(memory, adb), 1))
                    await asyncio.sleep(1)
                print("PSS MiB", len(expected), samples, "median", statistics.median(samples), flush=True)
        for system_back in [False, True]:
            async with tab(http, adb, previous) as ws:
                await click_web(ws, ".instance-drawer-trigger,.instance-picker")
                await asyncio.to_thread(choose, adb, "管理实例")
            if system_back:
                async with asyncio.timeout(15):
                    while not any(n.get("text") == "返回对话" for n in await asyncio.to_thread(nodes, adb)):
                        await asyncio.sleep(.2)
                adb("shell", "input", "keyevent", "KEYCODE_BACK")
            else:
                await asyncio.to_thread(choose, adb, "返回对话")
            async with tab(http, adb, previous) as ws:
                await wait_for(ws, "document.visibilityState==='visible' && !!document.querySelector('#composer-input:not(:disabled)')")
                assert await evaluate(ws, "performance.timeOrigin") == documents[5]
        print("Both manager return actions retained the original document.", flush=True)
        async with tab(http, adb, previous) as ws:
            name = await evaluate(ws, "window.__focusMobile.name")
            for append in [True, False]:
                await click_web(ws, ".instance-drawer-trigger,.instance-picker")
                await asyncio.to_thread(choose, adb, "管理实例")
                await asyncio.to_thread(rename_in_manager, adb, name if append else name + "R", append)
                expected_name = json.dumps(name + "R" if append else name)
                await wait_for(ws, "document.visibilityState==='visible' && window.__focusMobile.name===" + expected_name)
                assert await evaluate(ws, "performance.timeOrigin") == documents[5]
        print("Renaming updated the selected page without reloading it.", flush=True)
        async with tab(http, adb, previous) as ws:
            await click_web(ws, ".instance-drawer-trigger,.instance-picker")
            await asyncio.to_thread(choose, adb, "管理实例")
        await asyncio.to_thread(choose, adb, "保留实例页面数 · 5")
        await asyncio.to_thread(choose, adb, "1")
        async with asyncio.timeout(15):
            while await trace(adb, http) != {previous}:
                await asyncio.sleep(.2)
        await asyncio.to_thread(choose, adb, "返回对话")
        async with tab(http, adb, previous) as ws:
            await wait_for(ws, "document.visibilityState==='visible'")
            assert await evaluate(ws, "performance.timeOrigin") == documents[5]
            await click_web(ws, ".instance-drawer-trigger,.instance-picker")
            await asyncio.to_thread(choose, adb, origins[0])
        async with tab(http, adb, origins[0]) as ws:
            await wait_for(ws, "!!document.querySelector('#composer-input:not(:disabled)')")
            assert await evaluate(ws, "performance.timeOrigin") != documents[0]
        assert await trace(adb, http) == {origins[0]}
        print("Lowering the limit retained the current page. Switching at one page cold-opened the selected entry.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    asyncio.run(run(parser.parse_args()))
