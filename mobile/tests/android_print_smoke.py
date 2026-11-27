"""Exercise the diagnostic WebView and native PDF paths on an Android userdebug emulator."""
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
        item = "[...document.querySelectorAll('[role=menuitem]')].find(el => el.textContent.includes('PDF'))"
        await wait_for(ws, "!!" + item)
        await evaluate(ws, item + ".click()")
        await click_web(ws, "button[form=focus-export-options]:enabled")
        button = "#focus-mobile-print button.system-print:enabled"
        notice = "document.querySelector('#focus-mobile-print .summary-print-error')"
        content = "document.querySelector('#focus-mobile-print .summary-print-content').innerText"
        diagnostic = "#focus-mobile-print .summary-print-diagnostic"
        report = f"JSON.parse(document.querySelector('{diagnostic} pre').textContent)"
        await wait_for(ws, "!!document.querySelector('#focus-mobile-print [data-status=ready]')")
        body = await evaluate(ws, content)
        assert body.strip() and not await evaluate(ws, "!!" + notice)
        await click_web(ws, diagnostic + " > summary")
        assert not await evaluate(ws, f"!!document.querySelector('{diagnostic} pre')")
        test_page = diagnostic + " .print-test-page"
        assert not await evaluate(ws, f"!!document.querySelector('{test_page}')")
        await click_web(ws, diagnostic + " .diagnostic-actions button")
        assert await evaluate(ws, "window.__focusMobile.features.includes('print-job-diagnostics')")

        try:
            adb("shell", "pm", "set-user-restriction", *policy, "1")
            # The bridge's synchronous prompt returns after DocumentsUI closes.
            await ws.send_json({"id": 50, "method": "Runtime.evaluate", "params": {
                "expression": "document.querySelector('#focus-mobile-print button.save-pdf:enabled').click()",
                "userGesture": True,
            }})
            direct_text, _ = await save_document(adb)
            assert "Reading position" in direct_text
            await wait_for(ws, "!!document.querySelector('#focus-mobile-print button.save-pdf:enabled')")
            assert await evaluate(ws, f"{report}.attempts") == 0
            await click_web(ws, button)
            await wait_for(ws, f"!!{notice}?.offsetHeight")
            assert await evaluate(ws, content) == body
            assert await evaluate(ws, f"{report}.events.some(e => e.attempt === 1 && e.event === 'bridge-error')")
        finally:
            adb("shell", "pm", "set-user-restriction", *policy, "0")

        await click_web(ws, button)
        text, _ = await save_pdf(adb)
        assert "Reading position" in text and "Focus Mobile print test" not in text
        await wait_for(ws, f"document.visibilityState === 'visible' && !{notice}")
        assert await evaluate(ws, content) == body
        await wait_for(ws, f"{report}.events.some(e => e.attempt === 2 && e.event === 'host-resume')")

        await click_web(ws, test_page)
        # Keep this job in the chooser through the last scheduled sample.
        await system_control(adb, lambda n: n.get("resource-id") == "com.android.printspooler:id/destination_spinner")
        await asyncio.sleep(31)
        text, count = await save_pdf(adb)
        assert text == "Focus Mobile print test" and count == 1
        await wait_for(ws, f"{report}.events.some(e => e.attempt === 3 && e.event === 'host-resume')")
        await click_web(ws, diagnostic + " .diagnostic-actions button")
        snapshot = await evaluate(ws, report)
        assert snapshot["attempts"] == 3 and snapshot["native"]["status"] == "collected"
        assert not await evaluate(ws, f"!!document.querySelector('{test_page}')")
        rows = snapshot["native"]["events"]
        observations = snapshot["native"]["observations"]
        assert observations["status"] == "collected"
        assert any(r["attempt"] == 1 and r["event"] == "printing-restricted" for r in rows)
        for attempt, source in ((2, "webview"), (3, "native-test")):
            events = {r["event"] for r in rows if r["attempt"] == attempt and r["source"] == source}
            assert {"request", "adapter-created", "job-returned", "start", "layout", "write", "finish"} <= events, events
            signals = {r["event"] for r in observations["events"] if r["attempt"] == attempt and r["source"] == source}
            assert signals & {"window-initial-focused", "window-initial-unfocused"}, signals
            assert {"intent-start", "intent-returned", "window-unfocused", "activity-paused", "activity-resumed",
                    "job-query-start"} <= signals, signals
            assert signals & {"job-created", "job-queued", "job-started", "job-completed", "job-not-listed"}, signals
        pending_states = {"job-created", "job-queued", "job-started", "job-blocked", "job-not-listed"}
        samples = [r for r in observations["events"] if r["attempt"] == 3 and r["event"] in pending_states]
        returned = next(r["ms"] for r in rows if r["attempt"] == 3 and r["event"] == "job-returned")
        assert len(samples) == 4 and samples[-1]["ms"] - returned >= 30_000, samples
        # The start/stop protocol used by an older instance still returns its original shape.
        legacy = await evaluate(ws, """(() => {
          const op = 'focus/1/' + window.__focusMobile.ticket + '/print-diag-';
          const id = prompt(op + 'start', '');
          return JSON.parse(prompt(op + 'stop', id));
        })()""")
        assert legacy["events"] == [] and "observations" not in legacy
        assert "Reading position" not in json.dumps(snapshot) and await evaluate(ws, content) == body
        print("Read back the direct and both system-printed PDFs and checked launch, window, job and adapter evidence.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--loopback", action="store_true", help="use the authorized adb-reversed loopback entry")
    asyncio.run(run(parser.parse_args()))
