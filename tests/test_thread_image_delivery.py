import pathlib
import tempfile
import unittest

from bot.thread_image_delivery import ThreadImageDeliveryController


class ThreadImageDeliveryTests(unittest.TestCase):
    def test_deliver_local_image_rejects_when_no_attached_bindings(self) -> None:
        controller = ThreadImageDeliveryController(
            upload_image=lambda local_path: "img-key-1",
            send_image_by_key=lambda chat_id, image_key: "msg-1",
            path_exists=lambda path: True,
            path_is_file=lambda path: True,
        )

        with self.assertRaisesRegex(ValueError, "没有 attached"):
            controller.deliver_local_image(
                thread_id="thread-1",
                local_path="/tmp/generated.png",
                attached_bindings=(),
            )

    def test_deliver_local_image_uploads_once_and_fanouts_to_all_bindings(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        image_path = pathlib.Path(tempdir.name) / "generated.png"
        image_path.write_bytes(b"png")

        uploaded_paths: list[str] = []
        sent: list[tuple[str, str]] = []
        controller = ThreadImageDeliveryController(
            upload_image=lambda local_path: uploaded_paths.append(local_path) or "img-key-1",
            send_image_by_key=lambda chat_id, image_key: sent.append((chat_id, image_key)) or f"msg:{chat_id}",
        )

        result = controller.deliver_local_image(
            thread_id="thread-1",
            local_path=str(image_path),
            attached_bindings=(("ou_user", "chat-1"), ("ou_other", "chat-2")),
        )

        self.assertTrue(result.fully_delivered)
        self.assertEqual(uploaded_paths, [str(image_path)])
        self.assertEqual(sent, [("chat-2", "img-key-1"), ("chat-1", "img-key-1")])
        self.assertEqual(
            [item.binding_id for item in result.delivered],
            ["p2p:ou_other:chat-2", "p2p:ou_user:chat-1"],
        )

    def test_deliver_local_image_reports_partial_delivery(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        image_path = pathlib.Path(tempdir.name) / "generated.png"
        image_path.write_bytes(b"png")

        controller = ThreadImageDeliveryController(
            upload_image=lambda local_path: "img-key-1",
            send_image_by_key=lambda chat_id, image_key: "" if chat_id == "chat-2" else "msg:chat-1",
        )

        result = controller.deliver_local_image(
            thread_id="thread-1",
            local_path=str(image_path),
            attached_bindings=(("ou_user", "chat-1"), ("ou_other", "chat-2")),
        )

        self.assertFalse(result.fully_delivered)
        self.assertEqual([item.binding_id for item in result.delivered], ["p2p:ou_user:chat-1"])
        self.assertEqual([item.binding_id for item in result.failed], ["p2p:ou_other:chat-2"])
