"""Resolve one stable Node/npm toolchain for a browser update check."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping

from bot.installation.update_process import UpdateError


_NODE_BIN_ENV = "FOCUS_NODE_BIN"
_NPM_BIN_ENV = "FOCUS_NPM_BIN"
_FNM_DIR_ENV = "FNM_DIR"
_NVM_DIR_ENV = "NVM_DIR"
_VERSION_TIMEOUT_SECONDS = 30


class NodeToolchainError(UpdateError):
    """The updater cannot find or execute one matching Node/npm pair."""


@dataclass(frozen=True, slots=True)
class NodeToolchain:
    """One validated toolchain selected for the whole check operation."""

    node: pathlib.Path
    npm: pathlib.Path
    bin_dir: pathlib.Path
    node_version: str
    npm_version: str
    source: str

    def environment(
        self, base: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """Return a child environment that makes npm use this Node installation."""

        environment = dict(os.environ if base is None else base)
        current_path = environment.get("PATH", "")
        environment["PATH"] = (
            str(self.bin_dir)
            if not current_path
            else os.pathsep.join((str(self.bin_dir), current_path))
        )
        return environment

    def preflight(self) -> dict[str, str]:
        """Return non-secret diagnostics suitable for the update journal."""

        return {
            "source": self.source,
            "node_path": str(self.node),
            "node_version": self.node_version,
            "npm_path": str(self.npm),
            "npm_version": self.npm_version,
        }


def _path_from_value(raw: str | None, *, name: str) -> pathlib.Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    candidate = pathlib.Path(value).expanduser()
    if not candidate.is_absolute():
        raise NodeToolchainError(f"{name} must be an absolute executable path")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise NodeToolchainError(f"{name} is not an executable file: {candidate}")
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise NodeToolchainError(f"{name} cannot be resolved: {candidate}") from exc


def _executable_in_bin(bin_dir: pathlib.Path, names: tuple[str, ...]) -> pathlib.Path | None:
    for name in names:
        candidate = bin_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _pair_from_paths(
    node: pathlib.Path | None,
    npm: pathlib.Path | None,
    *,
    source: str,
    require_same_bin: bool = False,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, str] | None:
    if node is None and npm is None:
        return None
    if node is None:
        node = _executable_in_bin(npm.parent, ("node", "node.exe")) if npm else None
    if node is None:
        return None
    if npm is None:
        npm = _executable_in_bin(node.parent, ("npm", "npm.cmd", "npm.exe"))
    if npm is None:
        return None
    if require_same_bin and node.parent != npm.parent:
        return None
    try:
        node = node.resolve(strict=True)
        npm = npm.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return node, npm, node.parent, source


def _explicit_candidate(
    environment: Mapping[str, str],
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, str] | None:
    node = _path_from_value(environment.get(_NODE_BIN_ENV), name=_NODE_BIN_ENV)
    npm = _path_from_value(environment.get(_NPM_BIN_ENV), name=_NPM_BIN_ENV)
    if node is None and npm is None:
        return None
    candidate = _pair_from_paths(node, npm, source="explicit-toolchain")
    if candidate is None:
        raise NodeToolchainError(
            "FOCUS_NODE_BIN/FOCUS_NPM_BIN do not identify a matching Node/npm pair"
        )
    return candidate


def _path_candidate(
    environment: Mapping[str, str],
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, str] | None:
    path = environment.get("PATH")
    if not path:
        return None
    node = shutil.which("node", path=path)
    npm = shutil.which("npm", path=path)
    return _pair_from_paths(
        pathlib.Path(node) if node else None,
        pathlib.Path(npm) if npm else None,
        source="PATH",
        require_same_bin=True,
    )


def _home(environment: Mapping[str, str]) -> pathlib.Path:
    return pathlib.Path(environment.get("HOME") or pathlib.Path.home()).expanduser()


def _fnm_bin_candidates(
    environment: Mapping[str, str],
) -> list[tuple[pathlib.Path, str]]:
    roots: list[pathlib.Path] = []
    for raw in (
        environment.get(_FNM_DIR_ENV),
        str(_home(environment) / ".local" / "share" / "fnm"),
        str(_home(environment) / ".fnm"),
    ):
        if not raw:
            continue
        root = pathlib.Path(raw).expanduser()
        if root not in roots:
            roots.append(root)

    candidates: list[tuple[pathlib.Path, str]] = []
    for root in roots:
        bin_dir = root / "aliases" / "default" / "bin"
        if bin_dir.is_dir():
            candidates.append((bin_dir, f"fnm-default:{root}"))
    return candidates


def _nvm_bin_candidates(
    environment: Mapping[str, str],
) -> list[tuple[pathlib.Path, str]]:
    root = pathlib.Path(
        environment.get(_NVM_DIR_ENV) or _home(environment) / ".nvm"
    ).expanduser()
    alias = root / "alias" / "default"
    if not alias.is_file():
        return []
    try:
        version = alias.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return []
    if not version or pathlib.Path(version).name != version:
        return []
    bin_dir = root / "versions" / "node" / version / "bin"
    if not bin_dir.is_dir():
        return []
    return [(bin_dir, f"nvm-default:{root}")]


def _stable_candidates(
    environment: Mapping[str, str],
) -> list[tuple[pathlib.Path, pathlib.Path, pathlib.Path, str]]:
    candidates: list[tuple[pathlib.Path, pathlib.Path, pathlib.Path, str]] = []
    for bin_dir, source in (
        *_fnm_bin_candidates(environment),
        *_nvm_bin_candidates(environment),
    ):
        candidate = _pair_from_paths(
            _executable_in_bin(bin_dir, ("node", "node.exe")),
            _executable_in_bin(bin_dir, ("npm", "npm.cmd", "npm.exe")),
            source=source,
            require_same_bin=True,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _version(command: pathlib.Path, environment: Mapping[str, str], *, label: str) -> str:
    try:
        result = subprocess.run(
            [str(command), "--version"],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=dict(environment),
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NodeToolchainError(f"{label} could not be executed") from exc
    version = result.stdout.strip().splitlines()
    if not version or not version[0] or len(version[0]) > 128:
        raise NodeToolchainError(f"{label} returned no usable version")
    return version[0]


def resolve_node_toolchain(
    environment: Mapping[str, str] | None = None,
) -> NodeToolchain:
    """Resolve and validate one Node/npm pair for a single update check.

    Explicit paths and the current PATH are preferred.  If neither contains a
    usable pair, only stable fnm/nvm aliases are considered; shell startup
    files and temporary version-manager shims are intentionally ignored.
    """

    base = dict(os.environ if environment is None else environment)
    explicit = _explicit_candidate(base)
    path_candidate = _path_candidate(base)
    candidates = [
        candidate for candidate in (explicit, path_candidate) if candidate is not None
    ]
    if explicit is None:
        candidates.extend(_stable_candidates(base))
    if not candidates:
        raise NodeToolchainError(
            "Node/npm is unavailable; configure an absolute toolchain path, "
            "add both commands to the updater PATH, or set a stable fnm/nvm default"
        )

    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for node, npm, bin_dir, source in candidates:
        key = (str(node), str(npm))
        if key in seen:
            continue
        seen.add(key)
        child_environment = dict(base)
        current_path = child_environment.get("PATH", "")
        child_environment["PATH"] = (
            str(bin_dir)
            if not current_path
            else os.pathsep.join((str(bin_dir), current_path))
        )
        try:
            node_version = _version(node, child_environment, label="node")
            npm_version = _version(npm, child_environment, label="npm")
        except NodeToolchainError as exc:
            errors.append(f"{source}: {exc}")
            if explicit is not None:
                break
            continue
        return NodeToolchain(
            node=node,
            npm=npm,
            bin_dir=bin_dir,
            node_version=node_version,
            npm_version=npm_version,
            source=source,
        )

    detail = "; ".join(errors[:3])
    suffix = f" ({detail})" if detail else ""
    raise NodeToolchainError(f"No usable Node/npm toolchain found{suffix}")
