import json
import pathlib
import tempfile
import unittest

from bot.stores.chat_binding_store import CHAT_BINDING_STORE_SCHEMA_VERSION, ChatBindingStore


class ChatBindingStoreTests(unittest.TestCase):
    def _make_store(self) -> tuple[tempfile.TemporaryDirectory[str], ChatBindingStore, pathlib.Path]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        data_dir = pathlib.Path(tempdir.name)
        return tempdir, ChatBindingStore(data_dir), data_dir / "chat_bindings.json"

    def test_store_round_trips_group_and_p2p_bindings(self) -> None:
        _, store, state_path = self._make_store()

        store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "/tmp/p2p",
                "current_thread_id": "thread-p2p",
                "current_thread_title": "p2p title",
                "feishu_runtime_state": "attached",
                "current_thread_write_owner_thread_id": "thread-p2p",
                "approval_policy": "on-request",
                "sandbox": "workspace-write",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
            },
        )
        store.save(
            ("__group__", "oc_group"),
            {
                "working_dir": "/tmp/group",
                "current_thread_id": "thread-group",
                "current_thread_title": "",
                "feishu_runtime_state": "detached",
                "current_thread_write_owner_thread_id": "",
                "approval_policy": "never",
                "sandbox": "danger-full-access",
                "model": "",
                "reasoning_effort": "",
            },
        )

        raw = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], CHAT_BINDING_STORE_SCHEMA_VERSION)
        self.assertEqual(raw["p2p_bindings"]["oc_p2p"]["ou_user"]["current_thread_id"], "thread-p2p")
        self.assertNotIn("current_thread_write_owner_thread_id", raw["p2p_bindings"]["oc_p2p"]["ou_user"])
        self.assertEqual(raw["p2p_bindings"]["oc_p2p"]["ou_user"]["reasoning_effort"], "high")
        self.assertEqual(
            raw["p2p_bindings"]["oc_p2p"]["ou_user"]["configured_settings"],
            ["approval_policy", "model", "permissions_profile_id", "reasoning_effort"],
        )
        self.assertEqual(raw["group_bindings"]["oc_group"]["current_thread_id"], "thread-group")

        self.assertEqual(store.load(("ou_user", "oc_p2p"))["current_thread_title"], "p2p title")

    def test_load_ignores_legacy_pending_collaboration_mode_sync_field(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 6,
                    "p2p_bindings": {
                        "oc_p2p": {
                            "ou_user": {
                                "working_dir": "/tmp/p2p",
                                "current_thread_id": "thread-p2p",
                                "current_thread_title": "",
                                "feishu_runtime_state": "attached",
                                "approval_policy": "on-request",
                                "permissions_profile_id": ":workspace",
                                "collaboration_mode": "plan",
                                "pending_collaboration_mode_sync": "true",
                                "model": "",
                                "reasoning_effort": "",
                            }
                        }
                    },
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = store.load(("ou_user", "oc_p2p"))

        assert loaded is not None
        self.assertNotIn("pending_collaboration_mode_sync", loaded)
        self.assertNotIn("collaboration_mode", loaded)

    def test_load_all_returns_all_normalized_bindings(self) -> None:
        _, store, _ = self._make_store()

        store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "/tmp/p2p",
                "current_thread_id": "thread-p2p",
                "current_thread_title": "",
                "feishu_runtime_state": "attached",
                "current_thread_write_owner_thread_id": "thread-p2p",
                "approval_policy": "on-request",
                "sandbox": "workspace-write",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
            },
        )
        store.save(
            ("__group__", "oc_group"),
            {
                "working_dir": "/tmp/group",
                "current_thread_id": "thread-group",
                "current_thread_title": "group title",
                "feishu_runtime_state": "detached",
                "current_thread_write_owner_thread_id": "",
                "approval_policy": "never",
                "sandbox": "danger-full-access",
                "model": "",
                "reasoning_effort": "",
            },
        )

        loaded = store.load_all()

        self.assertNotIn("current_thread_write_owner_thread_id", loaded[("ou_user", "oc_p2p")])
        self.assertEqual(loaded[("__group__", "oc_group")]["current_thread_title"], "group title")
        self.assertEqual(loaded[("ou_user", "oc_p2p")]["reasoning_effort"], "high")
        self.assertEqual(
            loaded[("ou_user", "oc_p2p")]["configured_settings"],
            ["approval_policy", "model", "permissions_profile_id", "reasoning_effort"],
        )

    def test_store_ignores_unknown_configured_settings(self) -> None:
        _, store, _ = self._make_store()

        saved = store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "",
                "current_thread_id": "",
                "current_thread_title": "",
                "feishu_runtime_state": "",
                "approval_policy": "",
                "permissions_profile_id": "",
                "model": "",
                "reasoning_effort": "",
                "configured_settings": ["model", "future_setting", "model"],
            },
        )

        self.assertEqual(saved["configured_settings"], ["model"])
        self.assertEqual(store.load(("ou_user", "oc_p2p"))["configured_settings"], ["model"])

    def test_clear_all_removes_state_file(self) -> None:
        _, store, state_path = self._make_store()

        store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "/tmp/p2p",
                "current_thread_id": "thread-p2p",
                "current_thread_title": "",
                "feishu_runtime_state": "attached",
                "current_thread_write_owner_thread_id": "",
                "approval_policy": "on-request",
                "sandbox": "workspace-write",
                "model": "",
                "reasoning_effort": "",
            },
        )
        self.assertTrue(state_path.exists())

        store.clear_all()

        self.assertFalse(state_path.exists())

    def test_store_rejects_missing_schema_version(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "p2p_bindings": {},
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "schema_version"):
            store.load(("ou_user", "oc_p2p"))

    def test_store_rejects_stale_schema_version(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "p2p_bindings": {},
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "schema_version must be one of",
        ):
            store.load(("ou_user", "oc_p2p"))

    def test_store_rejects_bound_thread_without_runtime_state(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": CHAT_BINDING_STORE_SCHEMA_VERSION,
                    "p2p_bindings": {
                        "oc_p2p": {
                            "ou_user": {
                                "working_dir": "/tmp/p2p",
                                "current_thread_id": "thread-1",
                                "current_thread_title": "",
                                "feishu_runtime_state": "",
                                "current_thread_write_owner_thread_id": "",
                                "approval_policy": "on-request",
                                "sandbox": "workspace-write",
                                "model": "",
                                "reasoning_effort": "",
                            }
                        }
                    },
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "feishu_runtime_state must be attached or detached"):
            store.load(("ou_user", "oc_p2p"))

    def test_store_rejects_legacy_released_runtime_state(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 4,
                    "p2p_bindings": {
                        "oc_p2p": {
                            "ou_user": {
                                "working_dir": "/tmp/p2p",
                                "current_thread_id": "thread-1",
                                "current_thread_title": "",
                                "feishu_runtime_state": "released",
                                "current_thread_write_owner_thread_id": "thread-1",
                                "approval_policy": "on-request",
                                "sandbox": "workspace-write",
                                "model": "",
                                "reasoning_effort": "",
                            }
                        }
                    },
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "feishu_runtime_state must be attached or detached"):
            store.load(("ou_user", "oc_p2p"))

    def test_store_rejects_runtime_state_without_thread_id(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": CHAT_BINDING_STORE_SCHEMA_VERSION,
                    "p2p_bindings": {
                        "oc_p2p": {
                            "ou_user": {
                                "working_dir": "/tmp/p2p",
                                "current_thread_id": "",
                                "current_thread_title": "",
                                "feishu_runtime_state": "detached",
                                "current_thread_write_owner_thread_id": "",
                                "approval_policy": "on-request",
                                "sandbox": "workspace-write",
                                "model": "",
                                "reasoning_effort": "",
                            }
                        }
                    },
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "must be empty when current_thread_id is empty"):
            store.load(("ou_user", "oc_p2p"))

    def test_store_normalizes_deprecated_approval_policy_on_load(self) -> None:
        _, store, state_path = self._make_store()
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": CHAT_BINDING_STORE_SCHEMA_VERSION,
                    "p2p_bindings": {
                        "oc_p2p": {
                            "ou_user": {
                                "working_dir": "/tmp/p2p",
                                "current_thread_id": "",
                                "current_thread_title": "",
                                "feishu_runtime_state": "",
                                "approval_policy": "on-failure",
                                "sandbox": "workspace-write",
                                "model": "",
                                "reasoning_effort": "",
                            }
                        }
                    },
                    "group_bindings": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = store.load(("ou_user", "oc_p2p"))

        assert loaded is not None
        self.assertEqual(loaded["approval_policy"], "on-request")

    def test_store_keeps_empty_approval_policy_empty(self) -> None:
        _, store, state_path = self._make_store()

        store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "/tmp/p2p",
                "current_thread_id": "",
                "current_thread_title": "",
                "feishu_runtime_state": "",
                "approval_policy": "",
                "sandbox": "",
                "model": "",
                "reasoning_effort": "",
            },
        )

        raw = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["p2p_bindings"]["oc_p2p"]["ou_user"]["approval_policy"], "")
        loaded = store.load(("ou_user", "oc_p2p"))
        assert loaded is not None
        self.assertEqual(loaded["approval_policy"], "")

    def test_store_keeps_empty_permissions_profile_id_empty(self) -> None:
        _, store, state_path = self._make_store()

        store.save(
            ("ou_user", "oc_p2p"),
            {
                "working_dir": "/tmp/p2p",
                "current_thread_id": "",
                "current_thread_title": "",
                "feishu_runtime_state": "",
                "approval_policy": "",
                "permissions_profile_id": "",
                "model": "",
                "reasoning_effort": "",
            },
        )

        raw = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["p2p_bindings"]["oc_p2p"]["ou_user"]["permissions_profile_id"], "")
        loaded = store.load(("ou_user", "oc_p2p"))
        assert loaded is not None
        self.assertEqual(loaded["permissions_profile_id"], "")
