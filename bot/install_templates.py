"""Installation templates loaded from the repository's canonical examples."""

from __future__ import annotations

import importlib.resources
import pathlib

import yaml
from bot.codex_command_resolver import detect_stable_codex_command


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _packaged_template_dir() -> importlib.resources.abc.Traversable:
    return importlib.resources.files("bot.install_template_data")


def _load_template(filename: str) -> str:
    repo_path = _repo_root() / "config" / filename
    if repo_path.exists():
        return repo_path.read_text(encoding="utf-8")
    packaged_path = _packaged_template_dir() / filename
    return packaged_path.read_text(encoding="utf-8")


SYSTEM_YAML_TEMPLATE = _load_template("system.yaml.example")
CODEX_YAML_TEMPLATE = _load_template("codex.yaml.example")


def _yaml_assignment_line(key: str, value: str) -> str:
    return yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True).strip()


def render_initial_codex_yaml() -> str:
    stable_command = detect_stable_codex_command()
    if not stable_command:
        return CODEX_YAML_TEMPLATE
    rendered_assignment = _yaml_assignment_line("codex_command", stable_command)
    return CODEX_YAML_TEMPLATE.replace(
        "# codex_command: codex",
        "\n".join(
            [
                "# 已自动探测到稳定的 Codex 启动命令；如需改回其他命令，可手动编辑。",
                rendered_assignment,
                "# codex_command: codex",
            ]
        ),
        1,
    )
