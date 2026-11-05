"""Prepare complete CPython installations outside replaceable Focus environments.

See docs/contracts/install-artifact-delivery.zh-CN.md. uv owns platform selection,
download verification and extraction; Focus pins its tool/runtime versions and root.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import venv
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass


_POLICY_FILE = "python-runtime.json"
_POLICY_WHEEL_PATH = f"bot/installation/{_POLICY_FILE}"
_PROBE = (
    "import ctypes,ensurepip,json,os,pathlib,sqlite3,ssl,sys,sysconfig,venv,zlib; "
    "print(json.dumps(dict(version='.'.join(map(str,sys.version_info[:3])),"
    "implementation=sys.implementation.name,base_prefix=str(pathlib.Path(sys.base_prefix).resolve()),"
    "stdlib=str(pathlib.Path(sysconfig.get_path('stdlib')).resolve()),"
    "executable=str(pathlib.Path(sys.executable).resolve()))))"
)


class PythonRuntimeError(RuntimeError):
    """A runtime could not be prepared or verified before installation."""


@dataclass(frozen=True, slots=True)
class PythonRuntimePolicy:
    python_version: str
    uv_version: str

    def directory(self, data_root: pathlib.Path) -> pathlib.Path:
        return data_root / ".python" / f"cpython-{self.python_version}-uv-{self.uv_version}"


def runtime_policy(wheel: pathlib.Path | None = None) -> PythonRuntimePolicy:
    """The target wheel carries its own runtime requirement, including future upgrades."""
    try:
        if wheel is None:
            raw = pathlib.Path(__file__).with_name(_POLICY_FILE).read_bytes()
        else:
            with zipfile.ZipFile(wheel) as archive:
                if archive.getinfo(_POLICY_WHEEL_PATH).file_size > 1024:
                    raise ValueError("oversized policy")
                raw = archive.read(_POLICY_WHEEL_PATH)
        value = json.loads(raw)
        if (len(raw) > 1024 or not isinstance(value, dict)
                or set(value) != {"schema_version", "python_version", "uv_version"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or any(not isinstance(value[k], str) or re.fullmatch(r"\d+\.\d+\.\d+", value[k]) is None
                       for k in ("python_version", "uv_version"))
                or tuple(map(int, value["python_version"].split("."))) < (3, 11, 0)
                or not value["python_version"].startswith("3.")):
            raise ValueError("invalid policy")
        return PythonRuntimePolicy(value["python_version"], value["uv_version"])
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise PythonRuntimeError("Target Focus bundle has no valid dedicated Python policy") from exc


def _environment() -> dict[str, str]:
    # Preserve the operator's proxies, indexes and certificates. uv settings must
    # not redirect a managed runtime or select a different build/interpreter.
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "UV_"))}


def _run(command: list[str], *, label: str, timeout: float = 1200) -> str:
    try:
        result = subprocess.run(command, env=_environment(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                check=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        # Tool output may include credential-bearing package/proxy URLs.
        raise PythonRuntimeError(f"{label} failed; check the host's network, certificates and toolchain") from exc
    return result.stdout.strip()


def verify_python(python: pathlib.Path, policy: PythonRuntimePolicy, data_root: pathlib.Path) -> dict[str, str]:
    """Prove that both base interpreter and standard library belong to Focus."""
    root = policy.directory(data_root).resolve()
    try:
        observed = json.loads(_run([str(python), "-I", "-B", "-c", _PROBE], label="Dedicated Python probe", timeout=30))
        if (observed["version"] != policy.python_version or observed["implementation"] != "cpython"
                or not pathlib.Path(observed["base_prefix"]).is_relative_to(root)
                or not pathlib.Path(observed["stdlib"]).is_relative_to(root)):
            raise ValueError("runtime is not owned by Focus")
    except (ValueError, KeyError, TypeError) as exc:
        raise PythonRuntimeError("Python interpreter or standard library is outside the pinned Focus runtime") from exc
    return observed


def venv_python(directory: pathlib.Path) -> pathlib.Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _find_python(root: pathlib.Path, policy: PythonRuntimePolicy) -> pathlib.Path | None:
    candidates = list(root.glob(f"cpython-{policy.python_version}-*"))
    if not candidates:
        return None
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise PythonRuntimeError("Dedicated Python directory is ambiguous or redirected")
    candidate = candidates[0] / ("python.exe" if os.name == "nt" else "bin/python3")
    try:
        python = candidate.resolve(strict=True)
    except OSError as exc:
        raise PythonRuntimeError("Dedicated Python installation is incomplete") from exc
    if not python.is_relative_to(root.resolve()):
        raise PythonRuntimeError("Dedicated Python executable escapes its managed directory")
    return python


@contextlib.contextmanager
def _uv(policy: PythonRuntimePolicy, data_root: pathlib.Path) -> Iterator[pathlib.Path]:
    existing = shutil.which("uv")
    if existing:
        try:
            version = _run([existing, "--version"], label="uv version", timeout=10).split()
        except PythonRuntimeError:
            version = []
        if version[:2] == ["uv", policy.uv_version]:
            yield pathlib.Path(existing).resolve()
            return
    # Bootstrap only a temporary download tool. Never install into the caller's
    # system/Conda environment, nor retain uv as a Focus runtime dependency.
    with tempfile.TemporaryDirectory(prefix="python-bootstrap-", dir=data_root) as raw:
        temporary = pathlib.Path(raw)
        bootstrap = temporary / "bootstrap"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(bootstrap)
        wheels = temporary / "wheels"
        wheels.mkdir()
        _run([str(venv_python(bootstrap)), "-I", "-m", "pip", "download", "--quiet",
              "--disable-pip-version-check", "--no-deps", "--only-binary=:all:",
              "--dest", str(wheels), f"uv=={policy.uv_version}"], label="Pinned uv download")
        files = list(wheels.glob("*.whl"))
        if len(files) != 1:
            raise PythonRuntimeError("Pinned uv download did not produce exactly one wheel")
        executable = "uv.exe" if os.name == "nt" else "uv"
        entry = f"uv-{policy.uv_version}.data/scripts/{executable}"
        try:
            with zipfile.ZipFile(files[0]) as archive:
                info = archive.getinfo(entry)
                if not 0 < info.file_size <= 128 * 1024**2:
                    raise ValueError("invalid uv executable size")
                tool = temporary / executable
                with archive.open(info) as source, tool.open("xb") as target:
                    shutil.copyfileobj(source, target)
                tool.chmod(0o700)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise PythonRuntimeError("Pinned uv wheel is invalid") from exc
        if _run([str(tool), "--version"], label="Pinned uv probe", timeout=10).split()[:2] != ["uv", policy.uv_version]:
            raise PythonRuntimeError("Downloaded uv has an unexpected version")
        yield tool


def ensure_python(policy: PythonRuntimePolicy, data_root: pathlib.Path) -> pathlib.Path:
    """Download missing runtimes before service admission; never repair a live runtime in place."""
    data_root = data_root.resolve()
    root = policy.directory(data_root)
    if (data_root / ".python").is_symlink() or root.is_symlink():
        raise PythonRuntimeError("Dedicated Python root must not be a symbolic link")
    root.mkdir(parents=True, exist_ok=True)
    python = _find_python(root, policy)
    if python is None:
        with _uv(policy, data_root) as tool:
            _run([str(tool), "--no-config", "--no-cache", "--system-certs", "python", "install",
                  "--install-dir", str(root), "--no-bin", "--no-registry",
                  f"cpython-{policy.python_version}"], label="Dedicated CPython download")
        python = _find_python(root, policy)
        if python is None:
            raise PythonRuntimeError("uv did not produce the requested CPython installation")
    verify_python(python, policy, data_root)
    return python


def existing_python(policy: PythonRuntimePolicy, data_root: pathlib.Path) -> pathlib.Path:
    """Apply must never download or silently switch a previously prepared runtime."""
    root = policy.directory(data_root.resolve())
    if (data_root / ".python").is_symlink() or root.is_symlink():
        raise PythonRuntimeError("Dedicated Python root must not be a symbolic link")
    python = _find_python(root, policy)
    if python is None:
        raise PythonRuntimeError("Prepared dedicated Python is missing; check the update again")
    verify_python(python, policy, data_root)
    return python


def create_venv(python: pathlib.Path, directory: pathlib.Path) -> None:
    _run([str(python), "-I", "-m", "venv", "--copies", str(directory)], label="Dedicated Python environment")
