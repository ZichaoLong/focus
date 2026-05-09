import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

from bot.managed_skills.feishu_scheduled_prompts.skill.scripts.manage_scheduled_prompt import (
    ScheduledTaskSpec,
    create_task,
    list_specs,
    normalize_task_id,
    render_service_unit,
    render_timer_unit,
    scheduled_task_root,
    service_unit_path,
    show_task,
    systemd_user_dir,
    task_dir,
    timer_unit_path,
)


class ScheduledPromptSkillTests(unittest.TestCase):
    def test_normalize_task_id_rejects_invalid_characters(self) -> None:
        with self.assertRaises(ValueError):
            normalize_task_id("Bad Task")

    def test_rendered_units_route_back_through_prompt_send(self) -> None:
        spec = ScheduledTaskSpec(
            task_id="ashare-close",
            instance="explorer",
            binding_id="group:chat-1",
            on_calendar="Mon..Fri 15:25",
            description="A-share close recap",
            prompt_file="/tmp/prompt.txt",
            ctl_path="/home/tester/.local/bin/feishu-codexctl",
            synthetic_source="schedule",
            display_mode="silent",
            created_at="2026-05-09T00:00:00+00:00",
        )

        service = render_service_unit(spec)
        timer = render_timer_unit(spec)

        self.assertIn("prompt send", service)
        self.assertIn("--binding-id", service)
        self.assertIn("OnCalendar=Mon..Fri 15:25", timer)
        self.assertIn("Persistent=true", timer)

    def test_create_task_writes_metadata_prompt_and_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            prompt_file = root / "prompt.txt"
            prompt_file.write_text("继续明天的分析\n", encoding="utf-8")
            args = types.SimpleNamespace(
                task_id="morning-follow-up",
                instance="explorer",
                binding_id="p2p:ou_user:chat-1",
                on_calendar="2026-05-10 09:35",
                prompt_file=str(prompt_file),
                description="Morning follow-up",
                synthetic_source="schedule",
                display_mode="announce",
                ctl_path="/home/tester/.local/bin/feishu-codexctl",
            )
            systemctl_calls: list[tuple[str, ...]] = []

            def _fake_systemctl(*args: str, check: bool = True):
                del check
                systemctl_calls.append(args)
                return types.SimpleNamespace(stdout="", stderr="")

            with patch.dict(
                "os.environ",
                {
                    "XDG_DATA_HOME": str(root / "xdg-data"),
                    "XDG_CONFIG_HOME": str(root / "xdg-config"),
                },
                clear=False,
            ):
                with patch(
                    "bot.managed_skills.feishu_scheduled_prompts.skill.scripts.manage_scheduled_prompt._run_systemctl",
                    side_effect=_fake_systemctl,
                ):
                    result = create_task(args)

                self.assertEqual(result, 0)
                self.assertEqual(
                    systemctl_calls,
                    [
                        ("daemon-reload",),
                        ("enable", "feishu-codex-scheduled-morning-follow-up.timer"),
                        ("start", "feishu-codex-scheduled-morning-follow-up.timer"),
                    ],
                )
                self.assertTrue((scheduled_task_root() / "morning-follow-up" / "task.json").exists())
                self.assertTrue((scheduled_task_root() / "morning-follow-up" / "prompt.txt").exists())
                self.assertTrue(service_unit_path("morning-follow-up").exists())
                self.assertTrue(timer_unit_path("morning-follow-up").exists())
                specs = list_specs()
                self.assertEqual(len(specs), 1)
                self.assertEqual(specs[0].binding_id, "p2p:ou_user:chat-1")

    def test_show_task_reads_stored_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            with patch.dict(
                "os.environ",
                {
                    "XDG_DATA_HOME": str(root / "xdg-data"),
                    "XDG_CONFIG_HOME": str(root / "xdg-config"),
                },
                clear=False,
            ):
                task_dir("daily").mkdir(parents=True, exist_ok=True)
                (scheduled_task_root() / "daily" / "task.json").write_text(
                    """
{
  "task_id": "daily",
  "instance": "explorer",
  "binding_id": "group:chat-1",
  "on_calendar": "Mon..Fri 15:25",
  "description": "Daily recap",
  "prompt_file": "/tmp/prompt.txt",
  "ctl_path": "/tmp/feishu-codexctl",
  "synthetic_source": "schedule",
  "display_mode": "silent",
  "created_at": "2026-05-09T00:00:00+00:00"
}
""".strip()
                    + "\n",
                    encoding="utf-8",
                )

                self.assertEqual(show_task("daily"), 0)


if __name__ == "__main__":
    unittest.main()
