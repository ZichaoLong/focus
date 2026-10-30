"""Wire maintenance to existing data owners; see the data-retention contract."""
from __future__ import annotations

import pathlib
import time
from collections.abc import Callable

from bot.binding_runtime_contract import BindingSessionSnapshot
from bot.data_retention import DataRetentionService
from bot.data_retention_contract import DataPruneResult, DataRetentionPolicy
from bot.diagnostic_logs import prune_logs
from bot.file_message_domain import FileMessageDomain
from bot.stores.attachment_store import AttachmentStore
from bot.stores.data_retention_store import DataRetentionStore
from bot.stores.generated_image_delivery_store import GeneratedImageDeliveryStore
from bot.stores.terminal_result_store import TerminalResultStore


def compose_data_retention(
    *, data_dir: pathlib.Path, policy: DataRetentionStore,
    sessions: Callable[[], tuple[BindingSessionSnapshot, ...]],
    web_cwds: Callable[[], tuple[str, ...]],
    recovery_active: Callable[[], bool],
    prune_profiles: Callable[[float], DataPruneResult],
    prune_timings: Callable[[float], DataPruneResult],
    prune_groups: Callable[..., DataPruneResult],
    attachments: AttachmentStore, files: FileMessageDomain,
    terminal_results: TerminalResultStore, image_deliveries: GeneratedImageDeliveryStore,
) -> DataRetentionService:
    def cutoff(selected: DataRetentionPolicy, now: float) -> float:
        # A long-running execution may still need its dedup evidence.
        starts = [now - max(0.0, time.monotonic() - s.execution.started_at) - 1 for s in sessions()
                  if s.execution.running and s.execution.started_at > 0]
        return max(0, min([now - selected.records_days * 86400, *starts]))

    def logs(selected: DataRetentionPolicy, now: float) -> DataPruneResult:
        removed = prune_logs(data_dir, keep_days=selected.records_days)
        return DataPruneResult(len(removed), sum(item.size for item in removed))

    return DataRetentionService(policy, {
        "diagnostic_logs": logs,
        "group_messages": lambda p, now: prune_groups(
            now - p.records_days * 86400,
            protected_chats=tuple(s.binding[1] for s in sessions() if s.execution.running)),
        "terminal_results": lambda p, now: DataPruneResult() if recovery_active() else terminal_results.prune(cutoff(p, now)),
        "image_deliveries": lambda p, now: DataPruneResult() if recovery_active() else image_deliveries.prune(cutoff(p, now)),
        "browser_navigation": lambda p, now: prune_profiles(now - p.records_days * 86400),
        "prompt_timings": lambda p, now: prune_timings(now - p.records_days * 86400),
        "pending_attachments": lambda p, now: files.prune_pending(now=now),
        "attachments": lambda p, now: attachments.prune(now=now, protected_cwds=(
            *web_cwds(), *(s.working_dir for s in sessions() if s.execution.running))),
    })
