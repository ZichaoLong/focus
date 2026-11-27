"""Exercise the native print button from the instance manager on a dedicated Android 15 userdebug emulator."""
import argparse
import asyncio
import json
import re

from android_page_retention import choose, nodes
from android_print_smoke import save_pdf, system_control
from android_webview_smoke import PACKAGE, emulator_adb


def open_test(adb):
    adb("shell", "am", "start", "-W", "-a", "org.focus.mobile.PICK", "-n", PACKAGE + "/org.focus.mobile.MainActivity")
    choose(adb, "系统打印诊断")
    screen = nodes(adb)
    assert not any(n.get("class") == "android.webkit.WebView" for n in screen)
    assert not any(n.get("text") == "复制诊断报告" for n in screen)


async def copy_report(adb):
    choose(adb, "复制诊断报告")
    await system_control(adb, lambda n: n.get("text") == "诊断报告已复制。")
    detail = await system_control(adb, lambda n: n.get("package") == PACKAGE and n.get("text", "").startswith("{"))
    report = json.loads(detail.get("text"))
    assert report["format"] == "focus-mobile-native-print/v1"
    trace = report["native"]
    assert trace["status"] == trace["observations"]["status"] == "collected"
    for rows in (trace["events"], trace["observations"]["events"]):
        assert rows and all(r["source"] == "native-button" and r["attempt"] == 1 for r in rows)
    return report


async def run(args):
    adb = emulator_adb(args.adb, args.serial)
    user = adb("shell", "am", "get-current-user")
    spooler = "com.android.printspooler"
    package = adb("shell", "dumpsys", "package", spooler)
    setting = re.search(rf"User {re.escape(user)}:.*?\benabled=(\d+)", package)
    if not setting or setting[1] not in {"0", "1"}:
        raise ValueError("Start with the AOSP print spooler enabled on the test emulator")
    restore = "default-state" if setting[1] == "0" else "enable"
    open_test(adb)
    choose(adb, "打印一页测试文本")
    text, pages = await save_pdf(adb)
    assert text == "Focus Mobile print test" and pages == 1
    report = await copy_report(adb)
    env = report["environment"]
    assert env["printingFeature"] is True and env["aospSpoolerPackage"] == env["aospSpoolerService"] == "enabled", env
    assert env["printDialog"] == "resolvable", env
    events = {r["event"] for r in report["native"]["events"]}
    assert {"request", "job-returned", "start", "layout", "write", "finish"} <= events, events
    observed = {r["event"] for r in report["native"]["observations"]["events"]}
    assert {"intent-returned", "activity-paused", "activity-resumed", "job-query-start"} <= observed, observed
    choose(adb, "返回实例管理")

    try:
        adb("shell", "pm", "disable-user", "--user", user, spooler)
        open_test(adb)
        choose(adb, "打印一页测试文本")
        report = await copy_report(adb)
        env = report["environment"]
        assert env["aospSpoolerPackage"] == env["aospSpoolerService"] == "disabled", env
        assert env["printDialog"] in {"disabled", "not-visible"}, env
        events = {r["event"] for r in report["native"]["events"]}
        assert "request" in events and "job-returned" not in events and "layout" not in events, events
        choose(adb, "返回实例管理")
    finally:
        adb("shell", "pm", restore, "--user", user, spooler)
    print("Saved the native one-page PDF and verified the independent report with the spooler enabled and disabled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    asyncio.run(run(parser.parse_args()))
