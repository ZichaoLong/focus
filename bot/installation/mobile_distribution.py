"""Read signed Android packages from the configured mobile distribution Git repository."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from bot.atomic_file import atomic_write_text
from bot.file_lock import FileLockBusyError, acquire_file_lock, open_lock_file, release_file_lock
from bot.installation.update import validate_source
from bot.installation.update_process import UpdateError
from bot.platform_paths import default_data_root


DEFAULT_MOBILE_DIST = "https://github.com/ZichaoLong/focus-mobile-dist.git"
MAX_APK_BYTES = 32 * 1024 * 1024
CHANNELS = ("main", "stable")


@dataclass(frozen=True, slots=True)
class AndroidRelease:
    package: str
    version: str
    version_code: int
    source_revision: str
    sha256: str
    certificate_sha256: str
    size: int

    @classmethod
    def parse(cls, raw: bytes) -> AndroidRelease:
        if len(raw) > 4096:
            raise ValueError("Mobile release manifest exceeds size limit")
        try:
            fields = json.loads(raw)
            release = cls(**fields)
            valid = (
                re.fullmatch(r"[a-zA-Z][\w]*(?:\.[a-zA-Z][\w]*)+", release.package, re.ASCII)
                and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,63}", release.version)
                and type(release.version_code) is int and 0 < release.version_code <= 2100000000
                and type(release.size) is int and 0 < release.size <= MAX_APK_BYTES
                and re.fullmatch("[a-f0-9]{40}", release.source_revision)
                and re.fullmatch("[a-f0-9]{64}", release.sha256)
                and re.fullmatch("[a-f0-9]{64}", release.certificate_sha256)
            )
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Invalid mobile release manifest") from exc
        if not valid:
            raise ValueError("Invalid mobile release manifest")
        return release

    @property
    def blob_path(self) -> str:
        return f"android/{self.sha256}.apk"


class DistributionUnavailable(RuntimeError):
    pass


def mobile_cache() -> MobileDistribution:
    try:
        source = validate_source(os.environ.get("FOCUS_MOBILE_DIST_URL") or DEFAULT_MOBILE_DIST)
    except UpdateError as exc:
        raise DistributionUnavailable("FOCUS_MOBILE_DIST_URL must be an HTTPS or SSH Git URL without a password, query or fragment") from exc
    source_id = hashlib.sha256(source.encode()).hexdigest()
    return MobileDistribution(source, default_data_root() / "mobile-updates" / source_id)


class MobileDistribution:
    def __init__(self, source: str, directory: Path):
        self.source = source
        self.directory = directory
        # Older versions fetched directly into "git", which may still have a writer.
        self.git_dir = directory / "ready.git"

    def _git(self, *args: str, check: bool = True, git_dir: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "--git-dir", str(git_dir or self.git_dir), *args], check=check, timeout=50,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    def _cached(self, channel: str, stale: bool) -> dict:
        path = self.directory / f"{channel}.json"
        if not path.exists():
            if stale:
                raise DistributionUnavailable("Mobile source is unreachable and no package is cached")
            return {"release": None, "checked_at": 0, "stale": False}
        release = AndroidRelease.parse(path.read_bytes())
        if stale:
            blob = self.apk(release.sha256)
            if blob.stat().st_size != release.size or hashlib.sha256(blob.read_bytes()).hexdigest() != release.sha256:
                raise ValueError("Cached mobile package differs from its manifest")
        return {"release": asdict(release), "checked_at": int(path.stat().st_mtime), "stale": stale}

    def apk(self, digest: str) -> Path:
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid APK digest")
        path = self.directory / (digest + ".apk")
        if not path.is_file():
            raise FileNotFoundError("APK is no longer cached")
        return path

    def check(self, channel: str) -> dict:
        if channel not in CHANNELS:
            raise ValueError("Unknown Android channel")
        self.directory.mkdir(parents=True, exist_ok=True)
        with open_lock_file(self.directory / "sync.lock") as lock:
            try:
                acquire_file_lock(lock, blocking=False)
            except FileLockBusyError as exc:
                raise DistributionUnavailable("Mobile package check in progress") from exc
            try:
                return self._sync(channel)
            finally:
                release_file_lock(lock)

    def _fetch(self) -> bool:
        # The source lock excludes other checks. A killed checker can leave a
        # workspace behind, but no later Git process will reuse its path.
        for abandoned in self.directory.glob("git-fetch-*"):
            shutil.rmtree(abandoned, ignore_errors=True)
        with tempfile.TemporaryDirectory(dir=self.directory, prefix="git-fetch-", ignore_cleanup_errors=True) as work:
            repo = Path(work) / "repo.git"
            if self.git_dir.exists():
                self.git_dir.rename(repo)
            try:
                self._git("init", "--bare", "--quiet", git_dir=repo)
                self._git("fetch", "--quiet", "--no-tags", "--no-auto-gc", "--depth=1",
                          self.source, "+refs/heads/main:refs/heads/main", git_dir=repo)
            except (OSError, subprocess.SubprocessError):
                return False
            repo.rename(self.git_dir)
        return True

    def _sync(self, channel: str) -> dict:
        if not self._fetch():
            return self._cached(channel, True)
        channel_path = f"channels/{channel}.json"
        index = self.directory / f"{channel}.json"
        previous = AndroidRelease.parse(index.read_bytes()) if index.exists() else None
        if not self._git("ls-tree", "FETCH_HEAD", "--", channel_path).stdout:
            if previous:
                self._retain_pin(previous)
            index.unlink(missing_ok=True)
            return self._cached(channel, False)
        release = AndroidRelease.parse(self._blob(channel_path, 4096))
        destination = self.directory / (release.sha256 + ".apk")
        if (not destination.exists() or destination.stat().st_size != release.size
                or hashlib.sha256(destination.read_bytes()).hexdigest() != release.sha256):
            data = self._blob(release.blob_path, release.size)
            if len(data) != release.size or hashlib.sha256(data).hexdigest() != release.sha256:
                raise ValueError("Mobile package bytes do not match the channel manifest")
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                temporary.write_bytes(data)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        if previous and previous.sha256 != release.sha256:
            self._retain_pin(previous)
        atomic_write_text(index, json.dumps(asdict(release)) + "\n", mode=0o600)
        # Give a phone time to finish a pinned download across channel updates.
        in_use = {release.sha256}
        for other in CHANNELS:
            descriptor = self.directory / f"{other}.json"
            if descriptor.is_file():
                in_use.add(AndroidRelease.parse(descriptor.read_bytes()).sha256)
        for apk in self.directory.glob("*.apk"):
            if apk.stem not in in_use and time.time() - apk.stat().st_mtime > 7 * 86400:
                apk.unlink(missing_ok=True)
        return self._cached(channel, False)

    def _retain_pin(self, previous: AndroidRelease) -> None:
        path = self.directory / (previous.sha256 + ".apk")
        if path.exists():
            path.touch()

    def _blob(self, path: str, limit: int) -> bytes:
        spec = "FETCH_HEAD:" + path
        size = self._git("cat-file", "-s", spec, check=False)
        if size.returncode or not size.stdout.strip().isdigit() or int(size.stdout) > limit:
            raise ValueError("Missing or oversized mobile distribution file")
        return self._git("cat-file", "blob", spec).stdout
