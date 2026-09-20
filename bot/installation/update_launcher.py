"""Launch browser-update workers in a service-independent user unit."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from bot.installation.update_process import UpdateError, UpdateLaunchOutcomeUnknown


# Keep the updater independent from the Focus service cgroup without dropping
# the operator's package/network authority.  Do not forward the service's
# provider credentials or arbitrary environment into source-controlled build
# hooks.
_FORWARDED_ENVIRONMENT = (
    "PATH",
    "FOCUS_CONFIG_ROOT",
    "FOCUS_DATA_ROOT",
    "FOCUS_BIN_DIR",
    "FOCUS_NODE_BIN",
    "FOCUS_NPM_BIN",
    "HOME",
    "FNM_DIR",
    "NVM_DIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "SSH_AUTH_SOCK",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "PIP_CONFIG_FILE",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_FIND_LINKS",
    "PIP_TRUSTED_HOST",
    "PIP_CERT",
    "PIP_CLIENT_CERT",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NPM_CONFIG_USERCONFIG",
    "NPM_CONFIG_REGISTRY",
    "NPM_CONFIG_PROXY",
    "NPM_CONFIG_HTTPS_PROXY",
    "NPM_CONFIG_NO_PROXY",
    "npm_config_userconfig",
    "npm_config_registry",
    "npm_config_proxy",
    "npm_config_https_proxy",
    "npm_config_no_proxy",
    "NODE_EXTRA_CA_CERTS",
)
_SYSTEMD_USER_BUS_ENVIRONMENT = ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")


def launch_update_worker(journal, operation_id: str, mode: str) -> None:
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        raise UpdateError("systemd-run is unavailable; update was not started")
    unit = journal.read()["unit"]
    if not unit or mode not in {"check", "apply"}:
        raise UpdateError("invalid update worker launch")
    setenv_args = [
        f"--setenv={name}={os.environ[name]}"
        for name in _FORWARDED_ENVIRONMENT
        if os.environ.get(name)
    ]
    command = [
        systemd_run,
        *setenv_args,
        # A check/apply worker is a long-lived oneshot service.  Do not make
        # the launcher wait for that service to finish before returning the
        # durable admission response to the browser.
        "--no-block",
        "--user",
        "--unit",
        unit.removesuffix(".service"),
        "--collect",
        "--property=Type=oneshot",
        "--property=KillMode=process",
        "--",
        sys.executable,
        "-I",
        "-m",
        "bot.installation.update_worker",
        "--operation-file",
        str(journal.path),
        "--operation-id",
        operation_id,
        "--mode",
        mode,
    ]
    # systemd-run --user talks to the caller's user manager over the user bus.
    # Keep only the bus locator and PATH in the launcher environment; the
    # explicitly allow-listed values above are passed to the worker itself.
    environment = {
        "PATH": os.environ.get("PATH", ""),
        **{
            name: os.environ[name]
            for name in _SYSTEMD_USER_BUS_ENVIRONMENT
            if os.environ.get(name)
        },
    }
    try:
        result = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateLaunchOutcomeUnknown(
            "Updater launch timed out; inspect the systemd user unit before retrying"
        ) from exc
    if result.returncode != 0:
        raise UpdateError("systemd user updater could not be started")
