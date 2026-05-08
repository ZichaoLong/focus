#!/usr/bin/env python3
"""
Bootstrap installer for local feishu-codex development checkouts.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import venv

from bot.platform_paths import default_data_root


def _ensure_supported_python() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更高版本。")


def _venv_python_path(venv_dir: pathlib.Path) -> pathlib.Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


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
            "当前 Python 无法在受管 .venv 中引导 pip；请确认已安装该 Python 对应的 venv/ensurepip 组件。"
        ) from exc
    if not _venv_has_pip(venv_python):
        raise SystemExit("已尝试使用 ensurepip 修复受管 .venv，但其中仍然缺少 pip。")


def main() -> None:
    _ensure_supported_python()
    install_dir = pathlib.Path(__file__).resolve().parent
    venv_dir = default_data_root() / ".venv"
    if not venv_dir.exists():
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    venv_python = _venv_python_path(venv_dir)
    if not venv_python.exists():
        raise SystemExit(f"受管 .venv 不完整，缺少解释器：{venv_python}")
    _ensure_venv_pip(venv_python)
    _run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    _run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "setuptools<81", "wheel"])
    _run_checked([str(venv_python), "-m", "pip", "install", str(install_dir)])
    _run_checked([str(venv_python), "-m", "bot.manage_cli", "bootstrap-install"])


if __name__ == "__main__":
    main()
