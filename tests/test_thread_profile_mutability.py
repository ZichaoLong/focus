import unittest

from bot.thread_profile_mutability import (
    THREAD_RESUME_MUTABILITY_REASON_LOADED,
    THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED,
    check_thread_resume_memory_mode_mutable,
    check_thread_resume_profile_mutable,
    format_thread_resume_memory_mode_denial_for_feishu,
    format_thread_resume_memory_mode_denial_for_local_cli,
    format_thread_resume_profile_denial_for_feishu,
    format_thread_resume_profile_denial_for_local_cli,
)


class ThreadProfileMutabilityTests(unittest.TestCase):
    def test_loaded_thread_profile_denial_for_local_cli_names_instance_and_reset_command(self) -> None:
        check = check_thread_resume_profile_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        self.assertFalse(check.allowed)
        self.assertEqual(check.reason_code, THREAD_RESUME_MUTABILITY_REASON_LOADED)
        reason = format_thread_resume_profile_denial_for_local_cli(check, instance_name="explorer")
        self.assertIn("实例 `explorer` 的 backend", reason)
        self.assertIn("`fcodex resume`", reason)
        self.assertIn("`-p/--profile`", reason)
        self.assertIn("thread 级 next-load 设置", reason)
        self.assertIn("feishu-codexctl --instance explorer service reset-backend", reason)
        self.assertIn("/profile <name>", reason)

    def test_loaded_thread_memory_mode_denial_for_local_cli_is_memory_specific(self) -> None:
        check = check_thread_resume_memory_mode_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        self.assertFalse(check.allowed)
        self.assertEqual(check.reason_code, THREAD_RESUME_MUTABILITY_REASON_LOADED)
        reason = format_thread_resume_memory_mode_denial_for_local_cli(check, instance_name="explorer")
        self.assertIn("实例 `explorer` 的 backend", reason)
        self.assertIn("memory mode", reason)
        self.assertIn("thread 级 next-load 设置", reason)
        self.assertIn("feishu-codexctl --instance explorer service reset-backend", reason)
        self.assertIn("/memory <off|read|read_write>", reason)

    def test_runtime_unverified_profile_denial_for_local_cli_is_fail_closed(self) -> None:
        check = check_thread_resume_profile_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: False,
            list_loaded_thread_ids=lambda: (_ for _ in ()).throw(RuntimeError("backend down")),
        )

        self.assertFalse(check.allowed)
        self.assertEqual(check.reason_code, THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED)
        reason = format_thread_resume_profile_denial_for_local_cli(check, instance_name="default")
        self.assertIn("按 fail-close 拒绝", reason)
        self.assertIn("实例 `default` 的 backend", reason)
        self.assertIn("feishu-codexctl --instance default service reset-backend", reason)

    def test_loaded_thread_profile_denial_for_feishu_mentions_current_instance_reset_backend(self) -> None:
        check = check_thread_resume_profile_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        reason = format_thread_resume_profile_denial_for_feishu(check, instance_name="explorer")
        self.assertIn("实例 `explorer` 的 backend", reason)
        self.assertIn("thread-wise profile", reason)
        self.assertIn("thread 级 next-load 设置", reason)
        self.assertIn("/reset-backend", reason)

    def test_loaded_thread_memory_mode_denial_for_feishu_mentions_current_instance_reset_backend(self) -> None:
        check = check_thread_resume_memory_mode_mutable(
            "thread-1",
            unbound_reason="missing",
            has_runtime_lease=lambda _thread_id: True,
            list_loaded_thread_ids=lambda: [],
        )

        reason = format_thread_resume_memory_mode_denial_for_feishu(check, instance_name="explorer")
        self.assertIn("实例 `explorer` 的 backend", reason)
        self.assertIn("thread-wise memory mode", reason)
        self.assertIn("thread 级 next-load 设置", reason)
        self.assertIn("/reset-backend", reason)


if __name__ == "__main__":
    unittest.main()
