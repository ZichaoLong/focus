#!/usr/bin/env python3
"""Build the dependency-free Java WebView shell with the official Android SDK."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree as xml

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT"))
    parser.add_argument("--unsigned", action="store_true", help="produce a zipaligned APK for release signing")
    parser.add_argument("--debug-ca", type=Path, help="extra PEM CA for an isolated development test APK only")
    args = parser.parse_args()
    if not args.sdk:
        parser.error("set ANDROID_HOME or pass --sdk")
    if args.debug_ca and args.unsigned:
        parser.error("test trust anchors are supported only for debug builds")
    tools = args.sdk.resolve() / "build-tools" / "35.0.0"
    platform = args.sdk.resolve() / "platforms" / "android-35" / "android.jar"
    suffix = ".exe" if os.name == "nt" else ""
    batch = ".bat" if os.name == "nt" else ""

    def run(*argv):
        subprocess.run([str(part) for part in argv], check=True)

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build) as temp:
        work = Path(temp)
        name = "focus-unsigned" if args.unsigned else "focus-debug-test-ca" if args.debug_ca else "focus-debug"
        manifest = ROOT / "AndroidManifest.xml"
        res = work / "res"
        shutil.copytree(ROOT / "res", res)
        if args.debug_ca:
            document = xml.parse(manifest)
            document.getroot().find("application").set("{http://schemas.android.com/apk/res/android}debuggable", "true")
            # A distinct package keeps synthetic test data and trust out of the normal installation.
            document.getroot().set("package", "org.focus.mobile.testca")
            for activity in document.getroot().findall("application/activity"):
                key = "{http://schemas.android.com/apk/res/android}name"
                activity.set(key, "org.focus.mobile" + activity.get(key))
            manifest = work / "AndroidManifest.xml"
            document.write(manifest, encoding="utf-8")
            (res / "raw").mkdir()
            shutil.copyfile(args.debug_ca, res / "raw" / "test_ca.pem")
            security = res / "xml/focus_network.xml"
            config = xml.parse(security)
            xml.SubElement(config.find("base-config/trust-anchors"), "certificates", src="@raw/test_ca")
            config.write(security, encoding="utf-8")
        run(tools / ("aapt2" + suffix), "compile", "--dir", res, "-o", work / "resources.zip")
        apk = work / "base.apk"
        run(tools / ("aapt2" + suffix), "link", "-o", apk, "--manifest", manifest, "-I", platform, "-R", work / "resources.zip")
        classes = work / "classes"
        classes.mkdir()
        run("javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-bootclasspath",
            os.pathsep.join(map(str, (platform, tools / "core-lambda-stubs.jar"))),
            "-d", classes, *sorted((ROOT / "src").rglob("*.java")))
        jar = work / "classes.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            for cls in classes.rglob("*.class"):
                archive.write(cls, cls.relative_to(classes))
        run(tools / ("d8" + batch), "--min-api", "28", "--lib", platform, "--output", work, jar)
        with zipfile.ZipFile(apk, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.write(work / "classes.dex", "classes.dex")
        result = build / (name + ".apk")
        aligned = work / "aligned.apk"
        run(tools / ("zipalign" + suffix), "-p", "-f", "4", apk, aligned)
        if args.unsigned:
            shutil.copyfile(aligned, result)
        else:
            key = Path.home() / ".android" / "debug.keystore"
            if not key.exists():
                key.parent.mkdir(exist_ok=True)
                run("keytool", "-genkeypair", "-keystore", key, "-storepass", "android", "-keypass", "android",
                    "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
                    "-dname", "CN=Android Debug,O=Android,C=US", "-validity", "10000")
            run(tools / ("apksigner" + batch), "sign", "--ks", key, "--ks-key-alias", "androiddebugkey",
                "--ks-pass", "pass:android", "--out", result, aligned)
            run(tools / ("apksigner" + batch), "verify", "--verbose", result)
        print(result)


if __name__ == "__main__":
    main()
