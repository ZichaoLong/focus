"""Local diagnostic inventory and retention; usable while the service is stopped."""

from __future__ import annotations

from bot.diagnostic_logs import LOG_POLICIES, RETENTION_DAYS, log_inventory, prune_logs
from bot.instance_layout import (
    global_data_dir,
    require_instance_exists,
    resolve_instance_paths,
)
from bot.instance_resolution import (
    current_cli_instance_name,
    resolve_cli_instance_target,
)


def handle_logs(
    instance_name: str,
    action: str,
    *,
    dry_run: bool = False,
    keep_days: int = RETENTION_DAYS,
) -> int:
    if keep_days < 0:
        raise ValueError("keep-days 必须大于或等于 0。")
    # An explicit local inventory needs no live registry. With no registry
    # directory there can be no running-instance selection to consult either.
    if instance_name or not global_data_dir().exists():
        selected = require_instance_exists(instance_name or current_cli_instance_name())
        target = resolve_instance_paths(selected)
    else:
        target = resolve_cli_instance_target(
            preferred_running_instance=current_cli_instance_name()
        )
    data_dir = target.data_dir
    print(f"instance: {target.instance_name}\nlogs: {data_dir}")
    if action == "status":
        try:
            files = log_inventory(data_dir)
        except OSError as exc:
            raise ValueError(f"无法读取诊断日志：{exc}") from exc
        for policy in LOG_POLICIES:
            size = sum(entry.size for entry in files if entry.policy == policy)
            print(
                f"{policy.name}: {size} bytes / {policy.max_bytes * (policy.backups + 1)} bytes"
            )
        print(f"retention: {RETENTION_DAYS} days (按文件最后写入时间)")
        print("只统计 Focus 诊断日志；不包含会话数据、Codex 日志数据库或系统 journal。")
        return 0
    try:
        removed = prune_logs(data_dir, dry_run=dry_run, keep_days=keep_days)
    except OSError as exc:
        raise ValueError(f"日志清理未完成（可能正被写入，请稍后重试）：{exc}") from exc
    for entry in removed:
        print(
            f"{'would remove' if dry_run else 'removed'}: {entry.path} ({entry.size} bytes)"
        )
    print(
        f"{'would free' if dry_run else 'freed'}: {sum(entry.size for entry in removed)} bytes"
    )
    return 0
