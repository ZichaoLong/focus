import unittest

from bot.thread_profile_mutability import (
    THREAD_RESUME_MEMORY_MODE_LOADED_REASON,
    THREAD_RESUME_PROFILE_LOADED_REASON,
    check_thread_resume_memory_mode_mutable,
    check_thread_resume_profile_mutable,
)


class ThreadProfileMutabilityTests(unittest.TestCase):
    def test_loaded_thread_denial_text_guides_attach_vs_reprofile(self) -> None:
        can_write, reason = check_thread_resume_profile_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        self.assertFalse(can_write)
        self.assertEqual(reason, THREAD_RESUME_PROFILE_LOADED_REASON)
        self.assertIn("不能同时携带 `-p/--profile`", reason)
        self.assertIn("去掉 `-p/--profile`", reason)
        self.assertIn("verifiably globally unloaded", reason)
        self.assertIn("/profile <name>", reason)
        self.assertIn("feishu-codexctl service reset-backend", reason)

    def test_loaded_thread_memory_mode_denial_text_is_memory_specific(self) -> None:
        can_write, reason = check_thread_resume_memory_mode_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        self.assertFalse(can_write)
        self.assertEqual(reason, THREAD_RESUME_MEMORY_MODE_LOADED_REASON)
        self.assertIn("memory mode", reason)
        self.assertIn("/memory <off|read|read_write>", reason)
        self.assertIn("feishu-codexctl service reset-backend", reason)


if __name__ == "__main__":
    unittest.main()
