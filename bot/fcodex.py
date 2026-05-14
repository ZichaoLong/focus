"""
fcodex 本地 wrapper。
"""

from __future__ import annotations

import os
import pathlib
import secrets
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass, replace

from bot.adapters.base import ThreadSummary
from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from bot.codex_config_reader import resolve_profile_from_codex_config
from bot.config import load_config_file
from bot.constants import DEFAULT_APP_SERVER_URL
from bot.env_file import load_env_file
from bot.instance_layout import DEFAULT_INSTANCE_NAME, global_data_dir, validate_instance_name
from bot.instance_resolution import (
    CliRuntimeTarget,
    current_cli_instance_name,
    list_running_instances,
    resolve_cli_runtime_target,
    resolve_running_instance_app_server_url,
)
from bot.local_websocket_auth import FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR, FCODEX_SERVICE_TOKEN_ENV_VAR
from bot.platform_paths import default_data_root, is_windows
from bot.stores.thread_memory_mode_store import ThreadMemoryModeStore
from bot.thread_resolution import (
    looks_like_thread_id,
    resolve_resume_name_via_remote_backend,
)
from bot.stores.thread_resume_profile_store import ThreadResumeProfileRecord, ThreadResumeProfileStore
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLeaseStore
from bot.thread_resume_profile_setting import (
    ThreadResumeProfileSetting,
    describe_thread_resume_profile_setting_diff,
    format_thread_resume_profile_missing_fields,
    resolve_thread_resume_profile_setting,
    thread_resume_profile_setting_from_record,
    thread_resume_profile_setting_missing_fields,
    thread_resume_profile_settings_equal,
)
from bot.thread_profile_mutability import (
    check_thread_resume_profile_mutable,
    format_thread_resume_profile_denial_for_local_cli,
)
from bot.thread_runtime_coordination import preview_thread_global_loaded_gate

_OPTIONS_WITH_VALUE = {
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

_REMOVED_WRAPPER_COMMAND_HINTS = {
    "/help": "本地查看/管理请改用 `feishu-codexctl`；进入 TUI 后再使用 upstream `/help`。",
    "/threads": "本地看线程请改用 `feishu-codexctl thread list --scope cwd` 或 `feishu-codexctl thread list --scope global`。",
    "/resume": "请改用 `fcodex resume <thread_id|thread_name>`。",
    "/profile": "请改用启动时显式传 `fcodex -p <profile>`。",
    "/archive": "请改用 `feishu-codexctl thread archive --thread-id <id>` 或 `--thread-name <name>`；飞书侧仍可用 `/archive`。",
}


def _has_option(user_args: list[str], names: tuple[str, ...]) -> bool:
    for arg in user_args:
        for name in names:
            if arg == name or arg.startswith(f"{name}="):
                return True
    return False


def _has_explicit_remote(user_args: list[str]) -> bool:
    return _has_option(user_args, ("--remote",))


def _has_explicit_profile(user_args: list[str]) -> bool:
    return _has_option(user_args, ("-p", "--profile"))


def _has_explicit_remote_auth_token_env(user_args: list[str]) -> bool:
    return _has_option(user_args, ("--remote-auth-token-env",))


def _has_explicit_cwd(user_args: list[str]) -> bool:
    return _has_option(user_args, ("-C", "--cd"))


def _default_data_dir() -> pathlib.Path:
    raw = os.environ.get("FC_DATA_DIR", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    return default_data_root()


def _consume_instance_arg(user_args: list[str]) -> tuple[str, list[str]]:
    if not user_args:
        return "", []
    first = user_args[0]
    if first == "--instance":
        if len(user_args) < 2:
            print("`--instance` 缺少实例名。", file=sys.stderr)
            raise SystemExit(2)
        return validate_instance_name(user_args[1]), user_args[2:]
    if first.startswith("--instance="):
        return validate_instance_name(first.split("=", 1)[1]), user_args[1:]
    return "", list(user_args)


def _first_positional_index(user_args: list[str], *, start: int = 0) -> int | None:
    i = start
    while i < len(user_args):
        arg = user_args[i]
        if arg == "--":
            return i + 1 if i + 1 < len(user_args) else None
        if not arg.startswith("-") or arg == "-":
            return i
        option_name = arg.split("=", 1)[0]
        if option_name in _OPTIONS_WITH_VALUE and "=" not in arg:
            i += 2
            continue
        i += 1
    return None


def _resume_command_index(user_args: list[str]) -> int | None:
    first_positional_index = _first_positional_index(user_args)
    if first_positional_index is None:
        return None
    if user_args[first_positional_index] != "resume":
        return None
    return first_positional_index


def _resume_target_index(user_args: list[str]) -> int | None:
    resume_index = _resume_command_index(user_args)
    if resume_index is None:
        return None
    return _first_positional_index(user_args, start=resume_index + 1)


def _removed_wrapper_command_error(user_args: list[str]) -> int | None:
    first_positional_index = _first_positional_index(user_args)
    if first_positional_index is None:
        return None
    first_positional = str(user_args[first_positional_index] or "").strip()
    if not first_positional.startswith("/"):
        return None
    print(f"fcodex shell 层不再支持 slash 自命令：`{first_positional}`", file=sys.stderr)
    hint = _REMOVED_WRAPPER_COMMAND_HINTS.get(first_positional)
    if hint:
        print(hint, file=sys.stderr)
    else:
        print("其他 `/...` 命令请先进入 Codex TUI 再执行。", file=sys.stderr)
    return 2


def _lease_owner_instance(thread_id: str) -> str:
    lease = ThreadRuntimeLeaseStore(global_data_dir()).load(thread_id)
    if lease is None:
        return ""
    return lease.owner_instance


def _configured_app_server_url(cfg: dict) -> str:
    return str(cfg.get("app_server_url", DEFAULT_APP_SERVER_URL)).strip() or DEFAULT_APP_SERVER_URL


def _preferred_resume_instance_for_thread(thread_id: str, *, explicit_instance: str = "") -> str:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return ""
    owner_instance = _lease_owner_instance(normalized_thread_id)
    normalized_explicit = str(explicit_instance or "").strip()
    if normalized_explicit and owner_instance and owner_instance != normalized_explicit:
        raise ValueError(
            f"目标 thread 当前的 live runtime owner 是 `{owner_instance}`；"
            f"不能显式传 `--instance {normalized_explicit}`。"
            f"请改用 `--instance {owner_instance}`，或先让该 thread 完全 unloaded 后再试。"
        )
    if owner_instance:
        return owner_instance
    running_instances = list_running_instances()
    if len(running_instances) == 1:
        return running_instances[0].instance_name
    return ""


def _assert_cross_instance_resume_loaded_gate(thread_id: str, *, target_instance: str) -> None:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return
    preview = preview_thread_global_loaded_gate(
        thread_id=normalized_thread_id,
        current_instance_name=target_instance,
        running_instances=list_running_instances(),
    )
    if preview.allowed:
        return
    raise ValueError(preview.reason_text)


def _resume_lookup_instance_name(cfg: dict) -> str:
    configured_url = _configured_app_server_url(cfg)
    running_instances = list_running_instances()
    if not running_instances:
        return ""
    current_instance = current_cli_instance_name()
    preferred_order = sorted(
        running_instances,
        key=lambda entry: (entry.instance_name != current_instance, entry.instance_name),
    )
    for entry in preferred_order:
        app_server_url = resolve_running_instance_app_server_url(
            entry,
            configured_app_server_url=configured_url,
        )
        if app_server_url:
            return entry.instance_name
    raise ValueError("运行中的实例均未发布可用的 app-server 地址；请重启实例后再试。")


def _resolve_runtime_target_for_wrapper(
    *,
    cfg: dict,
    explicit_instance: str,
    thread_id: str = "",
    preferred_running_instance: str = "",
    allow_default_running_fallback: bool = True,
) -> CliRuntimeTarget:
    """Resolve the one shared-backend runtime target for this wrapper launch."""
    configured_url = _configured_app_server_url(cfg)
    preferred_instance = str(preferred_running_instance or "").strip() or (_lease_owner_instance(thread_id) if thread_id else "")
    try:
        return resolve_cli_runtime_target(
            configured_app_server_url=configured_url,
            explicit_instance=explicit_instance or None,
            preferred_running_instance=preferred_instance,
            allow_default_running_fallback=allow_default_running_fallback,
            default_instance_data_dir=_default_data_dir(),
        )
    except ValueError as exc:
        error_text = str(exc)
        if (
            thread_id
            and "检测到多个运行中的实例" in error_text
            and "请显式传 `--instance <name>`" in error_text
        ):
            running_names = ", ".join(entry.instance_name for entry in list_running_instances()) or "（无）"
            error_text = (
                "当前是 `fcodex resume <thread>` 路径，但该 thread 现在没有唯一可用的实例路由。"
                f"当前运行中的实例：{running_names}。"
                "请显式传 `--instance <name>`。"
                "如果你原本期望沿用某个实例，请先确认该实例是否仍持有该 thread，"
                "必要时在该实例侧执行 `feishu-codexctl --instance <name> service reset-backend` 后再试。"
            )
        print(error_text, file=sys.stderr)
        raise SystemExit(2)


def _inject_profile_arg_if_missing(user_args: list[str], profile: str) -> list[str]:
    if not profile or _has_explicit_profile(user_args):
        return list(user_args)
    return ["--profile", profile, *user_args]


def _inject_default_cwd(user_args: list[str]) -> list[str]:
    if _has_explicit_cwd(user_args):
        return list(user_args)
    return ["--cd", os.getcwd(), *user_args]


def _remote_adapter_config(
    cfg: dict,
    app_server_url: str,
    *,
    data_dir: pathlib.Path | None = None,
) -> CodexAppServerConfig:
    config = CodexAppServerConfig.from_dict(cfg)
    return replace(
        config,
        app_server_mode="remote",
        app_server_url=app_server_url,
        app_server_data_dir=str(data_dir) if data_dir is not None else "",
    )


def _resolve_thread_target_via_remote_backend(
    cfg: dict,
    app_server_url: str,
    data_dir: pathlib.Path,
    target: str,
) -> tuple[ThreadSummary | None, str | None]:
    cleaned = target.strip()
    if not cleaned:
        return None, "目标不能为空"
    if looks_like_thread_id(cleaned):
        config = _remote_adapter_config(cfg, app_server_url, data_dir=data_dir)
        adapter = CodexAppServerAdapter(config)
        try:
            return adapter.read_thread(cleaned, include_turns=False).summary, None
        except Exception as exc:
            return None, f"未找到匹配的线程：`{cleaned}` ({exc})"
        finally:
            adapter.stop()
    try:
        thread = resolve_resume_name_via_remote_backend(
            base_config=_remote_adapter_config(cfg, app_server_url, data_dir=data_dir),
            app_server_url=app_server_url,
            query_limit=int(cfg.get("thread_list_query_limit", 100)),
            target=cleaned,
        )
    except Exception as exc:
        return None, str(exc)
    return thread, None


@dataclass(frozen=True, slots=True)
class _ResolvedResumeTarget:
    user_args: list[str]
    preferred_running_instance: str = ""


def _resolve_resume_lookup_runtime_target(
    cfg: dict,
    explicit_instance: str,
) -> CliRuntimeTarget:
    normalized_explicit = str(explicit_instance or "").strip()
    if normalized_explicit:
        return _resolve_runtime_target_for_wrapper(
            cfg=cfg,
            explicit_instance=normalized_explicit,
            allow_default_running_fallback=False,
        )
    try:
        lookup_instance = _resume_lookup_instance_name(cfg)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    if lookup_instance:
        return _resolve_runtime_target_for_wrapper(
            cfg=cfg,
            explicit_instance=lookup_instance,
            allow_default_running_fallback=False,
        )
    return _resolve_runtime_target_for_wrapper(
        cfg=cfg,
        explicit_instance="",
        allow_default_running_fallback=False,
    )


def _resolve_resume_target(
    cfg: dict,
    explicit_instance: str,
    user_args: list[str],
) -> _ResolvedResumeTarget:
    target_index = _resume_target_index(user_args)
    if target_index is None:
        return _ResolvedResumeTarget(user_args=list(user_args))
    target = str(user_args[target_index] or "").strip()
    if not target:
        return _ResolvedResumeTarget(user_args=list(user_args))
    if explicit_instance:
        if looks_like_thread_id(target):
            try:
                _preferred_resume_instance_for_thread(target, explicit_instance=explicit_instance)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)
            return _ResolvedResumeTarget(user_args=list(user_args))
        lookup_target = _resolve_resume_lookup_runtime_target(cfg, explicit_instance)
        thread, error = _resolve_thread_target_via_remote_backend(
            cfg,
            lookup_target.app_server_url,
            lookup_target.data_dir,
            target,
        )
        if thread is None:
            print(str(error or "未找到匹配的线程。"), file=sys.stderr)
            raise SystemExit(2)
        try:
            _preferred_resume_instance_for_thread(thread.thread_id, explicit_instance=explicit_instance)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        resolved = list(user_args)
        resolved[target_index] = thread.thread_id
        return _ResolvedResumeTarget(user_args=resolved)
    if looks_like_thread_id(target):
        try:
            preferred_instance = _preferred_resume_instance_for_thread(target)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        return _ResolvedResumeTarget(
            user_args=list(user_args),
            preferred_running_instance=preferred_instance,
        )
    lookup_target = _resolve_resume_lookup_runtime_target(cfg, explicit_instance)
    thread, error = _resolve_thread_target_via_remote_backend(
        cfg,
        lookup_target.app_server_url,
        lookup_target.data_dir,
        target,
    )
    if thread is None:
        print(str(error or "未找到匹配的线程。"), file=sys.stderr)
        raise SystemExit(2)
    try:
        preferred_instance = _preferred_resume_instance_for_thread(thread.thread_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    resolved = list(user_args)
    resolved[target_index] = thread.thread_id
    return _ResolvedResumeTarget(
        user_args=resolved,
        preferred_running_instance=preferred_instance,
    )


def _thread_resume_profile_mutable(
    cfg: dict,
    app_server_url: str,
    data_dir: pathlib.Path,
    thread_id: str,
    *,
    target_instance_name: str,
) -> tuple[bool, str]:
    adapter = CodexAppServerAdapter(_remote_adapter_config(cfg, app_server_url, data_dir=data_dir))
    try:
        check = check_thread_resume_profile_mutable(
            thread_id,
            unbound_reason="恢复目标不能为空。",
            has_runtime_lease=lambda normalized_thread_id: (
                ThreadRuntimeLeaseStore(global_data_dir()).load(normalized_thread_id) is not None
            ),
            list_loaded_thread_ids=adapter.list_loaded_thread_ids,
        )
        return (
            check.allowed,
            format_thread_resume_profile_denial_for_local_cli(
                check,
                instance_name=target_instance_name,
            ),
        )
    finally:
        adapter.stop()


def _persist_thread_resume_profile_for_resume(
    thread_id: str,
    setting: ThreadResumeProfileSetting,
) -> None:
    ThreadResumeProfileStore(global_data_dir()).save(
        thread_id,
        profile=setting.profile,
        model=setting.model,
        model_provider=setting.model_provider,
    )


def _runtime_provider_for_profile(
    cfg: dict,
    app_server_url: str,
    data_dir: pathlib.Path,
    profile: str,
) -> str:
    normalized_profile = str(profile or "").strip()
    if not normalized_profile:
        return ""
    adapter = CodexAppServerAdapter(_remote_adapter_config(cfg, app_server_url, data_dir=data_dir))
    try:
        runtime_config = adapter.read_runtime_config()
        for item in runtime_config.profiles:
            if item.name == normalized_profile:
                return str(item.model_provider or "").strip()
    except Exception:
        return ""
    finally:
        adapter.stop()
    return ""


def _resolve_thread_resume_profile_setting_for_resume(
    cfg: dict,
    app_server_url: str,
    data_dir: pathlib.Path,
    profile: str,
) -> ThreadResumeProfileSetting:
    normalized_profile = str(profile or "").strip()
    runtime_provider = _runtime_provider_for_profile(cfg, app_server_url, data_dir, normalized_profile)
    resolved = resolve_profile_from_codex_config(normalized_profile)
    return resolve_thread_resume_profile_setting(
        normalized_profile,
        resolved=resolved,
        runtime_provider=runtime_provider,
    )


def _require_concrete_explicit_profile_setting(
    setting: ThreadResumeProfileSetting,
) -> ThreadResumeProfileSetting:
    missing_fields = thread_resume_profile_setting_missing_fields(setting)
    if not missing_fields:
        return setting
    missing_text = format_thread_resume_profile_missing_fields(missing_fields)
    raise ValueError(
        "当前 `-p/--profile` 解析出的 thread-wise profile slice 不完整："
        f"profile=`{setting.profile or '（未设置）'}`，缺少：{missing_text}。"
        "本项目显式 profile 改写只读取共享用户级 `CODEX_HOME/config.toml`，"
        "不读取当前 cwd / 项目本地 config。"
    )


def _require_concrete_persisted_profile_record(
    thread_id: str,
    record: ThreadResumeProfileRecord,
) -> ThreadResumeProfileSetting:
    setting = thread_resume_profile_setting_from_record(record)
    missing_fields = thread_resume_profile_setting_missing_fields(setting)
    if not missing_fields:
        assert setting is not None
        return setting
    missing_text = format_thread_resume_profile_missing_fields(missing_fields)
    raise ValueError(
        "当前 thread 已持久化的 thread-wise profile slice 不完整："
        f"thread=`{thread_id}`，profile=`{record.profile}`，缺少：{missing_text}。"
        "当前按 fail-close 拒绝继续。"
        "请显式执行 `fcodex resume <thread> -p <profile>` 重新写入完整设置，"
        "或改用飞书 `/profile <name>`。"
    )


def _inject_saved_thread_resume_profile_if_needed(user_args: list[str], thread_id: str) -> list[str]:
    if _has_explicit_profile(user_args):
        return list(user_args)
    record = ThreadResumeProfileStore(global_data_dir()).load(thread_id)
    if record is None or not record.profile:
        return list(user_args)
    # Wrapper-side `--profile` is only a CLI hint for upstream TUI/bootstrap.
    # The real persisted next-load profile slice is enforced later by the
    # local proxy when it rewrites `thread/resume`.
    return _inject_profile_arg_if_missing(user_args, record.profile)


@dataclass(frozen=True, slots=True)
class _WrapperProfileLaunchPlan:
    user_args: list[str]
    new_thread_profile_seed: ThreadResumeProfileSetting | None = None
    new_thread_memory_mode_seed: str = ""
    resume_profile_hint: str = ""


def _build_wrapper_profile_launch_plan(
    *,
    cfg: dict,
    app_server_url: str,
    data_dir: pathlib.Path,
    instance_name: str,
    user_args: list[str],
) -> _WrapperProfileLaunchPlan:
    """Plan wrapper-side profile behavior before launching upstream Codex.

    Wrapper responsibilities stop at:

    - existing-thread resume profile read/write
    - deciding whether this launch carries a one-time new-thread seed

    The proxy later owns enforcing that seed at the actual `thread/start` RPC
    boundary, then holding it as pending state until the first successful turn
    materializes that logical thread.
    """
    planned_args = list(user_args)
    configured_new_thread_memory_mode_seed = CodexAppServerConfig.from_dict(cfg).new_thread_memory_mode_seed
    resume_thread_id = _thread_target_hint(planned_args)
    explicit_profile = _extract_option_value(planned_args, ("-p", "--profile")).strip()
    if resume_thread_id:
        resume_profile_hint = ""
        saved_profile_record = ThreadResumeProfileStore(global_data_dir()).load(resume_thread_id)
        desired_setting: ThreadResumeProfileSetting | None = None
        if explicit_profile:
            resume_profile_hint = explicit_profile
            try:
                desired_setting = _require_concrete_explicit_profile_setting(
                    _resolve_thread_resume_profile_setting_for_resume(
                        cfg,
                        app_server_url,
                        data_dir,
                        explicit_profile,
                    )
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)
            if thread_resume_profile_settings_equal(saved_profile_record, desired_setting):
                return _WrapperProfileLaunchPlan(
                    user_args=planned_args,
                    resume_profile_hint=resume_profile_hint,
                )
        elif saved_profile_record is not None:
            try:
                _require_concrete_persisted_profile_record(resume_thread_id, saved_profile_record)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)
            resume_profile_hint = str(saved_profile_record.profile or "").strip()
        elif ThreadMemoryModeStore(global_data_dir()).load(resume_thread_id) is not None:
            adapter = CodexAppServerAdapter(_remote_adapter_config(cfg, app_server_url, data_dir=data_dir))
            try:
                runtime_config = adapter.read_runtime_config()
                resume_profile_hint = str(runtime_config.current_profile or "").strip()
            except Exception:
                resume_profile_hint = ""
            finally:
                adapter.stop()
        if explicit_profile:
            can_write, deny_reason = _thread_resume_profile_mutable(
                cfg,
                app_server_url,
                data_dir,
                resume_thread_id,
                target_instance_name=instance_name,
            )
            if not can_write:
                if (
                    saved_profile_record is not None
                    and str(saved_profile_record.profile or "").strip() == explicit_profile
                ):
                    desired_setting = desired_setting or _require_concrete_explicit_profile_setting(
                        _resolve_thread_resume_profile_setting_for_resume(
                            cfg,
                            app_server_url,
                            data_dir,
                            explicit_profile,
                        )
                    )
                    diffs = describe_thread_resume_profile_setting_diff(saved_profile_record, desired_setting)
                    if diffs:
                        diff_text = "；".join(diffs)
                        deny_reason = (
                            "当前 `-p/--profile` 指向同名 profile，但它解析出的 thread 级 next-load 设置已变化："
                            f"{diff_text}。"
                            "要让这些变化生效，必须等该 thread truly unloaded，或先 reset backend。"
                            f"\n{deny_reason}"
                        )
                print(deny_reason, file=sys.stderr)
                raise SystemExit(2)
            desired_setting = desired_setting or _require_concrete_explicit_profile_setting(
                _resolve_thread_resume_profile_setting_for_resume(
                    cfg,
                    app_server_url,
                    data_dir,
                    explicit_profile,
                )
            )
            _persist_thread_resume_profile_for_resume(
                resume_thread_id,
                desired_setting,
            )
            return _WrapperProfileLaunchPlan(
                user_args=planned_args,
                resume_profile_hint=resume_profile_hint,
            )
        return _WrapperProfileLaunchPlan(
            user_args=_inject_saved_thread_resume_profile_if_needed(planned_args, resume_thread_id),
            resume_profile_hint=resume_profile_hint,
        )
    if explicit_profile:
        try:
            desired_setting = _require_concrete_explicit_profile_setting(
                _resolve_thread_resume_profile_setting_for_resume(
                    cfg,
                    app_server_url,
                    data_dir,
                    explicit_profile,
                )
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        return _WrapperProfileLaunchPlan(
            user_args=planned_args,
            new_thread_profile_seed=desired_setting,
            new_thread_memory_mode_seed=configured_new_thread_memory_mode_seed,
        )
    return _WrapperProfileLaunchPlan(
        user_args=planned_args,
        new_thread_memory_mode_seed=configured_new_thread_memory_mode_seed,
    )


def _extract_option_value(user_args: list[str], names: tuple[str, ...]) -> str:
    i = 0
    while i < len(user_args):
        arg = user_args[i]
        for name in names:
            if arg == name:
                return user_args[i + 1] if i + 1 < len(user_args) else ""
            prefix = f"{name}="
            if arg.startswith(prefix):
                return arg[len(prefix) :]
        if arg.split("=", 1)[0] in _OPTIONS_WITH_VALUE and "=" not in arg:
            i += 2
            continue
        i += 1
    return ""


def _thread_target_hint(user_args: list[str]) -> str:
    target_index = _resume_target_index(user_args)
    if target_index is not None:
        target = str(user_args[target_index] or "").strip()
        if looks_like_thread_id(target):
            return target
    return ""


def _resolve_effective_cwd(user_args: list[str]) -> str:
    raw = _extract_option_value(user_args, ("-C", "--cd")).strip()
    if not raw:
        return os.getcwd()
    return os.path.abspath(os.path.expanduser(raw))


def _read_subprocess_ready_line(process: subprocess.Popen[str], timeout_seconds: float = 5.0) -> str:
    if process.stdout is None:
        raise RuntimeError("proxy stdout unavailable")

    result: dict[str, object] = {}

    def _reader() -> None:
        try:
            result["line"] = process.stdout.readline()
        except Exception as exc:  # pragma: no cover - defensive
            result["error"] = exc

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise TimeoutError("proxy readiness timeout")
    error = result.get("error")
    if isinstance(error, Exception):
        raise error
    return str(result.get("line", ""))


def _launch_local_cwd_proxy(
    backend_url: str,
    effective_cwd: str,
    data_dir: pathlib.Path,
    *,
    instance_name: str = DEFAULT_INSTANCE_NAME,
    service_token: str = "",
    new_thread_profile_seed: str = "",
    new_thread_profile_model_seed: str = "",
    new_thread_profile_model_provider_seed: str = "",
    new_thread_memory_mode_seed: str = "",
    resume_profile_hint: str = "",
    proxy_auth_token: str,
) -> tuple[str, subprocess.Popen[str]]:
    cmd = [
        sys.executable,
        "-m",
        "bot.fcodex_proxy",
        "--backend-url",
        backend_url,
        "--cwd",
        effective_cwd,
        "--data-dir",
        str(data_dir),
        "--instance",
        instance_name,
        "--global-data-dir",
        str(global_data_dir()),
        "--new-thread-profile-seed",
        new_thread_profile_seed,
        "--new-thread-profile-model-seed",
        new_thread_profile_model_seed,
        "--new-thread-profile-model-provider-seed",
        new_thread_profile_model_provider_seed,
        "--new-thread-memory-mode-seed",
        new_thread_memory_mode_seed,
        "--resume-profile-hint",
        resume_profile_hint,
        "--parent-pid",
        str(os.getpid()),
    ]
    env = os.environ.copy()
    env[FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR] = proxy_auth_token
    if service_token:
        env[FCODEX_SERVICE_TOKEN_ENV_VAR] = service_token
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        ready_line = _read_subprocess_ready_line(process).strip()
        if ready_line:
            return ready_line, process
        exit_code = process.poll()
        if exit_code is None:
            raise RuntimeError("proxy did not report listen url")
        raise RuntimeError(f"proxy exited before ready (exit={exit_code})")
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
        raise


def _stop_child_process(process: subprocess.Popen[str] | None, *, timeout_seconds: float = 1.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_upstream_codex(
    argv: list[str],
    env: dict[str, str],
    *,
    proxy_process: subprocess.Popen[str] | None,
) -> int | None:
    if not is_windows():
        try:
            os.execvpe(argv[0], argv, env)
        except Exception:
            _stop_child_process(proxy_process)
            raise
        return None

    codex_process = subprocess.Popen(argv, env=env)
    try:
        return codex_process.wait()
    except BaseException:
        _stop_child_process(codex_process)
        raise
    finally:
        _stop_child_process(proxy_process)


def main() -> None:
    load_env_file()
    cfg = load_config_file("codex")
    codex_command = str(cfg.get("codex_command", "codex")).strip() or "codex"
    explicit_instance, user_args = _consume_instance_arg(sys.argv[1:])
    if "--dry-run" in user_args:
        print("fcodex 不再提供 `--dry-run` wrapper 入口。", file=sys.stderr)
        print("本地查看线程请改用 `feishu-codexctl thread list`、`thread status`、`thread bindings`。", file=sys.stderr)
        raise SystemExit(2)
    if explicit_instance and _has_explicit_remote(user_args):
        print("`--instance` 不能与显式 `--remote` 同时使用。", file=sys.stderr)
        raise SystemExit(2)
    if not _has_explicit_remote(user_args) and _has_explicit_remote_auth_token_env(user_args):
        print("wrapper 自建 proxy 路径不接受显式 `--remote-auth-token-env`；该参数仅用于显式 `--remote`。", file=sys.stderr)
        raise SystemExit(2)
    removed_wrapper_error = _removed_wrapper_command_error(user_args)
    if removed_wrapper_error is not None:
        raise SystemExit(removed_wrapper_error)

    preprocessed = _ResolvedResumeTarget(user_args=list(user_args))
    if not _has_explicit_remote(user_args):
        preprocessed = _resolve_resume_target(cfg, explicit_instance, user_args)
    preprocessed_args = list(preprocessed.user_args)

    if _has_explicit_remote(preprocessed_args):
        data_dir = _default_data_dir()
        app_server_url = str(cfg.get("app_server_url", DEFAULT_APP_SERVER_URL)).strip() or DEFAULT_APP_SERVER_URL
        resolved_target = CliRuntimeTarget(
            instance_name=current_cli_instance_name(),
            data_dir=data_dir,
            app_server_url=app_server_url,
        )
    else:
        thread_target = _thread_target_hint(preprocessed_args)
        resolved_target = _resolve_runtime_target_for_wrapper(
            cfg=cfg,
            explicit_instance=explicit_instance,
            thread_id=thread_target,
            preferred_running_instance=preprocessed.preferred_running_instance,
            allow_default_running_fallback=not bool(thread_target),
        )
        data_dir = resolved_target.data_dir
        app_server_url = resolved_target.app_server_url
        if thread_target:
            try:
                _assert_cross_instance_resume_loaded_gate(
                    thread_target,
                    target_instance=resolved_target.instance_name,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)

    user_args = list(preprocessed_args)

    argv = [*shlex.split(codex_command)]
    effective_cwd = _resolve_effective_cwd(user_args)
    new_thread_profile_seed: ThreadResumeProfileSetting | None = None
    new_thread_memory_mode_seed = ""
    resume_profile_hint = ""
    if not _has_explicit_remote(user_args):
        profile_launch_plan = _build_wrapper_profile_launch_plan(
            cfg=cfg,
            app_server_url=app_server_url,
            data_dir=data_dir,
            instance_name=resolved_target.instance_name,
            user_args=user_args,
        )
        user_args = list(profile_launch_plan.user_args)
        new_thread_profile_seed = profile_launch_plan.new_thread_profile_seed
        new_thread_memory_mode_seed = profile_launch_plan.new_thread_memory_mode_seed
        resume_profile_hint = profile_launch_plan.resume_profile_hint
    user_args = _inject_default_cwd(user_args)
    proxy_process: subprocess.Popen[str] | None = None
    proxy_auth_token = ""
    if not _has_explicit_remote(user_args):
        try:
            # Upstream Codex TUI omits `cwd` on `thread/start` in `--remote` mode.
            # Without this local proxy, the shared app-server falls back to its own
            # WorkingDirectory (`~/.local/share/feishu-codex`) and fresh `fcodex`
            # sessions don't inherit the caller's shell cwd.
            proxy_kwargs: dict[str, str] = {}
            if resolved_target.instance_name != DEFAULT_INSTANCE_NAME or resolved_target.service_token:
                proxy_kwargs = {
                    "instance_name": resolved_target.instance_name,
                    "service_token": resolved_target.service_token,
                }
            proxy_auth_token = secrets.token_urlsafe(32)
            proxy_url, proxy_process = _launch_local_cwd_proxy(
                app_server_url,
                effective_cwd,
                data_dir,
                new_thread_profile_seed=new_thread_profile_seed.profile if new_thread_profile_seed is not None else "",
                new_thread_profile_model_seed=new_thread_profile_seed.model if new_thread_profile_seed is not None else "",
                new_thread_profile_model_provider_seed=(
                    new_thread_profile_seed.model_provider if new_thread_profile_seed is not None else ""
                ),
                new_thread_memory_mode_seed=new_thread_memory_mode_seed,
                resume_profile_hint=resume_profile_hint,
                proxy_auth_token=proxy_auth_token,
                **proxy_kwargs,
            )
        except Exception as exc:
            print(f"启动 fcodex 本地 cwd proxy 失败：{exc}", file=sys.stderr)
            raise SystemExit(2)
        argv.extend(["--remote", proxy_url, "--remote-auth-token-env", FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR])
    argv.extend(user_args)
    env = os.environ.copy()
    env["FC_DATA_DIR"] = str(data_dir)
    env["FC_INSTANCE"] = resolved_target.instance_name
    if proxy_auth_token:
        env[FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR] = proxy_auth_token
    exit_code = _run_upstream_codex(argv, env, proxy_process=proxy_process)
    if exit_code is not None:
        raise SystemExit(exit_code)
    return


if __name__ == "__main__":
    main()
