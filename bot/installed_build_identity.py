"""Persist the exact bundle identity of the successful managed install."""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from bot.atomic_file import atomic_write_text


INSTALLED_BUILD_IDENTITY_FILE_NAME = "installed-build.json"
INSTALLED_BUILD_IDENTITY_SCHEMA = "focus-installed-build"
INSTALLED_BUILD_IDENTITY_SCHEMA_VERSION = 1
INSTALL_CHANNELS = frozenset({"stable", "development", "local"})

_MAX_IDENTITY_BYTES = 64 * 1024
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_REQUIRED_KEYS = {
    "build_id",
    "channel",
    "schema",
    "schema_version",
    "source_revision",
    "version",
}


class InstalledBuildIdentityError(RuntimeError):
    """The persisted installed-build identity cannot be trusted."""


class _DuplicateJsonKey(ValueError):
    pass


def _require_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise InstalledBuildIdentityError(f"{label} is not a safe identifier")
    return value


@dataclass(frozen=True, slots=True)
class InstalledBuildIdentity:
    version: str
    channel: str
    build_id: str
    source_revision: str

    def __post_init__(self) -> None:
        _require_identifier(self.version, label="installed Focus version")
        if self.channel not in INSTALL_CHANNELS:
            raise InstalledBuildIdentityError(
                f"unsupported installed Focus channel: {self.channel!r}"
            )
        _require_identifier(self.build_id, label="installed Focus build_id")
        _require_identifier(
            self.source_revision,
            label="installed Focus source_revision",
        )

    def wire_payload(self) -> dict[str, str]:
        return {
            "version": self.version,
            "channel": self.channel,
            "build_id": self.build_id,
            "source_revision": self.source_revision,
        }


def installed_build_identity_path(global_data_root: pathlib.Path | str) -> pathlib.Path:
    return pathlib.Path(global_data_root) / INSTALLED_BUILD_IDENTITY_FILE_NAME


def _decode_payload(raw: bytes) -> dict[str, Any]:
    if len(raw) > _MAX_IDENTITY_BYTES:
        raise InstalledBuildIdentityError("installed-build identity is too large")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKey(key)
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InstalledBuildIdentityError(
            "installed-build identity is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise InstalledBuildIdentityError("installed-build identity must be an object")
    return payload


def read_installed_build_identity(
    global_data_root: pathlib.Path | str,
) -> InstalledBuildIdentity | None:
    """Read one closed identity record, or ``None`` before the first new install."""

    path = installed_build_identity_path(global_data_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstalledBuildIdentityError(
            f"installed-build identity cannot be read: {path}"
        ) from exc

    payload = _decode_payload(raw)
    if set(payload) != _REQUIRED_KEYS:
        raise InstalledBuildIdentityError(
            "installed-build identity does not match the closed schema"
        )
    if (
        payload["schema"] != INSTALLED_BUILD_IDENTITY_SCHEMA
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != INSTALLED_BUILD_IDENTITY_SCHEMA_VERSION
    ):
        raise InstalledBuildIdentityError(
            "installed-build identity schema or version is unsupported"
        )
    return InstalledBuildIdentity(
        version=_require_identifier(payload["version"], label="installed Focus version"),
        channel=str(payload["channel"]),
        build_id=_require_identifier(
            payload["build_id"],
            label="installed Focus build_id",
        ),
        source_revision=_require_identifier(
            payload["source_revision"],
            label="installed Focus source_revision",
        ),
    )


def write_installed_build_identity(
    global_data_root: pathlib.Path | str,
    identity: InstalledBuildIdentity,
) -> None:
    """Atomically replace the shared identity after a successful install body."""

    if type(identity) is not InstalledBuildIdentity:
        raise TypeError("installed-build identity must be InstalledBuildIdentity")
    payload: dict[str, object] = {
        "schema": INSTALLED_BUILD_IDENTITY_SCHEMA,
        "schema_version": INSTALLED_BUILD_IDENTITY_SCHEMA_VERSION,
        **identity.wire_payload(),
    }
    atomic_write_text(
        installed_build_identity_path(global_data_root),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        mode=0o600,
    )
