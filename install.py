#!/usr/bin/env python3
"""
Bootstrap installer for local feishu-codex development checkouts.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import venv

from bot.platform_paths import default_data_root

_DEFAULT_PIP_EXTRA_INDEX_URL = "https://pypi.org/simple"


def _ensure_supported_python() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更高版本。")


def _venv_python_path(venv_dir: pathlib.Path) -> pathlib.Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_cfg_path(venv_dir: pathlib.Path) -> pathlib.Path:
    return venv_dir / "pyvenv.cfg"


def _venv_is_complete(venv_dir: pathlib.Path) -> bool:
    return _venv_cfg_path(venv_dir).exists() and _venv_python_path(venv_dir).exists()


def _recreate_venv(venv_dir: pathlib.Path) -> None:
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(venv_dir)


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _run_pip_install(venv_python: pathlib.Path, *args: str) -> None:
    command = [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", *args]
    try:
        _run_checked(command)
        return
    except subprocess.CalledProcessError:
        if os.environ.get("PIP_EXTRA_INDEX_URL"):
            raise
        fallback_command = [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--extra-index-url",
            _DEFAULT_PIP_EXTRA_INDEX_URL,
            *args,
        ]
        print(
            "pip install 失败，正在使用官方 PyPI 额外源重试一次："
            f" {_DEFAULT_PIP_EXTRA_INDEX_URL}",
            file=sys.stderr,
        )
        _run_checked(fallback_command)


def _venv_has_pip(venv_python: pathlib.Path) -> bool:
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "--version"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _ensure_venv_pip(venv_python: pathlib.Path) -> None:
    if _venv_has_pip(venv_python):
        return
    try:
        _run_checked([str(venv_python), "-m", "ensurepip", "--upgrade"])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "当前 Python 无法在受管 .venv 中引导 pip；"
            "请确认已安装该 Python 对应的 venv/ensurepip 组件，"
            "或删除受管 .venv 后重试。"
        ) from exc
    if not _venv_has_pip(venv_python):
        raise SystemExit("已尝试使用 ensurepip 修复受管 .venv，但其中仍然缺少 pip。")


def main() -> None:
    _ensure_supported_python()
    install_dir = pathlib.Path(__file__).resolve().parent
    venv_dir = default_data_root() / ".venv"
    if not _venv_is_complete(venv_dir):
        _recreate_venv(venv_dir)
    venv_python = _venv_python_path(venv_dir)
    if not venv_python.exists():
        raise SystemExit(f"受管 .venv 不完整，缺少解释器：{venv_python}")
    _ensure_venv_pip(venv_python)
    _run_pip_install(venv_python, "setuptools<81", "wheel")
    _run_pip_install(venv_python, "--no-build-isolation", str(install_dir))
    _run_checked([str(venv_python), "-m", "bot.manage_cli", "bootstrap-install"])


if __name__ == "__main__":
    main()
