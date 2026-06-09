from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

ChatBindingKey: TypeAlias = tuple[str, str]
OwnerBindingQueueKind = Literal["prompt", "compact"]


@dataclass(frozen=True, slots=True)
class OwnerBindingQueueItem:
    kind: OwnerBindingQueueKind
    binding: ChatBindingKey
    sender_id: str
    chat_id: str
    message_id: str = ""
    text: str = ""
    actor_open_id: str = ""
    origin_chat_type: str = ""
    origin_sender_open_id: str = ""
    origin_sender_user_id: str = ""
    origin_sender_type: str = ""
    origin_feishu_thread_id: str = ""
    assistant_context_mode: str = ""
    assistant_context_created_at: int = 0
    assistant_context_seq: int = 0
    assistant_context_sender_name: str = ""
    input_items: tuple[dict[str, Any], ...] = ()
    synthetic_source: str = ""
    display_mode: str = "silent"
    surface_failures: bool = True


class OwnerBindingQueue:
    """Small in-memory FIFO for follow-up work submitted by the active binding."""

    def __init__(self) -> None:
        self._items: dict[ChatBindingKey, deque[OwnerBindingQueueItem]] = defaultdict(deque)
        self._draining: set[ChatBindingKey] = set()

    def enqueue(self, item: OwnerBindingQueueItem) -> int:
        queue = self._items[item.binding]
        queue.append(item)
        return len(queue)

    def begin_drain(self, binding: ChatBindingKey) -> OwnerBindingQueueItem | None:
        if binding in self._draining:
            return None
        queue = self._items.get(binding)
        if not queue:
            return None
        self._draining.add(binding)
        return queue[0]

    def finish_drain(self, binding: ChatBindingKey, *, started: bool) -> None:
        if started:
            queue = self._items.get(binding)
            if queue:
                queue.popleft()
                if not queue:
                    self._items.pop(binding, None)
        self._draining.discard(binding)
