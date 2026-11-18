"""Surface-neutral diagnostic text for backend-reset evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from bot.backend_reset.contract import BackendResetPreview


@dataclass(frozen=True, slots=True)
class BackendResetDiagnosticsPorts:
    """Small presentation-only capabilities retained by RuntimeAdmin."""

    instance_name: Callable[[], str]
    format_binding_ids: Callable[[tuple[str, ...] | list[str]], str]
    short_thread_ids: Callable[[tuple[str, ...] | list[str]], str]


class BackendResetDiagnostics:
    def __init__(self, ports: BackendResetDiagnosticsPorts) -> None:
        self._ports = ports

    def hard_blocker_lines(self, preview: BackendResetPreview) -> list[str]:
        lines: list[str] = []
        if preview.blocking_active_turn_count:
            line = f"backend active threads：`{preview.blocking_active_turn_count}`"
            if preview.active_loaded_thread_preview:
                line += f" ({self._ports.short_thread_ids(preview.active_loaded_thread_preview)})"
            lines.append(line)
        if preview.blocking_pending_request_count:
            lines.append(
                f"待处理审批/输入请求：`{preview.blocking_pending_request_count}`"
            )
        if preview.running_binding_ids:
            lines.append(
                "运行中的 Feishu bindings："
                + self._ports.format_binding_ids(preview.running_binding_ids)
            )
        if preview.runtime_verification_failed:
            lines.append("backend loaded thread 校验：`unverified`")
        return lines

    def collateral_lines(self, preview: BackendResetPreview) -> list[str]:
        lines = [
            f"当前实例 loaded threads：`{preview.collateral_loaded_thread_count}`",
        ]
        if preview.attached_binding_ids:
            lines.append(
                "attached Feishu bindings："
                + self._ports.format_binding_ids(preview.attached_binding_ids)
            )
        if preview.blocking_holder_labels:
            lines.append(
                "live runtime holders："
                + self._format_holder_labels(preview.blocking_holder_labels)
            )
        if preview.collateral_active_loaded_thread_count:
            lines.append(
                "其中 active threads："
                f"`{preview.collateral_active_loaded_thread_count}`"
            )
        if preview.loaded_thread_preview:
            lines.append(
                "preview："
                + self._ports.short_thread_ids(preview.loaded_thread_preview)
            )
        return lines

    def flat_diagnostics(self, preview: BackendResetPreview) -> tuple[str, ...]:
        lines = [f"当前实例：`{self._ports.instance_name()}`"]
        lines.extend(
            f"hard blocker：{item}" for item in self.hard_blocker_lines(preview)
        )
        lines.extend(
            f"collateral impact：{item}" for item in self.collateral_lines(preview)
        )
        return tuple(lines)

    @staticmethod
    def _format_holder_labels(holder_labels: tuple[str, ...] | list[str]) -> str:
        normalized = [
            str(label or "").strip()
            for label in holder_labels
            if str(label or "").strip()
        ]
        if not normalized:
            return "（无）"
        return ", ".join(f"`{label}`" for label in normalized)
