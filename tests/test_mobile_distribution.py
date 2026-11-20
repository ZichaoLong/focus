from dataclasses import asdict
import hashlib
import json
import os
import subprocess

import pytest

from bot.installation.mobile_distribution import AndroidRelease, DistributionUnavailable, MobileDistribution, mobile_cache


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), "-c", "user.name=Fixture",
                                    "-c", "user.email=fixture@example.invalid", *args]).strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "dist"
    repo.mkdir()
    git(repo, "init", "-q", "--initial-branch=main")
    (repo / "channels").mkdir()
    (repo / "android").mkdir()
    return repo


def release(data):
    return AndroidRelease("org.focus.mobile", "1.2.0", 3, "a" * 40, hashlib.sha256(data).hexdigest(), "b" * 64, len(data))


def publish(repo, data, channel="main"):
    descriptor = release(data)
    (repo / descriptor.blob_path).write_bytes(data)
    (repo / "channels" / (channel + ".json")).write_text(json.dumps(asdict(descriptor)))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "channel")
    return descriptor


def test_git_cache_pins_replaced_bytes_and_reports_offline(repository, tmp_path):
    current = publish(repository, b"first")
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    assert cache.check("stable") == {"release": None, "checked_at": 0, "stale": False}
    first = cache.check("main")
    assert first["checked_at"] > 0 and first["release"] == asdict(current) and not first["stale"]
    pin = cache.apk(current.sha256)
    os.utime(pin, (1, 1))
    second = publish(repository, b"second")
    new = cache.check("main")
    assert new["release"] == asdict(second)
    assert pin.read_bytes() == b"first"
    repository.rename(tmp_path / "offline")
    assert cache.check("main") == {**new, "stale": True}
    with pytest.raises(DistributionUnavailable):
        cache.check("stable")
    cache.apk(second.sha256).write_bytes(b"wrong!")
    with pytest.raises(ValueError, match="differs"):
        cache.check("main")


def test_invalid_published_bytes_do_not_replace_verified_channel(repository, tmp_path):
    first = publish(repository, b"verified")
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    assert cache.check("main")["release"] == asdict(first)
    corrupt = publish(repository, b"invalid")
    (repository / corrupt.blob_path).write_bytes(b"INVALID")
    git(repository, "commit", "-qam", "bad bytes")
    with pytest.raises(ValueError, match="bytes"):
        cache.check("main")
    with pytest.raises(FileNotFoundError):
        cache.apk(corrupt.sha256)
    (repository / "channels/main.json").unlink()
    git(repository, "commit", "-qam", "withdraw")
    assert cache.check("main")["release"] is None
    assert cache.apk(first.sha256).read_bytes() == b"verified"


def test_sources_and_channels_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FOCUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("FOCUS_MOBILE_DIST_URL", "https://example.net/official")
    official = mobile_cache()
    monkeypatch.setenv("FOCUS_MOBILE_DIST_URL", "ssh://git@example.org/fork")
    fork = mobile_cache()
    assert fork.directory != official.directory
    with pytest.raises(ValueError):
        fork.check("../main")
    with pytest.raises(ValueError):
        fork.apk("../secret")
    monkeypatch.setenv("FOCUS_MOBILE_DIST_URL", "file:///unexpected")
    with pytest.raises(DistributionUnavailable, match="FOCUS_MOBILE_DIST_URL"):
        mobile_cache()


@pytest.mark.parametrize("field,value", [("package", "unqualified"), ("sha256", "../bad"), ("version_code", True),
                                         ("source_revision", "working-tree"), ("size", 34000000), ("extra", None)])
def test_manifest_is_bounded_and_exact(field, value):
    raw = asdict(release(b"x"))
    raw[field] = value
    with pytest.raises(ValueError):
        AndroidRelease.parse(json.dumps(raw).encode())
