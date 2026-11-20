from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from bot.installation.mobile_distribution import AndroidRelease
from scripts import publish_android


def test_distribution_publication_idempotence_promotion_and_readback(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", remote], check=True)
    for name in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{name}_EMAIL", "fixture@example.invalid")
        monkeypatch.setenv(f"GIT_{name}_NAME", "Fixture")
    apk = tmp_path / "fixture.apk"
    apk.write_bytes(b"first signed fixture")
    args = SimpleNamespace(repository=remote.as_uri(), sdk=tmp_path, channel="main", promote_main=False,
                           apk=apk, certificate_sha256="b" * 64, package="org.focus.mobile", source_revision="a" * 40)
    # The publisher also inspects the bytes read back from the independent remote clone.
    inspected = []

    def inspect(file, tools, certificate, package):
        inspected.append(Path(file).name)
        raw = file.read_bytes()
        return AndroidRelease(package, "1.2.0", 3, "a" * 40, hashlib.sha256(raw).hexdigest(), certificate, len(raw))

    monkeypatch.setattr(publish_android, "inspect_apk", inspect)
    def git(*argv):
        return subprocess.check_output(["git", "--git-dir", str(remote), *argv]).strip()

    publish_android.publish(args)
    first_commit = git("rev-parse", "main")
    first = AndroidRelease.parse(git("show", "main:channels/main.json"))
    assert git("show", "main:" + first.blob_path) == apk.read_bytes()
    publish_android.publish(args)
    assert git("rev-parse", "main") == first_commit
    args.channel, args.promote_main = "stable", True
    publish_android.publish(args)
    assert json.loads(git("show", "main:channels/stable.json")) == asdict(first)
    args.channel, args.promote_main = "main", False
    apk.write_bytes(b"second signed fixture")
    publish_android.publish(args)
    assert git("show", "main:" + first.blob_path) == b"first signed fixture"
    second = replace(first, sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), size=apk.stat().st_size)
    assert AndroidRelease.parse(git("show", "main:channels/main.json")) == second
    args.channel, args.promote_main = "stable", True
    publish_android.publish(args)
    assert first.blob_path.encode() not in git("ls-tree", "-r", "--name-only", "main")
    assert git("show", first_commit.decode() + ":" + first.blob_path) == b"first signed fixture"
    assert inspected.count("verified.apk") == 5
    previous = git("rev-parse", "main")
    args.source_revision = "c" * 40
    with pytest.raises(ValueError, match="source revision"):
        publish_android.publish(args)
    assert git("rev-parse", "main") == previous


def test_verifier_requires_expected_certificate_before_publication(tmp_path, monkeypatch):
    apk = tmp_path / "fixture.apk"
    apk.write_bytes(b"sample")
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "Signer #1 certificate SHA-256 digest: " + "a" * 64)
    with pytest.raises(ValueError, match="designated release certificate"):
        publish_android.inspect_apk(apk, tmp_path, "b" * 64, "org.focus.mobile")
