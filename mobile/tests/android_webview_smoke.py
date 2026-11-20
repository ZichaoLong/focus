"""Exercise the installed test-CA shell against an entry from emulator_gateway.py."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import uuid

import aiohttp

PACKAGE = "org.focus.mobile.testca"
ACTIVITY = PACKAGE + "/org.focus.mobile.MainActivity"


async def smoke(args):
    entries = json.loads((args.lab / "instances.json").read_text())
    origin = entries[args.entry]["origin"]
    expected_host = "127.0.0.1" if args.entry == 2 else "10.0.2.2"
    if urlsplit(origin).hostname != expected_host or not args.serial.startswith("emulator-"):
        raise ValueError("Expected the loopback fixture and a dedicated Android emulator")
    if (args.cycle_network or args.wait_session_expiry) and args.entry == 2:
        raise ValueError("Choose a trusted-proxy HTTPS entry for network and automatic reauthorization checks")

    def adb(*argv):
        return subprocess.check_output([args.adb, "-s", args.serial, *argv], text=True, stderr=subprocess.DEVNULL).strip()

    def launch():
        adb("shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
            "-f", "0x10200000", "-n", ACTIVITY)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async def attach():
            async with asyncio.timeout(45):
                while True:
                    port = None
                    try:
                        pid = str(int(adb("shell", "pidof", PACKAGE + ":web")))
                        port = adb("forward", "tcp:0", "localabstract:webview_devtools_remote_" + pid)
                        async with session.get("http://127.0.0.1:" + port + "/json/list") as response:
                            pages = await response.json()
                        page = next((p for p in pages if urlsplit(p["url"]).path == "/"
                                     and p["url"].startswith(origin + "/")), None)
                        if page:
                            return port, await session.ws_connect(page["webSocketDebuggerUrl"])
                    except (subprocess.SubprocessError, ValueError, aiohttp.ClientError, OSError):
                        pass
                    if port:
                        adb("forward", "--remove", "tcp:" + port)
                    await asyncio.sleep(.35)

        async def evaluate(ws, expression):
            await ws.send_json({"id": 100, "method": "Runtime.evaluate",
                                "params": {"expression": expression, "returnByValue": True, "userGesture": True,
                                           "awaitPromise": True}})
            while True:
                reply = await ws.receive_json(timeout=10)
                if reply.get("id") == 100:
                    result = reply["result"]
                    if "exceptionDetails" in result:
                        raise AssertionError(result["exceptionDetails"]["text"])
                    return result["result"].get("value")

        async def wait_for(ws, expression):
            async with asyncio.timeout(25):
                while not await evaluate(ws, expression):
                    await asyncio.sleep(.25)

        launch()
        port, ws = await attach()
        try:
            # A one-time local authorization fragment must finish its exchange
            # in the original document before the test navigates to the thread.
            await wait_for(ws, "!!document.querySelector('textarea:not(:disabled)') && !location.hash")
            await ws.send_json({"id": 1, "method": "Network.enable"})
            await ws.send_json({"id": 2, "method": "Page.navigate", "params": {"url": origin + "/?focusApp=1&thread=thread-1"}})
            received, upgraded, hello = set(), False, False
            async with asyncio.timeout(40):
                while not (upgraded and hello and {"/api/client/register", "/api/meta"} <= received):
                    event = await ws.receive_json()
                    params = event.get("params", {})
                    method = event.get("method")
                    if method == "Network.responseReceived" and params["response"]["status"] == 200:
                        received.add(urlsplit(params["response"]["url"]).path)
                    elif method == "Network.webSocketHandshakeResponseReceived":
                        upgraded = params["response"]["status"] == 101
                    elif method == "Network.webSocketFrameReceived":
                        data = params["response"]["payloadData"]
                        hello |= data.startswith("{") and json.loads(data).get("type") == "hello"
            await wait_for(ws, "!!document.querySelector('textarea:not(:disabled)') && location.search.includes('thread=thread-1')")
            if not any(p.startswith('/assets/') for p in received):
                raise AssertionError("No successful static asset response observed")
            draft = "emulator-draft-" + uuid.uuid4().hex
            await evaluate(ws, "(()=>{ const el=document.querySelector('textarea'); el.value=" + json.dumps(draft)
                           + "; el.dispatchEvent(new Event('input',{bubbles:true})); })()")
            await wait_for(ws, "Object.keys(localStorage).some(k=>k.includes('.draft.') && localStorage[k]===" + json.dumps(draft) + ")")
            print("Page, assets, registration, metadata and WebSocket 101/hello passed", flush=True)
        finally:
            await ws.close()
            adb("forward", "--remove", "tcp:" + port)

        adb("shell", "input", "keyevent", "KEYCODE_HOME")
        await asyncio.sleep(1)
        launch()
        adb("shell", "input", "keyevent", "KEYCODE_SLEEP")
        await asyncio.sleep(2)
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        adb("shell", "wm", "dismiss-keyguard")
        check = "location.search.includes('thread=thread-1') && document.querySelector('textarea:not(:disabled)')?.value===" + json.dumps(draft)
        for step in ("emulator Home and screen off/on", "process stop and relaunch"):
            if step.startswith("process"):
                adb("shell", "am", "force-stop", PACKAGE)
                launch()
            port, ws = await attach()
            try:
                await wait_for(ws, check)
                print(step + " preserved the thread and its unsent draft", flush=True)
            finally:
                await ws.close()
                adb("forward", "--remove", "tcp:" + port)

        if args.wait_session_expiry:
            port, ws = await attach()
            try:
                await wait_for(ws, check)
                document_start = await evaluate(ws, "performance.timeOrigin")
                await ws.send_json({"id": 4, "method": "Network.enable"})
                expired, registered, hello = False, False, False
                async with asyncio.timeout(135):
                    while not (expired and registered and hello):
                        event = await ws.receive_json()
                        method, params = event.get("method"), event.get("params", {})
                        if method == "Network.webSocketFrameReceived":
                            frame = json.loads(params["response"]["payloadData"])
                            if frame.get("type") == "session_expired":
                                expired = True
                            elif frame.get("type") == "hello" and registered:
                                hello = True
                        elif expired and method == "Network.responseReceived":
                            response = params["response"]
                            if urlsplit(response["url"]).path == "/api/client/register" and response["status"] == 200:
                                registered = True
                        elif expired and method == "Network.requestWillBeSent" and params["request"]["method"] == "POST":
                            assert urlsplit(params["request"]["url"]).path == "/api/client/register"
                await wait_for(ws, check)
                assert await evaluate(ws, "performance.timeOrigin") != document_start
                print("Observed server session_expired, new document registration and hello; thread and draft restored with no business POST.", flush=True)
            finally:
                await ws.close()
                adb("forward", "--remove", "tcp:" + port)

        if args.cycle_network:
            if adb("shell", "cmd", "connectivity", "airplane-mode") != "disabled":
                raise ValueError("Start this check with the emulator's airplane mode off")
            port, ws = await attach()
            probe = "fetch('/focus-connect.txt',{cache:'no-store',signal:AbortSignal.timeout(4000)}).then(r=>r.status,()=>0)"
            try:
                assert await evaluate(ws, probe) == 200
                document_start = await evaluate(ws, "performance.timeOrigin")
                wifi_enabled = adb("shell", "cmd", "wifi", "status").startswith("Wifi is enabled")
                try:
                    adb("shell", "cmd", "connectivity", "airplane-mode", "enable")
                    # Android can keep Wi-Fi on in airplane mode.
                    if wifi_enabled:
                        adb("shell", "svc", "wifi", "disable")
                    await wait_for(ws, "!navigator.onLine")
                    assert await evaluate(ws, probe) == 0
                    assert await evaluate(ws, check)
                    await ws.send_json({"id": 3, "method": "Network.enable"})
                finally:
                    adb("shell", "cmd", "connectivity", "airplane-mode", "disable")
                    if wifi_enabled:
                        adb("shell", "svc", "wifi", "enable")
                upgraded, hello = False, False
                async with asyncio.timeout(65):
                    while not (upgraded and hello):
                        event = await ws.receive_json()
                        method, params = event.get("method"), event.get("params", {})
                        if method == "Network.webSocketHandshakeResponseReceived":
                            upgraded = params["response"]["status"] == 101
                        elif method == "Network.webSocketFrameReceived":
                            data = params["response"]["payloadData"]
                            hello |= data.startswith("{") and json.loads(data).get("type") == "hello"
                # Cellular and Wi-Fi can become available a few seconds apart.
                await wait_for(ws, probe + ".then(status=>status===200)")
                assert await evaluate(ws, "performance.timeOrigin") == document_start
                await wait_for(ws, check)
                print("Emulator airplane mode interrupted HTTPS; the same document and draft resumed with WebSocket 101/hello.", flush=True)
            finally:
                await ws.close()
                adb("forward", "--remove", "tcp:" + port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--entry", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--cycle-network", action="store_true", help="cycle system airplane mode on the dedicated emulator")
    parser.add_argument("--wait-session-expiry", action="store_true", help="observe trusted-proxy recovery with fixture --session-lifetime 60")
    parser.add_argument("lab", type=Path)
    asyncio.run(smoke(parser.parse_args()))
