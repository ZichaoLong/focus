"""Verify print-job rejection and retry on a dedicated Android userdebug emulator."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from android_navigation_smoke import resumed
from android_tabs_smoke import click_web, tab
from android_webview_smoke import emulator_adb, evaluate, wait_for


async def run(args):
    entries = json.loads((args.lab / "instances.json").read_text())
    origin = entries[-1 if args.loopback else 1]["origin"]
    if urlsplit(origin).hostname != ("127.0.0.1" if args.loopback else "10.0.2.2"):
        raise ValueError("Expected an isolated emulator gateway")
    adb = emulator_adb(args.adb, args.serial)
    user = adb("shell", "am", "get-current-user")
    policy = ("--user", user, "no_printing")
    if adb("shell", "pm", "get-user-restriction", *policy) != "false":
        raise ValueError("Start with printing allowed on the test emulator")

    async with aiohttp.ClientSession() as session, tab(session, adb, origin) as ws:
        await ws.send_json({"id": 1, "method": "Page.navigate",
                            "params": {"url": origin + "/?focusApp=1&thread=thread-1"}})
        await click_web(ws, ".tb-session-actions button:enabled")
        item = "[...document.querySelectorAll('[role=menuitem]')].find(el => el.textContent.includes('PDF'))"
        await wait_for(ws, "!!" + item)
        await evaluate(ws, item + ".click()")
        await click_web(ws, "button[form=focus-export-options]:enabled")
        button = "#focus-mobile-print .summary-print-actions button:first-of-type:enabled"
        notice = "document.querySelector('#focus-mobile-print .summary-print-error')"
        content = "document.querySelector('#focus-mobile-print .summary-print-content').innerText"
        diagnostic = "#focus-mobile-print .summary-print-diagnostic"
        report = f"JSON.parse(document.querySelector('{diagnostic} pre').textContent)"
        await wait_for(ws, "!!document.querySelector('#focus-mobile-print [data-status=ready]')")
        body = await evaluate(ws, content)
        assert body.strip() and not await evaluate(ws, "!!" + notice)
        await click_web(ws, diagnostic + " > summary")
        assert not await evaluate(ws, f"!!document.querySelector('{diagnostic} pre')")
        await click_web(ws, diagnostic + " .diagnostic-actions button")

        try:
            adb("shell", "pm", "set-user-restriction", *policy, "1")
            await click_web(ws, button)
            await wait_for(ws, f"!!{notice}?.offsetHeight")
            assert await evaluate(ws, content) == body
            assert await evaluate(ws, f"{report}.events.some(e => e.attempt === 1 && e.event === 'bridge-error')")
        finally:
            adb("shell", "pm", "set-user-restriction", *policy, "0")

        await click_web(ws, button)
        async with asyncio.timeout(15):
            while "com.android.printspooler/" not in resumed(adb):
                await asyncio.sleep(.2)
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        await wait_for(ws, f"document.visibilityState === 'visible' && !{notice}")
        assert await evaluate(ws, content) == body
        await wait_for(ws, f"{report}.events.some(e => e.attempt === 2 && e.event === 'host-resume')")
        await click_web(ws, diagnostic + " .diagnostic-actions button")
        snapshot = await evaluate(ws, report)
        events = [row["event"] for row in snapshot["events"] if row["attempt"] == 2]
        assert snapshot["attempts"] == 2 and "bridge-ok" in events and "host-pause" in events and "host-resume" in events
        assert body.strip() not in json.dumps(snapshot)
        print("The opt-in report recorded rejection, retry, and foreground signals. The preview retained its content.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--loopback", action="store_true", help="use the authorized adb-reversed loopback entry")
    asyncio.run(run(parser.parse_args()))
