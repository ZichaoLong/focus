"""Installation identity and metadata-only server update discovery."""

import pathlib
import re
import secrets

from bot.installed_build_identity import InstalledBuildIdentityError, read_installed_build_identity
from bot.installation import installer
from bot.installation.install_bundle import InstallBundleError
from bot.installation.update_launcher import update_environment
from bot.installation.update_process import UpdateError, run
from bot.atomic_file import atomic_write_text


def installation_id(root: pathlib.Path) -> str:
    """Caller holds the machine update lock, including during first creation."""
    path = root / "web-update-installation-id"
    try:
        with path.open("rb") as handle:
            value = handle.read(33).decode("ascii", errors="replace")
    except FileNotFoundError:
        value = secrets.token_hex(16)
        atomic_write_text(path, value, mode=0o600)
    if re.fullmatch("[0-9a-f]{32}", value) is None:
        raise UpdateError("安装标识损坏，请在主机核实")
    return value


def installed_build(root: pathlib.Path) -> dict | None:
    try:
        identity = read_installed_build_identity(root)
    except InstalledBuildIdentityError as exc:
        raise UpdateError("无法核验当前安装的构建记录") from exc
    return identity.wire_payload() if identity else None


def resolve_candidate(target: str, source: dict | None, root: pathlib.Path) -> dict:
    if target == "stable":
        try:
            manifest, _, _ = installer.stable_bundle_metadata()
        except (SystemExit, OSError, InstallBundleError) as exc:
            raise UpdateError("无法核验 stable 发布清单") from exc
        return dict(revision=manifest.source_revision, version=manifest.version,
                    build_id=manifest.build_id, digest=manifest.bundle.sha256)
    output = run(["git", "ls-remote", "--exit-code", "--refs", "--", source["url"], "refs/heads/main"],
                 cwd=root, label="查询 main", timeout=15, env=update_environment())
    refs = [line.split("\t")[0] for line in output.splitlines() if line.endswith("\trefs/heads/main")]
    if len(refs) != 1 or re.fullmatch("[a-f0-9]{40}", refs[0]) is None:
        raise UpdateError("更新源没有返回唯一的 main commit")
    return dict(revision=refs[0], version="", build_id="", digest="")
