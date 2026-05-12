"""Bash completion helpers for feishu-codex command wrappers."""

from __future__ import annotations

import pathlib
import shlex
import sys
import textwrap
from dataclasses import dataclass

from bot.instance_layout import DEFAULT_INSTANCE_NAME, list_known_instance_names
from bot.platform_paths import default_user_bash_completion_dir, is_windows

COMPLETION_COMMAND_NAMES = (
    "feishu-codex",
    "feishu-codexctl",
    "feishu-codexd",
    "fcodex",
)

_THREAD_MEMORY_MODES = ("off", "read", "read_write")
_FEISHU_CODEX_OPTIONS_WITH_VALUE = {"--instance", "--lines"}
_FEISHU_CODEXCTL_OPTIONS_WITH_VALUE = {
    "--instance",
    "--binding-id",
    "--text",
    "--text-file",
    "--synthetic-source",
    "--display-mode",
    "--actor-open-id",
    "--scope",
    "--cwd",
    "--thread-id",
    "--thread-name",
    "--mode",
    "--path",
}
_FCODEX_OPTIONS_WITH_VALUE = {
    "-C",
    "--add-dir",
    "-a",
    "--ask-for-approval",
    "-c",
    "--config",
    "--cd",
    "--disable",
    "--enable",
    "-i",
    "--image",
    "--instance",
    "--local-provider",
    "-m",
    "--model",
    "-p",
    "--profile",
    "--remote",
    "--remote-auth-token-env",
    "-s",
    "--sandbox",
}


@dataclass(frozen=True, slots=True)
class CompletionContext:
    words: tuple[str, ...]
    cword: int

    @property
    def current(self) -> str:
        if 0 <= self.cword < len(self.words):
            return self.words[self.cword]
        return ""

    @property
    def previous(self) -> str:
        if self.cword <= 0:
            return ""
        return self.words[self.cword - 1]

    @property
    def args_before_cursor(self) -> tuple[str, ...]:
        if self.cword <= 1:
            return ()
        return self.words[1 : min(self.cword, len(self.words))]


def bash_completion_supported() -> bool:
    return not is_windows()


def bash_completion_dir() -> pathlib.Path | None:
    return default_user_bash_completion_dir()


def bash_completion_file_paths() -> list[pathlib.Path]:
    directory = bash_completion_dir()
    if directory is None:
        return []
    return [directory / command_name for command_name in COMPLETION_COMMAND_NAMES]


def render_bash_completion_script(*, venv_python: pathlib.Path) -> str:
    python_command = shlex.quote(str(pathlib.Path(venv_python)))
    return textwrap.dedent(
        f"""\
        # Bash completion for feishu-codex wrappers.

        _fc_complete_dispatch() {{
          local command_name="$1"
          local output
          COMPREPLY=()
          output=$({python_command} -m bot.bash_completion complete "$command_name" "$COMP_CWORD" "${{COMP_WORDS[@]}}" 2>/dev/null) || return 0
          [[ -n "$output" ]] || return 0
          while IFS= read -r line; do
            [[ -n "$line" ]] || continue
            COMPREPLY+=("$line")
          done <<< "$output"
        }}

        _fc_complete_feishu_codex() {{
          _fc_complete_dispatch feishu-codex
        }}

        _fc_complete_feishu_codexctl() {{
          _fc_complete_dispatch feishu-codexctl
        }}

        _fc_complete_feishu_codexd() {{
          _fc_complete_dispatch feishu-codexd
        }}

        _fc_complete_fcodex() {{
          _fc_complete_dispatch fcodex
        }}

        complete -o bashdefault -o default -F _fc_complete_feishu_codex feishu-codex
        complete -o bashdefault -o default -F _fc_complete_feishu_codexctl feishu-codexctl
        complete -o bashdefault -o default -F _fc_complete_feishu_codexd feishu-codexd
        complete -o bashdefault -o default -F _fc_complete_fcodex fcodex
        """
    )


def install_bash_completion_files(*, venv_python: pathlib.Path) -> pathlib.Path | None:
    directory = bash_completion_dir()
    if directory is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    rendered = render_bash_completion_script(venv_python=venv_python)
    for path in bash_completion_file_paths():
        path.write_text(rendered, encoding="utf-8")
    return directory


def remove_bash_completion_files() -> None:
    for path in bash_completion_file_paths():
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def complete_words(command_name: str, words: list[str], cword: int) -> list[str]:
    normalized_command = str(command_name or "").strip()
    if normalized_command not in COMPLETION_COMMAND_NAMES:
        return []
    context = CompletionContext(words=tuple(words), cword=max(cword, 0))
    if normalized_command == "feishu-codex":
        return _complete_feishu_codex(context)
    if normalized_command == "feishu-codexctl":
        return _complete_feishu_codexctl(context)
    if normalized_command == "feishu-codexd":
        return _complete_feishu_codexd(context)
    return _complete_fcodex(context)


def _complete_feishu_codex(context: CompletionContext) -> list[str]:
    instance_matches = _complete_choice_option(context, "--instance", list_known_instance_names())
    if instance_matches is not None:
        return instance_matches

    current = context.current
    args_before = context.args_before_cursor
    positionals = _positionals_before_cursor(args_before, _FEISHU_CODEX_OPTIONS_WITH_VALUE)
    positional_index = len(positionals)

    if positional_index == 0:
        return _complete_candidates(
            current,
            [
                "--instance",
                "--help",
                "-h",
                "start",
                "stop",
                "restart",
                "status",
                "autostart",
                "run",
                "log",
                "config",
                "instance",
                "skill",
                "uninstall",
                "purge",
            ],
        )

    command = positionals[0]
    if command == "autostart" and positional_index == 1:
        return _complete_candidates(current, ["enable", "disable", "status"])
    if command == "config":
        if current.startswith("-"):
            return _complete_candidates(current, ["--open", "--help", "-h"])
        if positional_index == 1:
            return _complete_candidates(current, ["system", "codex", "env", "init-token"])
        return []
    if command == "instance":
        if positional_index == 1:
            return _complete_candidates(current, ["create", "list", "remove"])
        if len(positionals) >= 2 and positionals[1] == "remove" and positional_index == 2:
            named_instances = [name for name in list_known_instance_names() if name != DEFAULT_INSTANCE_NAME]
            return _complete_candidates(current, named_instances)
        return []
    if command == "skill" and positional_index == 1:
        return _complete_candidates(current, ["install", "uninstall"])
    if command == "log" and current.startswith("-"):
        return _complete_candidates(current, ["--lines", "--help", "-h"])
    return []


def _complete_feishu_codexctl(context: CompletionContext) -> list[str]:
    for option_name, choices in (
        ("--instance", list_known_instance_names()),
        ("--display-mode", ["silent", "announce"]),
        ("--scope", ["cwd", "global"]),
        ("--mode", list(_THREAD_MEMORY_MODES)),
    ):
        matches = _complete_choice_option(context, option_name, choices)
        if matches is not None:
            return matches

    current = context.current
    args_before = context.args_before_cursor
    positionals = _positionals_before_cursor(args_before, _FEISHU_CODEXCTL_OPTIONS_WITH_VALUE)
    positional_index = len(positionals)

    if positional_index == 0:
        return _complete_candidates(
            current,
            [
                "--instance",
                "--help",
                "-h",
                "instance",
                "service",
                "binding",
                "prompt",
                "thread",
                "image",
            ],
        )

    resource = positionals[0]
    if resource == "instance" and positional_index == 1:
        return _complete_candidates(current, ["list"])
    if resource == "service":
        if positional_index == 1:
            return _complete_candidates(current, ["status", "reset-backend", "attach"])
        if len(positionals) >= 2 and positionals[1] == "reset-backend" and current.startswith("-"):
            return _complete_candidates(current, ["--force", "--help", "-h"])
        return []
    if resource == "binding":
        if positional_index == 1:
            return _complete_candidates(current, ["list", "status", "clear", "attach", "detach", "clear-all"])
        return []
    if resource == "prompt":
        if positional_index == 1:
            return _complete_candidates(current, ["send"])
        if len(positionals) >= 2 and positionals[1] == "send" and current.startswith("-"):
            return _complete_candidates(
                current,
                [
                    "--binding-id",
                    "--text",
                    "--text-file",
                    "--synthetic-source",
                    "--display-mode",
                    "--actor-open-id",
                    "--help",
                    "-h",
                ],
            )
        return []
    if resource == "thread":
        if positional_index == 1:
            return _complete_candidates(current, ["list", "status", "bindings", "memory", "archive", "attach", "detach"])
        if len(positionals) < 2:
            return []
        action = positionals[1]
        if current.startswith("-"):
            if action == "list":
                return _complete_candidates(current, ["--scope", "--cwd", "--help", "-h"])
            if action == "memory":
                return _complete_candidates(
                    current,
                    [
                        "--thread-id",
                        "--thread-name",
                        "--mode",
                        "--reset-backend",
                        "--force-reset-backend",
                        "--help",
                        "-h",
                    ],
                )
            if action in {"status", "bindings", "archive", "attach", "detach"}:
                return _complete_candidates(current, ["--thread-id", "--thread-name", "--help", "-h"])
        return []
    if resource == "image":
        if positional_index == 1:
            return _complete_candidates(current, ["send"])
        if len(positionals) >= 2 and positionals[1] == "send" and current.startswith("-"):
            return _complete_candidates(current, ["--path", "--thread-id", "--thread-name", "--help", "-h"])
        return []
    return []


def _complete_feishu_codexd(context: CompletionContext) -> list[str]:
    matches = _complete_choice_option(context, "--instance", list_known_instance_names())
    if matches is not None:
        return matches
    return _complete_candidates(context.current, ["--instance", "--help", "-h"])


def _complete_fcodex(context: CompletionContext) -> list[str]:
    matches = _complete_choice_option(context, "--instance", list_known_instance_names())
    if matches is not None:
        return matches

    current = context.current
    args_before = context.args_before_cursor
    positionals = _positionals_before_cursor(args_before, _FCODEX_OPTIONS_WITH_VALUE)
    positional_index = len(positionals)
    if positional_index == 0:
        if not args_before:
            return _complete_candidates(current, ["--instance", "resume"])
        return _complete_candidates(current, ["resume"])
    return []


def _complete_choice_option(
    context: CompletionContext,
    option_name: str,
    choices: list[str],
) -> list[str] | None:
    current = context.current
    previous = context.previous
    if previous == option_name:
        return _complete_candidates(current, choices)
    inline_prefix = f"{option_name}="
    if current.startswith(inline_prefix):
        value_prefix = current[len(inline_prefix) :]
        return [f"{inline_prefix}{match}" for match in _complete_candidates(value_prefix, choices)]
    return None


def _positionals_before_cursor(args_before_cursor: tuple[str, ...], options_with_value: set[str]) -> list[str]:
    positionals: list[str] = []
    index = 0
    while index < len(args_before_cursor):
        token = args_before_cursor[index]
        if token == "--":
            positionals.extend(args_before_cursor[index + 1 :])
            break
        if token.startswith("-") and token != "-":
            option_name = token.split("=", 1)[0]
            if option_name in options_with_value and "=" not in token:
                index += 2
                continue
            index += 1
            continue
        positionals.append(token)
        index += 1
    return positionals


def _complete_candidates(prefix: str, candidates: list[str]) -> list[str]:
    normalized_prefix = str(prefix or "")
    seen: set[str] = set()
    matches: list[str] = []
    for candidate in candidates:
        normalized_candidate = str(candidate or "")
        if not normalized_candidate.startswith(normalized_prefix):
            continue
        if normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        matches.append(normalized_candidate)
    return matches


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4 or args[0] != "complete":
        print("usage: python -m bot.bash_completion complete <command> <cword> <comp_words...>", file=sys.stderr)
        return 2
    command_name = str(args[1] or "").strip()
    try:
        cword = int(args[2])
    except ValueError:
        return 0
    words = list(args[3:])
    for candidate in complete_words(command_name, words, cword):
        print(candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
