import unittest

from bot.thread_memory_mode import build_thread_memory_config_override


class ThreadMemoryModeTests(unittest.TestCase):
    def test_build_thread_memory_config_override_only_writes_top_level_memories(self) -> None:
        override = build_thread_memory_config_override(
            "read_write",
            profile_name_hint="provider2",
        )

        self.assertEqual(
            override,
            {
                "memories": {
                    "use_memories": True,
                    "generate_memories": True,
                }
            },
        )
        self.assertNotIn("profiles", override)
