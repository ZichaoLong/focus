"""Prepare and revalidate exact wheel bytes for a network-free install body."""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import zipfile

from bot.atomic_file import atomic_write_text
from bot.installation.install_bundle import sha256_file
from bot.installation.update_process import UpdateError


def seal_wheelhouse(root: pathlib.Path) -> None:
    files = sorted(root.glob("*.whl"))
    if not files or set(files) != set(root.iterdir()):
        raise UpdateError("Dependency preparation must produce only wheels")
    records = [{"name": p.name, "size": p.stat().st_size, "sha256": sha256_file(p)} for p in files]
    atomic_write_text(root.parent / "wheels.json", json.dumps(records), mode=0o600)


def verify_wheelhouse(root: pathlib.Path) -> tuple[pathlib.Path, int, int]:
    try:
        raw = (root.parent / "wheels.json").read_bytes()
        if len(raw) > 65536:
            raise ValueError("manifest too large")
        records = json.loads(raw)
        if not isinstance(records, list) or not 1 <= len(records) <= 256:
            raise ValueError("invalid wheel count")
        names: set[str] = set()
        requirements: list[str] = []
        expanded = inodes = 0
        for record in records:
            if not isinstance(record, dict) or set(record) != {"name", "size", "sha256"}:
                raise ValueError("invalid record")
            name, size, digest = record["name"], record["size"], record["sha256"]
            if (not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", name) is None
                    or name in names or type(size) is not int or not 0 < size <= 512 * 1024**2
                    or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                raise ValueError("invalid wheel identity")
            names.add(name)
            path = root / name
            if path.is_symlink() or path.stat().st_size != size or sha256_file(path) != digest:
                raise ValueError("wheel changed")
            with zipfile.ZipFile(path) as archive:
                expanded += sum(info.file_size for info in archive.infolist())
                inodes += len(archive.infolist())
            if expanded > 2 * 1024**3:
                raise ValueError("expanded wheels too large")
            requirements.append(f"{path.resolve().as_uri()} --hash=sha256:{digest}\n")
        if names != {p.name for p in root.iterdir()} or root.is_symlink():
            raise ValueError("wheelhouse changed")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise UpdateError("Prepared wheelhouse failed integrity verification; check again") from exc
    target = root.parent / "offline-requirements.txt"
    atomic_write_text(target, "".join(requirements), mode=0o600)
    return target, expanded, inodes


def offline_command(python: pathlib.Path, requirements: pathlib.Path) -> list[str]:
    # No dependency resolution, indexes, source build or cache can introduce
    # bytes that were not tested. pip check proves the closed dependency set.
    return [str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check",
            "--no-index", "--no-deps", "--no-cache-dir", "--require-hashes",
            "--only-binary=:all:", "--force-reinstall", "-r", str(requirements)]


def offline_environment() -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(("PYTHON", "PIP_"))}
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def install_offline(python: pathlib.Path, requirements: pathlib.Path) -> None:
    subprocess.run(offline_command(python, requirements), check=True,
                   env=offline_environment(), timeout=1200)
