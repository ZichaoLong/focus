#!/usr/bin/env python3
"""Build the Java WebView shell with the Android SDK and pinned AndroidX WebKit."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from urllib.request import urlopen
from xml.etree import ElementTree as xml

ROOT = Path(__file__).resolve().parent
WEB = ROOT.parent.parent / "web"
MANAGER_ASSETS = ROOT.parent / "harmony/entry/src/main/resources/rawfile"
WEBKIT = "https://dl.google.com/dl/android/maven2/androidx/webkit/webkit/1.12.1/webkit-1.12.1.aar"
WEBKIT_SHA256 = "18a0a51ad129e0c8563f031d46c8a7e61169f56ae84e562a0d75686941262111"


def clean_source_revision():
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", ".", str(MANAGER_ASSETS), str(WEB)], cwd=ROOT)
    except (OSError, subprocess.CalledProcessError):
        return "working-tree"
    return revision if not changes else "working-tree"


def webkit_dependency(path):
    if path.is_file():
        data = path.read_bytes()
    else:
        with urlopen(WEBKIT, timeout=60) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != WEBKIT_SHA256:
        raise ValueError("AndroidX WebKit 1.12.1 checksum mismatch: " + str(path))
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as cache:
            cache.write(data)
        Path(cache.name).replace(path)
    return zipfile.ZipFile(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT"))
    parser.add_argument("--unsigned", action="store_true", help="produce a zipaligned APK for release signing")
    parser.add_argument("--debug-ca", type=Path, help="extra PEM CA for an isolated development test APK only")
    parser.add_argument("--webkit-aar", type=Path, help="offline copy of the official AndroidX WebKit 1.12.1 AAR")
    args = parser.parse_args()
    if not args.sdk:
        parser.error("set ANDROID_HOME or pass --sdk")
    if args.webkit_aar and not args.webkit_aar.is_file():
        parser.error("--webkit-aar must name an existing offline AAR")
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
    source_id = clean_source_revision()
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
            for activity in document.getroot().find("application"):
                if activity.tag not in ("activity", "service", "provider"):
                    continue
                key = "{http://schemas.android.com/apk/res/android}name"
                activity.set(key, "org.focus.mobile" + activity.get(key))
                authority = "{http://schemas.android.com/apk/res/android}authorities"
                if activity.get(authority):
                    activity.set(authority, activity.get(authority).replace("org.focus.mobile.", "org.focus.mobile.testca."))
                affinity = "{http://schemas.android.com/apk/res/android}taskAffinity"
                if activity.get(affinity):
                    activity.set(affinity, activity.get(affinity).replace("org.focus.mobile.", "org.focus.mobile.testca."))
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
        with webkit_dependency(args.webkit_aar or build / "webkit-1.12.1.aar") as dependency:
            webkit = Path(dependency.extract("classes.jar", work / "webkit"))
            keep = Path(dependency.extract("proguard.txt", work / "webkit"))
            license_text = dependency.read("META-INF/androidx/webkit/webkit/LICENSE.txt")
        run("javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-bootclasspath",
            os.pathsep.join(map(str, (platform, tools / "core-lambda-stubs.jar"))),
            "-classpath", webkit,
            "-d", classes, *sorted((ROOT / "src").rglob("*.java")))
        jar = work / "classes.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            for cls in classes.rglob("*.class"):
                archive.write(cls, cls.relative_to(classes))
        run("java", "-cp", tools / "lib/d8.jar", "com.android.tools.r8.R8", "--release",
            "--min-api", "28", "--lib", platform, "--pg-conf", keep,
            "--pg-conf", ROOT / "keep.pro", "--output", work, jar, webkit)
        conversation = work / "conversation"
        subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "build", "--", "--mode", "android-conversation", "--outDir", str(conversation)],
                       cwd=WEB, check=True)
        if clean_source_revision() != source_id:
            source_id = "working-tree"
        with zipfile.ZipFile(apk, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("assets/focus-source-revision.txt", source_id)
            archive.write(work / "classes.dex", "classes.dex")
            for asset in ("server-updates.html", "server-updates.js", "first-screen.js", "records.html", "records.js", "records-sql.json"):
                archive.write(MANAGER_ASSETS / asset, "assets/" + asset)
            for asset in sorted(conversation.rglob("*")):
                if asset.is_file():
                    archive.write(asset, "assets/conversation/" + asset.relative_to(conversation).as_posix())
            archive.writestr("META-INF/androidx/webkit/LICENSE.txt", license_text)
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
