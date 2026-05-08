from __future__ import annotations

import os
import pathlib
import shlex
import shutil

DEFAULT_CODEX_COMMAND = "codex"


def _resolve_existing_path(raw: str | None) -> pathlib.Path | None:
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    if not path.exists():
        return None
    return path.resolve()


def _current_command_path(command: str) -> pathlib.Path | None:
    resolved = shutil.which(command)
    if not resolved:
        return None
    return pathlib.Path(resolved).expanduser()


def _is_path_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _home_dir() -> pathlib.Path:
    return pathlib.Path.home()


def _candidate_fnm_roots() -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []
    for raw in (
        os.environ.get("FNM_DIR"),
        str(_home_dir() / ".local" / "share" / "fnm"),
        str(_home_dir() / ".fnm"),
    ):
        path = _resolve_existing_path(raw)
        if path is not None and path not in roots:
            roots.append(path)
    fnm_executable = _resolve_existing_path(shutil.which("fnm"))
    if fnm_executable is not None and fnm_executable.parent not in roots:
        roots.insert(0, fnm_executable.parent)
    return roots


def _candidate_nvm_roots() -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []
    for raw in (
        os.environ.get("NVM_DIR"),
        str(_home_dir() / ".nvm"),
    ):
        path = _resolve_existing_path(raw)
        if path is not None and path not in roots:
            roots.append(path)
    return roots


def _detect_fnm_stable_codex_command() -> str | None:
    current_codex = _current_command_path("codex")
    current_node = _current_command_path("node")
    resolved_node = _resolve_existing_path(str(current_node)) if current_node is not None else None
    resolved_codex = _resolve_existing_path(str(current_codex)) if current_codex is not None else None
    for fnm_root in _candidate_fnm_roots():
        default_installation_root = fnm_root / "aliases" / "default"
        if not default_installation_root.exists():
            continue

        default_node_candidates = [
            default_installation_root / "bin" / "node",
            default_installation_root / "bin" / "node.exe",
        ]
        default_codex_candidates = [
            default_installation_root / "bin" / "codex",
            default_installation_root / "bin" / "codex.cmd",
            default_installation_root / "bin" / "codex.exe",
        ]
        default_codex_js = default_installation_root / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"

        stable_node = next((candidate for candidate in default_node_candidates if candidate.exists()), resolved_node)
        stable_codex = next(
            (candidate for candidate in default_codex_candidates if candidate.exists()),
            default_codex_js if default_codex_js.exists() else resolved_codex,
        )
        if stable_node is None or stable_codex is None:
            continue
        if not stable_node.exists() or not stable_codex.exists():
            continue
        return shlex.join([str(stable_node), str(stable_codex)])
    return None


def _resolve_nvm_alias(root: pathlib.Path, name: str, *, seen: set[str] | None = None) -> str | None:
    normalized = str(name or "").strip()
    if not normalized:
        return None
    if seen is None:
        seen = set()
    if normalized in seen:
        return None
    seen.add(normalized)
    version_dir = root / "versions" / "node" / normalized
    if version_dir.exists():
        return normalized
    alias_path = root / "alias" / normalized
    if alias_path.exists():
        target = alias_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return _resolve_nvm_alias(root, target, seen=seen)
    return None


def _detect_nvm_stable_codex_command() -> str | None:
    current_codex = _current_command_path("codex")
    resolved_codex = _resolve_existing_path(str(current_codex)) if current_codex is not None else None
    for nvm_root in _candidate_nvm_roots():
        version_candidates: list[pathlib.Path] = []
        resolved_alias = _resolve_nvm_alias(nvm_root, "default")
        if resolved_alias:
            version_candidates.append(nvm_root / "versions" / "node" / resolved_alias)
        versions_root = nvm_root / "versions" / "node"
        if versions_root.exists():
            for child in sorted(versions_root.iterdir()):
                if child.is_dir() and child not in version_candidates:
                    version_candidates.append(child)
        if (
            resolved_codex is not None
            and _is_path_within(resolved_codex, nvm_root)
            and resolved_codex.name.startswith("codex")
        ):
            return str(resolved_codex)
        matching_candidates = [
            candidate / "bin" / "codex"
            for candidate in version_candidates
            if (candidate / "bin" / "codex").exists()
        ]
        if matching_candidates:
            return str(matching_candidates[0])
    return None


def detect_stable_codex_command() -> str | None:
    return _detect_fnm_stable_codex_command() or _detect_nvm_stable_codex_command()


def resolve_managed_codex_command(configured_command: str) -> str:
    normalized = str(configured_command or "").strip() or DEFAULT_CODEX_COMMAND
    if normalized != DEFAULT_CODEX_COMMAND:
        return normalized
    if shutil.which(DEFAULT_CODEX_COMMAND):
        return DEFAULT_CODEX_COMMAND
    return detect_stable_codex_command() or DEFAULT_CODEX_COMMAND
