"""Q&A selection and content rules for browser exports.

See docs/contracts/focus-web-summary-export.zh-CN.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.codex_protocol.client import CodexRpcProtocolError
from bot.focus_web_wire_catalog import FOCUS_WEB_ENUM_BY_NAME
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.projection import project_user_prompt_text


MAX_SELECTED_TURNS = 100
EXPORT_TURN_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class SummaryExportSelection:
    scope: str = "all"
    turn_ids: tuple[str, ...] = ()
    content: str = "qa"


def decode_export_selection(value: object) -> SummaryExportSelection:
    if (
        not isinstance(value, dict)
        or set(value) != {"scope", "turn_ids", "content"}
        or value.get("scope") not in FOCUS_WEB_ENUM_BY_NAME["summary_export_scope"].values
        or value.get("content") not in FOCUS_WEB_ENUM_BY_NAME["summary_export_content"].values
        or not isinstance(value.get("turn_ids"), list)
    ):
        raise invalid_selection()
    ids = value["turn_ids"]
    if (
        len(ids) > MAX_SELECTED_TURNS
        or any(not isinstance(item, str) or not item or item != item.strip()
               or len(item) > 256 for item in ids)
        or len(set(ids)) != len(ids)
        or (value["scope"] == "selected") != bool(ids)
    ):
        raise invalid_selection()
    return SummaryExportSelection(value["scope"], tuple(ids), value["content"])


def invalid_selection() -> WebRuntimeError:
    return WebRuntimeError(
        "Choose all, last_turn, or 1..100 distinct turns, and qa, final_answers, or prompts.",
        code="invalid_summary_export_selection", status=400,
    )


def export_turn_items(turn: object) -> list[dict[str, Any]]:
    if not isinstance(turn, dict) or not isinstance(turn.get("items"), list):
        raise malformed("turn without items")
    if any(not isinstance(item, dict) for item in turn["items"]):
        raise malformed("non-object item")
    return turn["items"]


def export_turn_identity(turn: object) -> tuple[str, str]:
    if not isinstance(turn, dict):
        raise malformed("non-object turn")
    identity, status = turn.get("id"), turn.get("status")
    if not isinstance(identity, str) or not identity or identity != identity.strip():
        raise malformed("invalid turn identity")
    if status not in FOCUS_WEB_ENUM_BY_NAME["export_turn_status"].values:
        raise malformed("invalid turn status")
    return identity, status


def export_user_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if not isinstance(content, list):
        raise malformed("invalid user content")
    parts: list[str] = []
    for entry in content:
        if not isinstance(entry, dict):
            raise malformed("invalid user content")
        if entry.get("type") != "text":
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            raise malformed("invalid user text")
        try:
            text = project_user_prompt_text(text, reject_malformed_focus_envelope=True)
        except ValueError as exc:
            raise malformed("malformed Focus attachment prompt") from exc
        if normalized := text.strip():
            parts.append(normalized)
    return "\n\n".join(parts)


def export_qa(turn: object, *, include_followups: bool = False) -> tuple[list[str], str | None]:
    prompts: list[str] = []
    final: str | None = None
    for item in export_turn_items(turn):
        if item.get("type") == "userMessage" and (include_followups or not prompts):
            prompts.append(export_user_text(item))
        elif item.get("type") == "agentMessage":
            phase = item.get("phase")
            if phase not in (None, "commentary", "partial_answer", "final_answer"):
                raise malformed("unknown agent message phase")
            if phase == "final_answer":
                text = item.get("text")
                if not isinstance(text, str):
                    raise malformed("invalid final answer")
                final = text.strip() or None
    return prompts, final


def require_exportable_turn(turn: dict[str, Any], content: str) -> None:
    identity, status = export_turn_identity(turn)
    prompts, answer = export_qa(turn, include_followups=True)
    if content == "prompts":
        if any(prompts):
            return
        raise WebRuntimeError(
            "A chosen turn has no text prompt to export. No partial file was downloaded.",
            code="thread_summary_export_missing_content", status=409,
            details={"turn_id": identity, "content": content},
        )
    if status != "completed" or not prompts or not answer:
        raise WebRuntimeError(
            "A chosen turn is unfinished or has no confirmed final reply. "
            "Wait for completion or export prompts only; no partial file was downloaded.",
            code="thread_summary_export_incomplete_turn", status=409,
            details={"turn_id": identity, "status": status},
        )


def malformed(reason: str) -> CodexRpcProtocolError:
    return CodexRpcProtocolError("thread/turns/list", f"Codex export history contains {reason}")
