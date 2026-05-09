from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_UNIT_PREFIX = "feishu-codex-scheduled"


@dataclass(frozen=True, slots=True)
class ScheduledTaskSpec:
    task_id: str
    instance: str
    binding_id: str
    on_calendar: str
    description: str
    prompt_file: str
    ctl_path: str
    synthetic_source: str
    display_mode: str
    created_at: str

    @property
    def unit_name(self) -> str:
        return f"{_UNIT_PREFIX}-{self.task_id}"


def _xdg_data_home() -> pathlib.Path:
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    return pathlib.Path.home() / ".local" / "share"


def _xdg_config_home() -> pathlib.Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    return pathlib.Path.home() / ".config"


def scheduled_task_root() -> pathlib.Path:
    return _xdg_data_home() / "feishu-codex" / "scheduled-tasks"


def systemd_user_dir() -> pathlib.Path:
    return _xdg_config_home() / "systemd" / "user"


def task_dir(task_id: str) -> pathlib.Path:
    return scheduled_task_root() / task_id


def metadata_path(task_id: str) -> pathlib.Path:
    return task_dir(task_id) / "task.json"


def prompt_path(task_id: str) -> pathlib.Path:
    return task_dir(task_id) / "prompt.txt"


def service_unit_path(task_id: str) -> pathlib.Path:
    return systemd_user_dir() / f"{_UNIT_PREFIX}-{task_id}.service"


def timer_unit_path(task_id: str) -> pathlib.Path:
    return systemd_user_dir() / f"{_UNIT_PREFIX}-{task_id}.timer"


def normalize_task_id(task_id: str) -> str:
    normalized = str(task_id or "").strip().lower()
    if not _TASK_ID_RE.fullmatch(normalized):
        raise ValueError("task_id 只允许小写 ASCII、数字、点、下划线、短横线，且长度 1-64。")
    return normalized


def detect_ctl_path(explicit_path: str = "") -> str:
    normalized = str(explicit_path or "").strip()
    if normalized:
        return normalized
    detected = shutil.which("feishu-codexctl")
    if not detected:
        raise ValueError("未找到 `feishu-codexctl`；请先确认它在 PATH 中。")
    return detected


def _run_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["systemctl", "--user", *args]
    return subprocess.run(command, check=check, text=True, capture_output=True)


def _write_text(path: pathlib.Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _shell_execstart(spec: ScheduledTaskSpec) -> str:
    command = [
        spec.ctl_path,
        "--instance",
        spec.instance,
        "prompt",
        "send",
        "--binding-id",
        spec.binding_id,
        "--text-file",
        spec.prompt_file,
        "--synthetic-source",
        spec.synthetic_source,
        "--display-mode",
        spec.display_mode,
    ]
    return "/bin/sh -lc " + shlex.quote(" ".join(shlex.quote(part) for part in command))


def render_service_unit(spec: ScheduledTaskSpec) -> str:
    description = spec.description or f"Feishu Codex scheduled prompt: {spec.task_id}"
    return "\n".join(
        [
            "[Unit]",
            f"Description={description}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={_shell_execstart(spec)}",
            "",
        ]
    )


def render_timer_unit(spec: ScheduledTaskSpec) -> str:
    description = spec.description or f"Feishu Codex scheduled timer: {spec.task_id}"
    return "\n".join(
        [
            "[Unit]",
            f"Description={description}",
            "",
            "[Timer]",
            f"OnCalendar={spec.on_calendar}",
            "Persistent=true",
            f"Unit={spec.unit_name}.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def save_spec(spec: ScheduledTaskSpec, *, prompt_text: str) -> None:
    normalized_task_id = normalize_task_id(spec.task_id)
    prompt_file = prompt_path(normalized_task_id)
    _write_text(prompt_file, prompt_text)
    stored = ScheduledTaskSpec(
        task_id=normalized_task_id,
        instance=spec.instance,
        binding_id=spec.binding_id,
        on_calendar=spec.on_calendar,
        description=spec.description,
        prompt_file=str(prompt_file),
        ctl_path=spec.ctl_path,
        synthetic_source=spec.synthetic_source,
        display_mode=spec.display_mode,
        created_at=spec.created_at,
    )
    _write_text(metadata_path(normalized_task_id), json.dumps(asdict(stored), ensure_ascii=False, indent=2) + "\n")
    _write_text(service_unit_path(normalized_task_id), render_service_unit(stored))
    _write_text(timer_unit_path(normalized_task_id), render_timer_unit(stored))


def load_spec(task_id: str) -> ScheduledTaskSpec:
    path = metadata_path(normalize_task_id(task_id))
    if not path.exists():
        raise ValueError(f"未找到 task：{task_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ScheduledTaskSpec(**raw)


def list_specs() -> list[ScheduledTaskSpec]:
    root = scheduled_task_root()
    if not root.exists():
        return []
    specs: list[ScheduledTaskSpec] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = child / "task.json"
        if not meta.exists():
            continue
        raw = json.loads(meta.read_text(encoding="utf-8"))
        specs.append(ScheduledTaskSpec(**raw))
    return specs


def create_task(args: argparse.Namespace) -> int:
    task_id = normalize_task_id(args.task_id)
    ctl_path = detect_ctl_path(args.ctl_path)
    prompt_text = pathlib.Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    spec = ScheduledTaskSpec(
        task_id=task_id,
        instance=str(args.instance or "").strip(),
        binding_id=str(args.binding_id or "").strip(),
        on_calendar=str(args.on_calendar or "").strip(),
        description=str(args.description or "").strip(),
        prompt_file="",
        ctl_path=ctl_path,
        synthetic_source=str(args.synthetic_source or "schedule").strip() or "schedule",
        display_mode=str(args.display_mode or "silent").strip() or "silent",
        created_at=_utc_now_iso(),
    )
    existed = service_unit_path(task_id).exists() or timer_unit_path(task_id).exists()
    save_spec(spec, prompt_text=prompt_text)
    _run_systemctl("daemon-reload")
    _run_systemctl("enable", f"{spec.unit_name}.timer")
    _run_systemctl("restart" if existed else "start", f"{spec.unit_name}.timer")
    print(f"task: {task_id}")
    print(f"instance: {spec.instance}")
    print(f"binding: {spec.binding_id}")
    print(f"on_calendar: {spec.on_calendar}")
    print(f"prompt_file: {prompt_path(task_id)}")
    print(f"service_unit: {service_unit_path(task_id)}")
    print(f"timer_unit: {timer_unit_path(task_id)}")
    print(f"result: {'updated' if existed else 'created'}")
    return 0


def list_tasks() -> int:
    specs = list_specs()
    if not specs:
        print("当前没有已登记的 scheduled tasks。")
        return 0
    print("TASK_ID\tINSTANCE\tBINDING\tON_CALENDAR\tDISPLAY\tDESCRIPTION")
    for spec in specs:
        print(
            "\t".join(
                [
                    spec.task_id,
                    spec.instance,
                    spec.binding_id,
                    spec.on_calendar,
                    spec.display_mode,
                    spec.description or "-",
                ]
            )
        )
    return 0


def show_task(task_id: str) -> int:
    spec = load_spec(task_id)
    print(f"task: {spec.task_id}")
    print(f"instance: {spec.instance}")
    print(f"binding: {spec.binding_id}")
    print(f"on_calendar: {spec.on_calendar}")
    print(f"display_mode: {spec.display_mode}")
    print(f"synthetic_source: {spec.synthetic_source}")
    print(f"description: {spec.description or '-'}")
    print(f"prompt_file: {spec.prompt_file}")
    print(f"service_unit: {service_unit_path(spec.task_id)}")
    print(f"timer_unit: {timer_unit_path(spec.task_id)}")
    print(f"created_at: {spec.created_at}")
    return 0


def remove_task(task_id: str) -> int:
    spec = load_spec(task_id)
    _run_systemctl("disable", "--now", f"{spec.unit_name}.timer", check=False)
    _run_systemctl("reset-failed", f"{spec.unit_name}.timer", f"{spec.unit_name}.service", check=False)
    for path in (
        service_unit_path(spec.task_id),
        timer_unit_path(spec.task_id),
        metadata_path(spec.task_id),
        prompt_path(spec.task_id),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        task_dir(spec.task_id).rmdir()
    except OSError:
        pass
    _run_systemctl("daemon-reload")
    print(f"task: {spec.task_id}")
    print("result: removed")
    return 0


def run_task_now(task_id: str) -> int:
    spec = load_spec(task_id)
    _run_systemctl("start", f"{spec.unit_name}.service")
    print(f"task: {spec.task_id}")
    print("result: started-now")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_scheduled_prompt.py",
        description="Manage Linux systemd --user timers that send future prompts into Feishu-bound Codex threads.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--task-id", required=True)
    create.add_argument("--instance", required=True)
    create.add_argument("--binding-id", required=True)
    create.add_argument("--on-calendar", required=True)
    create.add_argument("--prompt-file", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--synthetic-source", default="schedule")
    create.add_argument("--display-mode", choices=("silent", "announce"), default="silent")
    create.add_argument("--ctl-path", default="")

    subparsers.add_parser("list")

    show = subparsers.add_parser("show")
    show.add_argument("--task-id", required=True)

    remove = subparsers.add_parser("remove")
    remove.add_argument("--task-id", required=True)

    run_now = subparsers.add_parser("run-now")
    run_now.add_argument("--task-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "linux":
        print("该 helper 当前只支持 Linux systemd --user。", file=sys.stderr)
        return 2
    if shutil.which("systemctl") is None:
        print("未找到 `systemctl`；该 helper 需要 systemd --user。", file=sys.stderr)
        return 2
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "create":
            return create_task(args)
        if args.command == "list":
            return list_tasks()
        if args.command == "show":
            return show_task(args.task_id)
        if args.command == "remove":
            return remove_task(args.task_id)
        if args.command == "run-now":
            return run_task_now(args.task_id)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip() or str(exc)
        print(message, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
