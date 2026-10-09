from dataclasses import replace
from unittest.mock import Mock

from bot.adapters.base import ThreadSnapshot
from bot.web_runtime.contract import WebRuntimeError
from tests.web_runtime.harness import WebRuntimeControllerHarness


class WebThreadForkTests(WebRuntimeControllerHarness):
    def prepare_fork(self, new_id="fork-1"):
        branch = replace(self.fake.summary(), thread_id=new_id, ephemeral=False)

        def fork(thread_id):
            self.assertEqual(thread_id, "thread-1")
            self.fake.extra_summaries.append(replace(branch))
            return ThreadSnapshot(
                summary=branch, turns=[], effective_model="model-a",
                effective_approval_policy="never", effective_permissions_profile_id=":workspace",
            )

        def rename(thread_id, name):
            self.assertEqual(thread_id, new_id)
            self.fake.summary_for(thread_id).name = name

        self.fake.fork_thread = Mock(side_effect=fork)
        self.fake.rename_thread = Mock(side_effect=rename)
        return branch

    def test_fork_creates_named_persistent_session_without_prompt_or_parent_selection_change(self):
        self.controller.meta("tab-1")
        original = self.profile_store.load("tab-1")
        branch = self.prepare_fork()
        result = self.controller.fork_thread("tab-1", "thread-1")
        self.assertEqual(result, {
            "accepted": True, "thread_id": "fork-1", "source_thread_id": "thread-1", "name_warning": "",
        })
        self.fake.fork_thread.assert_called_once_with("thread-1")
        self.fake.rename_thread.assert_called_once_with("fork-1", "Demo · 分支 fork-1")
        self.assertEqual(branch.name, "Demo · 分支 fork-1")
        self.assertEqual(self.fake.summary().name, "Demo")
        self.assertEqual(self.fake.started, [])
        self.assertEqual(self.profile_store.load("tab-1"), original)
        self.assertIsNone(self.store.load("thread-1"))
        self.assertIsNone(self.store.load("fork-1"))
        listing = self.controller.list_threads(client_id="tab-1", scope="global")
        listed = next(t for t in listing["threads"] if t["id"] == "fork-1")
        self.assertEqual(listed["name"], "Demo · 分支 fork-1")

    def test_fork_name_uses_display_title_when_source_has_no_explicit_name(self):
        for preview, title in (("First question", "First question"), ("", "（无标题）")):
            with self.subTest(preview=preview):
                source = replace(self.fake.summary(), name="", preview=preview)
                self.fake.read_thread = Mock(return_value=ThreadSnapshot(summary=source))
                branch = self.prepare_fork(f"fork-{len(self.fake.extra_summaries)}")
                self.controller.fork_thread("tab-1", "thread-1")
                self.fake.rename_thread.assert_called_once_with(
                    branch.thread_id, f"{title} · 分支 {branch.thread_id}",
                )
                self.assertEqual(source.name, "")

    def test_nearby_uuidv7_forks_use_different_id_suffixes(self):
        names = []
        for new_id in (
            "019aa042-f752-7862-b44a-94554fe28027",
            "019aa042-f752-75eb-86d2-614350a6f9d0",
        ):
            branch = self.prepare_fork(new_id)
            self.controller.fork_thread("tab-1", "thread-1")
            names.append(branch.name)
        self.assertEqual(names, ["Demo · 分支 4fe28027", "Demo · 分支 50a6f9d0"])

    def test_rename_failure_keeps_created_branch_and_never_retries_either_effect(self):
        for error, applied in (
            (ValueError("rejected"), False),
            (TimeoutError("response lost"), False),
            (TimeoutError("response lost"), True),
        ):
            with self.subTest(error=type(error), applied=applied):
                branch = self.prepare_fork(f"fork-{len(self.fake.extra_summaries)}")

                def rename(thread_id, name):
                    if applied:
                        self.fake.summary_for(thread_id).name = name
                    raise error

                self.fake.rename_thread.side_effect = rename
                with self.assertLogs("bot.web_runtime.thread_create_coordinator", level="WARNING"):
                    result = self.controller.fork_thread("tab-1", "thread-1")
                self.assertTrue(result["accepted"])
                self.assertEqual(result["thread_id"], branch.thread_id)
                self.assertIn(branch.thread_id, result["name_warning"])
                self.assertIn("rename it manually", result["name_warning"])
                self.fake.fork_thread.assert_called_once_with("thread-1")
                self.fake.rename_thread.assert_called_once_with(
                    branch.thread_id, f"Demo · 分支 {branch.thread_id}",
                )
                self.assertEqual(branch.name, "Demo")
                listing = self.controller.list_threads(client_id="tab-1", scope="global")
                listed = next(t for t in listing["threads"] if t["id"] == branch.thread_id)
                expected_name = f"Demo · 分支 {branch.thread_id}" if applied else "Demo"
                self.assertEqual(listed["name"], expected_name)
                self.assertEqual(self.fake.summary().name, "Demo")
                self.assertIsNone(self.store.load(branch.thread_id))

    def test_fork_unknown_is_not_retried_or_used_as_a_parent_mutation_fence(self):
        self.fake.fork_thread = Mock(side_effect=TimeoutError("response lost"))
        self.fake.rename_thread = Mock()
        with self.assertRaises(WebRuntimeError) as caught:
            self.controller.fork_thread("tab-1", "thread-1")
        self.assertEqual(caught.exception.code, "thread_fork_unknown")
        self.fake.fork_thread.assert_called_once_with("thread-1")
        self.fake.rename_thread.assert_not_called()
        self.assertIsNone(self.store.load("thread-1"))
        self.assertEqual(self.fake.started, [])

    def test_ephemeral_is_hidden_and_cannot_be_opened_or_forked_by_web(self):
        side = replace(self.fake.summary(), thread_id="side-1", ephemeral=True)
        self.fake.extra_summaries.append(side)
        self.fake.fork_thread = Mock()
        for scope in ("current", "global"):
            listing = self.controller.list_threads(client_id="tab-1", scope=scope)
            self.assertNotIn("side-1", [t["id"] for t in listing["threads"]])
        for action in (self.controller.read_thread, self.controller.fork_thread):
            with self.assertRaises(WebRuntimeError) as caught:
                action("tab-1", "side-1")
            self.assertEqual(caught.exception.code, "ephemeral_thread_unavailable")
        self.fake.fork_thread.assert_not_called()
