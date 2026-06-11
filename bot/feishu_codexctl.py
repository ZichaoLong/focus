"""Local admin CLI for the running feishu-codex service."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import unicodedata
from dataclasses import replace
from typing import Any

from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from bot.binding_identity import format_binding_id
from bot.config import load_config_file
from bot.constants import display_path, format_timestamp
from bot.codex_protocol.client import CodexRpcError
from bot.env_file import load_env_file
from bot.instance_layout import global_data_dir, list_known_instance_names, resolve_instance_paths
from bot.instance_resolution import (
    list_running_instances,
    resolve_cli_instance_target,
    resolve_running_instance_app_server_url,
)
from bot.platform_paths import default_data_root
from bot.service_control_plane import ServiceControlError, control_request
from bot.stores.app_server_runtime_store import AppServerRuntimeStore, resolve_effective_app_server_url
from bot.stores.chat_binding_store import ChatBindingStore
from bot.stores.interaction_lease_store import InteractionLeaseStore, make_feishu_interaction_holder
from bot.stores.service_instance_lease import ServiceInstanceLease
from bot.stores.instance_registry_store import InstanceRegistryEntry
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLeaseStore
from bot.thread_resolution import list_current_dir_threads, list_global_threads
from bot.version import __version__

_CODEX_THREAD_ID_ENV_VAR = "CODEX_THREAD_ID"


class _HelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def _data_dir() -> pathlib.Path:
    raw = os.environ.get("FC_DATA_DIR", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    return default_data_root()


def _resolve_target_instance(
    explicit_instance: str | None,
    *,
    preferred_running_instance: str = "",
):
    return resolve_cli_instance_target(
        explicit_instance,
        preferred_running_instance=preferred_running_instance,
    )


def _request(data_dir: pathlib.Path, method: str, params: dict[str, Any] | None = None) -> Any:
    return control_request(data_dir, method, params)


def _remote_adapter(
    data_dir: pathlib.Path,
    *,
    running_entry: InstanceRegistryEntry | None = None,
) -> tuple[CodexAppServerAdapter, dict[str, Any], str]:
    cfg = load_config_file("codex")
    configured_url = str(cfg.get("app_server_url", "ws://127.0.0.1:8765")).strip() or "ws://127.0.0.1:8765"
    if running_entry is not None:
        app_server_url = resolve_running_instance_app_server_url(
            running_entry,
            configured_app_server_url=configured_url,
        )
        if not app_server_url:
            raise ValueError(
                f"运行中的实例 `{running_entry.instance_name}` 未发布可用的 app-server 地址；请重启该实例后再试。"
            )
    else:
        app_server_url = resolve_effective_app_server_url(configured_url, data_dir=data_dir)
    config = replace(
        CodexAppServerConfig.from_dict(cfg),
        app_server_mode="remote",
        app_server_url=app_server_url,
        app_server_data_dir=str(data_dir),
    )
    return CodexAppServerAdapter(config), cfg, app_server_url


def _thread_target_params(args: argparse.Namespace) -> dict[str, str]:
    thread_id = str(getattr(args, "thread_id", "") or "").strip()
    thread_name = str(getattr(args, "thread_name", "") or "").strip()
    if bool(thread_id) == bool(thread_name):
        raise ValueError("必须且只能提供 --thread-id 或 --thread-name。")
    if thread_id:
        return {"thread_id": thread_id}
    return {"thread_name": thread_name}


def _lease_owner_instance(thread_id: str) -> str:
    lease = ThreadRuntimeLeaseStore(global_data_dir()).load(thread_id)
    if lease is None:
        return ""
    return str(lease.owner_instance or "").strip()


def _image_send_target_params(args: argparse.Namespace) -> tuple[dict[str, str], str]:
    thread_id = str(getattr(args, "thread_id", "") or "").strip()
    thread_name = str(getattr(args, "thread_name", "") or "").strip()
    if thread_id and thread_name:
        raise ValueError("不能同时提供 --thread-id 和 --thread-name。")
    if thread_id:
        return {"thread_id": thread_id}, thread_id
    if thread_name:
        return {"thread_name": thread_name}, ""
    env_thread_id = str(os.environ.get(_CODEX_THREAD_ID_ENV_VAR, "") or "").strip()
    if env_thread_id:
        return {"thread_id": env_thread_id}, env_thread_id
    raise ValueError(
        "必须提供 --thread-id 或 --thread-name；若在 Codex turn 内调用，也可依赖环境变量 `CODEX_THREAD_ID`。"
    )


def _thread_archive_inputs(args: argparse.Namespace) -> tuple[list[str], str]:
    raw_thread_ids = list(getattr(args, "thread_ids", []) or [])
    thread_ids = list(dict.fromkeys(str(item or "").strip() for item in raw_thread_ids if str(item or "").strip()))
    thread_name = str(getattr(args, "thread_name", "") or "").strip()
    if thread_ids and thread_name:
        raise ValueError("thread archive 不能同时提供 `--thread-id` 和 `--thread-name`。")
    if not thread_ids and not thread_name:
        raise ValueError("thread archive 必须提供至少一个 `--thread-id`；单线程也可改用 `--thread-name`。")
    return thread_ids, thread_name


def _resolve_thread_archive_target(args: argparse.Namespace):
    targets = _resolve_thread_archive_targets(args)
    if len(targets) != 1:
        raise ValueError("thread archive 批量模式请改用 _resolve_thread_archive_targets().")
    return targets[0]


def _resolve_thread_archive_targets(args: argparse.Namespace):
    thread_ids, thread_name = _thread_archive_inputs(args)
    explicit_instance = str(getattr(args, "instance", "") or "").strip()
    if thread_ids:
        if explicit_instance:
            target = _resolve_target_instance(explicit_instance)
            return [(target, {"thread_id": thread_id}) for thread_id in thread_ids]
        targets = []
        for thread_id in thread_ids:
            preferred_instance = _lease_owner_instance(thread_id)
            targets.append(
                (
                    _resolve_target_instance(None, preferred_running_instance=preferred_instance),
                    {"thread_id": thread_id},
                )
            )
        return targets
    target_params = {"thread_name": thread_name}
    if explicit_instance:
        return [(_resolve_target_instance(explicit_instance), target_params)]
    bootstrap_target = _resolve_target_instance(None)
    snapshot = _request(bootstrap_target.data_dir, "thread/status", target_params)
    resolved_thread_id = str(snapshot.get("thread_id", "") or "").strip()
    live_runtime_owner = snapshot.get("live_runtime_owner") or {}
    owner_instance = ""
    if isinstance(live_runtime_owner, dict):
        owner_instance = str(live_runtime_owner.get("instance_name", "") or "").strip()
    if resolved_thread_id:
        target_params = {"thread_id": resolved_thread_id}
    if owner_instance:
        return [(_resolve_target_instance(None, preferred_running_instance=owner_instance), target_params)]
    return [(bootstrap_target, target_params)]


def _prompt_text_from_args(args: argparse.Namespace) -> str:
    inline_text = str(getattr(args, "text", "") or "")
    text_file = str(getattr(args, "text_file", "") or "").strip()
    if bool(inline_text.strip()) == bool(text_file):
        raise ValueError("必须且只能提供 --text 或 --text-file。")
    if text_file:
        path = pathlib.Path(text_file).expanduser()
        if not path.exists():
            raise ValueError(f"prompt 文本文件不存在：{display_path(str(path))}")
        if not path.is_file():
            raise ValueError(f"prompt 文本文件不是普通文件：{display_path(str(path))}")
        return path.read_text(encoding="utf-8")
    return inline_text


def _live_runtime_summary(snapshot: dict[str, Any]) -> tuple[str, list[str]]:
    owner = snapshot.get("live_runtime_owner")
    holder_labels = snapshot.get("live_runtime_holder_labels")
    if isinstance(owner, dict) and isinstance(holder_labels, list):
        label = str(owner.get("label", "") or "").strip() or "none"
        normalized_holders = [str(item or "").strip() for item in holder_labels if str(item or "").strip()]
        return label, normalized_holders
    return "none", []


def _terminal_display_width(text: str) -> int:
    total = 0
    for ch in str(text):
        if ch in "\r\n":
            continue
        if unicodedata.combining(ch):
            continue
        if unicodedata.category(ch) == "Cf":
            continue
        total += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return total


def _render_table(headers: list[str], rows: list[list[str]], *, gap: int = 2) -> list[str]:
    if not headers:
        return []
    normalized_rows = [[str(cell) for cell in row] for row in rows]
    widths = [_terminal_display_width(str(cell)) for cell in headers]
    for row in normalized_rows:
        if len(row) != len(headers):
            raise ValueError("表格列数不一致。")
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _terminal_display_width(cell))

    def _pad(cell: str, width: int) -> str:
        padding = max(width - _terminal_display_width(cell), 0)
        return cell + (" " * padding)

    rendered: list[str] = []
    for row in [headers, *normalized_rows]:
        parts: list[str] = []
        for index, cell in enumerate(row):
            if index == len(headers) - 1:
                parts.append(cell)
                continue
            parts.append(_pad(cell, widths[index]) + (" " * gap))
        rendered.append("".join(parts).rstrip())
    return rendered


def _format_goal_ts_seconds(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "-"
    if timestamp <= 0:
        return "-"
    return format_timestamp(timestamp)


def _goal_status_label(status: str) -> str:
    return {
        "active": "进行中",
        "paused": "已暂停",
        "blocked": "已阻塞",
        "usageLimited": "触发 usage 限制",
        "budgetLimited": "触发预算限制",
        "complete": "已完成",
    }.get(str(status or "").strip(), "未知")


def _print_service_status(data_dir: pathlib.Path) -> int:
    metadata = ServiceInstanceLease(data_dir).load_metadata()
    published_endpoint = metadata.control_endpoint if metadata is not None else ""
    try:
        result = _request(data_dir, "service/status")
    except ServiceControlError as exc:
        print("service: stopped")
        print(f"control endpoint: {published_endpoint or 'unavailable'}")
        runtime = AppServerRuntimeStore(data_dir).load_managed_runtime()
        if runtime is not None:
            print(f"last known app server: {runtime.active_url}")
        print(f"reason: {exc}")
        return 3
    if result.get("instance_name"):
        print(f"instance: {result['instance_name']}")
    print("service: running")
    print(f"pid: {result['pid']}")
    print(f"control endpoint: {result['control_endpoint']}")
    print(f"app server: {result['app_server_url']}")
    print(f"app server mode: {result.get('app_server_mode', '-')}")
    print(f"bindings: total={result['binding_count']} bound={result['bound_binding_count']} attached={result['attached_binding_count']}")
    print(f"threads: bound={result['thread_count']} feishu-attached={result['attached_thread_count']} loaded={result['loaded_thread_count']}")
    print(f"running bindings: {', '.join(result['running_binding_ids']) or '（无）'}")
    print(f"backend reset: {result.get('backend_reset_status', '-')}")
    if result.get("backend_reset_reason_code"):
        print(f"backend reset reason code: {result['backend_reset_reason_code']}")
    if result.get("backend_reset_reason"):
        print(f"backend reset reason: {result['backend_reset_reason']}")
    return 0


def _reset_service_backend(data_dir: pathlib.Path, *, force: bool) -> int:
    result = control_request(
        data_dir,
        "service/reset-backend",
        {"force": bool(force)},
        timeout_seconds=30.0,
    )
    print("backend reset: ok")
    print(f"force: {'yes' if result.get('force') else 'no'}")
    print(f"app server: {result.get('app_server_url', '-')}")
    print(f"detached bindings: {', '.join(result.get('detached_binding_ids') or []) or '（无）'}")
    print(f"interrupted bindings: {', '.join(result.get('interrupted_binding_ids') or []) or '（无）'}")
    print(f"fail-closed requests: {int(result.get('fail_closed_request_count') or 0)}")
    print(f"purged runtime leases: {', '.join(result.get('purged_thread_ids') or []) or '（无）'}")
    print("next:")
    print("  - attach this instance: feishu-codexctl service attach")
    print("  - attach one thread: feishu-codexctl thread attach --thread-id <thread_id>")
    print("  - attach one binding: feishu-codexctl binding attach <binding_id>")
    return 0


def _attach_service(data_dir: pathlib.Path) -> int:
    result = _request(data_dir, "service/attach")
    print("runtime attach: ok")
    print(f"instance: {result.get('instance_name', '-')}")
    print(f"attached threads: {', '.join(result.get('attached_thread_ids') or []) or '（无）'}")
    print(f"attached bindings: {', '.join(result.get('attached_binding_ids') or []) or '（无）'}")
    blocked_threads = result.get("blocked_threads") or []
    if blocked_threads:
        print("blocked threads:")
        for item in blocked_threads:
            binding_ids = ", ".join(item.get("binding_ids") or []) or "（无 binding）"
            print(f"- {item.get('thread_id', '-')}: {binding_ids} -> {item.get('reason', '（无原因）')}")
        return 1
    if not result.get("attached_binding_ids"):
        print("note: 当前实例没有需要恢复的 detached 推送。")
    return 0


def _print_binding_list(data_dir: pathlib.Path) -> int:
    result = _request(data_dir, "binding/list")
    bindings = result.get("bindings") or []
    if not bindings:
        print("当前没有可见 binding。")
        return 0
    rows: list[list[str]] = []
    for item in bindings:
        thread = item["thread_id"][:8] + "…" if item["thread_id"] else "-"
        cwd = display_path(str(item["working_dir"] or ""))
        rows.append(
            [
                item["binding_id"],
                item["binding_kind"],
                item["binding_state"],
                item["feishu_runtime_state"],
                thread,
                cwd,
            ]
        )
    for line in _render_table(["BINDING_ID", "KIND", "STATE", "RUNTIME", "THREAD", "CWD"], rows):
        print(line)
    return 0


def _print_binding_status(data_dir: pathlib.Path, binding_id: str, *, instance_name: str = "") -> int:
    snapshot = _request(data_dir, "binding/status", {"binding_id": binding_id})
    live_runtime_owner, live_runtime_holders = _live_runtime_summary(snapshot)
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"binding: {snapshot['binding_id']}")
    print(f"kind: {snapshot['binding_kind']}")
    print(f"chat_id: {snapshot['chat_id']}")
    if snapshot["binding_kind"] == "p2p":
        print(f"sender_id: {snapshot['sender_id']}")
    print(f"working_dir: {display_path(snapshot['working_dir'])}")
    print(f"binding: {snapshot['binding_state']}")
    print(f"thread: {snapshot['thread_id'] or '-'} {snapshot['thread_title'] or ''}".rstrip())
    print(f"feishu push: {snapshot['feishu_runtime_state']}")
    print(f"current instance backend thread status: {snapshot['backend_thread_status']}")
    print(f"backend running turn: {'yes' if snapshot['backend_running_turn'] else 'no'}")
    print(f"live runtime owner: {live_runtime_owner}")
    print(f"live runtime holders: {', '.join(live_runtime_holders) or '（无）'}")
    print(f"current-instance interaction owner: {snapshot['interaction_owner']['label']}")
    if snapshot["next_prompt_allowed"]:
        print("next prompt: accepted")
    else:
        print(f"next prompt: blocked ({snapshot['next_prompt_reason_code']})")
        print(f"next prompt reason: {snapshot['next_prompt_reason']}")
    if snapshot["thread_id"]:
        availability = "available" if snapshot["detach_available"] else "blocked"
        print(f"detach: {availability}")
        if snapshot["detach_reason_code"]:
            print(f"detach reason code: {snapshot['detach_reason_code']}")
        if snapshot["detach_reason"]:
            print(f"detach reason: {snapshot['detach_reason']}")
    print(f"approval_policy: {snapshot['approval_policy']}")
    print(f"permissions_profile_id: {snapshot['permissions_profile_id']}")
    print(f"collaboration_mode: {snapshot['collaboration_mode']}")
    return 0


def _clear_binding(data_dir: pathlib.Path, binding_id: str) -> int:
    result = _request(data_dir, "binding/clear", {"binding_id": binding_id})
    print(f"cleared binding: {result['binding_id']}")
    print(f"thread: {result['thread_id'] or '-'} {result['thread_title'] or ''}".rstrip())
    return 0


def _attach_binding(data_dir: pathlib.Path, binding_id: str) -> int:
    result = _request(data_dir, "binding/attach", {"binding_id": binding_id})
    print(f"binding: {result['binding_id']}")
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    if result.get("already_attached"):
        print("note: 该 binding 原本就已 attached。")
    else:
        print("note: 该 binding 已恢复 attached，可继续接收推送。")
    return 0


def _detach_binding(data_dir: pathlib.Path, binding_id: str) -> int:
    result = _request(data_dir, "binding/detach", {"binding_id": binding_id})
    print(f"binding: {result['binding_id']}")
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    print(f"backend thread status: {result['backend_thread_status']}")
    if result.get("already_detached"):
        print("note: 该 binding 原本就已 detached。")
    elif result.get("backend_still_loaded"):
        print("note: backend 仍保持 loaded；通常还有本地 fcodex 或其他外部订阅者。")
    else:
        print("note: 该 binding 已 detached；如果它是最后一个 attached 的 Feishu binding，服务已自动停止该 thread 的 Feishu 订阅。")
    return 0


def _clear_all_bindings(data_dir: pathlib.Path) -> int:
    result = _request(data_dir, "binding/clear-all")
    cleared_binding_ids = result.get("cleared_binding_ids") or []
    if result.get("already_empty"):
        print("当前没有可清除的 binding。")
        return 0
    print(f"cleared bindings: {', '.join(cleared_binding_ids) or '（无）'}")
    return 0


def _is_cli_thread_unreadable_for_stale_cleanup_error(exc: Exception) -> bool:
    if not isinstance(exc, CodexRpcError):
        return False
    message = str(exc.error.get("message", "") or "").strip().lower()
    return (
        message.startswith("no rollout found for thread id ")
        or message.startswith("thread not found:")
        or message.startswith("thread not loaded:")
    )


def _resolve_stale_binding_query_target() -> tuple[str, pathlib.Path, InstanceRegistryEntry]:
    running_instances = list_running_instances()
    if not running_instances:
        raise ValueError(
            "binding clear-stale 需要至少一个运行中的实例，以便通过 app-server 验证 thread 是否仍存在。"
        )
    selected = sorted(
        running_instances,
        key=lambda item: (0 if str(item.instance_name or "").strip().lower() == "default" else 1, item.instance_name),
    )[0]
    return selected.instance_name, pathlib.Path(selected.data_dir), selected


def _build_thread_presence_checker(
    data_dir: pathlib.Path,
    *,
    running_entry: InstanceRegistryEntry,
):
    adapter, _cfg, _app_server_url = _remote_adapter(pathlib.Path(data_dir), running_entry=running_entry)
    cache: dict[str, tuple[str, str]] = {}

    def _check(thread_id: str) -> tuple[str, str]:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return "skip", "empty_thread_id"
        cached = cache.get(normalized_thread_id)
        if cached is not None:
            return cached
        try:
            adapter.read_thread(normalized_thread_id, include_turns=True)
        except Exception as exc:
            if _is_cli_thread_unreadable_for_stale_cleanup_error(exc):
                result = ("stale", str(exc) or "thread not found")
            else:
                result = ("unknown", str(exc) or type(exc).__name__)
        else:
            result = ("present", "")
        cache[normalized_thread_id] = result
        return result

    return adapter, _check


def _clear_stale_bindings_from_store(
    data_dir: pathlib.Path,
    thread_presence_check,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    store = ChatBindingStore(pathlib.Path(data_dir))
    interaction_leases = InteractionLeaseStore(pathlib.Path(data_dir))
    clear_bindings: list[tuple[tuple[str, str], str]] = []
    retained_binding_ids: list[str] = []
    skipped_binding_ids: list[str] = []
    unknown_threads: dict[str, str] = {}
    stale_thread_ids: set[str] = set()
    for binding, state in sorted(store.load_all().items(), key=lambda item: format_binding_id(item[0])):
        binding_id = format_binding_id(binding)
        thread_id = str(state.get("current_thread_id", "") or "").strip()
        if not thread_id:
            skipped_binding_ids.append(binding_id)
            continue
        status, reason = thread_presence_check(thread_id)
        if status == "stale":
            clear_bindings.append((binding, thread_id))
            stale_thread_ids.add(thread_id)
            continue
        if status == "unknown":
            unknown_threads.setdefault(thread_id, reason)
            retained_binding_ids.append(binding_id)
            continue
        retained_binding_ids.append(binding_id)

    if not dry_run:
        for binding, thread_id in clear_bindings:
            store.clear(binding)
            interaction_leases.release(
                thread_id,
                make_feishu_interaction_holder(binding[0], binding[1], owner_pid=0),
            )
    cleared_binding_ids = [format_binding_id(binding) for binding, _thread_id in clear_bindings]
    return {
        "cleared_binding_ids": [] if dry_run else cleared_binding_ids,
        "would_clear_binding_ids": cleared_binding_ids if dry_run else [],
        "stale_thread_ids": sorted(stale_thread_ids),
        "unknown_threads": [
            {"thread_id": thread_id, "reason": reason}
            for thread_id, reason in sorted(unknown_threads.items())
        ],
        "retained_binding_ids": retained_binding_ids,
        "skipped_binding_ids": skipped_binding_ids,
        "dry_run": bool(dry_run),
    }


def _cleanup_stale_bindings_in_running_instance(
    data_dir: pathlib.Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    result = _request(
        pathlib.Path(data_dir),
        "binding/clear-stale",
        {
            "dry_run": bool(dry_run),
        },
    )
    return dict(result)


def _clear_stale_bindings(
    *,
    explicit_instance: str = "",
    dry_run: bool = False,
) -> int:
    normalized_explicit_instance = str(explicit_instance or "").strip()
    cleanup_results: list[dict[str, Any]] = []
    cleanup_failures: list[dict[str, str]] = []

    if normalized_explicit_instance:
        target = _resolve_target_instance(normalized_explicit_instance)
        if target.running_entry is not None:
            try:
                result = _cleanup_stale_bindings_in_running_instance(target.data_dir, dry_run=dry_run)
            except Exception as exc:
                cleanup_failures.append(
                    {"instance_name": target.instance_name, "mode": "control-plane", "reason": str(exc)}
                )
            else:
                cleanup_results.append({"instance_name": target.instance_name, "mode": "control-plane", **result})
        else:
            query_instance_name, query_data_dir, query_running_entry = _resolve_stale_binding_query_target()
            adapter, thread_presence_check = _build_thread_presence_checker(
                query_data_dir,
                running_entry=query_running_entry,
            )
            try:
                try:
                    result = _clear_stale_bindings_from_store(
                        target.data_dir,
                        thread_presence_check,
                        dry_run=dry_run,
                    )
                except Exception as exc:
                    cleanup_failures.append(
                        {"instance_name": target.instance_name, "mode": "local-store", "reason": str(exc)}
                    )
                else:
                    cleanup_results.append(
                        {
                            "instance_name": target.instance_name,
                            "mode": "local-store",
                            "query_instance_name": query_instance_name,
                            **result,
                        }
                    )
            finally:
                adapter.stop()
    else:
        running_entries = list_running_instances()
        if not running_entries:
            raise ValueError(
                "binding clear-stale 需要至少一个运行中的实例，以便通过 app-server 验证 thread 是否仍存在。"
            )
        running_instance_names: set[str] = set()
        for entry in running_entries:
            running_instance_names.add(str(entry.instance_name or "").strip().lower())
        stopped_instance_names = [
            str(instance_name or "").strip().lower()
            for instance_name in list_known_instance_names()
            if str(instance_name or "").strip().lower()
            and str(instance_name or "").strip().lower() not in running_instance_names
        ]
        adapter = None
        thread_presence_check = None
        query_instance_name = ""
        if stopped_instance_names:
            query_instance_name, query_data_dir, query_running_entry = _resolve_stale_binding_query_target()
            adapter, thread_presence_check = _build_thread_presence_checker(
                query_data_dir,
                running_entry=query_running_entry,
            )
        for entry in running_entries:
            instance_name = str(entry.instance_name or "").strip().lower()
            try:
                result = _cleanup_stale_bindings_in_running_instance(pathlib.Path(entry.data_dir), dry_run=dry_run)
            except Exception as exc:
                cleanup_failures.append(
                    {"instance_name": instance_name, "mode": "control-plane", "reason": str(exc)}
                )
            else:
                cleanup_results.append({"instance_name": instance_name, "mode": "control-plane", **result})

        try:
            for normalized_instance_name in stopped_instance_names:
                if thread_presence_check is None:
                    raise RuntimeError("stale binding thread presence checker was not initialized")
                paths = resolve_instance_paths(normalized_instance_name)
                try:
                    result = _clear_stale_bindings_from_store(
                        paths.data_dir,
                        thread_presence_check,
                        dry_run=dry_run,
                    )
                except Exception as exc:
                    cleanup_failures.append(
                        {
                            "instance_name": normalized_instance_name,
                            "mode": "local-store",
                            "reason": str(exc),
                        }
                    )
                    continue
                cleanup_results.append(
                    {
                        "instance_name": normalized_instance_name,
                        "mode": "local-store",
                        "query_instance_name": query_instance_name,
                        **result,
                    }
                )
        finally:
            if adapter is not None:
                adapter.stop()

    _print_stale_binding_cleanup_results(
        cleanup_results,
        cleanup_failures,
        dry_run=dry_run,
        scope_label=normalized_explicit_instance or "all known instances",
    )
    unknown_count = sum(len(item.get("unknown_threads") or []) for item in cleanup_results)
    return 1 if cleanup_failures or unknown_count else 0


def _print_stale_binding_cleanup_results(
    cleanup_results: list[dict[str, Any]],
    cleanup_failures: list[dict[str, str]],
    *,
    dry_run: bool,
    scope_label: str,
) -> None:
    action_key = "would_clear_binding_ids" if dry_run else "cleared_binding_ids"
    action_label = "would clear stale bindings" if dry_run else "cleared stale bindings"
    total_stale = 0
    total_unknown = 0
    print(f"scope: {scope_label}")
    if dry_run:
        print("mode: dry-run")
    if not cleanup_results and not cleanup_failures:
        print("instances: （无）")
        return
    for item in cleanup_results:
        binding_ids = list(item.get(action_key) or [])
        stale_thread_ids = list(item.get("stale_thread_ids") or [])
        unknown_threads = list(item.get("unknown_threads") or [])
        total_stale += len(binding_ids)
        total_unknown += len(unknown_threads)
        print(f"- {item.get('instance_name', '-')} ({item.get('mode', '-')}):")
        query_instance = str(item.get("query_instance_name", "") or "").strip()
        if query_instance:
            print(f"  query instance: {query_instance}")
        print(f"  {action_label}: {', '.join(binding_ids) or '（无）'}")
        if stale_thread_ids:
            print(f"  stale threads: {', '.join(stale_thread_ids)}")
        if unknown_threads:
            print("  unknown threads:")
            for unknown in unknown_threads:
                print(f"  - {unknown.get('thread_id', '-')}: {unknown.get('reason', '')}")
    if cleanup_failures:
        print("cleanup warnings:")
        for item in cleanup_failures:
            print(
                f"- {item.get('instance_name', '-')}"
                f" ({item.get('mode', '-')}): {item.get('reason', 'unknown error')}"
            )
    print(
        "summary: "
        f"instances={len(cleanup_results)} "
        f"{'would_clear' if dry_run else 'cleared'}={total_stale} "
        f"unknown_threads={total_unknown} "
        f"cleanup_failed={len(cleanup_failures)}"
    )


def _send_binding_prompt(
    data_dir: pathlib.Path,
    *,
    binding_id: str,
    text: str,
    actor_open_id: str = "",
    synthetic_source: str = "",
    display_mode: str = "silent",
    instance_name: str = "",
) -> int:
    result = _request(
        data_dir,
        "binding/submit-prompt",
        {
            "binding_id": binding_id,
            "text": text,
            "actor_open_id": actor_open_id,
            "synthetic_source": synthetic_source,
            "display_mode": display_mode,
        },
    )
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"binding: {result['binding_id']}")
    print(f"thread: {result.get('thread_id') or '-'}")
    print(f"display_mode: {result.get('display_mode') or 'silent'}")
    if result.get("synthetic_source"):
        print(f"synthetic_source: {result['synthetic_source']}")
    if result.get("started"):
        print("started: yes")
        print(f"turn_id: {result.get('turn_id') or '-'}")
        return 0
    if result.get("queued"):
        print("started: no")
        print("queued: yes")
        print(f"queue_position: {int(result.get('queue_position') or 0)}")
        return 0
    print("started: no")
    if result.get("reason_code"):
        print(f"reason code: {result['reason_code']}")
    if result.get("reason"):
        print(f"reason: {result['reason']}")
    return 1


def _print_thread_status(data_dir: pathlib.Path, target_params: dict[str, str], *, instance_name: str = "") -> int:
    snapshot = _request(data_dir, "thread/status", target_params)
    live_runtime_owner, live_runtime_holders = _live_runtime_summary(snapshot)
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"thread: {snapshot['thread_id']} {snapshot['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(snapshot['working_dir'])}")
    print(f"current instance backend thread status: {snapshot['backend_thread_status']}")
    print(f"backend running turn: {'yes' if snapshot['backend_running_turn'] else 'no'}")
    print(f"live runtime owner: {live_runtime_owner}")
    print(f"live runtime holders: {', '.join(live_runtime_holders) or '（无）'}")
    print(f"bound bindings: {', '.join(snapshot['bound_binding_ids']) or '（无）'}")
    print(f"attached bindings: {', '.join(snapshot['attached_binding_ids']) or '（无）'}")
    print(f"detached bindings: {', '.join(snapshot['detached_binding_ids']) or '（无）'}")
    print(f"current-instance interaction owner: {snapshot['interaction_owner']['label']}")
    availability = "available" if snapshot["detach_available"] else "blocked"
    print(f"detach: {availability}")
    if snapshot["detach_reason_code"]:
        print(f"detach reason code: {snapshot['detach_reason_code']}")
    if snapshot["detach_reason"]:
        print(f"detach reason: {snapshot['detach_reason']}")
    return 0


def _print_thread_bindings(data_dir: pathlib.Path, target_params: dict[str, str]) -> int:
    result = _request(data_dir, "thread/bindings", target_params)
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    bindings = result.get("bindings") or []
    if not bindings:
        print("bindings: （无）")
        return 0
    print("bindings:")
    for item in bindings:
        print(f"- {item['binding_id']} [{item['feishu_runtime_state']}]")
    return 0


def _print_thread_goal_result(result: dict[str, Any], *, instance_name: str = "", note: str = "") -> int:
    goal = result.get("goal")
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    if note:
        print(f"note: {note}")
    if not isinstance(goal, dict):
        print("goal: （无）")
        return 0
    objective = str(goal.get("objective", "") or "").strip()
    status = str(goal.get("status", "") or "").strip()
    print(f"objective: {objective or '-'}")
    print(f"status: {status or '-'} ({_goal_status_label(status)})")
    token_budget = goal.get("token_budget")
    print(f"token budget: {token_budget if token_budget is not None else '-'}")
    print(f"tokens used: {int(goal.get('tokens_used') or 0)}")
    print(f"time used: {int(goal.get('time_used_seconds') or 0)}s")
    print(f"created_at: {_format_goal_ts_seconds(goal.get('created_at'))}")
    print(f"updated_at: {_format_goal_ts_seconds(goal.get('updated_at'))}")
    return 0


def _print_thread_goal(data_dir: pathlib.Path, target_params: dict[str, str], *, instance_name: str = "") -> int:
    result = _request(data_dir, "thread/goal", target_params)
    return _print_thread_goal_result(result, instance_name=instance_name)


def _set_thread_goal(
    data_dir: pathlib.Path,
    target_params: dict[str, str],
    *,
    objective: str = "",
    status: str = "",
    instance_name: str = "",
) -> int:
    normalized_objective = str(objective or "").strip()
    normalized_status = str(status or "").strip()
    if not normalized_objective and not normalized_status:
        raise ValueError("thread goal set 至少需要 `--objective` 或 `--status`。")
    params: dict[str, Any] = dict(target_params)
    if normalized_objective:
        params["objective"] = normalized_objective
    if normalized_status:
        params["status"] = normalized_status
    result = _request(
        data_dir,
        "thread/goal/set",
        params,
    )
    return _print_thread_goal_result(result, instance_name=instance_name, note="当前 thread goal 已更新。")


def _clear_thread_goal(data_dir: pathlib.Path, target_params: dict[str, str], *, instance_name: str = "") -> int:
    result = _request(data_dir, "thread/goal/clear", target_params)
    note = "当前 thread goal 已清除。" if result.get("cleared") else "当前 thread 原本就没有 goal。"
    return _print_thread_goal_result(result, instance_name=instance_name, note=note)


def _print_thread_list(
    data_dir: pathlib.Path,
    *,
    scope: str,
    cwd: str,
    running_entry: InstanceRegistryEntry | None = None,
) -> int:
    adapter, cfg, app_server_url = _remote_adapter(data_dir, running_entry=running_entry)
    del app_server_url
    try:
        limit = int(cfg.get("thread_list_query_limit", 100))
        threads = (
            list_current_dir_threads(adapter, cwd=cwd, limit=limit)
            if scope == "cwd"
            else list_global_threads(adapter, limit=limit)
        )
    finally:
        adapter.stop()
    if not threads:
        print("当前没有可见线程。")
        return 0
    rows: list[list[str]] = []
    for item in threads:
        rows.append(
            [
                item.thread_id,
                str(item.model_provider or "-"),
                display_path(item.cwd),
                item.title,
            ]
        )
    for line in _render_table(["THREAD_ID", "PROVIDER", "CWD", "TITLE"], rows):
        print(line)
    return 0


def _detach_thread(data_dir: pathlib.Path, target_params: dict[str, str]) -> int:
    result = _request(data_dir, "thread/detach", target_params)
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"detached bindings: {', '.join(result['detached_binding_ids']) or '（无）'}")
    print(f"backend thread status: {result['backend_thread_status']}")
    if result.get("detach_reason_code"):
        print(f"detach reason code: {result['detach_reason_code']}")
    if result["already_detached"]:
        print("note: Feishu push for this thread was already detached.")
    elif result["backend_still_loaded"]:
        print("note: backend is still loaded; external subscribers are still attached, typically local fcodex.")
    else:
        print("note: Feishu push for this thread has been detached while keeping bindings intact.")
    return 0


def _attach_thread(data_dir: pathlib.Path, target_params: dict[str, str]) -> int:
    result = _request(data_dir, "thread/attach", target_params)
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    print(f"attached bindings: {', '.join(result.get('attached_binding_ids') or []) or '（无）'}")
    if result.get("already_attached_binding_ids"):
        print(f"already attached bindings: {', '.join(result.get('already_attached_binding_ids') or [])}")
    if not result.get("changed"):
        print("note: 当前 thread 没有需要恢复的 detached 推送。")
    return 0


def _same_path(left: pathlib.Path | str, right: pathlib.Path | str) -> bool:
    left_path = pathlib.Path(left).expanduser().resolve(strict=False)
    right_path = pathlib.Path(right).expanduser().resolve(strict=False)
    return left_path == right_path


def _clear_archived_thread_bindings_from_store(
    data_dir: pathlib.Path,
    thread_id: str,
    *,
    dry_run: bool = False,
) -> list[str]:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return []
    store = ChatBindingStore(pathlib.Path(data_dir))
    interaction_leases = InteractionLeaseStore(pathlib.Path(data_dir))
    cleared_binding_ids: list[str] = []
    for binding, state in sorted(store.load_all().items(), key=lambda item: format_binding_id(item[0])):
        if str(state.get("current_thread_id", "") or "").strip() != normalized_thread_id:
            continue
        if not dry_run:
            store.clear(binding)
            interaction_leases.release(
                normalized_thread_id,
                make_feishu_interaction_holder(binding[0], binding[1], owner_pid=0),
            )
        cleared_binding_ids.append(format_binding_id(binding))
    return cleared_binding_ids


def _cleanup_archived_thread_bindings_in_running_instance(
    data_dir: pathlib.Path,
    thread_id: str,
    *,
    dry_run: bool,
) -> list[str]:
    result = _request(
        pathlib.Path(data_dir),
        "thread/clear-archived-bindings",
        {
            "thread_id": thread_id,
            "dry_run": bool(dry_run),
        },
    )
    return list(result.get("would_clear_binding_ids") or result.get("cleared_binding_ids") or [])


def _cleanup_archived_thread_bindings_in_scope(
    thread_id: str,
    *,
    explicit_instance: str = "",
    exclude_instance_name: str = "",
    exclude_data_dir: pathlib.Path | None = None,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return [], []

    normalized_exclude_instance = str(exclude_instance_name or "").strip().lower()
    normalized_exclude_data_dir = pathlib.Path(exclude_data_dir) if exclude_data_dir is not None else None
    normalized_explicit_instance = str(explicit_instance or "").strip()
    cleanup_results: list[dict[str, Any]] = []
    cleanup_failures: list[dict[str, str]] = []
    running_instance_names: set[str] = set()

    if normalized_explicit_instance:
        target = _resolve_target_instance(normalized_explicit_instance)
        try:
            if target.running_entry is not None:
                cleared_binding_ids = _cleanup_archived_thread_bindings_in_running_instance(
                    target.data_dir,
                    normalized_thread_id,
                    dry_run=dry_run,
                )
                mode = "control-plane"
            else:
                cleared_binding_ids = _clear_archived_thread_bindings_from_store(
                    target.data_dir,
                    normalized_thread_id,
                    dry_run=dry_run,
                )
                mode = "local-store"
        except Exception as exc:
            return [], [
                {
                    "instance_name": target.instance_name,
                    "mode": "control-plane" if target.running_entry is not None else "local-store",
                    "reason": str(exc),
                }
            ]
        return [
            {
                "instance_name": target.instance_name,
                "mode": mode,
                "cleared_binding_ids": cleared_binding_ids,
            }
        ], []

    for entry in list_running_instances():
        instance_name = str(entry.instance_name or "").strip().lower()
        running_instance_names.add(instance_name)
        entry_data_dir = pathlib.Path(entry.data_dir)
        if instance_name == normalized_exclude_instance:
            continue
        if normalized_exclude_data_dir is not None and _same_path(entry_data_dir, normalized_exclude_data_dir):
            continue
        try:
            cleared_binding_ids = _cleanup_archived_thread_bindings_in_running_instance(
                entry_data_dir,
                normalized_thread_id,
                dry_run=dry_run,
            )
        except Exception as exc:
            cleanup_failures.append(
                {
                    "instance_name": instance_name,
                    "mode": "control-plane",
                    "reason": str(exc),
                }
            )
            continue
        cleanup_results.append(
            {
                "instance_name": instance_name,
                "mode": "control-plane",
                "cleared_binding_ids": cleared_binding_ids,
            }
        )

    for instance_name in list_known_instance_names():
        normalized_instance_name = str(instance_name or "").strip().lower()
        if (
            not normalized_instance_name
            or normalized_instance_name == normalized_exclude_instance
            or normalized_instance_name in running_instance_names
        ):
            continue
        paths = resolve_instance_paths(normalized_instance_name)
        if normalized_exclude_data_dir is not None and _same_path(paths.data_dir, normalized_exclude_data_dir):
            continue
        try:
            cleared_binding_ids = _clear_archived_thread_bindings_from_store(
                paths.data_dir,
                normalized_thread_id,
                dry_run=dry_run,
            )
        except Exception as exc:
            cleanup_failures.append(
                {
                    "instance_name": normalized_instance_name,
                    "mode": "local-store",
                    "reason": str(exc),
                }
            )
            continue
        cleanup_results.append(
            {
                "instance_name": normalized_instance_name,
                "mode": "local-store",
                "cleared_binding_ids": cleared_binding_ids,
            }
        )

    return cleanup_results, cleanup_failures


def _cleanup_archived_thread_bindings_in_other_instances(
    thread_id: str,
    *,
    target_instance_name: str,
    target_data_dir: pathlib.Path,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    return _cleanup_archived_thread_bindings_in_scope(
        thread_id,
        exclude_instance_name=target_instance_name,
        exclude_data_dir=target_data_dir,
        dry_run=dry_run,
    )


def _resolve_archived_thread_listing_target(
    explicit_instance: str = "",
) -> tuple[str, pathlib.Path, InstanceRegistryEntry]:
    normalized_explicit_instance = str(explicit_instance or "").strip()
    if normalized_explicit_instance:
        target = _resolve_target_instance(normalized_explicit_instance)
        if target.running_entry is None:
            raise ValueError(
                "thread clear-archived-bindings --all 需要目标实例正在运行，"
                "以便查询上游 archived thread 列表；若已知 thread id，请改用 --thread-id。"
            )
        return target.instance_name, target.data_dir, target.running_entry

    running_instances = list_running_instances()
    if not running_instances:
        raise ValueError(
            "thread clear-archived-bindings --all 需要至少一个运行中的实例，"
            "以便查询上游 archived thread 列表；若已知 thread id，请改用 --thread-id。"
        )
    selected = sorted(
        running_instances,
        key=lambda item: (0 if str(item.instance_name or "").strip().lower() == "default" else 1, item.instance_name),
    )[0]
    return selected.instance_name, pathlib.Path(selected.data_dir), selected


def _list_archived_thread_ids_from_running_instance(
    data_dir: pathlib.Path,
    *,
    running_entry: InstanceRegistryEntry,
    page_size: int = 100,
) -> list[str]:
    adapter, _cfg, _app_server_url = _remote_adapter(pathlib.Path(data_dir), running_entry=running_entry)
    seen_thread_ids: set[str] = set()
    archived_thread_ids: list[str] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    try:
        while True:
            page, cursor = adapter.list_threads(
                limit=page_size,
                cursor=cursor,
                sort_key="updated_at",
                model_providers=[],
                archived=True,
            )
            for thread in page:
                thread_id = str(thread.thread_id or "").strip()
                if not thread_id or thread_id in seen_thread_ids:
                    continue
                seen_thread_ids.add(thread_id)
                archived_thread_ids.append(thread_id)
            if not cursor:
                break
            if cursor in seen_cursors:
                raise RuntimeError(f"thread/list archived pagination returned a repeated cursor: {cursor}")
            seen_cursors.add(cursor)
    finally:
        adapter.stop()
    return archived_thread_ids


def _print_archive_cleanup_results(
    cleanup_results: list[dict[str, Any]],
    cleanup_failures: list[dict[str, str]],
    *,
    dry_run: bool = False,
    scope_label: str = "in other instances",
) -> None:
    non_empty_results = [item for item in cleanup_results if item.get("cleared_binding_ids")]
    action = "would clear bindings" if dry_run else "cleared bindings"
    header = f"{action} {scope_label}:" if scope_label else f"{action}:"
    if non_empty_results:
        print(header)
        for item in non_empty_results:
            print(
                f"- {item.get('instance_name', '-')}"
                f" ({item.get('mode', '-')}): "
                + (", ".join(item.get("cleared_binding_ids") or []) or "（无）")
            )
    elif cleanup_results:
        print(f"{header} （无）")
    if cleanup_failures:
        print("cleanup warnings:")
        for item in cleanup_failures:
            print(
                f"- {item.get('instance_name', '-')}"
                f" ({item.get('mode', '-')}): {item.get('reason', 'unknown error')}"
            )


def _clear_all_archived_thread_bindings(
    *,
    explicit_instance: str = "",
    dry_run: bool = False,
) -> int:
    query_instance_name, query_data_dir, query_running_entry = _resolve_archived_thread_listing_target(explicit_instance)
    archived_thread_ids = _list_archived_thread_ids_from_running_instance(
        query_data_dir,
        running_entry=query_running_entry,
    )
    print(f"archived query instance: {query_instance_name}")
    print(f"archived threads: {len(archived_thread_ids)}")
    print(f"scope: {explicit_instance or 'all known instances'}")
    if dry_run:
        print("mode: dry-run")
    if not archived_thread_ids:
        print("bindings: （无）")
        return 0

    changed_thread_count = 0
    cleared_binding_count = 0
    cleanup_failure_count = 0
    for thread_id in archived_thread_ids:
        cleanup_results, cleanup_failures = _cleanup_archived_thread_bindings_in_scope(
            thread_id,
            explicit_instance=explicit_instance,
            dry_run=dry_run,
        )
        thread_cleared_count = sum(len(item.get("cleared_binding_ids") or []) for item in cleanup_results)
        if thread_cleared_count or cleanup_failures:
            print()
            print(f"thread: {thread_id}")
            _print_archive_cleanup_results(
                cleanup_results,
                cleanup_failures,
                dry_run=dry_run,
                scope_label="",
            )
        if thread_cleared_count:
            changed_thread_count += 1
            cleared_binding_count += thread_cleared_count
        cleanup_failure_count += len(cleanup_failures)

    action = "would_clear_bindings" if dry_run else "cleared_bindings"
    print()
    print(
        "summary: "
        f"archived_threads={len(archived_thread_ids)} "
        f"threads_with_bindings={changed_thread_count} "
        f"{action}={cleared_binding_count} "
        f"cleanup_failed={cleanup_failure_count}"
    )
    return 1 if cleanup_failure_count else 0


def _clear_archived_thread_bindings(
    thread_id: str = "",
    *,
    all_archived: bool = False,
    explicit_instance: str = "",
    dry_run: bool = False,
) -> int:
    normalized_thread_id = str(thread_id or "").strip()
    if bool(normalized_thread_id) == bool(all_archived):
        raise ValueError("thread clear-archived-bindings 必须且只能提供 --thread-id 或 --all。")
    if all_archived:
        return _clear_all_archived_thread_bindings(
            explicit_instance=explicit_instance,
            dry_run=dry_run,
        )
    cleanup_results, cleanup_failures = _cleanup_archived_thread_bindings_in_scope(
        normalized_thread_id,
        explicit_instance=explicit_instance,
        dry_run=dry_run,
    )
    print(f"thread: {normalized_thread_id}")
    print(f"scope: {explicit_instance or 'all known instances'}")
    if dry_run:
        print("mode: dry-run")
    if not cleanup_results and not cleanup_failures:
        print("instances: （无）")
        return 0
    _print_archive_cleanup_results(
        cleanup_results,
        cleanup_failures,
        dry_run=dry_run,
        scope_label="",
    )
    return 1 if cleanup_failures else 0


def _archive_thread(data_dir: pathlib.Path, target_params: dict[str, str], *, instance_name: str = "") -> int:
    result = _request(data_dir, "thread/archive", target_params)
    cleanup_results, cleanup_failures = _cleanup_archived_thread_bindings_in_other_instances(
        str(result["thread_id"]),
        target_instance_name=instance_name,
        target_data_dir=data_dir,
    )
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    print(f"cleared bindings in this instance: {', '.join(result.get('cleared_binding_ids') or []) or '（无）'}")
    _print_archive_cleanup_results(cleanup_results, cleanup_failures)
    print("note: 归档完成；该 thread 会从常规列表中隐藏，不是硬删除。")
    print("note: 已同时清理其他可达运行实例与已知非运行实例里指向该 thread 的本地 bindings。")
    return 1 if cleanup_failures else 0


def _archive_threads(thread_ids: list[str], *, explicit_instance: str = "") -> int:
    normalized_thread_ids = [str(item or "").strip() for item in thread_ids if str(item or "").strip()]
    if not normalized_thread_ids:
        raise ValueError("thread archive 缺少目标。")
    if len(normalized_thread_ids) == 1:
        thread_id = normalized_thread_ids[0]
        target = _resolve_target_instance(
            explicit_instance or None,
            preferred_running_instance="" if explicit_instance else _lease_owner_instance(thread_id),
        )
        return _archive_thread(
            target.data_dir,
            {"thread_id": thread_id},
            instance_name=target.instance_name,
        )

    success_count = 0
    failure_count = 0
    cleanup_failure_count = 0
    resolved_explicit_target = _resolve_target_instance(explicit_instance) if explicit_instance else None
    print(f"batch archive: total={len(normalized_thread_ids)}")
    for index, requested_thread_id in enumerate(normalized_thread_ids, start=1):
        print(f"[{index}/{len(normalized_thread_ids)}] thread: {requested_thread_id or '-'}")
        try:
            target = resolved_explicit_target or _resolve_target_instance(
                None,
                preferred_running_instance=_lease_owner_instance(requested_thread_id),
            )
        except ValueError as exc:
            failure_count += 1
            print("status: failed")
            print(f"reason: {exc}")
            if index != len(normalized_thread_ids):
                print()
            continue
        print(f"instance: {target.instance_name}")
        try:
            result = _request(target.data_dir, "thread/archive", {"thread_id": requested_thread_id})
        except ServiceControlError as exc:
            failure_count += 1
            print("status: failed")
            print(f"reason: {exc}")
        else:
            success_count += 1
            print("status: archived")
            print(f"resolved thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
            print(f"working_dir: {display_path(result['working_dir'])}")
            print(
                "cleared bindings in this instance: "
                + (", ".join(result.get("cleared_binding_ids") or []) or "（无）")
            )
            cleanup_results, cleanup_failures = _cleanup_archived_thread_bindings_in_other_instances(
                str(result["thread_id"]),
                target_instance_name=target.instance_name,
                target_data_dir=target.data_dir,
            )
            _print_archive_cleanup_results(cleanup_results, cleanup_failures)
            cleanup_failure_count += len(cleanup_failures)
        if index != len(normalized_thread_ids):
            print()
    print()
    print(f"summary: archived={success_count} failed={failure_count} cleanup_failed={cleanup_failure_count}")
    print("note: 每个 thread 都按现有单线程 archive 语义独立路由、独立执行。")
    print("note: archive 成功后会清理其他可达运行实例与已知非运行实例里指向该 thread 的本地 bindings。")
    return 0 if failure_count == 0 and cleanup_failure_count == 0 else 1


def _send_thread_image(
    data_dir: pathlib.Path,
    target_params: dict[str, str],
    *,
    local_path: str,
    instance_name: str = "",
) -> int:
    result = _request(
        data_dir,
        "thread/send-image",
        {
            **target_params,
            "local_path": local_path,
        },
    )
    if instance_name:
        print(f"instance: {instance_name}")
    print(f"thread: {result['thread_id']} {result['thread_title'] or ''}".rstrip())
    print(f"working_dir: {display_path(result['working_dir'])}")
    print(f"local_path: {display_path(result['local_path'])}")
    print(f"delivered bindings: {', '.join(result['delivered_binding_ids']) or '（无）'}")
    if result.get("failed_binding_ids"):
        print(f"failed bindings: {', '.join(result['failed_binding_ids'])}")
        print("note: 图片只完成部分投递；若重试，已成功的 binding 可能会再次收到同一张图片。")
        return 1
    return 0


def _list_running_instances() -> int:
    instances = list_running_instances()
    if not instances:
        print("当前没有运行中的实例。")
        return 0
    rows: list[list[str]] = []
    for item in instances:
        control = item.control_endpoint
        app_server = resolve_running_instance_app_server_url(item) or "-"
        rows.append([item.instance_name, str(item.owner_pid), control, app_server])
    for line in _render_table(["INSTANCE", "PID", "CONTROL", "APP_SERVER"], rows):
        print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu-codexctl",
        description=(
            "本地查看 / 管理面：查看运行中的 feishu-codex service、binding、thread 与实例。\n\n"
            "说明：\n"
            "- `feishu-codexctl` 是本地查看 / 管理面，不是第二个 Codex 前端\n"
            "- 命名实例必须先显式 `feishu-codex instance create <name>`；这里不会隐式创建\n"
            "- 除 `instance list` 外，其余命令都可加 `--instance <name>`；显式值优先\n"
            "- 若未显式指定，则按 preferred-running（若有）/ unique-running / default-running / current-instance-paths 规则解析；多实例仍有歧义时必须显式指定\n"
            "- `binding clear` / `clear-all` 清的是 Feishu 本地 bookmark，不删除 thread，也不等于 `detach`\n"
            "- `thread list` 默认列当前目录线程，也支持 `--scope global`\n"
        ),
        epilog=(
            "常用命令:\n"
            "  feishu-codexctl service status\n"
            "  feishu-codexctl service reset-backend\n"
            "  feishu-codexctl service attach\n"
            "  feishu-codexctl instance list\n"
            "  feishu-codexctl binding list\n"
            "  feishu-codexctl binding status <binding_id>\n"
            "  feishu-codexctl binding attach <binding_id>\n"
            "  feishu-codexctl binding detach <binding_id>\n"
            "  feishu-codexctl binding clear-stale --dry-run\n"
            "  feishu-codexctl prompt send --binding-id <binding_id> --text '继续执行'\n"
            "  feishu-codexctl thread list --scope cwd\n"
            "  feishu-codexctl thread status --thread-id <id>\n"
            "  feishu-codexctl thread goal --thread-id <id>\n"
            "  feishu-codexctl thread archive --thread-name demo\n"
            "  feishu-codexctl thread archive --thread-id <id-1> --thread-id <id-2>\n"
            "  feishu-codexctl thread clear-archived-bindings --thread-id <id> --dry-run\n"
            "  feishu-codexctl thread clear-archived-bindings --all --dry-run\n"
            "  feishu-codexctl thread attach --thread-id <id>\n"
            "  feishu-codexctl thread detach --thread-name <name>\n"
            "  feishu-codexctl image send --thread-id <id> --path ./diagram.png\n"
            "\n"
            "多实例:\n"
            "  feishu-codexctl --instance corp-a service status\n"
            "  feishu-codexctl --instance corp-a thread status --thread-name demo\n"
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"feishu-codexctl {__version__}")
    parser.add_argument(
        "--instance",
        help=(
            "目标实例；显式值优先。命名实例必须先 `feishu-codex instance create <name>`。"
            "省略时按运行中实例解析，必要时必须显式指定。仅 `instance list` 不使用这个参数。"
        ),
    )
    subparsers = parser.add_subparsers(dest="resource", required=True, title="resources", metavar="resource")

    instance = subparsers.add_parser(
        "instance",
        help="查看运行中的实例注册表。",
        description="实例发现面。当前只提供 `list`，用于查看本机运行中的实例及其控制面地址。",
        formatter_class=_HelpFormatter,
    )
    instance_sub = instance.add_subparsers(dest="action", required=True, title="instance commands", metavar="instance-command")
    instance_sub.add_parser(
        "list",
        help="列出运行中的实例。",
        description="列出本机运行中的实例、owner pid、control endpoint 与 app-server 地址。",
        formatter_class=_HelpFormatter,
    )

    service = subparsers.add_parser(
        "service",
        help="查看目标实例的服务状态。",
        description="服务查看面。用于确认目标实例是否在运行，以及当前 control plane / app-server 发现状态。",
        formatter_class=_HelpFormatter,
    )
    service_sub = service.add_subparsers(dest="action", required=True, title="service commands", metavar="service-command")
    service_sub.add_parser(
        "status",
        help="查看服务运行态。",
        description="查看目标实例当前服务运行态、control endpoint、app-server 地址以及 binding / thread 统计。",
        formatter_class=_HelpFormatter,
    )
    service_reset = service_sub.add_parser(
        "reset-backend",
        help="重置当前实例 backend，不重启 feishu-codex service。",
        description=(
            "重置当前实例 backend，不重启 feishu-codex service 进程。\n"
            "普通 reset 只在确认当前实例没有待处理工作时允许；如需打断当前实例里的运行中 turn / 审批 / 输入请求，可加 `--force`。"
        ),
        formatter_class=_HelpFormatter,
    )
    service_reset.add_argument(
        "--force",
        action="store_true",
        help="强制重置 backend，允许打断当前实例里正在进行的工作。",
    )
    service_sub.add_parser(
        "attach",
        help="恢复当前实例下 detached 的 Feishu 推送。",
        description="恢复当前实例下全部 detached 的 Feishu binding 推送；若部分 thread 被其他实例占用，会逐项报告 blocked 原因。",
        formatter_class=_HelpFormatter,
    )

    binding = subparsers.add_parser(
        "binding",
        help="查看或清理目标实例里的 Feishu binding。",
        description=(
            "Binding 管理面。\n"
            "`clear` / `clear-all` / `clear-stale` 清的是 Feishu 本地 bookmark，不删除 thread，也不等于 `detach`。"
        ),
        formatter_class=_HelpFormatter,
    )
    binding_sub = binding.add_subparsers(dest="action", required=True, title="binding commands", metavar="binding-command")
    binding_sub.add_parser(
        "list",
        help="列出当前实例可见 binding。",
        description="列出当前实例可见的 binding、运行态、关联 thread 与 cwd。",
        formatter_class=_HelpFormatter,
    )
    binding_status = binding_sub.add_parser(
        "status",
        help="查看单个 binding 详情。",
        description="查看单个 binding 的 chat、thread、runtime 与下一次发言可否被接受。",
        formatter_class=_HelpFormatter,
    )
    binding_status.add_argument("binding_id", help="目标 binding id。")
    binding_clear = binding_sub.add_parser(
        "clear",
        help="清除单个 binding bookmark。",
        description="清除单个 Feishu binding bookmark；不会删除 thread，也不会执行 detach。",
        formatter_class=_HelpFormatter,
    )
    binding_clear.add_argument("binding_id", help="要清除的 binding id。")
    binding_attach = binding_sub.add_parser(
        "attach",
        help="恢复单个 binding 的飞书推送。",
        description="让目标 binding 从 detached 恢复到 attached；不启动 turn，只恢复推送接收能力。",
        formatter_class=_HelpFormatter,
    )
    binding_attach.add_argument("binding_id", help="要恢复的 binding id。")
    binding_detach = binding_sub.add_parser(
        "detach",
        help="暂停单个 binding 的飞书推送。",
        description="让目标 binding 从 attached 变为 detached；保留 bookmark，不删除 thread。",
        formatter_class=_HelpFormatter,
    )
    binding_detach.add_argument("binding_id", help="要暂停的 binding id。")
    binding_sub.add_parser(
        "clear-all",
        help="清除当前实例下全部 binding bookmark。",
        description="清除当前实例下全部 Feishu binding bookmark；不会删除 thread，也不会执行 detach。",
        formatter_class=_HelpFormatter,
    )
    binding_clear_stale = binding_sub.add_parser(
        "clear-stale",
        help="清理指向已不可读取 thread 的 stale binding bookmark。",
        description=(
            "扫描本项目本地 binding，并通过运行中的 app-server 验证其 thread 是否仍可读取。\n"
            "明确不可读取的 thread 视为 stale 并清理对应 bookmark；查询失败或无法判断时 fail-closed 保留。\n"
            "默认扫描所有运行中实例和已知非运行实例；传全局 `--instance <name>` 时只作用于该实例。"
        ),
        formatter_class=_HelpFormatter,
    )
    binding_clear_stale.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览会清理哪些 binding，不修改本地数据。",
    )

    prompt = subparsers.add_parser(
        "prompt",
        help="向某个 binding 合成提交一条新 prompt。",
        description=(
            "Prompt 注入管理面。\n"
            "当前只提供 `send`：直接通过正在运行的 feishu-codex service，"
            "向目标 binding 对应的 thread 合成发起一轮新 prompt。"
        ),
        formatter_class=_HelpFormatter,
    )
    prompt_sub = prompt.add_subparsers(dest="action", required=True, title="prompt commands", metavar="prompt-command")
    prompt_send = prompt_sub.add_parser(
        "send",
        help="向目标 binding 发起一轮 synthetic prompt。",
        description=(
            "向目标 binding 发起一轮 synthetic prompt。\n"
            "这是 binding-scoped 动作；真正执行仍会经过 running-turn / attach / interaction 等保护，"
            "不可写时 fail-closed 返回拒绝原因。"
        ),
        formatter_class=_HelpFormatter,
    )
    prompt_send.add_argument("--binding-id", required=True, help="目标 binding id。")
    prompt_text_group = prompt_send.add_mutually_exclusive_group(required=True)
    prompt_text_group.add_argument("--text", help="要提交的 prompt 文本。")
    prompt_text_group.add_argument("--text-file", help="从本地 UTF-8 文本文件读取 prompt。")
    prompt_send.add_argument(
        "--synthetic-source",
        default="",
        help="可选 synthetic source 标签，例如 `schedule`。",
    )
    prompt_send.add_argument(
        "--display-mode",
        choices=("silent", "announce"),
        default="silent",
        help="是否先向目标聊天发送一条触发说明。",
    )
    prompt_send.add_argument(
        "--actor-open-id",
        default="",
        help="可选 actor_open_id；主要供 group/shared binding 的高级场景使用。",
    )

    thread = subparsers.add_parser(
        "thread",
        help="查看或管理 thread。",
        description=(
            "Thread 管理面。\n"
            "- `list` 默认列当前目录线程；也支持 `--scope global`\n"
            "- 其他 thread 子命令必须按各自帮助显式指定目标 thread\n"
            "- `goal` 是 thread-scoped 的本地调试 / 运维面，默认查看，也支持 set/clear\n"
            "- 所有实例共享同一套 persisted thread 发现面；实例差异主要体现在 live runtime 持有"
        ),
        formatter_class=_HelpFormatter,
    )
    thread_sub = thread.add_subparsers(dest="action", required=True, title="thread commands", metavar="thread-command")
    thread_list = thread_sub.add_parser(
        "list",
        help="列出可见 thread。",
        description="列出 persisted thread。默认按当前目录过滤，也支持 `--scope global` 查看全局线程。",
        formatter_class=_HelpFormatter,
    )
    thread_list.add_argument("--scope", choices=("cwd", "global"), default="cwd", help="列线程时使用的作用域。")
    thread_list.add_argument("--cwd", default="", help="当 `--scope cwd` 时使用的目录；省略时取当前 shell 目录。")
    thread_status = thread_sub.add_parser(
        "status",
        help="查看单个 thread 详情。",
        description="查看单个 thread 的 backend 状态、绑定关系与 detach 可用性。",
        formatter_class=_HelpFormatter,
    )
    thread_status_target = thread_status.add_mutually_exclusive_group(required=True)
    thread_status_target.add_argument("--thread-id", help="目标 thread id。")
    thread_status_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_bindings = thread_sub.add_parser(
        "bindings",
        help="查看某个 thread 关联的 binding。",
        description="查看某个 thread 当前关联的 binding 列表。",
        formatter_class=_HelpFormatter,
    )
    thread_bindings_target = thread_bindings.add_mutually_exclusive_group(required=True)
    thread_bindings_target.add_argument("--thread-id", help="目标 thread id。")
    thread_bindings_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_goal = thread_sub.add_parser(
        "goal",
        help="查看或调试某个 thread 的 goal。",
        description=(
            "Thread goal 调试面。\n"
            "默认直接查看当前 goal，也支持 `show` / `set` / `clear`。\n"
            "其中 `set --status active|paused` 只是 thread-scoped 的 persisted goal 改写，"
            "不是 runtime resume / pause 命令；是否立即继续运行，仍取决于 thread 当前是否 loaded"
            " 以及 loaded 后是否 idle。\n"
            "这是本地 CLI 调试 / 运维面，直接经由 service control plane 调用 goal RPC。"
        ),
        formatter_class=_HelpFormatter,
    )
    thread_goal_target = thread_goal.add_mutually_exclusive_group(required=False)
    thread_goal_target.add_argument("--thread-id", help="目标 thread id。")
    thread_goal_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_goal_sub = thread_goal.add_subparsers(dest="goal_action", required=False, title="goal commands", metavar="goal-command")
    thread_goal.set_defaults(goal_action="show")
    thread_goal_show = thread_goal_sub.add_parser(
        "show",
        help="查看某个 thread 当前 goal。",
        description="查看某个 thread 当前 goal；等价于省略 `show` 直接执行 `thread goal`。",
        formatter_class=_HelpFormatter,
    )
    thread_goal_show_target = thread_goal_show.add_mutually_exclusive_group(required=True)
    thread_goal_show_target.add_argument("--thread-id", help="目标 thread id。")
    thread_goal_show_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_goal_set = thread_goal_sub.add_parser(
        "set",
        help="设置或调试某个 thread 的 goal。",
        description="设置或调试某个 thread 的 goal；至少提供 `--objective` 或 `--status` 之一。",
        formatter_class=_HelpFormatter,
    )
    thread_goal_set_target = thread_goal_set.add_mutually_exclusive_group(required=True)
    thread_goal_set_target.add_argument("--thread-id", help="目标 thread id。")
    thread_goal_set_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_goal_set.add_argument("--objective", default="", help="新的 goal objective。")
    thread_goal_set.add_argument(
        "--status",
        choices=("active", "paused"),
        default="",
        help="可选 persisted goal 状态；当前只暴露 `active|paused` 这两个本地调试用状态改写。",
    )
    thread_goal_clear = thread_goal_sub.add_parser(
        "clear",
        help="清除某个 thread 当前 goal。",
        description="清除某个 thread 当前 goal。",
        formatter_class=_HelpFormatter,
    )
    thread_goal_clear_target = thread_goal_clear.add_mutually_exclusive_group(required=True)
    thread_goal_clear_target.add_argument("--thread-id", help="目标 thread id。")
    thread_goal_clear_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_archive = thread_sub.add_parser(
        "archive",
        help="归档一个或多个 thread，并清理指向它们的本地 bindings。",
        description=(
            "归档目标 thread，使其从常规列表中隐藏，而不是硬删除。\n"
            "可重复提供 `--thread-id` 做批量归档；批量时每个 thread 都独立按当前单线程语义路由并执行。\n"
            "归档成功后，会清理当前目标实例、其他可达运行实例，以及已知非运行实例里指向该 thread 的 bindings。"
        ),
        formatter_class=_HelpFormatter,
    )
    thread_archive.add_argument(
        "--thread-id",
        dest="thread_ids",
        action="append",
        default=[],
        help="目标 thread id。可重复提供以批量归档。",
    )
    thread_archive.add_argument(
        "--thread-name",
        help="目标 thread 名称。仅单线程归档时可用，不能与 `--thread-id` 连用。",
    )
    thread_clear_archived = thread_sub.add_parser(
        "clear-archived-bindings",
        help="清理已归档 thread 残留的本地 bindings。",
        description=(
            "只清理本项目本地 binding bookmark，不调用上游 Codex archive。\n"
            "必须显式选择 `--thread-id <id>` 或 `--all`；`--all` 会先通过运行中的实例查询上游 archived thread 列表。\n"
            "默认扫描所有运行中实例和已知非运行实例；传全局 `--instance <name>` 时只作用于该实例。\n"
            "适合补救旧版本 archive、外部归档，或服务重启后无 live owner 导致的跨实例残留。"
        ),
        formatter_class=_HelpFormatter,
    )
    thread_clear_archived_target = thread_clear_archived.add_mutually_exclusive_group(required=True)
    thread_clear_archived_target.add_argument("--thread-id", help="要清理本地 binding 的 archived thread id。")
    thread_clear_archived_target.add_argument(
        "--all",
        dest="all_archived",
        action="store_true",
        help="查询上游 archived thread 列表，并清理命中的本地 binding bookmark。",
    )
    thread_clear_archived.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览会清理哪些 binding，不修改本地数据。",
    )
    thread_detach = thread_sub.add_parser(
        "detach",
        help="暂停某个 thread 的飞书推送。",
        description="让 Feishu 服务暂停该 thread 当前 attached bindings 的推送，同时保留 thread 与 binding 关系。",
        formatter_class=_HelpFormatter,
    )
    thread_detach_target = thread_detach.add_mutually_exclusive_group(required=True)
    thread_detach_target.add_argument("--thread-id", help="目标 thread id。")
    thread_detach_target.add_argument("--thread-name", help="目标 thread 名称。")
    thread_attach = thread_sub.add_parser(
        "attach",
        help="恢复某个 thread 下 detached 的飞书推送。",
        description="把目标 thread 当前所有 detached 的 Feishu bindings 恢复到 attached；不启动 turn。",
        formatter_class=_HelpFormatter,
    )
    thread_attach_target = thread_attach.add_mutually_exclusive_group(required=True)
    thread_attach_target.add_argument("--thread-id", help="目标 thread id。")
    thread_attach_target.add_argument("--thread-name", help="目标 thread 名称。")

    image = subparsers.add_parser(
        "image",
        help="向某个 thread 的 attached Feishu bindings 发送图片。",
        description=(
            "图片出站管理面。\n"
            "当前只提供 `send`：把一张本地图片发送到目标 thread 当前所有 attached 的 Feishu bindings。\n"
            "如果省略 `--thread-id/--thread-name`，会尝试读取当前环境变量 `CODEX_THREAD_ID`。"
        ),
        formatter_class=_HelpFormatter,
    )
    image_sub = image.add_subparsers(dest="action", required=True, title="image commands", metavar="image-command")
    image_send = image_sub.add_parser(
        "send",
        help="把本地图片发送到目标 thread 的所有 attached bindings。",
        description=(
            "把一张本地图片发送到目标 thread 当前所有 attached 的 Feishu bindings。\n"
            "这是 thread-scoped 动作，不会扫描工作区，也不会自动推断任意图片文件。"
        ),
        formatter_class=_HelpFormatter,
    )
    image_send.add_argument("--path", required=True, help="本地图片路径。")
    image_send_target = image_send.add_mutually_exclusive_group(required=False)
    image_send_target.add_argument("--thread-id", help="目标 thread id。省略时可回落到 `CODEX_THREAD_ID`。")
    image_send_target.add_argument("--thread-name", help="目标 thread 名称。")
    return parser


def main() -> None:
    load_env_file()
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.resource == "instance" and args.action == "list":
            raise SystemExit(_list_running_instances())
        if args.resource == "image" and args.action == "send":
            target_params, preferred_thread_id = _image_send_target_params(args)
            target = _resolve_target_instance(
                args.instance,
                preferred_running_instance=_lease_owner_instance(preferred_thread_id),
            )
            raise SystemExit(
                _send_thread_image(
                    target.data_dir,
                    target_params,
                    local_path=args.path,
                    instance_name=target.instance_name,
                )
            )
        if args.resource == "thread" and args.action == "archive":
            thread_ids, thread_name = _thread_archive_inputs(args)
            if thread_name:
                target, target_params = _resolve_thread_archive_target(args)
                raise SystemExit(
                    _archive_thread(
                        target.data_dir,
                        target_params,
                        instance_name=target.instance_name,
                    )
                )
            raise SystemExit(_archive_threads(thread_ids, explicit_instance=str(args.instance or "").strip()))
        if args.resource == "thread" and args.action == "clear-archived-bindings":
            raise SystemExit(
                _clear_archived_thread_bindings(
                    getattr(args, "thread_id", "") or "",
                    all_archived=bool(getattr(args, "all_archived", False)),
                    explicit_instance=str(args.instance or "").strip(),
                    dry_run=bool(args.dry_run),
                )
            )
        if args.resource == "binding" and args.action == "clear-stale":
            raise SystemExit(
                _clear_stale_bindings(
                    explicit_instance=str(args.instance or "").strip(),
                    dry_run=bool(args.dry_run),
                )
            )
        target = _resolve_target_instance(args.instance)
        data_dir = target.data_dir
        if args.resource == "service" and args.action == "status":
            raise SystemExit(_print_service_status(data_dir))
        if args.resource == "service" and args.action == "reset-backend":
            raise SystemExit(_reset_service_backend(data_dir, force=bool(args.force)))
        if args.resource == "service" and args.action == "attach":
            raise SystemExit(_attach_service(data_dir))
        if args.resource == "binding" and args.action == "list":
            raise SystemExit(_print_binding_list(data_dir))
        if args.resource == "binding" and args.action == "status":
            raise SystemExit(_print_binding_status(data_dir, args.binding_id, instance_name=target.instance_name))
        if args.resource == "binding" and args.action == "attach":
            raise SystemExit(_attach_binding(data_dir, args.binding_id))
        if args.resource == "binding" and args.action == "detach":
            raise SystemExit(_detach_binding(data_dir, args.binding_id))
        if args.resource == "binding" and args.action == "clear":
            raise SystemExit(_clear_binding(data_dir, args.binding_id))
        if args.resource == "binding" and args.action == "clear-all":
            raise SystemExit(_clear_all_bindings(data_dir))
        if args.resource == "prompt" and args.action == "send":
            raise SystemExit(
                _send_binding_prompt(
                    data_dir,
                    binding_id=args.binding_id,
                    text=_prompt_text_from_args(args),
                    actor_open_id=args.actor_open_id,
                    synthetic_source=args.synthetic_source,
                    display_mode=args.display_mode,
                    instance_name=target.instance_name,
                )
            )
        if args.resource == "thread" and args.action == "list":
            cwd = str(args.cwd or "").strip() or os.getcwd()
            raise SystemExit(
                _print_thread_list(
                    data_dir,
                    scope=args.scope,
                    cwd=cwd,
                    running_entry=target.running_entry,
                )
            )
        if args.resource == "thread" and args.action == "status":
            raise SystemExit(
                _print_thread_status(
                    data_dir,
                    _thread_target_params(args),
                    instance_name=target.instance_name,
                )
            )
        if args.resource == "thread" and args.action == "goal":
            goal_action = str(getattr(args, "goal_action", "") or "show").strip() or "show"
            if goal_action == "show":
                raise SystemExit(
                    _print_thread_goal(
                        data_dir,
                        _thread_target_params(args),
                        instance_name=target.instance_name,
                    )
                )
            if goal_action == "set":
                raise SystemExit(
                    _set_thread_goal(
                        data_dir,
                        _thread_target_params(args),
                        objective=str(args.objective or ""),
                        status=str(args.status or ""),
                        instance_name=target.instance_name,
                    )
                )
            if goal_action == "clear":
                raise SystemExit(
                    _clear_thread_goal(
                        data_dir,
                        _thread_target_params(args),
                        instance_name=target.instance_name,
                    )
                )
        if args.resource == "thread" and args.action == "bindings":
            raise SystemExit(_print_thread_bindings(data_dir, _thread_target_params(args)))
        if args.resource == "thread" and args.action == "attach":
            raise SystemExit(_attach_thread(data_dir, _thread_target_params(args)))
        if args.resource == "thread" and args.action == "detach":
            raise SystemExit(_detach_thread(data_dir, _thread_target_params(args)))
    except ServiceControlError as exc:
        print(f"控制面请求失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    parser.print_usage(sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
