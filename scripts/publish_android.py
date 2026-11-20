#!/usr/bin/env python3
"""Explicitly publish a verified Android APK and its channel in one Git commit."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.installation.mobile_distribution import AndroidRelease, CHANNELS, MAX_APK_BYTES  # noqa: E402


def git(directory, *args, check=True):
    return subprocess.run(["git", *args], cwd=directory, check=check, stdout=subprocess.PIPE, timeout=120)


def inspect_apk(apk: Path, tools: Path, expected_certificate: str, package: str) -> AndroidRelease:
    if not apk.is_file() or not 0 < apk.stat().st_size <= MAX_APK_BYTES:
        raise ValueError("Missing or oversized APK")
    suffix = ".exe" if os.name == "nt" else ""
    signer = tools / ("apksigner.bat" if os.name == "nt" else "apksigner")
    verification = subprocess.check_output([signer, "verify", "--print-certs", str(apk)], text=True)
    certificates = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})$", verification, re.M)
    if certificates != [expected_certificate]:
        raise ValueError("APK does not have the designated release certificate")
    badging = subprocess.check_output([tools / ("aapt" + suffix), "dump", "badging", apk], text=True)
    identity = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    if not identity or identity[1] != package or "application-debuggable" in badging.splitlines():
        raise ValueError("Unexpected application identity or debuggable package")
    with zipfile.ZipFile(apk) as archive:
        revision = archive.read("assets/focus-source-revision.txt").decode("ascii")
    value = AndroidRelease(package, identity[3], int(identity[2]), revision,
                           hashlib.sha256(apk.read_bytes()).hexdigest(), certificates[0], apk.stat().st_size)
    return AndroidRelease.parse(json.dumps(asdict(value)).encode())


def publish(args):
    tools = args.sdk / "build-tools" / "35.0.0"
    with tempfile.TemporaryDirectory(prefix="focus-android-publish-") as temp:
        root = Path(temp)
        dist = root / "dist"
        git(root, "init", "--quiet", "--initial-branch=main", "dist")
        git(dist, "remote", "add", "origin", args.repository)
        heads = git(dist, "ls-remote", "--heads", "origin").stdout.splitlines()
        if heads:
            if not any(row.endswith(b"\trefs/heads/main") for row in heads):
                raise ValueError("Nonempty distribution repository has no main branch")
            git(dist, "fetch", "--quiet", "--depth=1", "origin", "refs/heads/main")
            tree = git(dist, "ls-tree", "-rz", "FETCH_HEAD", "--", "android", "channels").stdout
            if any(not row.startswith(b"100644 blob ") for row in tree.split(b"\0") if row):
                raise ValueError("Distribution paths must contain regular, non-executable Git blobs")
            git(dist, "reset", "--quiet", "--hard", "FETCH_HEAD")
        descriptor = dist / "channels" / (args.channel + ".json")
        if args.promote_main:
            if args.channel != "stable":
                raise ValueError("Promotion is only valid for Android stable")
            source = AndroidRelease.parse((dist / "channels/main.json").read_bytes())
            apk = dist / source.blob_path
        else:
            apk = args.apk.resolve()
        release = inspect_apk(apk, tools, args.certificate_sha256, args.package)
        if release.source_revision != args.source_revision:
            raise ValueError("APK was not built from the requested clean source revision")
        if args.promote_main and release != source:
            raise ValueError("APK differs from main channel manifest")
        old = AndroidRelease.parse(descriptor.read_bytes()) if descriptor.exists() else None
        if old:
            if release.version_code < old.version_code or old.package != release.package:
                raise ValueError("Channel package identity or version would regress")
        blob = dist / release.blob_path
        if blob.exists():
            if hashlib.sha256(blob.read_bytes()).hexdigest() != release.sha256:
                raise ValueError("Immutable APK path contains different bytes")
        else:
            blob.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(apk, blob)
        descriptor.parent.mkdir(exist_ok=True)
        raw = (json.dumps(asdict(release), indent=2, sort_keys=True) + "\n").encode()
        descriptor.write_bytes(raw)
        # Keep shallow checkouts small. Previous commits retain permanent APK links.
        if old and old.sha256 != release.sha256:
            other = dist / "channels" / ("stable.json" if args.channel == "main" else "main.json")
            if not other.exists() or AndroidRelease.parse(other.read_bytes()).sha256 != old.sha256:
                git(dist, "rm", "--quiet", "--ignore-unmatch", "--", old.blob_path)
        git(dist, "add", "--", release.blob_path, descriptor.relative_to(dist))
        if git(dist, "diff", "--cached", "--quiet", check=False).returncode:
            git(dist, "commit", "--quiet", "-m", f"Publish Android {args.channel} {release.version} ({release.source_revision[:12]})")
            try:
                git(dist, "push", "origin", "HEAD:refs/heads/main")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                print("Push result uncertain; checking remote state", file=sys.stderr)
        # A fresh object database verifies the bytes returned by the remote even
        # when push reports a lost acknowledgement or the channel already existed.
        verify = root / "verify"
        git(root, "clone", "--quiet", "--no-checkout", "--depth=1", "--branch", "main", "--", args.repository, str(verify))
        returned = git(verify, "show", f"HEAD:channels/{args.channel}.json").stdout
        if returned != raw:
            raise ValueError("Remote channel differs; inspect concurrent publication before retrying")
        received = root / "verified.apk"
        received.write_bytes(git(verify, "show", "HEAD:" + release.blob_path).stdout)
        if inspect_apk(received, tools, args.certificate_sha256, args.package) != release:
            raise ValueError("Remote APK failed read-back verification")
        print(json.dumps({"distribution_commit": git(verify, "rev-parse", "HEAD").stdout.decode().strip(),
                          "channel": args.channel, **asdict(release)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=CHANNELS, required=True)
    parser.add_argument("--repository", required=True, help="Writable distribution repository")
    parser.add_argument("--source-revision", required=True, help="Exact 40-character source commit")
    parser.add_argument("--certificate-sha256", required=True, help="Expected public signer fingerprint")
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--package", default="org.focus.mobile")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--apk", type=Path)
    source.add_argument("--promote-main", action="store_true")
    publish(parser.parse_args())


if __name__ == "__main__":
    main()
