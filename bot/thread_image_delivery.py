from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Callable, TypeAlias

from bot.binding_identity import format_binding_id

ChatBindingKey: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ThreadImageDeliveryMessage:
    binding_id: str
    chat_id: str
    message_id: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class ThreadImageDeliveryResult:
    thread_id: str
    local_path: str
    image_key: str
    delivered: tuple[ThreadImageDeliveryMessage, ...]
    failed: tuple[ThreadImageDeliveryMessage, ...]

    @property
    def fully_delivered(self) -> bool:
        return not self.failed and bool(self.delivered)


class ThreadImageDeliveryController:
    def __init__(
        self,
        *,
        upload_image: Callable[[str], str | None],
        send_image_by_key: Callable[[str, str], str | None],
        path_exists: Callable[[str], bool] = os.path.exists,
        path_is_file: Callable[[str], bool] = os.path.isfile,
    ) -> None:
        self._upload_image = upload_image
        self._send_image_by_key = send_image_by_key
        self._path_exists = path_exists
        self._path_is_file = path_is_file

    def deliver_local_image(
        self,
        *,
        thread_id: str,
        local_path: str,
        attached_bindings: tuple[ChatBindingKey, ...],
    ) -> ThreadImageDeliveryResult:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            raise ValueError("thread_id 不能为空。")
        normalized_path = str(local_path or "").strip()
        if not normalized_path:
            raise ValueError("图片路径不能为空。")
        resolved_path = str(pathlib.Path(normalized_path).expanduser())
        if not self._path_exists(resolved_path) or not self._path_is_file(resolved_path):
            raise ValueError(f"图片路径不存在或不是文件：{resolved_path}")
        normalized_bindings = tuple(
            sorted(
                {
                    (str(sender_id or "").strip(), str(chat_id or "").strip())
                    for sender_id, chat_id in attached_bindings
                    if str(sender_id or "").strip() and str(chat_id or "").strip()
                }
            )
        )
        if not normalized_bindings:
            raise ValueError("当前 thread 没有 attached 的 Feishu binding，不能发送图片。")

        image_key = str(self._upload_image(resolved_path) or "").strip()
        if not image_key:
            raise RuntimeError(f"上传图片失败：{resolved_path}")

        delivered: list[ThreadImageDeliveryMessage] = []
        failed: list[ThreadImageDeliveryMessage] = []
        for binding in normalized_bindings:
            binding_id = format_binding_id(binding)
            message_id = str(self._send_image_by_key(binding[1], image_key) or "").strip()
            if message_id:
                delivered.append(
                    ThreadImageDeliveryMessage(
                        binding_id=binding_id,
                        chat_id=binding[1],
                        message_id=message_id,
                    )
                )
                continue
            failed.append(
                ThreadImageDeliveryMessage(
                    binding_id=binding_id,
                    chat_id=binding[1],
                    error="send_failed",
                )
            )

        return ThreadImageDeliveryResult(
            thread_id=normalized_thread_id,
            local_path=resolved_path,
            image_key=image_key,
            delivered=tuple(delivered),
            failed=tuple(failed),
        )
