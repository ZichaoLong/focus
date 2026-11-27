"""Exercise system printing and server PDF fallback on an Android userdebug emulator."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from android_page_retention import nodes, tap
from android_tabs_smoke import click_web, tab
from android_webview_smoke import emulator_adb, evaluate, wait_for


async def system_control(adb, matches):
    async with asyncio.timeout(35):
        while True:
            for node in await asyncio.to_thread(nodes, adb):
                if node.get("enabled") == "true" and matches(node):
                    return node
            await asyncio.sleep(.2)


async def save_pdf(adb):
    button_id = "com.android.printspooler:id/print_button"
    button = await system_control(adb, lambda n: n.get("resource-id") == button_id
                                  or (n.get("package") == "com.android.printspooler" and n.get("text") == "Select a printer"))
    if button.get("resource-id") != button_id:
        tap(adb, button)
        target = await system_control(adb, lambda n: n.get("resource-id") == "com.android.printspooler:id/title"
                                      and n.get("text") == "Save as PDF")
        tap(adb, target)
        button = await system_control(adb, lambda n: n.get("resource-id") == button_id)
    tap(adb, button)
    return await save_document(adb)


async def save_document(adb):
    field = await system_control(adb, lambda n: "documentsui" in n.get("package", "") and n.get("class") == "android.widget.EditText")
    filename = "focus-print-" + uuid4().hex + ".pdf"
    tap(adb, field)
    adb("shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A")
    adb("shell", "input", "text", filename)
    save = await system_control(adb, lambda n: "documentsui" in n.get("package", "") and n.get("resource-id", "").endswith(":id/button1"))
    tap(adb, save)
    async with asyncio.timeout(25):
        while not (remote := adb("shell", "find", "/storage/emulated/0", "-name", filename)):
            await asyncio.sleep(.3)
    try:
        with TemporaryDirectory() as tmp:
            local = Path(tmp) / filename
            # DocumentsUI creates the destination before the spooler finishes writing it.
            async with asyncio.timeout(25):
                while True:
                    adb("pull", remote, str(local))
                    if local.read_bytes().rstrip().endswith(b"%%EOF"):
                        break
                    await asyncio.sleep(.3)
            text = subprocess.check_output(["pdftotext", local, "-"], text=True)
            return text.strip(), text.count("\f")
    finally:
        adb("shell", "rm", remote)


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
        item = "[...document.querySelectorAll('[role=menuitem]')].find(el => /打印|Print/.test(el.textContent))"
        await wait_for(ws, "!!" + item)
        await evaluate(ws, item + ".click()")
        await click_web(ws, "button[form=focus-export-options]:enabled")
        button = "#focus-mobile-print button.system-print:enabled"
        notice = "document.querySelector('#focus-mobile-print .summary-print-offer')"
        content = "document.querySelector('#focus-mobile-print .summary-print-content').innerText"
        await wait_for(ws, "!!document.querySelector('#focus-mobile-print [data-status=ready]')")
        body = await evaluate(ws, content)
        assert body.strip() and not await evaluate(ws, "!!" + notice)
        try:
            adb("shell", "pm", "set-user-restriction", *policy, "1")
            await click_web(ws, button)
            await wait_for(ws, f"!!{notice}?.offsetHeight")
            assert await evaluate(ws, content) == body
            # The picker returns to the exact preview before the job starts.
            await ws.send_json({"id": 50, "method": "Runtime.evaluate", "params": {
                "expression": "document.querySelector('#focus-mobile-print .save-pdf').click()",
                "userGesture": True,
            }})
            direct_text, _ = await save_document(adb)
            assert "Reading position" in direct_text
            await wait_for(ws, "!!document.querySelector('#focus-mobile-print .save-pdf:enabled')")
        finally:
            adb("shell", "pm", "set-user-restriction", *policy, "0")
        # Simulate the receipt seen in environments where Android never opens the panel.
        # Only intercept the print operation. The picker, gateway and file transfer stay real.
        await evaluate(ws, """window.originalPrintPrompt = window.prompt;
          window.prompt = (op, data) => op.endsWith('/print') ? 'ok' : window.originalPrintPrompt(op, data); true""")
        try:
            await click_web(ws, button)
            await wait_for(ws, f"!!{notice}?.innerText.match(/打印面板|print dialog/)")
            assert await evaluate(ws, content) == body
        finally:
            await evaluate(ws, "window.prompt = window.originalPrintPrompt; delete window.originalPrintPrompt; true")
        await click_web(ws, button)
        text, _ = await save_pdf(adb)
        assert "Reading position" in text
        await wait_for(ws, "document.visibilityState === 'visible'")
        assert await evaluate(ws, content) == body
        print("Read back both the server download and the Android system-printed PDF.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--loopback", action="store_true", help="use the authorized adb-reversed loopback entry")
    asyncio.run(run(parser.parse_args()))
