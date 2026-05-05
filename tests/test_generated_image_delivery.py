import pathlib
import tempfile
import unittest

from bot.adapters.base import ThreadSnapshot, ThreadSummary
from bot.generated_image_delivery import (
    GeneratedImageArtifact,
    GeneratedImageDeliveryController,
    collect_generated_images,
)
from bot.stores.generated_image_delivery_store import GeneratedImageDeliveryStore


def _snapshot(*, turns: list[dict]) -> ThreadSnapshot:
    return ThreadSnapshot(
        summary=ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="completed",
        ),
        turns=turns,
    )


class GeneratedImageDeliveryTests(unittest.TestCase):
    def test_collect_generated_images_uses_only_target_turn(self) -> None:
        snapshot = _snapshot(
            turns=[
                {
                    "id": "turn-0",
                    "items": [
                        {
                            "type": "imageGeneration",
                            "id": "old-image",
                            "status": "completed",
                            "savedPath": "/tmp/old.png",
                        }
                    ],
                },
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "imageGeneration",
                            "id": "new-image",
                            "status": "completed",
                            "savedPath": "/tmp/new.png",
                            "revisedPrompt": "A blue square",
                        }
                    ],
                },
            ]
        )

        images = collect_generated_images(snapshot, turn_id="turn-1")

        self.assertEqual(
            images,
            (
                GeneratedImageArtifact(
                    turn_id="turn-1",
                    item_id="new-image",
                    saved_path="/tmp/new.png",
                    revised_prompt="A blue square",
                ),
            ),
        )

    def test_collect_generated_images_fail_closes_when_turn_missing(self) -> None:
        snapshot = _snapshot(
            turns=[
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "imageGeneration",
                            "id": "img-1",
                            "status": "completed",
                            "savedPath": "/tmp/new.png",
                        }
                    ],
                }
            ]
        )

        images = collect_generated_images(snapshot, turn_id="turn-missing")

        self.assertEqual(images, ())

    def test_generated_image_delivery_records_and_deduplicates(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        image_path = pathlib.Path(tempdir.name) / "generated.png"
        image_path.write_bytes(b"png")

        store = GeneratedImageDeliveryStore(pathlib.Path(tempdir.name))
        sent: list[tuple[str, str, str, bool]] = []
        controller = GeneratedImageDeliveryController(
            store=store,
            reply_local_image=lambda chat_id, local_path, parent_message_id, reply_in_thread: sent.append(
                (chat_id, local_path, parent_message_id, reply_in_thread)
            )
            or "msg-image-1",
        )

        snapshot = _snapshot(
            turns=[
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "imageGeneration",
                            "id": "img-1",
                            "status": "completed",
                            "savedPath": str(image_path),
                        }
                    ],
                }
            ]
        )

        first = controller.deliver_snapshot_images(
            sender_id="ou_user",
            chat_id="chat-1",
            thread_id="thread-1",
            snapshot=snapshot,
            turn_id="turn-1",
            prompt_message_id="msg-1",
            prompt_reply_in_thread=True,
        )
        second = controller.deliver_snapshot_images(
            sender_id="ou_user",
            chat_id="chat-1",
            thread_id="thread-1",
            snapshot=snapshot,
            turn_id="turn-1",
            prompt_message_id="msg-1",
            prompt_reply_in_thread=True,
        )

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(
            sent,
            [("chat-1", str(image_path), "msg-1", True)],
        )
        self.assertEqual(len(store.list_all()), 1)

    def test_generated_image_delivery_supports_keyword_only_reply_transport(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        image_path = pathlib.Path(tempdir.name) / "generated.png"
        image_path.write_bytes(b"png")

        store = GeneratedImageDeliveryStore(pathlib.Path(tempdir.name))
        sent: list[tuple[str, str, str, bool]] = []

        def _reply_local_image(
            chat_id: str,
            local_path: str,
            *,
            parent_message_id: str = "",
            reply_in_thread: bool = False,
        ) -> str | None:
            sent.append((chat_id, local_path, parent_message_id, reply_in_thread))
            return "msg-image-1"

        controller = GeneratedImageDeliveryController(
            store=store,
            reply_local_image=_reply_local_image,
        )
        snapshot = _snapshot(
            turns=[
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "imageGeneration",
                            "id": "img-1",
                            "status": "completed",
                            "savedPath": str(image_path),
                        }
                    ],
                }
            ]
        )

        delivered = controller.deliver_snapshot_images(
            sender_id="ou_user",
            chat_id="chat-1",
            thread_id="thread-1",
            snapshot=snapshot,
            turn_id="turn-1",
            prompt_message_id="msg-1",
            prompt_reply_in_thread=True,
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            sent,
            [("chat-1", str(image_path), "msg-1", True)],
        )
