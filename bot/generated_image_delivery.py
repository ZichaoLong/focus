from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

from bot.adapters.base import ThreadSnapshot
from bot.stores.generated_image_delivery_store import (
    GeneratedImageDeliveryRecord,
    GeneratedImageDeliveryStore,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GeneratedImageArtifact:
    turn_id: str
    item_id: str
    saved_path: str
    revised_prompt: str = ""


def collect_generated_images(
    snapshot: ThreadSnapshot,
    *,
    turn_id: str = "",
) -> tuple[GeneratedImageArtifact, ...]:
    normalized_turn_id = str(turn_id or "").strip()
    target_turns = snapshot.turns
    if normalized_turn_id:
        matched_turns = [
            turn
            for turn in snapshot.turns
            if str(turn.get("id", "") or "").strip() == normalized_turn_id
        ]
        if not matched_turns:
            return ()
        target_turns = matched_turns[-1:]
    elif target_turns:
        target_turns = target_turns[-1:]
    else:
        return ()

    artifacts: list[GeneratedImageArtifact] = []
    for turn in target_turns:
        current_turn_id = str(turn.get("id", "") or "").strip()
        items = turn.get("items") or []
        for item in items:
            if str(item.get("type", "") or "").strip() != "imageGeneration":
                continue
            status = str(item.get("status", "") or "").strip().lower()
            if status and status != "completed":
                continue
            item_id = str(item.get("id", "") or "").strip()
            saved_path = _read_string(item, "savedPath", "saved_path")
            if not item_id or not saved_path:
                continue
            artifacts.append(
                GeneratedImageArtifact(
                    turn_id=current_turn_id,
                    item_id=item_id,
                    saved_path=saved_path,
                    revised_prompt=_read_string(item, "revisedPrompt", "revised_prompt"),
                )
            )
    return tuple(artifacts)


class GeneratedImageDeliveryController:
    def __init__(
        self,
        *,
        store: GeneratedImageDeliveryStore,
        reply_local_image: Callable[..., str | None],
        path_exists: Callable[[str], bool] = os.path.exists,
    ) -> None:
        self._store = store
        self._reply_local_image = reply_local_image
        self._path_exists = path_exists

    def deliver_snapshot_images(
        self,
        *,
        sender_id: str,
        chat_id: str,
        thread_id: str,
        snapshot: ThreadSnapshot,
        turn_id: str = "",
        prompt_message_id: str = "",
        prompt_reply_in_thread: bool = False,
    ) -> int:
        delivered = 0
        for artifact in collect_generated_images(snapshot, turn_id=turn_id):
            normalized_thread_id = str(thread_id or "").strip() or snapshot.summary.thread_id
            if self._store.has_delivery(
                sender_id=sender_id,
                chat_id=chat_id,
                thread_id=normalized_thread_id,
                turn_id=artifact.turn_id,
                item_id=artifact.item_id,
            ):
                continue
            if not self._path_exists(artifact.saved_path):
                logger.warning(
                    "跳过图片投递：图片文件不存在 chat=%s thread=%s turn=%s item=%s path=%s",
                    chat_id,
                    normalized_thread_id[:12],
                    artifact.turn_id[:12],
                    artifact.item_id[:12],
                    artifact.saved_path,
                )
                continue
            message_id = self._reply_local_image(
                chat_id,
                artifact.saved_path,
                parent_message_id=str(prompt_message_id or "").strip(),
                reply_in_thread=bool(prompt_reply_in_thread),
            )
            if not message_id:
                continue
            self._store.record(
                GeneratedImageDeliveryRecord(
                    sender_id=str(sender_id or "").strip(),
                    chat_id=str(chat_id or "").strip(),
                    thread_id=normalized_thread_id,
                    turn_id=artifact.turn_id,
                    item_id=artifact.item_id,
                    local_path=artifact.saved_path,
                    message_id=message_id,
                    delivered_at=time.time(),
                )
            )
            delivered += 1
        return delivered


def _read_string(raw: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""
