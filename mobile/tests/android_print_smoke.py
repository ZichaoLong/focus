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
    origin = json.loads((args.lab / "instances.json").read_text())[1]["origin"]
    if urlsplit(origin).hostname != "10.0.2.2":
        raise ValueError("Expected the emulator gateway's second HTTPS entry")
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
        notice = "document.querySelector('#focus-mobile-print .summary-print-toolbar [role=status]')"
        content = "document.querySelector('#focus-mobile-print .summary-print-content').innerText"
        await wait_for(ws, "!!document.querySelector('#focus-mobile-print [data-status=ready]')")
        body = await evaluate(ws, content)
        assert body.strip() and not await evaluate(ws, "!!" + notice)

        try:
            adb("shell", "pm", "set-user-restriction", *policy, "1")
            await click_web(ws, button)
            await wait_for(ws, f"!!{notice}?.offsetHeight")
            assert await evaluate(ws, content) == body
        finally:
            adb("shell", "pm", "set-user-restriction", *policy, "0")

        await click_web(ws, button)
        async with asyncio.timeout(15):
            while "com.android.printspooler/" not in resumed(adb):
                await asyncio.sleep(.2)
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        await wait_for(ws, f"document.visibilityState === 'visible' && !{notice}")
        assert await evaluate(ws, content) == body
        print("Rejected print job showed an error; retry from the same preview opened system printing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    asyncio.run(run(parser.parse_args()))
