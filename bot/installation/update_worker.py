"""Worker used by the browser update transient systemd user unit."""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import sys

from bot.installation import installer
from bot.installation.install_bundle import validate_install_bundle
from bot.installation.node_toolchain import resolve_node_toolchain
from bot.installation.offline import seal_wheelhouse, verify_wheelhouse
from bot.installation.update import UpdateJournal
from bot.installation.update_process import UpdateError, run
from bot.manage_cli.install_surface import create_managed_install_transaction
from bot.platform_paths import default_data_root


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation-file", type=pathlib.Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--mode", choices=("check", "apply"), required=True)
    return parser.parse_args(argv)


def _disk(paths: tuple[pathlib.Path, ...], staged: int = 0) -> dict[str, int]:
    values = []
    inodes = []
    for path in paths:
        usage = shutil.disk_usage(path)
        info = os.statvfs(path)
        values.append(int(usage.free))
        inodes.append(int(getattr(info, "f_favail", info.f_ffree)))
    free = min(values)
    available_inodes = min(inodes)
    required = max(1024**3, staged * 4)
    if free < required or available_inodes < 2000:
        raise UpdateError(f"insufficient update filesystem capacity (free={free}, inodes={available_inodes})")
    return {"free_bytes": free, "required_bytes": required, "free_inodes": available_inodes}


def _revision(checkout: pathlib.Path, requested: str) -> str:
    ref = f"{requested}^{{commit}}" if requested else "refs/remotes/origin/main"
    resolved = run(["git", "-C", str(checkout), "rev-parse", ref], cwd=checkout, label="git revision").splitlines()[-1].strip().lower()
    if len(resolved) != 40 or any(c not in "0123456789abcdef" for c in resolved):
        raise UpdateError("git did not return a full commit SHA")
    run(["git", "-C", str(checkout), "checkout", "--detach", resolved], cwd=checkout, label="git checkout")
    return resolved


def _venv_python(venv_dir: pathlib.Path) -> pathlib.Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _has_build_toolchain(python: pathlib.Path, *, cwd: pathlib.Path) -> bool:
    try:
        run(
            [str(python), "-I", "-c", "import setuptools, wheel"],
            cwd=cwd,
            label="build toolchain check",
            timeout=30,
        )
    except UpdateError:
        return False
    return True


def _build_python(checkout: pathlib.Path, root: pathlib.Path) -> pathlib.Path:
    """Use the managed interpreter when it has build tools, otherwise stage them."""

    current = pathlib.Path(sys.executable)
    if _has_build_toolchain(current, cwd=checkout):
        return current

    build_venv = root / "build-venv"
    base = pathlib.Path(getattr(sys, "_base_executable", sys.executable))
    run([str(base), "-m", "venv", str(build_venv)], cwd=root, label="build Python")
    python = _venv_python(build_venv)
    requirements = checkout / "requirements-build.in"
    if not requirements.is_file() or requirements.is_symlink():
        raise UpdateError("source checkout is missing requirements-build.in")
    run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "-r",
            str(requirements),
        ],
        cwd=checkout,
        label="build dependencies",
    )
    if not _has_build_toolchain(python, cwd=checkout):
        raise UpdateError("temporary build environment lacks setuptools and wheel")
    return python


def _check(journal: UpdateJournal, operation: dict) -> None:
    root = journal.directory(operation["operation_id"])
    root.mkdir(parents=True, exist_ok=False)
    checkout = root / "source"
    output = root / "install"
    source = operation["operation_source"]
    try:
        disk = _disk((journal.root, default_data_root()))
        toolchain = resolve_node_toolchain()
        npm_environment = toolchain.environment()
        run(["git", "clone", "--filter=blob:none", "--no-checkout", "--single-branch", "--branch", "main", source["url"], str(checkout)], cwd=root, label="git clone", env=None)
        revision = _revision(checkout, operation["requested_commit"])
        run([str(toolchain.npm), "--prefix", str(checkout / "web"), "ci"], cwd=checkout, label="npm ci", env=npm_environment)
        run([str(toolchain.npm), "--prefix", str(checkout / "web"), "run", "build"], cwd=checkout, label="Web build", env=npm_environment)
        output.mkdir()
        build_python = _build_python(checkout, root)
        run([str(build_python), "-I", str(checkout / "scripts" / "build_install_bundle.py"), "--output-dir", str(output),
             "--source-revision", revision, "--build-id", f"web-{revision[:12]}"], cwd=checkout, label="Focus bundle build")
        bundles = tuple(output.glob("focus-install-*.zip"))
        if len(bundles) != 1:
            raise UpdateError("source build must produce exactly one Focus bundle")
        bundle = bundles[0]
        validated = validate_install_bundle(bundle, extraction_dir=root / "validated")
        preflight_venv = root / "preflight-venv"
        run([getattr(sys, "_base_executable", sys.executable), "-m", "venv", str(preflight_venv)], cwd=root, label="preflight Python")
        python = _venv_python(preflight_venv)
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        run([str(python), "-I", "-m", "pip", "download", "--disable-pip-version-check", "--dest", str(wheelhouse),
             "--constraint", str(validated.dependency_lock_path), str(validated.wheel_path)], cwd=root, label="dependency download")
        seal_wheelhouse(wheelhouse)
        offline_req, expanded, wheel_inodes = verify_wheelhouse(wheelhouse)
        _disk((journal.root, default_data_root()), staged=bundle.stat().st_size + expanded)
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        journal.settle(operation["operation_id"], "checking", state="ready", resolved_commit=revision,
                       message="Source, Web build, dependency, disk and offline-install preflight passed",
                       preflight={"git": "passed", "node": "passed", "npm": "passed", "web_build": "passed",
                                  "pip": "passed", "disk": "passed", "node_toolchain": toolchain.preflight(),
                                  "free_bytes": disk["free_bytes"], "free_inodes": disk["free_inodes"], "wheelhouse_files": wheel_inodes},
                       bundle_sha256=digest, staging_dir=str(root), bundle_path=str(bundle),
                       wheelhouse_path=str(wheelhouse), offline_requirements=str(offline_req), installation_started=False)
    except BaseException as exc:
        journal.settle(operation["operation_id"], "checking", state="failed",
                       message="Update check failed; the old Focus installation is unchanged", error=str(exc)[:16384])
        shutil.rmtree(root, ignore_errors=True)


def _apply(journal: UpdateJournal, operation: dict) -> None:
    transaction = None
    started = False
    try:
        bundle = pathlib.Path(operation["bundle_path"])
        wheelhouse = pathlib.Path(operation["wheelhouse_path"])
        requirements = pathlib.Path(operation["offline_requirements"])
        if not bundle.is_file() or bundle.is_symlink() or not wheelhouse.is_dir() or wheelhouse.is_symlink() or not requirements.is_file():
            raise UpdateError("prepared offline update files are missing")
        validated = validate_install_bundle(bundle, extraction_dir=bundle.parent / "worker-validated")
        verify_wheelhouse(wheelhouse)
        transaction = create_managed_install_transaction(operation="web-update")
        transaction.prepare()
        started = transaction.stop_phase_started
        journal.settle(operation["operation_id"], "applying", state="applying",
                       message="All instances are idle; installing the exact prepared bundle offline",
                       installation_started=started)
        installer.install_bundle_body(validated, offline_requirements=requirements)
        transaction.complete()
        journal.settle(operation["operation_id"], "applying", state="succeeded",
                       message="Focus updated and services restarted; reload the browser document",
                       installation_started=started)
    except BaseException as exc:
        if transaction is not None:
            started = started or transaction.stop_phase_started
        if transaction is not None:
            try:
                transaction.abort()
            except BaseException as cleanup:
                exc.add_note(str(cleanup))
        journal.settle(operation["operation_id"], "applying", state="failed",
                       message="Update failed; inspect service state before retrying", error=str(exc)[:16384],
                       installation_started=started)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    journal = UpdateJournal(args.operation_file.parent)
    with journal.locked():
        operation = journal.read()
        if operation["operation_id"] != args.operation_id:
            return 2
        if args.mode == "check" and operation["state"] == "checking":
            # Lock is released before the long-running operation. The journal
            # state remains the single-flight admission proof.
            pass
        elif args.mode == "apply" and operation["state"] == "applying":
            pass
        else:
            return 2
    if args.mode == "check":
        _check(journal, operation)
    else:
        _apply(journal, operation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
