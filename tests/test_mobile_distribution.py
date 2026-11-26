from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
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


def test_check_recovers_from_legacy_shallow_lock(repository, tmp_path):
    previous = publish(repository, b"previous")
    directory = tmp_path / "cache"
    directory.mkdir()
    git(directory, "init", "-q", "--bare", "git")
    legacy = directory / "git"
    git(legacy, "fetch", "-q", "--depth=1", repository.as_uri(), "refs/heads/main")
    (legacy / "shallow.lock").write_bytes((legacy / "shallow").read_bytes())
    (directory / "main.json").write_text(json.dumps(asdict(previous)))
    (directory / (previous.sha256 + ".apk")).write_bytes(b"previous")

    current = publish(repository, b"current")
    cache = MobileDistribution(repository.as_uri(), directory)
    result = cache.check("main")
    assert result["release"] == asdict(current) and not result["stale"]
    assert cache.apk(previous.sha256).read_bytes() == b"previous"
    assert cache.apk(current.sha256).read_bytes() == b"current"
    assert (legacy / "shallow.lock").exists()
    os.utime(legacy / "FETCH_HEAD", (1, 1))
    os.utime(legacy, (1, 1))
    assert cache.check("main")["release"] == asdict(current)
    assert not legacy.exists()


def test_reused_git_cache_drops_obsolete_apks_and_skips_repeat_compaction(repository, tmp_path, monkeypatch):
    prior = publish(repository, b"old package")
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    cache.check("main")
    old_blob = git(repository, "rev-parse", "HEAD:" + prior.blob_path).decode("ascii")
    (repository / prior.blob_path).unlink()
    current = publish(repository, b"current package")
    # Earlier checkers could already have fetched this tip and retained the old blob.
    git(cache.git_dir, "config", "core.logAllRefUpdates", "true")
    git(cache.git_dir, "config", "gc.bigPackThreshold", "1")
    git(cache.git_dir, "fetch", "-q", "--depth=1", cache.source, "+refs/heads/main:refs/heads/main")
    git(cache.git_dir, "cat-file", "-e", old_blob)
    real_run = subprocess.run
    compactions = []

    def record_git(command, **kwargs):
        if "gc" in command:
            compactions.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_git)
    for _ in range(2):
        result = cache.check("main")
        assert not result["stale"] and result["release"] == asdict(current)
    assert len(compactions) == 1
    assert subprocess.run(["git", "-C", str(cache.git_dir), "cat-file", "-e", old_blob]).returncode != 0
    assert cache.apk(prior.sha256).read_bytes() == b"old package"
    assert not list(cache.directory.glob("git-fetch-*"))


def test_interrupted_compaction_keeps_verified_release(repository, tmp_path, monkeypatch):
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    current = publish(repository, b"verified")
    real_run = subprocess.run

    def timeout_gc(command, **kwargs):
        if "gc" in command:
            raise subprocess.TimeoutExpired(command, 50)
        return real_run(command, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(subprocess, "run", timeout_gc)
        result = cache.check("main")
    assert result["release"] == asdict(current) and not result["stale"]
    assert cache.apk(current.sha256).read_bytes() == b"verified"
    assert not cache.git_dir.exists()
    assert cache.check("main")["release"] == asdict(current)
    assert cache.git_dir.is_dir()


def test_expired_apks_are_pruned_on_offline_and_unpublished_checks(repository, tmp_path):
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    stable = publish(repository, b"stable", "stable")
    cache.check("stable")
    previous = publish(repository, b"previous")
    cache.check("main")
    current = publish(repository, b"current")
    cache.check("main")
    for release in (stable, previous, current):
        os.utime(cache.apk(release.sha256), (1, 1))
    offline = repository.rename(tmp_path / "offline")
    assert cache.check("main")["stale"]
    with pytest.raises(FileNotFoundError):
        cache.apk(previous.sha256)
    assert cache.apk(stable.sha256).read_bytes() == b"stable"
    assert cache.apk(current.sha256).read_bytes() == b"current"
    offline.rename(repository)
    (repository / "channels/main.json").unlink()
    git(repository, "commit", "-qam", "withdraw main")
    assert cache.check("main")["release"] is None
    assert cache.apk(current.sha256).read_bytes() == b"current"
    os.utime(cache.apk(current.sha256), (1, 1))
    assert cache.check("main")["release"] is None
    with pytest.raises(FileNotFoundError):
        cache.apk(current.sha256)
    assert cache.apk(stable.sha256).read_bytes() == b"stable"


def test_timed_out_fetch_keeps_download_and_next_check_recovers(repository, tmp_path, monkeypatch):
    cache = MobileDistribution(repository.as_uri(), tmp_path / "cache")
    previous = publish(repository, b"previous")
    first = cache.check("main")
    current = publish(repository, b"current")
    real_run = subprocess.run

    def timeout_fetch(command, **kwargs):
        if "fetch" in command:
            repo = Path(command[command.index("--git-dir") + 1])
            (repo / "shallow.lock").write_bytes(b"interrupted")
            with pytest.raises(DistributionUnavailable, match="check in progress"):
                MobileDistribution(cache.source, cache.directory).check("stable")
            assert (repo / "shallow.lock").is_file()
            assert cache.apk(previous.sha256).read_bytes() == b"previous"
            raise subprocess.TimeoutExpired(command, 50)
        return real_run(command, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(subprocess, "run", timeout_fetch)
        assert cache.check("main") == {**first, "stale": True}
    assert cache.apk(previous.sha256).read_bytes() == b"previous"
    result = cache.check("main")
    assert result["release"] == asdict(current) and not result["stale"]


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
