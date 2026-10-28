"""Web thread creation and persistent fork transaction owner.

This coordinator owns the complete product transaction from one browser draft
through ``thread/start``, local projection, first-turn preparation,
``turn/start``, and typed known/unknown results. Persistent forks share creation
and local projection without a first turn. State remains in its existing
owners; this module only fixes their ordering.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from bot.adapters.base import ThreadItemsPage, ThreadSnapshot, ThreadSummary
from bot.codex_protocol.client import CodexRpcPreSendError
from bot.runtime_loop import RuntimeContextGuard
from bot.stores.web_next_turn_settings_store import WebNextTurnSettings
from bot.thread_create_transaction import (
    CommittedThreadCreate,
    ThreadCreateLocalCommitFailed,
    ThreadCreateOutcomeUnknown,
)
from bot.web_runtime.operation_service import WebOperationService
from bot.web_runtime.document_registry import WebDocumentRegistry
from bot.web_runtime.projection import FocusWebProjection
from bot.web_runtime.contract import WebRuntimeError, new_web_client_user_message_id
from bot.web_runtime.interest import WebRuntimeInterestRegistry
from bot.web_runtime.direct_thread_target_coordinator import require_web_direct_thread_snapshot
from bot.web_runtime.lifecycle_coordinator import WebRuntimeLifecycleCoordinator
from bot.web_runtime.writer_workspace_coordinator import (
    WebWriterWorkspaceCoordinator,
    accept_web_document_intent,
    require_connected_web_document,
    require_web_thread_id,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebThreadCreatePorts:
    """External-effect ports; state owners are explicit constructor inputs."""

    create_and_commit_thread: Callable[
        ...,
        CommittedThreadCreate[ThreadSnapshot, str],
    ]
    start_turn: Callable[..., dict[str, Any]]
    read_thread: Callable[[str, bool], ThreadSnapshot]
    rename_thread: Callable[[str, str], None]
    list_threads_page: Callable[..., tuple[list[ThreadSummary], str | None]]
    list_thread_items: Callable[..., ThreadItemsPage]
    capture_connection_generation: Callable[[], int]


class WebThreadCreateCoordinator:
    """Run Web creation and fork transactions on RuntimeLoop."""

    def __init__(
        self,
        *,
        documents: WebDocumentRegistry,
        workspace: WebWriterWorkspaceCoordinator,
        next_turn_settings: Callable[[], WebNextTurnSettings],
        operations: WebOperationService,
        lifecycle: WebRuntimeLifecycleCoordinator,
        remember_direct_thread_summary: Callable[[ThreadSummary], None],
        runtime_interest: WebRuntimeInterestRegistry,
        projection: FocusWebProjection,
        ports: WebThreadCreatePorts,
        runtime_context_guard: RuntimeContextGuard,
    ) -> None:
        if not isinstance(workspace, WebWriterWorkspaceCoordinator):
            raise TypeError("Web thread create requires the workspace owner")
        if not callable(next_turn_settings):
            raise TypeError("Web thread create requires next-turn settings")
        if not isinstance(operations, WebOperationService):
            raise TypeError("Web thread create requires the operation owner")
        if not isinstance(ports, WebThreadCreatePorts):
            raise TypeError("Web thread create requires typed ports")
        if not callable(runtime_context_guard):
            raise TypeError("Web thread create requires a RuntimeLoop context guard")
        self._documents = documents
        self._workspace = workspace
        self._next_turn_settings = next_turn_settings
        self._operations = operations
        self._lifecycle = lifecycle
        self._remember_direct_thread_summary = remember_direct_thread_summary
        self._runtime_interest = runtime_interest
        self._projection = projection
        self._ports = ports
        self._runtime_context_guard = runtime_context_guard

    def fork_thread(
        self, client_id: str, thread_id: str, *, turn_id: str = "", item_id: str = "",
    ) -> dict[str, Any]:
        """Create an independent persistent branch; selection is a normal Web open."""
        self._runtime_context_guard()
        require_connected_web_document(self._documents, client_id)
        source_id = require_web_thread_id(thread_id)
        source = self._ports.read_thread(source_id, False)
        require_web_direct_thread_snapshot(source, thread_id=source_id, operation="fork")
        name_warning = ""
        edit_prompt = None
        fork_args: dict[str, Any] = {}
        if turn_id or item_id:
            if not turn_id or not item_id or turn_id.strip() != turn_id or item_id.strip() != item_id:
                raise WebRuntimeError("历史编辑需要确切的 turn ID 和 item ID。", code="invalid_history_target")
            if source.history_mode != "paginated":
                raise WebRuntimeError("历史编辑仅支持 paginated 历史；未创建分支。", code="history_edit_unsupported")
            try:
                generation = self._ports.capture_connection_generation()
                text = self._read_edit_prompt(source_id, turn_id, item_id, generation)
            except WebRuntimeError:
                raise
            except Exception as exc:
                logger.warning("History edit input read failed for %s", source_id, exc_info=True)
                raise WebRuntimeError(
                    "无法完整读取原 prompt；未创建分支。请刷新历史后重试。",
                    code="history_edit_unavailable", status=409,
                    details={"source_thread_id": source_id, "read_error": type(exc).__name__},
                ) from exc
            edit_prompt = {"turn_id": turn_id, "item_id": item_id, "text": text}
            fork_args = {"fork_before_turn_id": turn_id, "fork_connection_generation": generation}

        def commit_fork(snapshot: ThreadSnapshot) -> str:
            nonlocal name_warning
            new_id = require_web_thread_id(snapshot.summary.thread_id)
            name = f"{source.summary.title} · 分支 {new_id[-8:]}"
            try:
                self._ports.rename_thread(new_id, name)
            except Exception:
                logger.warning(
                    "Could not confirm automatic fork name for %s", new_id, exc_info=True,
                )
                name_warning = (
                    f"Branch {new_id[-8:]} was created, but its automatic name could not be confirmed. "
                    "You can rename it manually."
                )
            else:
                snapshot.summary.name = name
            self._remember_direct_thread_summary(snapshot.summary)
            self._workspace.remember_thread_cwd(new_id, snapshot.summary.cwd)
            self._runtime_interest.mark_confirmed(new_id)
            self._runtime_interest.open_in_browser(new_id, expected_close_version=0)
            self._projection.publish("thread_invalidated", thread_id=new_id, reason="web_thread_forked")
            return new_id

        try:
            created = self._ports.create_and_commit_thread(
                fork_from_thread_id=source_id,
                local_commit=commit_fork,
                **fork_args,
            )
        except ThreadCreateOutcomeUnknown as exc:
            raise WebRuntimeError(
                "Fork result is unknown. Refresh the session list before creating another branch.",
                code="thread_fork_unknown", status=409,
                details={"attempt_id": exc.attempt_id, "source_thread_id": source_id},
            ) from exc
        except CodexRpcPreSendError as exc:
            raise WebRuntimeError(str(exc), code="history_edit_unavailable", status=409) from exc
        except ThreadCreateLocalCommitFailed as exc:
            raise WebRuntimeError(
                "The branch was created, but local setup failed. Open it from the session list.",
                code="thread_create_local_commit_failed", status=503,
                details={"thread_id": exc.thread_id, "source_thread_id": source_id},
            ) from exc
        # A bounded observation, never inventory authority or a creation retry.
        visibility = "check_failed"
        visibility_diagnostic = ""
        try:
            page, _cursor = self._ports.list_threads_page(
                limit=100, sort_key="created_at", source_kinds=[], model_providers=[],
                archived=False, timeout=2.0, require_existing_connection=True,
            )
            visibility = (
                "found" if any(t.thread_id == created.local_result for t in page)
                else "not_found"
            )
        except Exception as exc:
            visibility_diagnostic = f"thread/list check failed ({type(exc).__name__}); branch {created.local_result} was created."
            logger.warning("Fork visibility check failed for %s", created.local_result, exc_info=True)
        return {
            "accepted": True,
            "thread_id": created.local_result,
            "source_thread_id": source_id,
            "name_warning": name_warning,
            "list_visibility": visibility,
            "visibility_diagnostic": visibility_diagnostic,
            "edit_prompt": edit_prompt,
        }

    def _read_edit_prompt(self, thread_id: str, turn_id: str, item_id: str, generation: int) -> str:
        """Read the first input in the exact upstream turn, never a display preview."""
        deadline = time.monotonic() + 5.0
        cursor = None
        seen: set[str] = set()
        while time.monotonic() < deadline:
            page = self._ports.list_thread_items(
                thread_id, turn_id=turn_id, cursor=cursor, limit=100, sort_direction="asc",
                timeout=max(0.001, deadline - time.monotonic()), expected_connection_generation=generation,
            )
            for entry in page.items:
                if entry.turn_id != turn_id:
                    raise WebRuntimeError("上游历史坐标不匹配；未创建分支。", code="history_edit_unsupported")
                item = entry.item
                if item.get("type") != "userMessage":
                    continue
                if item.get("id") != item_id:
                    raise WebRuntimeError("同一轮的补充消息不能独立编辑；请选择该轮的首条 prompt。未创建分支。", code="history_edit_unsupported")
                content = item.get("content")
                if (not isinstance(content, list) or not content or any(
                    not isinstance(part, dict) or part.get("type") != "text"
                    or not isinstance(part.get("text"), str) or part.get("text_elements")
                    or set(part) - {"type", "text", "text_elements"} for part in content
                )):
                    raise WebRuntimeError("此 prompt 含附件、提及或其他结构化输入，暂不能完整恢复，未创建分支。", code="history_edit_unsupported")
                text = "\n".join(part["text"] for part in content)
                if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
                    raise WebRuntimeError("原 prompt 为空或超过编辑大小限制；未创建分支。", code="history_edit_unsupported")
                return text
            if not page.next_cursor or page.next_cursor in seen:
                break
            cursor = page.next_cursor
            seen.add(cursor)
        raise WebRuntimeError("未能确认原 prompt，请刷新历史后重试；未创建分支。", code="history_edit_unavailable")

    def start_thread(
        self,
        client_id: str,
        *,
        text: str,
        cwd: str = "",
        attachment_ids: list[str] | None = None,
        intent_generation: int = 0,
    ) -> dict[str, Any]:
        """Create a thread, commit its Web owner, and start its first turn."""

        self._runtime_context_guard()
        normalized_client_id = require_connected_web_document(
            self._documents,
            client_id,
        )
        accept_web_document_intent(
            self._documents,
            normalized_client_id,
            intent_generation,
        )
        profile = self._workspace.profile(normalized_client_id)
        normalized_text = str(text or "").strip()
        normalized_attachment_ids = self._workspace.normalize_attachment_ids(
            attachment_ids
        )
        if not normalized_text and not normalized_attachment_ids:
            raise WebRuntimeError(
                "Prompt or attachment is required.",
                code="empty_prompt",
            )
        normalized_cwd = str(
            cwd or profile.working_dir or self._workspace.default_working_dir or ""
        ).strip()
        if not normalized_cwd:
            raise WebRuntimeError(
                "A working directory is required.",
                code="invalid_cwd",
            )
        scope_key, normalized_cwd = self._workspace.attachment_scope(
            normalized_client_id,
            cwd=normalized_cwd,
        )
        attachment_records = self._workspace.resolve_attachments(
            normalized_client_id,
            scope_key=scope_key,
            attachment_ids=normalized_attachment_ids,
        )
        settings = self._next_turn_settings()
        selected_model = settings.model
        selected_effort = settings.reasoning_effort
        config_overrides = (
            {"model_reasoning_effort": selected_effort} if selected_effort else None
        )

        def commit_web_projection(snapshot: ThreadSnapshot) -> str:
            """Return the exact created id without creating a temporary owner."""

            thread_id = require_web_thread_id(snapshot.summary.thread_id)
            self._runtime_interest.mark_confirmed(thread_id)
            self._runtime_interest.open_in_browser(thread_id, expected_close_version=0)
            return thread_id

        try:
            try:
                created = self._ports.create_and_commit_thread(
                    local_commit=commit_web_projection,
                    cwd=normalized_cwd,
                    config_overrides=config_overrides,
                    model=selected_model or None,
                    approval_policy=settings.approval_policy,
                    permissions_profile_id=settings.permissions_profile_id,
                )
            except Exception:
                raise
        except ThreadCreateOutcomeUnknown as exc:
            raise WebRuntimeError(
                "Codex may have created the thread, but Focus did not receive a reliable result. "
                "Refresh the global thread list before deciding whether to create again.",
                code="mutation_unknown",
                status=409,
                details={
                    "operation": "thread_create",
                    "attempt_id": exc.attempt_id,
                },
            ) from exc
        except ThreadCreateLocalCommitFailed as exc:
            raise WebRuntimeError(
                "Codex created the thread, but Focus could not finish its local Web setup. "
                "Open the created thread from the global thread list before retrying the draft.",
                code="thread_create_local_commit_failed",
                status=503,
                details={
                    "operation": "thread_create",
                    "attempt_id": exc.attempt_id,
                    "thread_id": exc.thread_id,
                    "stage": exc.stage,
                },
            ) from exc
        except Exception as exc:
            if self._operations.is_unknown_mutation_error(exc):
                raise WebRuntimeError(
                    "Codex may have created the thread, but Focus did not receive "
                    "a reliable result. Refresh the global thread list before "
                    "deciding whether to create again.",
                    code="mutation_unknown",
                    status=409,
                    details={
                        "operation": "thread_create",
                        "attempt_id": str(getattr(exc, "attempt_id", "") or ""),
                    },
                ) from exc
            raise

        snapshot = created.response
        thread_id = require_web_thread_id(snapshot.summary.thread_id)
        if created.local_result != thread_id:
            raise RuntimeError("thread/create returned a different Web thread identity")

        self._project_committed_web_create(
            normalized_client_id,
            snapshot,
            fallback_cwd=normalized_cwd,
        )
        try:
            input_items = self._workspace.prompt_input_items(
                normalized_text,
                attachment_records,
                thread_id=thread_id,
                requested_model=selected_model,
            )
        except Exception as exc:
            logger.exception(
                "Web owner committed but first-turn input preparation failed: thread=%s",
                thread_id[:12],
            )
            # The create is committed to this document.  Preserve the draft on
            # that exact thread so ``start_prompt`` can retry without another
            # create operation.
            raise self._known_first_prompt_failure_error(
                normalized_attachment_ids,
                thread_id=thread_id,
                restored_message=(
                    "The Codex thread was created, but its first turn did not start. "
                    "Focus kept the thread and draft there; do not create another thread."
                ),
            ) from exc

        client_user_message_id = new_web_client_user_message_id()
        try:
            self._workspace.set_attachments_submitted(
                normalized_attachment_ids,
                submitted=True,
                scope_key=f"thread:{thread_id}",
            )
            # This is ordinary upstream-routed input.  Like an existing-thread
            # prompt, it does not read or create a shared main-turn lease; the
            # upstream turn/start call retains its native start-or-steer race.
            self._ports.start_turn(
                thread_id=thread_id,
                input_items=input_items,
                cwd=snapshot.summary.cwd or normalized_cwd,
                model=selected_model or None,
                approval_policy=settings.approval_policy,
                permissions_profile_id=settings.permissions_profile_id,
                reasoning_effort=selected_effort or None,
                client_user_message_id=client_user_message_id,
            )
        except Exception as exc:
            if self._operations.is_unknown_mutation_error(exc):
                raise WebRuntimeError(
                    "Codex may have accepted this first prompt, but Focus did not receive "
                    "its result. Focus will not replay it automatically; inspect the "
                    "created thread before submitting anything else.",
                    code="turn_submission_unknown",
                    status=503,
                    details={"thread_id": thread_id, "operation": "prompt"},
                ) from exc
            raise self._known_first_prompt_failure_error(
                normalized_attachment_ids,
                thread_id=thread_id,
                restored_message=(
                    "The Codex thread was created, but its first turn did not start. "
                    "Focus kept the empty thread and restored the draft there."
                ),
            ) from exc

        try:
            self._projection.publish(
                "thread_invalidated",
                thread_id=thread_id,
                reason="web_thread_started",
            )
        except Exception:
            logger.exception(
                "Started Web turn projection failed: thread=%s",
                thread_id[:12],
            )
        return {
            "accepted": True,
            "mode": "started",
            "thread_id": thread_id,
            "turn_id": "",
        }

    def _known_first_prompt_failure_error(
        self,
        attachment_ids: list[str],
        *,
        thread_id: str,
        restored_message: str,
    ) -> WebRuntimeError:
        attachments_restored = not attachment_ids
        if attachment_ids:
            try:
                attachments_restored = (
                    self._workspace.rollback_attachments_after_failed_submission(
                        attachment_ids,
                        scope_key=f"thread:{thread_id}",
                    )
                    is True
                )
            except Exception:
                logger.exception(
                    "Failed to restore attachments after first-turn failure: thread=%s",
                    thread_id[:12],
                )
        attachment_disposition = (
            "restored" if attachments_restored else "reupload_required"
        )
        message = restored_message
        if not attachments_restored:
            message = (
                "The Codex thread was created, but its first turn did not start "
                "and Focus could not restore its draft attachments. Open the "
                "created thread, remove the old attachments, and upload them again."
            )
        return WebRuntimeError(
            message,
            code="thread_created_turn_not_started",
            status=409,
            details={
                "thread_id": thread_id,
                "attachment_disposition": attachment_disposition,
            },
        )

    def _project_committed_web_create(
        self,
        client_id: str,
        snapshot: ThreadSnapshot,
        *,
        fallback_cwd: str,
    ) -> None:
        """Best-effort projections after the durable Web owner has committed."""

        thread_id = require_web_thread_id(snapshot.summary.thread_id)

        def select_thread() -> None:
            selection = self._workspace.select_thread(client_id, thread_id)
            self._lifecycle.settle_runtime_cleanup_candidates(
                selection.runtime_cleanup_thread_ids
            )

        steps: tuple[tuple[str, Callable[[], None]], ...] = (
            (
                "direct thread summary",
                lambda: self._remember_direct_thread_summary(snapshot.summary),
            ),
            (
                "thread cwd cache",
                lambda: self._workspace.remember_thread_cwd(
                    thread_id,
                    snapshot.summary.cwd or fallback_cwd,
                ),
            ),
            ("Web selection", select_thread),
            (
                "runtime interest",
                lambda: self._runtime_interest.mark_confirmed(
                    thread_id,
                    client_id=client_id,
                ),
            ),
            (
                "owner projection",
                lambda: self._projection.publish(
                    "owner_changed",
                    thread_id=thread_id,
                    reason="web_thread_created",
                ),
            ),
        )
        for step, action in steps:
            try:
                action()
            except Exception:
                logger.exception(
                    "Committed Web create projection failed: step=%s thread=%s",
                    step,
                    thread_id[:12],
                )
