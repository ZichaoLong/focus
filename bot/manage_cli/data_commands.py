"""Instance retention configuration and service-owned cleanup, without Web."""

from __future__ import annotations

from pathlib import Path

from bot.data_retention_contract import DataRetentionPolicy
from bot.instance_layout import resolve_instance_paths
from bot.instance_resolution import current_cli_instance_name, resolve_cli_instance_target
from bot.service_control_plane import (
    ServiceControlError,
    ServiceControlKnownNotCommittedError,
    ServiceControlOutcomeUnknownError,
    control_request,
)
from bot.stores.data_retention_store import DataRetentionStore


def _prune_policy(result: object) -> DataRetentionPolicy:
    """Do not print success for a malformed or incomplete control receipt."""
    try:
        if (not isinstance(result, dict)
                or set(result) != {"policy", "results", "errors", "records", "bytes_freed"}
                or not isinstance(result["policy"], dict)
                or set(result["policy"]) != {"records_days", "attachments_days"}
                or not isinstance(result["results"], dict) or not isinstance(result["errors"], dict)):
            raise ValueError
        policy = DataRetentionPolicy(**result["policy"])
        for counts in [result, *result["results"].values()]:
            if not isinstance(counts, dict) or any(
                type(counts.get(key)) is not int or counts[key] < 0 for key in ("records", "bytes_freed")
            ):
                raise ValueError
        if any(result[key] != sum(counts[key] for counts in result["results"].values())
               for key in ("records", "bytes_freed")):
            raise ValueError
        if any(not isinstance(value, str) for value in result["errors"].values()):
            raise ValueError
        return policy
    except (ValueError, TypeError) as exc:
        raise ValueError("清理响应无效，无法确认执行结果；未自动重试。") from exc


def handle_data(
    instance_name: str, action: str, *, records_days: int | None = None,
    attachments_days: int | None = None,
) -> int:
    target = resolve_cli_instance_target(
        instance_name or None, preferred_running_instance=current_cli_instance_name())
    store = DataRetentionStore(
        target.data_dir, config_dir=(Path(target.running_entry.config_dir) if target.running_entry
                                     else resolve_instance_paths(target.instance_name).config_dir))
    if action in {"status", "retention"}:
        changes = {key: value for key, value in {
            "records_days": records_days, "attachments_days": attachments_days,
        }.items() if value is not None}
        if action == "retention" and not changes:
            raise ValueError("请至少指定 --records-days 或 --attachments-days。")
        try:
            policy = store.load() if action == "status" else store.update(changes)
        except OSError as exc:
            raise ValueError(f"保留期配置读写失败：{exc}") from exc
        print(f"instance: {target.instance_name}\nconfig: {store.path}")
        print(f"Focus 记录保留期: {policy.records_days} 天\n附件保留期: {policy.attachments_days} 天")
        return 0
    if action != "prune":
        raise ValueError(f"Unknown data action: {action}")
    try:
        result = control_request(target.data_dir, "data/prune", timeout_seconds=120)
    except ServiceControlKnownNotCommittedError as exc:
        raise ValueError("清理需要目标 Focus 服务正在运行；请先执行 focusctl --instance "
                         f"{target.instance_name} service start。无需启用 Web。详情：{exc}") from exc
    except ServiceControlOutcomeUnknownError as exc:
        raise ValueError(f"清理请求结果未知，服务端可能仍在执行；未自动重试。详情：{exc}") from exc
    except ServiceControlError as exc:
        raise ValueError(f"数据清理未完成：{exc}") from exc
    policy = _prune_policy(result)
    print(f"instance: {target.instance_name}")
    print(f"Focus 记录保留期: {policy.records_days} 天\n附件保留期: {policy.attachments_days} 天")
    for name, counts in result["results"].items():
        print(f"{name}: {counts['records']} 项 / {counts['bytes_freed']} bytes")
    for name, error in result["errors"].items():
        print(f"{name}: 清理失败 ({error})")
    print(f"清理合计: {result['records']} 项 / {result['bytes_freed']} bytes；仅服务端到期数据。")
    return 1 if result["errors"] else 0
